# UltraView 弹性画布与非阻断操作体验优化计划

**状态：** Proposed / 未实施
**日期：** 2026-08-16
**执行基线：** `963f236e feat(ultraview): anchor inserts and sharpen previews`
**范围：** UltraView 自由网格的画布边界、平移/缩放、新卡初始尺寸、卡片动作区、删除与反馈，以及已选定的“钛蓝琥珀”视觉系统；不改变只读预览、零分析计算和 View 身份合同，也不把配色扩散到 TraceLab 其他工作区。

## 0. 决策摘要

本批采用“**有安全上限的弹性工作区**”，不再通过继续放大一张固定 1600px 画布来掩盖问题，也不立即重宿主为 `QGraphicsView`。

1. `1600×900 / 12 列` 继续作为 **1× 卡片尺寸和导出的基准标尺**，不再是屏幕上的可拖动边界。
2. 屏幕工作区按内容和当前视口动态扩展，四周始终保留平移余量；拖到边缘时先自动平移、再无感扩展。
3. 普通用户只在接近当前可扩展边缘时看到弱提示；只有达到极远的安全上限才出现红色硬边界和可执行说明。
4. 新 Board 初始缩放上限为 66%；“适应内容”只缩不放，最高 100%；大于 100% 只属于临时聚焦，最高仍可到 300%。
5. 新增 View 使用有效预览做一次“按原图比例、只缩不放”的初始尺寸修正，不要求用户逐张点击自动适应。
6. 卡片动作图标按真实几何重新居中，并增加“从当前 Board 移除”图标；不删除源 View，操作可撤销。
7. 所有拒绝都必须同时给出原因和下一步；不使用阻塞式 `QMessageBox`，不把重要反馈只写进状态栏。
8. 视觉方向正式选定 **“钛蓝琥珀”**：钛蓝承担专业、导航和主动作，琥珀只承担能量与关键强调，铜红承担危险状态；画布使用多层冷暖渐变，浮层使用暖白实体材质和分层阴影。此前“月白石蓝”仅保留为历史基线，不再是本批实现目标。视觉源样位于 `docs/analyzer/ui-prototypes/2026-08-16-ultraview-premium-color-directions.html?theme=titanium`。

这套方案接近 Miro 的核心体验：视口可以持续导航、对象直接操控、边缘拖动会带动画布、绝大多数时候看不到“墙”；但 UltraView 仍是有整数网格、24 张已放置卡上限、可确定导出和项目恢复的工程对比板，不扩成通用无限白板。

## 1. 当前证据与根因

### 1.1 三种坐标职责被混成一个边界

当前 `free_grid.screen_grid_metrics()` 固定使用 `BASE_BOARD_SIZE[0] == 1600` 和 12 列。这个值同时承担了：

- 卡片 1× 尺寸标尺；
- 屏幕 scroll host 的尺寸；
- `GridRect` 的合法范围；
- 碰撞规划器的搜索范围；
- 导出合成的宽度。

因此，在 2560 逻辑像素宽的 5K 窗口中点击 100% 后，1600px 画布反而比安全视口窄，水平滚动条最大值为 0；`pan_scroll()` 即使继续写滚动条也无法移动。卡片到达第 12 列时又立即进入 `OUT_OF_BOUNDS`，所以“墙”会落在窗口中部附近，而不是远处。

结论：**单纯把 1600 改成更大的固定数字只能把问题延后，并会改变卡片物理尺寸和导出；正确修复是拆开标尺、内容范围和交互工作区。**

### 1.2 当前 Fit 和新 Board 初始值会主动放大问题

- 空 Board 以整张 1600×1020 逻辑画布计算 fit；在大窗口可得到约 122%。
- 单卡“适应内容”测试明确要求命中 `ZOOM_MAX == 300%`。
- 100% 时标准 4×3 卡约为 512×288；两张卡已经占据较大视觉面积，而画布又没有外侧 pan slack。

这不是用户不会操作，而是产品把“看清单卡”和“浏览整板”混成了同一个 Fit 动作。

### 1.3 图标和新增卡初始比例是两个独立缺口

- 当前卡片 header 高 34px，动作条实际高 24px，但自身 `sizeHint` 为 28px；按钮中心比 header 中心低约 2px。
- 新增卡统一采用 `standard == 4×3`，只有用户主动点击“按原图比例”才调用 `fit_rect_for_aspect()`。
- Coordinator 已能从 `PreviewStore` 取得预览并执行只缩不放的比例匹配，缺的是“新增时的一次性策略”，不是新的图像算法。

### 1.4 删除已有模型能力，但缺少直接入口和安全感

卡片右键菜单、Delete 键和 `remove_ref_requested` 已能从 Board membership 中移除 ref，且不会删除源 View。当前动作条没有该入口，几何历史又会在 membership 改变时被清空，所以直接删除缺少 Miro 类产品应有的“立即操作 + 明确结果 + Ctrl/Cmd+Z 恢复”。

## 2. 本计划对历史合同的修订

