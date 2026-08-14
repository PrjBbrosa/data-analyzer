# UltraView 画布交互分析：对标 Miro 类 canvas 工具

日期：2026-08-14 · 作者：Claude · 性质：**纯分析，不含实施**（用户指令：先分析别直接改）
触发：用户反馈——"当前交互不直观；单独每个图的缩放、拖动等都要按修饰键，是垃圾交互；
建议参考 Miro 这类 canvas 软件的交互逻辑整体优化。"
关联：`docs/analyzer/ui-prototypes/2026-08-14-ultraview-floating-canvas-options.html`
（全画布浮层三方案视觉研究——那是**视觉结构层**，本文是**交互语义层**，互补不重复）。

## 0. 结论速览

用户的体感是准的，而且病根不在参数调优，是**三个结构性决策**共同造成的：

1. **主拖拽语义被数据操作占用**——普通拖 = 换引用/交换槽位（P0 遗产），
   于是"移动卡片"这个最高频的布局操作被流放到 Alt+拖，"改大小"被流放到
   Alt+Shift+拖。Miro 世界里这两个恰恰是**零修饰键**的一等手势。
2. **布局手势用 QDrag/MIME 实现**——移动和 resize 都走 drag-and-drop 管线
   （`widgets.py:1712-1728`），没有实时 ghost、没有连续反馈、"用拖放表达
   resize"本身反直觉，还引入了嵌套事件循环崩溃族（S1，已出 lesson）。
3. **没有视口变换层**——画布只有滚动条（`BoardScrollArea`，
   `widgets.py:2035`），不能缩放、不能拖动平移。overview、minimap、
   FocusLayer 三个面各写一套渲染器，本质都是在补"缺 zoom/pan"这一个洞。

对应的解法是一个阶梯（§5）：**Tier 0 去修饰键 + 直接操纵**（不动架构，收益最大）、
**Tier 1 视口 zoom/pan**（`grid_metrics` 纯映射已经为此留好了缝）、
**Tier 2 QGraphicsView 重宿主**（仅当 Tier 1 真机手感不达标才升级）。
建议 Tier 0+1 合成一个 P3 package 立项，Tier 2 作为备选路线写进 spec 的风险节。

## 1. 现状交互全景（实测自 HEAD 60516a72 代码）

### 1.1 画布层（Board 空间）
| 操作 | 现状 | 锚点 |
|---|---|---|
| 平移 | 仅滚动条 + Home/End/PageUp/PageDown | `widgets.py:2035-2075` |
| 缩放 | **无**（P0/P1 明确 no board zoom） | `layouts.py:4-5` 注释 |
| 拖动平移 / 空格平移 / 中键平移 | 无 | — |
| 滚轮 | QScrollArea 默认纵向滚动；无 Ctrl+滚轮缩放、无 pinch | 全模块无 `wheelEvent` |
| 全局导航 | BoardOverview（模态整板投影，点卡跳转） | `widgets.py:2077` |
| 局部导航 | FreeGridMinimap（168×112，点击居中视口） | `widgets.py:1958` |

### 1.2 卡片层（两种模式通用）
| 操作 | 现状 | 锚点 |
|---|---|---|
| 单击 | 选中（单选，无框选/多选） | `widgets.py:1415-1419` |
| 双击 / Enter | FocusLayer（静态放大 ≤100%，模态） | `widgets.py:1421`、`2540` |
| **普通拖** | **ref-MIME QDrag = 数据操作**：拖到另一卡=交换/替换、拖到空槽=移动、拖到托盘=下架 | `widgets.py:1425-1437`、coordinator `_on_swap_slots` 等 |
| Delete / Backspace / O / R / Ctrl+C | 移除 / 入托盘 / 开源 View / 重绑 / 复制图像 | `widgets.py:1443-1469` |
| 右键 | 上下文菜单（含全部次级操作） | `widgets.py:1411` |

