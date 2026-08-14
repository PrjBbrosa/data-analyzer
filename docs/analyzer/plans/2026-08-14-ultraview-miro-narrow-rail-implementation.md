# UltraView Miro 式窄轨浮岛工作区 Implementation Plan

日期：2026-08-14

状态：**READY FOR REVIEW；窄轨方向已确认，但尚未授权执行产品源码修改**

Spec：[2026-08-14-ultraview-miro-narrow-rail-spec.md](../specs/2026-08-14-ultraview-miro-narrow-rail-spec.md)

视觉参考：[2026-08-14-ultraview-miro-layout-options.html](../ui-prototypes/2026-08-14-ultraview-miro-layout-options.html)，只实现 B · 窄轨按需

## 0. 执行原则

1. 先冻结当前能力和 geometry，再迁移入口；每个任务先写 RED。
2. 只重排 UltraView UI，Board mutation 继续通过 UltraViewPage signals → UltraViewCoordinator 的现有单写点。
3. 不改 UltraView schema、UltraViewRef、PreviewStore、sidecar、compositor 或分析 job 路径。
4. 不保留“脱离布局但仍可见”的旧兼容 widget。若暂留兼容对象，必须显式 hide，并有 isVisibleTo 断言。
5. HTML 定义信息架构和视觉目标；真实 PyQt 字体度量、窗口 chrome、拖放时序和现有功能合同优先。
6. 不把当前 P3 review 中的视口/FOCUS 缺陷包装成 UI 改版成果。重叠缺陷若阻塞本包，单独 RED、单独提交、单独说明。

## 1. 预计文件范围

### 1.1 主要修改

- mf4_analyzer/ui/chart_stack/ultraview/page.py
- mf4_analyzer/ui/chart_stack/ultraview/widgets.py
- mf4_analyzer/ui/chart_stack/ultraview/__init__.py
- mf4_analyzer/ui_kit/icons.py
- mf4_analyzer/ui_kit/style.qss
- mf4_analyzer/ui/hints.py
- mf4_analyzer/ui/quickref.py
- tests/ui/test_ultraview_page.py
- tests/ui/test_ultraview_viewport.py
- tests/ui/test_ultraview_mode_integration.py
- tests/ui/test_ultraview_job_isolation.py
- tests/ui/test_ultraview_export.py
- tools/verify_ultraview_visuals.py

### 1.2 建议新增

- mf4_analyzer/ui/chart_stack/ultraview/floating_layout.py
  Qt-free rect 计算和小窗口碰撞规则，不持有 QWidget。
- mf4_analyzer/ui/chart_stack/ultraview/chrome.py
  BoardIsland、ToolRail、GlobalIsland、NavigationIsland、CardContextIsland 和弹层宿主。
- tests/ui/test_ultraview_floating_layout.py

如果实现中证明 widgets.py 内小改更清晰，可以不新增 chrome.py；但不得把 page.py 扩成另一份 1000 行控件实现。Page 继续负责组合与信号路由，presentation widget 归 widgets/chrome。

## 2. 动工 Gate

### Gate 1：工作区与基线

执行前记录：

~~~bash
git status --short --branch
git log -1 --oneline
git diff --check
~~~

起草时工作区已有未跟踪 reviews/UI prototypes，并在起草期间出现 free_grid.py、gesture.py、layouts.py、viewport.py、widgets.py 的并行未提交 correctness 修改。本计划没有改动这些源文件。执行提交只纳入对应 Task 明确拥有的差异；先辨明并行修改的 owner/commit，不覆盖、不回退，也不把它们误算成本 UI 改版产物。

### Gate 2：现有 focused suite

先用当前 HEAD 运行并记录：

~~~bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_layouts.py \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_viewport.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_export.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_ultraview_project_session.py \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_ultraview_preview_store.py \
  tests/ui/test_ultraview_preview_sidecar.py \
  tests/ui/test_ultraview_entry.py \
  tests/ui/test_ultraview_probes.py -q
~~~

异常退出、超时或 segfault 一律记 UNVERIFIED。

### Gate 3：重叠 P3 缺陷