| 历史合同 | 新合同 | 保留内容 |
|---|---|---|
| `2026-08-15-ultraview-fixed-canvas-and-autofit-spec.md`：1600/12 列既是显示画布也是边界 | 1600/12 列降为 canonical base frame；screen workspace 是动态 extent | 1× 卡片尺寸、整数 GridRect、screen/export 同一 cell pitch |
| `2026-08-15-ultraview-fit-zoom-and-dismiss-fixes-plan.md`：单卡 Fit 命中 300% | Board Fit 上限 100%，单卡不得因 Fit 被放大 | 25%–300% 总缩放范围和鼠标锚点缩放 |
| 当前越界测试：越过 12 列显示红墙并拒绝 | 越过 base frame 先扩展；只有越过 safety bounds 才拒绝 | 普通移动不缩小邻居，非法提交不写模型 |
| 新增统一 4×3，手动按比例 | 新增时一次性按预览比例只缩不放；手动按钮仍保留 | `fit_rect_for_aspect()` 离散网格算法 |
| `_GridHistory` 只保存几何，membership 改变即清空 | Board placement history 覆盖添加、移除、移动、缩放和整理 | 每 Board 独立、一次用户意图一个 undo entry |
| “月白石蓝”低饱和单色视觉基线 | “钛蓝琥珀”成为 UltraView 正式视觉合同，加入冷暖背景渐变、浮层层级和有限主按钮渐变 | 低干扰、只读预览、类别优先的 View 库结构、图表内容原色 |

历史文档保留为当时证据，不回写“已实施”；本计划实施时通过新测试替换已过时断言。

## 3. 产品交互合同

### 3.1 三层坐标模型

| 层 | 定义 | 是否持久化 | owner |
|---|---|---:|---|
| Base frame | 0–11 列的 1600px 1× 标尺；默认工作原点 | 否（常量） | Qt-free grid geometry |
| Content bounds | 所有 placed `GridRect` 的并集 | 只通过各 GridRect 间接持久化 | state / geometry |
| Workspace extent | `base frame ∪ content bounds ∪ viewport halo`，按 cell chunk 扩展 | 否；切板后可重算 | Page 的 workspace controller |

`GridRect.column/row` 改为允许有限的负数。旧项目的 0–11 列、0–47 行数据不需要迁移；payload 字段和单位不变。窗口像素、workspace extent、滚动条最大值、DPR 和 edge timer 都不得写入项目。

默认安全范围：

- column：`[-48, 60)`，即 base frame 左右各再留 48 列；
- row：`[-48, 96)`，即当前 48 行基线的上、下方各再留一个基线高度；
- span 仍使用现有最小/最大值，rect 的右/下边必须落在安全范围内；
- 24 张 placed / 200 membership 上限不变。

安全范围是防止坏 payload、失控拖动和无界搜索的工程护栏，不是日常布局建议。它不画永久边框。

### 3.2 弹性工作区与持续平移

1. 工作区至少包含 base frame 和 content bounds。
2. 四周 halo 取 `max(4 cells, 0.5 × 当前安全视口)`；所以空 Board、100% 和内容比窗口小时仍有可用滚动范围。
3. extent 按 4 列 / 4 行为一组扩展。当前 Board 会话内只扩不缩，避免删除卡片或窗口 resize 时 scroll origin 跳变；切板/重开后从内容、持久化 viewport 和 halo 重建。
4. `100%` 只改变 scale，并保持当前视口中心；它不得把滚动范围钳成 0，也不得把卡片吸回 base frame。
5. 手掌、Space+左拖、中键拖和 trackpad 平移继续通过现有 `ViewportGestureRouter`；不得再给 card/preview/overlay 各加一套 event forwarding。
6. 缩放、pan 和 extent 扩展只改变 viewport/runtime geometry，不调用 `_after_board_mutation()`，也不让工程进入内容脏状态。

### 3.3 边缘自动平移和边界反馈

拖动卡片、resize handle、marquee 或从 Library/未放置区拖入时：

- 指针进入 viewport 四周 72 logical px 的 activation band，启动 16ms tick 的自动平移；
- 速度按离边缘的距离从 4px/tick 线性提高到 22px/tick，对角方向可同时生效；
- 每次 tick 重新将全局指针映射到 board，ghost 与最终 `GridRect` 使用同一 resolver；
- 接近当前 extent 时先按 chunk 扩展，再继续 pan；用户不需要松手、缩小或点击额外按钮；
- release、Esc、drag leave、window deactivate、Board 切换和 widget destroyed 都必须停止 timer 并清 ghost。

反馈分两级：

| 场景 | 视觉 | 文案/动作 |
|---|---|---|
| 接近当前可扩展边缘 | 低饱和钛蓝渐隐带 + 稀疏点线；只在手势期间出现 | 首次停留 400ms 后显示“继续拖动可扩展画布”，不发重复 Toast |
| 达到 safety bounds | 铜红虚线硬边界 + 禁止标记；ghost 保持在最后合法位置 | Toast：“已到画布安全边界 · 整理卡片或新建 Board”；本次不提交 |

钛蓝提示不得像墙：无红底、无整块遮罩、无永久边框；铜红只表示真正无法继续的极端情况。