### 1.3 自由网格附加层（P2）
| 操作 | 现状 | 锚点 |
|---|---|---|
| 移动卡片 | **Alt+拖**（另一种 MIME 的 QDrag）或 Alt+方向键 | `widgets.py:1712-1728`、`1730-1748` |
| 改卡片大小 | **Alt+Shift+拖**（同样是 QDrag！）或 Alt+Shift+方向键 | 同上 `:1721` |
| 尺寸预设 | 仅右键菜单（小/标准/宽/高/大/横幅） | `widgets.py:1694-1707` |
| resize handle / 拖拽 ghost / 框选 | **全部没有**（A04 欠账，audit 已补记） | — |
| 碰撞 | 拒绝 + toast（60516a72 后两路一致） | coordinator |
| 撤销 | Cmd/Ctrl+Z/Shift+Z（页面级快捷键） | `page.py:252-255` |

### 1.4 小结：用户抱怨的逐条对应
- "单独每个图的拖动要按键" → Alt+拖移动（1.3 第 1 行）。
- "单独每个图的缩放要按键" → Alt+Shift+拖 resize，且无 handle 无预览（1.3 第 2 行）。
- "不直观" → 移动/缩放 affordance 完全不可见（无 handle、无光标变化、无 ghost），
  修饰键组合只能从 hints/帮助页学；画布本身不能缩放平移，"canvas"的空间心智模型
  没有建立起来。

## 2. 病根诊断

### 2.1 拖拽语义占位错误（根因，其余是并发症）
P0 把"普通拖"分配给了数据操作（换引用/交换槽位），这在**模板模式、4-6 张卡**
的世界里是成立的——槽位固定，拖卡等于换内容。P2 引入自由网格后，"移动"变成
最高频操作，但语义槽已被占，只好加修饰键。**这是优先级装反了**：Miro/Figma/
白板类工具的公理是"拖 = 空间移动"，数据操作才是需要显式 affordance 的那个。

### 2.2 布局手势用错了机制
移动/resize 走 `QDrag.exec_()`（MIME 序列化 → 嵌套事件循环 → drop 端解析）：
- 无实时反馈：拖动过程中卡片原地不动，没有 ghost 跟手、没有落点预览、没有
  非法位置着色——用户要到松手才知道结果（碰撞被拒时尤其困惑）。
- "拖放表达 resize" 违反直觉：resize 心智模型是"抓住边缘拉"，不是"把卡拖到
  某处表示新尺寸"。
- 嵌套事件循环是 S1 崩溃族的温床（已固化为 lesson
  `ultraview-qdrag-exec-must-outlive-source.md`）。
QDrag 的正当用途是**跨容器数据传递**（库→板、卡→托盘），布局内直接操纵应当是
mousePress/Move/Release 状态机 + 实时几何更新 + 松手单次提交（天然进 undo 栈）。

### 2.3 缺视口变换层，导致三个补丁面
没有 zoom/pan，就需要 overview 补"看全局"、minimap 补"知道自己在哪"、
FocusLayer 补"看清一张"。三者各写一套缩放渲染（我在多维评审 S5 已指出 overview
是第二套渲染器必然漂移）。一个真正的可缩放画布会把三者收敛为同一个视口变换的
三个档位：fit-to-board、当前视口、zoom-to-card。

## 3. Miro 交互模型拆解（目标语义参照系）

Miro 类工具的手势公理，按不可妥协程度排序：

1. **视口**：滚轮/双指 = 平移；Ctrl(Cmd)+滚轮、pinch = **以光标为锚点**缩放；
   空格+拖或中键拖 = 平移；快捷档位 fit / 100%；缩放控件常驻角落。
2. **直接操纵零修饰键**：点击选中；**拖对象 = 移动**；选中框带 handle，
   拖 handle = resize；拖空白 = 框选多选；多选整体移动。
3. **连续反馈**：拖动全程 ghost 跟手、对齐吸附参考线实时出现、非法/合法状态
   实时着色，松手才提交（非法则弹回）。
4. **修饰键做增强不做门槛**：Shift = 约束比例/轴向，Alt = 拖出副本。
   任何基础操作都不需要修饰键。
