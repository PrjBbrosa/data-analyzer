# 两日优化修复与系统性鲁棒性执行 Plan

日期：2026-09-12。状态：**文档完成；本轮修订后的 T5 已完成**。其余任务状态见各自实施记录。

输入：[Review](../reviews/2026-09-12-two-day-optimization-review.md)、[Spec](../specs/2026-09-12-optimization-robustness-spec.md)。任务编号 T0～T9，需求 R01～R10，验收 A01～A18。

2026-09-12 用户后续指令已取消范围恢复 feature，授权本轮执行修订后的 T5：移除状态条和按钮，以 Home / 重新计算完成操作。此更新不授权其他未完成任务；原 T5 的按钮 dirty 修复不再作为目标。

本计划先关闭错误显示和状态合同，再做最终性能及跨 UI 验收。默认按依赖顺序执行；本轮用户明确授权 T5 的入口移除，未请求启动 agent。其余任务的授权与完成状态以各自实际会话和验证记录为准。初始审查生成的失败探针在 `.state` 快照中，实施时应迁入正式 owner 测试并保留失败前证据。

## 1. 依赖与文件责任

```text
T0 冻结当前基线 / 协调在途工作
 ├─ T1 频谱范围正确性（P1）
 ├─ T2 通道树恢复成本
 ├─ T3 选择控件提交顺序
 ├─ T4 Batch 诊断与结果过期
 ├─ T5 移除独立范围恢复入口
 └─ T6 X 标签来源
T1 / T3 / T5 / T6 + 当前在途实现 → T7 候选集成
T1～T7 → T8 原生性能与横向验收 → T9 证据收口
```

Owner 指模块责任，不预先指定 agent。若后续用户明确授权并行，同一文件及公共契约仍由一个协调者集成；worker 只跑各自 focused/boundary，不运行全套。

| 任务 | 主要文件责任 | 不跨入的责任 |
|---|---|---|
| T1 | `ui/pg_canvas/line_canvas.py`；必要时既有 `spectrum_display.py` | 不重写 DSP、不修改校准阈值 |
| T2 | `ui/widgets/channel_tree.py` | 不迁移业务选择状态或整棵树模型 |
| T3 | `ui/chart_stack/cards.py`；有失败证据才改其他选择 owner | 不改 MainWindow 渲染管线 |
| T4 | `ui/drawers/batch/result_details.py`、`sheet.py`；必要时 InputPanel 语义信号 | 不改 runner、计算或输出算法 |
| T5 | `ui/analysis_section_page.py`、`ui/main_window/_analysis_mixin.py`、hints/quickref | 不改 viewport 持久化、Home 或 DSP |
| T6 | `ui/time_xaxis.py`、`inspector_sections/persistent_top.py`、apply/restore/capture 消费者 | 不以控件保存第二套业务意图 |
| T7 | 在途 Section/quality/motion 的最终合同集成；共享文件由协调者串行处理 | 不覆盖其他会话的改动 |
| T8/T9 | `.state` 探针、durable 验收记录和当前文档 | 不因门禁失败擅自扩大产品重构 |

所有相对源路径均位于 `mf4_analyzer/` 下，测试路径从仓库根开始。

## 2. 执行任务

### T0 — 建立当前可复核基线

**依赖：** 无。**目标：** Review 基线与即将实施版本明确分开。

- [ ] 读取全部三份 Review/Spec/Plan，检查实际 HEAD、dirty/staged scope 和在跑 pytest。保留初始 manifest 与 named-path diff。
- [ ] 确认 `d1299597`、Section reveal/time gate、prepared facts、motion 320 ms、channel-config placeholder 的当前落地状态；按真实 owner 解决在途冲突，不从历史快照覆盖 live 文件。
- [ ] 新建不可变测试候选，记录源码、依赖、探针、目标测试哈希。引用本次 `9cda` 的 1814/43 结果仅作审查证据，不能当新候选通过结果。
- [ ] 复现与准备修改的 owner 对应的失败 probe；将正式回归放入该 owner 现有测试文件。不得将 `.state` 路径变成正式测试依赖。
- [ ] 明确用户后续实施授权和本任务范围。没有实施授权时止于已完成的文档交付，不把此列表自动作为新授权。

**验证：** 范围、引用、哈希和目标 owner 的既有 focused；不运行泛化全套 baseline。纯文档调整只做链接/一致性/`git diff --check`，无需新增措辞断言测试。

### T1 — 先修复小幅值频谱自动 Y（F01 / R01 / A01～A03）

