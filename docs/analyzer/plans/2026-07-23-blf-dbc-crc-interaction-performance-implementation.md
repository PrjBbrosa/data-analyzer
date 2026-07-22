# BLF / DBC 导入与 CRC 时间域交互性能 — Implementation Plan

日期：2026-07-23
Spec：`docs/analyzer/specs/2026-07-23-blf-dbc-crc-interaction-performance-spec.md`
Review：`docs/analyzer/reviews/2026-07-23-recent-blf-dbc-channel-ui-review.md`

## Goal

按风险和依赖顺序关闭两类问题：先修正测试基线与 CRC 交互热路径，再优化 DBC 候选、导入顺序和进度真实性，最后做 Qt 离屏与前台实机验收。

不建议“三个阶段同时改完再一起测”。当前工作树已经混有多类未提交改动；本计划使用小步、失败测试先行、分主题提交的方式，确保每层都能独立回滚和定位性能变化。

## Global Constraints

- 实施前完整阅读 spec、review 与本计划；以真实源码和当前工作树为准。
- 不覆盖、不格式化、不删除用户已有的无关修改。
- 每个行为或性能任务先建立失败测试/基准，确认失败原因后再改生产代码。
- Qt item 创建、`PlotDataItem.setData()` 和 paint 留在 GUI 线程；后台线程只做纯数据工作。
- 显示 envelope 不能进入 cursor、统计、FFT、过滤或导出的数据源。
- 所有 async 结果携带 transaction/generation；旧结果必须丢弃。
- 进度只能单调前进，100% 只能在真实完成后出现。
- 每个 UI 改动都做 Qt 离屏几何/截图复核；最终性能必须追加前台实机证据。
- 不新增第三方依赖；优先使用现有 PyQt5、pyqtgraph、numpy、worker 和 progress 设施。
- 不自动 commit、push、merge 或清理工作树，等待用户明确授权。
- pytest 使用项目 venv：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest ...
```

## Stage 0 — Baseline、工作区保护与失败契约

### Task 0.1 — 固化当前状态

**Read**

- `docs/analyzer/reviews/2026-07-23-recent-blf-dbc-channel-ui-review.md`
- `docs/analyzer/specs/2026-07-23-blf-dbc-crc-interaction-performance-spec.md`
- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `mf4_analyzer/ui/pg_canvas/renderer.py`
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
- `mf4_analyzer/ui/pg_canvas/quality.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `mf4_analyzer/io/loader.py`

执行：

```bash
git status --short --branch
git diff --stat
git diff --check
```

记录已修改与未跟踪文件。后续每个 task 只触碰列出的 owned files。

