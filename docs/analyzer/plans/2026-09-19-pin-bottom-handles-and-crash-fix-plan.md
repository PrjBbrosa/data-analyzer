# Pin 底部按钮、多面板与闪退修复计划

- 日期：2026-09-19。
- 状态：计划已编写，产品实施未开始。本次授权范围为写 plan，不执行产品修复。
- 当前核对基线：HEAD `c75c47e3`；已有本轮分析文档修改、新 demo 和无关未跟踪文件。执行前重查，不覆盖别人的修改。
- 执行方式：单协调者按任务依赖顺序执行，不要求并行 agent。
- 依据：[分析与崩溃证据](../reviews/2026-09-19-pin-layout-and-crash-analysis.md)、[交互 demo 的 A 方案](../ui-prototypes/2026-09-19-pin-in-chart-options.html)、用户最后一张截图及“这些按钮或者多余的东西不要了”。
- **最后一张截图优先于 demo**：删除整条额外 Pin 工具栏；demo 中仍存在的数量提示、上方编号索引、操作说明、“＋ Pin”“全部收起”以及实验控制按钮，都不是产品目标。

## 1. 最终交互契约

### 1.1 界面只保留必要入口

1. 左侧文件/通道、右侧图表设置保持现有空间。不开新侧栏，不收起 Inspector 来换空间，不做 B/C 比较带或单卡方案。
2. **不新增 Pin 工具栏，不占一个空白行**。用户截图中的“3 个 Pin · 点击底部按钮展开，左右拖动微调”、上方 P 索引、“＋ Pin”和“全部收起”均不落地；移除后绘图区直接接原有图表工具栏。
3. 创建仍走现有合法上下文中的 **P 键**。不新增“＋ Pin”或双击图表创建入口；后者只是 demo 的便捷操作，不能覆盖现有图表双击行为。
4. 底部数据位置附近的 **Pn 按钮**是展开/收起、横向微调入口，配合同一记录的竖线。数量不是新工具条内容。
5. 简短说明放在按钮 tooltip、已有 hints/quickref；操作失败使用已有反馈通道。不新增常驻说明条、成功计数、批量收起或管理面板。

### 1.2 操作表

| 操作 | 结果 | 必须保持 |
| --- | --- | --- |
| 按 P 新建 | 固定记录、竖线、底部 Pn；面板默认收起 | 原捕获时刻、绑定通道、重复 P 检查、编号规则 |
| 点击底部 Pn | 只切换该记录的展开/收起 | 其他 Pin 的展开状态、位置、坐标不变 |
| 同时点击 P1、P2、P3 | 三张面板可同时展开，独立操作 | 不变成只能打开一张的互斥模式 |
| 拖底部 Pn 左右移动 | 修改这一条记录的数据坐标；线、标题、读数一起更新 | 不开关面板，不改变记录 UUID、序号、通道集合 |
| Shift + 拖动 | 指针增量按普通拖动的 1/10 精调 | 中途按下/松开 Shift 不跳位置 |
| 聚焦底部按钮后 ← / → | 按所属坐标域做小步调整 | 仅按钮焦点内接管，不新增全窗口快捷键 |
| 拖面板标题 | 只改变该面板摆放 | 数据坐标、读数、Pn 位置不变 |
| 面板原有 ＋/− | 保留 full/mini 切换 | 不复用为“收进 P 按钮” |
| 面板原有 × | 删除这条记录及其所有投影 | 不删除别的 Pin、不重编号 |
| 面板原有取消固定 | 沿用当前 unpin/候选交接 | 不因这次改动重做取消固定语义 |
| 普通缩放/平移/Home/Fit | 仅重投影 | Pin 物理坐标不变，不等同于拖动 P 按钮 |

**消除 demo 的歧义**：demo 标题“−”曾表示收起，但生产 `CursorPill._toggle_btn` 已承担 full/mini。落地保留已有按钮含义；收起统一点底部 Pn，不增加另一个标题按钮。展开/收起与 full/mini 是两个独立维度。

### 1.3 默认值、恢复与身份

