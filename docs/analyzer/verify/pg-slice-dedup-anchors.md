# 包 C · 锚点重定位与盘点(Task 0)

- 重定位基线:`main` @ `ab19622f`(包 B 已合并)。计划/设计文档里引 `e385ce5a`
  的行号**全部作废**——包 B 把 `heatmap_canvas.py` 从 3021 削到 **2518** 行,
  `line_canvas.py` = 2235 行。
- 本文档随 C1–C4 推进增补(差异归类、审计表)。

## Step 1 · 三组锚点的当前位置

### 空态提示三件套

| 方法 | `line_canvas.py` | `heatmap_canvas.py` |
| --- | --- | --- |
| 字段 `_empty_hint_text` / `_empty_hint_item` | 259-260 | 391-392 |
| `show_empty_hint` | 703-732 | 719-748 |
| `_reposition_empty_hint` | 734-742 | 750-758 |
| `clear_empty_hint` | 744-758 | 760-774 |

逐行 diff(56 行 vs 56 行,行数完全一致):**唯一差异是宿主 ViewBox 的取法**
——line 用 `self._plot_amp.vb`,heatmap 用 `self._plot.vb`,共 8 处。
没有任何逻辑/顺序/异常处理差异。→ 用「目标 ViewBox」一个参数即可吸收,
不需要留分叉。

`canvas.py`(时域)另有一份 `show_empty_hint` / `clear_empty_hint`
(2623-2647),实现完全不同(挂在 `self._glw` 而非 vb,无 reposition)。
**明确禁止动 `canvas.py`**,不纳入 C1。

外部消费面(必须保持签名/属性不变):
- `ui/main_window/_analysis_mixin.py:610-621`、`ui/main_window/window.py:2775,2835`
  调 `show_empty_hint` / `clear_empty_hint`。
- 测试直接读 `_empty_hint_item` / `_empty_hint_text`:
  `tests/ui/test_analysis_multiview_integration.py`(多处)、
  `tests/ui/test_pg_heatmap_canvas.py:1040-1049`、
  `tests/ui/test_pg_timedomain_canvas.py:1666-1678`、
  `tests/ui/test_main_window_smoke.py`、`tests/ui/test_project_session.py:251`。
  → 两个字段必须留在**画布实例**上,不能只存在于帮助类里。

### remark 视口层

| 方法 | `line_canvas.py` | `heatmap_canvas.py` | 结论 |
| --- | --- | --- | --- |
| `_viewport_pos_to_scene` | 2095-2099 | 2231-2235 | **逐字 100% 相同**(5 行) |
| `_remark_item_at_viewport_pos` | 2123-2167 | 2256-2300 | **逐字 100% 相同**(45 行) |

第三份拷贝:`annotations.py:230-274`(`AnnotationManager`,服务 `canvas.py`)。
与上面两份只差 `self.remarks` ↔ `self._remarks` 和一行 docstring
(相似度 0.911)。属 `canvas.py` 的委托面,**本包不动**,仅记录。

外部消费面:
- `line_canvas.py:241` / `heatmap_canvas.py:389` 把 `_remark_item_at_viewport_pos`
  作为 `RemarkInteraction(remark_at_viewport_pos=...)` 的回调传入。
- `tests/ui/test_pg_timedomain_canvas.py:1233,1334,1392` monkeypatch 的是
  **canvas.py 侧**(`AnnotationManager`),不受本包影响。

### 分栏对齐四件套

| 方法 | `line_canvas.py` | `heatmap_canvas.py` |
| --- | --- | --- |
| `prepare_split_layout_alignment` | 1523-1556 | 1867-1901 |
| `reset_split_layout_alignment` | 1558-1567 | 1903-1916 |
| `_unify_stacked_left_axes` | 1569-1592 | 1918-1951 |
| `apply_split_layout_alignment` | 1636-1666 | 2015-2042 |
| (周边)`_alignment_left_axes` | 1668-1669 | 2044-2048 |
| (周边)`_alignment_bottom_axes` | 1671-1675 | 2050-2054 |
| (周边)`recommended_split_title_width` | 1515-1521 | 1853-1865 |

公共基类已存在:`_split_mixin._StackedSplitMixin`(`_split_mixin.py:211-290`),
两画布都继承。差异审计见下面 §C3。

外部消费面(签名是与页面的契约,**不可改**):
`ui/analysis_section_page.py:465-544` 按 `hasattr` 探测三个 `*_split_layout_alignment`
并用**不同的关键字**分别调用两种画布
(line:`amp_bottom_axis_height` / `time_bottom_axis_height` / `amp_right_reserve` /
`time_right_reserve`;heatmap:`main_bottom_axis_height` / `slice_bottom_axis_height` /
`slice_right_reserve`)。指标方法名也不同:`line_layout_metrics` /
`heatmap_layout_metrics`。

