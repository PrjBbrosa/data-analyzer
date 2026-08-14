# UltraView Miro 式窄轨浮岛工作区 Spec

日期：2026-08-14

状态：**方向已确认；本文冻结产品与交互合同，尚未授权修改产品源码**

目标原型：[2026-08-14-ultraview-miro-layout-options.html](../ui-prototypes/2026-08-14-ultraview-miro-layout-options.html)，以其中 **B · 窄轨按需** 为视觉方向

配套计划：[2026-08-14-ultraview-miro-narrow-rail-implementation.md](../plans/2026-08-14-ultraview-miro-narrow-rail-implementation.md)

## 0. 结论

UltraView 改成一张连续的只读画布，编辑和导航控件以轻量浮岛叠在画布边缘。默认不展开 View 库，左侧只保留 48 px 窄轨；View 库、未放置区和设置面板按需覆盖画布，不再参与主布局分配，也不推动卡片重新排版。

本文只增量覆盖 P1/P2/P3 文档中的 **页面结构、控件入口和视觉布局**。Board 数据、自由网格手势、视口、导出、演示、只读和零计算等行为合同继续以上游已落地实现为准；若旧文档与本文在“控件放在哪里”上冲突，以本文为准。

本改版的原则是 **迁移入口，不删除能力**：

1. Board 创建、切换、复制、重命名、删除、排序全部保留。
2. 八种模板、受控自由网格、整理、撤销/重做全部保留。
3. 五种轴类型筛选和轴一致性警告全部保留，但整行 CompareRail 改为漏斗按钮弹层。
4. View 库的分组、搜索、折叠、添加、移出、定位和拖放全部保留。
5. 未放置区的放置、移除、重新绑定、定位和拖放全部保留。
6. 卡片的打开原 View、临时放大、替换、移到未放置、移除、复制图像和自由网格尺寸预设全部保留。
7. 整板复制、PNG 1×/2×、演示、缩放、适应、100%、minimap 和整板概览全部保留。
8. UltraView 的只读、零分析计算、稳定引用、项目持久化和 PreviewStore 合同不变。

改版主要改变入口密度、层级和空间占用，不改变分析逻辑、Board 数据模型或预览来源。

## 1. 当前软件事实

起草时 HEAD 基线为 a9dbd2b1，UltraView 已经不是早期 2～6 图原型，而是 P1/P2/P3 能力叠加后的独立非模态 Board 工具窗。起草期间工作树另有并行中的未提交 P3 correctness 修改；本文没有编辑、吸收或宣称完成这些修改，真正执行前必须重查 HEAD 与 dirty scope。

### 1.1 当前结构

UltraViewPage 当前使用以下垂直和水平布局：

~~~text
UltraViewPage
├── QSplitter
│   ├── ViewLibraryPanel                 224 px 默认宽
│   └── BoardColumn
│       ├── BoardSwitcher                33 px
│       ├── BoardToolbar                 42 px
│       ├── CompareRail                  38 px
│       ├── BoardScrollArea              剩余空间
│       └── UnplacedTray                 折叠仍占 30 px
└── UltraViewHintBar                     28 px
~~~

对应实现见：

- mf4_analyzer/ui/chart_stack/ultraview/page.py:180
- mf4_analyzer/ui/chart_stack/ultraview/widgets.py:500
- mf4_analyzer/ui/chart_stack/ultraview/widgets.py:673
- mf4_analyzer/ui/chart_stack/ultraview/widgets.py:896
- mf4_analyzer/ui/chart_stack/ultraview/widgets.py:3407

当前结构把四类临时控件都做成永久占位。实测在 1280×800 的 UltraViewPage 中，View 库占 224 px，BoardScrollArea 只有约 1052×629；在工具窗允许的 800×560 最小尺寸下，工具栏最小宽度会把页面撑到约 1145 px，说明现有横向控件已经不适合小窗口。

### 1.2 当前能力清单

