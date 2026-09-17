# 各 Section 页面切换动效扩展计划

- 日期：2026-09-16
- 状态：待实施；本次仅编写计划。
- 目标：将现有时域 View 动效扩展到 FFT、FFT vs Time、Order、FRF 内部 View 切换，以及五个 Section 之间的用户导航；保持正确性并控制额外显示成本。
- 当前 HEAD：`0bcac91e`；存在时域动效修复及 FFT 游标在途修改。实施前记录实际 HEAD、相关文件哈希和 dirty scope，保留其他任务成果。
- 前置：[安全与性能 follow-up](2026-09-16-page-transition-safety-performance-followup-plan.md)及其[验证记录](../verify/2026-09-16-page-transition-safety-performance-followup.md)。记录称时域生命周期修复已落地，但 Cocoa 性能/前台及 Windows 为 UNKNOWN；不据用户同意或 offscreen 通过推导已满足扩展准入。
- 执行：单协调者顺序集成，逐 Section 验收；本计划不要求并行 agent，不授权本次实施或自动提交/发布。

## 1. 范围与产品行为

| 用户操作 | 本轮目标 |
|---|---|
| 时域内部 View 切换 | 保持已有单 Pane 行为并做回归。 |
| FFT / FFT vs Time / Order / FRF 内部 View 切换 | 单 Pane、目标恢复合法且该类成本准入后，使用共享过渡。 |
| 五个 Section 之间切换 | 通过原导航 owner 捕获离开画面、正常提交和恢复，再交接到真实目标。覆盖双向路径，不只覆盖从时域出发。 |
| 缓存命中、未计算、缺源、stale、错误/空态 | 展示原来的合法结果或状态；不为动画发起计算，不借用上一 View 结果补画面。 |
| 项目打开/恢复、预设应用、初始化、同目标重复点击 | 保持直接终态；用户导航与程序恢复入口明确区分。 |
| 分屏任一端、多 Pane 结构变化、UltraView/Batch/采集 | 本轮直接终态；不扩大双 Pane 准入。 |

保持 300 ms、0 px；导航按钮、业务目标即时按原顺序确认，不等待动画结束。不新增 QSettings、自动播放队列、每 View 位图缓存或新动画状态机。只有局部图面交接，不让整个 MainWindow、Inspector 或导航按钮随旧截图滞留；复核当前 stack 截图是否含 View 标签/底栏，若含必须明确裁剪/层级边界，保证导航持续可见、可点击。

动画仍是显示优化，不承诺消除原有计算/绘制卡顿。性能不达标或能力缺失的路径直接呈现目标，记录具体未准入场景。

## 2. 当前实现缺口（已读源码）

| Owner / 符号 | 当前事实 | 扩展要求 |
|---|---|---|
| `main_window/window.py` 初始化 | enabled sections 仅 `time` | 最后按实测矩阵开放，不先打开全部 Section。 |
| `_analysis_mixin.py:_on_analysis_switch` | begin 仅 FFT、单 Pane；当前生产未开放 FFT | 使用各 section/view 的稳定身份，统一接入原 manager 提交顺序。 |
| `_on_analysis_view_switched` | target request 仅 FFT，且依赖 `facts_synced_by_render` | facts 返回值不是通用 paint-ready 状态；分别处理 cache hit、空态、deferred 和 retained reveal。 |
| `window.py:_on_mode_changed` | 原 Section 捕获后显隐页面，再应用来源/参数及恢复；未接跨 Section 动效 | 在旧图隐藏前捕获，目标布局/恢复完成后申请真实 paint 回执。 |
| `_render_time_section_entry` | 受 TimeRenderGate、View 对象身份、mode 和关闭状态保护的延后恢复 | 返回时域须等该真实事务完成；不能在 `_on_mode_changed` 尾部提前 ready。 |
| `PgLineCanvas` | 已有 `presentation_paint_acknowledged/request_presentation_paint_ack` | 补齐语义失效范围，验证 retained reveal/预览/空态。 |
| `PgFRFCanvas`、`PgHeatmapCanvas` | 有布局变化信号，没有上述自然 paint 协议 | 在真实 GraphicsView 绘制完成处补回执，不能用布局信号替代。 |
| `PageTransitionController` | 已移除 Paint 误取消，并在 ready 后冻结 input target updates | 原生像素、延后 freeze 的 token 绑定、所有退出 thaw 必须验证后才能推广。 |
| `ChartStack.request_page_transition_target` | content invalidation 监听目前可选 | 对新准入的 managed canvas 要求完整生命周期契约，缺失就直接终态，不能静默降低保护。 |