当前 review 已登记 Board 切换 viewport 污染、模板缩小无效、卡到托盘回归等问题。本包不自动获得修复授权，但要在 Task 0 做现状 characterization：

- 若缺陷仍存在且与新浮岛 geometry 无关，登记 baseline，不在本包顺手修。
- 若缺陷使 A03/A10/A11 无法验收，先提一个窄修复提交，提交信息明确“pre-existing correctness prerequisite”，不要混在视觉提交。
- 高危 correctness 红未关闭时，不得仅凭窄轨截图宣告整个 UltraView 可合入。

## 3. 任务顺序

~~~text
Task 0 现状冻结与 parity 矩阵
  ├── Task 1 Qt-free 浮岛 geometry + CanvasHost
  │     ├── Task 2 BoardIsland + ToolRail + View 库浮层
  │     ├── Task 3 布局/筛选/显示/导出弹层
  │     └── Task 4 未放置 + 状态 + 导航 + 演示
  ├── Task 5 卡片上下文工具条
  └── Task 6 icon/QSS/帮助/视觉验收
                         ↓
                 Task 7 零计算与全套收官
~~~

## Task 0 — 冻结操作等价、当前 geometry 和已知红

### RED

在 tests/ui/test_ultraview_page.py 或新测试中先建立动作清单，断言当前 Page 可以发出以下 intent：

- Board create/select/duplicate/rename/delete/reorder/name change
- layout/free-grid/organize/undo/redo
- compare filter
- show titles/show sources
- copy board/export 1×/2×/presentation
- add/remove/locate/replace/place/move-to-unplaced
- open source/focus/copy card/free-grid preset
- zoom in/out/fit/reset/overview/minimap

增加当前 geometry probe：

- 1280×800：记录 library、switcher、toolbar、rail、scroll、tray、hint 的 page-relative rect。
- 800×560：断言当前最小宽问题被 characterization，而不是把错误尺寸写成未来期望。

把 HTML B 的每个 visible action 与现有 signal/state transition 做一一表；spec §8 的九项产品修正必须进入 checklist。

### GREEN

- 只加 characterization 和测试 helper，不改 UI。
- 更新 tools/verify_ultraview_visuals.py，使它可以输出 page-relative geometry JSON；此时仍渲染旧 UI。

### 验证

~~~bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_viewport.py \
  tests/ui/test_ultraview_mode_integration.py -q
~~~

## Task 1 — 浮岛 geometry 与连续 CanvasHost

目标：先替换占位结构，不迁移行为。

### RED

新增 tests/ui/test_ultraview_floating_layout.py：

1. 输入 1280×800，输出 rail、board、board island、global island、status island、nav island rect；所有 rect 在 stage 内且互不冲突。
2. 输入 800×560，常驻控件不重叠，board rect 不低于 710×470。
3. 1280×800 board rect 不低于 1190×700。
4. overlay panel 打开/关闭时 board rect 完全相同。
5. CardContextIsland 靠近顶部、右侧、底部卡片时自动翻转或 clamp，不越界。
6. NavigationIsland 与 minimap rect 冲突时，minimap 上移或折叠，二者不遮挡。
7. 非法/极小尺寸返回 bounded rect，不出现负宽高。

### GREEN

- 新增 floating_layout.py 的 immutable DTO 与纯函数。
- UltraViewPage 从 QSplitter + BoardColumn 垂直流改为单一 CanvasHost。
- BoardScrollArea 成为 CanvasHost 的主内容；浮岛和弹层都是它的 sibling overlay。
- ViewLibraryPanel、CompareRail、UnplacedTray 暂时仍是原类，只改变 parent/geometry，不改变 signal。
- 移除 BoardSwitcher/BoardToolbar/CompareRail/Tray/Hint 对主 QVBoxLayout 的永久占位。
- CanvasHost resizeEvent 只调用纯 rect 计算；不在 paint/resize 中触发 Board mutation 或 preview capture。
- BoardScrollArea viewport resize 仍只接现有 grid/free-grid/minimap geometry 更新。

点阵背景：

- 由 CanvasHost 或透明 scroll viewport 的缓存 tile 绘制。
- tile 只在 DPR/palette 改变时重建，不能每帧生成整板图片。
- 不改导出 compositor 背景；点阵是 UI chrome，不进入 PNG。

