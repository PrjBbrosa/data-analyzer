# 批处理性能优化设计（惰性加载 + 去除 pivot 往返）

日期：2026-06-20
分支：`codex/multi-entry-sync`
来源：本会话对 `mf4_analyzer/batch.py` + `ui/drawers/batch/` 的只读审计
执行：`signal-processing-expert`（sonnet 模型），TDD-first

## 背景

批处理逻辑与连线经多轮迭代后整体正确（116/116 测试通过），但通读源码发现两处**净收益、低风险**的性能浪费：

1. **`run()` 前全量加载磁盘文件**。`run()` 里 `tasks = list(self._expand_tasks(...))`（`batch.py:181`），而 `_expand_tasks` 又 `files_iter = list(self._resolve_files(...))`（`batch.py:331`）。后果：批处理一批 `file_paths`（磁盘上、尚未注册到 main_window 的文件）时，**第 1 个任务还没跑、所有文件已全部读进内存**——启动延迟与内存峰值随文件数线性增长。而 UI 的进度总数/ETA 来自自己的 dry-run 预览（`sheet.py:525-527`，明确「no disk loads」），**不依赖** runner 这次全量 load；`list()` 仅为了让两段式 `_expand_tasks` 能迭代两遍。

2. **谱图导出的 `matrix → long → pivot` 往返**。`_compute_{order_time,fft_time}_dataframe` 用 `np.repeat/np.tile` 把矩阵摊平成长表（`batch.py:715-726`），`_write_image` 再 `df.pivot(...)` 还原回矩阵画图（`batch.py:655-658`）。即便**只导图不导数据**，也照样摊平再还原。谱图是 frames×bins 级，这趟往返白烧内存和时间。

## 范围

- **P0-A（去 pivot 往返）**：新增矩阵优先的内部结果载体 `_Spectro2D`；compute 直接产出它；`_write_image` 对热图直接吃矩阵（不再 pivot）；长表仅在 `export_data=True` 时按需构造。
- **P0-B（惰性加载 + 逐文件驱逐）**：`target_signals` 路径下 `_expand_tasks` 产出延迟任务元组 `(file_key, ch)`（**不**触发加载）；`run()` 逐任务解析+加载磁盘文件，并在转入下一个文件时从 `_disk_cache` 驱逐上一个（任务是 file-major，单磁盘文件常驻内存 ≤1）。

## 非目标

- **不引入并行**（多进程/线程池跑任务）。当前「确定性顺序 + 简单取消」是有意取舍，并行属更大改动，本轮不碰。
- **不改 `pattern`（`signal_pattern`）枚举路径**。它需要逐文件读通道名才能枚举，无法惰性化；且 UI 永不产出 pattern 模式（`sheet.get_preset` 始终走 `free_config(target_signals=...)`）。pattern 是 legacy/测试路径，保持现状。
- **不改 `current_single` 路径**、不改 `_write_dataframe` 的 CSV/xlsx 输出内容、不改 FFT（一维）的导出与绘制。
- **不动 UI**（`ui/drawers/batch/*`、`sheet.py`、`runner_thread.py`）。本轮纯 `batch.py` + 其测试。
- **不改公开 tuple 契约**（`fft.py` 的 `one_sided_amplitude` 等）。`BatchRunner` 保持 GUI-free。

## 锁定决策

| 决策 | 内容 | 理由 |
|---|---|---|
| 保留旧方法名作薄包装 | `_compute_{order_time,fft_time}_dataframe` 改为 `return cls._compute_*_spectro(...).to_long_dataframe()` | `tests/test_batch_runner.py` 直接调这些方法 + `_matrix_to_long_dataframe`；薄包装让既有测试零改动（lesson `codex-order-batch-boundaries`：保留既有兼容） |
| `_Spectro2D.matrix` 为 x-major `(len(x), len(y))` | 与 `_matrix_to_long_dataframe(x, y, matrix)` 的既有约定一致 | 长表构造逻辑不变，CSV 输出**逐字节相同** |
| `_write_image` 热图用 `spectro.matrix.T` | imshow 要 `(rows=y, cols=x)`；可证 `pivot.to_numpy() == matrix.T` | 渲染矩阵与原 pivot **完全等价**（lesson `2026-06-11-slice-must-read-same-display-matrix-as-heatmap`）；COT/谱图轴本就升序，pivot 的排序是 no-op |
| 长表仅 `export_data` 时构造 | `_run_one` 仅图导出时不再建长表 | 直接省掉只导图场景的整趟摊平+pivot |
| 惰性只覆盖 `target_signals` | 该模式任务集 = `(file_ids ∪ file_paths) × target_signals`，无需加载即可枚举 | 这是唯一的 UI 路径；任务集与事件流**计数/顺序均不变**，仅去掉预加载 |
| 保留「全已加载且无一匹配 → blocked」 | 新增 `_any_target_could_match`：已加载文件查真实列，磁盘路径乐观假定可能匹配（逐任务再验） | 保住既有 `blocked: ['no matching batch tasks']` 语义（已加载场景），磁盘场景下未命中信号改以逐任务 `task_failed` 呈现（同为最终 blocked，信息更细） |
| 逐文件驱逐 `_disk_cache` | 转入不同文件时 `pop` 上一磁盘 key；循环末尾再 pop 收尾；**绝不**驱逐 `self.files`（main_window 所有） | 任务 file-major → 单磁盘文件常驻 ≤1，内存封顶 |