### 3.4 缩放、Fit 与初始视图

- 新建 Board 或旧项目中没有 viewport payload 的 Board：`zoom = min(0.66, fit(two-card working frame, safe viewport))`，永不因大屏上调到 66% 以上。
- 有合法持久化 viewport 的 Board：精确恢复，不擅自改成新默认值。
- “适应内容”：以 placed cards 的并集为目标，保留约 6% 安全边距，`zoom <= 1.0`；空 Board 适应 two-card working frame，不适应整张弹性 extent。
- “100%”：围绕当前视口中心恢复 1×，不回原点、不取消 halo。
- 双击卡片/聚焦层：允许临时放大到 300%，并保存进入前 viewport；Esc 精确返回。
- 加卡、删卡、预览到达、窗口 resize 不自动改变用户当前 viewport。自动改变的只有首次未初始化视图和用户显式触发 Fit/100%/聚焦。

### 3.5 新卡一次性按预览比例

1. 新 ref 有有效 preview 时，先以 `board.free_grid_default_size` 得到最大 rect，再调用现有 `fit_rect_for_aspect()`，用结果参与 anchor 解析和插入；所以 ghost、模型和最终 card 一致。
2. 无 preview 时立即按标准尺寸插入，绝不等待、弹窗或阻止；Coordinator 记录一个 session-only pending token：`board_id + ref + inserted_rect + layout_revision`。
3. 第一张有效 preview 到达时，只有 placement 仍等于 `inserted_rect` 才执行一次 shrink-only auto-fit；用户已手动 resize、套用尺寸 preset、移除或切换布局即取消 pending。
4. 仅移动卡片不取消比例修正；应用时使用卡片当前 origin 和原 span 上限。
5. 项目恢复、切 Board、sidecar hydrate 和已存在卡片不得再次自动调整。
6. 自动比例修正不另占一个撤销层级：如果它紧跟新增且期间没有其他编辑，合并到新增命令的 after snapshot；否则只更新尺寸但不吞掉用户下一次 Ctrl/Cmd+Z。

### 3.6 卡片动作区与直接移除

动作顺序统一为：`打开源 View → 临时聚焦 → 按原图比例 → 从当前 Board 移除 → 更多`。

- 移除图标复用 `remove_ref_requested`，不新建第二条 mutation 路径；模板和自由网格 card 均可用。
- tooltip / accessibleName 使用完整文案：`从当前 Board 移除（不删除源 View）`。
- 不弹确认框。完成后 Toast：`已从当前 Board 移除 · 源 View 保留 · Ctrl/Cmd+Z 撤销`。
- Undo 恢复原 membership、placed/tray 身份和原 `GridRect/slot`，不重新 first-fit。
- 动作条不再同时设置互相冲突的 24px fixed height 与 28px sizeHint；以 header 的实际 `contentsRect` 居中，所有 button center 与 header center 的纵向差不超过 1px。
- 窄卡片优先省略标题和状态文字，不隐藏移除入口；达到最窄 LOD 时，打开/聚焦/移除保留，低频动作进入“更多”。

### 3.7 非阻断反馈规则

| 用户意图 | 可接受结果 | 必须反馈 |
|---|---|---|
| 拖到普通 12 列外 | 扩展并继续 | 边缘弱提示，不报错 |
| 碰撞但存在合法布局 | ghost 同时显示所有受影响卡；一次提交 | `已重排 N 张 · Ctrl/Cmd+Z 撤销` |
| 碰撞且 safety bounds 内无合法布局 | 保持原布局 | 红 ghost + `附近没有可用空间 · 继续向空白处拖动或整理 Board` |
| 达到 24 张 placed 上限但 membership 未满 | ref 进入未放置区 | `画布已放置 24 张，已移到未放置区 · 打开` |
| membership 达 200 | 不添加 | `本 Board 已达 200 个 View · 新建 Board 或先移除` |
| 缺少 preview | 标准尺寸立即落位 | 不报错；“按原图比例”保持 disabled 并给 tooltip |
| 删除卡片 | 立即从当前 Board 移除 | 明确“不删除源 View”并支持 undo |
| 导出范围超过当前安全上限 | 不影响画布编辑 | 导出入口给出实际尺寸和“改用 1× / 整理卡片”动作，不用画布墙限制布局 |

### 3.8 “钛蓝琥珀”视觉合同

此节是实现合同，不是仅供参考的 moodboard。HTML 原型用于确认方向；生产实现必须走当前 QWidget/QPainter/QSS 路径，并以真实 macOS Cocoa 渲染为准。

#### 3.8.1 角色色与材质 token

