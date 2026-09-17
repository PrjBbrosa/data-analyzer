# 9 月 17 日提交审查与优化计划

- 日期：2026-09-17，Asia/Shanghai。
- 状态：**F1/F2/F3 已按本文修复；offscreen owner/边界通过；Cocoa/Windows/全量仍 partial/UNKNOWN**。产品修复已执行。
- 当前审查快照：`fa7f6e21`。修复在该快照之上实施。
- 范围：9 月 16 日的 `b0b3fcf7`、`0bcac91e`、`a30cceef`、`a58f8c01`、`3fb56a4a`，以及 9 月 17 日的 `fa7f6e21`。
- 开始审查时 HEAD 为 `3fb56a4a`，扩展实现尚未提交；审查期间外部提交为 `fa7f6e21`。提交 diff 与测试前保存的 tracked diff 经 `cmp` 完全一致，新增测试文件 SHA-256 也一致，测试期间没有发现相关源码内容变化。
- 工作区原有未跟踪文件 `ssh-keygen` 保留，未读取其内容或纳入审查产物。
- 执行方式：单协调者顺序修复。用户于 2026-09-17 授权按本文执行并提交推送。

## 1. 结论与问题分级

发现 **2 项 P2 实现问题、1 项 P3 共享组件防护缺口**。功能已有大量定向覆盖，但不能据此确认所有优化完成，更不能宣称零隐藏 bug。

### F1 / P2：目标 View 的缓存判断读了离开页参数