5. **双击 = 进入对象**（编辑/聚焦）；上下文工具条浮在选区上方。
6. **容器**（Miro 的 frame ≈ 我们的 Board）：可整体选中、可 zoom-to-fit。

## 4. 映射到 UltraView：目标交互草案

| 手势 | 现状 | 目标 |
|---|---|---|
| 拖卡片（自由网格） | Alt+拖（QDrag） | **普通拖 = 移动**：ghost 跟手，网格落点实时高亮（合法蓝/非法红），松手提交或弹回 |
| 改卡片大小 | Alt+Shift+拖（QDrag） | 选中出 **8 向 handle**，拖 handle 吸附到整数格，实时显示 "6×3" 徽标 |
| 画布缩放 | 无 | Ctrl(Cmd)+滚轮 + pinch，以光标为锚；工具条 −/100%/＋/fit（原型 HTML 已画） |
| 画布平移 | 滚动条 | 滚轮双轴平移 + 空格/中键拖平移；滚动条保留 |
| 看全局 | BoardOverview 模态 | **fit-to-board 档位**（同一视口变换，不再是第二渲染器）；overview 可退役 |
| 看清一张 | FocusLayer 模态 | zoom-to-card（动画视口过渡）；FocusLayer 短期保留为兼容路径 |
| 换引用/替换 | 普通拖卡到另一卡 | **从库/托盘拖入**保留 QDrag（跨容器，正当用途）；卡对卡替换改为"拖入悬停 0.5s 出现替换意图环"或检查器按钮——从主手势上腾位 |
| 交换两卡（模板） | 普通拖 | 模板模式槽位固定，拖 = 移动到槽位、占用则交换——语义与自由网格"拖=移动"统一 |
| 多选 | 无 | 拖空白 = 框选；Shift+点 = 加选；多选整体移动/删除/入托盘 |
| 键盘路径 | Alt+方向键等 | **保留**为次要通道（无障碍 + 精调），hints/quickref 同步（/update-hints） |
| 尺寸预设 | 右键菜单 | 保留，作为 handle 之外的快捷路径 |

沿途附赠的收敛：`pixels_to_grid_delta`（`free_grid.py:125`，当前死代码）正是
直接操纵状态机需要的函数——现有纯几何层已经为正确的交互写好了原料。

## 5. 工程可行性阶梯

### Tier 0 — 去修饰键 + 直接操纵（不动架构，先杀最痛的）
- 自由网格卡：mousePress/Move/Release 状态机替代 Alt+QDrag；ghost 用现成
  预览 QImage 半透明绘制在 Board 顶层；落点用 `candidate_move` +
  `rect_is_available`（`free_grid.py:159-182`）实时判色；松手一次提交进
  undo 栈（现有 `GridGeometryCommand` 语义吻合）。
- resize：选中态画 handle（QWidget 子控件或 paintEvent），拖动映射
  `candidate_resize`。
- 数据操作腾位：库/托盘→板保留 QDrag；卡对卡替换迁到悬停意图或检查器。
- 风险：模板模式与自由网格的"拖"语义要一次讲清（都改成"拖=移动"）；
  hints/quickref/帮助页全量同步；现有绕过真实键鼠事件的测试要补真事件用例
  （多维评审 §6 已点名这个空白）。
- 这一层**不需要**视口变换，单独发布已能消掉用户抱怨的主体。

### Tier 1 — 视口变换（zoom/pan）
- `grid_metrics()`（`free_grid.py:61-106`）是纯逻辑→像素映射，zoom 因子可以
  干净插入（缩放 column_width/row_height/gutter/padding 或缩放入参视口），
  模板模式同理走 `layouts.slot_rects` 的 content 缩放。
- 卡片仍是 QWidget：缩放 = 逐卡 setGeometry + 预览 pixmap 重采样。手势进行中
  用 FastTransformation，静止 300ms 后补 SmoothTransformation 高质量档
  （双档渲染，与现有 quality 思路同构）。24 卡上限下量级可控，但**必须真机
  验证手感**（offscreen 量不出，Gotchas 既有条款）。
