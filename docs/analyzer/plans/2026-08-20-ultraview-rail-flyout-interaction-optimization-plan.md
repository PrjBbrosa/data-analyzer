# UltraView Rail / 四工具 / 对象工具条 Miro 对齐整改 Plan

- 日期：2026-08-20
- 状态：**IMPLEMENTED — focused offscreen green; Cocoa / Windows still unverified**
- 本轮授权：按 W0–W5 落地 rail 节奏、唯一 primary fill、四工具 Miro 入口、对象工具条与 picker overlay
- 分析基线：`codex/ultraview-authoring-tools` / `ac5fef2bd2da1daa897b5614f147473e4ae90582`
- 用户目标：rail 拉开间距；Sticky / Text / Shapes / Draw 的入口、弹层和对象工具条向用户已提供的 Miro 参考图对齐；消除图标跳感、按钮堆积、巨大低质选项面板
- 视觉边界：保留 UltraView 左侧 rail、自由网格、左上既有主 chrome；不增加 dark mode；不引入 Miro AI Generate 等 TraceLab 不支持的功能

## 1. 结论先行

当前问题不是“再调几个 padding”能解决，而是三套信息层级同时失控：

1. **Rail 没有节奏。** 真实页面中组内间距为 `0 px`，divider 只提供 `1 px`；10 枚按钮连成一根密集图腾。
2. **Rail 没有唯一焦点。** Free Grid、打开的 Layout、作者工具 Draw 可以同时成为高强度填充态；截图中甚至出现三枚大色块。
3. **作者图标不是一个家族。** 新增四枚按钮直接混用 Font Awesome Solid 的便签、衬线 `A`、实心几何组合和粗铅笔；外框虽已稳定，实际 ink weight 仍忽大忽小。
4. **四个功能没有沿用 Miro 的信息架构。** Sticky 被横向铺成 4×4；Shapes 变成无文字的胶囊格；Draw 把工具、宽度、颜色同时摊成三行；Text 的选项又变成巨大二维按钮板。
5. **对象工具条把每个控件都做成一枚独立按钮。** 全局 `QToolButton` 边框/渐变泄漏进 toolbar，形成“药丸火车”，没有属性组和主次动作。
6. **二级弹层采用固定 260 px + 2/4 列稀疏网格。** Font、字号这类本应是紧凑列表的选择，被做成遮挡对象、遮挡工具条的白色大板。
7. **测试绿不等于 UI 合格。** 本轮 focused offscreen 为 `49 passed`，但现有测试还主动要求 Sticky flyout `>=260 px`，没有约束 rail 间距、Miro 布局、toolbar 分组或弹层遮挡。

因此，本轮整改方向是：

```text
Rail：稳定小按钮 + 明确间距 + 单一高强调态 + 同源线性图标
入口弹层：按 Miro 的纵向邻接结构，不再横向摊满画布
对象工具条：一块共享 shell + 内部无边框 cell + 分组分隔线
二级选项：内容驱动的锚定列表/色板，不再固定 260 px 二维散排
```

## 2. 七张现状图的问题识别

### 图 1 — 整条 rail

可见问题：

- Free Grid、Layout、Draw 同时使用大面积钛蓝—琥珀填充，主焦点不唯一；
- Free Grid 与 Layout 两枚 active tile 直接相接，作者四工具也没有组内呼吸；
- divider 几乎贴着相邻按钮和 badge，不能形成分组；
- Sticky 是独立浅蓝实心方块，Text 是粗衬线 `A`，Shapes 是一组实心几何，Draw 是粗铅笔，视觉语言不一致；
- 图标 nominal size 都是 20，但实际 ink bounds 和 stroke weight 不同，造成“图标大小一直跳”的感受；
- Unplaced `1` 与 Sync `2` 两个 badge 抢过按钮本身，且离分隔线过近；
- rail 同时承担 mode、panel、author tool、warning、count、sync 五类信息，却没有清晰的强调优先级。

判定：**P0 信息层级失败 + P1 图标体系失败。**

### 图 2 — Shapes 打开态

可见问题：

- 当前白色面板是大矩形，没有 Miro 式圆角、阴影和真实透明角；
- 连接线与形状被拆成“第一行 3 个小图标 + 第二行胶囊形状 token”，信息表达不一致；
- 所有选项无文字，折线、箭头、菱形、三角形的含义只能猜；
- 形状 cell 被绘制成胶囊轮廓，看起来像线型选择，不像对象类型；
- 5 个形状发生换行，留下大量无意义空白；
- rail 上 Shapes 在鼠标仍停留时显示纯青色，而不是用户要求的琥珀渐变。

