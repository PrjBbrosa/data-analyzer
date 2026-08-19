# UltraView Miro 式作者体验 Spec

- 日期：2026-08-20
- 状态：**M0.3 DIRECTION ACCEPTED WITH AMENDMENTS**；作者纵切已落地，平台验收仍见配套 Plan 的 M8 PARTIAL
- 适用范围：UltraView Free Grid 的创作 chrome、Text、Shape、Connector、Pen、Highlighter、Eraser、Lasso
- 前置恢复 Spec：`2026-08-19-ultraview-recovery-interaction-resize-autofit-spec.md`
- 行为/数据基线：`2026-08-15-ultraview-annotation-notes-arrows-spec.md`
- 配套实施 Plan：`../plans/2026-08-20-ultraview-miro-authoring-completion-plan.md`
- 被拒绝的旧方向：`../ui-prototypes/2026-08-19-ultraview-authoring-tools-prototype.html`

> 2026-08-20 M8 supersession：M0–M7 作者纵切已落地。当前 release 入口是 Select / Sticky / Text / Shapes / Connector / Draw（Draw flyout 含 Eraser/Lasso）。下文 §0「release rail 仍只展示 Select + Sticky」与 §15「当前」行描述的是当时基线，不是现在的产品入口。当前用户可见合同见 `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py` 与 `mf4_analyzer/help/ultraview-guide.html`。Cocoa / Windows frozen / 全量套件仍 UNVERIFIED。

> 本文不是“把按钮补出来”的清单。它定义用户看见什么、工具怎样进入/退出、对象如何创建与编辑、
> chrome 如何避让画布、什么证据才算完成。未通过本文每个纵向切片出口前，对应 release 入口保持隐藏。

## 0. 当前结论

当前 checkout 已经不再是 2026-08-19 review 时的 dead-button 状态：

- `a4035287` 已接通 Select + Sticky，并建立 `BoardInteractionController`；
- `03d42d97` 已拆出 Card Fit solver；
- release rail 仍只展示 Select + Sticky；
- Text/Shape/Stroke/Connector 的 state、解析、基础 render 和部分 chrome scaffold 已存在；
- Page/coordinator 只完成 Sticky 纵切，其他工具没有 release 级 create/edit/history/save 事务；
- 当前还有 resize/ghost 相关未提交源码，本文不触碰、不把它们视为已验收结果。

因此，后续不能重新铺一套平行基础，也不能把 `ShapePopover`、`DrawPopover`、
`TextFormattingToolbar` 的“类已经存在”当成功能完成。正确方向是：

1. 保留已经验证的数据/几何/renderer 合同；
2. **固定 chrome 分区保持现状**：rail 与左上 Board Island 不搬家；
3. 作者体验只改工具状态视觉、flyout、选中工具条；
4. Text、Shape、Connector、Draw 分别走完整纵向切片，每一波只在完整事务通过后展示相应入口。

### 0.1 M0.3 用户决定（2026-08-20）

| 项 | 结论 |
|---|---|
| 1. rail 信息架构 | **保留全部现有入口**。Library / Free Grid / Layout / Filter / Unplaced / Sync 不迁出 rail。作者工具插在 Filter 与 Unplaced 之间。 |
| 2. Board / Add View | **左上保持现状**。Board Island 仍是板名 + 切换 + 新建 Board。不把 View Library 改成 `+ View`。 |
| 3. selection toolbar | **ACCEPTED** |
| 4. Shape / Draw flyout | **ACCEPTED**（Connector 仍独立，不混进 Shape） |
| 5. light / dark | **不做 dark**。作者 chrome 只按 light 设计与验收。 |
| 6. compact 800×560 | **ACCEPTED**（Global overflow、toolbar 不换行、rail 不截断） |

第一版把 rail 收成 creator-only、把 View Library 放到 Board Island 的方向已 **REJECTED**。旧 08-19 prototype 仍 REJECTED。

## 1. 为什么当前界面离 Miro 很远

### 1.1 保留混装 rail，修的是状态语义而不是搬家

M0.3 已决定：当前 `ToolRail` 的入口集合保持不变。Library、Free Grid、Layout、Filter、作者工具、
Unplaced、Sync 继续共用左列。产品不通过把板级动作拆到 Board Island / 状态 chip 来“更像 Miro”。