### Task 0.2 — 复跑相关回归基线

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_channel_widget.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_timedomain_hotpath_perf.py
```

基线预期是审查时的 `12 failed, 381 passed, 1 deselected`。若数量变化，先分类，不把新失败吸收到优化任务里。

### Task 0.3 — 关闭旧测试契约债务

**Owned files**

- `tests/ui/test_channel_widget.py`
- 必要时仅修正直接相关的 fixture/helper

操作：

1. 让需要可操作通道的测试显式建立 View attachment；
2. 将 macOS 不稳定的 pre-show `QMessageBox.windowTitle()` 断言改为 show 后行为或创建参数断言；
3. 不降低产品侧 View attachment 约束；
4. 复跑 Task 0.2，目标 0 failures。

**Checkpoint 0**：在进入性能重构前，相关旧契约已全绿，避免后续无法区分回归来源。

## Stage 1 — CRC 诊断护栏与单次 envelope

### Task 1.1 — 增加真实形态的确定性 fixture

**Owned files**

- `tests/ui/test_high_variation_envelope.py`
- `tests/ui/test_timedomain_hotpath_perf.py`
- 可创建：`tests/fixtures` 下的小型生成 helper（不提交真实大型 BLF）

新增一个 5,727 点、0–255 离散域、与真实 `EPS_CRC1` transition 特征一致的合成 fixture。测试不得按通道名触发策略。

先写失败测试：

```python
def test_dense_discrete_profile_is_stable_across_full_and_zoomed_windows(): ...
def test_initial_bind_builds_dense_discrete_envelope_once(): ...
def test_dense_discrete_profile_preserves_raw_channel_array(): ...
def test_dense_discrete_settled_envelope_preserves_bucket_extrema(): ...
```

预期在当前代码上：窗口稳定性与单 pass 用例 FAIL。

### Task 1.2 — 抽出纯 `RenderProfile`

**Owned files**

- 建议创建：`mf4_analyzer/ui/pg_canvas/render_profile.py`
- Modify：`mf4_analyzer/ui/pg_canvas/renderer.py`
- Modify：`mf4_analyzer/ui/pg_canvas/overlay_axes.py`

实现纯函数：

```text
classify_render_profile(t, values, source_revision) -> RenderProfile
bucket_width_for(profile, mode, pixel_width, interactive) -> int
```

要求：

- 基于原始数组的有限采样/统计，不依赖 channel name/file type；
- 结果按 `(data_id, channel, data_revision)` 缓存；
- `dense_discrete` 在全范围和局部 viewport 保持一致；
- 先决定 width，再调用一次 envelope；
- raw arrays 原样留在 `channel_data`。

### Task 1.3 — 校准 bucket budget

对以下信号做视觉与数值对照：

- 真实形态 CRC / rolling counter；
- smooth sine；
- 高噪声连续物理量；
- 稀疏 digital state；
- 单尖峰与窄脉冲。

比较 250 / 350 / 500 bucket 的 Qt 截图、grab 耗时与 min/max 保真。默认保留现有 350，只有证据支持时才改常量。

同时必须对同一真实 fixture 分别测量 AA off、AA on + NoCache、AA on +
DeviceCoordinateCache。若 `dense_discrete` 的 AA paint 超出交互预算，即使
displayed point count 低于通用 density gate，也要硬拒绝 idle/export AA；
不得把点数 cap 误当成 AA 成本已经安全。

**Checkpoint 1**：CRC 策略稳定、首帧 single-pass、显示 envelope 与原始分析数据分离。

Checkpoint 1 还要求质量提示明确显示 high-raster-cost 阻断；smooth 低密度
信号仍能进入 idle AA，禁止用全局关闭 AA 代替几何策略。

### Task 1.4 — Dense-discrete 视觉平滑栅格层

原生 Qt AA 在真实 `EPS_CRC1` 上无法在保真前提下进入帧预算，
因此保留 AA hard gate，新增 single/subplot 最小可验证层：

- 以 settled buffer envelope 生成高分辨率透明 `QImage`；
- 使用非 AA cosmetic pen 的两遍亚像素偏移绘制，再平滑下采样；
- GUI 线程创建 `QPixmap` 并原子替换 data-coordinate item；
- 交互期间只作 ViewBox transform，100 ms settle 后按最新 X/Y range
  重生成；
- generation、DPR、size、color、visibility、data revision 均参与失效；
- 原 PDI 保留业务可见性和 data bounds，raster ready 后只抑制 vector pen；
- 位图尺寸为 `logical × max(2, DPR)`，DPR2 不再经历 4×→2× 的
  `QImage.scaled`；单项 16 MiB、全局 64 MiB，失败/超限回退
  native-AA-off PDI；
- overlay 本轮允许显式回退，但不得重开 native AA；
- 混合 subplot 按曲线后端分流：dense ready raster 的 PDI 不开 native AA，
  general smooth 仍按密度门禁开启；dense fallback 时继续全局硬阻断；
- quality status 区分“高分辨率缓存已完成”、“生成中”和
  “高光栅成本回退”。

为真实 fixture 生成 non-AA/raster 离屏对比图，并记录 QImage 生成、
QPixmap swap 与 transform-only 的 P50/P95。cursor/statistics/raw export 不得依赖
该位图。

## Stage 2 — 平移的 interactive / settled 双路径

### Task 2.1 — 替换错误的 setData 热路径测试契约

**Owned files**

- `tests/ui/test_pg_timedomain_canvas.py`
- `tests/ui/test_timedomain_hotpath_perf.py`

当前 `TestTimeDomainCanvasPGSetDataHotPathContract` 把“五个 distinct pan window 必须五次 `setData()`”锁成正确行为。先将它替换为新契约：

```python
def test_drag_range_events_reuse_existing_geometry_inside_buffer(): ...
def test_drag_coalesces_to_latest_target_range(): ...
def test_drag_settle_calls_setdata_once_for_latest_range(): ...
def test_drag_crossing_buffer_is_rate_limited(): ...
def test_programmatic_xlim_gets_deterministic_settled_refresh(): ...
def test_stale_settle_generation_cannot_mutate_pdi(): ...
def test_ticks_and_visible_range_signal_emit_once_after_settle(): ...
```

这些测试在实现前应按预期 FAIL，且失败原因必须是逐窗口 `setData()`。

### Task 2.2 — 在 ViewBox 暴露交互生命周期

**Owned files**

- `mf4_analyzer/ui/pg_canvas/viewbox.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `mf4_analyzer/ui/pg_canvas/quality.py`

实现明确的 begin/update/end 或等效状态：