## 契约（执行者必须满足）

**`_Spectro2D`（模块级 `@dataclass(frozen=True)`）**
- 字段：`x: np.ndarray`、`y: np.ndarray`、`matrix: np.ndarray`（shape `(len(x), len(y))`）、`x_name: str`、`y_name: str`
- 方法：`to_long_dataframe() -> pd.DataFrame` == `_matrix_to_long_dataframe(self.x, self.y, self.matrix, self.x_name, self.y_name)`

**compute（`BatchRunner` classmethod）**
- 新增 `_compute_order_time_spectro(sig, rpm, time, fs, params) -> _Spectro2D`（`x=times, y=orders, matrix=amplitude`）
- 新增 `_compute_fft_time_spectro(sig, time, fs, params, *, channel_name='') -> _Spectro2D`（`x=times, y=frequencies, matrix=amplitude.T`）
- `_compute_order_time_dataframe` / `_compute_fft_time_dataframe`：保留签名，改为薄包装委托 `*_spectro().to_long_dataframe()`
- `_compute_fft_dataframe`：**不变**

**`image_payload` 形状（`_run_one` → `_write_image`）**
- FFT：`('fft', fft_df)`（一维 `[frequency_hz, amplitude]`，不变）
- 热图：`('order_time'|'fft_time', spectro)`（`_Spectro2D`，**取代**原来的长表 df）
- `_write_image` 热图分支：`matrix = spectro.matrix.T`；`extent=[x.min, x.max, y.min, y.max]`；轴标签用 `spectro.x_name/y_name`；db/vmin/vmax 逻辑不变

**惰性加载（`run()` + `_expand_tasks`）**
- `target_signals` 任务元组 = `(file_key, signal_name)`；`file_key` ∈ `file_ids ∪ file_paths`（无则回退 `self.files` 全集）；枚举**不调 loader**
- 新增 `_resolve_task_file(file_key) -> (fid, fd_or_failure)`：注册 fid → live `FileData`；磁盘路径 → `_loader` 加载并缓存进 `_disk_cache`（失败存 `_LoadFailure`）
- 新增 `_any_target_could_match(file_keys, target_signals) -> bool`
- `run()` 循环改吃 2 元组、逐任务解析、逐文件驱逐；既有 per-task `task_started/done/failed`、cancel、`progress_callback` 仅 `task_done` 触发等语义**全部保持**

## 测试影响

主测试文件 `tests/test_batch_runner.py`（直接调 `_expand_tasks`/`_write_image`/`_matrix_to_long_dataframe`/`_compute_order_time_dataframe`）+ `tests/ui/test_order_smoke.py`（调 `_expand_tasks`）。

- 旧名薄包装 + `_matrix_to_long_dataframe` 不变 → 既有直调测试应保持绿。
- `_expand_tasks` 返回元组从 3 元组 `(fid, fd, ch)` 变 2 元组 `(file_key, ch)`：**直接解包 `_expand_tasks` 结果的测试需同步更新**（TDD：先改/加期望测试）。
- 新增测试（执行者写）：
  1. `_compute_order_time_spectro` / `_compute_fft_time_spectro` 的 `matrix` 与对应长表 `to_long_dataframe()` 互证一致。
  2. `_write_image` 热图渲染矩阵 == 旧 pivot 矩阵（`spectro.matrix.T`）。
  3. 只导图（`export_image=True, export_data=False`）时**不构造长表**（spy/计数）。
  4. 惰性：带间谍 `loader` 的多 `file_paths` 批跑，断言 loader **逐任务**调用（非 run 前全量）、且 `_disk_cache` 同时驻留 ≤1 项。
  5. 「全已加载且 target_signals 无一匹配」仍得 `blocked`（保语义）。

## 性能边界

- 仅改批处理（离线、低频、用户显式触发），不进任何每帧/重绘热路径。
- `_Spectro2D` 不复制大数组（持有 compute 已分配的矩阵引用）；按 lesson `2026-04-26` 不新增谱图尺寸的中间缓冲。
- 惰性路径净减分配（不再 `list()` 全量 FileData）；驱逐把磁盘批的内存从 O(文件数) 降到 O(1)。

## 验收

- `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -k batch -q` 全绿，且新增 5 项测试通过。
- 回归：`.venv/bin/python -m pytest tests/test_batch_runner.py -q` 全绿。
- 全套冒烟（执行者最后跑一遍）：`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`。