判定：**P0 选项不可读。** 不能继续用 icon-only grid 修补，需恢复 Miro 的纵向“图标 + 名称 + 快捷键”目录。

### 图 3 — Draw 打开态

可见问题：

- 四个工具图标光学尺寸不同，Eraser/Lasso 有裁切或贴边感；
- 工具、线宽、8 色同时横向摊开，用户一次要扫描三条互不相同的轴；
- 线宽 preview 使用红/粉色，与当前选中的黑/蓝/红色状态没有一致映射；
- 8 个大色圆比工具本身更抢眼；
- 每个子选项都有独立边框，整个 panel 像控件样品板；
- Draw rail 的 active hover 被纯青色覆盖，琥珀端完全消失。

判定：**P0 操作模型过载。** 按 Miro 改为纵向 subrail，并用既有 3 个 preset 做渐进披露。

### 图 4 — Sticky 打开态

可见问题：

- 16 色被做成 4×4、48 px 以上的大块，面板横向侵入画布；
- Stack 被拉成约整块画布宽的按钮，与其低频连续放置职责不匹配；
- 面板无标题却占据巨大面积，视觉上像一个页面而不是邻接工具板；
- 白色矩形 backing 覆盖网格，圆角/阴影不可见；
- 与用户提供的 Miro 参考图“2 列纵向色板 + 底部动作”方向相反。

判定：**P0 尺寸和结构错误。** 改为 2×8 纵向色板；TraceLab 只保留 Stack，不引入 Generate。

### 图 5 — Sticky 字号弹层

可见问题：

- `auto / 12 / 14 / 18 / 24` 只有 5 项，却占据约半屏宽的大白板；
- 选项按稀疏两列摆放，阅读路径来回跳；
- 弹层没有贴住触发的字号控件，反而覆盖了工具条左半部分和对象内容；
- 大量空白没有提供任何信息；
- 背后的 selection toolbar 仍是一串独立 bordered buttons。

判定：**P0 弹层锚点与尺寸错误。** 字号改成单列紧凑菜单，直接贴在字号 cell 下方/上方。

### 图 6 — Shape 对象工具条

可见问题：

- 每个属性都是独立圆角方块，且相互紧贴，形成“按钮列车”；
- shape、fill、stroke、width、dash、corner/text、duplicate、lock、more 没有分组；
- 色块与线宽预览缺少清晰的语义边界，图标之间容易混淆；
- 复制、锁定、更多与核心样式拥有同样视觉重量；
- toolbar 几乎贴住 selection outline，且宽度由按钮外框累积膨胀；
- 左端控件/图标出现裁切和重叠感。

判定：**P0 工具条视觉语法错误。** 外层只保留一个 shell，内部 cell 默认无边框，按属性组加 divider。

### 图 7 — Text 工具条与字体弹层

可见问题：

- `Sans / Serif / Mono` 三项被排成稀疏的 2+1 大按钮板；
- 字体弹层从屏幕左上大面积展开，不跟随 font family cell；
- Text toolbar 继续把 I、U、align、list、color、link、duplicate、lock、more 全部做成独立药丸；
- font family、font size、格式、段落、颜色、对象动作没有分组；
- popup 覆盖工具条，用户看不到“自己从哪里打开、将改到哪里”。

判定：**P0 锚定弹层 + P0 工具条层级失败。** 使用 Miro 的单一横向 shell 和内容驱动列表。

## 3. 当前源码与 offscreen 证据

### 3.1 Rail 真实几何

`ToolRail` 当前根布局在 `chrome.py` 中是：

```text
contents margins = desktop (10,4,10,4) / compact (6,2,6,2)
root spacing     = 0
divider height   = 1
button           = desktop 40×40 / compact 36×36
```

真实 `UltraViewPage` 的 offscreen 测量：

| Stage | Rail | 组内按钮 gap | 两组 divider 带来的 gap |
|---|---:|---:|---:|
| 1280×720 | `64×412` | `0 px` | `1 px` |
| 800×560 | `52×368` | `0 px` | `1 px` |

所以用户看到“太密”不是主观误差，而是当前布局合同就是零间距。

当前状态还能同时成立：

```text
Free Grid  modeActive=true
Layout     panelOpen=true
Draw       active=true
```

这三类 selector 都使用高强度填充，rail 没有唯一视觉 owner。

### 3.2 “点击后不是琥珀渐变”的直接根因