相关规则：[Paint 不等于内容失效](../../lessons-learned/overlay-paint-is-not-content-invalidation.md)、[延后 Section 恢复共用 RenderGate](../../lessons-learned/deferred-section-entry-shares-render-gate.md)、[分析来源归属 Pane](../../lessons-learned/codex-analysis-section-state-needs-pane-local-sources.md)。历史 lesson 的旧源码路径以本计划当前 owner 为准。

## 3. 共用控制器与职责

- `chart_stack/page_transition.py`：继续唯一持有进度、旧图、请求 token、输入保护、freeze/thaw 和释放；不查数据、不选 View、不提交计算。
- `chart_stack/stack.py`：局部覆盖区域、目标 canvas 集合、ready/失效连接、来源/目标的准入检查；不增加另一套业务状态。
- `main_window/window.py:_on_mode_changed`：只接已有跨 Section 导航事务的离开与到达阶段；需要提取纯呈现接线时放 ChartStack 显式接口，不扩大 window 状态簇。
- `_analysis_mixin.py`：内部 View 用户意图及已有 cache restore 完成接线；不复制各算法的渲染/计算逻辑。
- `pg_canvas/line_canvas.py`、`frf_canvas.py`、`heatmap_canvas.py`：拥有自身显示代际、几何、绘制回执和内容失效。时域仍由 `canvas.py` 拥有。
- 中立层/兼容 facade 不承担新实现；presentation token、Qt wrapper 和截图不写项目状态或预设。

若三个 canvas 的回执代码确实相同，可只提取无业务判断的窄 paint-fence helper；先证明协议等价，不为了名称统一重构画布继承体系。

## 4. 导航、就绪与失效协议

### 4.1 时序

1. 用户意图由原 owner 校验；重复目标、程序恢复、不支持布局、未准入负载直接走原路径，不抓图。
2. 保留原离开 View/来源/范围捕获顺序，在旧页面隐藏或被改写前取得一次合格局部离开图。source/target 共同纳入 token：Section、稳定 view_id、请求 generation、宿主几何/DPR、Pane 签名。
3. 原业务流程立即提交并恢复目标。动画不能改变 dirty、任务数量、cache pin、候选选择、坐标/参数恢复次数。
4. 目标恢复事务明确结束后，待真实 canvas 可见且最终几何有效，申请该 token 的自然 paint 回执。只有可见目标回执被接受；布局信号、`singleShot(0)`、facts bool 或计算完成本身都不等于画面就绪。
5. 绘制完后开始旧图淡出；空态同样需要合法绘制回执。无可用回执或目标已失效则撤层，不保留旧图等新计算。
6. finished 只释放；显式输入、身份/语义变化或生命周期失效则取消并恢复更新。

ready 只服务当前目标；在 pending 时用户再次导航由原 owner 接受最新目标，迟到 B 回执不能让 C 显示成 B。跨 Section 时 `set_mode` 的旧取消规则须与新 target 一致：目标页面的正常显隐不能误取消；离开目标、第三次导航及真实几何变化仍须取消或重定向。空间改变不能把旧截图拉伸冒充像素连续。

### 4.2 各 Section 特殊合同

| 目标 | 就绪条件 | 必须失效的事件 |
|---|---|---|
| Time | 延后 Section entry/原 View restore 完成，最终 X/Y 与 settle 后自然 paint | clear、来源/选择、重新绘图、View/范围意图变化。 |
| FFT | retained reveal 或 cache restore 的频谱和预览均为目标，最终显示参数/范围正确后 paint | 新结果、来源、幅值/dB/单位/计权、预览选择、范围/视图替换。 |
| FRF | 幅值/相位/coherence 等当前可见面板及状态统一恢复后 paint | set_result/set_state/clear、显示参数/范围、输入/输出来源或结果替换。 |
| FFT vs Time | 图像、时间/频率轴、色阶、colorbar、可见切片和状态一致后 paint | 新结果、color map/levels、切片方向/位置或开关、显示模式、clear/来源替换。 |
| Order | 阶次图、轴/色阶/切片与 RPM 来源/结果上下文一致后 paint | 同热图，并覆盖 RPM 来源、阶次结果和上下文替换。 |

实施前逐 owner 列 mutation → invalidation 表，以真实调用点为依据。语义变更在冻结控件前/变更开始时通知并 thaw；不能等被冻结的 widget 下一次 paint 才发现变更。点选 colorbar/切片、频率游标、工具栏参数等输入不一定落在同一个 viewport，要覆盖实际命中面与非图面 setter 通知。

