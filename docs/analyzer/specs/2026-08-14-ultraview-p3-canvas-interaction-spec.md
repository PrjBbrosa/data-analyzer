# UltraView P3：画布交互改版 + 遗留收口 Spec

日期：2026-08-14 · 作者：Claude · 状态：**DRAFT，未授权执行**
配套 plan：`docs/analyzer/plans/2026-08-14-ultraview-p3-canvas-interaction-implementation.md`
上游输入：
- 交互分析 `docs/analyzer/reviews/2026-08-14-ultraview-canvas-interaction-analysis.md`（病根与阶梯，本 spec 把其 §4/§5 规范化）
- 多维评审 §9 收口核对 `docs/analyzer/reviews/2026-08-14-ultraview-p1-p2-multidimensional-review.md`（遗留六项，并入本包）
- 视觉研究 `docs/analyzer/ui-prototypes/2026-08-14-ultraview-floating-canvas-options.html`（视觉层，另行择案）

## 1. 为什么现在做，为什么合成一个包

用户对 P1/P2 落地后的直接反馈：移动、改尺寸都要修饰键（Alt+拖 / Alt+Shift+拖）、
无 affordance、画布不能缩放平移——"不直观，是垃圾交互"。交互分析定性为三个结构
性根因：主拖拽语义被数据操作占用、布局手势误用 QDrag、缺视口变换层。

**合并理由**（而不是收口与交互各立一包）：
1. 遗留项 1（residency FOCUS tier 死参数）正是 P3-2 zoom-to-card 的钩子，分开做会接两次。
2. 遗留项 3（真实鼠标事件回归测试缺失）如果先给旧 Alt+QDrag 手势补测试，P3-1 一动手就全部作废——测试只给新手势写一次。
3. 其余遗留项（digest characterization、destroyed 重连、影子缓存、扩容回填、导出拒绝文案）都是小项，独立成包的 spec/plan/验收开销大于工作本身。

## 2. 范围与非目标

范围（三个里程碑，plan 按此分批）：
- **P3-0 遗留收口**：多维评审 §9 六项中的 2/4/5/6（1、3 并入 P3-2/P3-1）。
- **P3-1 直接操纵**：去修饰键的移动/resize/多选，数据操作重新安置，发现性面同步。
- **P3-2 视口变换**：zoom/pan、LOD、FOCUS tier 接线、视口态持久化、真机验收。

非目标（明确不做，防止范围爬行）：
- 模板模式降级为 auto-layout 命令（P4 方向，见 D1）。
- 导出分页 PNG（维持 A15 已文档化欠账，本包只改拒绝文案）。
- P2-B live inspection（维持 audit NO-GO）。
- QGraphicsView 重宿主（Tier 2 仅为备选路线，见 §9）。
- 预览内容的任何再计算（零计算合同不动）。

## 3. 决策记录（默认裁决，用户可推翻）

| # | 决策 | 裁决 | 理由 |
|---|---|---|---|
| D1 | 模板模式去留 | **保留双模式**，但拖拽语义统一为"拖=移动"（模板内=移动到槽位/占用则交换） | 降级动 schema 与心智模型，超出本包；语义统一是本包必须做的 |
| D2 | 视口态（zoom/pan per Board）持久化 | **持久化**，作为 payload 的 **digest 外**字段，缺省容忍（additive，不升 schema） | Miro 惯例；B1/B5 教训是视图态不得进身份 digest，不是不得存盘 |
| D3 | 卡对卡替换的新家 | 库/托盘拖入悬停 ≥0.6s 出**替换意图环**为主路径；右键菜单「替换为…」为辅 | 从主拖拽手势上腾位后必须有显式替代；意图环是 Miro 系惯例 |
| D4 | 扩容自动回填（`set_layout` 把托盘 refs 补进新槽） | **保留行为 + toast「已从托盘补位 N 张」+ 双向测试**，推翻 P2 plan Task 2 RED#3 | 回填非破坏、可撤销、对用户有利；本仓文化反对的是**静默**，加 toast 即合规。改 plan 合同须在提交里写明（护栏变更纪律） |

## 4. 交互规范（normative）

### 4.1 卡片直接操纵（自由网格）
- **移动**：左键按下卡片 → 超过 `startDragDistance` 进入移动态；半透明 ghost
  （现有预览 QImage，不重绘）跟手；目标格实时高亮，合法蓝 / 非法（碰撞或越界）红；
  松手：合法则单次提交（进 undo 栈），非法则动画弹回原位 + 已有 toast。
  实现为 mousePress/Move/Release 状态机，**不走 QDrag**。