### 兼容纪律

- page.library_panel、board_switcher、board_toolbar、compare_rail、unplaced_tray、hint_bar、board_scroll_area 访问器在本任务继续可用。
- 不把旧 splitter 留在对象树中作为未布局可见 widget。
- 如果工具脚本或测试依赖 objectName，先保留 objectName；新 objectName 另加，不用同一功能两个名字并存。

### 验证

- UV-NR-A01、A02、A03 geometry RED 转绿。
- 原 focused tests 除明确的结构断言更新外保持绿。

## Task 2 — BoardIsland、ToolRail 与 View 库浮层

### RED：Board

1. 当前 Board 名称正确投影并 elide，tooltip 保留全名。
2. 点击名称打开 Board 菜单；方向键/Enter 切换。
3. 20 个 Board 时菜单可滚动、当前项可见、新建禁用理由可读。
4. 拖动菜单项发 reorder_requested；重建 Board 列表不得发生在拖动回调栈内。
5. 上移/下移键盘等价路径发同一个 reorder_requested。
6. 复制、重命名、删除发既有 typed intent；删除仍确认。
7. F2/双击当前名称走 board_name_changed 或 rename_requested 的唯一既有协调路径。

### RED：View 库

1. 页面初次打开 library_open 为 false，ToolRail 库图标未 active。
2. 点击图标打开库；board_scroll geometry/zoom/center/scroll 不变。
3. Esc 和点击画布关闭后焦点回触发按钮。
4. 分组、搜索、折叠、添加、移出、定位现有测试在浮层宿主下仍绿。
5. 拖放开始后请求关闭库：源 widget 活到 drag_finished，之后才关闭。
6. presentation 进入时记录 library 状态并隐藏；退出精确恢复。

### GREEN

- BoardSwitcher 内部改成紧凑 BoardIsland/BoardMenu；保持已有 signals。
- ToolRail 建立 View、布局、筛选、未放置四个图标和分隔。
- ViewLibraryPanel reparent 到 CanvasHost overlay，不再由 splitter 分配宽度。
- active_panel 和 library_open 由 UltraViewPage 单一拥有；ToolRail 只发 intent。
- 所有按钮使用 QToolButton icon-only、tooltip、accessibleName、TabFocus。
- Board 菜单使用当前 rounded menu/popover 机制；列表排序不可在 QDrag.exec_ 或 QTabBar tabMoved 等嵌套回调里同步重建。

### 明确更新的旧测试

- “library 默认 visible”改成“rail 默认可见、library 默认关闭”。
- presentation 退出恢复的是进入前状态，不固定断言 true。
- BoardSwitcher 的 QTabBar 内部结构测试替换为功能测试；Board CRUD/reorder 信号合同不变。

### 验证

- UV-NR-A03、A04、A13、A14。
- 复跑 library rebuild deferred tests 和 Board reorder nested-event-loop tests。

## Task 3 — 布局、筛选、显示和导出弹层

### RED：布局

1. 弹层展示 LAYOUT_SLOTS 的八项，顺序和 LAYOUT_LABELS_ZH 一致。
2. 当前模板有选中态；切换发 layout_changed 一次。
3. 自由网格入口发 free_grid_toggled；切回模板确认取消时 UI checked state 恢复。
4. 自由网格状态下显示整理、Undo、Redo；模板状态隐藏或禁用，并有原因 tooltip。
5. 4→12 回填、12→4 溢出及 toast 保持当前合同。

### RED：筛选

1. 五项 COMPARE_FILTERS 全部存在，包括 time_freq。
2. 筛选只改变 dimmed 投影，不改变 board payload、card order 或 geometry。
3. active 图标状态在关闭弹层后仍可见。
4. axis_consistency_facts 产生单位/范围 warning 时，弹层文案和漏斗 warning dot 同步。
5. 无 warning 时不编造“几组一致”的数量。

### RED：显示与导出

1. 显示弹层只有标题、来源两个持久开关。
2. stale/missing/orphaned 状态标签不受显示弹层影响。
3. 导出弹层三个动作分别发 copy_board_requested、export_png_requested(1/2)。
4. 超限导出继续走现有 ComposeError/toast 文案。