| 角色 | 值 | 用途 |
|---|---|---|
| `canvas` / `canvasDeep` | `#F7F8F7` / `#E9EFF1` | 画布暖白基底与冷灰蓝纵深 |
| `canvasDot` / `canvasLine` | `rgba(44,82,93,0.17)` / `rgba(38,74,86,0.10)` | 细点阵与 5 倍节拍的粗网格；不得比卡片边框更抢眼 |
| `glowTeal` / `glowAmber` / `glowCopper` | `rgba(31,104,128,0.16)` / `rgba(238,151,58,0.13)` / `rgba(197,76,64,0.08)` | 左上钛蓝、右上琥珀、下方铜红的环境光 |
| `surface` / `surfaceSolid` / `surfaceSoft` / `surfaceTint` | `rgba(255,255,254,0.91)` / `#FFFEFD` / `#EDF2F2` / `#E9F1F3` | 浮层、卡片、hover/selected 洗色 |
| `ink` / `muted` / `quiet` | `#183039` / `#66787E` / `#87969A` | 主文字、普通图标、次要说明 |
| `line` / `lineStrong` | `rgba(50,86,97,0.23)` / `rgba(42,78,89,0.37)` | 常规与选中边界 |
| `brand` / `brandDeep` | `#24697C` / `#174F5E` | 钛蓝主色、pressed/focus 深色 |
| `amber` / `copper` | `#E58F32` / `#BE594C` | 主渐变终点、少量暖色强调 |
| `success` / `warning` / `danger` | `#198565` / `#DC861F` / `#C94F4A` | 语义状态；不得用琥珀冒充危险 |

颜色只通过角色 token 消费，不在 widget/QSS/paintEvent 中继续散落相近 literal。新的 UltraView token 独立于全局 `CONTROL_COLORS`，避免为了一个面板改变 TraceLab 其他控件。

#### 3.8.2 画布背景

背景从下到上固定为六层，并在 DPR/resize 后由缓存的 `QPixmap` 或等价静态 paint layer 重建；平移/拖动期间不得每帧重新生成渐变纹理：

1. `145°` 线性基底：`canvas → canvasDeep`，消除当前整块灰蒙感；
2. 以画布约 `(16%, 4%)` 为中心的钛蓝径向光晕；
3. 以 `(88%, 9%)` 为中心的琥珀径向光晕；
4. 以 `(64%, 104%)` 为中心的铜红径向光晕；
5. `23 logical px` 节拍的细点阵；
6. `115 logical px` 节拍的水平/垂直粗网格。

背景上缘可加入一条静态“信号地平线”作为 UltraView 的识别性细节：1px 虚线波形，钛蓝→琥珀→铜红渐变，最终合成 alpha 不超过 14%。生产版不做持续漂移动画，避免视觉干扰、无意义 repaint 和截图不确定性。图表预览、导出 PNG 与只读信号颜色不随背景重新着色。

#### 3.8.3 浮层、边框与阴影

- Board selector、View 库、左侧工具轨、右上工具条、缩放条、Toast/边界说明使用暖白浮层；普通卡片仍以边框区分，不给 24 张卡逐张加 `QGraphicsDropShadowEffect`。
- 浮层实体色使用 `#FFFEFD` 或预合成后的 `surface`，不依赖 Qt 不稳定的 `backdrop-filter`/实时模糊。圆角和两段式阴影沿用 `FloatingChrome` 的统一 QPainter 路径。
- 主浮层阴影目标：近层约 `0 4px 14px rgba(31,61,70,0.07)`，远层约 `0 22px 62px rgba(31,61,70,0.15)`；小浮层使用约 `0 2px 6px rgba(37,66,73,0.05)` + `0 11px 28px rgba(37,66,73,0.10)`。Qt 可用离屏 mask/分层绘制近似，但同层组件必须共用同一算法。
- View 库等主要浮层顶部增加 2–3px 钛蓝→琥珀→铜红强调线，不把整张面板填成渐变。
- 选中卡使用 `brand` 边框 + `surfaceTint` 微弱洗色；不得使用彩虹边框、发光描边或会压过信号图的高饱和大面积填充。
- QSS 同时出现 `border` 与 `border-radius` 时必须写完整 shorthand，继续受 `tests/ui_kit/test_qss_border_shorthand.py` 约束。

#### 3.8.4 按钮和交互状态

| 类型/状态 | 视觉合同 |
|---|---|
| 普通浮层 icon button | `surfaceSolid` + `line`；图标 `muted`；hover 为 `surfaceTint` + `brandDeep`；pressed 使用更深的预合成钛蓝洗色；focus-visible 为 2px `brand` 外环 |
| 持续 mode active | `qlineargradient` / `QLinearGradient(#3C8495 → #F0A44C)`，白色图标；hover/pressed 使用 `#2F7181`，且必须重绘为白色 `QIcon`（QSS `color` 不会重染既有图标）；只用于当前模式，不用于“面板已打开” |
| 一次性主动作 | 空板“打开 View 库”、新建 Board `+`、当前上下文中的 Fit/演示主动作可使用同一钛蓝→琥珀渐变；动作完成或不再是主建议后恢复普通按钮 |
| panel-open / selected | 左侧 ToolRail 和右上 GlobalIsland 的已打开主面板使用同一钛蓝→琥珀渐变 + 白色图标，明确“当前目的地”；Board selector 菜单仍为钛蓝描边 + `surfaceTint`，避免所有浮层触发器同时抢眼 |
| 危险动作 | `danger #C94F4A` 图标/边框和浅铜红 wash；卡片移除默认仍是普通图标，hover 后才显示 danger，避免动作区一直发红 |
| disabled | `quiet` 降低对比，不保留琥珀高光；仍提供原因 tooltip/accessible description |