- 新 Pin 默认 `panel_expanded=False`；旧工程没有该字段时也默认收起。用户明确展开过的记录，切 View/分屏、保存重开后恢复该意图；不能每次 replot 全部弹开或全部收起。
- 建议字段名 `panel_expanded`，属于 `PinnedCursorIntent` 的可保存用户展示意图，独立于 `presentation=full/mini`、运行时可用性及临时空间不足。
- collection 仍由已有 ViewState/PaneState 与 bridge 管理；controller 持有现有绑定投影。不得另建一份 MainWindow 展开列表或全局按“P1”索引的字典。
- 记录身份仍是 owner/scope + record UUID；Pn 只是展示编号。Pin 跨过另一 Pin、取消/恢复展开、拖动到相同位置，不合并、不重编号。
- 拖动到已有 Pin 的位置允许并存；新建 P 的既有去重规则不变。复制 View 仍换 scope/record UUID，保留局部编号与展示意图。

## 2. 当前代码事实与改动归属

以下行号是计划编写时定位，执行时以符号为准。

| 文件 / 符号 | 当前事实 | 本轮职责 |
| --- | --- | --- |
| `ui/pinned_cursor_state.py:90` `PinnedCursorIntent` | 已有坐标、full/mini、anchor，没有独立展开字段；payload version=1 | 增加 optional 展开意图、规范化与往返，保持中立导入 |
| `ui/chart_stack/pinned_cursor_controller.py:987` `_project_record` | 创建/刷新时要求 pill 可见，继承 live 位置 | 默认不展开；按记录展示意图投影，显式展开时排布 |
| 同文件 `:366` `raise_record`、`:2066` `_project_axis_labels` | label click 只置顶；绑定只传 record ID | 接入独立 toggle；拖动事件保留端点身份 |
| 同文件 `:804` `_physical_x`、`:857` `_evaluate`、`:896` `_evaluate_intent` | 已有领域坐标变换和中立事实查询 | 复用求值，不复制 DSP；补底部轴按钮的 X 映射适配 |
| 同文件 `:1354` `_mark_user_intent` | 现有 revision + intent_changed | 提交成功一次通知，预览/取消不伪造用户提交 |
| `ui/pg_canvas/pinned_cursor_overlay.py:432` `PinnedAxisLabel` | 当前只有 click/hover，release 即 click；簇成员缺端点动作合同 | 指针阈值、捕获/取消、焦点键盘、稳定单记录/端点命中 |
| 同文件 `PinnedLabelGeom` / `PinnedOverlayEndpoint` | 几何中已有 endpoint/物理位置；簇 member 目前仅 record/text/ordinal | 不能在簇路径丢失 A/B；维持真实物理点与标签位置分离 |
| `ui/chart_stack/cursor_pill.py:480` `setVisible` / `awaiting_space` | 已区分请求显示与空间暂不可见 | 不把用户收起误判为等待空间；保留真实文档测量 |
| `ui/chart_stack/stack.py` / `ui/analysis_section_page.py` | 已有多 pill 捕获/合图与 owner 安全区域 | 复用；复制只含实际展开面板，底部 P/线保留 |

不把新实现放进 `ui/pg_canvases.py` facade；不把图形映射塞入中立模型。当前 controller 较大不是本轮拆分理由。

## 3. 先修闪退：坐标域与 Qt5 方向

### 3.1 证据及置信边界

- 系统报告 `~/Library/Logs/DiagnosticReports/Python-2026-09-19-164137.ips`：主线程 `QWidget::mapTo`、`SIGSEGV`、访问地址 `0x28`，调用链含 QTimer。
- 先前独立 offscreen 进程直接调用生产 `_sync_leaders`，在 `pinned_cursor_overlay.py:1211` 得到 **exit 139**；`canvas` 确实是 `_glw` 的祖先。
- 安全方向对照 `glw.viewport().mapFrom(canvas, point)` → `glw.mapToScene(...)`：坐标往返 True、**exit 0**。探针 `.state/probe_pin_mapto.py` 只作临时证据，必须转为持久 subprocess regression。
- 本轮源码重查：`_sync_leaders` 两处 `canvas.mapTo(glw, ...)` 仍在；controller `_in_data_viewport` 也仍有三处 `canvas.mapTo(canvas._glw.viewport(), ...)`，其中 `mapped` 未使用。
- 这证实当前生产方法有可致崩缺陷；原始事故没有 Python 行号，不能声称已重放用户完整操作。当天 12:16 的 `sip_api_visit_wrappers` 退出清理崩溃属于另一类，记录为独立未解决事项。

### 3.2 修复要求

