# 分析模块对比视图与时域一致性 Follow-up Spec

- 日期：2026-10-11（Asia/Shanghai）。
- 状态：**已实施 F1–F6 及新增输入提交/显示回调缺陷修复；平台验收 PARTIAL，详见验证报告。**
- 核查基线：`4667dd06c98d624b6d5e5663eeb69e4b8911e60e` 加当前 dirty worktree。已有版本、FRF、色阶、帮助和测试改动保持原样。
- 用户目标：频域及其他分析模块与时域一致，**两侧功能和数据独立，操作按钮公用**；消除图内重复工具栏，恢复正确参数编辑、右键和底部半色标签。
- 范围：FFT、FFT vs Time、Order、FRF 的同模块跨 View 对比，以及旧“添加对比窗格”入口的语义澄清。时域是交互对照，不要求改写时域实现。跨模块比较继续属于 UltraView。
- 执行文档：[Follow-up Plan](../plans/2026-10-11-analysis-comparison-timedomain-parity-followup-plan.md)。用户随后授权并行实施；[实施验证](../verify/2026-10-11-analysis-comparison-timedomain-parity.md) 记录修复、测试和剩余验收。

## 1. 修复前诊断与根因

主要根因是：**新建了 peer View 的画布与计算目标绑定，却没有完整接入原有共享工具栏、可见 card 枚举和标签投影协议。** 参数模型本身也同时存在两种“对比”语义。

本轮对真实 MainWindow、生产 card/canvas、合成 CSV 执行控件事件探针，四个模块结果一致。使用生产 QSS/Fusion；offscreen 和独立 Cocoa 测试进程分别运行。普通点击落在真实 ViewBox 中心，参数修改经过真实 combo 信号；Home 的最终调用用 spy 记录，标注与工具模式读取真实状态。测试窗口不是用户原始项目，也不是 Windows 包。

| ID / 级别 | 修复前事实及影响 | 修复前源码位置 / 根因（行号为诊断快照） |
| --- | --- | --- |
| F2 / P1 | 点击右侧后共享 Home 调用了 host；共享标注后实际状态为 `[host=True, peer=False]`。清除使用同一错误目标解析，存在清错侧风险（本轮未执行真实清除） | `analysis_section_page.py:939` `_focused_nav_delegate()`、`:944` `_focused_annotation_card()` 只查询 `self._cards`；与已经支持 peer 的 `focused_canvas()` / 频率游标 provider 不一致 |
| F1 / P2 | 四模块的 peer toolbar 与快捷提示带可见，图面被额外压缩；主侧只有一个 pane 时提示带也未按整个对比状态隐藏 | `analysis_section_page.py:184` `AnalysisPaneHost.set_pane_count()` 直接 `_make_card()`；没有走 `:860` `enter_split()` 的 detach/hide、共享接线及模式继承。`:1072` `_sync_card_hint_bars()` 只数 host cards |
| F3 / P2 | 共享 Zoom 后两侧模式为 `[zoom, pan]`；右侧未纳入广播，工具栏高亮的目标同样仍取 host | `analysis_section_page.py:963` `_visible_peer_toolbars()` 只枚举 host；`:1014` `_sync_shared_nav_highlight()` 依赖错误 annotation target。Back/Forward 的工具组也受此枚举影响，需在实施时补真实历史步进复现 |
| F4 / P2 | A 红色、B 绿色，分析对比打开后 host 标签 partner color 为 `None`，无法画出左右各半色块 | `view_tabbar.py:709` `_partner_color_for()` 只读 `ViewManager.partner_for()`；分析关系由 `main_window/analysis_comparison.py` 独立保存，没有接入标签投影 |
| F5 / P2 | B 获得焦点后顶部焦点条仍采用 A 的红色；时域对照为 B 的绿色 | `analysis_section_page.py:263` `AnalysisPaneHost._apply_focus_style()` 读取 page 的 active view accent；`:1135` 该 accent 来自 manager.active（host），并非 focused view |
| F6 / P2 | peer 不在 `ChartStack._all_cards()` 中；刻度控件统一回显等遍历遗漏 peer | `chart_stack/stack.py:565` 只拼接 `page.peek_cards()`；`analysis_section_page.py:501` 只返回 host cards。这是枚举缺口；不能据此断言所有消费者已出现故障 |
| U1 / 产品语义冲突 | 旧“添加对比窗格”只新增同一 View 的 PaneState，算法参数位于 View 层，不能独立调整。跨 View 对比的实测 A=hanning、B=hamming，点击 B 后改 blackman，A 保持 hanning、B 正确变化 | `analysis_view_state.py` 的 `AnalysisViewState.params` 与 `PaneState`；`analysis_section_page.py:422` 仍用 `split_action_mode='active_pane'`；`_analysis_mixin.py:1499` 修改 manager.active 的 panes。不能把共享参数模型误判成所有跨 View 参数都失效 |
| U2 / 待定位用户路径 | 四模块普通右键实测均弹出“视图选项”。开启标注后，在空白处右键均不弹菜单；该条件与用户反馈相容，但尚未证实是用户触发方式 | `pg_canvas/remarks.py:370` `RemarkInteraction.handle_mouse_press()` 在标注开启时消费右键删除手势；各分析 canvas 同时控制菜单 enable。此前引用的 `viewbox.py::_delete_remark_from_context_event()` 属于时域路径，现更正。此行为不是已证明的 peer 专有故障 |