**优先级：P1。依赖：T0。** Owner：PgLineCanvas。

- [ ] 迁移 `test_small_linear_auto_y_tracks_visible_window` 的最小复现至 `tests/ui/test_spectrum_interaction.py`，先确认旧代码失败。
- [ ] 扩展为量级/单位等比参数化，断言实际 viewRange 包含 raw 有效极值；覆盖边界插值、常量/单点/NaN/空窗及 manual Y。测试不只断言 `_fit` 被调用或返回 True。
- [ ] 去掉固定绝对 `1e-9` 对真实变化的抑制。依据 pyqtgraph 往返范围行为选择精确规范化去重或相对/ULP+包含约束；记录选择理由。
- [ ] 若增加“最近实际应用目标”，放在既有 spectrum 状态 owner，列明用户改 Y、结果更新、clear、View 恢复和销毁的失效；没有必要就不引入字段。
- [ ] 校验 Home/历史/resize/restore/export flush、raw 输出不变，manual Y 不做自动查询；保留 timer 和 AA 合同。

**Focused：** `tests/ui/test_spectrum_interaction.py`、`test_spectrum_display_cache.py`、`test_pg_line_canvas.py`；`tests/signal/test_display_range_index.py`、`test_display_ranges.py` 的直接合同。若中立算法未改，不新增一套镜像算法测试。

**Boundary：** `tests/ui/test_pg_canvas_backref_invariants.py`；若动到中立模块，再加 `tests/test_signal_no_gui_import.py`。修改共享范围消费者时加对应 Batch renderer owner。

**原生门：** 生产 QSS 的 Cocoa 重放 A01、A03，截图检查主图数据可见，另比 raw/data export。性能单独留到 T8，不在 offscreen 报 FPS。

**完成标准：** 原失败变绿，所有量级满足包含不变量，既有无重复扫描/setData 合同保持。回退仅撤销新 no-op 策略，不恢复错误的 fixed epsilon。

### T2 — 通道恢复一次遍历（F02 / R02 / A04～A05）

**依赖：T0。** Owner：channel tree。

- [ ] 将身份读取计数 probe 迁入 `tests/ui/test_channel_filter_context.py`；保留 500/1k/2k 与增加 10k 的尺度检查，计数线性约束优先于机器耗时阈值。
- [ ] 只记录有展开意义的节点；用一次 live 遍历构造局部复合身份索引或直接应用快照。滚动锚点查询复用该索引。
- [ ] 检查 `_tree_item_for_data` 其他批量调用，特别是 replace-file 展开恢复；有同类证据才纳入本 owner 的同一局部实现。
- [ ] 覆盖同名异源、分组节点、锚点删除、清筛选排队期间更换 View/删文件/重建/关闭；不得恢复旧 checked 或改变已绘曲线。
- [ ] 保留 generation 和 deferred timer 生命周期；不持久保存 QTreeWidgetItem 引用。

**Focused：** `tests/ui/test_channel_filter_context.py`、`test_channel_widget.py`、`test_channel_widget_setters.py`。

**Boundary：** 仅修改本 owner 时运行 `tests/ui/test_no_lambda_signal_connections.py`；若新增公共 import，再运行 `test_import_boundaries.py`。

**原生门：** Cocoa 大通道树实际清筛选，对照滚动位置、展开与 checked，不仅调私有 restore。记录 GUI 阻塞耗时，计数测试作为确定性回归门。

**完成标准：** 身份工作量 O(N+K)，2k 不再出现 200 万次读取；上下文恢复合同不退化。

### T3 — 选择控件的最终状态与同步通知（F03 / R03 / A06～A08）

**依赖：T0。** Owner：chart cards，其他控件按证据纳入。

- [ ] 将 TimeChartCard 两个失败模式迁到 `tests/ui/test_chart_selection_slide.py`；增加 FrequencyCursorCard 实际焦点目标的同步重定向测试。
- [ ] 用通知槽断言 checked、业务模式、indicator 目标已经同步；覆盖槽内改选、禁用和 Qt 对象销毁，不用 sleep 模拟慢业务。
- [ ] 对确有“emit 后按旧 mode 再 follow”的 owner 调整局部顺序，保持原 signal 参数和次数；通知返回后不补放旧状态。
- [ ] 横查 Toolbar、MethodButtonGroup、SegmentedChoice、PillSwitch；已正确的实现只跑适用回归。尤其检查 canvas setter 自身可能同步通知的边界，不能只看外层 signal。
- [ ] 保留分屏焦点路由、程序 snap、重复点击、off/reduced、有效 disabled 状态；明确 View marker 必须等 manager 确认。

