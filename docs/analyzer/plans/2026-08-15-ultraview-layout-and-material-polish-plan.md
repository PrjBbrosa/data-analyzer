# UltraView 布局与月白石蓝质感优化方案

日期：2026-08-15  
状态：PROPOSED（仅方案；未改产品源码）  
原型基线：[2026-08-15-ultraview-view-library-rework-options.html](../ui-prototypes/2026-08-15-ultraview-view-library-rework-options.html)

## 1. 已确认的决策

1. **View 库维持当前“展开分组”方案，不在本包继续调整。**
2. 布局弹层改为**每行两个模板**，使用产品已有的全部八种模板；不是把自由网格伪装成第九个模板。
3. 布局缩略图重画为较精细的“纸面卡片 + 内凹画布 + 布局槽位”图示，避免目前 HTML 中蓝色小格的玩具感。
4. 布局弹层底部的“撤销 / 重做 / 整理自由网格”按钮组移除。自由网格的直接移动、尺寸调整、项目保存，以及 `Ctrl+Z` / `Ctrl+Shift+Z` 历史能力保留；本次只是移除不常用的浮层入口，不删状态模型或手势能力。
5. UltraView 采用“**月白石蓝**”作为局部材质方向：以接近月白的工作画布承载数据，用石蓝表达选中、模式和焦点；不把 UltraView 图标里的蓝紫渐变铺满应用，也不重刷产品其它页面的全局控制色。

## 2. 现状对比与问题归因

| 维度 | 产品当前实现 | 当前 HTML 原型 | 结论 |
|---|---|---|---|
| 布局模板 | `LayoutPicker` 已按 `index // 2, index % 2` 排成两列，并包含 8 项 | 仅 6 项，三列排列 | 原型应向真实产品收敛：8 项、两列，避免确认后才发现能力缺失。 |
| 缩略图 | `layout_thumbnail_icon()` 为 72×44 的单层浅蓝几何块 | 56×33 的同类简化蓝块 | 二者都是“功能正确、材质粗糙”；应升级图形层次，而非再加装饰。 |
| 底部操作 | 自由网格态才显示整理、撤销、重做；`Ctrl+Z` / `Ctrl+Shift+Z` 另有快捷键 | 始终出现“撤销 / 整理自由网格”示意按钮 | 可去除底栏；历史仍有快捷键，布局弹层回归单一职责“选模板”。 |
| 底色 | `CanvasHost.paintEvent()` 直接画 #E9EFF3 与 22 px 点阵；QSS 同为 #E9EFF3 | 月白石蓝方案使用 #EDF2F5、#3E709C；外层仍保留一点紫色氛围 | 产品与原型的冷灰底接近，但活动蓝相差很大，应由 UltraView 局部 token 统一。 |
| 图标 | UltraView 图标由 `Icons` 固定颜色的 QPixmap 绘制，普通态默认 #475569；QSS 的 `color` 不会自动给现成 pixmap 着色 | SVG 跟随 CSS `currentColor`，选中后自然变石蓝 | 产品不能只改 QSS 色值；需在图标设置路径中显式重绘 active/rest 图标。 |

产品的布局语义和浮层几何已可复用：模板与自由网格是两个独立模式，布局弹层只需选择模板；左轨弹层已经以触发按钮的纵向中心计算锚点，并在安全区内夹住。因此本包不改变 Board、自由网格、导出、拖放或弹层定位合同。

## 3. 目标视觉系统

产品对象是工程师在高数据密度 Board 中编排分析图，而不是一个展示型网页。质感来自克制的层次、干净的边界和有意义的状态色。

| 角色 | 目标色值 | 用途 |
|---|---|---|
| 月白画布 | `#EDF2F5` | CanvasHost 连续工作底，不用纯白抢卡片层级。 |
| 石蓝点阵 | `rgba(77, 109, 132, .15)` | 22 px 点阵，降到“能定位、不抢读图”的程度。 |
| 浮岛纸白 | `#FCFDFE` | 左轨、顶部/底部浮岛与布局浮层的实面。 |
| 石蓝主色 | `#3E709C` | 当前模板、模式 active、键盘焦点与主动作。 |
| 深石蓝 | `#315E85` | pressed、文字强调和选中模板标题。 |
| 选中雾面 | `#EAF2F8` | active wash；用于表达状态，不作为大块底色。 |
| 冷灰边线 | `#C7D4DF` / `rgba(67, 92, 111, .20)` | 岛、缩略图框和常规分隔。 |
| 正文 / 次文 | `#203347` / `#6B7D8E` | 保留数据软件应有的清晰度。 |

唯一的识别性动作是：选中的布局缩略图有一张**石蓝描边的纸面**，其内的主槽位稍深、其余槽位保持月白灰。除此以外没有渐变大面、彩虹模板或卡片阴影堆叠。UltraView 品牌图标的蓝紫渐变只留在产品标识，不扩散到操作控件。

