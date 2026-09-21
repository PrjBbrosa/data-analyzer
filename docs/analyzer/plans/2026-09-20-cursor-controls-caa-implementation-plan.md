# Cursor 控件 C / A / A 实施计划

- 日期：2026-09-20。
- 决策：用户已选择 **C / A / A**；本文件固化交互、实现边界与验收顺序。
- 状态：**设计方向已确认，本文为实施计划，不代表产品已实现或通过验收。** 本轮只新增此文档。
- 代码参考：HEAD `24b45a94435049809f7035f12c5fbbb9663a7884`，并读取当前工作区。工作区已有进度、Pin 生命周期等未提交修改，实施前应核对归属，不覆盖、回退或重复实施。
- 视觉参考：[交互原型](../ui-prototypes/2026-09-20-cursor-controls-options.html)。原型是多方案比较页，默认组合及“推荐”标记不等于最终决定；以本文的 **C / A / A** 为准。
- 执行方式：按下列任务顺序实施，不需要另建全局状态管理器或并行拆分。

## 1. 确认的产品结果

| 项目 | 选择 | 最终交互 |
| --- | --- | --- |
| 内容显示 | **C：数值 / 完整双选项** | 同时显示两个选项，选中项表示当前模式；替换容易被误解为最小化的 ± |
| 底部 Pn 状态 | **A：蓝色阶梯** | 收起为中性浅底、空心点；打开为浅蓝底、实心点；打开且激活为蓝底白字、外环 |
| 固定面板操作 | **A：移除 P，保留 ×** | × 删除该 Pin；“取消固定，继续调整”移入标题 `Pn ▾` 菜单；普通活动 Cursor 保留固定入口 |

标题示意：

```text
固定面板： [P4 ▾]          [ 数值 | 完整 ] [×]
           t=29.2437s

活动面板： t=29.2437s       [P] [ 数值 | 完整 ]
```

示意表达控件关系，不规定所有域的时间/频率标题都必须另起一行；实际布局沿用各域内容合同，并按真实字体和可用宽度排版。

P 与 × 目前并非相同命令：`unpin_record` 会恢复活动游标、保留重新固定所需编号语义；`close_record` 删除记录而不恢复活动游标。本方案减少常驻按钮，但保留这两种能力。

## 2. 交互合同

### 2.1 “数值 / 完整”只改变内容密度

- 文案固定为 **数值 / 完整**，内部继续映射 `mini / full`；不改项目格式、旧 View/快照值及现有默认行为。
- 沿用完整的既有显示投影，不能把各域的 `mini/full` 简化成仅隐藏名称。数值、单位、颜色、A/B、差值及诊断内容按现有域规则呈现，不改计算。
- 两项互斥。点击已选项无操作，不反向切换、不重复发信号；点击另一项提交一次模式变化。
- 切换不收起面板、不删除 Pin、不切换游标模式、不改变数据坐标。每个 Pin 保持独立模式，不能改变其他 Pin 或错误写入 live 偏好。
- 恢复快照、View、投影时只同步选中状态，不制造用户意图信号或额外 dirty。
- 保持现有右边缘/顶部锚定及 safe rect 约束；模式切换后重新测量面板，并更新 tether 的真实连接边界。
- 使用互斥、可聚焦的原生按钮组；Tab 可到达，方向键切换选项，Space/Enter 激活。工具提示及可访问名称说明当前模式；焦点与选中样式区分。

### 2.2 Pn 三态与暂态强调

以原型 A 的颜色作为首版实现目标；最终以生产样式下的原生合图验收。

| 状态 | 背景 | 边框 | 文字/状态点 | 非颜色提示 |
| --- | --- | --- | --- | --- |
| 收起 | `#F8FAFC` | `#AAB7C8` | `#56657A` | 空心点；tooltip“展开 Pn 面板” |
| 打开、未激活 | `#E5EFFF` | `#6592CF` | `#164878` | 实心点；tooltip“收起 Pn 面板，保留固定读数” |
| 打开且激活 | `#2167C7` | `#174D98` | `#FFFFFF` | 实心点；外环 `#D3E2F7` |

