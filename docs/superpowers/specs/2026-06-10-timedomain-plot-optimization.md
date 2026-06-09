# 时域 Plot 性能优化与内核精简 — Spec（第一批：低风险）

日期：2026-06-10
状态：已评审（基于三路并行深度 review：渲染管线 / 数据流 / 死代码扫描，全部发现经 grep/AST 验证调用方）
配套 plan：`docs/superpowers/plans/2026-06-10-timedomain-plot-optimization.md`

## 1. 背景与已确认事实

时域 plot（`mf4_analyzer/ui/pg_canvas/` + `chart_stack.py` / `main_window.py` 数据流）的交互热路径核心设计是好的：C envelope 降采样（`signal/_envelope_cutils.positions_envelope`）+ per-channel range-key 闸门（`renderer.py` `_quantize_range_key`）+ 40ms 防抖 + 绘图期零拷贝切片。

已实测确认（不要推翻）：

- 卡顿根因 = CPU 光栅化（QPainter 软件渲染），随 overlay 通道数超线性 + dpr² 增长；像素宽封顶方案实测仅 13% 收益；OpenGL 有效但破坏 `QWidget.grab()` 导出（全白）。
- AA 滞回密度门控（`quality.py`）是实测校准过的正确设计。
- `autoDownsample` / `downsampleMethod='peak'` / `clipToView` **不应启用**——自研 C envelope 已在上游做了同等且更快的工作。
- ui/ 下「同名方法重复定义」结构性污染已全部修复（2026-06-10 AST 验证 0 真重复），可直接定点修改。

本批次浪费集中在三类，全部**低/中风险、功能不变**：

1. **重建型事件重复做工**：换通道 / 分↔叠切换 / 切 tab 时，每通道最多算 3 次 envelope（bind 全量 + restore 后 1-2 次可见窗口），monotonicity 全量重扫，隐藏的 stats_strip 还做 6 项全量统计。
2. **每个鼠标 tick 的 Python 旁路开销**：quality 状态机每 tick 双场景遍历 + N×getData + 跨对象信号；subplot N 行重复同一份 X 刻度计算；等值 sibling 传播仍强制重建轴 picture；resize 每个中间尺寸做双倍工。
3. **死代码与六份复制的基类**：~103 行零引用方法、~200 行 `_CanvasBackref` 逐字六份、双定义 helper。

## 2. 目标 / 非目标

**目标**

- G1：消除上述三类浪费，重建型事件（勾通道/切模式/切 tab）每通道 envelope 计算从 ≤3 次降到 1 次。
- G2：拖动/缩放期间每个鼠标 tick 不再做场景级遍历或状态重建（除必要的 sibling X 传播）。
- G3：删除高确定性死代码与重复定义，净减 ≥350 行，不改变任何用户可见行为。
- G4：所有改动保持现有测试契约；monkeypatch seam（`pg_canvases.py` shim、envelope re-export、canvas 单行委托、`enable_span_selector` no-op）**一律保留**。

**非目标（本批不做，见 §5 后续批次）**

- 不引入 OpenGL、不改导出链、不做合成曲线层。
- 不做 min-max pyramid。
- 不退役 matplotlib 版 `TimeDomainCanvas`（canvases.py:521-1601，parity 测试引用，需单独决策）。
- 不压 canvas.py 的单行委托层（4.2 解耦有意保留的红线）。
- 不改 `inspector_sections.py` 三类 Mixin 化（单独立项）。

## 3. 需求清单（Wave A：热路径性能）

每项的「验收」= 新增回归测试 + 既有套件全绿。

### A1 quality 状态机：值不变不发射 + AA-off 幂等早退
- 现状：`canvas.py` `_on_xrange_changed` 每个拖动 tick 调 `disable_interactive_quality()`；即使 `aa_on=False` 也走到 `_emit_quality_status_changed()` → `quality_status()` → 两次全场景遍历（`_collect_curve_items` + `_density_status`，后者对每条曲线 `getData()`）→ 发信号 → `chart_stack._set_quality_status` setToolTip/update。状态没变也全做。
- 要求：(a) `_emit_quality_status_changed` 缓存上次发射的 status dict，相同则不发射；(b) `disable_interactive_quality` 在 `aa_on=False` 且 idle timer 本来就未激活时直接 return（不构建 status）；timer 刚被取消（yellow→red 转变）时仍要发射。
- 验收：重复调用 `disable_interactive_quality` 零发射、零 `_density_status` 调用；`tests/ui/test_pg_timedomain_canvas.py -k quality` 全绿；quality 指示点的最终稳态颜色行为不变。

