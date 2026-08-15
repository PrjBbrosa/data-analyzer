# UltraView 固定逻辑画布与 auto-fit

日期：2026-08-15 · 状态：**已实施**
配套 plan：`docs/analyzer/plans/2026-08-15-ultraview-fixed-canvas-and-autofit-plan.md`

## 0. 结论

屏幕 Board 与导出合成器共用固定逻辑画布（模板 `BASE_BOARD_SIZE` 1600×900；
自由网格 1600 宽、行高 88）。窗口尺寸只决定「适应」缩放，不再改卡片长宽比。
新 Board 默认自由网格、默认适应视口；rail 切回模板按卡片数选最小够用的等分
模板；自由网格选中条提供「按原图比例」把卡片格数吸附到预览图宽高比。

## 1. 决策

1. **两种模式都改成固定逻辑画布**，不保留「模板铺满窗口」的旧阅读契约。
2. **auto-fit 改卡片尺寸**去贴合原图比例，只在自由网格可用；模板按钮置灰，
   不隐式切模式。
3. 缺 `layout_mode` 的旧 payload 仍按 **template** 恢复，不被新默认值改写。
4. 空 `viewport` / 缺省表示从未停靠；首次显示走 `zoom_fit()`。带 `zoom` 的
   旧工程精确恢复。

## 2. 几何

- 自由网格屏幕路径：`screen_grid_metrics(placements)` =
  `grid_metrics((1600, 0), placements)`，列宽与 `export_grid_metrics` 相同。
- `GRID_MIN_VISIBLE_ROWS = 10`，屏幕路径在已占行后再加 `GRID_SPARE_ROWS = 2`。
- 模板：`logical_board_size(layout_id, BASE_BOARD_SIZE)`，再按 zoom 同比放大。
- `fit_rect_for_aspect` 在合法 span 里最小化
  `|plot_w / (plot_h - chrome) − image_w / image_h|`，平局取面积最接近原卡。

## 3. 非目标

- 不做无限画布 / QGraphicsView。
- 不把预览图改成裁切填满（IgnoreAspectRatio）。
- 不在模板模式隐式切到自由网格。