- mouse drag 开始进入 `interactive`；
- wheel/box zoom 使用短 settle debounce；
- programmatic Home / `set_xlim()` 可直接请求 settled refresh；
- split View 每个 canvas 独立；
- 取消/clear 会停止 timer 并递增 generation。

### Task 2.3 — Buffer envelope 与 settle refresh

**Owned files**

- `mf4_analyzer/ui/pg_canvas/renderer.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`

实现：

1. settled envelope 覆盖 viewport 左右各 25% buffer；
2. buffer 内 range event 只更新 ViewBox transform；
3. buffer 外 coarse 更新上限 10 Hz；
4. quiet 100 ms 后仅刷新最新范围；
5. 每条可见 PDI settle 最多一次 `setData()`；
6. ticks、range signal、cursor tail work 聚合到 settle；
7. 现有 `_curve_path_cache` 若不再使用，删除误导性注释/死 seam；若保留，明确它不承担 production hot path。

### Task 2.4 — 加入聚合性能探针

**Owned files**

- `mf4_analyzer/ui/pg_canvas/_perf_probe.py`
- 对应测试

记录一次交互的 range events、transform-only frames、coarse/settled `setData()`、envelope/setData/paint 统计与 displayed points。默认关闭，不逐事件刷日志。

基准要求：

- 20 个 buffer 内 range event：0 次中间 `setData()`；
- settle：1 次 `setData()`；
- 离屏 P95 相比旧路径下降至少 50%；
- 真实 fixture 的 raw 5,727 点不变。

**Checkpoint 2**：CRC 连续拖动不再逐 range 重建曲线；这是本轮用户可感知问题的第一交付点。

## Stage 3 — 通道勾选 delta render

### Task 3.1 — 建立 render model diff

**Owned files**

- `mf4_analyzer/ui/main_window/window.py`
- 建议创建：`mf4_analyzer/ui/pg_canvas/render_model.py`
- `mf4_analyzer/ui/view_bridge.py`（仅在状态投影确需调整时）
- 对应 unit/UI tests

先写失败测试：

```python
def test_checking_one_channel_keeps_unchanged_pdi_and_viewbox_identity(): ...
def test_unchecking_one_channel_removes_only_its_items(): ...
def test_eye_toggle_does_not_full_rebuild(): ...
def test_selection_delta_preserves_xlim_cursor_and_other_channel_cache(): ...
def test_mode_change_still_uses_explicit_structural_rebuild(): ...
```

### Task 3.2 — 增量 add/remove/show/hide

**Owned files**

