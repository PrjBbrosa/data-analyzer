# pg_canvas 公共轴层提取 · monkeypatch 风险审计(包 B · Task 0 Step 3)

- 日期:2026-08-06
- 基线:`main` @ `b886a30e`(= 设计文档基线 `e385ce5a` + 纯 docs 提交,产品代码零差异)
- 对应风险点:设计文档 D-B2「若有测试 monkeypatch `heatmap_canvas.<符号>` 且断言的是
  **line_canvas** 的行为,该 patch 会失效」

## 结论(先说结果)

**D-B2 的风险点在当前基线上不成立:全仓没有任何测试 monkeypatch `heatmap_canvas`
的模块级属性。** 因此实施计划 Task 3 Step 2(把 patch 目标改到 `analysis_axes`)
**是空操作,不需要修改任何测试文件**。

判定命令(计划 Task 0 Step 3 原文):

```
grep -rn "heatmap_canvas" tests/ | grep -i "monkeypatch\|setattr\|patch"
```

→ **零命中**。

## 证据 1:canvas 测试里所有 `monkeypatch.setattr` 的目标

对 7 个画布测试文件逐个展开多行 `monkeypatch.setattr(` 调用,目标全部落在
本次移动清单之外:

| 文件:行 | patch 目标 | 属于移动清单? |
| --- | --- | --- |
| `test_pg_heatmap_canvas.py:112` | `QMenu.popup` | 否(Qt 类) |
| `test_pg_heatmap_canvas.py:473` | `_axis_interaction.edit_chart_options_dialog` | 否(另一模块) |
| `test_pg_heatmap_canvas.py:868 / 896 / 924` | canvas **实例**方法(`_add_remark_at_viewport_pos` 等) | 否(实例属性) |
| `test_pg_heatmap_canvas.py:1014` | canvas 实例 `grab` | 否 |
| `test_pg_heatmap_canvas.py:1589` | `QApplication.mouseButtons` | 否 |
| `test_pg_heatmap_canvas.py:2311 / 2339` | `pg.AxisItem.generateDrawSpecs` | 否(pyqtgraph 类) |
| `test_pg_heatmap_canvas.py:3119` | canvas 实例 `_align_slice_to_main` | 否 |
| `test_pg_line_canvas.py:106` | `QMenu.popup` | 否 |
| `test_pg_line_canvas.py:426` | `_axis_interaction.edit_chart_options_dialog` | 否 |
| `test_pg_line_canvas.py:757` | `QApplication.mouseButtons` | 否 |
| `test_pg_line_canvas.py:2199 / 2208` | 局部 axis 对象 / canvas 实例 | 否 |
| `test_pg_line_canvas.py:2356 / 2384 / 2412` | canvas 实例方法 | 否 |
| `test_axis_frame_alignment.py:53` | `pg.AxisItem.drawPicture` | 否 |
| `test_axis_grid_label_slack.py:61` | `pg.AxisItem.generateDrawSpecs` | 否 |
| `test_stacked_left_axis_metrics.py:77` | `pg.AxisItem.generateDrawSpecs` | 否 |

即:测试要么 patch pyqtgraph/Qt 基类,要么 patch 画布**实例**,没有一处
patch `heatmap_canvas` 模块全局名。移动后模块全局名的解析路径变化对它们没有影响。

## 证据 2:19 个移动符号在 tests/ 的引用形态(全是 import,不是 patch)

按符号逐个 `grep -rn "<符号>" tests/` 的结果归并如下。所有引用都是
**值绑定式 import 或字符串/docstring 提及**,移动后经 `heatmap_canvas` 再导出
继续解析到**同一个对象**,因此 `isinstance` 判定与数值断言都不受影响。

### 引用了移动符号、且行使的是 **line_canvas** 行为(D-B2 关注的形态)

| 文件:行 | 符号 | 形态 | 移动后是否需要改 |
| --- | --- | --- | --- |
| `test_pg_line_canvas.py:1107` | `_apply_axis_tick_density` | `from ...heatmap_canvas import`,直接调用作用在 line canvas 的 axis 上 | **否**——再导出后是同一函数对象 |
| `test_pg_line_canvas.py:2063` | `_BoundaryGridAxisItem` | `from ...heatmap_canvas import`,对 line canvas 的 axes 做 `isinstance` | **否**——再导出后是同一个类对象,`isinstance` 恒等 |