| 能力域 | 当前能力 | 当前入口 |
|---|---|---|
| Board | 最多 20 个；创建、切换、拖动排序、复制、重命名、删除 | 顶部 QTabBar、加号、标签右键 |
| Board 名称 | 当前 Board 名称可直接编辑 | BoardToolbar 左侧输入框 |
| View 库 | 五 section 分组、搜索、折叠、添加、移出、定位、拖放 | 左侧常驻面板 |
| 模板布局 | 左右、上下、2×2、左主+3、上主+3、3×2、3×3、4×3 | 布局下拉框 |
| 自由网格 | 12 列、最多 24 张；移动、八向 resize、框选、多选、组移动 | 自由网格按钮和画布直接操作 |
| 网格整理 | 压缩空行；不静默改变引用 | 顶部“整理” |
| Undo/Redo | 每 Board 原子历史 | Ctrl/Cmd+Z、Redo 快捷键 |
| 筛选 | 全部、时间、频率、时频、阶次；不匹配卡片弱化 | CompareRail 整行按钮 |
| 轴一致性 | 单位或 X 范围不一致提示 | CompareRail 右侧文本 |
| 显示 | Board 级显示标题、来源 | “显示”菜单 |
| 未放置 | 折叠/展开、放置、移除、重新绑定、定位、拖放 | 底部托盘 |
| 卡片 | 打开原 View、临时放大、替换、移到未放置、移除、复制图像 | 卡头放大按钮、双击、右键菜单 |
| 自由网格尺寸 | 小、标准、宽、高、大、横幅 | 卡片右键子菜单 |
| 导出 | 复制整板、PNG 1×、PNG 2×、复制单卡 | 顶部按钮与卡片菜单 |
| 视口 | 25%～200%、以光标缩放、平移、适应、100%、双击铺满卡片 | 顶部缩放簇和画布手势 |
| 导航 | 自由网格 minimap、整板概览点卡返回 | 右下 minimap、顶部“整板概览” |
| 演示 | 隐藏编辑面；大模板/自由网格可进入整板概览；Esc 退出 | 顶部“演示” |
| 可信度 | fresh/stale/missing/orphaned；只读、不计算 | 卡片状态、底部提示 |

## 2. 产品目标与非目标

### 2.1 目标

1. **最大化画布**：移除常驻 View 库、三条顶部横栏、折叠托盘和全宽提示栏对 BoardScrollArea 的挤占。
2. **按作用域分层**：Board、画布、对象、导航四类动作各有固定位置。
3. **图标优先、文字解释延后**：常驻面只显示图标；名称、选项、危险说明进入 tooltip、accessibleName、弹层或确认对话框。
4. **操作能力等价**：原有入口可被迁移，但任何已交付能力不得因“精简”消失。
5. **状态诚实**：缺失、过期、孤儿、导出失败、布局溢出和轴不一致仍然可见。
6. **零计算**：打开弹层、筛选、切 Board、切布局、缩放、演示和导出不提交分析任务。

### 2.2 非目标

- 不新增分析模式、计算算法或后台渲染器。
- 不实现 P2-B live inspection。
- 不把 QWidget Board 重宿主到 QGraphicsView。
- 不改变 UltraView nested schema、UltraViewRef、PreviewStore、sidecar 或 digest。
- 不删除固定模板，不把模板降级为一次性 auto-layout 命令。
- 不以本 UI 包顺手修复所有 P3 review 欠账；重叠路径必须有基线，但应单独归属。
- 不绘制自定义 macOS 标题栏；HTML 中的红黄绿窗口按钮只是展示框架，产品继续使用 UltraViewSheet 的原生独立工具窗。

## 3. 目标信息架构

