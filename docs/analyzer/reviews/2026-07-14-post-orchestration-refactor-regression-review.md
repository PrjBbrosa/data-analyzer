# 编排拆分后全面回归审查（2026-07-14）

**触发**：用户报告「最近一个大的架构拆分之后很多地方接线和逻辑都有问题，包括 hdf，之前是没问题的」。

**范围**：`8f18f480`（拆分前基线）→ `44df0ac1`（merge：`46e5cb84` unify analysis orchestration + `9034fc8a` preserve presets and restore zoom）。五个维度并行审查（FFT-vs-Time 迁移等价性 / Order+window 接线 / AnalysisJobService+缓存链路 / Inspector preset+滚轮 spec 落地 / HDF 链路 git 考古+offscreen 结构验证）+ 全量 pytest。

**方法**：旧版方法级逐条对照（`git show 8f18f480:<path>` vs HEAD）、全仓 grep 残留引用、getattr/hasattr 静默 no-op 排查、offscreen 真实文件节点计数、targeted 测试复核。

---

## 总结论

**「拆分造成大量回归」的判断不成立。** 编排拆分本身是一次高质量的忠实迁移：

- 全量 pytest **3351 passed, 8 skipped, 0 failed**。
- 旧 `_fft_time_mixin` 20 个方法逐一对照：数值/渲染/缓存键语义零漂移；`window.py` `_connect` 只增不减、无悬空连接；删除的 12+ 个旧派发字段/方法全仓生产代码零残留；8 处 getattr 防御式调用无一因改名变 no-op。
- 拆分还顺带修复了两处历史缺陷：worker 回调 `sender()` 的 macOS Bus-error（`_RunRelay` 结构性根治）、fft_time custom-X 的 stale-hit（`window.py:1865` 改清活动缓存）。
- `9034fc8a` 的 preset/zoom 补丁三段补齐，非只补出问题那段。

用户感知的问题**几乎全部来自更早的、与拆分正交的缺陷**（见「归因修正」）。

## 归因修正（用户报告的三个现象）

| 现象 | 真实归因 | 引入时间 |
|---|---|---|
| HDF 双轨没完全显示 | `loader.py` `load_hdf` 用 16 字符截断名当 dict 键 → 同名静默覆盖（1kHz 轨 19→15 通道，`Com_Motor_Torque`×4 中唯一有真数据的被全 0 覆盖）；另 factor=48 的 UINT32 通道整轨被丢且 `dropped_channels` UI 零暴露 | v1-latent（`fc910876`/`4e69195d`，2026-06-19）。该文件在 `4e69195d` 前根本打不开，从无「完整显示」的历史版本。UI 层经 offscreen 节点计数验证无二次丢失 |
| FFT 界面不自动识别 dB reference | navigator 勾选走 `_ch_changed`（window.py），FFT 分支不调 `_resolve_and_apply_db_reference('fft')`；代码自注 "Auto-resolve-on-selection-change is NOT yet wired"。图上曲线标签是对的（渲染路径现算），只是控件值/来源行不更新 | `8f18f480`（dB reference feature 本身的未完成接线），拆分未触碰 |
| MF4 `U_Nm`/`U_degYsec` 单位不识别 | 工具链标识符安全化改写（`U_` 前缀、`Y` 代 `/`）不匹配目录精确别名；扭矩类落 generic（dB re 1，数值正确）本属预期，代价是标签乱码 + 被同样改写的振动量（如 `mYs`）会错失 ISO 参考 | 目录设计与该工具链数据首次相遇，非回归 |

## 拆分新引入的问题（全部 low ~ low-med）

| # | 问题 | 位置 | 严重度 | 确信度 |
|---|---|---|---|---|
| N1 | `close_all` 绕过 `_invalidate_all_analysis_caches_for_fid`，只清缓存不清 `FftTimeCoordinator._pending` → 关全部文件时 in-flight fft_time 完成回调把死 fid 结果写回刚清空的缓存并渲染过期热图。与单文件关闭不对称 | `_project_io_mixin.py:796` vs `fft_time_coordinator.py:133` | low-med | confirmed |
| N2 | 单源 legacy 路径（无捕获源）首算现在会弹计算进度条（旧版只有 statusBar 文案） | `_fft_time_mixin.py:323`（`batch_started` 无条件 `_begin_compute_progress`） | low | confirmed |
| N3 | 多 pane 缓存命中逐个刷 statusBar（旧版只有末尾汇总） | `_fft_time_mixin.py:547-576` | low | confirmed（cosmetic） |
| N4 | 上游 skip 原因文案粒度下降（prepared=None 统一「源通道缺失或样本不足」） | `_fft_time_mixin.py:236` | low | confirmed |
| N5 | 死分支（`do_fft_time` 不可达 else）+ `test_main_window_smoke.py:2057` docstring 残留旧方法名 | `_fft_time_mixin.py:265-272` | low | confirmed |

