# UltraView View 库：材质、选中态与单层分组优化计划

日期：2026-08-15
状态：已实施；离屏回归与视觉门禁通过，真实 macOS 前台验收仍需带 View 结果的样本。

## 追加修订：➕ 刷新后的分区收口与 360px 宽度

新截图确认两个运行态问题：点击 `＋` 后，Board 的 membership 刷新会重建
`ViewLibraryPanel`；重建当下 Qt 尚未布局新 section，
`_body_layout.totalMinimumSize()` 会短暂返回 22px。若立即把它写回
`QScrollArea` body，五个 section 会被压进固定浮层高度；重新打开时的
`showEvent()` 恰好重测，因此才“自行恢复”。

本次追加约束：

1. `ViewLibraryPanel` 用自身持有的单次 `QTimer` 在下一轮 Qt layout 后同步
   body minimum height；不得依赖关闭/重开面板恢复。
2. 新回归覆盖真实的 `＋` 意图 → Board membership refresh 路径，并断言滚动条
   立即可用、所有 section 不低于各自 `minimumSizeHint()`。
3. 默认 / 最大宽度从先前的 440 / 480 收至 **360 / 400**。360px 比机械的
   352px 更贴合现有 12px gutter、色点、23px action 与长文本省略的余量。

## 目标

将 UltraView 的 View 库收束为更安静的“月白石蓝”材料系统，同时保留用户已认可的能力：直接按分析类型浏览、搜索、展开/收起、选择 View、拖拽以及添加/移除 Board。

本轮合并两次截图反馈：

1. 保留已选 View 的浮起感，不能退化成普通浅蓝填充。
2. 不允许相邻 View 的分隔线穿过选中卡片下方的圆角区域。
3. 五个分析区必须可区分，但只使用 UltraView 同源的低饱和蓝灰色阶，不能形成紫/绿/橙/黄的随机彩虹。
4. 延续已确认方向：移除“展开 / 概览”的双层信息架构、略微收窄面板，并稳定最外层四角的灰色圆角描边。

对应的视觉验收基准是
[`2026-08-15-ultraview-view-library-before-after-optimization.html`](../ui-prototypes/2026-08-15-ultraview-view-library-before-after-optimization.html)。它是设计对标，不是产品运行证据。

## 现状与边界

| 事实 | 当前实现 | 本次决策 |
| --- | --- | --- |
| View 库是既有画布浮层 | `UltraViewPage` 创建 `ViewLibraryPanel` 并注册到 `CanvasHost` | 保持同一浮层和触发器，不新建 `QMenu`、`QDialog` 或第二套状态。 |
| 已选身份已有单一所有者 | `ViewLibraryPanel._selected`，并由 `set_selected()` 投射到每个 `LibraryRowWidget` | 只增强这个既有投射的呈现，不新增持久化字段，不改变 `UltraViewRef(section, view_id)` 身份。 |
| 双层架构仍在源码 | `ViewLibraryPanel` 同时构造 groups 与 compact catalog，并显示“展开 / 概览”按钮 | 移除可见切换和紧凑 catalog 路径，分组标题成为唯一概览/展开入口。 |
| Qt 行间当前没有专门的 View-to-View hairline | 组内只有 `ultraViewLibrarySectionRule`，它是标题与内容之间的规则 | 红框中的线首先视为 HTML 对标稿的相邻行边框问题；不误删合法的标题规则。原生端要增加像素门禁，保证不存在该回归。 |
| 当前色材质是中性统一白 | `style.qss` 对 `ultraViewLibrarySection` 使用同一 `#fcfdfe` | 五类 section 使用一个月白石蓝色阶；View 自身的 `tab_color` 小点仍是 View 身份，不被分析类型底色覆盖。 |

## 不在范围内

- 不改变计算、预览、Board 布局、导出、项目保存或 source/channel 复合身份。
- 不把 View 库的选中态与 Board 卡片的多选/焦点状态混为一套状态。
- 不改动 View 的 `tab_color` 数据语义；本轮只改变 section 的容器材质与统一的选中铬。
- 不以离屏测试声称完成 macOS 前台或 Windows 冻结包验收。

## 实施步骤

### 1. 先冻结现有交互与几何约束

责任文件：

- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `tests/ui/test_ultraview_page.py`

1. 为至少两个时域 View 的 fixture 加入一个先失败的视觉/几何断言：选择第一个 View 后，只有它拥有 `selected=true`；重新选择第二个时，前者清除该状态；搜索、折叠/展开、`set_on_board()` 触发的 `_rebuild()` 后，选中 ref 仍会重新投射。
2. 记录现有真实尺寸常量：默认宽度为 470、最大宽度为 520、行高为 46、组内间距为 4。产品目标先采用 440 / 480，后按运行截图收至 360 / 400；在 800×560 与 1280×800 两个既有尺寸合同中测量标签省略、搜索框、按钮和滚动条，不以 HTML 的展示比例替代真实 Qt 尺寸。
3. 为选中行预留明确的垂直空气槽（常量命名为 `LIBRARY_SELECTED_ROW_GUTTER`），避免阴影或描边需要覆盖相邻 View 的几何区域。

### 2. 收敛为单层分组，不丢原有操作

责任文件：

- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui_kit/style.qss`
- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`