~~~text
┌──────────────────────── UltraViewSheet 原生窗口 ────────────────────────┐
│                                                                         │
│  ┌ Board 名称 ▾  ＋ ┐                         ┌ 显示 导出 演示 ┐         │
│  └──────────────────┘                         └───────────────┘         │
│                                                                         │
│  ┌──┐   ┌───────────────────────────────────────────────────────────┐  │
│  │库│   │                                                           │  │
│  │布│   │             BoardScrollArea / 连续点阵画布                │  │
│  │筛│   │                                                           │  │
│  │  │   │        选中卡片上方：对象级上下文工具条                   │  │
│  │托│   │                                                           │  │
│  └──┘   └───────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌ ?  只读预览 · 不计算 ┐          ┌ 概览  −  100%  ＋  适应  100% ┐  │
│  └──────────────────────┘          └────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
~~~

### 3.1 四层操作

| 层级 | 位置 | 只容纳 |
|---|---|---|
| Board 级 | 左上 BoardIsland | Board 切换、新建和 Board 菜单 |
| 画布级 | 左侧 ToolRail、右上 GlobalIsland | View、布局、筛选、未放置、显示、导出、演示 |
| 对象级 | 选中卡片附近 CardContextIsland | 当前卡片的打开、放大、复制、移到未放置和更多 |
| 导航级 | 右下 NavigationIsland | 整板概览、缩放、适应、100%、minimap 协同 |

同一个功能不在两个常驻区域重复出现。右键菜单可以作为完整、稳定的等价通道保留。

## 4. 空间与视觉合同

### 4.1 尺寸

| 元素 | 目标 |
|---|---|
| 外侧安全边距 | 12 px |
| 左侧窄轨 | 48 px 宽；单按钮 32×32；按钮间距 4 px |
| 浮岛高度 | 40 px；常规圆角 11 px |
| BoardIsland | 最大 240 px，名称 elide；加号独立 32×32 |
| GlobalIsland | 3 个图标：显示、导出、演示 |
| View 库浮层 | 264～288 px 宽；最大高度为画布高度减 96 px |
| 布局/筛选/显示弹层 | 240～300 px；从触发按钮右侧打开 |
| 未放置浮层 | 320～520 px 宽；最多 3 行后内部滚动 |
| CardContextIsland | 选择后出现；优先卡片上方居中，不足时放卡片内部上缘 |
| NavigationIsland | 右下；不遮挡 minimap；百分比使用等宽数字 |
| Canvas 初始安全区 | 左侧约 72 px、顶部约 64 px、右侧/底部 12～16 px |

1280×800 时 BoardScrollArea 的可见区域目标不低于 1190×700；800×560 时不允许任何子控件把 UltraViewPage 的 sizeHint 撑宽到窗口之外，BoardScrollArea 可见区域目标不低于 710×470。

### 4.2 视觉 token

| 角色 | 色值/要求 |
|---|---|
| 画布底色 | #E9EFF3 |
| 点阵 | rgba(60,82,104,0.16)，22 px 节距，缓存平铺 |
| 浮岛 | #FFFFFF 或近白不透明面；边线 rgba(74,96,121,0.20) |
| 主文字 | #17263A |
| 次文字 | #66778C |
| 主操作 | #1769E0；active 使用 #E9F1FF |
| 正常同步 | #0FA78F |
| 警告 | #D88B16 |
| 错误/破坏 | 继续使用应用既有危险色 |

Qt 产品实现沿用当前 PingFang SC / 系统字体，不引入网页字体。所有常驻图标通过 mf4_analyzer/ui_kit/icons.py 生成或复用，不用 emoji、Unicode 图形或平台字体 glyph 代替。

阴影只用于少量浮岛，不能给每张卡片挂 QGraphicsDropShadowEffect；卡片层以边线和选中环表达层级，避免 24 卡场景的绘制成本。

## 5. 功能迁移与取舍

### 5.1 BoardIsland

现有横向 QTabBar 改成“当前 Board 名称 + 下拉 + 新建”浮岛。

打开 Board 菜单后：

- 列出最多 20 个 Board，当前项有明确选中态。
- 支持单击切换。
- 支持拖动排序；键盘用户通过“上移/下移”菜单完成等价操作。
- 每项更多菜单保留复制、重命名、删除。
- 双击当前名称或 F2 可重命名，保留高频改名效率。
- 新建超过 20 个时保持当前禁用理由。
- 删除继续使用确认框，并明确不会删除源 View。