### GREEN

- BoardToolbar 从永久横栏改成行为 façade/浮岛组合；不再含永久 name input、layout combo 和 zoom cluster。
- CompareRail 保留 signal/filter API，但作为筛选弹层内容，不再是一整行。
- 布局 popover 使用真实八模板缩略图；自由网格选项不伪装成第九个 template layout_id。
- Display/Export 属于右上 GlobalIsland；presentation 按钮单独保持高识别度。
- active 动态属性使用字符串 true/false，并为 hover/pressed/focus 写完整 QSS。
- 不引入 show_status、schema bump 或新 coordinator state。

### 验证

- UV-NR-A05、A06、A07、A08、A17。
- test_compare_filter_and_axis_warnings_do_not_mutate_board
- test_board_toolbar_display_menu_emits_show_flags 的语义更新版
- test_compose_board_fixed_sizes_and_show_flags
- test_full_ultraview_export_sequence_stays_zero_compute

## Task 4 — 未放置、状态、导航、概览/minimap 与演示

### RED：未放置

1. badge 与 board.unplaced 长度一致，0 时不显示数字。
2. 项目恢复已有 unplaced 不自动打开。
3. 手动 move-to-unplaced 只 toast + badge。
4. 模板缩容 12→4 首次产生新 overflow 时自动打开并聚焦首项。
5. place/remove/rebind/locate/drag/drop 全部从浮层工作。
6. 浮层最多指定高度后内部滚动，不推动 BoardScrollArea。

### RED：StatusIsland

1. “?”仍发 quickref_requested。
2. 常态包含“只读”与“不计算”。
3. 状态文案 elide，但 accessibleName/tooltip 保留完整内容。
4. 页面 hints 仍能投影，不需要 28 px 全宽占位。

### RED：NavigationIsland

1. 五个现有 zoom 控件和 overview 均存在；25%～200% 与 label 同步。
2. fit 和 100% 是独立动作。
3. 自由网格 minimap 可点击定位，且与 nav island 不重叠。
4. BoardOverview 可打开、点击 template slot/free-grid ref 返回阅读位置。
5. 关闭/重开弹层不改 viewport payload。

### RED：演示

1. 进入后 BoardIsland、ToolRail、Global 编辑动作、StatusIsland、CardContextIsland、打开弹层和 unplaced 内容都隐藏。
2. 保留退出演示按钮；Esc 可退出。
3. 9/12 图与自由网格继续按当前规则显示 overview。
4. 退出后 library/panel/tray 展开状态精确恢复。
5. 主窗口 Inspector 不被隐藏，独立 UltraViewSheet 仍可与 Analyzer 并行。

### GREEN

- UnplacedTray reparent 为 tool-rail 触发的 overlay。
- 删除 set_board 中“0→正数一律展开”的全局规则，替换为 mutation reason 驱动的明确策略；若 coordinator 目前没有 reason，Page 通过前后 membership/unplaced delta 加一次性 overflow marker，不修改持久化。
- UltraViewHintBar 改为紧凑 StatusIsland；保留 hint_bar accessor 和 quickref signal，更新 objectName/测试时优先保持语义兼容。
- zoom 控件与 overview 从 BoardToolbar 搬到 NavigationIsland，signal 仍接 page.zoom_in/out/fit/reset/show_overview。
- minimap 继续是 BoardScrollArea viewport 子项，但位置由 floating layout 协调。
- presentation 不调用 setVisible 后遗留错误状态；所有浮层先 close，再隐藏 chrome。

### 风险

若“缩容自动打开”依赖 layout mutation 的来源，不能用“unplaced 数量变大”粗略推断所有场景。先追踪 _on_layout → set_layout warnings；优先用既有 warning/intent 传递显式 overflow count，避免 Board 切换误触发。

### 验证

- UV-NR-A09、A10、A11、A19。
- test_overflow_tray_is_visible_and_persisted 改为 badge/panel 语义。
- test_board_overview_click_returns_to_reading_slot
- test_free_grid_projects_cards_preserves_scroll_and_emits_keyboard_geometry
- test_presentation_does_not_hide_main_inspector