**Focused：** `tests/ui/test_chart_selection_slide.py`、`test_toolbar.py`、`test_batch_method_buttons.py`、`test_pill_switch.py`；`tests/ui_kit/test_segmented_choice.py`、`test_selection_indicator.py`；根据实际 owner 精选运行，未改 owner 可复用 T0 结果。

**View 确认门：** `tests/ui/test_view_marker_activation.py`、`test_view_tabbar.py`、`test_view_switch_reentrancy.py`。MainWindow 实际接线改变时再跑状态所有权门。

**Boundary：** lambda ratchet；QSS 若变化再跑 `tests/ui_kit/test_qss_border_shorthand.py`。不得为此次逻辑修复随意调样式。

**原生门：** 生产样式，Cocoa 在动画结束后自动检查 target/checked 和局部截图；同步重定向后没有文字与底板分属两个按钮。真实 driver start 与首位移 paint 时间线留给 T8。

### T4 — Batch 诊断完整与结果可信度（F04/F05 / R04/R05 / A09～A10）

**依赖：T0。** Owner：Batch result projection / Sheet configuration lifecycle。

- [ ] 在 `tests/ui/test_batch_result_details.py` 先加入 run warnings+items 和真实 filter switch 的两个失败用例。
- [ ] 用独立 run rows 投影 warnings/blocked reasons，保留 group/item 归属；添加空 items、混合 group、取消、未知状态、同文异来源和详情复制断言。
- [ ] 列出所有输入/方法/参数/输出的 user mutation 入口与程序投影入口。核对 filter、时间、源删除、恢复默认值的实际信号，完成一张接线表后再改代码。
- [ ] 将成功用户变更汇入现有 `_on_user_configuration` 或等价 owner 内入口；若必须区分 InputPanel.changed 原因，做最小向后兼容扩展并更新全部消费者。
- [ ] 保持 suspend 配对、stale 幂等、no-op 与元数据到达不误标、冻结结果不变；结果详情开关/选择/复制不触发运算。
- [ ] 若新增或改名用户可见诊断入口，同步 hints 和 quickref；不重排已调好的 Batch 面板/按钮。

**Focused：** `tests/ui/test_batch_result_details.py`、`test_batch_input_panel.py`、`test_batch_output_panel.py`、`test_batch_smoke.py`；涉及 filter switch 时加 `test_batch_switch_motion.py`。文案合同变化加 `test_hints.py` / `test_quickref.py`。

**Boundary：** `tests/ui/test_import_boundaries.py`、`test_no_lambda_signal_connections.py`。本任务不改 runner，因此不泛化跑 orchestration gate；若实际范围被批准扩入 runner，必须另加 `tests/test_batch_run_reporter.py`。

**原生门：** 完成后改滤波/时间/移除来源，标题马上变“上次运行结果”，rows 内容保持；run 级诊断可读可复制，窄窗/长文本不挤掉关闭和复制入口。

### T5 — 取消独立范围恢复入口（F06 后续决策 / R06 / A11）

**依赖：核对当前实际代码及其他在途改动。** Owner：分析页面和专用 UI 接线。

- [x] 删除范围状态条、按钮、专用恢复 callback/method 和提示刷新接线；保留所有范围保存、恢复及现有计算逻辑。
- [x] 现有 restore-button 测试改用真实计算按钮，保留逐轴 origin / View 往返验证；增加 Home 保留手动参数、计算按钮恢复该范围的实际操作断言。
- [x] 更新 hints / quickref 和本 Spec；原 Review 保留历史发现并注明入口已取消，不将历史复现改写为从未发生。
- [x] 同机 Cocoa 对照 Home 后页面布局，确认被删除行不再占用高度，图形与 View 栏直接衔接。

**Focused：** `tests/ui/test_analysis_section_page.py`、`test_analysis_view_state.py`、`test_analysis_auto_range_production.py`、`test_analysis_viewport_cold_restore.py`、`test_hints.py`、`test_quickref.py`；`test_analysis_multiview_integration.py` 的 viewport / ChartOptions 节点。

**Boundary：** `tests/ui/test_main_window_state_ownership.py`、`test_import_boundaries.py`、`test_no_lambda_signal_connections.py`。不新增 owner whitelist，不因删除入口运行全套。