位置：[`_fft_time_mixin.py:107`](../../../mf4_analyzer/ui/main_window/_fft_time_mixin.py#L107)、[`_analysis_mixin.py:189`](../../../mf4_analyzer/ui/main_window/_analysis_mixin.py#L189)。同类调用还存在于 `_fft_view_is_uncomputed` → `window.py:_fft_any_source_cached` 和 `_order_view_is_uncomputed`。

`_on_analysis_switch` 在 `mgr.set_active(idx)` 前调用 `_analysis_view_is_uncomputed(section, target)`。时频 helper 虽然读取了目标 sources，构造 key 时却调用 `_analysis_cache_key(..., pane_idx=0)`；后者从当前 Inspector 和当前活动 Pane 读取计算参数、时间范围。Order 虽先 overlay 目标 params 判断 RPM 模式，最终 key 仍回到 live params；FFT 复用的 helper 也没有传目标 params/range。FRF 的 `_frf_cache_key_for_pane(state, pane)` 使用目标状态，不应被泛化改坏。

**复现已通过真实 MainWindow 验证**：View 1 有 `hanning` 时频缓存，View 2 使用 `hamming`。从 View 2 返回 View 1，判断报告“未计算”；真实标签切换记录 `transition_started=0`，目标却成功显示缓存结果（`has_result=True`）。即相同目标是否有动效依赖离开页参数。反向误命中的风险和 FFT/Order 同类行为为静态推断，尚未分别复现。没有证据表明本问题改变了最终计算结果。

测试漏项：现有扩展测试的缓存目标和离开 View 大多共享计算参数，未覆盖不同窗函数、NFFT、时间范围的切换。

### F2 / P2：Off 路径仍支付动效专用的数据准备成本

位置：[`_analysis_mixin.py:175`](../../../mf4_analyzer/ui/main_window/_analysis_mixin.py#L175)、[`window.py:2148`](../../../mf4_analyzer/ui/main_window/window.py#L2148)；最终 policy 判断直到 `ChartStack.begin_page_transition` 才发生。

内部 View 与跨 Section 的前置判断没有在查缓存前短路 Off。只要 enabled sections 仍包含目标，就会先构造分析 key。时频路径进入 `_fft_time_effective_params_for_source`，取数组、范围掩码并调用 `prepare_analysis_time_axis`；该函数即使 `materialize=False` 也执行数组有限性检查及部分情况下的差分。Order 路径还涉及 RPM 准备。这些步骤发生在原有目标恢复之外。

**确定性调用探针**：设置 `POLICY_OFF` 后，仅调用 `_should_begin_analysis_page_transition('fft_time', 0)`，仍调用数据准备 **1 次**。当前 Off 测试只断言不截图、不开始动画，没有检查这笔额外工作。已证明新增扫描路径，未测其原生 P95，不将其描述为已经量化的卡顿或新增 FFT job。

### F3 / P3：共享游标缓存只恢复明细，不恢复同一来源的 primary

位置：[`stack.py:2182`](../../../mf4_analyzer/ui/chart_stack/stack.py#L2182)、[`stack.py:2380`](../../../mf4_analyzer/ui/chart_stack/stack.py#L2380)。

`_cursor_rows_by_canvas` 保存 `(cursor_mode, x_mode, channels)`，没有对应 primary。`_sync_cursor_pill_to_mode` 调用 `_refresh_cursor_projection(source)` 时未传 primary，因而沿用共享 pill 上一个领域的 `_primary_original`。

**组件级真实 Qt 复现**：时域 A=1s/B=2s → FFT A=10Hz/B=200Hz → `ChartStack.set_mode('time')`；明细为时域 speed 的 Min/Max/Avg，顶部仍是 FFT 的 A/B/Δf。已检查真实渲染 PNG，属于画面事实，不仅是内部属性断言。

**范围限制**：进一步执行完整 MainWindow、非空数据、真实游标 placement 和工具栏往返时，后续业务恢复会重发读数，最终 primary 正确（补充探针通过）。因此本项是共享恢复边界的中间态/潜在复用缺口，不能宣称常规 MainWindow 切换后持续显示错误。修复须留在现有 presentation owner，不为此新增 MainWindow 状态或全局缓存。

## 2. 提交执行情况与验证限制

| 改动 | 当前判断 |
|---|---|
| 通道树投影合并、候选列表去重、effective facts 单次同步 | 实现已落地；检查对应 owner 与来源隔离回归，未因旧记录称其已验收。 |
| 8.2.5 图标故障回退、输入/身份保护 | 当前实现保留精确异常分类与输入保护；发布帮助/打包合同纳入本轮门。 |
| 时域自然 paint 动效修复 | 普通 Paint 不再误取消；当前失效信号监听已恢复。 |
| FFT 游标共享布局 | 几何/字段 owner 测试通过；F3 的跨域 primary 边界仍有缺口。 |
| WWT X 标题来源 | 新导入 ordinary 分支显式 auto，owner 和项目恢复测试通过；保留旧项目显式 user 与 exact-binding 边界。 |
| 五工作区扩展 | 当前生产五区已启用，20 向正常交接测试通过；F1/F2 待修。 |
| 原生性能和跨平台 | Cocoa 前台、30 样本性能、Windows 源码/Full/Lite/DPI 仍未验收。 |

提交间发现一次已经补回的回归：`a58f8c01` 删除了 `a30cceef` 刚加入 `stack.py` 的 `_page_transition_content_slots` 初始化、失效连接和清理，`3fb56a4a` 仍缺失；`fa7f6e21` 又补回。**当前最终快照不再缺此保护**，不重复开一个产品修复任务；应保留该 seam 的真实内容替换测试，避免共享文件提交遗漏被大套件通过数掩盖。

扩展验证记录称用户另行要求五区全开。本审查保留当前启用决定，不根据旧计划成本门擅自关掉功能；全开与性能通过分别记录。历史计划仍有“待实施/本次仅编计划”文字，执行记录也缺少可复用的最终快照与完整命令；T4 负责补充当前台账，不重写历史事实。

## 3. 修复计划与 owner

### T0：固定快照及失败条件

- 核对当前 HEAD、dirty scope；保留其他任务更改。
- 将本轮 `.state/2026-09-17-review/test_review_probes.py` 中三个失败条件迁入下述正式 owner 测试，独立复现后再改源码。临时探针依赖 UI conftest 插件，不直接拷贝成新测试基建。
- F1 加入 `tests/ui/test_section_page_transition.py`；F2 同文件；F3 加入 `tests/ui/test_fft_cursor_layout.py`。
- F3 保留完整 MainWindow 已通过用例为对照，不能只用组件失败推导产品持续故障。
- 不要求全量 baseline；本轮稳定快照已有通过结果，可复用。

### T1：按目标状态解析缓存身份（F1）

Owner：`ui/main_window/_analysis_mixin.py`、`_fft_time_mixin.py`、`_order_mixin.py`，必要时 `_fft_mixin.py`/`window.py` 中现有 key seam。

1. 以目标 View/Panes 的复合来源、params、有效 time range、RPM 来源构造与实际 restore 相同的 key；复用已有 inactive-restore 合同和 neutral key builders，不维护第二套键字段。
2. 不把目标 params 临时 apply 到 Inspector 再读回，不提前 `set_active`，不改变原离开页 capture 和业务提交顺序。
3. 同时覆盖 FFT、FFT vs Time、Order：不同窗函数/NFFT/范围、RPM 模式；cache hit→miss、miss→hit；缓存部分命中时明确保持现有合法结果策略。
4. 保留 FRF 的 state-based key 行为。缺源、空 View 和项目 deferred restore 不发起动画专用计算。
5. 验收分别断言：是否 begin/capture、原目标结果/轴/来源、job 数量、pin 与 dirty；不能只断言活动索引。

Focused：新增节点、`test_analysis_multiview_integration.py` 的 params/来源恢复条目、`test_analysis_cache_pinning.py` 相关节点。先确认收集，不用 `0 selected` 充当通过。

### T2：先做廉价动效判断，消除 Off 附加工作（F2）

Owner：现有 ChartStack 呈现策略接口、`_analysis_mixin.py` 和 `window.py` 的导航接线；依赖 T1 明确目标 key。

1. 在任何动效专用 key/data 准备、截图之前判定 policy、enabled sections、导航类别、布局和生命周期。共享一个只读廉价判定接口，避免两条入口各自维护启用策略。
2. Off、未启用、程序恢复、分屏、同目标返回时，动效额外准备/扫描/截图为 0；原有正常业务恢复仍执行。
3. Light 路径若可复用已有目标有效事实，在同一事务内复用；禁止增加长期 View 位图缓存、并行状态机或通过陈旧 key 绕过数据有效性校验。
4. 计算/prepare 调用数以“同一目标的原业务恢复”作对照，不能仅统计 submit 或最终结果。

Focused：`test_section_page_transition.py` 的 Off/内部/跨区/程序恢复/分屏条目；`test_page_transition.py`、`test_page_transition_integration.py` 受影响节点。

### T3：让 primary 与明细属于同一呈现快照（F3）

Owner：`ui/chart_stack/stack.py`；必要时现有 `cursor_display_model.py` 的中立 DTO 和 `cursor_pill.py`。

1. 沿用当前每 canvas 呈现 owner，原子保存/恢复 primary 与 rows/领域；无 primary 时明确清空或隐藏，不能继承另一来源文字。
2. 对 clear/off、隐藏源、Pane 移除与销毁对称清理；不引入新的 QSettings 或 MainWindow 可变状态。
3. 验证 Time↔FFT，single/dual/仅 A、full/mini、分屏焦点、组件直接恢复和完整 MainWindow 后续恢复。比较 primary 的值/单位与明细领域，避免只检查 `Min` 或通道名。
4. 检查实际绘制文档和 frame，不改 shared planner 的宽高/颜色合同；每次逻辑更新仍仅一次 projection。

Focused：`test_fft_cursor_layout.py`、`test_cursor_single_pipeline.py`、`test_cursor_table_geometry.py`、`test_cursor_table_modes.py`；`test_split_routing.py`、`test_pill_switch.py` 中经过修改 seam 的条目。

### T4：合并边界、原生验收与文档台账

- 运行受影响 owner 后，再跑 `test_no_lambda_signal_connections.py`、`test_main_window_state_ownership.py`、`test_import_boundaries.py`；若动到 canvas collaborator，加 `test_pg_canvas_backref_invariants.py`。不放宽白名单。
- 保留 ready 后真实结果替换、普通 paint、A→B→C、关闭/项目恢复、freeze/thaw、自动与显式 UltraView capture 的合同；新增测试须走真实 widget 事件，不仅搜索源码字符串。
- 本轮修复不改变 ink/AA/DSP。若不得不动这些 owner，先修订范围并运行相应 restore/discrete settle/paint backstop 条目。
- 按[扩展计划 §6](2026-09-16-all-sections-page-transition-expansion-plan.md)在稳定快照上补 Cocoa Off/Light：5 次预热、30 个样本，分别记录 ready、完全交接、事件 lag、截图/底层 paint/thaw、峰值内存；关闭动效的前置扫描单列。不得将本轮并行运行定向测试时的耗时用作性能指标。
- Windows 源码、Full/Lite、100%/150%/200% 另列结果；无法执行继续记 UNKNOWN。当前全开不等于性能验收，不自动改变启用范围。
- 更新扩展、游标和 follow-up 的当前执行台账：快照、实际命令、通过/失败、剩余平台门；历史基线和曾经的执行状态保留。
- 如没有用户可见交互变更，不额外改 hints/quickref；若真实启用/使用规则改变，两者同时同步。
- 默认不跑 full suite。仅新的跨边界失败、顺序污染或明确 release/merge 门才按仓库规定由一个协调者运行一次稳定快照全门。

## 4. 本轮验证证据

临时证据均在 `.state/2026-09-17-review/`，不纳入 Git：

| 门 | 结果 |
|---|---|
| 新扩展、page transition、FFT cursor、三类 canvas、WWT importer/flow、project session | **642 passed, 1 skipped**，185.42s，正常退出；`focused-tests.log`。 |
| 共享布局、通道/来源、候选、RenderGate、边界和发布合同 | **977 passed, 1 skipped**，272.72s，正常退出；`boundary-and-prior-owner-tests.log`。 |
| 三个审查定向探针 | **3 failed, 1 deselected**，均为上述 F1/F2/F3 的预期合同失败；`probes-confirmed.log`。 |
| 完整 MainWindow 非空 FFT↔Time 游标往返对照 | **1 passed, 4 deselected**；`mainwindow-probe.log`。这是 F3 影响范围的限制证据。 |
| ChartStack 实际 Qt PNG | `primary-mixed-domain.png` 已检查，确认明细与 primary 跨领域混合；offscreen、合成读数。 |
| 空时域返回探索 | 未复现超时；不列为问题。 |
| Cocoa 前台/原生成本、Windows、全量 suite | 本轮未运行，不能推导通过。 |

两组既有定向门合计 **1619 passed, 2 skipped**。它们的全绿与三个新增探针失败并不矛盾：后者检验的是原测试未覆盖的条件。warnings 主要来自 pyqtgraph 对 NumPy 数组 shape 的弃用提示，未在本轮扩大修复。

第一组实际测试文件：`test_section_page_transition.py`、`test_page_transition.py`、`test_page_transition_integration.py`、`test_fft_cursor_layout.py`、`test_pg_line_canvas.py`、`test_frf_canvas.py`、`test_pg_heatmap_canvas.py`、`test_wwt_view_import.py`、`test_wwt_import_flow.py`、`test_project_session.py`（均在 `tests/ui/`）。

第二组实际测试文件：`tests/ui/` 下的 `test_channel_widget_setters.py`、`test_analysis_source_scope.py`、`test_analysis_multiview_integration.py`、`test_searchable_combo.py`、`test_time_section_entry.py`、`test_view_switch_reentrancy.py`、`test_cursor_table_geometry.py`、`test_cursor_table_modes.py`、`test_cursor_single_pipeline.py`、`test_hints.py`、`test_quickref.py`、`test_no_lambda_signal_connections.py`、`test_main_window_state_ownership.py`、`test_import_boundaries.py`、`test_pg_canvas_backref_invariants.py`，以及 `tests/ui_kit/test_icon_cache.py`、`tests/ui_kit/test_qss_border_shorthand.py`、`tests/test_help_content.py`、`tests/test_windows_build_script.py`。两组均使用下述环境和 `.venv/bin/python -m pytest -q`，没有运行全套 `tests/ui` 或全量 suite。

复现命令（隔离 UI conftest、只读产品代码）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q -s -p tests.ui.conftest \
  .state/2026-09-17-review/test_review_probes.py \
  -k 'not empty_time and not mainwindow'
```

本轮新增的是计划文档，不需要为文案另写 runtime test。交付门为引用/范围检查、`git diff --check`、源码快照复核和 lesson status。

## 5. Lessons 与关闭条件

已读取并复用 [overlay paint/失效](../../lessons-learned/overlay-paint-is-not-content-invalidation.md)、[延后恢复 RenderGate](../../lessons-learned/deferred-section-entry-shares-render-gate.md)、[Pane-local sources](../../lessons-learned/codex-analysis-section-state-needs-pane-local-sources.md)、[实际游标文档验收](../../lessons-learned/cursor-layout-tests-must-use-painted-document.md)。本轮缺口是既有来源/呈现合同覆盖不足，不再复制一篇同义 lesson；用正式回归关闭遗漏。共享文件失效保护曾被删除的事实已记录，不能从当前恢复反推中间提交安全。

完成标准：F1/F2 的真实导航和调用次数闭环通过；F3 组件快照一致，完整窗口对照不退化；owner/边界通过；台账与真实启用状态一致。原生及 Windows 未完成时总体仍标 partial，明确哪些功能已测、哪些平台与负载未知。

## 6. 2026-09-17 修复执行台账

基线仍是 `fa7f6e21`。本轮在其上修复 F1/F2/F3，未改 ink/AA/DSP，未改 hints/quickref，未 bump 版本。启用范围保持五个 Section 单 Pane 用户导航。

| 项 | 结果 |
|---|---|
| F1 目标 View 缓存身份 | `_analysis_cache_key_for_view_source` 用 overlay params + pane time range / RPM；FFT/FFT-vs-Time/Order 在窗函数、NFFT、范围不一致时按目标状态判命中。FRF 仍走 `_frf_cache_key_for_pane`。 |
| F2 Off/未启用/分屏/程序恢复 | `ChartStack.page_transition_presentation_admitted` 在 key/prepare/截图前判定 policy、enabled、split；window 生命周期检查共用。Off 路径 prepare=0。 |
| F3 共享 pill primary | `_cursor_rows_by_canvas` 现为 `(mode, x_mode, channels, primary)`；跨 Time↔FFT 恢复同一来源的 primary+明细；无 primary 时清空而非继承。 |
| 新 owner 测试 | `test_analysis_admission_uses_target_params`、NFFT/范围、miss↔hit、Off/分屏/程序恢复廉价门、`test_shared_pill_restores_primary_with_same_domain_rows` 等。 |
| page transition + FFT cursor owners | **107 passed, 1 skipped**（`test_section_page_transition.py`、`test_page_transition.py`、`test_page_transition_integration.py`、`test_fft_cursor_layout.py`），110.71s。 |
| cursor/split/analysis owners | **753 passed**（single pipeline、table geometry/modes、split routing、pill switch、multiview、cache pinning），152.27s。 |
| 边界 | **17 passed**：`test_no_lambda_signal_connections.py`、`test_main_window_state_ownership.py`、`test_import_boundaries.py`。 |
| Cocoa 5 预热 + 30 样本 Off/Light | **UNKNOWN**，本环境未跑前台/原生计时；不把定向测试墙钟当 P95。 |
| Windows 源码/Full/Lite/DPI | **UNKNOWN**。 |
| 全量 suite | 未跑。 |

命令（项目 venv、offscreen）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_section_page_transition.py \
  tests/ui/test_page_transition.py \
  tests/ui/test_page_transition_integration.py \
  tests/ui/test_fft_cursor_layout.py

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_cursor_single_pipeline.py \
  tests/ui/test_cursor_table_geometry.py \
  tests/ui/test_cursor_table_modes.py \
  tests/ui/test_split_routing.py \
  tests/ui/test_pill_switch.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_analysis_cache_pinning.py

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_import_boundaries.py
```

`tests/test_cache_key_dataclass_binding.py::test_fft_time_analysis_key_field_set_equals_spectrogram_params` 仍因既有 `nfft_facts_signature` 字段集与 `SpectrogramParams` 不一致失败；本轮未改 `_fft_time_analysis_cache_key` 的注册字段，不计入本次回归。总体仍标 **partial**：功能修复已测，平台与负载未知。
