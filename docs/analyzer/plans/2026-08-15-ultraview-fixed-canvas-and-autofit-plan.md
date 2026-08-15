# UltraView 固定逻辑画布与 auto-fit — 实施 plan

- 日期：2026-08-15 · 状态：**已实施**
- spec：`docs/analyzer/specs/2026-08-15-ultraview-fixed-canvas-and-autofit-spec.md`

## Task 1 固定逻辑画布

- `free_grid.screen_grid_metrics` / `GRID_MIN_VISIBLE_ROWS=10` / `GRID_SPARE_ROWS=2`
- `BoardGrid` / `FreeGridBoard` 不再用窗口尺寸推导列宽或槽位比例

## Task 2 默认适应

- `board.viewport == {}` 表示未停靠；`page._restore_viewport_from_board` 走 `zoom_fit`

## Task 3 默认自由网格

- `default_board().layout_mode = free_grid`
- `_normalize_board` 缺 `layout_mode` 仍回落 template

## Task 4 切回模板容量自适应

- `best_template_for(count)`；仅 rail 开关路径使用
- `_sync_layout_popover` 的 view_count 用 `all_refs`

## Task 5 单卡 auto-fit

- `fit_rect_for_aspect` + `CardContextIsland` fit 按钮 + 右键「按原图比例」
- 经 `plan_layout(LAYOUT_RESIZE)` 提交；模板模式置灰

## Task 6 文档与测试

- hints / quickref / ultraview-guide
- 聚焦 `tests/ui -k ultraview`；边界门禁见 CLAUDE.md
