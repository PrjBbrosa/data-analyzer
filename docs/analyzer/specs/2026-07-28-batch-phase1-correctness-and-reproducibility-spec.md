# 批处理 Phase 1：正确性与可复现性 Spec

- 日期：2026-07-28
- 状态：已实施；C1–C10 PASS
- 依赖：现有 `AnalysisPreset` / `BatchRunner` / `BatchSheet` 与 dB-reference 契约
- 后续：Phase 2 在本阶段 recipe 契约上扩展能力；Phase 3 在本阶段输出身份与渲染接口上扩展交付格式

## 1. Outcome

本阶段不追求新增大量控件，先让批处理成为可信的分析执行器：同一份文件、同一组参数、同一算法版本必须得到可解释、不会被静默改写、不会互相覆盖的结果。

完成后必须满足：

1. “从当前分析填入 → BatchSheet → 运行/导出 preset”不再丢失参数，也不把 Auto NFFT、Linear、dB Auto 等状态悄悄改成另一种配置。
2. `BatchRunner` 继续无 GUI 依赖，worker 线程不创建 `QApplication`、QWidget、pyqtgraph scene 或其他 GUI 对象。
3. 非法时间范围、采样率、Nyquist/频率范围、RPM 配置和轴范围在运行前或单任务开始前给出明确错误，不再静默回退。
4. 两个来源即使 basename、通道名和方法相同也不会覆盖彼此；写文件失败时不留下伪装成成功结果的半文件。
5. FFT dB 与单帧热图的极端输入能得到有限、可见的图，不出现 `-6000 dB` 量级的自动范围或零宽 scene。

## 2. Confirmed Baseline

| 事实 | 当前锚点 | 风险 |
| --- | --- | --- |
| `AnalysisPreset.params` 是开放 dict，但 BatchSheet 只保留少量白名单 passthrough | `mf4_analyzer/ui/drawers/batch/sheet.py` | 新增/隐藏参数很容易再次丢失 |
| `get_preset()` 始终重建为 `free_config` | `BatchSheet.get_preset()` | current-single 意图与精确 `(fid, channel)` 可能丢失 |
| MainWindow 优先使用 `_last_batch_preset` | `MainWindow.open_batch()` | 旧分析动作留下的最小参数可能覆盖当前 Inspector 状态 |
| worker 内调用 `_build_export_scene()`，其内部创建 Qt application/scene | `BatchRunnerThread.run()`、`batch.py` | GUI 对象跨线程，平台相关崩溃或未定义行为 |
| 图片固定 1120×630，直接写目标路径 | `BatchRunner._write_image()` | 不高清；同名覆盖；中途失败可能留下半文件 |
| 输出 stem 只含 short name、signal、method，且非 ASCII 被折叠 | `_safe_stem()` | 同 basename/中文名碰撞 |
| 时间范围文本解析失败返回 `None` | `InputPanel.time_range()` | 用户输入错误被解释为“全时段” |
| dB 线图直接对极小幅值取对数后自动范围 | `_build_export_scene()` | 零信号压扁可见曲线 |
| 热图 rectangle 由中心点差值直接构造 | `_build_export_scene()` | 单 frame/bin 时宽或高为 0 |

## 3. Scope

### 3.1 Recipe round-trip

新增一个纯 Python 的 recipe 规范化层，负责字段归属、迁移、验证和稳定序列化。`BatchSheet` 不再依赖“可见控件字段 + 手写 passthrough 白名单”来决定哪些字段应该保留。

每个方法至少完整保留下列字段：

- 通用：`fs`、`time_range`、`filter`、X/Y/Z 轴 auto/range、`amplitude_mode`、`weighting`、`db_reference`、`db_reference_mode`。
- FFT：`window`、`nfft`、`nfft_mode`、`t_win_s`、`overlap`、`avg_mode`、`avg_overlap`、`amp_y`。
- FFT-vs-Time：`window`、`nfft`、`nfft_mode`、`t_win_s`、`overlap`、`remove_mean`。
- Order：`window`、`nfft`、`nfft_mode`、`max_order`、`order_res`、`time_res`、`rpm_mode`、`manual_rpm`、`samples_per_rev`、`rpm_factor`。

字段暂时没有 UI 控件时仍必须原样保留；仅在用户切换到另一个方法时，按明确的 method schema 删除确定不兼容的字段。

### 3.2 Current-state ownership

- 打开批处理时，权威输入是调用当下的 Inspector / pane-local analysis state。
- `_last_batch_preset` 不再作为覆盖当前状态的第二权威来源。若保留该字段，只能作为兼容缓存，并且必须由完整 recipe 构造、按 section/view/source identity 校验后使用。
- `current_single` 被填入对话框后，若用户没有扩大文件/通道范围，运行 recipe 保留精确 source intent；一旦用户主动修改为多文件/多信号，显式转换为 `free_config`。
- 时域当前选择保留精确 `(file_id, channel)` 配对，不以文件集合 × 信号名集合制造用户未选择的任务。为兼容旧 preset，旧 cartesian 语义仍可读取。

### 3.3 Validation

验证分两层：

- UI/preflight：在“运行”前返回所有可发现问题，禁用运行并展示具体字段。
- runner/task：对磁盘加载后才知道的 Fs、Nyquist、通道长度、RPM 等再次验证；不相信 UI。

至少覆盖：