这两处是「引用 heatmap 路径 + 行使 line 行为」的仅有案例,但**都不是 monkeypatch**,
所以不落入 D-B2 的失效场景。按「函数体逐字平移、不做范围外改动」的纪律,**不动它们**。

### 其余引用(行使 heatmap / 通用行为)

| 文件 | 涉及符号 |
| --- | --- |
| `test_pg_heatmap_canvas.py` | `_apply_target_bottom_ticks`、`_make_analysis_plot`、`time_axis_display_extent`、`_auto_db_window`、`_robust_db_ceiling`、`_AUTO_CEILING_PCT`、`_AUTO_SPAN_DB`、`_BoundaryGridAxisItem`、`_BOUNDARY_GRID_EPS_PX` |
| `test_auto_color_span.py` | `_auto_db_window`、`_robust_db_ceiling`、`_AUTO_CEILING_PCT`、`_AUTO_SPAN_DB`(经模块别名 `hc`) |
| `test_slice_amp_floor_guard.py` | `_slice_amp_bounds`(经模块别名 `hc`) |
| `test_nudge_signals.py` | `_colorbar_is_dead`(`from ...heatmap_canvas import`) |
| `test_task6_preset_guard.py` | `_AUTO_CEILING_PCT`、`_AUTO_SPAN_DB`、`_robust_db_ceiling` |
| `test_axis_grid_label_slack.py` | `_make_analysis_plot` |
| `test_axis_frame_alignment.py` | `_apply_neutral_axis_frame`、`_make_analysis_plot` |

注意 `test_auto_color_span.py` / `test_slice_amp_floor_guard.py` 用的是
**模块别名属性访问**(`hc._auto_db_window(...)`),这正是再导出必须保留的形态:
`heatmap_canvas` 顶部的 `from .analysis_axes import ...` 会把这些名字重新绑到
模块命名空间上,`hc.<符号>` 继续可解析。

### 产品代码侧的旧路径引用(同样靠再导出兜住)

| 文件:行 | 符号 |
| --- | --- |
| `ui/main_window/_order_mixin.py:512` | `time_axis_display_extent` |
| `ui/main_window/_order_mixin.py:581` | `_auto_db_window` |
| `ui/pg_canvas/line_canvas.py:35-44` | 组 1 的 8 个符号(Task 3 改指 `analysis_axes`) |

## 附带发现:随函数移动的私有常量(不在 spec 的 19 个里)

spec 的移动清单由 `grep "^def \|^class \|^_AUTO\|^_SLICE"` 得出,漏掉了几个
**被移动函数体直接引用的模块级私有常量**。它们必须跟着走,否则移动后 `NameError`:

| 常量 | 行 | 唯一使用者 | 处置 |
| --- | --- | --- | --- |
| `_COLORBAR_DEAD_VISIBLE_FRAC` | :300 | `_colorbar_is_dead` | 随迁 |
| `_TARGET_BOTTOM_TICK_NICE_FACTORS` | :454 | `_apply_target_bottom_ticks` | 随迁 |
| `_TARGET_BOTTOM_TICK_MIN_GAP_PX` | :455 | 同上 | 随迁 |
| `_TARGET_BOTTOM_TICK_MIN_NARROW_GAP_PX` | :456 | 同上 | 随迁 |
| `_TARGET_BOTTOM_TICK_EDGE_PAD_PX` | :457 | 同上 | 随迁 |
| `_TARGET_BOTTOM_TICK_MIN_COUNT` | :458 | 同上 | 随迁 |
| `_BOUNDARY_GRID_EPS_PX` | :611 | `_BoundaryGridAxisItem` | 随迁,**且必须再导出**(`test_pg_heatmap_canvas.py:2281` 从旧路径 import) |

反向确认:`_EMPTY_X_RANGE` / `_EMPTY_Y_RANGE`(:622-623)虽然夹在移动区间里,
但使用者是 `PgHeatmapCanvas`(:1214-1215),属于组 3「热图专属」,**留在
`heatmap_canvas.py`**。

`_TARGET_BOTTOM_TICK_*` 与 `_COLORBAR_DEAD_VISIBLE_FRAC` 在 `mf4_analyzer/`、
`tests/`、`scripts/`、`tools/` 中零外部引用,所以不需要再导出(仍会随
`from .analysis_axes import *` 之外的显式列表一并再导出,以保守兼容)。