渐变按钮必须使用同一共享 helper/palette，hover/pressed/checked 不得各自手写一套近似色。任何常驻工具条同时最多一个大面积渐变 active；其他按钮保持安静，以免回到“所有按钮一个颜色”的另一极端。

#### 3.8.5 View 库类别强调色

类别色只帮助扫描，不作为 View 或信号身份键：时域 `#3D79EF`、频谱 `#8B5FD5`、时频 `#00A998`、频响 `#E28735`、阶次 `#B75B4D`。组标题、左侧色点保留类别色；大面积分类底和边框使用更淡的独立 wash/line token，避免把 View 库染成一块块实色面板。行文字、`+` 按钮和选中态仍遵守钛蓝琥珀交互角色，不能让类别色接管所有控件。

## 4. 架构与 owner

| 文件/模块 | 本批职责 | 禁止事项 |
|---|---|---|
| `mf4_analyzer/ui/ultraview_state.py` | signed GridRect 合法化、安全上限、状态 mutator、Board placement snapshot | Qt import、窗口像素、直接刷新 Page |
| `ui/chart_stack/ultraview/free_grid.py` | cell pitch、content/base bounds、signed rect mapping、planner 搜索 | timer、widget、MainWindow import |
| 新建 `ui/chart_stack/ultraview/elastic_workspace.py` | Qt-free extent/halo/chunk/edge velocity 计算 | 持久化、QApplication event filter |
| `ui/chart_stack/ultraview/viewport.py` | 初始 66%、Fit<=100%、100% 保持中心的纯策略 | card mutation、第二份 gesture router |
| `ui/chart_stack/ultraview/widgets.py` | card action bar、ghost、edge hint 绘制；发布手势状态 | 写 Board state、调用 Coordinator |
| 新建 `mf4_analyzer/ui_kit/ultraview_style.py` | 单一“钛蓝琥珀”角色 token、预合成色和 QSS token；供 stylesheet 与 UltraView painter 共用 | 修改全局 `CONTROL_COLORS`、业务状态、Qt widget |
| `mf4_analyzer/ui_kit/stylesheet.py` / `style.qss` | 注入 UltraView scoped token；只命中 `ultraView*` objectName/property | 全局 `QToolButton`/`QWidget` 污染、重复 literal、CSS-only filter |
| `ui/chart_stack/ultraview/chrome.py` | 消费共享 palette，绘制画布层、浮层、主渐变和统一阴影 | 保留 `ULTRAVIEW_MOON` 等旧色值形成第二套主题 |
| `ui/chart_stack/ultraview/page.py` | workspace extent、scroll host、edge timer 生命周期、signal funnel | state 字段直写、分析计算 |
| `ui/chart_stack/ultraview/viewport_router.py` | 继续作为唯一 QApplication 级 viewport 手势路由 | 子控件再复制事件转发 |
| `ui/main_window/ultraview_coordinator.py` | add/remove/auto-aspect/undo 单一 mutation owner、Toast | Page 反向写模型、多条 refresh 路径 |
| `ui/chart_stack/ultraview/compositor.py` | signed content bounds 的 offset、base-frame 最小导出、超限预检 | 把 screen halo/viewport 空白导出 |

不采用 `QGraphicsView` 的原因：当前 card、Library、Focus、minimap、selection、projection batching 和 PreviewStore 均已围绕 QWidget/scroll host 收口；本问题通过 extent + halo + edge auto-pan 可以在现有 owner 内解决。只有 24 张卡真实 Cocoa 交互基准仍持续不达标，才另立重宿主 spec，不在本批双轨维护两套画布。

## 5. 实施任务

### Task 0 — 冻结新基线与写红测

**Files:** 修改 `tests/ui/test_ultraview_state.py`、`test_ultraview_free_grid.py`、`test_ultraview_viewport.py`、`test_ultraview_page.py`、`test_ultraview_export.py`。

- [ ] 记录 HEAD、dirty scope 和当前 5K 前台几何：safe viewport、1× canvas/card、scroll maxima、Fit zoom、action centers。
- [ ] 把“单卡 Fit 必须到 300%”改为“Board Fit 不超过 100%”；把“越过第 12 列必须红墙拒绝”改为“越过 base frame 可接受，越过 safety bounds 才拒绝”。
- [ ] 新增红测：100% 时四向 pan range 非零；新 Board 不高于 66%；signed rect round-trip；edge auto-pan；移除 undo；新增卡一次性比例；动作按钮中心差不超过 1px。
- [ ] 红测必须先证明现状失败；截图/探针写 `.state/ultraview-elastic-canvas-*/`，不提交生成物。

**退出条件：** 旧断言只因新产品合同被显式替换，不通过删测试掩盖其他回归。

### Task 1 — signed grid、弹性 bounds 与状态兼容

**Files:** 修改 `mf4_analyzer/ui/ultraview_state.py`、`ui/chart_stack/ultraview/free_grid.py`；新建 `elastic_workspace.py`；测试 state/free-grid。