1. 父→后代转换使用后代的 `mapFrom(ancestor, point)`；无祖先保证时用明确 global round-trip。所有 `mapToScene` 输入都先转换到 **QGraphicsView viewport**，不能混用 view frame/widget 坐标。
2. 修引导线和频谱命中两个已定位 owner；删无用但仍可能崩溃的转换。读取真实 hierarchy，验证非零 layout margin、frame 和 viewport offset。
3. 保留必要的 Qt 存活/teardown 保护，但不能用 `try/except`、`sip.isdeleted` 掩盖方向错误；原生 SIGSEGV 不会变成 Python 异常。
4. Qt 原生失败回归必须隔离进子进程，超时明确 fail；断言退出码、无 SIGSEGV、正确坐标。不要让 pytest 主进程承担故意崩溃。

## 4. 底部拖动是一条独立事务

### 4.1 owner 与输入合同

- `PinnedAxisLabel` 负责原始鼠标/键盘输入和逻辑像素阈值；controller 负责语义事务。计划接口为 `begin / preview / commit / cancel`，事件携带 record UUID、endpoint 和 global pointer position，具体命名在 owner 内保持现有风格。
- 事务持有 owner/scope、canvas binding generation、数据 revision、record ID、端点、原始 intent、起始/上次指针及候选事实。仅 controller 的 owner state 持有；delete/unbind/hide/data invalidation 对称取消。
- 按下尚不改坐标；水平移动超过 `QApplication.startDragDistance()` 后进入拖动。生产采用平台阈值，**不照搬 demo 的 3px**。未越阈值释放只 toggle，一次拖动释放绝不能补发 click。
- 指针 capture 从按下保持到结束；重投影不能销毁/重绑正在拖动的 handle。密集标签重排不能把 P1 变成 P2，也不能在按下时先移走目标。
- 只监听按钮/所属 host 的相关事件，不把全局 MouseMove 加回应用级 P 过滤器。拖动时屏蔽所属画布 pan/zoom、P 新建及 live hover 响应；其余 owner 不受影响。

### 4.2 坐标、精调与读数

| 域 | 横向拖动 | 焦点左右键 |
| --- | --- | --- |
| Time-X | 视口位移通过当前 X 变换得到时间；复用已有单/双点取样 | 每次请求 ±0.001s，不捏造采样率；输出仍服从已有求值合同 |
| Custom-X | 修改指定 X 通道的工程坐标，保留 axis_identity/分支诊断 | 一个逻辑像素对应的域增量；不得套用“秒” |
| FFT | 请求频率交给现有参考网格吸附，采用返回的有效坐标 | 相邻有效参考频点；不同曲线仍各自网格取值 |
| FRF 线性/对数 | 通过现有 view-X↔Hz 转换；持久化真实 Hz | 相邻有效频点；不对 log10(f) 直接加 Hz |

- 底部按钮位于轴标签带，不能把其 Y 坐标直接交给 `_physical_x` 的“数据区命中”判断。使用所属数据 ViewBox 的横向映射，Y 选取合法数据区内部位置；全过程注明 global→viewport→scene→data。
- Shift 的 1/10 作用于每次新增的屏幕 X 位移，再做领域变换。拖动开始记录按钮与真实端点的偏移；标签因避让偏离竖线时，开始拖动不能突然跳到标签中心。
- 单点只更新 x；双点 Pn·A/Pn·B 只更新命中的端点，不平移整组、不自动交换 A/B。A=B 时保留两个可明确选择的端点操作目标；A>B 仍保留差值符号。
- 复用 `_evaluate_intent`/领域事实接口并保留 captured bindings。线、标题、读数及极值以同一候选坐标、同一 revision 原子投影；频率吸附后使用同一有效频率。
- 指针移出数据区不自动平移窗口、不吸附到别的 Pin。拖动候选限制在开始时可见范围和明确可用的 X 域内；范围/坐标域变更则取消。禁止 NaN/Inf、非法对数频率；数据缺口/无值保留既有诊断，不填 0、不连接 Custom-X 不连续支路。
- pending/incompatible/unrepresentable 状态允许展开、收起、删除，但禁用坐标编辑并通过 tooltip/现有状态栏说明。起点在视野外的方向标签可开关面板，不把边界像素当原点拖动；用户把该位置移回视野后再微调。

### 4.3 提交、取消与性能

