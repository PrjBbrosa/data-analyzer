# UltraView 接缝加固 · Task 0 清查

- 重锚日期：2026-08-16
- 代码锚点：`f85f2323`（本分支创建点）
- 范围：`mf4_analyzer/ui/chart_stack/ultraview/`、
  `mf4_analyzer/ui/main_window/ultraview_coordinator.py` 与 `tests/ui/test_ultraview_*.py`。
- 方法：对源码 AST 做了定向扫描；下列行号是 Task 0 的稳定定位，后续任务以符号名为准。

## §1 · 函数锚点

| 接缝 | Task 0 锚点 |
| --- | --- |
| D1 刷新根 | `UltraViewCoordinator.refresh_page` `:1200`；`_push_preview` `:1284`；`UltraViewPage.apply_preview_and_status` `:1716`；`_prune_runtime_caches` `:1756` |
| D3 视口 | `UltraViewPage._persist_viewport_to_board` `:1064`；直接写 `:1069`；`viewport_changed` `:224`；`_on_viewport_changed` `:719` |
| D4 路由 | `_page_of` `widgets.py:144`；五处 move 转发 `:2286/:2722/:2910/:3364/:3897`；`_cancel_board_gestures` 位于 page 生命周期路径 |
| D5 缩放 | `_grid.set_zoom` / `_free_grid.set_zoom` 配对位于 `page.py:1089-90, 1163-64, 1240-41, 1370-71` |
| D6 捕获 | `_iter_viewboxes` `ultraview_coordinator.py:183` |

规格中随在途库几何批漂移的行号已标注为 Task 0 重锚；本表是本批唯一的行号依据。

## §2 · D0 冻结表（白名单只能缩小）

### U1 · 模型 mutator 集合

运行时依据「接受 `board` 或 `workspace` 且是布局/成员/Board 生命周期写入函数」加既有
workspace 写入器得到下列冻结集合。`empty_slots()` 虽然返回 `list[str]`，但它是纯查询，
不属于 mutator。

```text
add_ref, apply_free_grid_preset, create_board, delete_board, duplicate_board,
free_grid_to_template, mark_workspace_mutated, move_to_unplaced, nudge_ratio,
organize_free_grid, place_free_grid_from_unplaced, place_from_unplaced,
rebind_ref, remove_ref, rename_board, reorder_board, replace_free_grid_ref,
replace_slot, set_active_board, set_free_grid_rect, set_free_grid_rects,
set_layout, set_ratio, set_workspace_preview_sidecar, swap_slots,
template_to_free_grid
```

`page.py` / `widgets.py` / `chrome.py` 对该集合的调用：**0**。

视图层模型字段写：`page.py:1069 self._board.viewport = ...` **1 条**；Task 3 目标 0。

### U1b · 模型字段在 state 模块外的写入

按接收者的实际模型类型筛除其他模块同名的普通字段后，当前白名单为：

```text
ultraview_coordinator.py:1703 board.name
ultraview_coordinator.py:1879 active_board(...).show_titles
ultraview_coordinator.py:1883 active_board(...).show_sources
page.py:1069 self._board.viewport
```

Task 3 目标：空集合。

### U2 · page 无反向引用

`page.py` / `widgets.py` / `chrome.py` AST 未发现 `coordinator`、`_ultraview`、`MainWindow`
或 `main_window` 的引用。基线：**0**。

### U3 · `_page_of` 表面

冻结属性集合（11）：

```text
begin_board_pan, clear_card_selection, end_board_pan_for_event,
handle_card_double_click, handle_pinch, handle_zoom_wheel, is_board_panning,
note_space, notify_canvas_click, unplaced_tray, update_board_pan
```

Task 7 目标保留卡片语义的 4 个：`clear_card_selection`、`notify_canvas_click`、
`handle_card_double_click`、`unplaced_tray`。

### U4 · mutator 漏斗例外

