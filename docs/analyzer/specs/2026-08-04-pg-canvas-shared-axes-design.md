# pg_canvas 公共轴层提取 · 设计(包 B)

- 日期:2026-08-04
- 基线:`main` @ `6236a5fe`(v7.9.3)。**本文所有行号以此 commit 为准。**
- 来源:2026-08-04 全仓复杂度评审(pg_canvas 画布族结构探查)。
- 实施计划:[2026-08-04-pg-canvas-shared-axes-implementation.md](../plans/2026-08-04-pg-canvas-shared-axes-implementation.md)
- 前置:无(独立于包 A/C/D/E;但**包 C 依赖本包完成**)。

## 问题与收益

`heatmap_canvas.py`(3021 行)是近两月全仓改动最频繁的文件(75 次提交)。结构性原因:
它的顶部约 550 行(L260-807)是**与 `PgHeatmapCanvas` 类无关的模块级轴/刻度/dB 工具**,
被 `line_canvas.py:35-44` 反向 import 了 8 个符号——`heatmap_canvas.py` 事实上兼任
「analysis 画布公共工具库」。后果:

1. **依赖倒置**:FFT 画布依赖热图画布文件,任何轴/刻度修复都必须落进 3021 行的文件;
2. **连带改动**:75 次 heatmap 提交中 30 次同时改 `line_canvas.py`;
3. 这批工具中的 `_robust_db_ceiling` / `_auto_db_window` / `_slice_amp_bounds` /
   `_SmoothImageItem` 正是 `batch_render_qt/_builder.py` 注释承认「Copied — not imported」
   的复制源头(批处理评审 P4)。

本包把这层提成独立模块 `ui/pg_canvas/analysis_axes.py`。**第一阶段是纯移动、零行为
变化**;第二阶段(可选、有闸门)把批处理复制的纯函数子集下沉到中立层供两边共享。

## 已核实的移动清单(基线 grep 实测)

`heatmap_canvas.py` 模块级符号,分三组:

**组 1 · 必须移动(`line_canvas.py:35-44` 反向 import 的 8 个):**
`_tick_counts_to_density`(:260)、`_apply_target_bottom_ticks`(:461)、
`_apply_axis_tick_density`(:580)、`_visual_padded_bounds`(:589)、
`_make_analysis_plot`(:688)、`_apply_neutral_axis_frame`(:706)、
`_AUTO_CEILING_PCT`(:348)、`_AUTO_SPAN_DB`(:337)。

**组 2 · 一并移动(组 1 的邻居与依赖,同属通用轴/dB 层):**
`_finite_float`(:276)、`_finite_data_bounds`(:284)、`_colorbar_is_dead`(:303)、
`_robust_db_ceiling`(:351)、`_auto_db_window`(:368)、`_SLICE_MAX_SPAN_DB`(:387)、
`_slice_amp_bounds`(:390)、`time_axis_display_extent`(:413)、
`_BoundaryGridAxisItem`(:626)、`_hide_plot_title`(:748)、`_SmoothImageItem`(:784)。

**组 3 · 明确不动(热图专属):**
colormap 块(:130-171 `_gnuplot2_lut` / `_normalise_colormap_name` / `_resolve_colormap`)、
`_AxisShim`(:174)、`_NamedColorMap`(:195)、`_HeatmapMappable`(:202)、
`_HeatmapAxisHandle`(:248)、`_SliceDirToggle`(:69)。

**非目标(明确列出以防执行者扩权):**
- `line_canvas.py:29-33` 从 `canvas.py` import 的 3 个 AA 常量不在本包范围;
- `tick_density.py`(canvas 专用 controller)与本层的**公式收敛不在本包执行**
  ——那是行为敏感改动,单独立项(见附录);
- 不改 `canvas.py`、不动 `PgHeatmapCanvas` / `PgLineCanvas` 的任何方法体。

## 设计决策

**D-B1 · 新模块 `ui/pg_canvas/analysis_axes.py`(第一阶段,必做)**

组 1 + 组 2 整体平移,函数体逐字不变,模块 docstring 写明:「analysis 画布
(line/heatmap)共享的轴、刻度、dB 显示工具;`canvas.py`(时域)不使用本模块」。

**D-B2 · 兼容别名与 monkeypatch 保护**

`heatmap_canvas.py` 顶部改为 `from .analysis_axes import <全部移动符号>`——
旧模块路径 `heatmap_canvas._robust_db_ceiling` 等继续可解析;heatmap 内部调用点
**不改写**(仍用裸名,经由模块全局解析,`monkeypatch.setattr(heatmap_canvas, "_x", ...)`
对 heatmap 内部调用仍然生效)。`line_canvas.py:35-44` 改为从 `analysis_axes` import。