- move：只投影临时候选；最多每 GUI 帧合并一次求值，只求当前记录；不创建新的采样算法、不重算 FFT/FRF 整体结果、不采样其他 Pin。
- release：同步处理最后一个指针位置，校验 owner/revision，再一次写入 collection、刷新事实/标记/摘要、发一次 `intent_changed`。有效坐标没变则无脏标记。
- Esc、窗口失焦、按钮丢失 capture、切 View/模式/数据 revision、关闭文件/owner：取消预览，恢复原意图；owner 已销毁则只清理，不重新创建控件。
- 键盘一次有效步进是一次提交；autorepeat 可以步进，但不得改展开状态。Esc 不是删除 Pin。
- 预览与捕获不能混出“旧坐标、新数值”：现有稳定捕获/UltraView 在事务期间延后该 owner 刷新，提交或取消后按既有 idle 机制刷新；工程序列化始终只读已提交意图。
- 拖动期间不得每帧重建全部 P 按钮、面板/QTextDocument 或全局 reflow。重排只在显式展开、内容尺寸/宿主改变时进行；移动 P 时面板位置保持，仅引线和内容变化。

## 5. 几何、颜色与拥挤

1. 底部 Pn 仍在原 X 轴附近的独立装饰层，不成为数值 tick，不遮住 tick 字形或轴标题。热区足够点击/拖动，绘制位置和命中区域同源；不依赖缩小文字塞下。
2. 首次展开优先靠近对应位置寻找空位；按**完整卡片矩形**避让图例、其他面板、底部按钮及既有 popover。不再继承 live pill 的统一中心位置作为每张默认位置。
3. 后续展开不移动用户手放的旧卡；自动位置在同一 geometry 内保持稳定。只有新卡找不到位置或窗口变小，才进行一次有界重排；保留用户 anchor 与实际 clamp 后显示位置的区别。
4. pinned 面板不透明白底，消除下层文字透出；live pill 视觉合同保持。使用同一份实际 QTextDocument 做测量与绘制。
5. 多通道沿用 full/mini 与现有表格预算/完整行降级；最小可读状态须有完整标题及至少一条完整内容行。**不照搬 demo 为挤下 8 张而把每张压成半行内容的行为**。
6. 最少验证正常窗口 3 张长名称面板同时展开。1/2/8/20 Pin 都不能丢记录；极小空间用既有 `awaiting_space` 表示用户请求展开但暂不可绘制，底部按钮保留并说明状态，空间恢复后兑现。不得偷偷将 `panel_expanded` 改回 False，也不承诺任意数量完整面板同时可见。
7. 密集底部按钮优先有限多行错开，保留指向真实 X 的细引线；必须能点/拖每个记录和双点端点。极密时仅在底部局部展开成员入口，可滚动访问；不能新增全宽索引栏，不能用聚合标签代替成员编辑。拖动中冻结该成员身份及 capture，结束后再排布。
8. 默认 single Pin 线从当前低 alpha/1px 提升为清晰蓝灰虚线，初始设计值 `#54749d`、1.5 逻辑像素、不额外降低 alpha；选中/拖动用 `#006bea`、2–2.5px。最终以 Cocoa/不同 DPR 的实际像素确认，不改网格颜色遮掩问题。
9. dual 保留 A/B 颜色和线型区分；通道自身颜色不变。所有同 record 的面板、按钮、线同步高亮，不能仅靠颜色表达展开状态。标签显示展开/收起标志，焦点可见。

## 6. 状态与输出兼容

- 在现有 payload version 1 中添加可选 boolean `panel_expanded`，旧缺省为 False；非 bool 显式诊断后使用 False，不能以字符串 truthiness 将 `"false"` 当 True。默认 False 可省略序列化，避免给旧未编辑记录制造无意义 diff。
- 不为这一可选展示字段升级外层工程 schema/分析 schema 或产品版本。若实际 codec 不支持可选字段则先报告证据并修订这项策略，不能未经检查自动升版。
- `_intent_to_dict/_parse_intent`、clone/remap、View/Pane round-trip 必须保留字段；不保存 drag transaction、hover、控件、临时 clamp、candidate sample。
- 用户展开/收起、坐标成功提交和标题拖动完成走现有用户意图变更通道；自动重排、hover、pending 和取消不使工程变脏。用户操作后回到与原状态相同值应满足现有 canonical digest 规则。
- 重绘、滤波、分析重算、隐藏再显示只刷新 facts，不强制展开；结果晚到须校验当前 record/坐标 revision，不能覆盖更新后的 Pin。
- 复制图片与主/副分屏、分析合图：收起状态只合成线/底部按钮，展开状态再合成面板一次。保留离屏方向标记和不可用诊断；不因布局暂不可见删意图。
- `capture_fingerprint_for` 加入稳定的 `panel_expanded` 及提交后坐标；展开/收起能让 UltraView 更新，纯 hover/拖动候选不能触发逐帧重新抓图。

## 7. 实施任务与聚焦门槛

### T0 — 核对基线与冻结目标行为