“工具栏仍有两个”与“参数不能独立”不能用同一个根因概括：前者是 peer 卡片接线遗漏，后者至少存在旧入口共享参数这个确定性原因。若用户实际使用跨 View 入口仍无法独立编辑，则须追加其控件、数据及操作顺序复现，不能通过撤掉 guard 或改所有参数归属来猜修。

### 1.1 修复前与时域对照

| 能力 | 时域当前机制 | 分析跨 View 当前状态 | 目标 |
| --- | --- | --- | --- |
| 图表工具栏 | 共享一排，secondary toolbar 隐藏但保留控制器 | peer 自带工具栏暴露 | 单一可见入口，保留各 canvas 控制器 |
| Home / 标注目标 | `ChartStack.focused_card()` / `_focused_nav_delegate()` | 两套解析，一部分支持 peer、一部分只支持 host | 一个显式 focus target 驱动所有局部动作 |
| 鼠标工具 | 同页可见两侧统一选择工具 | host 与 peer 分裂 | 工具模式同步，实际范围是否联动另由关系选项决定 |
| 参数/来源 | 各自 ViewState | 跨 View 参数基本路径独立；View 内 panes 共享 params | 用户所称独立对比明确对应两份 View 意图 |
| 标签颜色 | manager 配对关系 → host 半色、peer 实色 | 分析 owner 关系未投影 | 同一绘制器，单独只读关系适配 |
| 焦点颜色 | 被聚焦 View 的 tab color | peer 使用 host color | 焦点条与所属 View 一致 |
| 全卡片遍历 | 包含 primary、secondary | 只含分析 host | 对每个消费者明确“host / 指定 View / 全部可见”范围 |
| 右键 | 共享 ViewBox 菜单及标注手势 | 普通路径可弹出；标注模式会消费右键 | 验证完整命中和路由，不擅自宣称全局菜单损坏 |

时域不是所有行为绝对正确的证明。此次沿用其已核实交互合同：Home/标注/选项跟焦点；鼠标模式面向同页可见画布；历史按钮按现有逻辑对各可见画布各走自己的历史；共享保存/复制输出当前对比组合。结果、参数和历史栈仍分别所有。

### 1.2 诊断结果与限制

本地证据：`.state/analysis-comparison-followup-20261011/`。

| 检查 | 原样结果 | 解释 |
| --- | --- | --- |
| 当前既有 comparison 两个测试文件 | `40 passed, 221 warnings in 8.16s` | 现有参数、范围、缓存等回归通过，不包含本轮完整 toolbar/chrome 断言 |
| 新观察探针，生产 QSS，offscreen | `5 passed, 8 warnings in 6.02s` | 4 个分析模块加时域对照；通过表示记录成功，**不是 F1–F6 修复通过** |
| 同观察探针，生产 QSS，Cocoa | `5 passed, 8 warnings in 7.03s` | 独立原生 Qt 窗口与合成数据；重复观察到额外栏、错误 Home/标注目标和模式分裂 |
| 用户原项目前台 / Windows fresh frozen | `UNKNOWN` | 没有用户原文件和该次操作序列的复现，未运行 Windows 包 |