- `time_range` 必须是两个有限数且 `start < end`；裁剪后至少 2 个有效样本。
- `fs` 必须有限且大于 0；显式 `fs` 与文件推导值的选择写入运行事实。
- 固定 NFFT 为合法整数；Auto NFFT 不在 UI 往返时固化为 1024。
- X/Y/Z 手动范围均要求有限且 min < max；线性幅值允许负 Y，不能沿用 0..1e9 的通用限制。
- 频率范围不得超出有效 Nyquist；滤波被 Nyquist guard 钳制时保留 message。
- Order channel 模式要求 RPM channel；Manual 模式要求正的 manual RPM；跨文件 RPM 必须按 source identity 解析。
- 输出目录可创建且容量检查为警告/阻断事实，不以估算值伪装精确值。

### 3.4 Output identity and atomic writes

每个任务拥有稳定 `task_id`，由下列规范化字段哈希生成：

```text
source identity + group identity + channel identity + method + normalized recipe
```

人类可读文件名格式：

```text
{source_stem}__{group_slug}__{channel_slug}__{method}__{task_hash8}.{ext}
```

- Unicode 名称保留可读字符，只替换路径非法字符；不得把所有中文折叠为 `_`。
- Phase 1 的既有调用默认冲突策略为 `auto_number`，绝不静默覆盖。
- 数据和图片先写同目录临时文件，flush/close 成功后 `os.replace()` 到最终路径。
- `BatchItemResult` 记录 `task_id`、source/group identity、最终路径、有效参数和 warnings；Phase 3 再把这些事实汇总成 manifest。

### 3.5 GUI-free renderer boundary

建立 `mf4_analyzer/batch_render.py`（名称可在实施时微调）的纯渲染边界：

- 输入只含 numpy array、标量、字符串与不可变 render options。
- 使用无 GUI backend（优先 Matplotlib `Figure` + Agg canvas）生成 PNG；不得创建 `QApplication`、QWidget、QGraphicsScene 或 pyqtgraph widget。
- `BatchRunner` 负责数值与输出调度，不 import PyQt。
- Phase 1 默认像素仍可保持 1120×630，以隔离渲染线程修复；尺寸与矢量格式在 Phase 3 扩展。
- dB 转换复用唯一生产 helper；对零/非有限幅值使用与交互式 FFT 一致的有限 floor 和 robust 自动 Y 范围。
- 热图 extent 使用 frame/bin 覆盖边界而不是中心点差；单 frame/bin 用有效半步或稳定 fallback 构造非零面积。

### 3.6 Cancellation and task lifecycle

- 取消 token 在 load、preprocess、compute、data write、image render/write 各阶段前后检查。
- 当前不可中断的第三方数值调用允许完成当前 stage，但取消后不得继续写后续产物。
- `task_started` 之后必须恰好产生 done/failed/cancelled 之一；run 必须恰好产生一个 `run_finished`。

## 4. Compatibility

- 旧 batch preset JSON 继续可读；有 `db_reference` 无 mode 仍迁移为 Manual。
- 新 recipe 的未知字段在安全的 dict 边界中保留，已知字段做类型规范化；不得因为旧 UI 不认识字段就删除。
- CSV/XLSX 数值继续保持线性，dB reference 只影响图像显示和标签。
- 保留 file-major 惰性加载、只导图不构造长表和 `_Spectro2D` matrix-first 路径。

## 5. Non-goals

- 本阶段不扩展磁盘文件格式列表；见 Phase 2。
- 本阶段不新增内置 batch presets 或完整参数编辑控件；只保证现有/导入参数不丢。
- 本阶段不改变用户默认导出分辨率和格式；见 Phase 3。
- 不并行执行多个数值任务。

## 6. Acceptance Criteria

| ID | 验收 |
| --- | --- |
| C1 | 三个分析方法和时域的 current params 经 `build → apply → get/export → load` 后，规范化 recipe 等价 |
| C2 | Auto NFFT、Linear、`db_reference_mode=auto`、Welch、manual RPM 等不被默认控件改写 |
| C3 | stale `_last_batch_preset` 不能覆盖当前 pane/view Inspector 参数 |
| C4 | malformed/reversed/NaN time range 不再变成全段运行；错误包含字段名 |
| C5 | 非法 Fs/Nyquist/轴范围/RPM 配置得到确定 blocked/failed 结果 |
| C6 | 同 basename、同 channel、不同 source/group 生成不同且稳定的路径 |
| C7 | 已存在文件不被默认覆盖；写入异常不留下最终半文件 |
| C8 | `mf4_analyzer/batch.py` 及 worker 渲染路径无 PyQt/pyqtgraph/QApplication 创建 |
| C9 | 零 FFT 的 dB 图 Y range 有限且合理；单 frame 热图具有非零 scene/figure bounds |
| C10 | cancel/event 状态机无 started-without-terminal 事件 |

## 7. Verification

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_batch_runner.py \
  tests/test_batch_preset_io.py \
  tests/ui/test_batch_smoke.py \
  tests/ui/test_batch_runner_thread.py
```

另需执行：

- 两个同 basename/不同目录或 group 的真实写盘 probe；
- 生成零信号 FFT dB 与单 frame heatmap PNG，读取像素尺寸并检查非空内容；
- `rg -n "PyQt|pyqtgraph|QApplication" mf4_analyzer/batch.py mf4_analyzer/batch_render.py`，生产路径应无命中。

## 8. Implementation Result — 2026-07-28

C1–C10 全部 PASS。独立验收：core `175 passed`、Batch UI `110 passed`、compute-progress `25 passed`；`compileall` 与 `git diff --check` 通过。实现保留 file-major 惰性加载与线性数据导出语义，并把 worker 图片渲染迁移到 GUI-free 边界。
