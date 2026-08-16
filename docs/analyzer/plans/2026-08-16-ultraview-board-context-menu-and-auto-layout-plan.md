# UltraView 看板右键菜单与自动排版实施计划

状态：提案，尚未改产品代码  
输入：2026-08-16 用户确认——菜单首项为**看板级「适应内容」**；保留“复制为图片”“导出 PNG 1×”；新增“自动排版”必须另做算法；菜单与单文件时域的轻量右键表面一致，但所有动作一层直达。  
交互稿：[2026-08-16-ultraview-board-context-menu.html](../ui-prototypes/2026-08-16-ultraview-board-context-menu.html)

## 1. 决策与边界

### 1.1 菜单的触发面

- 只在 UltraView **画布空白处**右击出现；卡片右击继续走其已有的局部菜单，Board 名称行也继续走 Board 管理弹层。
- Page 的 viewport 事件路径拥有这个入口。`ViewportGestureRouter` 不接管 `ContextMenu`，因此不能为实现菜单而改动 Space/中键平移、Ctrl/Meta-wheel、pinch 或框选事件。
- overview、presentation、拖拽/resize/框选活跃期间不弹出菜单；Esc 与现有 popup 优先级保持一致。
- 菜单是一个普通、平铺的 `QMenu`；没有 `addMenu()`、没有二级 action、没有 `QWidgetAction` 控制面板。

### 1.2 首发菜单（固定顺序）

```text
适应内容
恢复 100%
查看整板概览
──────────
自动排版                         仅自由网格、至少两张已放置卡片
撤销自动排版                     仅最近一次自动排版仍在 undo 栈顶时
──────────
复制为图片
导出 PNG 1×
```

- “适应内容”复用 `UltraViewPage.zoom_fit()`：仅调整 Board 相机，按已放置卡片的包围盒居中填满安全区；**不**改任何 `GridRect`。
- “复制为图片”复用现有 1× `copy_board_to_clipboard()`；“导出 PNG 1×”复用 `choose_and_export_png(1)`。不在本菜单增加 2×、PDF 或 SVG。
- “恢复 100%”和“查看整板概览”复用已有导航级动作，作为右键的就近入口，不新增状态。
- 不加入“同步全部”：它是来源变化时的条件性抓图动作，现有窄轨入口已经带 stale 语义；没有真实 stale 状态时放入全局常驻菜单会制造无效动作。
- 不加入 View 库、切换模板、显示偏好、演示模式、卡片打开/替换/移除。这些要么需要二次选择，要么是卡片/浮层的专属责任，违反本菜单的“一键整板动作”定位。

### 1.3 两个“适应”不得混名

| 名称 | 作用对象 | 现有/新增 |
| --- | --- | --- |
| 适应内容 | 看板相机：缩放并居中内容 | 已有 `UltraViewPage.zoom_fit()` |
| 按原图比例 | 单卡 `GridRect` 尺寸 | 已有自由网格卡片动作 |
| 自动排版 | 全部自由网格卡片的位置 | 本计划新增 |

“自动排版”绝不叫“全局 AutoFit”，避免误解为逐张按原图比例；它也不是现有“整理空行”。`organize_free_grid()`仅删除完全空的行、保留列与 span，不能满足重新排布的意图。

## 2. 自动排版算法合同

### 2.1 用户可见语义

- 仅自由网格可用，模板布局中不显示（或不创建）此 action。
- 每张卡片**保留**当前 `column_span` 和 `row_span`，即不改变用户已经调整好的尺寸或原图比例。
- 按当前阅读顺序 `(row, column, 原列表序号)` 稳定排序，重新从左上开始紧凑排入 12 列基准网格。
- 一次点击产生**一个** `BoardPlacementSnapshot` 历史条目；`Cmd/Ctrl+Z` 和 `Cmd/Ctrl+Shift+Z` 仍能完整恢复/重做全部受影响卡片。
- 已经紧凑、少于两张卡片或无法在安全网格内合法排入时不写状态：前两种给 info toast，后一种给可操作 warning。没有部分提交、没有逐卡 toast。
- 不读取预览、不重算分析、不改变 `PreviewStore`、不改变未放置托盘、不会自动切换 Board。

### 2.2 纯函数方案

在 `mf4_analyzer/ui/chart_stack/ultraview/free_grid.py` 新增 `plan_auto_arrange(...) -> LayoutPlan`，不把算法塞入 QWidget 或 coordinator。

1. 输入 `Sequence[FreeGridPlacement]`、当前 `layout_revision`，验证 ref 唯一、rect 合法、span 在已有范围内。
2. 用 `(rect.row, rect.column, input_index, ref.section, ref.view_id)` 得到稳定阅读序列；最后两项只处理完全相同位置的确定性。
3. 对每张卡片保持 span 不变，从安全工作区左上角开始，按 `row`、再按 `column` 扫描第一个不与已排卡片相交的合法 `GridRect`。扫描受 `SAFETY_*` 行列边界限制。
4. 将所有 changed ref 作为 `RectTransition` 写入一个 `LayoutPlan(operation=LAYOUT_ARRANGE, mover_ref=None)`；`LayoutPlan.committed_updates()`已允许无 mover 而提交 transitions。
5. 任何输入不合法、找不到合法槽位、或计划内出现重叠时返回 rejected plan，调用方不改变 board。

