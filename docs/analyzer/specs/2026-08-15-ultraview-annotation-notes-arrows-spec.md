# UltraView 画布创作工具（便签贴纸 + 画笔 + 形状 + 文字）Spec

日期：2026-08-19 · 状态：**DRAFT，未授权产品执行**
配套 plan：`docs/analyzer/plans/2026-08-15-ultraview-annotation-notes-arrows-plan.md`

上游输入：

- `2026-08-14-ultraview-miro-narrow-rail-spec.md`（浮岛、画布与 rail 视觉合同）
- `2026-08-14-ultraview-p3-canvas-interaction-spec.md`（直接操纵、视口变换与卡片整格合同）
- 用户提供的 4 张 Miro 截图（2026-08-19）：画笔工具组、16 色便签、基础形状菜单、文字浮动工具条
- Miro 官方帮助中心：[Sticky notes](https://help.miro.com/hc/en-us/articles/360017572054-Sticky-notes)、[Pen](https://help.miro.com/hc/en-us/articles/360017730573-Pen)、[Text](https://help.miro.com/hc/en-us/articles/360017572094-Text)、[Connection lines](https://help.miro.com/hc/en-us/articles/360017730733-Connection-lines)、[Working with objects](https://help.miro.com/hc/en-us/articles/360017730953-Working-with-objects)

> 术语：本文的「贴纸」指截图中的 **Sticky Note / 便签贴纸**，不是 emoji、人物或装饰性贴纸图库。

## 0. 结论

UltraView 自由网格 Board 增加一套轻量、Miro 式的**画布创作工具**：便签贴纸、
自由文字、基础形状/连接线、画笔。四类内容不是四套互不相干的插件，而是同一套
`author_objects` 作者对象：共享坐标、选择、细吸附、锁定、层级、复制/删除、撤销、
Fit、整板概览、演示和 PNG 导出。

产品定位仍是「分析结果对比板的表达收尾」，不是通用协作白板。Miro 中与单机分析
汇报直接相关且实现边界清楚的行为尽量复制；会引入 AI、协作服务、复杂图算法或
跨平台不确定性的能力做明确精简，不留下“以后自然就有”的隐含承诺。

当前旧 spec/plan **不能直接执行**，因为它们仍假定空白 Board 没有右键菜单、选择只
覆盖卡片、导出/Fit 边界只来自卡片、undo 只需扩大 placement 快照，而且把本次需要的
画笔/形状/独立文字列为非目标。本版以 2026-08-19 的实际代码接缝重写这些合同。

## 1. Miro 对标与精简裁决

| 面 | Miro 参考行为 | UltraView V1 复制 | 明确精简 / 延后 |
|---|---|---|---|
| 便签贴纸 | `N`、16 个固定可读色、点击/拖放创建、改形、批量改色、Sticky Stack、约 3000 字符 | `N`、16 色、方形/宽形、点击创建后立即编辑、拖拽定尺寸、批量改色、轻量 Stack、3000 字符 | 不做 AI Generate、标签/作者/投票、表格粘贴转便签、Bulk mode 面板 |
| 画笔 | `P`、笔/高亮、三组预设、智能绘图、整笔/精密擦除、lasso | `P`、笔/高亮、每种 3 预设、整笔擦除、简化 lasso、鼠标/触控板/手写笔基础输入 | 不做智能图形识别、局部切割式精密擦除、压感宽度、掌触拒绝、手写转文字 |
| 形状与线 | Line/Arrow/Elbow/Block Arrow、Rectangle/Oval/Rhombus/Triangle/Divider、连接点、线型/箭头/颜色 | 截图中 9 个基础项全部保留；直线/箭头可锚定卡片和作者对象；闭合形状可含一段文字 | Elbow 只做确定性的单折/双折正交路径，不做避障；不做 More shapes、Diagram packs、自定义 SVG、曲线路由/line jumps |
| 文字 | `T`、字体/字号、B/I/U、对齐、列表、链接、文字色、highlight、锁定 | `T`、3 个跨平台字体角色、字号、整框 B/I/U、左中右对齐、项目符号/编号、整框链接、文字色/底色、锁定 | V1 不做字符级混排、多级列表、自定义字体上传、旋转、评论、AI |
| 通用对象 | `V` 选择、框选/多选、smart guides、duplicate、lock、z-order、align/distribute | 混合选择、作者对象复制/锁定/层级/对齐/均分、细网格与 smart guides、原子 undo | 不做持久化 group hierarchy、frames/layers、协作保护锁、对象类型筛选；不改变卡片既有复制/层级语义 |

上述“延后”项不是 V1 验收的隐藏缺口。首版完成后若要继续贴近 Miro，优先级为：
字符级富文本 → 精密擦除 → 持久化分组 → 更多形状；AI/评论/协作不进入当前路线。

## 2. 目标与非目标

### 2.1 目标

1. 用户能从常驻创作区一眼发现 `选择 / 便签 / 文字 / 形状 / 画笔`，并用快捷键进入。
2. 四类对象共享可靠的混合选择、移动、resize、复制、删除、锁定、层级、对齐、撤销。
3. 作者对象使用连续 Board 坐标和细吸附；既有卡片继续使用 schema 5 的整格/半格
   `GridRect`、碰撞规划与全有全无提交，不能被创作工具暗改。
4. 连接线端点可锚定卡片、便签、文字和形状；目标移动/resize 后线仍跟随。
5. screen / Fit / overview / presentation / PNG 1×/2× / 整板复制使用同一份几何和
   样式合同，不裁掉负坐标或卡片外侧的作者内容。
6. 中文 IME、macOS/Windows 键盘焦点、鼠标/触控板和基础手写笔输入可用。
7. 作者对象随 Board 保存、可前向透传、进每板 undo/redo；不进入 preview digest，
   不触发分析计算或预览重抓。

### 2.2 非目标

- 无限画布或 QGraphicsView 重宿主；仍使用现有 signed elastic workspace + safety bounds。
- 模板布局模式编辑作者对象；对象数据保留，切回 free-grid 后恢复可见可编辑。
- 实时协作、评论、@、投票、作者身份、保护锁、云端素材库。
- AI Generate、AI 绘图、智能手绘识别、OCR/手写转文字。
- BPMN/AWS/流程图库、自定义 SVG、曲线路由、避障路由、line jumps。
- 字符级富文本、多级列表、任意旋转、压感宽度、掌触拒绝、局部像素擦除。
- 改变分析卡片内容、源 View、预览身份或分析计算结果。

## 3. 核心产品决策

| # | 决策 | 裁决 |
|---|---|---|
| D1 | 入口 | 扩展现有左侧 rail，新增独立的 creation section：`选择 / 便签 / 文字 / 形状 / 画笔`。panel 信号与 tool 信号分离；现有 Board 空白右键菜单继续只承载「适应/100%/概览/自动整理/复制/导出」，不再假定它不存在，也不把创作入口塞进去。 |
| D2 | 适用模式 | creation section 始终可见；free-grid 可用，template/presentation/overview 中禁用并给出原因。切模式不删对象。 |
| D3 | 坐标 | 作者对象持久化为 schema 5 当前 canonical micro-grid 的**浮点坐标**。1 个当前 micro-cell = 原物理格的 1/2；默认 lattice 为 0.25 micro-cell，即原物理格的 1/8。坐标允许为负，但必须落在现有 safety bounds。 |
| D4 | 吸附 | smart guide（边/中心/等距，捕获半径 6 屏幕 px）优先于 0.25 micro-cell lattice；macOS `Cmd` / Windows `Ctrl` 在拖动时临时关闭吸附，沿 Miro 平台习惯；Alt 保留给复制拖动，不再承担“关吸附”。 |
| D5 | 选择身份 | 引入 Qt-free `BoardItemKey`：`card(UltraViewRef)` 或 `author(object_id)`。Page/gesture/context island 都投影同一选择集合；不再用 `_selected: UltraViewRef | None` 承载所有类型，也不使用歧义 `target_id: str`。 |
| D6 | 连接锚 | `AnchorTarget` 是结构化 union：card 存 `UltraViewRef`，author 存 `object_id`。默认 `auto` 解算最近边界，也可固定 N/E/S/W；目标删除时端点退化为最后解算自由点，并只提示一次。 |
| D7 | 渲染结构 | paint-only `AuthorPaintLayer` 与可交互 `StickyNoteWidget` / `BoardTextEditor` 是 `FreeGridBoard` 的**同级子对象**。不能把可交互 editor 放进 `WA_TransparentForMouseEvents` 的透明父层。所有 pointer 手势仍只有一个 `BoardInteractionController` owner。 |
| D8 | 层级 | 卡片是固定底层；所有作者对象在卡片上方；selection/guide/ghost chrome 最上。作者对象内部按持久化顺序排列，支持前移/后移/置顶/置底；卡片与作者对象之间不跨 band 重排。 |
| D9 | undo | 不把高点数 stroke 复制进全量 placement snapshot。使用 `BoardEditEntry`：可选 placement before/after + 精确 object patch before/after；一次手势/一次文字提交/一次样式批改只产生一条记录。 |
| D10 | 持久化 | Board payload additive 增加 `author_objects`，保持 `ULTRAVIEW_SCHEMA = 5`。2026-08-19 审计已证实现有 Board `passthrough` 的嵌套值在 duplicate 后仍浅共享：先以红测修成深度隔离/保真，再实施对象模型；不通过 bump schema 绕开。 |
| D11 | 范围上限 | 每板作者对象最多 240；其中 stroke 最多 120；每 stroke 持久化点最多 2048、全板总点最多 60,000；便签 3000 字符、文字框 6000 字符。超限拒绝并给出可行动 toast。 |
| D12 | digest/dirty | 作者对象不进 preview digest、不触发 recapture；任何持久化改变都必须 `mark_workspace_mutated`。摄像机、hover、工具选择、临时 path、选区不存盘。 |

## 4. 通用交互合同

### 4.1 Rail、工具状态与快捷键

- Rail 视觉顺序分三段：
  `Library / FreeGrid / Layout / Filter` → divider →
  `Select / Sticky / Text / Shapes / Draw` → divider →
  `Unplaced / SyncAll`。
- `V` 选择、`N` 便签、`T` 文字、`P` 画笔、`L` 连接线；形状菜单内保留
  `R` Rectangle、`O` Oval。快捷键在 `QLineEdit`、`QTextEdit`、
  `QPlainTextEdit` 或其 viewport 后代获得焦点时全部不抢占。
- 便签、文字、闭合形状是 one-shot：成功放置后回 Select；双击 rail 按钮可 pin，
  连续创建直到 `V`/Esc。笔、高亮、擦除、lasso 默认保持激活。
- Esc 顺序：提交/退出文字编辑 → 取消未完成对象/当前 stroke → 回 Select → 清选择
  → 既有 panel/overview/presentation 栈。不能绕过统一 `clear_board_selection()`。
- 激活工具时，鼠标主操作归工具；中键、Space+左键和已有右键拖动仍可平移。
  右键短按仍合成既有 card/board context menu，右键拖动不弹菜单。

### 4.2 选择、变换与通用工具条

- 命中优先级：editor/resize/anchor handle → 作者对象（逆 z）→ 卡片 → 空白。
- 单击选中；Shift+点增减；marquee 可混选卡片和作者对象；lasso 以对象中心落入
  闭合套索为选中标准（这是对 Miro 90% 覆盖规则的刻意简化）。
- 混合组移动：只含作者对象时走细 lattice；含卡片时由卡片合法整格 delta 决定，
  同一 delta 作用于作者对象，任一卡片非法则整组弹回。作者对象不参与卡片碰撞。
- resize 只针对单个便签/文字/闭合形状；8 向手柄，Shift 保持比例。
  connector 用端点/折点手柄；stroke 不 resize，允许整体移动。
- Delete/Backspace 对混合选择保持既有分工：卡片移到 Unplaced，作者对象删除，同一条
  history 原子恢复。Cmd/Ctrl+D、Cmd/Ctrl+C/V、锁定、前移/后移/置顶/置底只作用于
  作者对象；既有卡片 copy-as-image/context action 不变。
- 纯作者对象多选提供左/中/右、上/中/下对齐与水平/垂直均分；V1 不拿卡片参与
  对齐/均分，避免绕过卡片 collision planner。
- 锁定对象仍可被点选并显示锁态，但不能移动、编辑、resize、删除；再次解锁后恢复。
- 浮动工具条贴选区上方并 clamp 在 CanvasHost 可见区；空间不足时放下方。它只显示
  当前选择共同可用的动作，不能遮住 rail/popover。

### 4.3 细吸附与 guides

- lattice = 0.25 canonical micro-cell；拖动、resize、自由线端点适用。
- guide 候选来自视口邻近的卡片和作者对象外框：左右边、水平中心、上下边、垂直中心，
  另提供等距提示；一次最多显示水平/垂直各一条和一组等距标记。
- 捕获半径固定 6 屏幕 px，需按 zoom 反算 Board delta；guide 优先，lattice 其次。
- macOS Cmd / Windows Ctrl 临时关闭两类吸附；松开恢复。Alt+拖动复制当前可复制选择。
- 卡片自己的 move/resize 规划、半格 schema 5 identity 与 collision contract 不变。

## 5. 四类工具规范

### 5.1 便签贴纸

- 点击 Sticky 或按 `N` 后：单击创建默认 4×3 micro-cell 便签并立即编辑；拖拽则按
  起止点创建，最小 2×1.5 micro-cell，放开后编辑。
- 形态：Square（默认）/ Wide 两种；双击文字编辑；自动换行；默认自动字号，用户
  可在 `12 / 14 / 18 / 24` 四档覆盖。空白新便签退出编辑时自动删除。
- 色板按截图提供 4×4 共 16 个固定 palette token；不存 hex。每个 token 同时定义
  light/dark fill、border 和可读前景色；不开放任意颜色选择器。
- `Stack` 是低复杂度实现：在点击处创建 6 个普通空便签，依次偏移 6 个 100% px；
  顶部便签可直接拖走，露出下一张。**不新增 Stack 容器类型或补充库存逻辑**，因此
  保存、选择、undo 和导出都只处理普通便签。创建整叠是一条 undo。
- 多选便签可统一颜色、形态和字号；Enter/Tab 提交后在右侧生成同色同尺寸新便签，
  作为轻量连续录入。AI Generate、tag、author、vote 不出现占位按钮。
- zoom < 40% 只画底色与短文本占位，编辑器关闭；恢复到 ≥40% 后完整渲染。

### 5.2 文字

- 点击 Text 或按 `T`，在 Board 点击生成 auto-width 文本框并立即编辑；拖拽可先定宽。
- 文本框最多 6000 字符；中文 IME、复制粘贴、撤销输入由真实 `QTextEdit` 承担。
- V1 格式是**整框级**：字体角色 `sans / serif / mono`，字号 8–72，B/I/U，
  左/中/右对齐，普通/项目符号/编号列表，文字色，transparent/16 色底色，0–100%
  不透明度，单一 `http/https` 链接。选择局部字符后改样式仍应用到整框，并在 tooltip
  明示；不伪装成字符级富文本。
- 字体持久化语义 role，不存机器字体名；screen/compositor 通过同一 resolver 选择
  Noto Sans CJK/系统无衬线、衬线和等宽 fallback，CJK 缺字不得静默变豆腐块。
- 链接在编辑模式只显示；presentation 中 Cmd/Ctrl+click 才打开，普通点击仍选中。
  非 `http/https` 拒绝保存。PNG 只画可见链接样式，不声称可点击。
- resize 左右边改换行宽度，上下边只改框高度；不做旋转和字符级混排。

### 5.3 形状与连接线

- Shapes popover 顺序与截图一致：Line、Arrow、Elbow arrow、Block arrow、
  Rectangle (`R`)、Oval (`O`)、Rhombus、Triangle、Divider。没有不可用的 More shapes/Diagram
  占位入口。
- 闭合形状单击拖拽创建，默认 transparent fill + ink stroke；Block arrow 作为闭合
  shape。双击闭合形状可编辑一段居中文本，复用文字对象的整框级子集（字体角色、
  字号、B/I/U、对齐、文字色），文本仍属于 shape，不产生子对象。
- Divider 是无箭头直线；Line/Arrow/Elbow 是 connector。`L` 进入最近使用的 connector；
  Shift 约束水平/垂直/45°。
- connector 可通过两击创建，也可从选中 card/note/text/shape 的 4 个边点拖出。
  松手在目标轮廓 = 结构化锚定；空白 = 自由端点；Cmd/Ctrl 暂停锚定。
- 样式：1/2/4/8 px 四档，实线/虚线，16 色 + ink，start/end arrowhead 可独立为
  none/arrow。Block arrow 仅支持 fill/stroke，不转换成 connector。
- Elbow 采用确定性正交：auto 只选 `H-V` 或 `V-H` 的较短无自交方案；用户可拖一个
  中间 control 改折点。目标之间不做障碍检测，移动目标后重新按相同规则解算。
- 目标删除/移到未放置时，端点固化为删除前最终 Board 点；一条线两端都脱离也保留。

### 5.4 画笔

- Draw popover 包含 Pen、Highlighter、Eraser、Lasso；Pen/Highlighter 各有 3 个
  可编辑 preset，每个 preset = 颜色 + 线宽。默认选中的 preset 在 rail 上有明确状态。
- presets 是**每用户 UI 偏好**，通过现有隔离过的 QSettings 路径保存；不进入 Board、
  项目 payload、history 或 preview digest。当前 active subtool/preset 仅为会话态。
- pointer-down 到 pointer-up 是一个 stroke、一次 undo。采样存 Board 坐标；先做最小
  屏幕距离去抖，再用确定性 RDP 简化，最终不超过 2048 点；屏幕与导出从同一 points
  建 `QPainterPath`。原始事件点不进持久化或 undo。
- Pen 不透明、圆头圆接；Highlighter 固定 35% alpha、multiply-like 观感以普通
  source-over 可复现实现为准，不提供透明度滑杆。
- Eraser 是**整笔擦除**：路径扫过 stroke 的 hit corridor 即删除整条 stroke；一次
  pointer session 内删掉的多笔合为一条 undo。它不删除卡片/便签/文字/形状。
- Lasso 对所有可选 Board item 生效，闭合后按对象中心判定；锁定对象不加入结果。
- QTabletEvent 若存在按普通 pointer 采样，V1 不存 pressure/tilt；鼠标、触控板、笔
  产生相同确定性结果。工具激活时仍必须保留 Space/中键/右键画布平移。

## 6. Qt-free 数据合同

以下是语义模型，不要求实现逐字采用继承；序列化必须保持这些字段和边界：

~~~python
@dataclass(frozen=True)
class BoardPoint:
    x: float                    # schema-5 canonical micro-grid units
    y: float

@dataclass(frozen=True)
class BoardBox:
    x: float
    y: float
    width: float
    height: float

@dataclass(frozen=True)
class BoardItemKey:
    kind: Literal["card", "author"]
    card: UltraViewRef | None = None
    object_id: str | None = None

@dataclass(frozen=True)
class AnchorTarget:
    kind: Literal["card", "author"]
    card: UltraViewRef | None = None
    object_id: str | None = None
    anchor: Literal["auto", "n", "e", "s", "w"] = "auto"

@dataclass
class AuthorCommon:
    object_id: str              # UUID
    kind: str
    locked: bool = False

@dataclass
class StickyObject(AuthorCommon):
    box: BoardBox
    text: str
    palette: str
    shape: Literal["square", "wide"]
    font_size: int | Literal["auto"]

@dataclass
class TextObject(AuthorCommon):
    box: BoardBox
    text: str
    font_role: Literal["sans", "serif", "mono"]
    font_size: int
    bold: bool
    italic: bool
    underline: bool
    align: Literal["left", "center", "right"]
    list_style: Literal["none", "bullet", "number"]
    text_palette: str
    fill_palette: str | None
    opacity: int
    link: str | None

@dataclass
class ShapeObject(AuthorCommon):
    box: BoardBox
    shape: Literal["rectangle", "oval", "rhombus", "triangle", "block_arrow"]
    text: str
    fill_palette: str | None
    stroke_palette: str
    stroke_width: int
    line_style: Literal["solid", "dashed"]
    text_style: ShapeTextStyle

@dataclass
class StrokeObject(AuthorCommon):
    points: tuple[BoardPoint, ...]
    tool: Literal["pen", "highlighter"]
    palette: str
    width_px_100: int

@dataclass
class ConnectorEndpoint:
    point: BoardPoint           # last resolved point; target loss fallback
    target: AnchorTarget | None

@dataclass
class ConnectorObject(AuthorCommon):
    start: ConnectorEndpoint
    end: ConnectorEndpoint
    route: Literal["straight", "elbow"]
    elbow_bias: float | None
    line_style: Literal["solid", "dashed"]
    stroke_palette: str
    stroke_width: int
    start_head: Literal["none", "arrow"]
    end_head: Literal["none", "arrow"]

UltraViewBoardState.author_objects: list[
    StickyObject | TextObject | ShapeObject | StrokeObject | ConnectorObject | UnknownAuthorObject
]
~~~

- list 顺序就是作者对象 z-order；未知 `kind` 保留原 mapping 与相对位置，不参与渲染、
  命中或对象上限之外的复杂变换，但再次保存必须深度保真。
- recognized 非法对象丢弃并产出具名 warning；NaN/Inf、非法尺寸、越 safety bounds、
  过长文本/points、悬空 author target 都要有确定性 normalization。
- clone/copy/history 不允许浅拷贝可变 passthrough 后继续原位修改；未知对象 round-trip
  用深度语义等价验证。
- `author_objects` 是 Board 作者内容，进入项目持久化；生成 card preview presentation
  payload/digest 时必须显式排除。旧构建只要不认识该键，应通过 Board passthrough 原样写回。

## 7. 几何、边界与渲染

### 7.1 单一几何源

Qt-free `author_geometry.py` 负责：

- BoardPoint/Box ↔ pixel 映射；lattice/guide snap；shape path；connector anchor/route；
- stroke simplify、bounds、hit corridor；marquee/lasso 命中；
- `BoardContentBounds(cards, author_objects)`：卡片、便签、文字、shape、connector 的
  arrowhead、stroke 宽度全部纳入，向外 floor/ceil 到 canonical micro-cell。

screen、Fit、elastic extent、overview、compositor 只能消费这套函数，不能各写一份
“差不多”的 bounds。空 Board 但有作者对象时不再走空板 two-card working frame。

### 7.2 QWidget / painter 分工

- `AuthorPaintLayer`：shape、connector、stroke、guide、selection chrome；透明、paint-only。
- `StickyNoteWidget`：只在可读 LOD/编辑态实例化或显示，负责真实文本输入与语义颜色。
- `BoardTextEditor`：编辑 text/shape label 的临时 sibling editor；提交后普通 text 由
  painter/轻量 label 渲染，避免 240 个常驻 QTextEdit。
- 交互 widget 不能挂在 transparent-for-mouse-events 父层下；overlay 的 resize/zoom/
  destroyed 生命周期由 FreeGridBoard 单点协调，不能向 MainWindow 写状态。
- 线宽、字号以 100% logical px 持久化，乘 zoom/export factor；可见线宽下限 1 physical px。

### 7.3 层与合成

合成顺序固定：Board 背景 → cards → author objects 持久化顺序 → presentation-visible
link/lock 标记（如适用）。selection/handles/guides/cursor 不进入 export。

- PNG 1×/2×、整板复制和 BoardOverview 使用同一个 compositor；overview 可用低 LOD，
  但不能完全漏掉对象。
- Fit 与 export crop 使用同一 `BoardContentBounds`，并保留 canonical padding；负坐标
  通过 origin offset 映射，不能 clamp 回 0。
- 演示模式显示全部作者内容，隐藏编辑 chrome；链接仅 Cmd/Ctrl+click 响应。
- template 模式不显示作者对象，overview/export 若 Board 当前为 template 也不合成它们；
  切回 free-grid 后数据恢复。这一点避免自由坐标与模板槽位产生伪对应。

## 8. History、状态与错误语义

~~~python
@dataclass(frozen=True)
class ObjectPatch:
    object_id: str
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    before_index: int | None     # delete/reorder 前的 author z-order
    after_index: int | None      # create/reorder 后的 author z-order

@dataclass(frozen=True)
class BoardEditEntry:
    label: str
    placement_before: BoardPlacementSnapshot | None
    placement_after: BoardPlacementSnapshot | None
    object_patches: tuple[ObjectPatch, ...]
~~~

- stroke 在 release 前只存在 transient draft；取消/窗口失活不写 state、不推 history。
- editor 聚焦期间 Cmd/Ctrl+Z/Y 属于 QTextEdit；提交后一次 Board undo 回退整次编辑。
- `before_index` / `after_index` 是 patch 合同的一部分：仅靠 object_id/before/after 无法无歧义
  恢复 create/delete/reorder。mixed move、align/distribute、Stack、eraser sweep、批量 style
  都是一条 BoardEditEntry。
- history 每 Board 最多 100 条，并增加约 32 MiB 的序列化 payload 软预算；超过时丢最旧，
  不能因为一笔过大冻结 UI。超硬上限的 stroke 在提交前简化/拒绝，不进入 history。
- target 丢失是可恢复作者状态变化：端点退化 + 一次 toast。非法持久化对象是 data warning；
  Qt/编程错误不能被 broad `except` 降级。

## 9. 性能与量化验收

1. **Miro 核心路径**：`N/T/P/V/L/R/O` 焦点守卫正确；rail/popup/浮动工具条与四张
   参考图的层级、选中态、圆角/阴影、可见反馈相符，允许 TraceLab 配色而非像素抄色。
2. **吸附**：lattice 精确为 0.25 micro-cell；guide 捕获阈值 6 屏幕 px，Cmd/Ctrl 临时
   关闭；相同输入在 screen/export geometry 中结果一致。
3. **选择**：card + 四类作者对象可混选、组移、复制、删除；Esc 只清一个统一选择源，
   CardContextIsland/author toolbar 不残留。
4. **便签/文字**：中文 IME 可提交；16 色深浅主题对比可读；3000/6000 字符边界可测；
   Stack 创建 6 个普通对象且一次 undo。
5. **画笔**：同一采样输入产生稳定简化 points；每笔 ≤2048、全板 ≤60,000；Eraser
   只删除相交 stroke；一笔/一扫均一条 undo。
6. **连接**：锚定任一 card/note/text/shape 后移动/resize，端点仍在边界；目标删除后
   退化点等于删除前最终解算点，toast 一次。
7. **边界一致**：只放一个负坐标 stroke 或 note 的 Board，Fit/overview/export 均包含；
   100% screen 几何映射到 PNG 1× 偏差 ≤1 px，2× 等比。
8. **持久化**：满载 240 objects / 60,000 points 保存→载入→保存语义一致；未知 kind
   与旧构建 passthrough 深度保真；无作者对象的现有项目 payload 不发生无关 churn。
9. **性能**：真机 24 cards + 120 mixed author objects + 30,000 persisted points，连续 zoom/
   pan 与 pen drawing 的 p95 frame time 相对同 Board 无作者对象基线退化不超过 15%；
   pointer move 不每帧重建整板 QImage、不同步重排全部 QTextEdit。
10. **零计算**：创建/编辑/导出作者对象不触发 preview capture、分析计算或 digest 改变，
    只设置 workspace dirty。

## 10. 后续 Miro 差距（不进本轮 Definition of Done）

按价值/复杂度排序：

1. 字符级 rich text 与多级列表；
2. precision eraser（stroke 分段重建）与可选 pressure/tilt；
3. 持久化 group hierarchy、组内编辑、group copy/paste；
4. 曲线 connector、手工多折点、line jumps、轻量避障；
5. 更多基础/工程 shape packs 与自定义 SVG；
6. frame/layer、批量粘贴为便签、tag；
7. AI、评论、协作身份与保护锁（除非产品定位发生变化，否则不建议进入 TraceLab）。