普通 author active 已改为钛蓝—琥珀 `qlineargradient`，但 `[active=true]:hover` 和
`[active=true]:pressed` 又把背景替换成纯色 `UV_RAIL_ACTIVE_HOVER`。

点击后鼠标仍停在按钮上，用户真实看到的就是**纯青色 hover 态**，与图 2、图 3一致。整改不能只检查
idle active 的两个角像素，必须同时验证 active-hover 和 active-pressed 仍保留两个渐变 stop。

### 3.3 图标外框不再物理跳，但 optical ink 仍跳

Grok 当前改动已经让所有 rail button 外框在点击/repolish 前后保持相同；focused test 也证明
desktop `40×40 / iconSize 20`、compact `36×36 / iconSize 18` 不再塌缩。

未解决的是：

- `Sticky / Text / Shapes / Draw` 仍来自 `fa5s.sticky-note / fa5s.font / fa5s.shapes / fa5s.pen`；
- 四个 glyph 的填充比例、字重、斜角和视觉中心不同；
- Draw 还会随 pen/highlighter/eraser/lasso 更换 rail glyph，进一步造成“入口图标在变大变小”的感受；
- 现有测试只比较 `iconSize()`，没有测 pixmap 实际非透明 ink bounds。

### 3.4 四个入口弹层的真实尺寸/布局

| 弹层 | 当前 offscreen natural size | 当前结构 |
|---|---:|---|
| Sticky | `260×283` | 4×4 的 16 枚 `48×48` swatch + `236×35` Stack |
| Shapes | `248×112` | 3 枚 connector 小格 + 4+1 的 shape grid；渲染 child 高度仅约 21 px |
| Draw | `258×110` | 4 工具横排 + 3 宽度横排 + 8 色横排 |
| Text | 无入口弹层 | 直接进入创建；主要问题在选中后的 toolbar / picker |

共同容器虽然有自绘 rounded path，但 scroll viewport/content child 没有形成可靠的透明角和统一阴影；用户
截图中看到的是白色矩形 backing。只设置 `border-radius` 不足以证明真实角像素正确。

### 3.5 格式 picker 的真实尺寸

`FormatChoiceFlyout.min_width = 260`，`present_labels()` 对 `<=6` 项使用 2 列，对更多项使用 4 列。

| Picker | 当前 offscreen | 布局 |
|---|---:|---|
| Font family | `260×100` | Sans / Serif 两列，Mono 落到第二行 |
| Sticky size | `260×141` | auto/12/14/18/24 稀疏两列 |
| Text size | `260×141` | 8…72 四列换行 |

它还是 `Qt.Popup` 顶层窗口，从 toolbar button 的 global position 打开；这解释了截图里的大白板、遮挡和
锚点漂移。格式 picker 应走 CanvasHost 内共享 overlay/safe-rect，不再单独制造 native popup backing。

### 3.6 Toolbar 的“药丸火车”根因

`_FormatButton` 没有设置 UltraView toolbar 专用 `role`，因此继承全局 `QToolButton`：

```text
padding: 4px 10px
border: 1px solid ...
border-radius: 8px
background: vertical gradient
```

`SelectionToolbar` 自身又画了一块圆角 surface，于是出现“一个大 shell 里面再塞十几枚独立 shell”的双重
chrome。当前 `_body_layout.spacing=2` 也不足以形成语义分组。

### 3.7 当前自动测试结论

本轮命令：

```text
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_author_chrome.py \
  tests/ui/test_ultraview_selection_toolbar_contract.py \
  tests/ui/test_ultraview_sticky_slice.py -q
```

结果：

```text
49 passed in 5.36s
```

这是行为/结构绿，不是视觉验收。现有测试仍包含：

- Sticky first swatch `>=48`；
- Sticky flyout `>=260`；
- 只验证按钮不相交，不要求组内最小 gap；
- 只验证 active idle 渐变，不验证 active:hover；
- 只验证 option 存在，不验证单列/纵向 Miro 结构；
- 不验证 toolbar cell 无边框、分组和 popup 遮挡。

## 4. 目标 Rail 规范

### 4.1 可见 inventory

release rail 继续不显示 Select/鼠标按钮：

```text
Sticky  Text  Shapes & Connectors  Draw
  N      T             S            P
```

保留内部 Select、`V`、`Esc`、框选、对象 hit routing、移动和 resize。不要把“去掉可见鼠标按钮”误实现为
删除选择能力。

### 4.2 间距与分组（logical px）