## 4. 目标布局弹层

```text
┌──────────────────────────── 布局 ──────────────────────────── × ┐
│  选择模板 · 当前 3 个 View；自由网格在左侧独立开关                 │
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐                               │
│  │  [精细图示]   │  │  [精细图示]   │   左右双图 / 上下双图          │
│  │  左右双图 2格 │  │  上下双图 2格 │                               │
│  └──────────────┘  └──────────────┘                               │
│  ┌──────────────┐  ┌──────────────┐                               │
│  │  [精细图示]   │  │  [精细图示]   │   2×2 / 左主图 + 3 辅图        │
│  └──────────────┘  └──────────────┘                               │
│  ┌──────────────┐  ┌──────────────┐                               │
│  │  [精细图示]   │  │  [精细图示]   │   上主图 + 3 辅图 / 3×2        │
│  └──────────────┘  └──────────────┘                               │
│  ┌──────────────┐  ┌──────────────┐                               │
│  │  [精细图示]   │  │  [精细图示]   │   3×3 / 4×3                    │
│  └──────────────┘  └──────────────┘                               │
└────────────────────────────────────────────────────────────────────┘
```

- 每项展示：布局图、完整中文名称和“2 格 / 4 格 / 6 格 / 9 格 / 12 格”容量说明。
- 当前项只用石蓝框、月白 wash 与“当前”文字；**不再使用底部蓝色大按钮**。
- 自由网格开启时，八项均不高亮，标题说明改为“当前为自由网格；选择任一模板即可切回”。切回模板的现有确认和溢出到未放置区语义保持不变。
- 弹层宽度按两列缩略图的可读宽度计算，最大仍受 `Page._overlay_size()` 的 520 px 和画布安全区约束；800×560 时允许内部滚动，不能挤压按钮或遮住导航岛。

## 5. 实施任务

### Task 0：冻结范围与建立视觉基线

1. 记录工作树、现有 HTML 截图和运行中 UltraView 的 800×560、1280×800、1440×900 视觉基线。
2. 用 `tools/verify_ultraview_visuals.py` 产出 layout、rail、library、filter、unplaced、display、export 的 offscreen 快照与 geometry manifest；Cocoa 前台截图另列证据，不能由 offscreen 替代。
3. View 库截图只作为回归对照；本包不改 `ViewLibraryPanel`、分组、搜索或拖放。

### Task 1：先更新 HTML 原型，供视觉确认

文件：`docs/analyzer/ui-prototypes/2026-08-15-ultraview-view-library-rework-options.html`

1. 将 `.layout-grid` 从三列改为 `repeat(2, minmax(0, 1fr))`，相应收紧/重设 `.layout-panel` 宽度和单项高度，使四行两列在宽屏中留足呼吸感。
2. 补齐 `3 × 3`、`4 × 3` 两个模板，顺序严格匹配 `LAYOUT_LABELS_ZH`：左右、上下、2×2、左主+3、上主+3、3×2、3×3、4×3。
3. 重画 CSS mini-layout：外层为纸面框，内层为低对比画布；使用不同明度表达主槽位与辅槽位，保留真实长宽比例和均匀 gutter，不以高饱和蓝填满所有格。
4. 删除 `.layout-footer`、两个按钮及其 `data-message`；更新引导文案为“自由网格可由左侧独立开关进入”。
5. 将 HTML 的 canvas、点阵、浮层、选中态和 rail icon 色统一为第 3 节 token。原型不伪造 macOS 标题栏产品能力，现有展示壳仅作原型容器。
6. 验收：人工点击八项，选中态唯一；布局浮层仍与布局 rail 按钮纵向中心对齐；展开的 View 库与布局浮层互斥；无控制台错误。

### Task 2：产品布局弹层与缩略图实现

主要文件：

- `mf4_analyzer/ui/chart_stack/ultraview/chrome.py`
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_ultraview_chrome.py`
- `tests/ui/test_ultraview_page.py`

1. 在 `layout_thumbnail_icon()` 中把 72×44 的单层方块升级为约 88×54 的双层 QPainter 缩略图：外框、内凹底、真实 gutter、依布局不同的主槽位权重；使用石蓝低饱和填充而不是当前 #1769E0 透明蓝。
2. `LayoutPicker` 保持现有 `index // 2, index % 2` 的两列顺序，增加足以容纳 8 个完整中文标签的 cell 最小宽高和图标尺寸；不改变 `LAYOUT_LABELS_ZH`、`LAYOUT_SLOTS`、模板转换或点击信号。
3. 移除 `LayoutPicker` 的“整理 / 撤销 / 重做”控件、相关 layout 内信号和 `page.py` 的三条 popover connect。`set_current(layout_id, free_grid=...)` 仍保留，以便自由网格态正确清掉模板 checked state。
4. 保留 `UltraViewPage` 的自由网格快捷键和 `UltraViewCoordinator` 的历史处理；不移除 `organize_free_grid()`、历史快照、项目 schema 或直接操纵路径。它们不再被布局弹层提供入口。
5. QSS 只为 `#ultraViewLayoutPopover` 及 `role="layoutThumb"` 增加局部状态样式；遵守项目 QSS 规则，hover/checked 不使用会重置圆角的 `border:` 简写。
6. 红测优先：断言 8 个缩略图、两列四行、完整标签、当前模板唯一 checked、自由网格态无 checked template、底部三个按钮不存在；点击模板仍只发一次 `layout_id_chosen`，并保留切回模板确认。