异步任务继续按原结果 generation 提交：ready 后结果到达，先撤层/thaw 再原样显示合法新结果；旧任务丢弃规则不变，不为了动画丢结果、推迟提交或自动计算。热图/FRF 的多个可见子视口必须全部满足 ready，隐藏辅助视口不加入等待集合。

### 4.3 冻结、输入与捕获

- 每个 queued freeze 回调绑定其 token/generation；旧回调不得冻结新目标。记录每个控件原 updatesEnabled 状态；只恢复自己改变的状态，处理父子控件顺序及销毁。
- pending 不冻结必须产生首帧的目标；ready 后是否可安全冻结由各 canvas 原生证据决定。普通 Paint 不取消，正常质量 update 不作数据失效。
- 禁止假设时域 offscreen 冻结可直接推广到热图/FRF；检查真实 Cocoa 下透明层合成是否保留底图、是否黑白闪烁、揭盖时是否集中昂贵补绘。失败就不准入，不自动改用目标截图。
- pending 仅限制被覆盖图面；ready 首次图面输入先撤层后原事件一次。导航/关闭/取消继续有效，程序恢复直接终态。
- 显式复制/导出撤层后按原目标捕获；UltraView 沿用 ref/digest/稳定性 owner。快速重定向混合帧不得当作某个 Section 的正式预览，保存不持久化过渡状态。

## 5. 分批实施

### E0：固定前置与基线

- 固定当前在途修复稳定快照，阅读 follow-up 验证记录并补 Cocoa 原生 freeze/thaw 和性能证据。若原生不满足，先解决共享层阻断，再开放新 Section。
- 新增 `tests/ui/test_section_page_transition.py`（拟新增）作为扩展矩阵；冻结用户导航与程序恢复差异、计算调用数、最终 View/来源/范围/结果身份。
- 复用现有 probe，真实 MainWindow + 非空缓存/空态；临时证据放 `.state/section-transition-expansion/`，隔离 QSettings。
- 门：`test_page_transition.py`、`test_page_transition_integration.py` 受影响节点及原生小场景。无通用全量基线。

### E1：FFT 内部 View，打通首个新 Section

- 补 FFT 内容失效协议，复用已有自然 paint 回执；完善 cache hit/miss、仅预览、空态、retained reveal 的完成路径。
- 不把 `_render_analysis_view_from_cache` 的 facts 返回值改成模糊通用 ready；提供明确呈现完成通知，保留其原 facts 职责。
- 门：新增矩阵 FFT 部分；`test_pg_line_canvas.py`、`test_analysis_multiview_integration.py`、`test_section_entry_presentation.py` 相关节点；FFT 原生 Off/Light 成本通过后才开放此类导航。

### E2：Time ↔ FFT 跨 Section

- 接 `_on_mode_changed`，处理截图区域、导航不被旧图覆盖、隐藏/显示与 target token 的匹配。
- 返回 Time 在 `_render_time_section_entry` 实际完成后 request paint；忙碌门下等待已有 scope exit，不增加零毫秒轮询或 `processEvents()`。
- 门：新增双向切换/Time→FFT→Time 快速反向/中途删除；`test_time_section_entry.py`、`test_view_switch_reentrancy.py`、`test_section_entry_presentation.py`、UltraView 相关条目。

### E3：FRF 内部 View 与跨 Section

- 在 FRF 真实 paint 路径补自然回执/失效；冻结窗口覆盖全部已显示子图和合法空态。
- 接入同一分析 View 和跨 Section 通路，不复制 FFT 特例到第二个状态机。
- 门：新增矩阵 FRF 部分、`test_frf_canvas.py`、`test_analysis_multiview_integration.py` 来源/恢复条目及原生成本；与 Time、FFT 双向交接均验证。

### E4：FFT vs Time / Order 内部 View 与跨 Section

- 在共用 heatmap owner 补协议，分别验证两个业务 Section 的结果/来源，不能用同一个热图类推导两者全部通过。
- 覆盖切片开/关、colorbar 改变、图像更新、未计算/缺 RPM、异步结果到达、清空及关闭。
- 门：新增矩阵热图部分、`test_pg_heatmap_canvas.py`、`test_analysis_jobs.py`、`test_analysis_cache_pinning.py` 受影响条目；两 Section 原生性能分别准入。

### E5：组合矩阵与文档