- “激活/选中”是当前交互强调，沿用 hover、键盘焦点、当前操作及现有短时定位反馈；**不新增持久化 selected 字段或另一套选中记录管理器**。
- 底部 Pn 点击展开后获得操作强调；鼠标移出且焦点、拖动、定位反馈均结束时回到普通打开态。失焦/切换 View 后不得永久亮着。
- 收起的 Pn 在 hover/focus/drag 时仍为空心点，保持收起语义；可加强轮廓/外环，不伪装成面板已打开。拖动收起的 Pn 不自动展开。
- 拖动捕获期间保持强调，不能因鼠标离开控件或进入标题子按钮而闪回普通态。释放/取消后重新合成当前 hover/focus 状态；不能只在 Leave 时直接关闭所有强调。
- 面板和相应位置线/连接线跟随同一记录的交互强调；保留 dual A/B 端点配色，不能把 A/B 的线都改成 Pn 蓝色。
- `panel_expanded` 是用户开合意图，不等同于 QWidget 此刻可见。空间不足、数据不可用、域暂不可表示仍沿用既有诊断/可用性语义；需要说明暂不可见原因，不擅自改成用户收起，不只靠蓝色暗示正常。
- 样式变化不修改数据坐标、ordinal 或 hit target 的中心映射。圆点、边框、外环必须纳入实测布局；不得裁掉外环或让透明外环区域截走相邻标签事件。

### 2.3 标题菜单和 × 的职责

固定面板标题显示一个可点击、可聚焦的 **`Pn ▾`**，不同时在富文本中再画一份重复编号。菜单项为：

| 操作 | 结果 | 复用路径 |
| --- | --- | --- |
| 收起面板，保留 Pin | 面板消失，底部 Pn/位置线保留 | 既有 panel 开合 owner；只收起，不盲目 toggle |
| 取消固定，继续调整 | 移除固定记录，按既有语义接回活动游标 | 既有 `unpin_requested → unpin_record` |
| 删除 Pn | 删除记录、面板及其投影，不接回活动游标 | 与 × 同一个 `close_requested → close_record` |

- 删除项与前两项用分隔线区分；× 的 tooltip/accessible name 改为 **“删除 Pn”**，不再写容易被理解成收起的“关闭这一张面板”。不新增确认框。
- 普通活动 Cursor 没有 `Pn ▾`、没有删除 Pin 的 ×；固定入口继续遵循现有可固定条件和 P 键路由。固定面板不保留第二个常驻 P/图钉按钮。
- 点菜单按钮、分段按钮、× 不触发面板拖动；标题其余可拖动区域保留。菜单打开时不会让 hover 抖动导致状态闪烁。
- 菜单使用有明确父对象的 Qt 控件和项目现有样式。Esc/外部点击关闭；面板隐藏、Pin 删除、View/源失效时关闭并释放失效回调。
- 执行动作时由当前 owner 校验 record/scope；不能仅捕获旧编号再操作新 View 的同名 P1。菜单显示期间发生状态变化时，禁用或关闭失效动作。
- 不新增撤销系统、成功计数、状态切换工具条或管理面板。原型中的恢复/重置、场景切换按钮属于演示辅助功能，不是此次授权需求。

## 3. 现有实现与主要风险

| 当前入口 | 已读取的实现 | 本次需要处理 |
| --- | --- | --- |
| `chart_stack/cursor_pill.py`：`_position_title_actions`、`_TITLE_ACTION_RESERVE` | 原标题按固定 16px 按钮及静态预留定位；富文本与表格预算多处使用同一常量 | 双选项明显更宽，需统一测量标题控件占位，贯穿绘制、布局、最小宽度和安全区域 |
| 同文件：`_toggle_mode`、`_update_toggle_button`、`restore_snapshot`、`set_display_projection` | 现按钮直接反转模式；恢复和投影也更新按钮 | 改成显式选择目标模式，保留单次发信号及无信号恢复，兼容仍在使用的内部调用 seam |
| 同文件：`_sync_pin_hint_geometry`、`_on_pin_clicked` | pinned 角色显示 P，点击发 unpin；live 角色发 pin | 隐藏 pinned 的 P，把 unpin 接到标题菜单，live 条件不变 |
| `chart_stack/pinning/presentation.py` | 创建 pill、注入编号富文本、接模式/关闭/取消固定信号，管理几何与强调 | 单一编号菜单呈现，信号接回既有 owner；几何失效后 tether 同步 |
| `pg_canvas/pinned_cursor_overlay.py`：`PinnedAxisLabel.paintEvent` | highlighted 优先于 open，现 highlighted 填色比 open 更淡 | 按开合与交互态组合绘制，避免“越选中越不明显” |
| 同文件：标签外尺寸、cluster/member 与 endpoint 布局 | 排列和命中依赖外尺寸 | 圆点/外环不能只改 paint，不改尺寸；覆盖 P12、Pn·A/B、重叠簇、窄底栏 |
| `chart_stack/pinning/commands.py`、`pinned_cursor_controller.py` | close 与 unpin 命令具有不同生命周期结果 | 复用命令，不通过删除后手工新建 live 来模拟 unpin |
| `ui/hints.py`、`ui/quickref.py` | 仍含默认 −、+、蓝图钉、× 关闭等说明 | 与新入口同批更新；保留 Board 中 P 等已有上下文区别 |