**取舍**：Board 切换从直接点击标签变为打开菜单后点击，增加一次操作；换回的是不再让 1～20 个 Board 永久占据一整行。功能无删除。

### 5.2 View 库

ToolRail 第一项为 View 库：

- 默认关闭；打开后作为覆盖浮层出现在窄轨右侧。
- 打开/关闭不能改变 BoardScrollArea geometry、滚动位置、zoom 或 Board 内容。
- 五 section 分组、SearchField、折叠状态、完整 tooltip、添加/移出、定位和拖放保持当前语义。
- 点击画布空白或 Esc 关闭；在拖放进行中不得销毁或重建拖拽源。
- 当前进程内记住开关状态；不写入项目文件。演示结束恢复演示前状态。

**取舍**：添加 View 前需要先打开库；这是“最大图面”的直接代价。拖动工作流和全部库能力保留。

### 5.3 布局弹层

ToolRail 第二项为布局，弹层必须展示当前真实能力，不照搬 HTML 的四个示意项：

1. 左右双图
2. 上下双图
3. 2×2
4. 左主图 + 3 辅图
5. 上主图 + 3 辅图
6. 3×2
7. 3×3
8. 4×3
9. 受控自由网格

每项用小型几何预览和文字标签。切入自由网格后，同一弹层显示“整理布局”、Undo、Redo；切回模板继续使用当前确认文案，并把超出容量的引用移入未放置区。

布局切换、自由网格转换、整理和历史仍通过现有 Page intent 与 coordinator 单写点提交，不新增第二条 Board mutation 路径。

### 5.4 筛选弹层

ToolRail 第三项为漏斗：

- 选项为全部、时间轴、频率轴、时频轴、阶次轴。
- 行为继续是弱化不匹配卡片，不移除、不重排、不修改 Board。
- 非“全部”时，漏斗显示 active wash 和小圆点，不使用永久文字标签。
- 量纲不一致和 X 范围不一致放在弹层下方。
- 弹层关闭后，若存在不一致，漏斗使用 warning dot；不增加常驻 Compare 行。

HTML 原型缺少“时频轴”，产品实现必须补回当前第五类。

### 5.5 显示、导出、演示

右上 GlobalIsland 只有三个图标：

- **显示**：Board 级开关“卡片标题”“来源文件”。
- **导出**：复制整板图、PNG 1×、PNG 2×。
- **演示**：进入/退出演示模式。

HTML 原型里的“预览状态”开关不进入产品：

- 当前 BoardState 没有 show_status 字段。
- stale/missing/orphaned 是可信度信息，不应由用户隐藏。
- 为此新增持久字段会把纯布局改版扩成 schema/产品语义改动。

演示模式继续隐藏所有编辑浮岛、库浮层、未放置内容和对象工具条；保留一个清晰的“退出演示”入口和 Esc。9/12 图模板与自由网格继续遵守当前自动整板概览行为。

### 5.6 未放置区

ToolRail 底部为未放置图标和数量 badge。点击后打开浮层，完整复用 UnplacedTray 内容和动作。

打开规则：

- 项目重开时已有未放置项：只显示 badge，不自动遮挡画布。
- 用户主动“移到未放置”：更新 badge 和 toast，不强制打开。
- 模板缩容首次产生溢出：自动打开一次并聚焦首个新进入项，明确卡片没有丢失。
- 空状态：按钮仍可聚焦，弹层给出“缩小布局或移入的卡片会出现在这里”的说明。

**取舍**：移除底部常驻托盘后，未放置内容不再一眼展开；badge、缩容自动打开和 toast 共同补偿，不删除任何托盘操作。

### 5.7 导航浮岛

右下 NavigationIsland 保留：

- 整板概览
- 缩小
- 百分比
- 放大
- 适应窗口
- 恢复 100%

百分比可点击后输入或选择常用档位是可选增强，不是本包 Done 条件。缩放范围继续为 25%～200%，而不是 HTML 演示脚本中的 70%～125%。