### A2 resize 双倍做工合并到 settle pass
- 现状：`canvas.py resizeEvent` 每个中间尺寸**同步**做 `_recheck_subplot_label_placement()`（TextItem 全部拆建）+ `_unify_subplot_left_axis_widths()`；40ms 后 `_on_resize_settled` 又做一遍 unify。
- 要求：resizeEvent 只保留 `density_seeded` 失效 + settle timer 启动；label recheck 移入 `_on_resize_settled`（在既有 retick/unify 之前，保持原相对顺序）。
- 验收：resizeEvent 不再同步调用 label recheck；settle 调用恰一次；既有 resize/label 相关测试通过（若有测试依赖同步时序，仅修正其调度假设，不弱化断言）。

### A3 X 刻度计算按 (xlim, width, density) 记忆化
- 现状：`tick_density.py _apply_target_x_ticks_to_all_axes` 对 subplot 每行各算一遍 `_compute_target_x_ticks`（~30 个 nice-step 候选 × 每候选 QFontMetrics 逐 label 测宽），但各行 xlim/轴宽被钉死相同，结果必然一致。该函数每个 40ms debounce tick 都跑。
- 要求：controller 持有 `ticks_cache`（key = `(lo, hi, round(width,1), density_x)`，value = ticks 列表，含空结果；容量上限 32，超限整体 clear）。
- 验收：3 行 subplot 一轮 `_apply_target_x_ticks_to_all_axes` 最多 1 次 compute；同 key 第二轮 0 次；刻度渲染结果与改前一致。

### A4 `_refresh_visible_data` 尾部闸门 + `reset_view_to_data_extents` 去掉重复 flush
- 现状：所有通道命中 range-key 闸门（典型：reset_view 在 try 体和 finally **flush 两次**）时，尾部仍无条件跑全轴 retick + `xrange_changed`/`visible_range_changed` 双发射（→ inspector spinbox + view_bridge 全通道捕获）+ quality emit。
- 要求：(a) 循环统计 `updated_any`；全 skip 且 `(xlim, pixel_width)` 签名与上次相同 → 提前 return；签名存 `self._last_refresh_signature`（canvas init / clear / invalidate_envelope_cache 全清路径重置为 None）。(b) 删除 `reset_view_to_data_extents` try 体内的第一次 flush（finally 兜底，中间全同步无可见中间帧）。
- 验收：同 xlim 重复 flush 零发射零 retick；Home（查看全部）行为不变（X 全程 + Y raw 全程）。

### A5 sibling 传播等值分支不再触发轴 picture 重建
- 现状：`canvas.py _propagate_xlim_to_siblings` 等值分支仍调 `_sync_x_axis_item_range` → `AxisItem.setRange` 无条件 `picture=None; update()`，每 tick 强制每行轴文字重排版。
- 要求：等值分支直接 `continue`（轴在该 range 首次推送时已同步）。
- 验收：ranges 已收敛时 propagate 零次 `_sync_x_axis_item_range`；subplot 联动拖动行为不变（既有 propagate 测试全绿）。

### A6 monotonicity 跨重建指纹缓存
- 现状：`overlay_axes._bind_channel` 每次重建对每通道全量 `np.diff` 扫描（`_is_monotonic_array`），数据没变（勾通道/切模式/切 tab）也重扫。
- 要求：canvas 持有 `_monotonic_fingerprint_cache`，key = `(data_id, name, len, t[0], t[-1])`（O(1) 指纹，range-filter 切片与自定义 X 轴换源都会改变指纹）；`clear()` **不**清它；`invalidate_monotonicity_cache()` 与 `full_reset()` 清空；容量上限 256。
- 验收：同数组二次重建 0 次全量扫描；显式 invalidate 后重扫；NaN/非单调通道的 envelope 回退路径行为不变。

### A7 隐藏 stats_strip 不再做全量统计
- 现状：`main_window._plot_time_on_canvas` 每次 replot 对每通道全数组算 min/max/mean/rms/std/ptp（含 `sig**2` 全量临时分配），而 `chart_stack._STATS_STRIP_ENABLED = False` 控件永不可见。
- 要求：`collect_stats = update_primary_ui and _STATS_STRIP_ENABLED` 闸门；False 时跳过 `st[name]` 计算与 `update_stats(st)`；空数据路径的 `update_stats({})` 清空调用保留。
- 验收：`_STATS_STRIP_ENABLED=False` 下 replot 不做统计；`tests/ui/test_chart_stack_stats_visibility.py` + `test_main_window_smoke.py` 全绿。若未来把开关打开，统计行为与现状一致。