## Task 5 — 卡片上下文工具条与操作等价

### RED

1. 无选择时不显示；选择一张卡后出现并锚定该卡。
2. 顶部空间不足时工具条翻到卡片内上缘或下方，不越出 CanvasHost。
3. 开原 View、临时放大、复制图像、移到未放置各发既有 signal 一次。
4. “更多”保留替换、从总览移除和全部六个尺寸预设。
5. orphaned 卡仍显示 inline rebind/remove，不被工具条遮挡。
6. 右键菜单全部动作继续可用。
7. 双击 zoom-to-card/focus 现有行为不回归。
8. 24 卡只创建一个上下文工具条，不给每卡创建 shadow/popover。
9. zoom、scroll、resize、Board switch、卡片删除后位置刷新或隐藏，不持有已删除 QWidget。

### GREEN

- 新增 CardContextIsland，由 Page 根据 UltraViewRef 查询当前 card geometry。
- 工具条只持 UltraViewRef，不持久持有 card wrapper；每次重定位前用 card_for 查询。
- 先保留卡头 focus button；上下文工具条与真机验收通过后，在同一 Task 后半移除永久按钮并更新 geometry test。
- 右键菜单作为完整后备入口，不为追求极简删除。
- 自由网格 handles/ghost overlay z-order 高于卡片，CardContextIsland 在非手势状态高于卡片；进入 move/resize 时工具条隐藏，结束后恢复。

### 验证

- UV-NR-A12、A14。
- 现有 test_menu_double_click_and_keyboard_share_intents
- card focus geometry 测试改为上下文工具条 geometry/pixel 检查
- free-grid move/resize/group/replace-ring 测试全绿

## Task 6 — Icons、QSS、帮助与渲染矩阵

### RED：Icons/QSS

1. rail/layout/filter/unplaced/display/export/presentation/overview/fit/100/card actions 使用真实 QIcon，不用文字 glyph。
2. idle、hover、pressed、checked/active、disabled、focus、presentation 状态截图可区分。
3. active 状态经过 hover 不丢失；idle pressed 不伪装成 active。
4. 浮岛圆角外四角像素不漏矩形底。
5. 800×560、1280×800、1440×900 无重叠、裁切或弹层越界。
6. library、layout、filter、unplaced、board menu、card context、presentation 七个主状态各有截图。
7. prefers-reduced-motion 在 Qt 中对应“无非必要动画”或系统动画禁用；不要求照搬 CSS。

### GREEN

- 在 mf4_analyzer/ui_kit/icons.py 补齐 UltraView line icons；优先复用 eye_open、export、expand_focus、copy_image、menu、panel_left、mode_ultraview。
- style.qss 新增统一 role/property selector；禁止 border 简写覆盖 radius。
- 浮岛 shadow 只挂固定数量宿主；24 卡不得新增 per-card effect。
- 选中卡使用边线 + 外环；筛选弱化继续保留当前 opacity 语义，修复时不要让手势结束清掉 dim。
- 更新 tools/verify_ultraview_visuals.py 产出三尺寸 × 七状态图和 geometry JSON。

### 帮助同步

更新 mf4_analyzer/ui/hints.py、mf4_analyzer/ui/quickref.py 和 UltraView help：

- “顶栏多个 Board 标签”改为“左上 Board 菜单”。
- “工具栏显示/概览/缩放”改为右上/右下浮岛。
- “底部托盘”改为左轨未放置。
- 增加 View 库默认收起、布局/筛选弹层、卡片上下文工具条。
- 保留只读、直接操纵、替换环、自由网格、minimap、overview、Esc 和零计算说明。

### 验证

~~~bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_viewport.py -q
~~~

再在 macOS Cocoa 前景运行视觉工具，保存截图和 page-relative geometry；offscreen 结果只用于排版草稿。

## Task 7 — 零计算、边界门禁与收官

### 零计算序列

为下列完整序列增加/扩展 probe：

1. 打开 UltraViewSheet。
2. 开关 View 库。
3. 切 Board。
4. 开关 layout/filter/display/export/unplaced/board 菜单。
5. 切筛选。
6. 切模板/自由网格、整理、Undo/Redo。
7. zoom/pan/fit/100%/overview/minimap。
8. 进入/退出演示。
9. 复制单卡、复制整板、导出 1×/2×。
10. 保存项目。