- **resize**：选中卡显示 8 向 handle（4 角 + 4 边，命中区 ≥8px，光标随向变化）；
  拖 handle 吸附整数格（`candidate_resize` + `clamp_rect`），实时显示 span 徽标
  （如 "6×3"）；合法性着色与提交/弹回同移动。
- **多选**：拖画布空白 = 框选；Shift+点 = 加/减选；多选整体移动（组内相对位置
  不变，任一成员非法则整组非法）；Delete/Backspace 作用于全组。组操作进 undo
  栈为**单条**。
- 修饰键降为增强：Shift+拖 handle = 保持宽高比（对齐到最近合法整数格）。
  Alt+方向键 / Alt+Shift+方向键**保留**为键盘精调通道。
- 旧 Alt+拖 / Alt+Shift+拖手势与 layout-MIME QDrag 路径**移除**（不做兼容期）。

### 4.2 数据操作重新安置
- 库/托盘 → 板：**保留 QDrag**（跨容器传递，正当用途；S1 护栏不动）。
  落到空白 = 放置；悬停已有卡 ≥0.6s 出现替换意图环，环内松手 = 替换，环外 = 取消。
- 卡 → 卡交换：自由网格中取消专用手势（移动已覆盖需求）；模板模式拖卡到占用
  槽位 = 交换（维持现状语义，但换直接操纵实现）。
- 卡 → 托盘：拖出画布下缘到托盘区仍可用（QDrag 或状态机落点判定，plan 定）；
  右键「移到未放置」保留。

### 4.3 视口变换（P3-2）
- 缩放：Ctrl(Cmd)+滚轮与触控板 pinch，**以光标为锚**；范围 25%–200%，步进
  平滑；工具条常驻 − / 百分比 / ＋ / fit / 100%（视觉从原型 HTML 择案）。
- 平移：双指滚动双轴平移；空格+左键拖或中键拖 = 抓手平移；滚动条保留。
- fit-to-board = 视口档位（取代 BoardOverview 的"看全局"职责；overview 控件
  退役与否由 plan Task 验证后定，退役需迁移其点击跳转能力）。
- zoom-to-card：双击卡片 = 动画视口过渡至该卡充满视口（FocusLayer 保留为
  兼容路径至 P3-2 验收后再裁）。
- 渲染双档：手势进行中 FastTransformation，静止 300ms 后 SmoothTransformation
  重绘一遍。中间缓冲复用，禁止每帧新分配整板 ARGB（S5 教训）。

### 4.4 chrome LOD
缩放 <60%：隐藏 footer；<40%：仅标题条。在 `CARD_HEADER_HEIGHT`/
`CARD_FOOTER_HEIGHT` 的几档固定 chrome 间切换，不连续缩放文字。

### 4.5 分辨率与 FOCUS tier
zoom-to-card 或视口放大使某卡显示尺寸超过其现存预览 0.75× 时，将该卡升入
FOCUS tier 重抓高分辨率（打通 residency `target_size` 生产路径——多维评审 S4
的另一半）；视口离开后闲时降回。抓取上限仍受 `MAX_PREVIEW_RAW_EDGE`/
`MAX_PREVIEW_PIXELS` 约束。

### 4.6 视口态持久化（D2）
payload 每 Board 增加 `viewport: {zoom, center_x, center_y}`（digest 外、
缺省容忍、非法值 clamp + warning）。P1 的未知字段 passthrough 契约保证旧读者
不销毁它。

## 5. 技术设计要点

- **直接操纵状态机**：新协作者（如 `ui/chart_stack/ultraview/gesture.py`），
  持有 press 起点、当前候选 `GridRect`、合法性缓存；复用 `pixels_to_grid_delta`
  （现死代码转正）、`candidate_move/resize`、`rect_is_available`。提交走现有
  coordinator intent（`geometry_requested` 族），**不新增第二条提交路径**。
- **ghost 层**：Board 顶层单个 overlay widget 画 ghost + 高亮 + 徽标 + 框选矩形，
  透明背景遵守 Gotchas（`WA_TranslucentBackground` 需 paintEvent 兜底）。