### A8 装载期纯浪费拷贝消除
- 现状：`io/loader.py` `np.array(s, float)`/`np.array(sig.timestamps, float)` 强拷（含 except 分支重复一份）；max-len 通道 timestamps 再拷一次给 `ref_ts`；`io/file_data.py` 时间列 `.values.astype(float)` 再拷一次。
- 要求：`np.asarray(..., dtype=np.float64)`（dtype 匹配时零拷贝）；`ref_ts = sigs[ch_name]['t']` 共享引用（下游契约 read-only，见 main_window.py:1780-1782 注释）；`file_data` 用 `to_numpy(copy=False).astype(float, copy=False)`。
- 验收：FileData.time_array 与 df 时间列共享内存（`np.shares_memory`）；`tests/test_mf4_loader.py` 全绿。注意 pandas 3 `DataFrame(dict)` 仍整体复制一次——本批不动容器设计。

### A9 重建路径消除「全量 envelope 算了就扔」
- 现状：`overlay_axes._bind_channel` 每通道先算 `xlim=None` **全量** envelope 绑给 PlotDataItem；带 xlim 恢复的重建（分↔叠、切 tab、`_replot_canvas_for_view`）随即被 `_restore_primary_xlim → _flush_pending_refresh` 的可见窗口 envelope 覆盖，第一帧从未上屏。
- 要求：`plot_channels` 增加 `defer_first_frame=False` 关键字；为 True 时 `_bind_channel(skip_envelope=True)` 绑空数组占位，并在 build 尾部武装 40ms 防抖刷新作为安全网（restore 被跳过时一个 tick 后仍出图）。`plot_channels_preserving_xlim` 在捕获到 xlim 时传 True；`MainWindow._plot_time_on_canvas` 增加同名参数，`_render_view_to_canvas` 在 `state.xlim is not None` 时传 True。**普通 `plot_channels`（默认 False）行为零变化**——`_set_xrange_to_data_union` blockSignals 不调度刷新，bind envelope 就是首帧，必须保留。
- 验收：preserving 路径零次 `build_envelope` 全量调用且 flush 后曲线非空；普通路径 bind envelope 照常；`test_pg_timedomain_canvas.py::...preserving_xlim` 既有用例全绿。

### A10 overlay 模式 cursor 竖线 3N → 3
- 现状：`cursor._ensure_cursor_items` 按 `axes_list` 每 handle 建一根 InfiniteLine；overlay 的 N 个 aux ViewBox 完全重叠共享 X 变换，N 根线画在同一屏幕位置（hover/单/双 cursor 最多 3N 根）。
- 要求：overlay 模式竖线只挂 X-master（`_cursor_line_handles()` helper：overlay → `[x_master]`，否则 `axes_list`）。**双 cursor 极值 marker（`_ensure_dual_cursor_extreme_markers`）不动**——它画 Y 值，必须留在各通道自己的坐标系。
- 验收：overlay 3 通道时 `_cursor_line_items` 长度 1，subplot 3 行时长度 3；cursor 视觉/读数行为不变。

## 4. 需求清单（Wave B：内核精简，功能零变化）

### B1 高确定性死代码删除（~117 行）
零引用已 AST+grep 验证（删除前仍须逐项 grep 复核）：

| 项 | 位置 | 备注 |
|---|---|---|
| `edit_axis_dialog()` | `ui/_axis_interaction.py:81-110` | matplotlib 旧轴编辑入口 |
| `AxisEditDialog` 类 | `ui/dialogs.py:467-512` | 级联死（唯一消费者是上一项） |
| `TimeChartCard.mount_view_tabbar()` | `ui/chart_stack.py:1536-1541` | **保留 :1534 `self.view_tabbar = None`**（测试断言） |
| `ChartStack.take_time_hint_bar()` | `ui/chart_stack.py:2164-2166` | 死转发壳 |
| `MainWindow.close_active()` | `ui/main_window.py:1446-1447` | 无接线 |
| `MainWindow._on_span()` | `ui/main_window.py:1700-1703` | SpanSelector 已退役；`span_selected` 信号全仓无 connect |
| `MarkupEditor._apply_style()` | `ui/markup/editor.py:1119-1120` | 死壳 |
| `_position_inside_label_items()`（复数版） | `ui/pg_canvas/canvas.py:1785-1787` | 单数版才是活的 |
| `ViewManager.has_split_pair()` | `ui/view_state.py:242-243` | 调用方都用 `partner_for()` |
| `_ElidedLabel.fullText()` | `ui/file_navigator.py:28-29` | 非 Qt 虚函数 |
| `set_files_source()` | `ui/drawers/batch/input_panel.py:195-197` | setter 从未被调 |
| pyflakes F401/F841 确认项 | dialogs.py:34、markup/editor.py:7、main_window.py 顶部、pipeline_strip.py:37、widgets/__init__.py:299 | **不碰** `_binding` import、`positions_envelope`/`build_envelope` re-export、pg_canvases.py 全部 F401 |