### 切片带盘点(C4 的接口面)

`_SliceDirToggle` 类:`heatmap_canvas.py:103-149`(47 行)。

`__init__` 里的 `_slice_*` 字段簇:
- 397-401 抗锯齿:`_slice_aa_on`、`_slice_aa_idle_timer`
- 419-456 状态簇:`_slice_curve` `_slice_plot` `_slice_marker` `_slice_toggle`
  `_slice_hint` `_slice_panel`(**注意:这是那个 QWidget 信息面板,名字已被占用**)
  `_slice_dir` `_slice_x_idx` `_slice_y_idx` `_slice_x_val` `_slice_y_val`
  `_slice_marker_updating` `_slice_x_btn_label` `_slice_y_btn_label` `_slice_toggle_w`
- 513-593 `with_slice=True` 构造块(slice PlotItem、curve、marker、面板/toggle/hint)
- 594-615 **不是切片的**:split divider / collapsed rail / colorbar
  ——归 `_StackedSplitMixin` 与主图,C4 不搬。

#### 切片专属(C4 搬迁候选)

| 方法 | 行 | 行数 |
| --- | --- | --- |
| `_apply_slice_curve_aa_state` | 646-653 | 8 |
| `_reset_slice_quality_for_rebuild` | 655-661 | 7 |
| `_slice_coords` | 1394-1409 | 16 |
| `_seed_slice` | 1411-1433 | 23 |
| `set_slice_direction` (公开) | 1435-1447 | 13 |
| `select_time_index` (公开) | 1449-1459 | 11 |
| `_slice_visible_mask` (staticmethod) | 1487-1504 | 18 |
| `_set_slice_x_range` | 1506-1518 | 13 |
| `_slice_axis_range` | 1520-1535 | 16 |
| `_apply_slice_amp_range` | 1537-1565 | 29 |
| `_apply_slice` | 1567-1624 | 58 |
| `_on_slice_marker_dragged` | 1626-1646 | 21 |
| `_update_slice_hint` | 1666-1681 | 16 |
| `_select_slice_at` | 1683-1704 | 22 |
| `set_slice_button_labels` (公开) | 1706-1712 | 7 |
| `_align_slice_to_main` | 1714-1730 | 17 |
| `_position_slice_panel` | 1732-1766 | 35 |
| `_set_slice_right_spacer` | 2056-2081 | 26 |
| **小计** | | **356** |
| `_SliceDirToggle` | 103-149 | 47 |
| **合计** | | **403** |

#### 主图/切片共用(留在 `PgHeatmapCanvas`,是 C4 的接口面)

传递依赖用 AST 扫过每个上表方法的函数体得到(不是 grep `def`,
所以模块级常量与被引用的宿主属性都在内),**搬迁时必须一并满足**:

宿主属性/方法(切片侧要读,留在画布):
`_glw` `_plot` `_cbar` · `_matrix_disp` `_x_coords` `_y_coords` `_extents`
`_x_label` `_y_label` · `_panel_time_range` `_panel_freq_range` `_panel_amp_range` ·
`_main_view_range()` `_current_amplitude_axis_label()` `_apply_default_axis_labels()`
`_short_axis_label()` `_time_index_for()` `_freq_index_for()` ·
`_set_curve_aa()` `disable_interactive_quality()` `schedule_idle_quality()` ·
`_activate_graphics_layout()` · QWidget 的 `width()` / `isVisible()` ·
信号 `layout_geometry_changed` `slice_picked` `slice_hint_requested`。

模块级传递依赖(C4 Step 3 移出文件时必须一起 import,否则 NameError):
`np` `pg` · `PG_AXIS_NEUTRAL_COLOR` `PG_AXIS_NEUTRAL_WIDTH`(来自
`ui/_axis_handle`)· `_hide_plot_title` `_slice_amp_bounds`(来自
`pg_canvas/analysis_axes`,实体在顶层 `qt_analysis_shared.py`)。
**`_slice_amp_bounds` / `_SLICE_MAX_SPAN_DB` / `_SmoothImageItem` 等 8 个符号
已在中立层,算「共用」,不搬回本包。**

`heatmap_canvas.py:38-45` 的注释警告:内部调用点靠本模块 globals 解析,
以便 `monkeypatch.setattr(heatmap_canvas, ...)` 生效。已复查:
仓库里**没有**测试 monkeypatch 本模块的 `_slice_amp_bounds` / `_hide_plot_title`
(`tests/ui/test_slice_amp_floor_guard.py` 直接调 `hc._slice_amp_bounds`,
只依赖再导出存在),所以 C4 Step 3 把这两个名字改从 `analysis_axes` 直接
import 到 `slice_panel.py` 是安全的。