文件：`existing-tests.log`、`styled-probe.log`、`cocoa-probe.log`、各 `*-observations.json`、各 `*-page.png`、`time-control.png`。初版探针误用部分模块的 combo 属性，已修正；初版构造错误不计为产品缺陷。探针显式加载 `tests.conftest` 与 `tests.ui.conftest`，保留 QSettings 隔离与 teardown。

截图已检查，FFT 可见右侧额外工具栏和底部提示带造成上下绘图区错位。这些是修复前截图；修复后的生产 Cocoa 截图、真实计算与导出证据另见实施验证，不能混用通过数量。

## 2. 产品行为合同

### 2.1 独立对比入口与兼容

1. “与此 View 并排 / 与其他 View 并排”代表两份独立分析意图 A/B，聚焦后分别编辑、计算、重算和保存。该路径是满足本次要求的主对比入口。
2. 旧“添加对比窗格”不能继续用容易理解为独立参数的名称与主入口并列。实施默认将其明确命名为“添加同参数窗格”，提示“同一 View，共享分析参数，来源与时间范围独立”；保留原数据模型和旧项目读写。菜单优先展示独立 View 对比。
3. 本 follow-up 不把旧 PaneState 静默迁成 View，不改变 MAX_PANES=2，不新增 pane.params。已有 1/2 panes 和 2 Views×2 panes 保持可打开。
4. 如从零建立另一套参数，使用现有“复制 View”→改参数→并排流程；本轮不新增自动复制/拆分迁移向导。独立比较不能指向同一个 view_id。
5. 对比内增删内部 pane 仍是明确指定 View 的局部动作。现有入口只操作 host；菜单必须标明目标，不能让 peer 焦点下的“当前”暗指 host。若提供 peer 入口，应携带 view_id 并走相同 owner。
6. 本文替代 2026-10-04 计划中旧双窗格入口的模糊命名与不完整 chrome 合同；保留该计划的 cache/request、来源隔离和比较关系持久化合同。

### 2.2 共享操作与独立状态

| 操作 | 目标 / 状态 | 禁止副作用 |
| --- | --- | --- |
| 计算参数、显示参数、预设、附件 | 当前焦点 View；pane 专属字段写当前 pane | 不写另一 View；不从另一侧 Inspector 值补默认值 |
| 来源、分析时间、游标、标注、相机 | `(section, view_id, pane_index)` | 不按显示名或 manager.active 猜目标 |
| Home、图表选项、标注开关/清除 | 焦点画布 | 不改变另一侧；显式轴联动可传播相机 |
| 平移/框选工具选择 | 同 section 当前可见画布的工具模式统一 | 不能同步参数或擅自开启相机联动；不广播隐藏模块 |
| Back/Forward | 与当前时域一致：每个可见 canvas 各走自己的历史；无历史侧不动 | 不共用历史栈，不把历史写进项目，不改计算时间/色阶 |
| 保存/复制对比图 | 当前 A+B，包含各侧已有可见读数/切片 | 不包含工具栏，不把 B 截图持久化成 A 的内容 |
| 单 View 抓图 / UltraView 引用 | 已有接口显式指定 View | 不因对比开放而混入 peer |
| 刻度等已有全局控件 | 保持其原作用域，遍历时包含所有应接收的 peer | 不借本修复把所有设置都改成全局或局部 |

“按键公用”是共用入口与回显，并不意味着 Home/标注同时执行两次。“功能独立”不禁止用户显式启用相机/色阶联动。联动默认关闭，并继续检查真实轴尺度、量纲、幅值模式及参考值兼容性；不重新引入 log/linear 错位。

### 2.3 焦点事务