### Task 3：月白石蓝材质与图标一致性

主要文件：

- `mf4_analyzer/ui/chart_stack/ultraview/chrome.py`
- `mf4_analyzer/ui_kit/style.qss`
- `mf4_analyzer/ui_kit/icons.py`（仅当需要为 UltraView 增加显式色参，不改其它产品图标默认色）
- `tests/ui/test_ultraview_chrome.py`
- `tools/verify_ultraview_visuals.py`

1. 将 `CanvasHost.paintEvent()` 的底色与点阵改为第 3 节月白石蓝 token；每次主题常量变动须使 `_dot_tile` 失效后重建，避免旧 QPixmap 残留。
2. 将 UltraView 浮岛、popover、卡片边框、hover、mode active、panel open、focus 的色值收敛为局部石蓝阶梯。全局 `CONTROL_COLORS` 仍保持现有 #1769E0，防止一次视觉打磨影响分析器其它页面。
3. 解决“QSS 只改文字色、不会改已绘制 QIcon”的事实：在 ToolRail 保存图标工厂并于 `_sync_button_states()` 依据 rest / panel-open / mode-active 显式 `setIcon()`；GlobalIsland、NavigationIsland、StatusIsland 与卡片上下文的 UltraView 图标也显式传入统一的 rest 色，演示模式继续传白色。
4. 图标仅改变颜色和光学边界，不改语义、tooltip、accessible name、32×32 可点击框或 rail 顺序（库、自由网格、布局、筛选、分隔、未放置）。
5. 新增像素/属性级测试：rest 和 active 的 rail icon pixmap 颜色不同；当前模板、自由网格和 panel-open 三种状态仍可区分；未放置 badge、筛选 warning、演示白色图标和焦点环保持原有可见性合同。
6. 在视觉 verifier 的 manifest 中记录：画布抽样色、点阵 alpha、岛/弹层 rect、模板缩略图网格坐标、selected icon/color；将 1280×800 触发按钮中心与 layout overlay 中心的误差继续限定在现有安全区规则内。

### Task 4：更新真实可见说明并完成回归

文件：

- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- `mf4_analyzer/help/ultraview-guide.html`

1. 删除“布局浮层的整理会压缩自由网格空行”这一入口描述。
2. 把自由网格历史说明改为“直接移动/调整后可使用 Ctrl+Z / Ctrl+Shift+Z 恢复或重做”，不再声称布局浮层内有按钮。
3. 保留自由网格的 12 列、24 卡、拖放、尺寸预设、minimap、保存与不重算说明。

## 6. 验证矩阵

先运行红测，再执行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_chrome.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_floating_layout.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_export.py \
  tests/ui/test_ultraview_state.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_no_lambda_signal_connections.py -q
```

随后执行：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python tools/verify_ultraview_visuals.py \
  --output .state/ultraview-layout-material-polish/after
git diff --check
```

前台验收（独立于上述测试）：在 macOS Retina 下检查 800×560、1280×800、1440×900；八模板两列、布局/自由网格的 active 区分、未放置 badge、筛选 warning、演示态、布局浮层锚点与 View 库互斥必须均可见。确认画布底色比卡片更退后、图标在选中/未选中时都清晰且不刺眼。

## 7. 非目标与提交边界

- 不重做 View 库，不改变其五类分组、搜索、加入 Board、拖放、状态点或 popup 几何。
- 不改 Board schema、`UltraViewBoardState`、`LAYOUT_SLOTS`、自由网格算法、卡片数据、导出、预览缓存和零计算合同。
- 不把月白石蓝扩展为全应用主题；只触及 UltraView 的画布、浮岛、布局模板与其图标路径。
- 不删除自由网格历史/整理的底层实现；它们将保持可兼容和可测试，后续若要废弃需另做使用证据和迁移决策。
- 建议分两次提交：`docs(ultraview): align layout prototype with template inventory`；`style(ultraview): refine layout picker and moonstone chrome`。每次仅暂存本计划所列文件。