**风险点(实施计划 Task 0 必查):** 若有测试 monkeypatch `heatmap_canvas.<符号>`
且断言的是 **line_canvas** 的行为,该 patch 会失效——此类测试把 patch 目标改到
`analysis_axes`(测试侧一行改动,逐个记录在 PR 描述)。

**D-B3 · 新增直接单测(填补空档)**

组 2 的纯函数目前只有经由画布的间接覆盖。新增 `tests/ui/test_analysis_axes.py`:

- `_slice_amp_bounds`:空数组 / 全 NaN / 正常数据 / 超 200 dB 跨度被
  `_SLICE_MAX_SPAN_DB` 钳制;
- `_robust_db_ceiling` + `_auto_db_window`:99 百分位天花板、30 dB 窗、全零矩阵;
- `_tick_counts_to_density` 与 `_apply_axis_tick_density` 的往返一致性;
- `_visual_padded_bounds`:正常/lo==hi/负区间;
- `time_axis_display_extent`:params 优先、metadata 回退、fallback 兜底三条路径;
- `_colorbar_is_dead` / `_finite_data_bounds` 边界值。

这些测试**先在基线上对着 `heatmap_canvas` 写绿、随移动改一次 import**,之后成为
公共层的永久回归网。

**D-B4 · 第二阶段(可选,有闸门):中立层下沉,为批处理去重铺路**

把纯函数子集(`_robust_db_ceiling` / `_auto_db_window` / `_slice_amp_bounds` /
`_SLICE_MAX_SPAN_DB` / `_SmoothImageItem`)再上移到**顶层中立模块**
`mf4_analyzer/qt_analysis_shared.py`(仿 `qt_plot_helpers.py` 先例——顶层 pyqtgraph
帮助模块,`batch_render_qt` 与 `ui/pg_canvas` 都可 import 而不破坏
`renderer_import_policy` 边界),`analysis_axes.py` 变为再导出。

**闸门(全部满足才执行):**
1. 第一阶段已收尾且全量测试与基线一致;
2. `tests/test_batch_render_import_boundary.py` 在改动后通过(中立模块不得拉 `ui.*`);
3. 本阶段**只建落点、不改 batch 侧**——`batch_render_qt/_builder.py` 切换到共享实现
  属于批处理评审第三步,需要 parity 基线重建,另行立项。

## 验收准则

**第一阶段:**
1. `tests/ui/test_pg_heatmap_canvas.py`(148 用例)、`test_pg_line_canvas.py`(119)、
   `test_axis_frame_alignment.py`、`test_axis_grid_label_slack.py`、
   `test_stacked_left_axis_metrics.py`、`test_colorbar_reset.py`、
   `test_slice_amp_floor_guard.py` 失败集与基线一致;新增 `test_analysis_axes.py` 全绿。
2. `grep "from .heatmap_canvas import" mf4_analyzer/ui/pg_canvas/line_canvas.py` → 零命中。
3. `heatmap_canvas.py` 行数减少 ≥ 500;`git diff` 中被移动函数的函数体零改动
   (可用 `git diff --color-moved=dimmed-zebra` 人工复核)。
4. 像素级守护:`tests/ui/test_pg_canvas_decomposition_characterization.py`(10 用例,
   docstring 自述就是为拆解钉行为的)必须绿。
5. 真机验收:启动 GUI,各出一张 FFT、FFT-Time、Order 图,目视核对轴框/刻度/
   colorbar 与基线截图无差异(macOS 原生,遵循 CLAUDE.md「验真机渲染」纪律)。

**第二阶段(若执行):** 上述全部 + import 边界测试 + `import mf4_analyzer.qt_analysis_shared`
不拉起 `mf4_analyzer.ui`。

## 附录 · 显式推迟的决定

**三套 tick 密度实现的收敛**(canvas.py 的 `TickDensityController` 内联公式 vs
本层 `_apply_target_bottom_ticks` vs `batch_render_qt` 的 `_apply_tick_density`):
`heatmap_canvas.py:264-268` 的注释已指认重抄原因。收敛是**视觉行为改动**,需要
characterization(对代表性输入钉住三套实现的刻度输出)+ 真机逐图验收,且横跨
批处理 parity 基线。待本包与批处理第一步落地后单独立项,不要在本包顺手做。