最重要的几何原则：**测量、分配和绘制使用同一份标题尺寸事实**。标题右侧控件组的实际 sizeHint/布局宽度为唯一来源，替代各处静态按钮数推算。标题左侧的编号菜单也进入标题预算。不得只扩大面板 minWidth，或把浏览器的 29px 按钮高度直接搬入 Qt。

宽度不足时，先按现有内容策略省略长名称并限制正文；标题控件仍完整可操作。连标题最小尺寸也容不下时，使用既有空间不足处理及可理解的提示，不暗中恢复成 ±、压扁汉字或把控件挤出 safe rect。字体、样式、DPR 和 live/pinned 角色变化都需使相关尺寸缓存正确失效。

## 4. 与前一份修复计划的衔接

[进度区与 Pin 投影修复计划](2026-09-20-progress-and-cursor-projection-hardening-plan.md) 继续负责同步进度布局、孤儿 Pn、拖动残影取证与 tether 可见性；其历史状态不能用来断言当前修复完成。

- CAA 不修改进度区，也不把“颜色更明显”当作残影或孤儿按钮的修复。
- `pinned_cursor_controller.py`、`pinning/presentation.py`、overlay 与 interaction/geometry 测试可能重叠。开工时先核对这些文件的未提交变更与实际验证结果，在当前修复基础上追加本计划。
- 连接线画笔/遮挡/捕获期强调沿用前一计划的 owner 和验收，本计划只统一状态语义；不得再建一套独立高亮 flag 或覆盖已校准画笔。
- 模式控件和菜单可以独立实施；涉及动态强调的整合需先明确现有捕获状态的 owner。自然拖动残影若仍 UNKNOWN，报告保留 UNKNOWN，不阻止独立控件结果的如实交付。

## 5. 分步实施与验证

### T0 — 核对工作区与建立有针对性的行为基线

- 记录 HEAD、相关 dirty 文件及已执行的验证；保留其他任务修改，不自行暂存、重置或提交。
- 核对可复用的按钮组/菜单样式及标题布局 seam；确认现有模式默认值、独立 Pin 偏好和 unpin 编号复用。
- 针对后续每项行为先补可失败的 owner 测试/确定性探针，随后实施；不为文案机械写测试，不要求预先全量 baseline。

### T1 — 分段控件与标题几何

**Owner**：`mf4_analyzer/ui/chart_stack/cursor_pill.py`；只有已证实共享需求时才抽到现有 widgets 层，不新建跨模块设置 owner。

1. 用互斥“数值 / 完整”替换 ±，将用户动作收敛到显式目标模式入口，旧 toggle seam 如有调用则薄包装复用。
2. 用户操作、快照恢复、结构化投影都更新同一控件状态；前者才提交一次模式意图。
3. 改标题控件实测预算，覆盖 `_primary` margins、文档宽度、表格布局、空间不足与模式切换的锚定；为 T3 的编号菜单预留同一测量入口，不硬编码按钮个数。
4. 校验真实绘制的 QTextDocument 与表格最后一列；不能用另建的、参数不同的文档证明未裁切。

**Focused**：`tests/ui/test_cursor_table_modes.py`、`test_cursor_table_geometry.py`、`test_cursor_single_pipeline.py`、`test_cursor_display_settings.py` 的相关用例；补幂等选择、恢复无信号、两 Pin 模式独立、窄宽/长名称/字号变化。

### T2 — Pn 蓝色三态与几何一致性

**Owner**：`mf4_analyzer/ui/pg_canvas/pinned_cursor_overlay.py`；`pinning/presentation.py` 仅负责已有交互事实到呈现的连接。

1. 实现三态颜色、空/实心点及外环；开合和暂态强调分开输入，绘制时组合，避免 hover 覆盖开合语义。
2. 沿用现有捕获/焦点 owner，补全菜单及子控件的交互边界；释放、取消、销毁均复位。
3. 实测外尺寸同步 solver、caption、hit rect；cluster/member、dual endpoint、边缘标记采用一致状态规则，不改变端点映射。

**Focused**：`tests/ui/test_pinned_cursor_geometry.py`、`test_pinned_cursor_interaction.py`；检查灰度下空/实心与实底仍可区分，原生合图的文字/状态点清晰；快速 press→release 无 MouseMove 仍提交最终坐标一次。

### T3 — 移除固定 P，接入编号菜单

**Owner**：`cursor_pill.py` 的标题及信号；`pinning/presentation.py` 的装配。controller/commands 仅在必需的既有动作连接处修改，不重写生命周期。

