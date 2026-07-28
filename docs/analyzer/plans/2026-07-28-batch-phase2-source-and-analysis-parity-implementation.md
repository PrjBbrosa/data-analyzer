# 批处理 Phase 2：来源与分析能力对齐 Implementation Plan

> 前置：Phase 1 acceptance C1–C10 全 PASS。执行继续 TDD-first；adapter、core、drawer 三条 lane 按公开契约串行汇合，禁止多个 agent 同时编辑 `batch.py` 或 drawer 文件。

> 执行状态：**COMPLETE（2026-07-28）**。P1–P10 全部 PASS；core、UI、source/import、真实 multi-group probe、offscreen 截图与 Cocoa exercise 均已完成。

## Goal

用统一 source adapter 扩展批处理格式和 multi-group 身份；复用单次分析预设/参数；补全 TimeDomain、NFFT、dB reference 与目标展开策略。

## Task 0 — Freeze contracts

- [x] 冻结 `LoadedSource`、`source_id`、target policy、`time_preprocess`、shared preset provider 的字段名。
- [x] 明确 BLF DBC context 通过 adapter context 的 `dbc_paths` 注入；没有 context 时状态为 limited。
- [x] 冻结 `SourceDescriptor`（无 DataFrame）与 `LoadedSource`（持有 FileData）的边界、probe cost 和 multi-group cache 结构。
- [x] 冻结 `.xls` 的 `xlrd` runtime/frozen dependency；不得继续用 openpyxl 打开 `.xls`。
- [x] 冻结 TimeDomain preset 为新 shared 定义（不是旧值提取），TimeContextual 与 BatchSheet 同源消费；冻结 Order preset 不声明 window、window 默认沿用 COT `hanning` 且 preset partial apply 不覆盖。
- [x] 冻结 FFT amplitude definition 为 `native | peak | rms`；native 保持单帧/峰值保持 peak、线性平均 RMS，显式值按 `√2` 在线性幅值层转换。
- [x] 对照 P1–P10 建验收 checklist，确认 Phase 1 gate 已通过。

## Task 1 — Unified adapter registry

**Owner:** signal/data agent；此 task 独占 adapter 文件，不改 UI/`batch.py`。

**Files:**

- Create: `mf4_analyzer/io/source_adapters.py`
- Modify only if needed: `mf4_analyzer/io/__init__.py`
- Tests: new `tests/test_source_adapters.py`

- [x] 先为 required format families 写 registry/dispatch 红测。
- [x] 定义 adapter protocol、availability、probe、load_sources、`LoadedSource`。
- [x] 定义 `SourceDescriptor`，并断言 probe 返回值不持有样本 DataFrame；暂时只能 full-probe 的 adapter 必须显式标 cost 并跑在 worker。
- [x] 逐个包装现有 DataLoader；不得重写 parser。
- [x] multi-group loader 返回稳定 group_id/source_id；MDF 复用 physical occurrence 去重。
- [x] BLF 加 DBC-required 分支和测试；optional dependency 缺失不破坏应用 import。
- [x] `.xls` 按扩展名使用 `xlrd`，补 runtime dependency/frozen smoke；`.xlsx` 继续使用 openpyxl。
- [x] WWT 两个仅 `t0` 不同的 group 必须得到不同 source_id；显示 label 可以相同但 identity 不可相同。

## Task 2 — Main/batch source integration

**Owner:** refactor agent，等 Task 1 API 绿后执行。

**Files:**

- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- Modify: `mf4_analyzer/batch.py`
- Modify: `mf4_analyzer/ui/drawers/batch/input_panel.py`
- Tests: loader dispatch、drop import、batch input tests

- [x] 主窗口支持声明与 batch dialog filter 从 registry 生成。
- [x] FileList row 改用 source_id；同 path 多 group 都可加入。
- [x] probe 与 runner load 调同一 adapter；保持磁盘惰性 load 和逐文件驱逐。
- [x] cache 分为 physical path → sources 与 source_id → FileData/locator；同一 physical multi-group 只加载一次，按 physical path 驱逐。
- [x] 为旧 file_ids/file_paths 做 migration adapter，不一次性破坏 preset。
- [x] 用最小 multi-group registry fixture 验证同路径多 logical source。

## Task 3 — Target policies and source-scoped RPM

**Owner:** core agent；独占 `batch.py` 与非 UI tests。

- [x] 红测 `common`、`available_per_source`、`exact_pairs` 的精确 task set。
- [x] 扩展 recipe/runtime scope，避免 available policy 产生注定缺失的 tasks。
- [x] 实现 same-source RPM、manual RPM、显式 cross-source RPM resolution 与真实 timebase validation/interpolation。
- [x] 保持 current-single/public tuple 兼容。

## Task 4 — Shared built-in presets

**Owner:** refactor agent；先提取纯定义，再改消费者。

**Files:**

- Create: `mf4_analyzer/analysis_presets.py`
- Modify: FFT、FFT-time、Order 三个既有 preset consumer；TimeContextual 新增 shared Time preset consumer
- Modify: `ui/drawers/batch/analysis_panel.py` / `method_buttons.py`
- Tests: contextual preset tests + batch preset UI tests