注意：`inspector_sections.set_range_from_span` 在删 `_on_span` 后成为「仅测试引用」，本批**不删**（动测试需单独决策）。

### B2 `_CanvasBackref` 六合一（~200 行）
六份逐字拷贝（renderer 版缺 `_owned_names` 分支，是其余的真子集）→ 新建 `ui/pg_canvas/_backref.py` 放超集版（quality.py 那份），六模块改 import。已验证 tests/ 无按模块路径 monkeypatch `_CanvasBackref`。

### B3 `_subplot_ylabel_text` / `_view_state_channel_key` 双定义收敛（~13 行）
canvas.py:115-127 与 overlay_axes.py:42-54 逐字相同 → 新建 `ui/pg_canvas/_shared.py`，两边 import。**canvas 模块属性必须保留**（`pg_canvases.py:16` shim 从 canvas re-export `_view_state_channel_key`）——用 `from ._shared import ...` 即可保住。不能让 overlay_axes import canvas（会成环：canvas → overlay_axes）。

## 5. 后续批次（本 spec 之外，按优先级）

1. **overlay 合成曲线层 spike**（高收益高风险）：单个挂 X-master 的自绘 QGraphicsItem 顺序画 N 通道（共享 X 变换 + per-channel Y 仿射），解锁 overlay 离屏缓存与 capped-dpr 光栅。唯一同时打「CPU 光栅 + dpr²」根因且保 `grab_pixmap` 的方向。前置：先把 `_propagate_xlim_to_siblings` 与 `_sync_overlay_aux_viewboxes` 两条 aux-vb X 写路径收敛为单 owner。必须先建 grab 导出回归。
2. **导出链 `QWidget.grab()` → `QGraphicsScene.render()`**：OpenGL 可切换的前置条件（GL viewport 不可 grab 即上次导出全白的原因）。
3. **min-max pyramid**：只治全景 pan 的 O(n_total)/tick 数据准备，对光栅瓶颈无效，排在 1/2 之后。插入点 `renderer.py` `positions_envelope` 调用处；失效钩子 `invalidate_envelope_cache` 已在。
4. **fft→time 切换 dirty flag**（main_window.py:790-791 无条件 rebuild）。
5. **`draw_idle` 收窄为按 ViewBox 失效**（cursor.py:243-248 全幅 update 被 overlay Y 拖动/滚轮/snap 动画每帧调用）。
6. **刷新调度状态收归 Renderer `_owned_names`**（pending flag/timer/flush 现散落 canvas/renderer 两处三个位置）。
7. **mpl `TimeDomainCanvas` 退役**（~1000 行 + 解除 PG 启动路径的 matplotlib import）：需先决策 parity 测试策略；死渲染管线（`_curve_path_cache` 从无写入 + painter-path 三件套 ~150 行）随之一并处置。
8. **`inspector_sections.py` 三个 Contextual 类 Mixin 化**（~250 行）；`exit_split` 释放副 canvas 数据。

## 6. 全局验收与回归策略

- 每个任务独立 commit，TDD（可行处先写失败测试）；新测试集中在 `tests/ui/test_timedomain_hotpath_perf.py`。
- 每任务后跑定向套件；每个 Wave 结束跑 `python -m pytest tests/ui -q`；全部完成跑 `python -m pytest tests -q`（默认排除 slow 标记）。
- 行为红线：曲线像素结果、刻度文本、cursor 读数、导出图像、quality 点稳态颜色、xlim/ylim 恢复语义全部不变。任何测试失败先按 systematic-debugging 找根因，禁止为过测而弱化断言；测试若编码的是「调度时序」实现细节（A2），仅修正时序假设并注明。
- 性能抽查（手动，非阻塞）：5 通道 2M 点文件，对比改前后 (a) 勾选/取消通道耗时 (b) 拖动流畅度 (c) 窗口拖边。预期 (a) 近半，(b)(c) 明显改善但光栅瓶颈仍在（属后续批次）。