| Token | Desktop | Compact |
|---|---:|---:|
| button outer | `40×40` | `36×36` |
| icon canvas | `20×20` | `18×18` |
| 同组 button gap | `6` | `4` |
| divider 上/下 clear space | `10 / 10` | `8 / 8` |
| divider | `1 px`，左右各 inset `8` | 同左 |
| rail 内边距 | `10, 8, 10, 8` | `6, 4, 6, 4` |

按钮尺寸不再扩大；用户需要的是**拉开节奏**，不是把图标再做大。

目标结构：

```text
[Library]
   6
[Free Grid]
   6
[Layout]
   6
[Filter]
  10
────────
  10
[Sticky]
   6
[Text]
   6
[Shapes]
   6
[Draw]
  10
────────
  10
[Unplaced]
   6
[Sync]
```

800×560 compact 仍应完整容纳，不允许通过重新压回 `0 px` 达成 fit；若未来新增 rail 功能，先进入 overflow，
不能继续无上限向竖列塞按钮。

### 4.3 单一高强调态

一条 rail 同一时刻只允许一枚大面积渐变 tile。优先级：

```text
author active > panel open > empty-board CTA > persistent mode
```

规则：

- 激活作者工具时，打开主 panel 应先退出作者工具到内部 Select；
- 打开作者 flyout 不再额外创造第二枚 panelOpen tile；
- Free Grid 是持续模式；当更高优先级目标存在时，只显示安静的 2 px teal side marker/outline，不再填满渐变；
- Filter 的持续条件、warning dot 和 count badge 是状态/通知，不是第二个 primary active；
- `active / active:hover / active:pressed` 三态都必须保留钛蓝→琥珀两个 stop；hover 只调整 border 或叠加轻微 wash，不能替换为纯青色；
- selection outline/handle 继续使用 Miro selection blue，不改成琥珀。

### 4.4 图标家族

新增四枚作者图标改成同源的 20 px outline set（SVG 或现有 painter icon helper），不再直接混用 Font
Awesome Solid：

| 功能 | 目标 glyph | 约束 |
|---|---|---|
| Sticky | 右下折角的 outline note | 不画实心方块 |
| Text | 简洁 `T` / type glyph | 不用衬线大写 `A` |
| Shapes | outline square + circle + triangle | 三个轮廓同一 stroke，不做实心团块 |
| Draw | 斜置 outline pen | 不用粗实心铅笔 |

统一：round cap/join、stroke 约 `1.75–2.0`、视觉 ink box 目标 `16–18 px`、视觉中心误差不超过 1 px。

Draw rail glyph 固定为 canonical pen，不再跟随 eraser/lasso 改入口图标；当前子工具在 flyout 和 cursor 中反馈。

新增测试要渲染图标 pixmap，比较非透明 ink bounds，而不是继续只比 `iconSize()==20`。

### 4.5 Badge

- badge 最大高度 `18`，右上角与按钮至少留 `2 px`，不能压到下一枚按钮/divider；
- 只对 count 使用数字 badge；warning 使用 8 px dot；active 不再兼做 attention；
- 相邻 Unplaced/Sync 同时有数字时，仍须有清晰 6/4 px 按钮 gap 和 divider clear space；
- badge 不参与按钮 layout，不改变按钮 outer rect。

## 5. 四个功能的 Miro 对齐方案

### 5.1 Sticky — 2×8 纵向色板

目标：直接采用用户 Miro 参考图的窄纵向 palette，而不是当前 4×4 大板。

```text
┌──────────────┐
│ [■]    [■]   │
│ [■]    [■]   │
│ [■]    [■]   │
│ [■]    [■]   │
│ [■]    [■]   │
│ [■]    [■]   │
│ [■]    [■]   │
│ [■]    [■]   │
│──────────────│
│  ▱  Stack    │
└──────────────┘
```

定量规范：

- 2 列 × 8 行，swatch `48×48`，gap `8`，panel padding `12`；
- natural width 目标约 `128–132`，禁止固定为 `260`；
- Stack 高 `38`，宽度只跟 palette content，不再拉到 236+；
- swatch border 画在内部，checked ring 不改变 outer size；
- 普通颜色 click：选色、关闭 palette、进入 one-shot Sticky；
- Stack：进入连续放置；
- 不加入 Miro `Generate`，因为 TraceLab 没有对应能力；
- 1280×720 和 800×560 都应完整显示；空间不足时整体 Y clamp，不先改回 4×4；
- rounded outer shell、scroll viewport、content child 的四角像素必须透明，不能再出现白色矩形 backing。

### 5.2 Shapes & Connectors — Miro 纵向目录

当前 icon grid 无文字、难分辨，不再保留。目标采用 Miro 的单列 catalog：