analysis compute、job submission、store-write 计数必须为 0；preview QImage 缩放、PNG decode/encode 和 clipboard 不算分析计算，但仍应保持可观察失败。

### Focused 与边界门禁

~~~bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_layouts.py \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_viewport.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_export.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_ultraview_project_session.py \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_ultraview_preview_store.py \
  tests/ui/test_ultraview_preview_sidecar.py \
  tests/ui/test_ultraview_entry.py \
  tests/ui/test_ultraview_probes.py -q
~~~

~~~bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_import_boundaries.py \
  tests/test_signal_no_gui_import.py \
  tests/test_batch_render_import_boundary.py \
  tests/test_native_import_boundaries.py \
  tests/test_packaging_imports.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py -q
~~~

### 全套

按仓库两进程合同运行：

1. 主套件忽略 tests/acquisition_ui。
2. tests/acquisition_ui 单独新进程。

任何异常退出均为 UNVERIFIED，不从已完成的测试数量推断通过。

### 真机

macOS Cocoa 必验：

- UltraViewSheet 800×560、1280×800、1440×900。
- Retina DPR。
- View 库拖放、未放置拖放、Board 菜单排序。
- 卡片直接移动/resize、替换环、context island 定位。
- 连续 zoom/pan、minimap、overview、presentation。
- 圆角、阴影、active/focus/disabled 像素。
- 24 卡下打开/关闭浮层不出现明显掉帧。

Windows frozen 验收只有在发布任务包含 Windows 时执行；不得用 source/offscreen 结果替代。

## 4. 建议提交序列

1. test(ultraview): freeze narrow-rail operation parity and geometry
2. refactor(ultraview): introduce floating canvas host and pure chrome geometry
3. feat(ultraview): compact Board island and on-demand View library rail
4. feat(ultraview): move layout filter display and export into scoped popovers
5. feat(ultraview): float unplaced status navigation and presentation chrome
6. feat(ultraview): add selected-card context toolbar without dropping menu actions
7. style(ultraview): align icons QSS hints and rendered visual states
8. test(ultraview): close zero-compute regression and platform verification

每个提交只拥有对应任务文件。若 Gate 3 需要 correctness prerequisite，放在提交 1 和 2 之间单独提交，不夹在 style commit。

## 5. 验收 ID → Task

| 验收 | Task |
|---|---|
| A01/A02 | 0、1 |
| A03 | 1、2、3、4 |
| A04 | 2 |
| A05/A06/A07/A08 | 3 |
| A09/A10/A11 | 4 |
| A12 | 5 |
| A13 | 2、4、5 |
| A14 | 2～6 |
| A15/A16 | 7 |
| A17/A18 | 6 |
| A19 | 4、7 |
| A20 | 6、7 |

## 6. 最终 Checklist

- [ ] 只实现 B · 窄轨按需，没有把 A/C 方案带进产品设置。
- [ ] BoardScrollArea 达到 spec 的两档最小可见面积。
- [ ] View 库和所有弹层不 reflow Board。
- [ ] Board CRUD/reorder/name/limit 无功能损失。
- [ ] 八模板 + 自由网格 + organize + undo/redo 无功能损失。
- [ ] 五类筛选 + axis warning 无功能损失。
- [ ] show titles/sources 保留，未增加 show_status。
- [ ] copy/export/presentation/zoom/overview/minimap 全部可达。
- [ ] unplaced 全动作保留，缩容时不会让用户误以为卡片丢失。
- [ ] 卡片动作和尺寸预设全部有等价入口。
- [ ] QDrag 源生命周期测试转绿。
- [ ] schema/digest/PreviewStore/sidecar/compositor 不变。
- [ ] hints/quickref/help 与新入口同步。
- [ ] 三尺寸七状态渲染截图已人工检查。
- [ ] Cocoa 前景与 offscreen 证据明确分开。
- [ ] focused、边界、两进程全套结果如实记录。
- [ ] git diff --check 通过，提交范围无无关 dirty 文件。