**完成标准：** 状态条与按钮消失且无空白占位；Home 查看全图、真实计算按钮按参数显示。已有非本次失败单列，不用顺带调整几何阈值掩盖。

**本轮验证：** focused 为 **190 passed / 1 failed**；唯一失败 `test_split_fft_time_heatmap_and_slice_plot_areas_align` 在改前同样失败，两侧宽度始终为 451.659375 / 459.51875，属于已有时频分屏对齐问题。适用边界 **17 passed**。生产 QSS 的 Cocoa 对照前后各 **1 passed**：Home 后状态行占高 **39→0 逻辑像素**，按钮消失，全图 X/Y 范围完全一致；实际计算按钮可返回手动参数范围。证据：`.state/remove-range-restore-20260912/`。未跑全套或 Windows frozen。

### T6 — 保存真实 X 标签来源（F07 / R07 / A12～A13）

**依赖：T0。共享 `_view_mixin.py` / `window.py` 与 T7 串行集成。** Owner：Custom-X 意图。

- [ ] 在 `tests/ui/test_time_channel_drop.py` / `test_view_switch_integration.py` 迁移同名手写失败路径；必须经过 textEdited→真实 Apply→capture/restore→time。
- [ ] 在 `ui/time_xaxis.py:CustomXAxisSpec` 定义 origin 字段及旧 payload 兼容规则；先查所有构造、replace、to/from-axis-options 和项目持久化消费者，列出迁移表。
- [ ] UI 编辑明确写 user，拖放/选通道生成明确写 auto；apply/restore 消费 spec origin，不再用文本相等覆盖新用户意图。
- [ ] 保持公开默认构造和旧项目读取；新保存包含 origin。若需要 schema 版本变化，同步实际版本测试，不能另造产品版本常量。
- [ ] 覆盖同名/异名、空标签、模式切换、PER_SOURCE_NAME/EXACT_SOURCE、失去来源的降级；程序 restore 不误发 user mutation。

**Focused：** `tests/ui/test_time_xaxis.py`、`test_time_channel_drop.py`、`test_view_switch_integration.py`、`test_project_dirty_guard.py`；新增 round-trip 放实际项目序列化 owner 测试中，先确认路径而非预设新测试框架。

**Boundary：** `tests/ui/test_import_boundaries.py`、`test_main_window_state_ownership.py`；如中立路径变更补独立 import probe。

**完成标准：** 新状态来源可逆 round-trip，旧状态兼容行为明确；不承诺恢复旧 payload 从未保存的手写来源。

### T7 — 与当前 Section / motion 在途工作集成（G02 / R08 / A08/A14/A15）

**依赖：T1/T3/T5/T6；T0 已确认的在途 owner。** 协调者独占共享文件的集成。

- [ ] 更新当前 follow-up 的执行状态：`9cda71ad` 的 Toolbar 局部顺序已修，未完成的是实际 paint/横向边界。旧日期性能记录不改成新成功。
- [ ] 确认 motion 320/400 的最终接受值，同步 constant 与消费者测试；测试应验证已批准合同，不能为绿灯删除必要断言。
- [ ] 运行 FFT reveal 的 show/hide/clear/几何变化、rapid section switch、立即复制/export、关闭和 generation 场景；断言真实 paint 前不提前 settle。
- [ ] time gate 检查 busy→leave 重放、重复合并、View 删除/切换、项目打开/关闭、UltraView 同步；避免 `processEvents` 重入与遗漏 finally。
- [ ] FFT prepared facts 在同一调用逐字段对照，包含缺源/short/非均匀时间/auto-manual NFFT；确认实际 fetch 次数与 compute/job 次数。
- [ ] 合并后记录一个稳定快照，重新跑本次改变的集成 owner，不复用混杂时长候选的“156 passed”当整体通过。

**Focused：** 当前存在的 `tests/ui/test_fft_section_reveal.py`、`test_fft_facts_prepared_input.py`、`test_section_entry_presentation.py`、`test_time_section_entry.py`、`test_toolbar.py`、`test_view_switch_reentrancy.py`、`test_timedomain_mode_switch_empty_frame.py`；`tests/ui_kit/test_motion.py`、`test_selection_indicator.py`。

**共享 paint owner：** `tests/ui/test_pg_line_canvas.py`、`test_frf_canvas.py`、`test_pg_timedomain_canvas.py` 的适用 settle/paint timer 节点，不因改一个 quality hook 就运行全部 `tests/ui`。