## Step 2 · 外部消费面(必须保留薄委托)

产品代码:
- `ui/chart_stack/stack.py:150-151` → `set_slice_button_labels()`、`set_slice_direction()`
- `ui/chart_stack/cards.py:210-219,974-994` → 信号 `slice_picked`、`slice_hint_requested`
- `ui/main_window/_order_mixin.py:653-654` → `canvas._slice_curve`(判空)、`canvas._seed_slice()`
- `ui/analysis_section_page.py:485-503` → 只读 `heatmap_layout_metrics()` 的
  `slice_bottom_axis_height` / `slice_right_reserve` 键

测试(`tests/ui/test_pg_heatmap_canvas.py` 为主):
`_slice_plot`(54)、`_slice_curve`(18+1)、`set_slice_direction`(16)、
`_slice_marker`(14)、`_slice_panel`(7)、`_select_slice_at`(6)、`_seed_slice`(5)、
`set_slice_button_labels`(4)、`_slice_dir`(4)、`_slice_aa_on`(4)、
`_slice_aa_idle_timer`(4)、`_slice_x_idx`(2)、`_slice_toggle`(1)、
`_align_slice_to_main`(1)。
`tests/ui/test_slice_amp_floor_guard.py` 只用模块级 `hc._slice_amp_bounds`。

> **命名冲突警告:** 计划里 C4 建议的聚合对象名 `self._slice_panel` **已被占用**
> ——它是切片信息面板那个 `QWidget`,且被 7 处测试直接读。聚合对象改用
> `self._slice`。

## Step 3 · 基线

见 [`pg-slice-dedup-baseline.txt`](pg-slice-dedup-baseline.txt)。
画布全量 **698 passed / 0 failed**;`tests/ui/` 全量
**3086 passed / 2 failed**,与 CLAUDE.md 记录的两条既有红完全一致。

真机截图基线:**本次执行按编排要求跳过**(改由 orchestrator 的两侧真机渲染
哈希对比覆盖)。本文件末尾列出改动触碰的可视面清单。

## C1 · 空态提示差异归类(已完成)

逐行 diff 的全部 8 处差异,归类:

| # | 位置 | 差异 | 归类 | 处置 |
| --- | --- | --- | --- | --- |
| 1 | `show`:`addItem` | `_plot_amp.vb` ↔ `_plot.vb` | **真实差异**——line 是两行堆叠(谱 + 时域预览),提示挂在幅值行;heatmap 只有主图 | `viewbox_getter` 回调吸收 |
| 2-3 | `show`:信号连接 | 同上 | 同上 | 同上 |
| 4-5 | `_reposition`:`sceneBoundingRect` / `mapSceneToView` | 同上 | 同上 | 同上 |
| 6-7 | `clear`:信号断开 | 同上 | 同上 | 同上 |
| 8 | `clear`:`removeItem` | 同上 | 同上 | 同上 |

「无意漂移」0 处;两边的样式常量、Z 值、异常分支、连接前先断开的顺序完全一致。
→ 共享实现 `ui/pg_canvas/empty_hint.py::EmptyHintOverlay`,零分叉。

保留的公开面:两画布的 `show_empty_hint` / `_reposition_empty_hint` /
`clear_empty_hint` 签名不变(薄委托),`_empty_hint_item` / `_empty_hint_text`
仍是**画布实例属性**(`on_state` 回写),因为多处测试与 `ui/main_window` 直接读它们。

## C2 · remark 视口层(已完成)

两处逐字 100% 相同,无差异需要归类。移入 `remarks.py` 的模块级函数:

| 新函数 | 参数 | 取代 |
| --- | --- | --- |
| `viewport_pos_to_scene(view, viewport_pos)` | 显式收 `QGraphicsView` | 两画布的 `_viewport_pos_to_scene`(各 5 行) |
| `remark_at_viewport_pos(remarks, view, viewport_pos)` | 显式收 remark 列表 + view | 两画布的 `_remark_item_at_viewport_pos`(各 45 行) |

裸字面量 `12 ** 2` 提为 `_LABEL_HIT_RADIUS_PX`。
两画布保留同名薄委托方法(`RemarkInteraction` 回调和测试都按名字调用)。

`annotations.py` 的第三份拷贝按计划**不动**(它服务 `canvas.py`)。

## C3 · 差异审计表

见本文件在 C3 提交中的增补。

## 改动触碰的可视面

见本文件在收尾提交中的增补。