1. 固定角色显示 `Pn ▾` 和 ×；live 角色保留 P；同步 T1 的标题尺寸与缓存失效。
2. 增加菜单动作并接入既有收起、unpin、close；避免 `.connect(lambda ...)`，遵循已有槽/partial 方式。
3. 统一 × 与菜单删除的 tooltip、状态反馈及 accessible name；删除命令一次执行，不意外恢复 live。
4. 覆盖菜单打开时 View 切换/删除/隐藏，确保不会操作旧 scope；复用既有 Qt ownership/teardown 机制。

**Focused**：`tests/ui/test_pinned_cursor_panels.py`、`test_pinned_cursor_lifecycle.py` 的相关用例。验证收起后能重新打开、unpin 接回 single/dual 且编号复用、× 清除全部投影而不接回 live、子按钮点击不拖动、菜单失效不复活记录。

### T4 — 提示、边界及原生验收

**Owner**：`mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`；涉及控件的 owner 测试和必要用户说明。

- 同步替换 ±、蓝图钉、含糊“关闭”等旧操作说明，明确 × 删除、Pn 收起、编号菜单取消固定。P 快捷键本身保持现有上下文路由。
- **Focused**：`tests/ui/test_quickref_status_hints.py`；涉及 quickref 展示再追加对应现有用例。
- **Boundary**：修改信号连接运行 `tests/ui/test_no_lambda_signal_connections.py`；改 QSS 运行 `tests/ui_kit/test_qss_border_shorthand.py`；碰 canvas backref 或中立层再分别运行已有 backref/import 门，不因 UI 改动直接通跑全部 tests/ui。
- 在稳定工作区只执行一次适用的整合测试集合，复用同指纹已通过结果。项目 Qt 测试使用 `.venv/bin/python`、隔离 QSettings 与 offscreen 环境；不并发运行全量套件。
- 用真实 ChartStack + 生产样式检查像素与几何，再做 Cocoa 自然交互；Windows 缩放/冻结版没有实测环境就明确 `UNVERIFIED`。HTML 与 offscreen 不替代原生验收。

## 6. 最小验收矩阵

采用代表组合，不要求所有维度全排列；每行需留下对应证据。

| 组合 | 通过标准 |
| --- | --- |
| live / pinned，各数值 / 完整 | 两选项都可读可点，当前值明确；无最小化误解；固定面板无 P，live 有合法固定入口 |
| 两张 Pin 独立切模式，随后 View/快照恢复 | 状态独立、内容不串；用户变化只提交一次，恢复不发意图信号 |
| 收起、打开、打开且激活 | 三态可一眼区分；空心点始终代表收起；hover 不把收起画成打开 |
| 标题拖动、Pn 拖动、拖出控件、快速松手、Esc/失焦取消 | 捕获期强调稳定；最终坐标提交一次；面板拖动不改 Pin X；结束后无卡住高亮 |
| 编号菜单三个动作及 × | 收起保留记录；unpin 正确接回活动游标；删除完整清理且不接回；关闭菜单不触发动作 |
| 菜单打开时切 View、关闭源、删除 Pin | 菜单关闭或失效；无旧 scope 回调、孤儿按钮、记录复活 |
| Time-X / Custom-X 单双游标；FFT 多 pane；FRF 线性/对数域 | 对应内容/坐标/端点语义保持，未开放的域能力不新增；FFT preview 不出现错误 Pin |
| P12、Pn·A/B、A=B、重叠簇、画布边缘、空间不足/不可用 | 标签实际外框与命中一致；圆点/外环/最后一列不裁切；不可用原因仍可理解 |
| 长名称、窄画布、系统字体/缩放、键盘-only | 真实标题控件互不重叠；焦点可见；模式与菜单可访问；不以固定英文宽度估算汉字 |
| 复制图片 / UltraView | 静态 Pn 状态和面板模式与当前记录一致；popup 不进入持久内容，不恢复旧投影 |

原生拖动验收包含 **press → 多次 move → 停住但不松手 → release → settle**，不只检查最后一帧。旧残影问题的自然屏幕证据仍由前一计划负责，不能用最终 grab 干净代替。

## 7. 完成定义与本轮文档验证

实施完成需同时满足：CAA 交互落地、相关 focused/boundary 门通过、生产样式几何与原生状态变化有证据、hints/quickref 一致、未扩大到未授权功能。报告分别列出实现、自动化、offscreen、Cocoa 和 Windows 状态；未跑的门如实标注。

本轮为 docs-only：核对所引用的原型、源码 owner、测试路径和前序计划，检查文档差异与空白错误；**不运行产品测试，不修改产品代码，不宣称完成 CAA 实施**。已有布局/标签 lessons 足以覆盖本次计划约束，无需重复新建 lesson。