```text
┌────────────────────────┐
│  ───   直线          L │
│  ──▶   箭头            │
│  └─▶   折线箭头        │
│────────────────────────│
│  □     矩形          R │
│  ▢     圆角矩形        │
│  ○     椭圆          O │
│  ◇     菱形            │
│  △     三角形          │
└────────────────────────┘
```

定量规范：

- panel natural width `220–240`；
- row 高 `44`，左右 padding `10/12`，icon box `24`，label 与 icon gap `10`；
- shortcut 右对齐、使用 quiet text；
- connector 3 项与 closed shape 5 项用 1 px divider + 8 px group space；
- row 默认无独立边框；hover 使用轻 surface wash；checked 使用 selection-blue wash/left mark；
- 不显示 unsupported Block Arrow、Divider、More shapes、Diagram；
- 选一项即关闭并进入 one-shot create；`L` 仍直达最近 connector；
- persisted Connector/Shape 类型和 schema 不变；只替换入口 UI。

### 5.3 Draw — Miro 纵向 subrail + 3 个 preset

当前“4 工具 + 3 线宽 + 8 色”三行矩阵全部摊开，改成 Miro 的窄纵向 subrail：

```text
┌──────┐
│ Pen  │  tooltip/accessibility 提供文字
│ Hi   │
│ Era  │
│ Las  │
│──────│
│  ●   │  preset 1：真实 color + width
│  ●   │  preset 2
│  ●   │  preset 3
└──────┘
```

定量规范：

- panel width `64–72`；padding `8`；
- 4 个 tool cell 为 `40×40`，vertical gap `4`；
- divider 上下各 `8`；
- 底部直接映射现有 `DEFAULT_DRAW_PRESETS` 的 3 个 preset，不再永远展示 8 色整排；
- preset circle/cell `32–36`，同时用颜色和真实 stroke preview 表达；
- 单击 preset 即切换；再次点击当前 preset 或明确 edit affordance，打开右侧紧凑 preset editor；
- preset editor 只显示 3 个 width + 2×4 色板，锚定在当前 preset 右侧，一次只开一个；
- 在 tool/preset/editor 内切换时保持 Draw 主 panel 打开；点击 canvas 或 Esc 才关闭；
- Pen/Highlighter/Eraser 维持连续工具；Lasso 完成后回内部 Select；
- active subtool 用 selection-blue wash/ring，不在 panel 内复制 rail 的钛蓝—琥珀渐变。

### 5.4 Text — 入口直接创建；选中后使用 Miro 横向工具条

Text 入口继续不弹空 flyout：点 `T` → 点击/拖拽创建 → 进入编辑。Miro 对齐发生在对象被选择后的属性条。

目标 desktop 结构：

```text
┌──────────────────────────────────────────────────────────────────────┐
│ T │ Font family │ Size ↕ │ B I U │ Align List │ Text Fill Link │ ⧉ 🔒 ⋯ │
└──────────────────────────────────────────────────────────────────────┘
```

规则：

- 外层只有一块 48 px 高共享 shell；内部 cell 默认透明、无边框、无独立背景；
- toolbar horizontal padding `4`，icon cell `36×36`，icon `18–20`；
- font family 为 `104–120` 宽的文本 cell；font size 为 `56–64` 宽；
- 组内 gap `0–2`，属性组之间使用 `1×24` divider + 两侧 `4–6` clear space；
- hover 只给当前 cell 一块轻圆角 wash；checked 使用 selection-blue wash；
- duplicate/lock/more 属于对象动作组，不能与字体属性混在一起；
- compact `<900` 时保留 Font / Size / Bold / Align / Text color / More，其余按固定优先级进入 `⋯`；
- 不允许 toolbar 换行；在对象上方/下方择优后，X/Y 两轴 clamp 到 CanvasHost safe rect。

## 6. Sticky / Shape / Text 对象工具条统一规范

### 6.1 一个 shell，不是一串 shell

统一移除 selection toolbar child 对全局 `QToolButton` chrome 的继承，新增 scope-bound role/property，例如
`role="selectionToolbarCell"`：

| State | Cell 视觉 |
|---|---|
| idle | transparent，border transparent |
| hover | light wash，8 px radius |
| pressed | 稍深 wash |
| checked | selection-blue wash / blue ink |
| focus | 2 px 内描边，不改 geometry |
| disabled | transparent + quiet ink |

外层 toolbar 才拥有：白色/暖白 surface、1 px edge、12–14 px radius、轻阴影。

### 6.2 各对象工具条分组