## 既有限制（被拆分暴露但非其引入）

- **cancel/replace 是生产死代码**：`AnalysisJobService.cancel()` 仅 `submit_batch(replace=True)` 调用，而全仓生产代码无一处传 `replace=True`，也无用户取消按钮。计算中关文件/切文件不取消 in-flight worker；order 完成回调无 fid 守卫会把死 fid 结果写回缓存——新旧等价。
- Order 单源路径 build 失败（如缺转速）静默无 toast——旧版等价。
- `dropped_channels`（HDF 被丢通道）全 UI 无消费点。

## 治理债 / 脆弱边界（当前正确，未来易断）

- 批次终结逻辑寄生在 progress 信号（`done==total and not is_running`），无独立完成信号；任何让 worker 静默退出的未来改动会让进度条永久卡住。
- 完成/失败路由是手写 section 白名单（window 只认 `'order'`，coordinator 只认 `'fft_time'`）：未来第三个 section 的结果会被双向静默吞掉。
- Order 缺 coordinator 抽象（与 fft_time 不对称）。**注意**：memory 所记「Phase2(Order/FFT) 留待后续」与代码不符——Order 的 worker 编排本 commit 已完全迁移，未做的只是 coordinator 层。
- 滚轮真事件测试缺口：line 缺 Shift、heatmap 缺 Ctrl 用例（lesson 要求 both×both）。

## 建议修复顺序

1. **HDF 同名覆盖**（高：错误数据）——`load_hdf` 重名按序号加后缀去重 + `dropped_channels` toast 暴露。
2. **FFT 勾选 → dB auto 接线**（中）——`_ch_changed` FFT 分支 + `_enter_fft_mode` 补 `_resolve_and_apply_db_reference('fft')`。
3. **N1 close_all pending**（low-med，一行级）——close_all 改走 per-fid invalidate 或额外清 coordinator pending。
4. **MF4 单位还原层**（中）——方案 C：facts 边界纯函数（剥 `U_` 前缀、字母间大写 Y→`/`），不动 `normalize_unit` 精确匹配内核。
5. N2-N5 及测试缺口可顺手或暂缓；治理债待 Phase2 一并处理。

## 实施记录（2026-07-14，TDD 全程 RED→GREEN）

前 4 项已修复（每项先写失败测试再实现）：

1. **HDF 同名覆盖** — `loader.py` `load_hdf` 组内按文件内 1-based 序号去重（首次出现保原名，碰撞加 `[idx]`）；新增纯函数 `format_dropped_channels_notice`，`_project_io_mixin.py` hdf 分支加载后 toast 提示被丢通道。真实文件验证：1x 轨 15→19 通道，`Com_Motor_Torque [19]` 保住真扭矩 [-4.22,4.62]，dropped 提示 "1 个通道未导入：CAN 1@SQuadriga"。测试 `test_head_hdf_loader.py`（+去重/唯一名/dropped 3 例）。
2. **FFT 勾选 → dB auto** — `window.py` `_ch_changed` FFT 分支 + `_enter_fft_mode` 各补 `_resolve_and_apply_db_reference('fft')`（rerender=False，只刷识别不重算）。测试 `test_main_window_smoke.py`（勾选触发 + 进模式触发 2 例）。
3. **N1 close_all pending** — `FftTimeCoordinator.invalidate_all()`（清 cache + pending）；`_project_io_mixin.py` `close_all` 调用它。测试 `test_task4_cache_invalidation.py`。
4. **MF4 单位还原（方案 C）** — `db_reference.canonicalize_source_unit`（剥 `U_` 前缀 + 字母间大写 `Y`→`/`，不动 `normalize_unit`）；`_analysis_mixin` + `batch.py` 两个 facts 边界应用。`U_Nm→Nm`、`U_degYsec→deg/sec`、`mYs2→m/s2`（振动量重新命中 acceleration 1e-6）。测试 `test_db_reference.py` + `test_main_window_smoke.py` + `test_batch_weighting.py`。

改动 7 生产 + 5 测试文件（+344/-14）。改动涉及测试文件 71+104 绿；全量回归见 git 提交前最终验证。N2-N5、治理债、测试覆盖缺口未动。