- [ ] 引入 base frame、safety bounds、`GridBounds`/等价不可变 DTO；保留 `GRID_COLUMNS=12` 兼容别名，但不再把它作为 screen clamp。
- [ ] 更新合法化、anchor resolver、first-free、collision planner、organize、payload restore，使 signed origin 在 safety bounds 内确定性工作。
- [ ] `rect_to_pixels()` 支持负 cell；screen 调用额外应用 workspace offset，export 调用额外应用 content offset，不能偷偷把 rect 本身 rebase。
- [ ] 新 `elastic_workspace.py` 提供纯函数：`content_bounds`、`desired_extent`、`expand_extent`、`edge_pan_velocity`；同输入同输出。
- [ ] 覆盖旧 payload 不漂移、非法极值有 warning、负坐标保存/重开、24/200 上限、planner 不缩小邻居和 search cap。

**退出条件：** state/free-grid 仍 Qt-free；旧项目像素布局在 base frame 内完全一致。

### Task 2 — scroll host、初始 66% 与 Fit/100% 语义

**Files:** 修改 `viewport.py`、`page.py`、必要的 minimap projection；测试 viewport/page。

- [ ] Page 为每个 Board 持有 session-only extent high-water mark；set/reset/teardown 对称清理。
- [ ] host size 来自动态 extent，不再来自固定 1600 宽；用 workspace offset 投影 cards、selection、ghost、minimap 和 insert anchor。
- [ ] 实现 halo，确保空 Board/单卡/100% 下水平和垂直均有 pan slack；fit parking origin 不可吞掉 slack。
- [ ] 新 Board/default viewport 使用 `min(0.66, two-card fit)`；合法旧 viewport 精确恢复。
- [ ] Board Fit 使用 content bounds、6% margin、上限 100%；100% 保持中心；Focus 300% 与 Esc 返回语义不变。
- [ ] projection batch 内只重算一次 extent/minimap，不因每张 card geometry signal 反复 resize host。

**退出条件：** 66%、100%、Fit、窗口 resize、切 Board、保存/重开均不跳原点；viewport 改变不标记 Board 内容 mutation。

### Task 3 — 边缘自动平移、无感扩展与弱提示

**Files:** 修改 `page.py`、`widgets.py`、`ghost_overlay.py`（若当前 overlay owner 适合）；测试 page/viewport/router。

- [ ] Page 只拥有一个 16ms edge timer；widget 仅发布 active gesture/pointer，timer 不进入 card。
- [ ] move、resize、marquee、Library drop、tray drop 在 72px band 中自动 pan，ghost 每 tick 与最终 resolver 一致。
- [ ] extent 接近边缘时按 4 cell chunk 扩展；普通 base-frame crossing 不出现红墙、不发 warning Toast。
- [ ] 实现钛蓝 continuation hint 和 400ms 首次文案；同一次 gesture 只出现一次，切 Board 后可再次出现。
- [ ] safety bounds 才出现红墙、禁止标记和 actionable Toast；Esc/release/deactivate/destroy 全部停止 timer。
- [ ] 复用 `ViewportGestureRouter`，增加结构测试防止第二个 QApplication event filter 或 child forwarding。

**退出条件：** 用户可以不停手把卡拖过当前四边；没有“指针继续走、卡片撞墙却无说明”的状态。

### Task 4 — 新卡一次性 auto-aspect

**Files:** 修改 state/free-grid 的插入 resolver、`ultraview_coordinator.py`；测试 state/free-grid/mode integration/project session。

- [ ] 有 preview：在插入前计算 shrink-only span，并与 drop/center anchor 一次解析、一次 `_after_board_mutation()`。
- [ ] 无 preview：立即标准落位并登记 pending token；preview 首次可用时仅在 placement 未被手动 resize/preset 时应用。
- [ ] pending token 在 remove、layout switch、project reset、Board delete、coordinator shutdown 对称清除。
- [ ] restore/hydrate 不登记 pending；移动不取消，手动 resize/preset 取消。
- [ ] 自动修正与最近新增 history entry 合并，不产生一次“看不见的 Ctrl/Cmd+Z”。

**退出条件：** 新增宽图/竖图首屏比例合理，缺图不阻塞，既有卡和恢复工程绝不被后台重排。

### Task 5 — 动作条垂直对齐、移除图标与可访问性

**Files:** 修改 `widgets.py`、UltraView icons（如需）；测试 page/icons/visual harness。

- [ ] 消除 action bar 固定高度与 sizeHint 冲突，以 header `contentsRect` 做真正垂直居中。
- [ ] 增加 remove icon，复用既有 signal；tooltip、accessibleName 和键盘焦点顺序完整。
- [ ] 小卡 LOD 保留打开/聚焦/移除；“更多”继续提供同一动作，但不能成为唯一删除入口。
- [ ] 几何测试覆盖 66/100%、标准/宽/最窄卡、DPR1/2；渲染像素检查不能只断言 QSS token。
- [ ] 删除后 Toast 明确源 View 保留，selection/focus/context popover 不持有被删 card 的 Qt wrapper。