Sticky：

```text
Shape  Fill | Font size | Duplicate  Lock  More
```

Shape：

```text
Shape  Fill  Stroke  Width  Dash  Corner | Text | Duplicate  Lock  More
```

Connector：

```text
Route  Start  End | Color  Width  Dash | Label | Duplicate  Lock  More
```

Stroke：

```text
Tool | Preset/Color  Width | Duplicate  Lock  More
```

Text：见 5.4。

Card / card_author 继续不显示作者 toolbar，只使用既有 Card hover/focus action bar。

### 6.3 与 selection bounds 的距离

- toolbar 与对象 selection bounds 间距 `8`；
- 首选 above；不够则 below；仍不够才在 safe rect 内侧夹紧；
- toolbar 不得覆盖 resize handle；
- 格式 picker 打开后，toolbar 不移动；
- 对象部分出 viewport 时，toolbar 自身仍必须完整可见。

## 7. 二级选项整改

### 7.1 禁止固定 260 px 的通用 picker

删除 `FormatChoiceFlyout` 的统一 `min_width=260`。按数据类型选择 renderer：

| 类型 | 目标布局 | 目标宽度 |
|---|---|---:|
| Font family | 单列 3 行，当前项 check | `160–180` |
| Sticky font size | 单列 5 行 | `96–112` |
| Text font size | 单列 9 行，可滚但正常 720 高不滚 | `96–112` |
| Width / Dash / Route / Align / List | 单列紧凑选项 | `120–160` |
| Palette | 4 列小 swatch；只显示颜色，不加大按钮 | content-driven |
| Shape type | 复用 Shapes 纵向 catalog/同一 row 语言 | `220–240` |

单列 row 高 `36–40`，左右 padding `10/12`；当前项使用 check/blue text，而不是把整枚大按钮描粗。

### 7.2 锚点和生命周期

- picker 与触发 cell 间距 `4–6`；
- 默认与 cell 左边对齐，右侧越界时对齐右边；
- 下方不足时翻到 toolbar 上方；
- 全程 clamp 在 CanvasHost safe rect；
- 使用 CanvasHost sibling overlay / 统一 rounded popup shell，不再使用独立 native `Qt.Popup` 大白板；
- 同时只允许一个 format picker；打开新的先关闭旧的；
- click option：应用并关闭；Esc：只关 picker，toolbar 和 selection 保留；
- click canvas：先关 picker，再按现有选择合同处理；
- 所有 scroll viewport/content child 首帧透明，不能覆盖 rounded corner。

## 8. 视觉 token 与品牌使用边界

钛蓝—琥珀渐变只用于 rail 的唯一 primary active，不扩散到每一枚小控件：

| Role | 建议值/方向 |
|---|---|
| Rail active | 既有 `UV_RAIL_ACTIVE_START → UV_RAIL_ACTIVE_END` |
| Rail active hover | 仍为双 stop，只轻微加深，不改纯色 |
| Selection / toolbar checked | Miro selection blue `#4262FF` + light wash |
| Flyout/toolbar surface | `#FFFFFF` / 既有 warm solid surface |
| Ink | `#183039` |
| Muted | 既有 `UV_MUTED`，但确保 4.5:1 文字对比 |
| Edge | 低对比 `UV_LINE` |
| Hover wash | 安静中性色或浅 selection wash |

这是 frontend-design 的核心收敛：每个 surface 只保留一个 signature treatment。若 rail、flyout、toolbar、
swatch 全部复制渐变，层级会再次失控。

## 9. 实施 Waves

### W0 — 把七张截图变成失败合同

先补/改测试，改前应能暴露当前视觉结构：

1. `test_release_rail_has_minimum_intragroup_gaps_and_divider_clear_space`
2. `test_only_one_rail_button_uses_primary_filled_state`
3. `test_author_active_hover_and_pressed_keep_two_gradient_stops`
4. `test_author_icons_share_rendered_ink_bounds_and_draw_icon_is_stable_across_subtools`
5. `test_sticky_palette_is_two_columns_eight_rows_and_width_is_bounded`
6. `test_shapes_catalog_is_one_column_with_visible_labels_and_shortcuts`
7. `test_draw_popover_is_vertical_and_exposes_three_presets_not_an_always_visible_color_matrix`
8. `test_selection_toolbar_cells_do_not_inherit_global_button_border_or_gradient`
9. `test_selection_toolbar_has_expected_group_dividers`
10. `test_font_and_size_pickers_are_single_column_content_driven_surfaces`
11. `test_format_picker_is_anchored_to_trigger_and_inside_safe_rect`
12. `test_flyout_corner_pixels_are_transparent_without_rectangular_backing`