- **视口变换**：zoom 因子进 `grid_metrics()` 入参侧（缩放 viewport 或缩放
  column_width/row_height/gutter/padding，plan spike 定），模板模式经
  `layouts.slot_rects` 的 content 同步缩放；卡片仍是 QWidget，逐卡
  setGeometry + pixmap 重采样。**卡片数上限 24 是此方案的可行性边界**，
  spike 必须在真机验证 24 卡连续缩放帧率。
- **状态归属**：手势态/视口态归新协作者 `_owned_names`；不得写穿宿主白名单外
  属性（backref 护栏）。信号连接不用 lambda（棘轮）。

## 6. 护栏对账

只读合同与零计算合同不动；视口/手势态不进身份 digest；QDrag 仅存于跨容器路径
（lesson `ultraview-qdrag-exec-must-outlive-source` 的护栏保留）；S5 缓冲复用；
状态所有权/lambda/import boundary 棘轮全部维持；hints/quickref/帮助页随手势
改版全量重写（`/update-hints`）；真机 Cocoa 验收强制（offscreen 只当排版草稿）。

## 7. 量化收益

- 移动一张卡：Alt+拖（无反馈、松手才知结果）→ 普通拖 + 全程 ghost；
  改尺寸：Alt+Shift+拖（不可发现）→ 可见 handle。基础操作修饰键数 2 → 0。
- 崩溃面收缩：布局手势离开 QDrag 嵌套事件循环，S1 风险族在布局路径上结构性消失。
- 导航面收敛：overview（第二渲染器已消灭）职责并入 fit 档位，minimap 保留，
  FocusLayer 视验收裁撤——三个补丁面 → 一个视口变换 + 一个 minimap。
- 遗留清零：多维评审 §9 六项全部关闭或并入。

## 8. 验收矩阵（节选，plan 展开为 RED 用例）

| # | 验收 | 环境 |
|---|---|---|
| UV-P3-A01 | 普通拖移动：ghost 跟手、合法/非法着色、松手提交/弹回，均以**真实鼠标事件**驱动 | offscreen |
| UV-P3-A02 | resize handle 八向命中、吸附整数格、span 徽标 | offscreen |
| UV-P3-A03 | 框选多选、组移动原子提交、组内任一非法整组弹回 | offscreen |
| UV-P3-A04 | 替换意图环：<0.6s 不触发、环内松手替换、环外取消 | offscreen |
| UV-P3-A05 | 移动/resize/组操作各为单条 undo；undo 失配清栈行为不回归 | offscreen |
| UV-P3-A06 | zoom-at-cursor 锚点不漂移；25%–200% clamp；fit/100% 档位 | offscreen + 真机 |
| UV-P3-A07 | 24 卡连续缩放/平移帧率达标（读数入 verify） | **真机 Cocoa** |
| UV-P3-A08 | pinch/双指平移手势可用 | **真机 Cocoa** |
| UV-P3-A09 | LOD 档位切换阈值正确、不抖动（滞回） | offscreen |
| UV-P3-A10 | FOCUS tier：放大触发高分重抓、离开降回、预算不破 | offscreen |
| UV-P3-A11 | 视口态存盘往返、旧读者 passthrough 不销毁、非法值 clamp+warning | offscreen |
| UV-P3-A12 | 零计算三层探针覆盖全部新手势与视口操作 | offscreen |
| UV-P3-A13 | 扩容回填 toast + 双向测试（D4） | offscreen |
| UV-P3-A14 | digest 跨进程 characterization 收紧（禁 `in {...}` 放宽写法） | offscreen 两进程 |
| UV-P3-A15 | hints/quickref/帮助页无 Alt+拖残留文案 | offscreen |

## 9. 风险与备选

- **最大技术未知数**：PyQt5/Cocoa 的 pinch（QNativeGestureEvent）与高频滚轮
  缩放的跟手性。plan Task 0 先做一日真机 spike；**升级判据**：24 卡连续缩放
  掉帧（>1 帧 >33ms 持续出现）或 pinch 事件不可靠 → 启动 Tier 2
  （QGraphicsView 重宿主）评估，本包 P3-2 暂停，P3-0/P3-1 不受影响照常交付。
- 手势切换无兼容期：老用户肌肉记忆断裂。缓解：hints 首次进入弹改版提示，
  键盘通道保留。
- 组移动 + 碰撞拒绝的组合爆炸：限定"整组刚体平移"（不重排组内相对位置），
  复杂度回到单矩形并集判定。