整板概览不能删除：当前 P3 证据已经确认 fit 不等价于“点卡片跳回阅读位置”。自由网格 minimap 继续存在，需与 NavigationIsland 避免重叠；minimap 可折叠进概览按钮的二级入口，但点击定位能力必须保留。

### 5.8 卡片上下文工具条

卡片选中后显示 CardContextIsland，默认快捷动作：

1. 打开原 View
2. 临时放大
3. 复制本卡图像
4. 移到未放置
5. 更多

“更多”保留替换、从总览移除和自由网格尺寸预设。右键菜单继续保留全部动作，作为稳定完整入口。orphaned 卡片的“重新绑定”“从总览移除”仍以内联高优先级提示呈现，不藏入更多菜单。

当前卡头的永久“临时放大”按钮可以在上下文工具条验收后移除；这是入口迁移，不是功能删除。双击卡片铺满视口、右键临时放大和上下文图标至少保留两条可发现通道。

### 5.9 提示与只读状态

全宽 UltraViewHintBar 改为左下轻量 StatusIsland：

- 保留“?”快速帮助入口。
- 常态显示“只读预览 · 不计算”。
- 新手提示和当前手势提示按现有 hints 轮换，不永久占一整行。
- stale/missing/orphaned 或轴不一致时使用真实状态文案，不显示无法从当前模型证明的“3 组范围一致”之类正向数字。

## 6. 状态与持久化

### 6.1 保持不变

- Board 的 name、layout_id、layout_mode、placements/free_grid、unplaced、show_titles、show_sources、viewport 继续按现有 schema 保存。
- compare filter 继续是页面瞬态状态，不进入 Board digest。
- presentation、打开的弹层、上下文工具条和选择态不写入项目。
- PreviewStore、sidecar、导出 compositor 和零计算探针不变。

### 6.2 新增 UI 瞬态

UltraViewPage 拥有且对称 reset：

- active_panel：none / library / layout / filter / unplaced / display / export / board
- library_open：bool，默认 false
- selected card context anchor
- presentation 前的 panel/library 快照

这些状态必须有单一 owner；不得写进 MainWindow 多文件状态，也不得依赖 getattr(..., False) 的静默默认。

## 7. 交互细节

### 7.1 弹层互斥

- 同一时间只允许一个画布级弹层打开。
- 切 Board、进入演示、关闭 UltraViewSheet、项目 reset 时全部关闭。
- Esc 优先级：进行中的卡片手势 → FocusLayer/BoardOverview → 当前弹层 → 选择集 → 演示。
- 文本编辑框拥有焦点时，Esc、Undo/Redo 不得被页面快捷键提前吞掉。

### 7.2 拖放

- 库/托盘跨容器拖放继续走 QDrag。
- 卡片布局移动/resize 继续走 P3 直接操纵状态机，不退回 QDrag。
- View 库和未放置浮层在 drag_finished 前不得重建或 deleteLater 拖拽源。
- 浮层关闭动作若发生在拖放期间，延迟到 drag_finished 后执行。

### 7.3 键盘与可访问性

- 所有图标按钮都有 tooltip、accessibleName、Tab focus 和可见 focus ring。
- 图标 active 状态不能只靠颜色；使用背景 wash、badge/dot 或 checked state。
- Board 菜单支持方向键、Enter、F2、Delete 前确认和排序等价路径。
- 弹层打开后焦点进入首个可操作项；关闭后回到触发按钮。
- 破坏性动作仍使用文字和确认，不做无标签垃圾桶“一键删”。
- 触控目标不小于 30×30 px。

## 8. 原型到产品的必要修正