**退出条件：** 所有图标视觉中心误差 <=1px；移除一步可达、含义无歧义、无确认弹窗。

### Task 6 — Board placement undo 与导出语义

**Files:** 修改 `ultraview_state.py`、`ultraview_coordinator.py`、`compositor.py`；测试 export/state/mode integration/project session。

- [ ] 用 Qt-free `BoardPlacementSnapshot` 覆盖 placed slots、free-grid rects、unplaced 顺序及必要布局字段；不包含 name、viewport、preview 或 Qt 对象。
- [ ] 将 `_GridHistory` 收口为每 Board 的 placement edit history：add/remove/move/resize/organize 一次用户意图一个 entry，最多保留 100 条。
- [ ] Ctrl/Cmd+Z/redo 恢复直接删除的 exact membership/geometry；membership 改变不再清空全部几何历史。
- [ ] deferred auto-aspect 仅能合并当前顶层 add entry；检测到中间编辑时不得改写旧 history。
- [ ] compositor 以 content bounds + canonical padding 合成，base-frame 内仍至少 1600×既有高度；负坐标统一 offset，screen halo 不进入 PNG。
- [ ] 1×/2× 超过 `MAX_EXPORT_EDGE/MAX_EXPORT_PIXELS` 时保留 guard，但 UI 必须显示实际尺寸及“1×/整理”方案；不得反过来用导出上限限制日常拖动。

**退出条件：** remove→undo、move→undo、add→auto-aspect→undo 均确定；旧 base-frame 导出像素位置不变，signed card 不丢失。

### Task 7 — 反馈文案、帮助与反馈节流

**Files:** 修改 `mf4_analyzer/ui/hints.py`、`ui/quickref.py`、UltraView user guide，以及 feedback owner；测试 hints/quickref/help/page。

- [ ] 按 §3.7 建立 reason→visual→Toast 的单一映射，widget 不自行拼另一套中文错误。
- [ ] continuation hint、collision、safety cap、24/200 上限、remove/undo 均有稳定文案和 accessible description。
- [ ] feedback 节流：边缘弱提示每 gesture 一次；同类硬拒绝 1s 内不形成 Toast storm；最终合法提交仍可立即通知。
- [ ] quickref 说明：四向平移、边缘自动扩展、Fit<=100%、临时聚焦<=300%、删除不删源 View、Ctrl/Cmd+Z。
- [ ] 帮助内容删除“固定 12 列是可移动边界”和“单卡适应放大到 300%”的旧暗示；保留“12 列基准网格/导出标尺”。

**退出条件：** 每一种被拒绝的操作都能回答“为什么”和“接下来做什么”，无状态栏-only 反馈。

### Task 8 — 落地“钛蓝琥珀”视觉系统

**Files:** 新建 `mf4_analyzer/ui_kit/ultraview_style.py`；修改 `ui_kit/stylesheet.py`、`style.qss`、`ui/chart_stack/ultraview/chrome.py`、`widgets.py` 和实际消费颜色的 UltraView icon/minimap owner；测试 palette/QSS/icons/page/visual harness。

- [ ] 先用 token/selector/渲染红测冻结 §3.8：禁止旧 Moonstone literal 继续作为生产颜色，禁止 UltraView selector 泄漏到全局控件。
- [ ] 建立共享 role palette 和渐变 helper；`stylesheet.py` 注入 QSS token，QPainter widget 从同一 palette 取色，不复制 HTML CSS 或建立第二份颜色表。
- [ ] 画布实现六层静态背景和低 alpha 信号地平线缓存；resize/DPR/theme rebuild 可重建，pan/drag 不重复分配渐变 pixmap。
- [ ] `FloatingChrome` 统一浮层圆角、边框、近/远两层阴影；移除逐卡阴影和实时背景模糊的实现诱惑。
- [ ] 按 §3.8.4 收口 neutral/hover/pressed/focus/active/panel-open/danger/disabled；同一工具条最多一个大面积渐变 active。
- [ ] View 库类别色以展示 token 使用，不进入身份、缓存、选择或信号颜色。
- [ ] 截图覆盖空 Board、View 库展开、两张/24 张卡、卡片 hover/remove、边缘弱提示、硬边界、66%/100%、DPR1/2；自动比较关键区域的背景、圆角、边框和控件中心，不要求用户逐张肉眼找差异。

**退出条件：** 真实 UltraView 不再灰蒙、浮层有清楚层级、关键动作有冷暖强调但普通按钮保持克制；offscreen token/QSS green 不能替代 Cocoa 像素验收。

### Task 9 — 相关门禁与真实 macOS 验收

**Files:** 不新增产品行为；证据保存在 `.state/ultraview-elastic-canvas-*/`，除非用户另行要求耐久验收文档。

- [ ] 先跑 owner tests，再跑结构/帮助边界；按新的 `AGENTS.md` **不默认跑全套 pytest**。
- [ ] 运行 `git diff --check`，确认只包含本计划文件和实施所需 owner；不暂存无关 dirty changes。
- [ ] 用真实 macOS Cocoa 在 1280px 级窗口和 5K Retina 窗口验证以下矩阵，覆盖“钛蓝琥珀”的空板、View 库、卡片、浮层、hover/focus/disabled/danger 与 66%/100%；不能用 HTML 原型或 offscreen green 代替。