- Owner：现有 Pin 测试及本 plan。先核对 HEAD、dirty、字段版本和关键 symbols；不先跑全套。
- 在既有测试文件中增加默认收起、独立展开、拖动不 click、取消不脏和坐标同帧的失败用例。原有捕获/几何测试若依赖“P 后自动展开”，显式展开再验证其原命题，不能删除捕获断言。
- 读 [Qt5 映射教训](../../lessons-learned/qt5-mapto-descendant-native-crash.md)、[真实文档几何教训](../../lessons-learned/cursor-layout-tests-must-use-painted-document.md)。
- Gate：新用例所在的 `tests/ui/test_pinned_cursor_panels.py`、`test_pinned_cursor_interaction.py` focused nodes；保留失败原因。此任务不做全量 baseline。

### T1 — 修原生崩溃（先于新拖动）

- Owner：`ui/pg_canvas/pinned_cursor_overlay.py`、`ui/chart_stack/pinned_cursor_controller.py`。
- 固化生产 leader/频谱命中 subprocess regression；修方向和 viewport 域。覆盖非零 margins、贴边/密集标签、频谱图区与时域预览排除。
- Gate：`tests/ui/test_pinned_cursor_geometry.py`、`test_pinned_cursor_interaction.py` 的对应现有及新增节点。崩溃用例只在子进程；若改 collaborator 声明，加 `test_pg_canvas_backref_invariants.py`。
- 完成标准：从可复现失败转为正常退出且坐标正确；不能只断言“不 crash”。

### T2 — 独立展示意图与默认收起

- Owner：`ui/pinned_cursor_state.py`、`ui/chart_stack/pinned_cursor_controller.py`、`ui/chart_stack/cursor_pill.py`；必要时已有 bridge/codec。
- 加字段、默认/恢复/复制；投影根据 expanded 状态决定显示。新建仍保留线/按钮/facts；不借用 `presentation=mini` 代表收起。
- 底部按钮 toggle 接到 controller；保留原 full/mini、关闭、unpin。区分用户收起与空间隐藏，复用可存活的 pill。
- Gate：`tests/test_pinned_cursor_state.py`、`tests/ui/test_pinned_cursor_panels.py`、`test_pinned_cursor_lifecycle.py`、`test_view_bridge.py`、`test_analysis_view_bridge.py`、`test_project_session.py` 关联节点；字段 codec 涉及则加 `tests/test_project_io.py`、`tests/test_project_io_analysis_views.py` 对应 round-trip。中立层修改加独立进程 Qt 导入隔离检查。

### T3 — 底部点击、拖动与领域微调

- 前置：T1、T2。Owner：`PinnedAxisLabel` 与 controller；canvas 只补必要的坐标/已有事实窄适配。
- 实现 §4 的 endpoint-aware 生命周期与预览/提交边界、Shift/方向键、撤销预览、拖动中禁止新建；新方法是计划接口，不能当作当前已存在。
- Gate：`tests/ui/test_pinned_cursor_interaction.py`、`test_pinned_cursor_facts.py`、`test_pinned_cursor_lifecycle.py`；领域回归选 `test_custom_x_cursor_contract.py`、`test_pg_line_canvas.py`、`test_frf_canvas.py` 相应采样/吸附/log/dual 节点。保持现有数值 oracle，不复制一份算法到测试来“自证”。
- 增加计数断言：移动一次只求值目标记录；release 只提交一次；取消/相同有效位置提交零次；缩放不写坐标。

### T4 — 多卡排布、底部可达性与线条

- Owner：controller、`pinned_cursor_overlay.py`、`cursor_pill.py`；host 使用既有安全区。
- 实现 §5，删除原“只避标题 26px”的 Pin 排布假设；保留活动面板已有 ownership。任何 demo 的 Pin 工具条都不加入 ChartStack。
- Gate：`tests/ui/test_pinned_cursor_geometry.py`、`test_cursor_table_geometry.py`、`test_fft_cursor_layout.py`、`test_pinned_cursor_panels.py`；`test_chart_stack.py::test_cursor_pill_toggle_stays_pinned_to_top_right_corner` 保护既有可见动作布局。
- 实绘检查：2/6 长名通道、负值/科学计数/单位；主副 pane、FFT 预览排除、FRF 三图；1/2/8/20 pins、同 X、边缘、不同 DPI。核对真实字形和按钮点击区域，不以 HTML/stylesheet token 代替 Qt。

### T5 — 输出、说明与稳定集成

