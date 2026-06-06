# 时域视图 UI 微调（4 项）

日期：2026-06-06
分支：docs/timedomain-view-tabs-plan

## 背景

用户在时域视图（TimeDomain）上提出 4 项交互/视觉调整。经代码核对，其中两项是
样式缺失而非功能缺失。本 spec 记录确认后的最终方案。

## 范围（4 项）

### ① 标签改名无缝化
- 现状：`view_tabbar.py:242` `_begin_inline_rename` 已是内联编辑（双击在标签处
  浮出 `QLineEdit#viewTabRenameEditor`），但 `style.qss` 未给该 objectName 写任何
  样式，于是用 macOS 默认白底+边框，看起来像一个独立浮框。
- 方案：在 `style.qss` 为 `QLineEdit#viewTabRenameEditor` 增加样式——浅蓝底贴合
  选中标签（`#e8f0ff` 一类）、`border-radius: 4px`、`font-size:12px`、
  `font-weight:600`、文字色与内边距与标签对齐；必要时微调
  `_begin_inline_rename` 的 geometry，使编辑框精确覆盖整块标签。
- 验收：双击标签后直接在标签文字上编辑，不再出现独立白色浮框。

### ② 满 6 个 View 时 ➕ 置灰
- 现状：`view_tabbar.py:200` `_update_plus_state` 在 `len(views) >= MAX_VIEWS(=6)`
  时已 `setEnabled(False)`（点击无效），但 `style.qss:1490` 的 `viewTabPlus`
  无 `:disabled` 规则，禁用后视觉仍是亮的。
- 方案：在 `style.qss` 增加 `QPushButton#viewTabPlus:disabled`（灰底/灰边/灰字）。
- 验收：到第 6 个 View 时，➕ 按钮明显变灰且不可点。

### ③ 新增右键「Y 轴自适应」
- 现状：右键已有「查看全部」= X+Y 都恢复到全部数据范围（等同 Home）。
- 方案：在 `pg_canvases.py` 的 `redesign_pg_context_menu()` 新增顶层菜单项
  **「Y 轴自适应」**。点击后：**保持当前 X（时间）范围不变**，把 Y 轴自动缩放到
  当前可见那段波形（overlay/分屏下对每个子图/viewbox 都生效）。优先用 pyqtgraph
  的 `setAutoVisible(y=True)` + `enableAutoRange(YAxis)` 让 Y 只按可见 X 段数据
  自适应。
- 与「查看全部」区分：查看全部 = X+Y 全量；Y 轴自适应 = X 不动、Y 贴合可见波形。
- 验收：放大某段时间后点该项，X 不变、波形纵向填满图面。

### ④ 右键「鼠标操作」放第一 + 新菜单顺序
- 方案：在 `redesign_pg_context_menu()` 重排顶层顺序为：
  `鼠标操作 · Y 轴自适应 · 查看全部 · X 轴范围 · Y 轴范围 · 网格`

### ④b 鼠标操作改为右键第一行内嵌图标切换（2026-06-07 迭代）
- 现状不满意：「鼠标操作」是二级子菜单，操作层级深。
- 方案：删掉「鼠标操作」子菜单，改为在右键菜单【第一行】内嵌一个分段切换控件
  （`QWidgetAction` 承载含两个 **只显示图标**、互斥 `QToolButton` 的小部件）：
  框选 + 平移。
  - 图标复用顶部 toolbar 的 qtawesome 图标：框选 `mdi.magnify-plus-outline`、
    平移 `mdi.cursor-move`；激活色 `#2563eb`、未激活 `#374151`（与 toolbar 一致）。
  - 选中态进菜单时读 `controller.current_mouse_mode()`（zoom→框选高亮，否则→平移）。
  - 点击调 `controller.set_zoom_mode()/set_pan_mode()` → 顶部 toolbar 自动同步
    （`mouse_mode_changed` 信号链已确认）；菜单每次重建会读当前模式，故双向联动。
  - 点完关闭菜单。
- 新顶层顺序：`[框选 | 平移 切换行] · Y 轴自适应 · 查看全部 · X 轴范围 · Y 轴范围 · 网格`

## 涉及文件
- `mf4_analyzer/ui/view_tabbar.py`（①，可能微调 geometry）
- `mf4_analyzer/ui_kit/style.qss`（①②）
- `mf4_analyzer/ui/pg_canvases.py`（③④，`redesign_pg_context_menu()` 等）

## 注意事项
- 该分支已知 UI 文件存在同名方法重复定义（最后一个生效）；定点改前先核对/去重。
- 改完需真机截图验证：置灰、无缝编辑框、菜单顺序、Y 轴自适应行为。

## 执行
4 项均由 `pyqt-ui-engineer` 专家实现，不涉及数值算法。