仍要修的是同一列里的**状态混淆**：`panelOpen`、`modeActive` 和 active tool 目前都像钛蓝-琥珀渐变。
用户必须先解释按钮类型，才能知道下一次点击会打开面板还是改变鼠标。作者工具继续借用 Miro 的
one-shot / 持续绘制 / 选中后上下文工具条语法，但不改固定 chrome 分区。

参考：[Toolbars](https://help.miro.com/hc/en-us/articles/360017730553-Toolbars)。

### 1.2 旧 prototype 判定为 REJECTED

`2026-08-19-ultraview-authoring-tools-prototype.html` 有以下结构性问题：

- 64 px rail + BOARD/CREATE/NAV 三块浮岛仍是“多段控制台”，不是一个连续 creation rail；
- 顶部贯穿式 topbar 占据大量画布安全区，和真实 UltraView 的 Board/Global islands 不同；
- demo 页面右侧说明栏、背景光晕和大阴影强化了展示稿感，不能回答 800×560 产品窗口怎样工作；
- 形状、画笔、文字工具条是静态演示，没有覆盖 flyout 与 selection toolbar 的避让、焦点和溢出；
- creator rail 与 View Library、布局、筛选、同步的最终归属没有作出产品级裁决。

旧 prototype 只保留为历史探索证据，不再作为实现视觉基线。M0 必须制作新的、按本文两档窗口尺寸
渲染的决策 prototype，并经用户确认后才能改产品 chrome。

## 2. 对标边界：借 Miro 的语法，不复制 Miro 产品

### 2.1 必须达到的 Miro 核心语法

| 面 | Miro 现行参考 | UltraView 目标 |
|---|---|---|
| Creation toolbar | 左侧、工具可点击或拖入；多数工具使用一次后回 Select | 左侧 creator rail；Sticky/Text/Shape/Connector one-shot，Draw 子工具持续 |
| Text | `T`，点击创建、拖入；选中/编辑时显示格式控制；单框最多 6000 字符 | 同一路径；CJK IME；整框级格式；上下文工具条 |
| Shape | `S`，基础形状菜单；选中后改 fill/border/opacity/corner | V1 基础 5 形状；格式工具条；无假 More Shapes |
| Connector | `L`，自由端点或对象锚点；context menu 改端点、线型、颜色 | 直线/箭头/正交折线；card/author 结构化锚点；目标生命周期完整 |
| Draw | `P`；Pen/Highlighter 各 3 preset；Eraser/Lasso 持续 | 同样 3 preset；整笔擦除；套索选择；首版不做 pressure/precision eraser |
| Selection | `V`、marquee、Shift 多选、lasso、align/lock/arrange | 单一 `BoardItemKey`；card/author 混选；作者对象通用 arrange |

参考资料（检索于 2026-08-20）：

- [Text](https://help.miro.com/hc/en-us/articles/360017572094-Text)
- [Shapes](https://help.miro.com/hc/en-us/articles/360017730713-Shapes)
- [Connection lines](https://help.miro.com/hc/en-us/articles/360017730733-Connection-lines)
- [Pen](https://help.miro.com/hc/en-us/articles/360017730573-Pen)
- [Working with objects](https://help.miro.com/hc/en-us/articles/360017730953-Working-with-objects)
- [Sticky notes](https://help.miro.com/hc/en-us/articles/360017572054-Sticky-notes)

### 2.2 TraceLab 的身份边界

UltraView 仍是“分析结果对比和说明板”，不是协作白板。以下不进入 V1：

- 在线协作、评论、投票、反应、用户头像、保护锁；
- AI 生成、智能图形识别、自动流程图；
- 外部 shape packs、BPMN/UML/AWS 图库、自定义 SVG；
- frame/layer 面板、任意 group hierarchy；
- pressure/tilt、precision eraser、曲线 connector、自动避障、line jumps；
- 字符级富文本和任意字体上传。

## 3. 产品体验方向

### 3.1 一句话

**Miro 的创作节奏 + TraceLab 的信号上下文。**

flyout 与 selection toolbar 使用成熟白板语法；左轨和 Board Island 保持现有分区。分析类型、数据状态和精确读数保留 TraceLab 语义。界面不靠大面积渐变、假玻璃或深阴影表达“高级”，而靠状态分离和直接反馈表达可用性。

### 3.2 唯一签名元素：Signal Spine

选中 card 时，对象工具条左缘显示 3 px 的分析类型色条，并用等宽小字显示 `TIME / FFT / TF / FRF /
ORDER`。选中 author object 时色条统一为 selection blue，显示 `TEXT / SHAPE / LINE / INK / NOTE`。

这是唯一允许带 TraceLab 强识别度的 chrome。其余创建工具保持中性，避免每个按钮同时使用钛蓝、琥珀、
分析分类色和状态色。这样既不做 Miro 像素复制，也不会退回“工程软件按钮墙”。

### 3.3 自我审查

若新 prototype 仍满足任一条件，则直接判为失败：

- 需要 BOARD / CREATE / NAV 文字标签才能解释 rail；
- 一个按钮的渐变、边框和图标颜色同时表达三种状态；
- 未选对象时仍常驻格式工具条；
- 窗口缩到 800×560 后左轨截断或工具条换成两行；
- 为“玻璃感”使用大面积半透明层，导致卡片/ghost/author paint 合成成本升高；
- 只展示漂亮静态画面，没有工具 active、flyout open、editing、dragging、selection 的状态样本。

## 4. 信息架构

### 4.1 固定 chrome 分区

| 区域 | 归属 | 常驻内容 | 不改 |
|---|---|---|---|
| Top-left Board Island | 板身份 | 板名、切换、新建 Board | 不加 `+ View`，不承载 Layout/Filter |
| Left Tool Rail | 板级动作 + 作者工具 | Library、Free Grid、Layout、Filter、作者工具、Unplaced、Sync | 不把既有入口迁到别处 |
| Top-right Global Island | 全局输出 | Display、Export、Presentation | 对象格式仍不放这里 |
| Bottom-left Status Island | 只读说明 | 现有「只读预览 · 不计算」 | Unplaced/Stale 继续用 rail badge |
| Bottom-right Navigation | 镜头 | Overview、−、zoom%、＋、Fit、1:1 | Undo/Redo 仍走键盘和菜单 |
| Selection Toolbar | 当前对象 | 类型相关格式 + 通用动作 + More | 未选中时不出现 |

Undo/Redo 保留键盘和 Board Edit 菜单；不为了“像 Miro”在 rail 额外塞 Undo/Redo。

### 4.2 Left rail 顺序

从上到下固定，与当前 `ToolRail` 一致，只在创作段插入完整作者工具：

1. View Library
2. Free Grid toggle
3. Layout
4. Filter
5. 创作段：Select (`V`) → Sticky (`N`) → Text (`T`) → Shape (`S`) → Connector (`L`) → Draw (`P`)
6. Unplaced（非零时 badge）
7. Sync（Stale 非零时 badge）

panel 按钮与 active tool 必须视觉正交：panelOpen / Free Grid mode 用中性填充；active tool 用 selection wash + 左条。不得再用钛蓝-琥珀渐变同时表达三种状态。

Release 入口仍按纵切解锁：未完成的 Text/Shape/Connector/Draw 不构造。M1 完成时创作段仍只有 Select + Sticky。

### 4.3 1280×720 布局

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ [整车问题总览 ▾] [+]                            [显示][导出][演示]          │
│                                                                              │
│ ┌────┐        ┌──────────── current selection toolbar ────────────┐          │
│ │Lib │        │▌FFT  Fill Stroke  Width  Text  Lock  ···          │          │
│ │Grid│        └────────────────────────────────────────────────────┘          │
│ │Lay │        ┌─────────┐          ┌──────────────┐                            │
│ │Filt│        │  card   │ ───────▶ │  shape/text  │                            │
│ │────│        └─────────┘          └──────────────┘                            │
│ │ V  │                                                                         │
│ │ N  │                                                                         │
│ │ T  │                                                                         │
│ │ S  │                                                                         │
│ │ L  │                                                                         │
│ │ P  │                                                                         │
│ │────│                                                                         │
│ │Unp │                                                                         │
│ │Sync│                                                                         │
│ └────┘                                                                         │
│ [只读预览 · 不计算]                              [概览][−][84%][+][适应][1:1]│
└──────────────────────────────────────────────────────────────────────────────┘
```

### 4.4 800×560 compact 布局

```text
┌────────────────────────────────────────────────────────────┐
│ [整车问题总览 ▾][+]                         [⋯][演示]      │
│ ┌──┐                                                       │
│ │Lib│     ┌──── selection toolbar ────────────────[⋯]┐    │
│ │… │     └────────────────────────────────────────────┘    │
│ │V │          card / author content                         │
│ │N │                                                       │
│ │… │                                                       │
│ │Sync│                                                     │
│ └──┘                                                       │
│ [只读预览 · 不计算]                    [−][84%][+][适应]   │
└────────────────────────────────────────────────────────────┘
```

Compact 规则：

- Global Island 只保留 overflow + Presentation；Display/Export 进入 overflow；
- Selection Toolbar 不换行：低优先级动作进 `···`；
- tool flyout 最大高为 stage 高度减 24 px，内容内部滚动；
- Unplaced/Stale 为 0 时 badge 隐藏，按钮仍在；
- tooltip 向右或向内翻转，不越过窗口；
- 左轨保持全部入口，可把 target 从 36 px 收到 32 px，但不得截断或改成横向工具条。

## 5. 视觉系统

### 5.1 核心颜色（chrome 只用 6 个）

| Token | 值 | 用途 |
|---|---:|---|
| `uvx.canvas` | `#F6F8F7` | 画布底色 |
| `uvx.surface` | `#FFFFFF` | rail、island、toolbar、flyout |
| `uvx.ink` | `#203038` | 主文本/图标 |
| `uvx.muted` | `#677880` | 次信息/shortcut |
| `uvx.selection` | `#4262FF` | active tool、selection、handles、focus |
| `uvx.signal` | `#24697C` | TraceLab identity、Board primary action、Signal Spine fallback |

琥珀只作为 warning/待处理语义，不能再参与普通 active gradient。分析类型色属于内容和 Signal Spine，
不成为通用按钮颜色。Sticky palette 是对象内容 palette，不计入 chrome token。

### 5.2 字体

- UI：`Noto Sans CJK SC`, `PingFang SC`, `Microsoft YaHei`, `Segoe UI`, sans-serif；
- 数字/快捷键/zoom/Signal Spine：`SF Mono`, `Menlo`, `Consolas`, monospace；
- rail icon 不放永久文字标签；tooltip 显示中文名 + shortcut；
- 11 px 只用于 shortcut/状态，主要按钮/菜单为 12–13 px，正文编辑默认 14 px。

Miro 2026 新设计语言强调更高对比和更广 CJK 字体覆盖；UltraView 只采纳可访问性方向，不复制其品牌：
[Miro's new design language overview](https://help.miro.com/hc/en-us/articles/25286391619986-Miro-s-new-design-language-overview)。

### 5.3 尺寸与材料

| 项 | 规格 |
|---|---:|
| stage inset | 12 px |
| Board/Global/Nav island 高 | 40 px |
| left rail 宽 | 56 px（compact 可 48 px） |
| rail target | 36×36 px（compact 可 32×32 px） |
| rail icon | 20 px |
| rail 内距/按钮间距 | 4 px / 2 px |
| surface radius | 12 px；rail 14 px |
| tool radius | 8 px |
| selection toolbar 高 | 40 px |
| flyout 宽 | 284 px（Sticky 248 px） |
| selection handle | 10 px visual / ≥18 px hit area |

Surface 使用 96–100% 不透明填充、1 px hairline 和单层克制 shadow。不得依赖 macOS blur、平台 QMenu
阴影或每卡 `QGraphicsOpacityEffect`。active tool 使用浅蓝 wash + 2 px 左侧 indicator；不使用渐变填充。

## 6. Chrome 状态合同

### 6.1 状态不能混用

| 状态 | 含义 | 视觉 |
|---|---|---|
| idle | 工具可用但未激活 | transparent |
| hover | pointer 指向 | neutral surface wash |
| active tool | 下一次画布动作 | selection wash + 左侧 2 px bar |
| flyout open | 配置面板打开 | active 保持；右侧 3 px chevron/dot，不换成另一种渐变 |
| pinned | one-shot 被固定连续创建 | active + 右上 pin glyph |
| disabled | 当前模式不可创建 | 40% opacity + 解释性 tooltip |
| editing | 真实 editor 聚焦 | selection toolbar 切换为 editing controls；creator active 不抢 shortcut |

一个时刻只有一个 active tool；flyout、pinned、selection 是正交状态。`panelOpen` 不得冒充 active tool。

### 6.2 工具生命周期

- Sticky/Text/Shape/Connector：成功创建后回 Select；双击按钮或 flyout pin 才连续创建；
- Pen/Highlighter/Eraser/Lasso：选中后持续，直到 V、Esc 或切换工具；
- 第二次点击 active Sticky/Shape/Draw 打开 flyout，不取消工具；
- Esc：editor commit/cancel → draft cancel → active tool 回 Select → 清 selection → 关闭 board overlay；
- Board switch、Presentation、Overview、Template mode：取消 draft/editor，回 Select，清 flyout；
- Space/中键/右键拖动临时 Pan，不改变 active tool；松开恢复工具 cursor。

## 7. 通用选择与上下文工具条

### 7.1 命中与选择

命中优先级保持：editor → resize/anchor handle → author 逆 z → card → blank。单击、Shift toggle、
marquee 和 lasso 都写同一个 `BoardInteractionController.selection`。

- marquee：对象与框有交集即选中；
- lasso：覆盖对象中心；锁定对象仍可选中，但不进入 move/erase；
- card + author mixed move 延续既有卡片合法 delta 合同；
- 单 author object 提供 8 向 resize（connector 为 endpoint/control handles，stroke 只整体 move）；
- selection chrome 始终高于 author paint 和 card；不进入 export。

### 7.2 Selection Toolbar

位置：优先在 selection bounds 上方 8 px，空间不足放下方；X 方向 clamp 到 stage safe rect。拖动中隐藏，
release 后一次重新定位，避免和 ghost 同帧抖动。

通用尾部固定：Duplicate、Lock、Arrange、More。Delete 放 More 和键盘，不放醒目的红底常驻按钮。

| 选择 | 左到右主要控件 |
|---|---|
| Card | Signal Spine、Open source、Sync、Focus、Card Fit、Copy image、More |
| Sticky | NOTE、shape、palette、font size/auto、align、Lock、More |
| Text | TEXT、font role、size、B/I/U、align、list、text/fill、link、Lock、More |
| Shape | SHAPE、switch type、fill、stroke、width/style、text、Lock、More |
| Connector | LINE、route、start/end head、color、width/style、Lock、More |
| Stroke | INK、Pen/Highlighter、color、width、Lock、More |
| Mixed author | MIXED、common fill/stroke if homogeneous、align、distribute、Lock、More |
| Card + author | MIXED、move/duplicate/delete/lock only；不显示危险的批量 style |

## 8. Text 纵向合同

### 8.1 创建与编辑

- `T` 或点击 Text，单击生成 auto-width text box 并立即进入 `BoardTextEditor`；
- 拖拽先定宽；最小 2×1 micro-cell，默认宽 6 micro-cell；
- 空文本退出即删除，不产生 history；非空 editor commit 只产生一条 history；
- double-click 进入编辑；Select 模式下选中后直接输入字符也进入编辑并替换内容；
- CJK IME composition 期间 Enter/Esc/shortcut 不被 board 截获；
- 上限 6000 字符，超限在 editor 内阻止并给一次非阻塞反馈。

### 8.2 V1 格式

整框级：font role `sans/serif/mono`、8–72、B/I/U、left/center/right、none/bullet/number list、
text color、transparent/semantic fill、opacity、单一 `http/https` link。局部选字改格式仍作用整框，tooltip
明确“应用到整个文本框”，不伪装富文本。

左右 resize 改换行宽度；上下 resize 改最小高度；不做旋转。Screen/overview/export 使用同一 style resolver。

## 9. Shape 纵向合同

### 9.1 Shape flyout

V1 首屏只放 5 个闭合形状：Rectangle、Rounded Rectangle、Oval、Diamond、Triangle。使用 5×1 或 3×2
图形网格，不使用平台 QMenu 文本长列表；每个 cell 有真实 SVG/Qt path preview 和 tooltip。

Line、Arrow、Elbow 不再混进 Shape flyout，它们属于独立 Connector 入口。Block Arrow 和 Divider 延后，
避免一个“Shape”按钮同时承担三类状态机。

### 9.2 创建与格式

- `S` 打开最近使用形状；单击画布创建默认 4×3，拖拽定尺寸；one-shot；
- Shift 保持 1:1 或初始比例；Alt/Option 从中心缩放；Cmd/Ctrl 暂停 snap；
- 双击 shape 或选中后输入，编辑内嵌 label；label 属于 shape，不创建 Text 子对象；
- fill：transparent + 8 个可访问 palette；stroke：ink + 8 palette；1/2/4/8 px；solid/dashed；
- rectangle/rounded rectangle 支持 0/8/16/24 px 语义 corner；其他形状无 corner control；
- selection toolbar 支持 switch type，保留 box/text/style/connector anchors。

## 10. Connector 纵向合同

### 10.1 创建

- `L` 激活最近使用的 Straight Line / Arrow / Elbow Arrow；flyout 可切换；
- 空白两击或 press-drag-release 创建自由 connector；
- 选中 card/sticky/text/shape 时显示 N/E/S/W 四个 18 px hit anchor；拖 anchor 创建；
- 落在目标轮廓 = 结构化 `AnchorTarget`；空白 = free endpoint；Cmd/Ctrl 暂停锚定；
- Shift 约束水平/垂直/45°；Esc 取消未完成 connector，不落 state/history。

### 10.2 编辑与目标生命周期

- endpoint handle 可重接；Elbow 只有一个用户 control，auto route 为确定性 H-V/V-H；
- style：none/arrow start/end、1/2/4/8 px、solid/dashed、8 palette；
- 目标 move/resize 后 endpoint 重新 resolve 到边界；目标删除/移到 Unplaced 时固化最后 Board point；
- target 丢失反馈每条 connector 一次；不做障碍避让、曲线、多折点、line jump；
- connector 可带一个整线 label，双击线创建；格式只含字号/颜色/水平文字，不支持列表。

## 11. Draw 纵向合同

### 11.1 Draw flyout

一个非模态 `QFrame` surface，顺序：Pen、Highlighter、Eraser、Lasso。Pen/Highlighter 各显示 3 个可编辑
preset chip（颜色 + 线宽真实 preview），不使用二级 QMenu。选中 preset 后 flyout 可关闭，工具保持 active。

Preset 是用户 UI 偏好，进入隔离 QSettings；不进入 Board、project、history 或 preview digest。

### 11.2 Pen / Highlighter

- pointer down → move → up 为一个 stroke、一条 undo；
- 收集 Board 坐标；先按 1.5 screen px 最小距离过滤，再确定性 RDP；
- 每 stroke ≤2048 persisted points，全板 ≤60,000；达到上限时结束当前 stroke 并反馈；
- Pen round cap/join、100% alpha；Highlighter 35% alpha，普通 source-over 可复现；
- pointer-to-draft paint 不等持久化 simplify；release 才一次 simplify/commit；
- draft 只 update dirty path bounds，不 repaint 整板、不重建 card QImage。

### 11.3 Eraser / Lasso

- Eraser V1 为整笔擦除：轨迹 hit corridor 碰到 stroke 就删除整条；不删除 card 或其他 author object；
- 一次 eraser session 删除多笔，合并为一条 undo；
- Lasso 对 card 和 author object 生效；闭合后按对象中心判断；
- Lasso selection 不持久化，不 dirty；完成后自动回 Select；
- precision eraser、stroke split、pressure/tilt 明确延后。

## 12. 数据、History、Fit、Export 合同

本文不重写 2026-08-15 已定的数据 DTO。以下仍为硬约束：

- `author_objects` 保持 additive schema 5；unknown kind 深度保真；
- `BoardItemKey` 使用 card composite identity 或 author object id；display text 不能做 key；
- 一次 create/edit/style/move/erase/lasso-delete = 一条 `BoardEditEntry`；
- author edit 只标 workspace dirty，不 recapture、不计算、不改变 preview digest；
- `BoardContentBounds(cards ∪ authors)` 是 Fit、elastic extent、overview、PNG 1×/2×、copy-board 的唯一边界；
- camera、active tool、selection、draft、flyout、editor widget、QSettings preset 不进项目；
- Presentation 只隐藏 chrome，不隐藏 author content；Template mode 不渲染/编辑 author，但数据保留；
- 旧项目没有 author_objects 时保存不产生无关 churn。

## 13. 性能合同

| 场景 | 预算 | 证据 |
|---|---:|---|
| 24 cards + 120 authors + 30k points，pan/zoom | 相对无 author 基线 p95 frame time 退化 ≤15% | Cocoa probe |
| 连续 Pen/Highlighter 30 s | pointer-to-draft-paint p95 ≤16.7 ms，max ≤33 ms | Cocoa event/paint timeline |
| Shape/Text/Sticky resize | p95 ≤16.7 ms，0 blank/double image | Cocoa gesture capture |
| selection toolbar 跟随 release | release 后 1 次定位；drag 中 0 次重排 | focused test + probe |
| Board switch/load 满载对象 | GUI thread stall p95 <50 ms，单次 <100 ms | deterministic fixture |
| Save/reopen 240 objects/60k points | 语义 round-trip，无 point/object 丢失 | state/session test |

自动化不得用 `processEvents()` 耗时冒充真实 input-to-present；offscreen 只证明事务和 paint 合同。

## 14. 可访问性与平台

- 所有 creator targets ≥40×40；handles visual 10 px、hit ≥18 px；
- tooltip = 中文名 + shortcut；accessibleName 不依赖 icon；
- keyboard focus 使用 selection blue 2 px ring，不用只变色；
- light 中普通文本 ≥4.5:1，大图标/边界 ≥3:1；作者 chrome 不做 dark 变体验收；
- Reduce Motion：flyout/toolbar 直接出现，不做 translate/fade；普通模式最多 120 ms opacity + 4 px translate；
- macOS 验证 CJK IME、trackpad pinch、Cmd；Windows 验证 Ctrl、触控笔普通 pointer、frozen Full/Lite；
- 平台 QMenu 不作为 Shape/Draw/Text 格式主容器，避免原生样式和 rounded shell 不一致。

## 15. Release 入口矩阵

| 波 | Release rail 可见 | 必须隐藏 |
|---|---|---|
| 当前 | Select、Sticky | Text、Shape、Connector、Draw |
| M1 chrome | Select、Sticky（迁入新 rail） | 其余 |
| M2 | + Text | Shape、Connector、Draw |
| M3 | + Shape | Connector、Draw |
| M4 | + Connector | Draw |
| M5 | + Draw/Pen/Highlighter | Eraser/Lasso 若未完成则 flyout 内隐藏 |
| M6 | Draw 完整含 Eraser/Lasso | 无 V1 dead affordance |

没有“Coming soon”灰按钮。隐藏不是临时视觉技巧，而是 release contract。

## 16. Definition of Done

必须同时满足：

1. 新 Miro-parity prototype 经用户确认，旧 prototype 明确不再是实现基线；
2. 左轨/Board/Global/Status/Nav/Selection Toolbar 分区符合 §4（rail 保留全部入口，左上保持现状），800×560 不裁切、不换行；
3. Text、Shape、Connector、Pen/Highlighter、Eraser/Lasso 各自完成 create→edit→undo/redo→save/reopen→
   overview/export 的纵向事务；
4. 入口矩阵无任何 visible+enabled dead action；
5. mixed selection、Esc、focus/IME、Board switch、Presentation/Overview/Template 没有双 owner 或残留 chrome；
6. Fit/overview/export 都包含负坐标 author-only content；
7. focused/boundary tests 通过，Cocoa 视觉/手势/性能证据通过；Windows frozen 明确通过或标记未验收；
8. `hints.py`、`quickref.py` 和 UltraView guide 只描述当波真实发布能力；
9. 未经上述证据，不能用“类已存在”“离屏绿测”“HTML 看起来对”宣布完成。