- Owner：controller 的 fingerprint、既有 stack/analysis capture；`ui/hints.py`、`ui/quickref.py` 及相关帮助正文。
- 以用户最后截图为准同步 demo A：去掉整个额外 Pin bar，不保留空行；若删除 demo-only 节点，连同监听器和“全部收起”说明一并清理。B/C 仅作历史备选，不进入产品。
- Gate：`tests/ui/test_pinned_cursor_capture.py`、`test_ultraview_capture_facts.py`、`test_ultraview_capture.py` 关联节点；`test_hints.py`、`test_quickref.py`、`test_quickref_status_hints.py`。说明文案不新建逐字镜像测试。
- 边界按实际文件运行：`tests/ui/test_pg_canvas_backref_invariants.py`、`test_import_boundaries.py`、`test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`、`tests/ui_kit/test_qss_border_shorthand.py`；新增 import/打包 seam 才加 packaging 门。
- 本轮产品实现跨意图保存、输入事务和捕获，最终稳定集成快照安排一次全量，由协调者唯一执行；T0–T4 不重复全量。先检查在跑的 pytest 及 cwd、记录 HEAD/dirty 指纹，依次运行主套件 `--ignore=tests/acquisition_ui` 和独立 `tests/acquisition_ui`，不并发。途中相关源码变化或异常退出均记 UNVERIFIED。

## 8. 必需验收清单

| ID | 验收 |
| --- | --- |
| P01 | 完整三栏下没有额外 Pin 工具条/数量说明/＋Pin/全部收起/空行；原图表工具栏与底部 View tabs 保留 |
| P02 | 连续按 P 得到独立编号和线，初始没有弹出面板；重复 P 不重复新建 |
| P03 | P1/P2/P3 可同时展开；收起 P2 只影响 P2；full/mini、关闭和 unpin 原行为不串 |
| P04 | 按下轻微抖动是一次 click；拖动释放不是 click；收起/展开状态均可拖动且不改变该状态 |
| P05 | 拖后 line/header/rows/extrema 同坐标；缩放/Home 不改坐标；跨 Pin 不换编号；边界和同点稳定 |
| P06 | Shift 中途切换无跳动；各域键盘微调使用真实单位；dual 两端可单独操作、A=B/A>B 不改语义 |
| P07 | Esc/失焦/切 View/数据重算/源关闭取消预览，工程无误脏；无旧 timer 回调复活目标 |
| P08 | 2/6 长名通道和 1/2/8/20 pins；至少常规窗口三卡可读；底部成员可独立操作，极小尺寸不裁半行冒充可读 |
| P09 | 分屏与分析 pane 隔离；FFT 预览不响应；Custom-X 不被当秒，FRF log 仍存 Hz |
| P10 | 源缺失/旧工程/坏展开字段/clone/remap/重开保持既有身份和兼容；默认收起、显式展开意图可恢复 |
| P11 | 屏幕、复制图、分屏/分析合图、UltraView 的展开/收起一致，预览不混入稳定捕获 |
| P12 | leader 与频谱命中的 native regression 正常退出且坐标正确；Cocoa 密集标签/缩放/切频谱不闪退 |

平台分别记录：offscreen focused tests、macOS Cocoa 前台、Windows source 与 Full/Lite frozen 100%/150%/200%。无环境则明确 UNVERIFIED；HTML 通过不代替任一产品平台验收。原始事故重放和 SIP 退出清理另列，不能宣称所有闪退都已解决。

## 9. 历史契约的覆盖关系与本次交付

- [2026-09-18 Pin 计划](2026-09-18-pinned-cursor-implementation-plan.md) 的创建后显示面板/继承 live 位置、标签只置顶、淡线基准，由本文替代。普通 viewport 操作仍不改 Pin；仅显式拖动/微调是新增坐标编辑例外。
- [2026-09-19 加固计划](2026-09-19-view-isolation-and-pinned-cursor-hardening-plan.md) 的未知 fid 丢弃、无撤销关闭、原 P 路由范围和 source identity 规则继续有效。它的历史状态/通过数不是当前实现验收；不重做无关 View/滤波/版本工作。
- 不修改 DSP/插值算法、不增加全局快捷键、不做 controller 大拆分、不升级版本、不处理无关未跟踪文件、不发布或提交。
- 本次只写正式 plan、在分析文档补最新决定和 `.state/` 规划记录。核对文件/符号、历史冲突、测试路径与 `git diff --check`；文档本身不改变可执行行为，因此本轮不运行 runtime suite。