不要通过现有 `plan_layout(..., LAYOUT_ARRANGE)`拼装全局排版：该路径的 fallback 是 `plan_neighbor_shrink()`，其可缩小邻卡，不符合“保留当前尺寸/比例”的产品合同。也不要复用 `organized_placements()`，它只压缩空行。

## 3. 实施顺序

### Task 0 — 冻结现状与入口 characterization

- 记录 card 右键、Board 行右键、画布空白右键的真实事件接收者；补充 regression，证明右击卡片不触发 board 菜单。
- 在 `tests/ui/test_ultraview_page.py` 增加画布 context-menu 事件的 route characterization；覆盖 free-grid/template、overview/presentation、活跃拖拽与 Esc。
- 读/更新交互稿，不改产品功能。

### Task 1 — 先实现并锁定自动排版纯算法

- 由 `free_grid.py`拥有 `plan_auto_arrange` 与必要的小型私有扫描 helper；不得导入 Qt。
- 新增 `tests/ui/test_ultraview_free_grid.py`：
  - 同一输入连续执行结果完全相同；
  - 输出 ref 集合、每张 span、合法边界均不变；
  - 输出任意两张不重叠，首张从左上优先；
  - 分散布局明显变紧凑，重复执行幂等；
  - 无法布局/非法输入 rejected 且输入不被修改。
- 这一步不接 UI、也不改变保存格式。

### Task 2 — coordinator 原子提交与历史

- `UltraViewCoordinator`新增单一 `_on_auto_arrange_free_grid()`：取 active Board、创建 `before` snapshot、执行纯 plan、一次 `set_free_grid_rects()`、一次 `_commit_grid_change()`。
- 仅当 plan 有 changes 时记录一条历史；no-op 走 page feedback，不建立空 undo。
- 复用现有 undo/redo、pending aspect cancel 和 `_after_board_mutation()`；不要新增第二套 history。
- 覆盖一次排版→undo→redo 的全部 placements 精确回环，以及 job-isolation（零计算）回归。

### Task 3 — Page 单层 QMenu 与信号接线

- `UltraViewPage`拥有菜单构建、enabled/visible matrix 与 action-to-intent；增加 typed `auto_arrange_requested`，由 coordinator 接线。
- 在 Page 已监听的 `_board_scroll.viewport()`路径识别 `QEvent.ContextMenu`。命中空白内容才打开 `ultraViewBoardContextMenu`；卡片自己的 `contextMenuEvent()`优先。
- 复用 `apply_rounded_menu_chrome(menu)`，但不传 check/submenu gutter；新增局部 QSS 使密度与 `#pgContextMenu`一致（14px shell、30px action、浅蓝 hover），不影响全局 QMenu。
- 所有 action 每次弹出时按状态生成：模板/空板不出现自动排版，history 顶部不是排版时不出现“撤销自动排版”。
- `copy_board_requested`、`export_png_requested.emit(1)`、`zoom_fit()`、`zoom_reset()`、`show_overview()`沿用现有路径。菜单关闭后不保留 QWidget/QMenu 引用，不污染 selection。

### Task 4 — 发现性与视觉验收

- 更新 `mf4_analyzer/ui/hints.py` 和 `mf4_analyzer/ui/quickref.py`：说明“画布空白右击”的位置，明确“自动排版保留尺寸、可撤销”，并区分“整理空行”。
- 更新 `mf4_analyzer/help/ultraview-guide.html`与帮助契约；不回写历史 specs/plans。
- 扩展 `tools/verify_ultraview_visuals.py`：至少输出 1280×800/800×560 的空白右键菜单、自动排版前后、卡片右键不串到 Board 菜单三张图。
- macOS Cocoa 前景手测：右击定位、关闭、Esc、Space/middle-pan/框选不受影响、自动排版一次 undo、图片复制、1× PNG save dialog、Retina 圆角/hover。离屏 Qt 只能作为结构检查。

## 4. 验证命令

先跑 owner tests，再跑边界：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_chrome.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py -q

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py -q
```

交付前另做真实前景 TraceLab 验收；不得用 HTML、offscreen 或历史测试数代替该验收。

## 5. 不在本计划中

- 卡片右键“自由网格尺寸”的既有二级菜单扁平化；这是另一项局部 card-UX 决策。
- “全部按原图比例”批量改尺寸；它与自动排版不同，需要另一套批量碰撞/预演合同。
- Board 注释、箭头、跨卡关联、导出 2×/PDF/SVG、布局模板的自动选择。