同时替换/删除会固化错误的旧断言：

- Sticky flyout `>=260`；
- Sticky 必须 4 列；
- Shapes 只验证 8 个 button 存在；
- Draw 必须同时可见 8 色；
- toolbar 只验证 height=48 / forbidden word，而不验证分组和 cell chrome。

### W1 — Rail rhythm / state / icons

Owner：`ui/chart_stack/ultraview/chrome.py` + UltraView scope QSS/icon helpers。

- 增加 desktop/compact gap 与 divider clear space；
- 建立唯一 primary active 投影；
- 修复 active hover/pressed 的渐变；
- 四枚作者入口换成同源 outline icon；
- Draw rail glyph 不再跟子工具变化；
- 整理 badge geometry；
- 不改 rail 其他 panel 的业务功能。

W1 出口：rail 不密、不跳、同时最多一枚大色块；1280×720 / 800×560 都完整。

### W2 — 共享 flyout / picker shell

Owner：`author_chrome.py` + `CanvasHost` overlay seam + UltraView scope QSS。

- 统一 natural-size 计算；
- 统一真实透明角、edge、shadow；
- 统一 anchor flip/clamp；
- 格式 picker 从顶层 `Qt.Popup` 迁入 CanvasHost overlay；
- 同时只开一个入口 flyout / picker；
- 不复制第二套 screen-level popup owner。

W2 出口：所有面板都有可靠圆角，首帧无 backing rectangle，键盘焦点不被异常抢走。

### W3 — 四功能逐个改造

按风险与可见收益顺序：

1. Shapes 纵向目录；
2. Sticky 2×8 palette；
3. Draw 纵向 subrail + 3 preset；
4. Text 入口保持直达，改 selection toolbar 和 picker。

每完成一个功能就跑自己的 focused tests 和 offscreen artifact，不等四个一起堆完再找问题。

### W4 — Selection toolbar 分组

Owner：`author_selection.py`（control order/capabilities）、`author_chrome.py`（presentation）、`page.py`
（anchor/lifecycle）。

- 只调整 UI control 分组/overflow，不改变格式 payload；
- 外层一个 shell，child 使用专用 cell role；
- 插入语义 divider；
- Sticky / Text / Shape / Connector / Stroke 分别验收；
- compact overflow 使用固定优先级，禁止随宽度随机跳项。

### W5 — 文档和 live gate

- 更新 `ui/hints.py`、`ui/quickref.py`、UltraView guide 中可见入口与 `V/Esc`；
- 重建当前截图 evidence，旧 verify PNG/NOTES 只能标 historical；
- 先 focused tests，再做 offscreen artifact matrix，最后做真实 Cocoa 前台；
- 不把 offscreen 观感当成 Cocoa 完成；Windows frozen 未跑时明确 `WINDOWS UNVERIFIED`。

## 10. 验证矩阵

### 10.1 Focused tests

```text
tests/ui/test_ultraview_author_chrome.py
tests/ui/test_ultraview_selection_toolbar_contract.py
tests/ui/test_ultraview_board_hit_routing.py
tests/ui/test_ultraview_author_integration.py
tests/ui/test_ultraview_sticky_slice.py
tests/ui/test_ultraview_author_text_slice.py
tests/ui/test_ultraview_author_shape_slice.py
tests/ui/test_ultraview_author_connector_slice.py
tests/ui/test_ultraview_author_draw_slice.py
tests/ui_kit/test_ultraview_style.py
tests/ui_kit/test_qss_border_shorthand.py
tests/ui/test_no_lambda_signal_connections.py
```

本整改不要求 routine pre-change full suite。稳定集成里程碑若需要 full gate，只由一个 owner 对同一稳定
source snapshot 执行。

### 10.2 Offscreen artifact matrix

1280×720 与 800×560 各生成：

1. rail idle；
2. Free Grid persistent + Sticky active；
3. Layout panel open；
4. Sticky 2×8；
5. Shapes 纵向 8 行；
6. Draw Pen / Highlighter / Eraser / Lasso 四个 subtool；
7. Text toolbar + font picker；
8. Sticky toolbar + size picker；
9. Shape toolbar + fill/width picker；
10. selection toolbar 在 top/right/bottom/left 边缘；
11. Unplaced/Sync badges 同时存在；
12. active hover/pressed 的 rail 渐变。

自动断言：

