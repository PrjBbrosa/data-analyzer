# 右侧 Inspector 悬停展开交互与自动收起优化计划

- 日期：2026-10-12。
- 状态：**代码与离屏测试已落地；Windows 真鼠标、Cocoa 前台和冻结包验收未关。**
- 基线：`main` / `08132b78ae350534a3d449c11daf30581b492cf7`，工作区包含已合并的本地修复及尚未提交的 v8.4.5 版本同步。实施前重新记录工作区，保留这些修改及原始 stash。
- 用户目标：右侧折叠带悬停展开后的 Inspector，像左侧通道面板一样可直接操作；移出后自动收起；点击折叠带可固定展开。
- 验收主场景：用户提供的 Windows 截图，时频分析、View 2 / 窗格 1、右侧 Inspector 临时展开。截图仅证明外观；无法据此证明事件命中、鼠标离开或控件实际启用状态。

## 1. 理解与范围

“悬停展开”应是原面板的临时可交互状态。信号选择、参数输入、分段按钮、下拉列表、滚动与计算等操作遵守固定展开时相同的产品规则；不需要先固定面板才能操作。只读字段和因数据条件禁用的控件继续遵守原有规则，例如“全时段”下的起止编辑器不能作为点击失效的证据。

保留现有三态：HIDDEN（收起）、PEEK（临时展开）、PINNED（固定展开）。PEEK 覆盖图表，不挤压图表；PINNED 占用 splitter 宽度。以左侧正常使用体验为目标，两侧共用交互机制；同时修复共有的事件缺口，而不是复制一套右侧控制器。

本轮不改 DSP、分析参数语义、自动计算策略、View/pane 身份、版本号、固定面板宽度或总体视觉设计。无需重做 Inspector 或增加新的浮动窗口体系。

## 2. 当前证据与待确认问题

行号对应上述工作区；实施时以符号定位为准。

| 证据级别 | 定位 / 结果 | 判断 |
| --- | --- | --- |
| 用户反馈 | 右侧临时展开后无法操作，移开不消失；左侧正常 | 两项均为必须验收的问题，不以现有测试通过否定反馈。 |
| 源码确认 | `mf4_analyzer/ui/main_window/window.py:553` 创建左右 `PeekOverlay`，`:559`、`:565` 创建相同的 `SidePanelController` | 左右已经共享状态机；应查宿主、命中、事件路径差异。 |
| 源码确认 | `ui/side_panels.py:168` 的 `set_panel()` 将原 panel 改挂到 overlay，再加入布局并 show | 右侧不是图片或只读复制品。简单“换成真实控件”不是修复方案。 |
| 源码确认 | `SidePanelStrip.leaveEvent()`（`:107`）只停止悬停打开计时器；控制器（`:247`）只订阅 overlay 的 enter/leave | 注释声称覆盖 overlay 与 strip 的并集，但 strip 进出未完整进入自动收起判断。 |
| 离屏真实控件探针 | `.state/right-panel-plan/probe.py` / `probe.log`：左右均出现 rail hover → PEEK → rail 直接到图表 → 等待 750 ms，仍 PEEK 且 collapse timer inactive | 已复现一条“展开后不收起”的实际事件路径。不能外推为用户所述所有“离开面板”路径均已复现。 |
| 源码确认 | `_on_collapse_timeout()`（`:271`）遇到任意 `activePopupWidget()` 即重启计时器 | 保护范围没有区分属于本面板的弹窗；也没有在超时点重新核对鼠标是否位于面板、折叠带或所属弹窗。 |
| 离屏几何观察 | Inspector 在 PEEK 下仍 visible/enabled，`WA_TransparentForMouseEvents=False`，父级为 `PeekOverlay`；根窗口 `childAt` 可命中其 `QLineEdit` | 未证实“整个 Inspector 被禁用”。离屏虚拟屏幕未完整覆盖窗口，`QApplication.widgetAt` 的空值不能作为 Windows 命中失败证据。 |
| 已执行测试 | `tests/ui/test_side_panel_reducer.py` + `tests/ui/test_side_panel_widgets.py`：**37 passed in 1.52s** | 当前测试多使用裸 QWidget、手动 `peek_requested.emit()` / `mouse_left.emit()`，没有证明真实 Inspector 的点击、弹窗、编辑和离开路径。 |
| 待原生确认 | Windows 上右侧可见但不可操作的直接原因 | 可能涉及重挂父级后的输入命中、遮挡、mouse grab、弹窗或坐标映射；目前均为排查分支，不作为既定根因。 |

额外差异：Inspector 固定外宽 288 px，内部为 `QScrollArea`（`ui/inspector.py:141`、`:146`）；左侧 FileNavigator 为另一控件树且 PEEK 可增加宽度。Inspector 浮层探针中内容相对 overlay 有 1 px 边框偏移，应核对实际 viewport/控件区域，但不能仅凭这 1 px 解释整个面板不可操作。

## 3. 目标交互合同