当前 AST 例外（函数调用 state mutator、且本体没有 `_after_board_mutation` /
`_commit_grid_change` / `_apply_grid_snapshot`）：

| 方法 | 合法原因 |
| --- | --- |
| `save_preview_sidecar` | 写入 sidecar 元数据，调用者的持久化流程决定落盘，不触发页面投影。 |
| `_after_board_mutation` | 漏斗本体，内部调用 `mark_workspace_mutated` 后刷新。 |
| `_on_organize_free_grid` | 网格历史转场由 `_record_grid_transition` 统一收口，AST 的直接函数体看不到该间接调用。 |

### U5 / U6

- U5：`"ultraViewPage"` 字面量 2 处：`page.py:228` 与 `widgets.py:147`。Task 1 目标常量定义唯一出现。
- U6：coordinator 对 page 私有表面的唯一访问：`page._select_ref(ref)`，`ultraview_coordinator.py:1358`。Task 3 目标空。

## §3 · D1 投影范围假设

`page._previews` / `_statuses` / `_ref_exists` 的投影读点都由当前 `self._board` 的
`membership_set` 驱动：模板/自由网格投影、overview 与 tray。`show_focus` 虽读 `_previews`，
但 `set_board` 会切走前持久化旧视口、切入后裁剪三个影子字典到新 Board 成员；
`_refresh_open_focus` 只刷新当前 page 的 focus 层。导出由 `PreviewStore` / 活动 Board
合成，不读 page 影子字典。

结论：可以把 `refresh_page` 的预览状态推送收窄为**活动 Board 的 `membership_set`**；
`_refresh_library` 保持原状，因为它直接从 store 派生状态。

## §4 · D2 几何裸字面量

`floating_layout.py` 是当前唯一尺寸事实源：`RAIL_WIDTH=56`、
`RAIL_CONTENT_HEIGHT=268`、`ISLAND_HEIGHT=40`、`BOARD_ISLAND_MAX_WIDTH=240`、
`GLOBAL_ISLAND_WIDTH=116`、`STATUS_ISLAND_WIDTH=200`、`NAVIGATION_ISLAND_WIDTH=268`。

待迁移清单：

| 文件 | 当前位置 | 裸值 |
| --- | --- | --- |
| `chrome.py` | `RAIL_MIN_HEIGHT` 同义别名与 `ToolRail.sizeHint` | `RAIL_CONTENT_HEIGHT` 别名 |
| `chrome.py` | `BoardIsland`、`GlobalIsland`、`NavigationIsland`、`StatusIsland`、`CardContextIsland` 的固定高度与 sizeHint | `40` |
| `page.py` | `_chrome_sizes()` `_hint` 回退 | `(240,40)`、`(116,40)`、`(200,40)`、`(232,40)` |

Task 5 需要以组件真实 `sizeHint()` 决定导航岛回退：当前组件计算宽 232，而布局常量是 268；
不能无依据把其中一个数字直接替换掉。

## §5 · D5 / D6

- D5：两种 grid 的 `set_zoom` 均有 4 处调用，Task 2 目标各 1 处。
- D6：`_iter_viewboxes` 支持 `axes_list`、六个 `_plot*` 名称和 `plots`，当前没有「全部落空」日志。

## §6 · 验证记录

专项基线为 **581 passed / 127 warnings**。主体分进程基线为 **7134 passed /
12 failed / 13 skipped / 3 deselected**；其中 9 条是既有顺序污染，另有 3 条可独立
复现的失配项。`tests/acquisition_ui` 独立为 **359 passed**。完整命令、失败 test-id
和独立复跑证据见同目录 `baseline.txt`。

**Task 0 结论：BLOCKED。** plan 明定「失配即停」，因此未进入 Task 1；三条失配
须由视觉 harness/card-context、LayoutPicker 尺寸与 QSS palette 的 owner 先恢复或
由用户明确接受新的基线。