| HTML B 示意 | 产品合同 |
|---|---|
| 4 个布局选项 | 展示当前八模板 + 自由网格 |
| 筛选缺少时频轴 | 补回全部五类 |
| 显示面板可隐藏状态 | 不提供；可信度状态强制可见 |
| Board 菜单只切换/新建 | 补齐排序、复制、重命名、删除、20 上限 |
| zoom 70%～125% | 保持产品 25%～200% |
| 未放置只 toast | 提供完整托盘浮层与拖放 |
| “更多”仅文案示意 | 接回替换、移除、尺寸预设、orphan rebind |
| 固定“3 组范围一致” | 只显示可由 axis_consistency_facts 证明的真实信息 |
| 自绘标题栏 | 保留原生 UltraViewSheet |

## 9. 验收矩阵

| ID | 验收 |
|---|---|
| UV-NR-A01 | 800×560 下 UltraViewPage 不被子控件撑宽；无横向裁切的常驻工具 |
| UV-NR-A02 | 1280×800 下 BoardScrollArea 可见区域不低于 1190×700；800×560 不低于 710×470 |
| UV-NR-A03 | 开关 View 库、布局/筛选/显示/导出/未放置弹层不改变 BoardScrollArea geometry、zoom、center 或滚动值 |
| UV-NR-A04 | Board 创建、切换、复制、重命名、删除、排序和 20 上限全部可达 |
| UV-NR-A05 | 八种模板、自由网格、整理、Undo/Redo 全部可达；切回模板确认与溢出语义不变 |
| UV-NR-A06 | 全部/时间/频率/时频/阶次筛选仅弱化，不改变 Board payload；轴不一致可见 |
| UV-NR-A07 | 显示标题和来源保持 Board 级持久化；stale/missing/orphaned 不可被隐藏 |
| UV-NR-A08 | 复制整板、PNG 1×/2×、复制单卡结果与当前 compositor 合同一致 |
| UV-NR-A09 | 演示隐藏编辑 chrome，退出后精确恢复 library/panel 状态和 Inspector 行为 |
| UV-NR-A10 | 25%～200%、缩放、平移、适应、100%、minimap、整板概览和点卡返回均可达 |
| UV-NR-A11 | 未放置 badge 准确；缩容首次自动打开；放置、移除、重新绑定、定位和拖放可用 |
| UV-NR-A12 | 卡片七项现有动作和六种自由网格尺寸预设全部有等价入口 |
| UV-NR-A13 | 库/托盘 QDrag 期间打开/关闭浮层不会销毁源 widget 或触发 qFatal |
| UV-NR-A14 | Tab、方向键、Enter、F2、Esc、Undo/Redo、tooltip、accessibleName 和 focus ring 完整 |
| UV-NR-A15 | 切 Board、开面板、筛选、布局、缩放、演示、复制、导出、保存的分析 job/store-write 计数保持 0 |
| UV-NR-A16 | UltraView payload、digest、sidecar 和 PreviewStore 行为不变；无 schema bump |
| UV-NR-A17 | 图标 idle/hover/pressed/active/disabled/presentation 状态在真实 QSS 下可区分 |
| UV-NR-A18 | 800×560、1280×800、1440×900 三档渲染截图无重叠、裁切、圆角漏底、浮层越界或遮挡 minimap |
| UV-NR-A19 | UltraView 仍为独立非模态工具窗；原 Analyzer 模式、Inspector 和源 View 可继续操作 |
| UV-NR-A20 | 现有 UltraView focused suite、状态所有权、lambda、QSS border、import boundary 和帮助文案门禁不回归 |

## 10. Done 定义

只有以下条件同时满足，窄轨浮岛 UI 才可以声明完成：

1. A01～A20 有自动化或明确的真机证据。
2. 当前能力迁移表逐项关闭，没有“为了简洁”留下不可达功能。
3. HTML、offscreen Qt、macOS Cocoa 前景证据分开记录；不以原型截图替代运行程序。
4. hints.py、quickref.py、帮助页和可访问名称与新入口一致。
5. 项目 schema、PreviewStore、sidecar、导出与零计算合同无变化。
6. 未解决的 P3 正确性问题单独登记，不得被本 UI 包的绿色视觉截图掩盖。
7. 变更范围只包含 UltraView UI/布局、必要 icon/QSS、测试和文档，不混入无关清理。