- chrome LOD：<60% 隐藏 footer，<40% 只留标题条——避免小字号糊成噪声。
  `CARD_HEADER_HEIGHT`/`CARD_FOOTER_HEIGHT` 是固定 chrome（`layouts.py:27-29`），
  LOD 就是在几档 chrome 高度间切换，不是连续缩放文字。
- 放大侧的分辨率上限：预览抓取上限 `MAX_PREVIEW_RAW_EDGE=1600`。多维评审 S4
  指出的 residency `target_size`/FOCUS tier 死参数**正是这里的钩子**——
  zoom-to-card 时把焦点卡升到 FOCUS tier 重抓高分辨率，闲时降回。
  这个"缺陷"其实是提前修好的地基。
- 视口态（zoom/pan per Board）**不得进入身份 digest**（B1/B5 的教训：
  视图态混进 digest 会把 stale 判定搞坏）；是否持久化进 payload 是产品决策
  （Miro 持久化；若持久化，作为 digest 外字段，schema 增量）。

### Tier 2 — QGraphicsView 重宿主（备选，不默认走）
- 收益：原生 transform/框选/item 系统，ghost 与吸附线是 scene 一等公民；
  卡片变 QGraphicsItem（绘制缓存 QImage + chrome），**QWidget 僵尸/QDrag
  崩溃族整类消失**；overview/minimap/compositor 可统一到 scene 渲染。
- 成本：`widgets.py` 卡片/板层约 2600 行重写，全部 UltraView UI 测试重锚，
  模板模式同步迁移；与 ui_kit QSS 样式体系脱钩（QGraphicsItem 不吃 QSS）。
- 判据：仅当 Tier 1 在真机上 pinch/滚轮缩放掉帧或跟手性不达标才升级。
  先做 Tier 1 的一日 spike（24 卡 + 连续缩放的真机帧率）再定。

### 推荐路线
**Tier 0 + Tier 1 合并为一个 P3 package**（"UltraView 画布交互"），
spec/plan 走 2026-08-04/08-08 的既有范式；Tier 2 写进 spec 的风险与备选节。
原型 HTML 的三方案（轻量浮岛/深色数据台/信号地图）在视觉层继续用，
本文的手势表是它们共享的交互底座。

## 6. 护栏对账（改交互不许碰坏的东西）

- **只读合同**：zoom/pan/选中/ghost 全是视图态，不得反写分析/时域状态，
  不得进 payload digest。
- **零计算合同**：直接操纵与视口变换只消费已有 QImage，不触发任何分析计算。
- **QDrag lesson**：新交互把 QDrag 收缩回跨容器传递，正面消解
  `ultraview-qdrag-exec-must-outlive-source` 整类风险。
- **S5 合成预算**：ghost/缩放的中间缓冲要复用，不得每帧新分配整板 ARGB。
- **棘轮**：新连接不用 lambda；新状态归属声明清楚（协作者 `_owned_names`）。
- **发现性面**：手势改版是 hints/quickref/帮助页的大改，`/update-hints` 必跑；
  修饰键从"门槛"降为"增强"后，帮助文案要整体重写。
- **真机验收**：pinch/惯性滚动/缩放帧率必须 Cocoa 真机测（offscreen 无效），
  验收产物进 `docs/analyzer/verify/`。

## 7. 开放问题（进 spec 前需要定夺）

1. **模板模式的去留**：Miro 化的终局是"自由网格为主，模板降为 auto-layout
   命令"（一键排成 3×3，排完仍是自由网格）。这一步动 schema 与心智模型，
   建议 P3 先不做、spec 里立为 P4 方向讨论。
2. **视口态是否持久化**（per Board 记住 zoom/pan）：建议持久化（Miro 惯例），
   digest 外字段。
3. **卡对卡替换的新家**：悬停意图环 vs 检查器按钮 vs 两者都要——需要用户拍板。
4. **Qt5/Cocoa 的 pinch 手势可靠性**：QNativeGestureEvent 在 PyQt5 下的
   触控板行为需要一日 spike 实测，这是 Tier 1 唯一的技术未知数。