- `mf4_analyzer/ui/pg_canvas/canvas.py`
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py`
- `mf4_analyzer/ui/main_window/window.py`

增加 canvas 级 delta API，避免 `_ch_changed()` 无条件 invalidate + `plot_channels()`。结构不兼容时允许 fallback full rebuild，但必须传递并记录 reason。

### Task 3.3 — 延后非首帧工作

检查 `_build_time_statistics()`、tick density、range input 同步和 filter companion 构建。能缓存的复用，非首帧必需项在首次 paint 后执行；不得改变最终结果。

基准：真实 CRC 的 warm 单通道勾选/取消 P95 目标小于 30 ms；未变化 PDI/ViewBox identity 保持。

**Checkpoint 3**：勾选/取消勾选不再重建整个画布，首次选择热点从结构重建中解耦。

## Stage 4 — DBC 候选去重、预筛与后台 probe

### Task 4.1 — 抽出纯候选身份与排序

**Owned files**

- 建议创建：`mf4_analyzer/blf_dbc_candidates.py`
- `tests/test_blf_dbc_candidates.py`
- Modify：`mf4_analyzer/ui/main_window/_project_io_mixin.py`

先写失败测试：

```python
def test_candidate_identity_is_order_independent_and_path_normalized(): ...
def test_recent_history_deduplicates_equivalent_dbc_sets(): ...
def test_structural_prefilter_ranks_id_overlap_without_decoding_frames(): ...
def test_auto_probe_limit_is_three(): ...
def test_strong_candidate_ranks_before_weak_recent_candidate(): ...
def test_unprobed_candidate_is_reported_as_unverified(): ...
```

### Task 4.2 — 读取时建立 CAN ID index

**Owned files**

- `mf4_analyzer/io/loader.py`
- `tests/test_blf_loader.py`

让单次 BLF read 同时产出或可复用 CAN ID histogram，不额外扫描完整 frames。保持现有 `read_blf_frames()` 兼容；新增 typed result 或旁路 API 时需明确迁移。

### Task 4.3 — 后台 probe 与取消

**Owned files**

- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- 现有 worker/job coordinator 相关模块（先确认项目模式再选）
- `tests/ui/test_blf_batch_import.py`

要求：

- 自动 probe 仅 top 3；
- probe 不在 GUI 主线程；
- transaction/generation 检查；
- cancel 后旧结果不弹窗、不登记；
- strong 足够明确时可提前结束；
- 用户展开未校验候选时按需后台 probe。

### Task 4.4 — 候选 UI 状态

候选列表显示“强匹配 / 弱匹配 / 校验中 / 未校验 / 不匹配”，默认选择最高分 strong。保持对话框宽度和按钮文字完整，并做 Qt 离屏截图。

真实基准：

- `0kph_50-6.blf`，约 27 MB / 611,013 帧；
- 同一 DBC 集合的两个排列只 probe 一次；
- GUI 在 probe 期间可响应并可取消；
- 自动完整 probe 数不超过 3。

**Checkpoint 4**：DBC 选择框前的线性主线程卡顿关闭。

## Stage 5 — 导入事务、顺序与错误语义

### Task 5.1 — 引入有序 ImportTransaction

**Owned files**

- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- 可创建纯模型模块与 tests
- `tests/ui/test_blf_batch_import.py`

先写：

```python
def test_mixed_import_preserves_original_input_order(): ...
def test_duplicate_input_path_is_skipped_once_with_feedback(): ...
def test_shared_dbc_scope_ends_with_current_import_transaction(): ...
def test_next_drop_prompts_for_dbc_again(): ...
def test_cancel_stops_only_current_transaction(): ...
```

BLF 共享策略与文件登记顺序解耦；不得先处理全部 BLF 再处理其他格式。

### Task 5.2 — 修正 mismatch 文案和动作

新增最后一个、中间一个、首个 BLF mismatch 的参数化测试。`N == 0` 时只写当前文件，不显示“后续 0 个”。

### Task 5.3 — 配置管理器空选择语义

**Owned files**

- `mf4_analyzer/ui/widgets/channel_config_manager.py`
- `tests/ui/test_channel_config_manager.py`

用 `selected_ids=None` 表示保留现有选择，空 iterable 表示显式清空。增加仍有有效配置时显式清空的测试。

**Checkpoint 5**：批量策略、下一次重新确认、mixed order 和边界文案全部确定。

## Stage 6 — 真实进度账本

### Task 6.1 — 纯 progress ledger

**Owned files**

- 建议创建：`mf4_analyzer/progress_ledger.py`
- `tests/test_progress_ledger.py`
- `mf4_analyzer/ui/compute_progress.py`

先写：

```python
def test_progress_is_monotonic_when_dynamic_work_is_added(): ...
def test_progress_reaches_100_only_after_final_phase(): ...
def test_cancelled_progress_never_reports_success(): ...
def test_unknown_phase_selects_indeterminate_state(): ...
```

账本接收实际 bytes/frames/channels 单位；UI 只消费 snapshot，不在各层手工映射固定百分比。

### Task 6.2 — Raw BLF assemble progress

**Owned files**

- `mf4_analyzer/io/loader.py`
- `tests/test_blf_loader.py`

为 `_raw_blf_channels()` 增加回调，覆盖 payload 拆分、series 组装和共享时间轴。无法细分的子阶段显式使用 indeterminate。

### Task 6.3 — DBC 与多文件进度接线

**Owned files**

- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `tests/ui/test_compute_progress_integration.py`
- `tests/ui/test_blf_batch_import.py`

候选实际 probe 数改变时扩展 ledger，总百分比不倒退。多个文件按实际文件大小/帧数加权，完成时点在文件登记之后。

### Task 6.4 — Plot progress 完成时点

**Owned files**

- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/pg_canvas/_perf_probe.py`
- progress integration tests

绘图 100% 必须包含首次可见 paint 或明确的 first-frame acknowledgement。delta render 与 full rebuild 使用不同工作量，不再对两者套同一固定 520–960 区间。

**Checkpoint 6**：进度与真实阶段一致，不再出现原始 BLF 40% 或 plot 半程后突然完成。

## Stage 7 — UI 与跨平台视觉回归

### Task 7.1 — 固定几何测试

复跑并强化：

- `tests/ui/test_file_navigator.py`
- `tests/ui/test_channel_config_bar.py`
- `tests/ui/test_blf_batch_import.py`

断言普通/选中通道行的 checkbox、swatch、文字、Pts、eye X 坐标一致；保存/下拉/应用高度一致；按钮文字完整。

### Task 7.2 — Qt 离屏截图

为以下状态输出到临时目录或正式 evidence 目录：