- 绘图区、切片、FRF 三行、空态区域的有效点击均解析到同一目标；右键先确定所属目标，再构建菜单。Qt 事件只能处理一次，不吞后续 ViewBox 菜单/拖动。
- 转移焦点时先向旧目标提交待输入参数/时间，再更新 binding focus，最后投影新目标的来源、控件、facts、游标、按钮和焦点条。一次投影不触发 DSP，不制造 dirty。
- 点击按钮不能因为 toolbar 原物理 parent 是 host 而回退目标；清除确认固定发起时的目标与存活身份，确认期间目标删除或内容替换则取消。
- 从 peer 切回 host 的同 pane index 也必须刷新全部共享按钮，不能因整数 index 没变而跳过。
- Inspector 或现有上下文标题应明确显示当前 View 名称和 pane；用现有标题位置，不向数据画布再加入一排控件。

### 2.4 工具栏、布局与颜色

- 每个分析 section 页面只有一排可见图表动作栏、一条底部 View 标签栏。所有 host/peer card 的内部 toolbar 隐藏，保留控制器和独立历史。不得因隐藏 toolbar 丢失 canvas 的菜单模式控制。
- 对比中不出现每 card 的通用快捷提示带；切片信息、FRF 有效事实等分析内容不是工具栏，不得一并隐藏。
- 1+1、1+2、2+1、2+2 组合均按同一接入流程管理；重复开关、peer 替换和窄窗方向变化不恢复内部 toolbar。
- host 标签色块左半 host、右半 peer，中间分隔，沿用时域绘制器；peer 自身标签保持实色。不能把“半色显示”解释成将整条 tab 背景一分为二。
- 标签、溢出列表、焦点条随重命名、改色、重排、切换、删除和项目恢复同步。关系用 view_id，不能缓存易变下标。
- 焦点条继续使用既有 3 px overlay，颜色来自焦点 View，不添加额外边框导致绘图区缩进。
- 窄窗须为 active tab 保留真实可见及可点击宽度；联动、锁色阶、展开操作收进“对比选项”，动作与 checked/enabled 复用原控件，宽窗恢复原按钮。
- 宽窗比较同结构图的主图、切片/FRF 行几何；窄窗保留用户拖动比例及既有展开/返回能力。不同分析行结构不要求虚假的逐像素等高。

### 2.5 右键合同与诊断分支

- 普通模式：四模块 host/peer 的主图、切片、FRF 各子图均应弹出相应菜单；选择动作使用点击侧目标，按钮回显同步。底部标签的管理菜单是独立路径，也必须验证。
- 标注模式：目前右键作为删除手势优先消费事件。先与时域相同手势做对照，验证命中标注/空白、标注开关回显、退出方式。不要为了菜单测试转绿而无条件禁用删除手势。
- 本轮不授权静默改写全模块右键手势。至少恢复正确标注目标及开关可见回显；若用户问题确认为“标注空白右键无反馈”，在既有提示区域说明删除模式和退出方式。若需要“空白弹菜单、命中才删除”的新语义，须单列交互变更并同时核对时域，不作为已确定修复混入。
- 普通模式仍无反应时，以真实事件追踪区分：焦点 filter、page transition 遮罩、Qt popup 生命周期、ViewBox menu enable、菜单构建异常。当前 `raiseContextMenu()` 的静默异常分支仅是待排查位置，尚无本次异常证据，不启动全仓异常清理。

## 3. 实现边界

| Owner | 本次责任 | 边界 |
| --- | --- | --- |
| `main_window/analysis_comparison.py` | 关系与 focused target、canvas binding、联动连接 | 不复制参数/结果，不引入第二个 active view 真源 |
| `analysis_section_page.py` / `AnalysisPaneHost` | card 接入/拆除、可见目标枚举、共享动作投影、焦点 chrome | 提供显式 focused card 与 visible cards 接口；host-only 获取仍保留给只截 A 等调用 |
| `chart_stack/toolbar.py` / `cards.py` | 复用现有 provider，局部 setter 与共享用户动作分开 | 不复制新 toolbar 控制器，不把共享按钮状态当 canvas 真源 |
| `view_tabbar.py` | 只读比较关系与焦点投影，复用半色色块 | 不给分析 manager 写时域 `_split_pairs`；避免出现两份关系 |
| `_analysis_mixin.py` / 各模块现有 owner | 参数捕获、焦点事务、计算/显示/来源/范围路由 | 只修被复现的入口，不扩张 MainWindow 状态 ratchet |
| `chart_stack/stack.py` | 全卡片消费者、游标/抓图接线 | 审计枚举作用域，不能直接把 `peek_cards()` 全局改成含 peer，破坏 host 导出 |