- [x] 用现有单次 preset 数值写 snapshot 红测。
- [x] 提取无 Qt provider，保留当前单次行为与名称。
- [x] Batch 加“频率/均衡/时间/自定义”，不复制数值。
- [x] TimeDomain 的“时间”preset 由 shared provider 新定义并同时接入 TimeContextual；未声称从旧 Inspector 数值提取。
- [x] Order window 使用 COT 既有 `hanning` 默认；三个旧 signal-type preset 不声明/覆盖 window。
- [x] 应用 preset 不改 source/output/dB state，不 dispatch compute/run。

## Task 5 — Spectral/order parameter UI parity

**Owner:** `pyqt-ui-engineer`；此 task 独占 batch drawer 文件。

- [x] 为各方法完整 get/apply round-trip 写红测。
- [x] window options 与 canonical helper 对齐；增加 Auto/Fixed NFFT、`t_win_s`。
- [x] FFT 增 averaging/overlap/amplitude definition；FFT-time 增完整 overlap/remove mean；Order 增 RPM mode/manual RPM/samples per rev。
- [x] amplitude mode 和轴范围归 OUTPUT，分析参数归 ANALYSIS；避免重复控件产生双权威。

## Task 6 — dB reference control and effective preview

**Owner:** `pyqt-ui-engineer` + core API 已冻结后执行。

- [x] 红测 Auto/Manual/value round-trip、legacy migration、preset partial apply。
- [x] 在 Batch Output 挂载一个 recipe-owned `DbReferenceControl`。
- [x] 调纯 resolver 生成 grouped preview；probe 未完成时显示“等待来源信息”。
- [x] runner 实际 resolution 与 preview 使用同一 facts adapter/catalog snapshot。
- [x] 测试 compute key/data export 不受 mode/value 影响，image label 使用 shared formatter。

## Task 7 — TimeDomain preprocessing

**Owner:** `signal-processing-expert` 负责数值，`pyqt-ui-engineer` 随后接 UI。

**Files:**

- Create or modify pure preprocessing module
- Modify: `batch.py`
- Modify: batch method/input panel
- Tests: numeric order + UI round-trip

- [x] 先写非交换输入，锁定 range→finite→scale/offset→remove mean→sampling→filter 顺序。
- [x] 使用抗混叠 resample/decimate helper，记录 actual Fs。
- [x] filter clamp facts 写进 task result；RPM 不跟随目标信号 filter/scale，spectral/order 不重复滤波。
- [x] Time method 不再空白，控件支持 original/target Fs/decimate 三种模式。

## Interim Execution Record

- Task 1 adapter/format/packaging focused：107 passed；主 agent 独立复核 registry/Excel/runtime/batch-dispatch/no-GUI 为 35 passed。
- Task 7 pure preprocessing：12 focused passed；连同 filter/validation/recipe/no-GUI/batch regression 为 151 passed；主 agent 独立复核 61 passed。
- Task 2/3 core integration：agent focused 232 passed；主 agent 独立复核 source/core/adapter/output/renderer/no-GUI 为 224 passed。
- `.venv` 已安装并验证 `xlrd 2.0.2`；Windows runtime dependency installed contract 为 PASS。
- 已知且如实暴露的边界：TDMS 仍沿用现有 flatten loader；MDF quantity/reference metadata 尚未由 DataLoader 提供；HDF/WWT/ZFD/MAT probe cost 为 `full`。
- Shared preset/TimeContextual/Batch UI：agent focused 212 passed；主 agent 独立 batch UI 133 passed、Inspector/preset 31 passed。
- Source/import/runtime regression：121 passed、1 skipped；Windows packaging installed contract PASS。
- 真实 HDF 两组 probe/load：2 个稳定 source_id 与 group_id 一致，available-per-source run 为 done，生成 2 个不碰撞 CSV。
- UI proof：`.state/batch-phase2-1080x760.png` 已按原始 1080×760 检查；Qt Cocoa 真实平台完成独立滚动、preset、available policy、Manual dBA exercise。

## Task 8 — UI geometry and error states

- [x] 288/320 px 列宽下新增控件无裁切；长参数通过各列独立滚动保持可达。
- [x] source unavailable、BLF no DBC、probe/load failure、partial availability 都有不同文案/状态。
- [x] 生成并检查 1080×760 offscreen 截图；另完成 Cocoa multi-group/available/preset/dB/time exercise。

## Task 9 — Phase gate

- [x] 跑 Phase 2 spec focused command以及所有 source/import/batch tests（Qt 长组合按已知 teardown 边界拆成独立绿测组）。
- [x] 跑一个真实 HDF multi-group probe 和 BLF missing-context / missing-package availability probe。
- [x] grep 主入口与 batch 的 extension/probe lists，确认不再存在会漂移的第二份硬编码支持表。
- [x] `git diff --check`；P1–P10 逐项记录证据，全部 PASS 后进入 Phase 3。

## Phase 2 Acceptance

P1–P10：**全部 PASS**。特别边界：`BatchItemResult.source_identity` 沿用 Phase 1 的物理 path 语义，logical source_id 在 `file_id` 中，group identity 单独记录；真实两组 HDF 的 task/output 仍稳定区分。TDMS group flatten 与 MDF quantity/reference metadata 是 registry 明示的 capability note，不被误报为已实现的 richer metadata。

## Stop Conditions

- probe 与 load 对同一路径产生不同 source_id：停止 UI 汇合。
- built-in preset 仍有两份数值定义：停止 Phase 2 完成判定。
- dB reference 进入 compute cache/dataframe 数值：必须修复后才能进入 Phase 3。