| 场景 | 目标行为 |
| --- | --- |
| 悬停折叠带 | 保留现有 150 ms 打开延迟，进入 PEEK；左右一致。 |
| 折叠带 → 面板、面板 → 折叠带、面板子控件之间移动 | 整体视为仍在交互区域，不闪退、不重复重挂父级。 |
| 从折叠带直接离开，或从面板任意边界移到图表/工具栏/窗口外 | 进入现有 600 ms 收起宽限期；超时复查后收起。重新进入则取消。 |
| 点击、输入、Tab 切换、滚轮 | 真实控件收到事件，值/选项按正常规则提交；滚动只影响当前面板，事件不穿透到图表。 |
| 打开所属下拉列表、搜索补全、右键菜单或参数对话框 | 交互完成前不因鼠标移出主面板而卸载原控件；关闭后立即重新评估区域并决定是否延时收起。 |
| 无关弹窗或残留输入焦点 | 不能永久阻止该侧收起。单纯 `hasFocus()` 不作为长期保活条件。 |
| 鼠标按下后的拖动/选中文本 | 操作结束前不重挂控件，不丢 release；结束后重新评估。 |
| 点击折叠带或既有工具栏面板按钮 | 按现有规则固定/收起；固定后鼠标离开不自动隐藏，按钮 checked 状态仅代表 PINNED。 |
| View/pane 或分析模块切换 | Inspector 继续由既有焦点上下文投影，不能写入另一 View/pane；PEEK 本身不启动计算。 |
| 主窗口隐藏、最小化、失活、关闭或离开当前工作区 | 暂态不能残留；所属模态对话框先完成正常交互。关闭/销毁时清理监听与计时器。 |
| 保存与恢复 | PEEK 仍按 HIDDEN 持久化；固定状态与记忆宽度保持既有合同。 |

## 4. 实施任务（顺序执行）

### T0 — 建立可失败的真实交互复现

- Owner：`.state/right-panel-plan/` 诊断文件；`tests/ui/test_side_panel_widgets.py`；新增 `tests/ui/test_side_panel_interaction.py`。
- 先记录 HEAD、工作区、运行源码/EXE 路径、版本、平台插件、窗口尺寸、DPR。Windows 须先确认运行的是哪个构建，避免修源码却验证旧 EXE。
- 使用真实 MainWindow、生产 QSS、隔离 QSettings 和小型合成信号。覆盖工具栏收起与 splitter 拖到边缘两种入口，先复现截图中的时频模式，再对照左侧。
- 记录 overlay/panel/scroll viewport 的父级、全局几何、visibleRegion/mask、enabled/visible、鼠标透明属性、native window、当前 mouse grabber、activePopupWidget，以及全局鼠标对应的 `widgetAt`/根窗口 `childAt`。坐标必须落在实际屏幕范围内。
- 捕获 enter/leave、press/release、focus 与计时器序列。真实鼠标命中后点击可操作按钮、输入数值、打开并选择下拉项；不能只调用 `setValue()` 或直接向预定控件发事件来证明原生命中正确。
- 先固化已复现的 strip→chart 不收起用例；对右侧不可操作保留独立用例和平台证据。若离屏不复现，保留 Windows 原生失败证据，不能将未知原因“修复完成”。
- Focused：现有两份 side-panel 测试 + 新增交互文件。已有 37 项结果可作为本轮初始基线，无需先跑全仓。

### T1 — 修复右侧输入命中与真实控件交互

- 主 owner：`mf4_analyzer/ui/side_panels.py` 的 `PeekOverlay` / `SidePanelController`。
- 仅当 T0 证明宿主接线或 Inspector 本身是原因时，才修改 `ui/main_window/window.py` 或 `ui/inspector.py` 的对应边界。
- 按 T0 证据修复遮挡、父级/坐标/布局或输入属性；保留原 Inspector 实例及其业务信号。不得批量启用所有子控件、转发原始鼠标给业务控件、复制 Inspector、无条件抢焦点或引入第二套参数状态。
- 保留 overlay 为主窗口内的 child widget，沿用现有局部坐标；不因点击问题直接改成原生顶层 `Qt.Tool`/`Qt.Popup`。顶层弹窗的全局坐标规则不能套用于当前 child overlay。
- Focused：新增右侧鼠标命中、点击值变化、键盘编辑、滚动及下拉选择用例；左侧对照通过；`tests/ui/test_inspector_width_cap.py`、`tests/ui/test_inspector_first_show_layout.py`。
- Boundary：若改宿主接线，运行 `tests/ui/test_main_window_state_ownership.py`；若改 QSS/壳体，追加 `tests/ui/test_surface_layering.py` 对应边缘条和面板圆角用例、`tests/ui_kit/test_qss_border_shorthand.py`，并记录原生像素证据。

### T2 — 统一整个交互区域的进入、离开和收起