生命周期：统一安装/拆除 toolbar highlight、viewport、copy、annotation、cursor、销毁连接和 pending timer；同一 card 不重复接线。关闭对比只解除展示，不删除 View 或结果 pin。迟到结果仍按 dispatch 的完整身份校验；显示时按当前 binding 与所属 View 最新显示意图投影。

本轮观察到 peer 已有 pinned-cursor owner，**不能因未 emit pane_added 就断言 Pin 完全失效**。Pin/P 快捷键、live/pinned pill 归属、关闭后的清理列入生命周期验收；只在失败后修改对应边界。

## 4. 验收合同

| AC | 必须证明的结果 |
| --- | --- |
| AC1 | 四模块各组合只有一个可见图表 toolbar；无 peer 提示带；时域对照无退化 |
| AC2 | 真实点击 peer 后 Home/标注/清除/图表选项/快捷键目标正确；开关及高亮与目标一致；确认竞态不清错侧 |
| AC3 | 两侧算法、显示、预设、来源和时间独立；未提交输入在 A/B/A、切模块、关闭和真实 save/reopen 后不串写；显示编辑不新增 DSP |
| AC4 | 普通模式右键及标签菜单实际弹出且能执行；标注手势单列验证，用户报告路径有 PASS 或明确剩余 UNKNOWN |
| AC5 | host 半色、peer 实色、焦点条颜色正确；改色/重排/溢出/删除/恢复后的像素及身份均正确 |
| AC6 | 鼠标模式同步、历史分别导航、联动兼容性、切片/FRF 三行对齐、保存复制/单 View 引用范围正确 |
| AC7 | peer 替换、2×2 动态 pane、反复开关、删除目标、源卸载、项目替换、后台完成无串写/重复信号/失效 wrapper |
| AC8 | 代码和 offscreen、生产 Cocoa、用户实际场景、Windows 新 frozen 分别记录，未运行项明确 UNKNOWN |

必须至少包含不同来源且同名通道、不同参数/量级/颜色、空态/已有结果、两侧结果到达次序相反等用例。不能只调用 `focus_comparison()` 验证后续处理，要从 viewport 点击或实际 QAction 进入；不能只比较两个路径相同，要检查已知目标确实改变、非目标确实不变。

## 5. 与历史工作的关系

- [2026-10-04 结果有效性与跨 View 计划](../plans/2026-10-04-analysis-view-result-validity-and-cross-view-comparison-plan.md)：保留独立 View、请求身份、缓存与来源合同；本 spec 补充完整交互接入并澄清旧窗格入口。
- [2026-10-04 实施 Review](../reviews/2026-10-04-analysis-view-implementation-review.md) 与 [2026-10-05 验证记录](../verify/2026-10-05-analysis-view-comparison-fixes.md)：历史 R1–R9 不能直接作为本轮新缺陷；当前 40 项回归通过。本轮 F1–F6 属于当时未覆盖的交互/chrome 路径。
- [2026-09-26 工具栏一致性计划](../plans/2026-09-26-toolbar-section-consistency-remediation-plan.md)：现在源码已有共享 annotation provider、历史组和统一导出，不重做该计划。将已有行为扩展到新增 peer 即可。
- 旧验证报告中的 FRF 三行、FFT-time 主图/切片两个对齐失败只作为历史线索。实施前重新运行这两个 node 已通过（`stack-layout-red.log` 中 2 passed）；没有修改布局算法或放宽断言。

文档校验覆盖范围、路径/符号、F→AC→任务映射及 `git diff --check`。实施新增保存前输入提交、冻结 dB 显示回调目标、peer 全局刻度和标注 relay、窄窗标签保留及新 peer 画布恢复固定游标回归；既有 DSP、项目 schema 与来源身份模型保持不变。全部验收状态以实施验证为准。