**Boundary：** backref、state ownership、import、lambda、QSettings。涉及 scope/collection 调整时加 `tests/test_conftest_autouse_scope.py`。

**完成标准：** 当前 focused 合同无未解释失败；性能仍需 T8，不由逻辑 gate 推导流畅。

### T8 — 原生性能与其他 UI 验收（G01 / R09/R10 / A03/A16/A17）

**依赖：T1～T7 正确性门通过。** 一个协调者维护测量与平台矩阵。

- [ ] 固定最终候选、可比基线、生产 QSS/字体、隔离 QSettings、DPR、窗口尺寸、数据、依赖与探针哈希；前后哈希一致才接受结果。
- [ ] 利用既有 `scripts/probe_spectrum_interaction.py` 与 Section 探针，补齐自然 paint 时间线；无需再建平行框架。强制 repaint 模式只作诊断，不能冒充自然交互。
- [ ] 同机交错 A/B，按 Spec R09 的 warmup/样本数，覆盖 auto/manual Y、宽窗 HIT、窄窗/越界、wheel/resize、empty/small/cached Section。记录正确性快照、分位数、事件积压、trace rebuild/setData/fetch/compute 次数。
- [ ] 分别核对频谱 auto-Y −30%、manual-Y ≤10% 回退、time Section ≥20% 改善；历史绝对值只作对照。未达标给热点归因与 partial，不调整门槛或盲目新增跨 View 缓存。
- [ ] 五分区真实操作：分屏焦点、Home/历史、切片、View 切换、保存重开、立即复制/导出、关闭。对修改影响的 raw/结果/范围/身份做自动比对；不是只看截图相似。
- [ ] 真实客户文件可用时执行对应场景；缺文件标 UNVERIFIED。Windows 100%/150% 源码控件与 Full/Lite frozen 单列，不用 Cocoa 替代。
- [ ] 若发现另一个 owner 的新问题，先给最小复现、影响和新边界任务，再扩大实现；不因为“其他 UI 可能受影响”主动重写它。

**Full gate 条件：** 最终合并确实包含本计划多个跨边界产品修改时，可作为一次稳定集成门；仅一个局部修复时无需 full。启动前检查已有 pytest 与 cwd，同一快照不得并发两个 full。先运行主套件 `--ignore=tests/acquisition_ui` 至正常退出，再单独运行 `tests/acquisition_ui`。前后 fingerprint 变化、异常退出或 timeout 标 UNVERIFIED。无新修改或失败原因不重复全套。

### T9 — 证据与文档收口（R10 / A18）

- [ ] 新建实施验证记录，逐 F/R/A/T 列实际 PASS/FAIL/UNVERIFIED 与证据路径；Review 的原始发现不改成从未发生。
- [ ] 验证整个 Spec/Plan、代码符号、测试文件/节点、引用及过期字段；任务完成状态和实际实现一致。
- [ ] 核对 source snapshot、named-file diff、`git diff --check`、lessons 状态；仅对新的可复用复发模式记录教训，已存在的规则优先补真实回归。
- [ ] 报告产品已改内容、测试结果和未跑平台，不累加互相重叠的测试总数。
- [ ] 不自动提交/推送；如用户另行要求，重新检查分支与 diff，仅 stage 本任务明确文件，保留其他 dirt。

## 3. Gate 与交付判定

| Gate | 必须证据 | 通过标准 |
|---|---|---|
| G0 | 基线 / 哈希 / scope / 失败复现 | 当前快照可追溯，未混入其他任务变动 |
| G1 | A01～A15 对应 owner 回归 | 不变量、生命周期、来源和事务正确；原 probe 红→绿 |
| G2 | 适用架构边界 | import、state、Qt 生命周期/接线 ratchet 通过 |
| G3 | Cocoa 生产样式 + 几何/像素 | F01/F03 视觉失败消失；其他新增可见信息可读且一致 |
| G4 | A16 可比性能时间线 | 原性能目标达标，正确性及事件积压不退化 |
| G5 | A17 平台/客户矩阵 | 各平台独立记录；缺失项不能标 PASS |
| G6 | A18 文档及证据收口 | 无未解释失败、无历史通过数替代当前验收 |

局部任务可在 G0/G1/G2 和对应原生门通过后完成该任务。整体优化“全部落实”要求 G4/G5 所需证据闭合；平台或客户材料缺失时交付 partial，并准确列出未完成门。本轮取消入口的 T5 已完成；其他任务按各自实施记录判断，不能由 T5 通过推断整体验收完成。