## 6. 验收矩阵

| 编号 | 场景 | 通过标准 |
|---|---|---|
| UX-01 | 新建空 Board | 初始 zoom <=66%；画布中心有两张标准卡的工作余量 |
| UX-02 | 加入宽图/竖图 | 首次显示已按预览比例只缩不放；无 preview 也立即出现 |
| UX-03 | 100% + 两张卡 | 卡片尺寸保持 1×，四向仍能 pan，不出现 scroll max=0 的锁死 |
| UX-04 | 拖过原第 12 列 | 卡片与 ghost 连续移动，工作区扩展，无红墙 |
| UX-05 | 拖到 viewport 四边 | 不松手即可自动 pan；速度连续，release 后立即停止 |
| UX-06 | 达到 safety bounds | 显示弱到强的边界升级、拒绝原因和下一步，模型不提交非法 rect |
| UX-07 | 碰撞 | 所有受影响卡 ghost 可见；接受时一条 undo，拒绝时有可行动文案 |
| UX-08 | Fit/100%/Focus | Fit<=100%；100% 保持中心；Focus 可到300%，Esc 精确返回 |
| UX-09 | 动作图标 | 纵向中心误差<=1px；remove 一步可达且 tooltip 说明“不删除源 View” |
| UX-10 | remove→undo→redo | 原 membership、slot/GridRect、tray 顺序精确恢复 |
| UX-11 | 保存/重开 | signed rect、viewport 精确恢复；runtime extent 从内容+halo 重建不漂移 |
| UX-12 | 导出 | base-frame 结果不变；负坐标卡被包含；超限提示实际尺寸与解决方案 |
| UX-13 | 24张卡持续操作 | 无明显 ghost/auto-pan 卡顿、无 Toast storm、无 timer/Qt wrapper 泄漏 |
| UX-14 | 钛蓝琥珀整体视觉 | 背景有冷暖纵深而不灰蒙；浮层、卡片和画布层级清楚；预览与信号原色不被污染 |
| UX-15 | 按钮与语义状态 | 主渐变仅落在当前 active/主动作；hover、focus、panel-open、disabled、danger 可区分，普通按钮不再全是同一淡色且不显杂乱 |

## 7. 相关测试命令

实施时按 owner 分段运行，避免一个异常 Qt 进程掩盖失败位置：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_viewport.py \
  tests/ui/test_ultraview_viewport_router.py -q
```

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_export.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_project_session.py -q
```

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_structure.py \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py \
  tests/test_help_content.py \
  tests/ui/test_ultraview_icons.py \
  tests/ui_kit/test_qss_palette_ratchet.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui_kit/test_qss_duplicate_selectors.py \
  tests/test_verify_ultraview_visuals.py -q

git diff --check
```

若其中任何进程 crash、timeout 或被中断，结果记为 `UNVERIFIED`；不从此前已完成的测试推断整段通过。Windows frozen acceptance 仍是发布门，本 UX 批次不以源码/offscreen 检查替代它。

## 8. 非目标与停止条件

- 不做协作、自由旋转、任意像素重叠、便签/箭头或第二套分析工作区。
- 不改变 PreviewStore residency、sidecar、digest、分析计算或 source View 状态。
- 不通过缩小卡片 1× 基准、放大预览位图或无限提高 render cap 解决导航问题。
- 不把 edge timer 或 workspace extent 放进 `UltraViewBoardState`。
- 不同时维护 QWidget 与 QGraphicsView 两套生产画布。
- 不把“钛蓝琥珀”升级成全局 TraceLab 换肤，不做运行时主题切换、暗色模式或新的主题设置项。
- 不给背景、信号地平线或按钮增加持续动画，不重新着色图表曲线、PreviewStore 位图或导出结果。
- 若实现 Task 1–3 后，24 卡真实 Cocoa 的 move/zoom/auto-pan 仍连续掉帧且 probe 指向 QWidget 数量/重绘，而非重复 projection 或 preview scale，停止继续微调，另立 QGraphicsView 重宿主 spec。

## 9. 完成定义

只有同时满足以下条件，计划才可标记 Implemented：

1. 12 列不再是日常屏幕拖动的隐藏墙，100% 下四向可导航；
2. 所有硬拒绝有可见原因和下一步，不使用阻塞弹窗；
3. 新卡自动得到合理长宽比，已有/恢复卡不被后台改尺寸；
4. 图标真实居中，remove 不删除源 View且可撤销；
5. signed layout、undo、export、项目恢复的相关自动化通过；
6. “钛蓝琥珀”的共享 token、背景渐变、浮层材质、按钮/类别强调和危险状态均按 §3.8 落地，没有污染全局控件或信号预览；
7. 真实 macOS 1280px 级窗口和 5K Retina 前台通过 UX-01–UX-15，截图和数值证据类别标注清楚；
8. 未运行的 Windows frozen/发布门明确写为未验证，不以本批结果代替。