- Owner：`ui/side_panels.py`、两份既有 side-panel 测试、新增交互测试。
- 由每侧现有 controller 负责自身事件观察和计时器；补齐 strip 与 overlay 的进入/离开，不新增 MainWindow 多处可写状态。
- 将 strip、overlay 内的子控件、属于本面板的弹窗/对话框作为交互集合。正常事件驱动重评估；必要的应用级过滤仅在 PEEK 期间启用，缩小关注范围，退出/销毁时移除，不吞掉业务输入、不长期高频轮询。
- 离开时启动一次宽限计时；超时时复查鼠标区域、所属 popup/dialog 和实际拖动状态。弹窗关闭后重评估，避免“只有一次 Leave，之后永远不再检查”；无关 popup 不能阻塞。
- 保留 HIDDEN/PEEK/PINNED reducer 与已有宽度夹取、左右 splitter 索引、PEEK-as-HIDDEN 持久化合同。临时延迟状态由 controller 显式初始化并对称清理。
- Focused：左右参数化；rail→chart、overlay→chart、overlay→rail、子控件移动、600 ms 内重入、所属/无关 popup、popup 关闭、拖动结束、重复 20 次展开/收起、窗口缩放/隐藏/销毁。
- Boundary：`tests/ui/test_no_lambda_signal_connections.py`，不得扩大现有白名单；保留所有旧宽度、双侧同时 PEEK、空间不足收起测试。

### T3 — 真实 Inspector 集成与用户说明

- Owner：新增 `tests/ui/test_side_panel_interaction.py`，必要的 `ui/hints.py`、`ui/quickref.py` 说明。
- 时域、频谱、时频、阶次、频响五种模式分别验证：临时展开可操作，输入保存，收起再展开仍正确；不把有意 disabled 的控件作为失败。
- 时频重点验证信号下拉、全时段/指定范围切换、FFT 点数/窗函数、重叠值、dB 参考设置和滚动。至少验证一次真实“计算”按钮完成其原有调用，而非只统计 clicked。
- 加入跨 View 比较/窗格焦点场景：一次有效编辑只作用于当前目标，另一个目标不变；收起不改变分析请求或缓存发布权限。
- 检查 UltraView 进入/退出、项目恢复与面板固定状态；复用 `tests/ui/test_ultraview_mode_integration.py` 中 sidebar persistent snapshot 相关用例，不整批扩大无关测试。
- 用户说明同步“悬停临时展开并可操作、离开自动收起、点击固定”到 hints 与 quickref；若决定维持原有措辞，逐条说明已覆盖的证据。
- Focused：新增交互文件；`tests/ui/test_main_window_smoke.py::test_main_window_collapsing_inspector_expands_chart_then_repin_restores`；被触及的比较焦点、持久化和说明测试。

### T4 — 原生验收与交付

- Windows 原生为必需问题关闭门：在正常窗口/最大化、100% 与高 DPI（至少 150%，并覆盖用户当前比例）下，真实鼠标从折叠带进入右面板，点击/输入/滚动/打开弹窗，再移出自动收起。重复对照左侧；抓取事件轨迹和截图/短录像。
- macOS Cocoa 回归：同样的展开、操作、弹窗、离开、固定流程；检查圆角、边框、原生阴影、焦点与事件穿透。
- 如果用户失败发生在冻结包，必须以包含修复的对应新 Windows Full/Lite 包复测；源码、offscreen、Cocoa 与冻结包结果分别记录，不互相替代。
- 完成 owner 测试后只运行适用边界门和 `git diff --check`。本任务是有界侧栏行为修复，默认不跑全仓或全部 `tests/ui`；发现跨域故障时先记录扩大验证的理由。
- 报告已复现原因、最终修复、左右对照证据、原生/冻结包状态；任一“可操作”或“自动收起”原生门未闭合则标为 partial，不宣称完全解决。

## 5. 完成判据

- [ ] Windows 用户场景中右侧 PEEK 的有效控件可被真实鼠标命中并操作，点击不穿透。
- [ ] rail 直接离开、panel 离开均可自动收起；区域内移动与短暂重入不误收起。
- [ ] 下拉/菜单/设置对话框使用期间不消失，结束后按鼠标位置恢复收起逻辑。
- [ ] 左侧既有交互无回归；左右状态机、时序、宽度与持久化规则一致。
- [ ] 五种模式、比较焦点、反复开合与窗口生命周期通过对应 focused/boundary gates。
- [ ] Windows 原生与 Cocoa 分别有证据；涉及冻结包时新包验收通过。
- [ ] 不改分析数值语义，不覆盖原有本地修改；使用说明与最终行为一致。

## 6. 本轮计划验证

本轮不是修复交付。已读共享控制器、MainWindow 接线、Inspector 构造、现有侧栏测试和相关 popup/圆角经验；已执行 37 项侧栏基线并运行离屏真实 MainWindow 诊断。未修改产品代码，未执行 Windows/Cocoa 前台验收。

文档交付检查：引用与现有符号对应、区分已确认与推测、实施顺序和每步门禁明确、`git diff --check`。不为本计划的文字增加单元测试，不运行全仓测试。