1. 在 `ViewLibraryPanel.__init__()` 删除可见的“展开 / 概览”分段按钮；`groups` 成为唯一内容树，分组标题的现有 `toggled_section` 保持为唯一展开动作。
2. 删除不再可达的 compact catalog 组装、显示同步和对应 QSS；若兼容性扫描仍有非测试调用者，保留只读兼容查询并固定返回 groups，不能留下一条可恢复旧双层 UI 的隐藏路径。
3. 保留现有 search：有查询时，命中 section 自动展开；保留五个固定 `SOURCE_SECTIONS` 的顺序、计数、可访问名称、拖拽、`+/-`、定位和钉住浮层功能。
4. 从 470/520 先收至 440/480、再收至 360/400 后，`UltraViewPage._overlay_size()` 仍只通过 `LIBRARY_DEFAULT_WIDTH` 取得最小宽度，不能增加第二个硬编码宽度。
5. 删除按钮后同步更新提示和快速参考中关于“概览”或模式切换的用户可见文本；不触及无关 UltraView 教程。

### 3. 做出稳定的浮起选中态，并消除穿过圆角的线

责任文件：

- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_ultraview_page.py`

1. 继续让 `LibraryRowWidget.set_selected()` 只接受布尔投射。选中时在行自身装配轻量、由该 widget 持有的阴影效果；取消选择时清除效果并 repolish。不得增加 Page 或 Coordinator 状态，也不得使用 QSS 不支持的 `box-shadow` 伪属性。
2. 选中行使用白色表面、月白石蓝描边、轻微上浮阴影；所有 section 的选中态共用这一套色值，不随 section 改变。
3. 组内行之间仅保留 `LIBRARY_SELECTED_ROW_GUTTER` 形成的空隙；不得新增 `QFrame.HLine`、跨整组的 sibling border 或背景线。`ultraViewLibrarySectionRule` 仅保留在“标题—展开内容”之间，并继续在收起/无行时隐藏。
4. 在选择、拖拽起始/结束、搜索 rebuild、折叠和取消选择后检查 effect 的生命周期：最多一个 LibraryRow 持有浮起效果，删除重建行前不会把效果或 Qt wrapper 留在父级。

### 4. 用同源月白石蓝区分五类 section

责任文件：

- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_ultraview_page.py`

1. 复用 section frame/header 已有的 `[section]` 动态属性，为 `time`、`fft`、`fft_time`、`frf`、`order` 分别配置相邻的蓝灰表面、边线和标题墨色。建议顺序是：

   | 类型 | 表面方向 | 边线/标题方向 |
   | --- | --- | --- |
   | 时域 | 最清的月白蓝 | 最清晰的石蓝 |
   | 频谱 | 稍冷的雾蓝 | 中等石蓝 |
   | 时频 | 微偏青的蓝灰 | 蓝绿灰墨色 |
   | 频响 | 中性钢蓝灰 | 中性蓝灰墨色 |
   | 阶次 | 最浅的雾灰蓝 | 最轻的蓝灰墨色 |

2. 五个 fill 的色相差保持很小、饱和度都低于选中蓝；不得恢复紫、鲜绿、橙、黄等独立类别卡片。标题、计数、chevron 必须在各自背景上满足可读性。
3. `LibraryRowWidget._dot` 继续显示 View 的 `tab_color`，因为它表示 View 身份而非类别。若前台验证发现小点仍显突兀，只允许单独提出“弱化 identity dot”的设计决策，不和本次 section 材质改动捆绑。

### 5. 固化外壳圆角与验证

责任文件：

- `mf4_analyzer/ui/chart_stack/ultraview/chrome.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_ultraview_chrome.py`

1. 继续使用 `CanvasHost.register_overlay()` 的既有 Library 浮层；外层 `QFrame#ultraViewLibrary` 负责完整 1 px 灰线和圆角，内部 head/body 不得覆盖四个角。不要把它改造成新的顶层 popup。
2. 对 macOS popup/rounding 相关改动遵守现有 translucent-shell lesson：若本轮触及顶层 shell，必须检查 `WA_TranslucentBackground` 和 native shadow 标志；若只改已有内嵌 overlay，不能借机扩大到全局 popup 重构。
3. 扩展目标测试：
   - 单层 groups、五个 section 顺序与搜索自动展开；
   - 360 宽度及 800×560、1280×800 的可用几何；
   - 选中行有浮起效果、仅一个 selected、rebuild 后仍正确；
   - grab 图中选中行底部圆角外的 gutter 没有横向非背景线，标题规则仍只位于 header/body；
   - 五个 section 的中心像素/边框像素属于同一蓝灰色域但彼此可区分；
   - 外层四角像素连续、无白色或 native 方框泄漏。
4. 执行顺序：先跑 `tests/ui/test_ultraview_page.py` 与 `tests/ui/test_ultraview_chrome.py`，再跑 `tests/ui_kit/test_qss_duplicate_selectors.py`、`tests/ui/test_import_boundaries.py`、`tests/ui/test_main_window_state_ownership.py`。Qt 命令使用项目 `.venv`、`QT_QPA_PLATFORM=offscreen`、`TMPDIR=/tmp`、`PYTHONPATH=.`。
5. 最后进行真实 macOS 前台检查：选中 View 1 后选择 View 2、收起/展开、输入搜索、拖拽与添加/移除；分别观察内部圆角、外层四角、五个色阶、窄窗口滚动和焦点环。Windows 冻结包是独立后续验收，不以此替代。

## 完成标准

- View 库不再显示“展开 / 概览”两个平行入口；五类 section 的 header 即概览也是展开入口。
- 选中 View 显著但克制地浮在列表上方，选择变化和 rebuild 不丢失。
- View 1 与 View 2 之间没有任何线穿过选中 View 的下圆角；合法的标题规则仍存在且位置正确。
- 五个 section 都可在不显得彩虹化的前提下一眼区分，并与 UltraView 的月白石蓝画布一致。
- 所有焦点测试、像素/几何门禁通过；macOS 前台结果单独记录。