- 五个 Section 共 20 个有向跨页组合，至少以小型合法缓存/空态做自动状态与像素终态对照；四个分析 Section 内部 View 分别覆盖。性能按不同渲染类别和已发现最差方向选择代表组，不能由一个方向外推全部。
- 多 Pane 路径验证直接终态且不抓图；正常单 Pane A→B→C、20 次反向、关窗/项目替换、结果到达时保证无等待连接/冻结/图像残留。
- 更新 `ui/hints.py` 和 `ui/quickref.py`，说明真实启用范围；不写“所有场景都有动效”。测试对应文案和宽度合同。
- 新增验证记录 `docs/analyzer/verify/2026-09-16-all-sections-page-transition-expansion.md`（拟新增），逐类记录启用/未启用、性能、Cocoa 和 Windows 状态。

## 6. 性能与回归门

沿用前一 follow-up 的全部预算，不因扩展放宽：目标 ready P95 增量 ≤10 ms，overlay paint P95 ≤4 ms，60 Hz 参考 paint 间隔 P95 ≤20 ms；Light 稳定 P95 ≤Off+300 ms+20 ms；Off 回退 ≤max(10%,5 ms)，事件 lag 增量 ≤max(Off 的10%,5 ms)。>50 ms 主线程停顿及揭盖后延迟重绘单独报告。峰值图像内存含临时副本 ≤64 MiB，不把 retained bytes 当峰值。

每组 5 次预热、至少 30 个样本，冷路径独立；测源截图、目标恢复、图面自然 paint、overlay、下层曲线/图像 paint、thaw 和 UltraView 尾部。输入回调、ready 和用户看清目标分别记时，不能把 300 ms 隐藏在统计之外。

- 每次合法交接最多一次离开捕获，目标捕获为 0；每帧新增 prepare/FFT/滤波/plot/setData/数据扫描为 0。
- 新 Section 的目标恢复与原 Off 保持同样业务调用数，未计算页面不新建任务；cache pin、结果身份、轴/单位/dB、FRF 相位/coherence、Order RPM 上下文均一致。
- 图像大小、DPR、数据/曲线/图像复杂度、切片状态纳入成本证据。准入检查必须在 source capture 前；某个昂贵 source 不能因 target 很轻而获准。
- 不把 `enabled_sections` 同时包含 source/target 当作任意边均合格。复用 ChartStack 的呈现准入 owner，以导航种类、源/目标能力、布局与已测条件判定；不建设持久化成本数据库或运行时全量签名。
- 缺协议、失效保护不完整或超预算直接终态，记录原因；不首次同步抓图卡住后再声称超时保护生效。

边界测试按实际变更运行：`test_no_lambda_signal_connections.py`、`test_main_window_state_ownership.py`、`test_import_boundaries.py`；触及 canvas collaborator 时 `test_pg_canvas_backref_invariants.py`。时域 restore/discrete settle、FFT/FRF AA 与 paint backstop、热图切片范围/色阶仅跑相关 owner 条目，不扩大为全 UI suite。集成节点实施前确认收集结果，0 selected 不算通过。

UI 检查使用项目 runtime、临时配置与正常 Qt teardown；offscreen 做功能/几何，不作性能准入。Cocoa 前台像素、输入和性能须单独通过；Windows 源码、Full/Lite、100%/150%/200% 独立记录，缺席保持 UNKNOWN，不能宣称跨平台完成。默认不跑 full suite；仅新证据要求时记录原因后按仓库规则顺序执行。

## 7. 完成标准和本次交付

完成需要逐 Section/导航类别列出：已接入、功能验证、性能准入、实际启用、平台缺口。正常 paint 不误取消，真实结果更新不被冻结掩盖；所有结束/取消/重定向路径恢复 updatesEnabled 并清理临时连接/图像。用户导航终态与 Off 一致，计算量不因动效增加。

任何类别未达准入可保持直接终态，但总任务应标 partial，并给具体阻断证据；不能用“已加进集合”表示扩展完成。本次仅新增计划，检查引用/owner/范围与 `git diff --check`，不修改产品代码、不执行上述实现门。

## 当前执行台账（2026-09-17）

上文「待实施」是 9 月 16 日编写时状态，保留。扩展实现与五区全开已在后续提交落地，验证记录见 [2026-09-16-all-sections-page-transition-expansion.md](../verify/2026-09-16-all-sections-page-transition-expansion.md)。2026-09-17 审查修复 F1/F2：目标缓存身份与 Off 廉价门；Cocoa 30 样本与 Windows 仍 UNKNOWN，总体仍 partial。