1. 普通行与选中行相邻；
2. 配置栏 disabled/enabled/open popup；
3. 批量 DBC 三按钮；
4. candidate 校验中/强/弱/未校验；
5. 进度 determinate/indeterminate/cancelled。

必须检查真实 widget geometry 与截图像素，不只检查 QSS token。

### Task 7.3 — macOS 与 Windows 前台

macOS Retina：

- 真实 T1EJ fixture 勾选 `EPS_CRC1`；
- 连续拖动 5 秒并记录 perf summary；
- 对比 native-AA-off fallback 与高分辨率平滑层的边缘，确认不以
  减少 bucket 或改变 CRC 数值语义换观感；
- 取消勾选；
- 多 BLF 统一 DBC、取消、下一次拖放重新确认。

Windows：

- 100% / 125% / 150% scaling 至少选两个；
- 检查文字裁切、按钮宽度和 CRC 拖动；
- 记录输入延迟/P95 与最大 stall。

**Checkpoint 7**：离屏行为、macOS live、Windows live 三种证据分开归档。

## Stage 8 — Final Verification And Delivery

### Task 8.1 — Focused suites

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_blf_loader.py \
  tests/test_blf_dbc_candidates.py \
  tests/test_progress_ledger.py \
  tests/ui/test_blf_open.py \
  tests/ui/test_blf_batch_import.py \
  tests/ui/test_compute_progress.py \
  tests/ui/test_compute_progress_integration.py \
  tests/ui/test_high_variation_envelope.py \
  tests/ui/test_channel_widget.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_channel_config_bar.py \
  tests/ui/test_channel_config_manager.py \
  tests/ui/test_pg_timedomain_canvas.py \
  tests/ui/test_timedomain_hotpath_perf.py
```

若计划中的新文件最终采用不同名称，命令同步更新，不能静默跳过。

### Task 8.2 — Wider regression

先按改动影响图选择 wider suites，再运行项目约定的完整测试入口。记录 exact passed/failed/skipped，不以“专项通过”代替全量结果。

### Task 8.3 — Static and workspace checks

```bash
git diff --check
git status --short --branch
git diff --stat
```

检查：

- 无无关文件；
- 无真实 BLF/DBC 大文件被新增到 Git；
- 无临时截图、profile 或日志泄漏；
- perf 探针默认关闭；
- stale 注释和旧“五次 pan 五次 setData”契约已清理。

### Task 8.4 — Recommended commit boundaries

建议依次形成：

1. `test(ui): align channel widget tests with view attachments`
2. `perf(plot): stabilize dense-discrete render profiles`
3. `perf(plot): defer viewport data refresh until interaction settles`
4. `perf(plot): update channel selection by render delta`
5. `perf(blf): dedupe and bound dbc candidate probing`
6. `fix(blf): preserve import order and transaction dbc scope`
7. `feat(ui): report phase-backed import and plot progress`
8. `test(ui): lock blf crc and cross-platform geometry regressions`

实际提交前重新查看 diff；若某提交无法独立测试/回滚，继续拆分，不为匹配列表强行合并。

## Execution Order And Stop Gates

执行顺序固定为：

```text
Baseline/tests
  → stable CRC profile
  → interactive/settled pan
  → channel delta render
  → DBC bounded async probe
  → import transaction/order
  → truthful progress
  → visual/live regression
```

Stop gates：

- Stage 0 不全绿，不进入结构性性能重构；
- Stage 2 数据保真或 cursor/stat/export 任一失败，停止并回滚该策略；
- Stage 3 未变化 PDI identity 不能保持，先解释结构依赖，不继续堆 workaround；
- Stage 4 出现旧 transaction 弹窗/登记，停止进入进度接线；
- macOS 前台仍出现大于 100 ms stall 时，不以离屏测试通过宣布完成；
- Windows 未验证时，最终状态写明 `PARTIAL / Windows pending`，不得写“全部完成”。

## Definition Of Done

- Spec 第 13 节 A/B/C 全部有证据；
- 相关测试 0 failures，wider/full suite 结果明确；
- 真实 `EPS_CRC1` 连续拖动期间不再逐 range `setData()`；
- warm checkbox delta 不重建未变化 PlotItem/ViewBox；
- DBC 候选按集合去重、自动 probe 有界且可取消；
- mixed input 顺序、下一次导入重新确认和 mismatch 文案正确；
- raw BLF、DBC probe/decode 与 plot 首帧进度真实；
- UI 几何没有回归，macOS/Windows 证据边界清楚；
- 主题提交可独立测试与回滚；
- lessons completion gate 已执行并记录结论。