- 组内 gap、divider clear space 达标；
- 所有 rail button rect 在 click/hover/active/popup/subtool 切换前后不变；
- 同时至多一个 primary filled rail tile；
- active、active:hover、active:pressed 的左上/右下采样不相同；
- 四作者 glyph actual ink bounds 差不超过 2 px；
- Sticky 恰为 2×8；Shapes 8 行不换行；Draw 主 panel 不显示横向 8 色长条；
- picker 与 trigger gap 为 4–6，且不与 toolbar/object 发生大面积遮挡；
- toolbar/flyout 全部落在 safe rect；
- rounded shell 四个角像素透明，内部 child 不覆盖圆角。

### 10.3 Cocoa 前台逐功能门

在 `./.venv/bin/python -m mf4_analyzer.app` 的真实 TraceLab 中验证：

- rail 从上到下扫视，图标家族统一、间距不挤；
- click 后鼠标不移开，仍能看到钛蓝—琥珀，不变纯青；
- Free Grid / Layout / author tool 不再同时出现三枚 primary fill；
- Sticky 从 rail 到选色/Stack/创建；
- Text 从创建、选中、Font/Size/格式到 Esc；
- Shapes 从目录选择到创建、选中后改 fill/stroke；
- Draw 从 tool/preset 到连续绘制、Eraser/Lasso、Esc/V；
- toolbar 在四边不挡 handle，不越界；
- popup 不抢异常键盘焦点，第一帧没有白色矩形闪烁；
- Card 仍走既有 hover/focus action bar，不被 author toolbar 覆盖。

## 11. 文件触点与禁止扩张

| 文件 | 计划内 | 计划外 |
|---|---|---|
| `chrome.py` | rail spacing/state/icon/badge | 不改 Board/Library/Layout 的业务 payload |
| `author_chrome.py` | 四工具 UI、toolbar presentation、picker shell | 不改 author DTO/schema/history |
| `author_selection.py` | control order、group metadata、compact priority | 不新增第二个 selection owner |
| `page.py` | overlay lifecycle、anchor/clamp、状态互斥 | 不新增 MainWindow 跨模块状态 |
| `style.qss` | UltraView scope cell/rail/flyout states | 不重排全局 QSS，不影响其他模块按钮 |
| `ui/hints.py` / `ui/quickref.py` / guide | 可见入口、V/Esc、Draw preset 说明 | 不承诺未实现能力 |
| focused tests/verify | 几何、像素、布局、artifact | 不用 token 存在代替真实渲染 |

明确不改：Top-left 既有主 chrome、Card preview/capture/Fit、Free Grid 拖拽/resize 算法、author data
schema、项目持久化格式、分析计算、dark mode、AI Generate。

## 12. Definition of Done

必须同时满足：

1. release rail 无可见 Select/鼠标按钮，但内部 Select、`V/Esc`、框选和对象操作完整；
2. rail desktop/compact 有明确组内 gap 和 divider clear space，不再 `0/1 px` 堆叠；
3. 同时最多一枚 primary gradient；active hover/pressed 仍有清晰琥珀端；
4. Sticky/Text/Shapes/Draw 使用同源 outline icon，实际 ink bounds 接近，Draw 子工具不再改变入口 glyph；
5. Sticky 为 2×8 窄色板；Shapes 为有名称/快捷键的纵向目录；Draw 为纵向 subrail + 3 preset；Text 入口直达；
6. 所有对象工具条为“一块 shell + 无边框 cell + 语义 divider”，不再是一串药丸；
7. Font/Size 等 picker 内容驱动、单列锚定，不再固定 260 px，不遮住半块画布；
8. flyout/picker 无白色矩形 backing，圆角 corner pixels 和第一帧正确；
9. toolbar/picker 在 1280×720、800×560 和四边对象场景中全部位于 safe rect；
10. focused tests、offscreen artifact matrix、真实 Cocoa 四功能逐项均通过；Windows 未跑则明确标记；
11. 与本任务无关的 `ssh-keygen`、`ssh-keygen.pub` 和其他工作树改动不进入 patch/commit。

## 13. Supersedes

本文取代旧版同名 Plan 中以下错误方向：

- Sticky 4×4 大色板；
- Shapes icon-only 4 列网格；
- Draw 工具/宽度/8 色三行全部展开；
- “所有 mode/panel/author active 都同时使用同一大面积渐变”；
- `FormatChoiceFlyout` 统一 260 px 与 2/4 列 label grid；
- 只靠 offscreen test green 即认为 UI 完成。

其余已经确定的 author 数据、画布 hit routing、Card hover、内部 Select 和项目持久化合同继续有效。
