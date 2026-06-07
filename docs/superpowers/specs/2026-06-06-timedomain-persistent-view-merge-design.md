# 时域多 View 持久合并与双栏状态同步 — 设计

- 日期：2026-06-06
- 范围：时域 View 标签、多 View 合并显示、双栏交互状态同步
- 状态：设计草案，待用户 review 后再进入实现
- 前置背景：`docs/superpowers/specs/2026-06-04-timedomain-view-tabs-design.md`

## 1. 背景

2026-06-04 的 View tabs 实现已经把单个时域 view 抽象成 `ViewState`，并提供了单画布切换与两个 view 并排对比的基础能力。当前实现的 split 更接近「一次性对比」：`ViewManager.split_with` 是活动 view 上的临时状态，切换 view 时会被清掉；副栏 canvas 也没有稳定绑定到它代表的 `ViewState`。

用户反馈的三个现象都指向同一个根因：

1. View 1 和 View 2 合并后，在 View 2 页面调整 View 1 的叠加/分屏，副栏会改画成 View 2，最终两栏都是 View 2 的曲线。
2. View 1 和 View 2 合并后，切到 View 1 再回 View 2，合并显示没有保持。
3. 两个 view 合并后，对其中一个 pane 缩放、平移、调整坐标，应该写回它原本的 view；之后打开该 view 应保持这个变化。

## 2. 当前证据与根因

### 2.1 副栏重绘仍依赖全局勾选状态

`MainWindow._plot_time_on_canvas()` 虽然能按目标 canvas 读取自己的分屏/叠加模式，但通道仍来自全局 navigator：

- `main_window.py:1288-1307`：`checked = self.channel_list.get_checked_channels()`，随后 `mode = self.chart_stack.plot_mode_for_canvas(canvas)`。
- `main_window.py:664-680`：`_replot_secondary_preserving_xlim()` 直接调用 `_plot_time_on_canvas(secondary, update_primary_ui=False)`。

因此，active View 2 页面中重绘 View 1 的副栏时，副栏使用的是 View 2 当前投影到全局控件里的通道集合。

### 2.2 split 是临时状态，切换 view 会主动清除

- `view_state.py:192-199`：`ViewManager.set_active()` 在 active 变化时清 `split_with` 并发 `split_changed(None)`。
- `main_window.py:425-433`：`_switch_view()` 切换前也会 `set_split(None)`。
- `tests/ui/test_split_routing.py:71-90` 当前测试明确断言「切换 view 后 split 退出」。

这说明问题 2 不是偶发 bug，而是旧设计语义与新需求冲突。

### 2.3 secondary pane 没有 view 归属，范围变化不会写回原 view

- `view_bridge.py:43-64` 的 `capture_view(window)` 只从全局 navigator、`chart_stack.canvas_time` 和 inspector 采集。
- `main_window.py:415-423` 的 `_capture_current_view()` 只捕获 active view。
- `main_window.py:411-413` 当前只连接了主 canvas 的 `xrange_changed`；Y 范围没有通用用户变化信号。

所以 secondary pane 的 zoom/pan/ylim 调整没有稳定路径写回它代表的 ViewState。

## 3. 目标

1. 合并关系常驻保持：View 1 和 View 2 合并后，切到 View 1 或 View 2 都显示这一对；切到未合并的 View 3 时显示单栏，回到 View 1 或 View 2 时自动恢复合并。
2. 每个 pane 永远绑定一个明确的 `ViewState`：primary pane 绑定 active view，secondary pane 绑定 active view 的合并伙伴。
3. 分屏/叠加、游标、通道勾选、坐标/范围设置、缩放/平移，都作用于当前聚焦 pane，并写回该 pane 绑定的 `ViewState`。
4. secondary pane 重绘必须从自己的 `ViewState` 取通道、颜色、plot mode、axis opts、overlay primary、xlim/ylims，不得从 active view 的全局状态偷取。
5. 增加取消合并入口，位置与合并入口保持一致，同时给用户一个可见的当前合并状态。
6. 保持 2026-06-04 View tabs 已有能力：单 view 切换、复制、删除、重命名、排序、改色、split 焦点路由、游标 pill 保存。

## 4. 非目标

- 不做跨会话 project 落盘。
- 不支持超过两个 view 的多宫格合并。
- 不把 FFT / 阶次 / FFT-vs-Time 纳入 view 合并。
- 不重构整个 `plot_time` 数据管线；本期只加必要的 view-state 渲染入口和 pane 绑定。
- 不改变未合并单 view 下的现有交互语义。

## 5. 用户体验设计

### 5.1 合并语义

把「与此 View 并排」升级为「两个 view 的持久合并关系」：

- 在 View 2 上选择「与 View 1 并排」后，关系为 `View 1 <-> View 2`。
- 当前 active 是 View 2：primary pane 显示 View 2，secondary pane 显示 View 1。
- 当前 active 是 View 1：primary pane 显示 View 1，secondary pane 显示 View 2。
- 当前 active 是未合并的 View 3：显示单栏，但 View 1 与 View 2 的关系仍保留。
- 回到 View 1 或 View 2：自动恢复双栏。

### 5.2 控件跟随焦点 pane

split active 时，点击某个 pane 后：

- pane 边框高亮仍表示焦点。
- 通道列表、分屏/叠加按钮、游标按钮、Inspector 时域坐标设置，投影为该 pane 绑定 view 的状态。
- 用户改通道勾选、叠加/分屏、游标、坐标设置后，写回该 pane 的 `ViewState`。
- 重绘只发生在该 pane；另一 pane 不被污染。

这解决「在 View 2 页面调整 View 1」的歧义：用户先点击 View 1 所在 pane，左侧/顶部/右侧控件就是在编辑 View 1。

### 5.3 取消合并入口

采用两个入口，主入口与现有习惯一致，辅助入口提高可见性：

1. **View 标签右键菜单**：已合并 view 的菜单里显示 `取消合并`，放在原 `与此 View 并排` 的同一位置。未合并且不是 active 自身时显示 `与此 View 并排`。
2. **View tabbar 右侧状态片**：split active 且 active 有合并伙伴时显示 `合并: View 2 + View 1  ×`。点击 `×` 取消当前合并关系。

状态片属于 View tabbar，不放进图表画布内部，因为合并关系是 view 层级状态，不是某条曲线或某个坐标轴的设置。

## 6. 状态模型

### 6.1 ViewManager 增加持久 pairing

现有字段保留：

```python
views: list[ViewState]
active: int
split_with: int | None
```

新增字段：

```python
_split_pairs: dict[int, int]
```

`_split_pairs` 是对称映射。若 View 1 与 View 2 合并，则内部保存：

```python
{0: 1, 1: 0}
```

`split_with` 不再是唯一真相源，而是「当前 active view 的 partner 快照」。这样可以少改现有 `split_changed` 接线。

### 6.2 ViewManager API

```python
def partner_for(self, idx: int) -> int | None
def set_split(self, idx: int | None) -> None
def clear_split_for(self, idx: int | None = None) -> None
def has_split_pair(self, idx: int) -> bool
```

语义：

- `set_split(idx)`：把 `active` 与 `idx` 设为一对；若 active 已有旧 partner，先清旧关系。
- `set_split(None)`：清 active 的合并关系。
- `clear_split_for(idx)`：清指定 view 的合并关系；`idx is None` 时清 active。
- `set_active(idx)`：不再清 pair，只更新 `active`，然后把 `split_with` 同步为 `partner_for(active)`。
- `delete_view(idx)`：删除该 view 相关 pair，并把剩余 pair index 重新映射。
- `reorder(from_idx, to_idx)`：保持 pair 跟着 view 对象移动，而不是跟着旧下标漂移。
- `duplicate(idx)` / `new_view()`：新 view 默认未合并。

## 7. Pane 绑定模型

在 `MainWindow` 中维护当前渲染绑定：

```python
_primary_view_idx: int | None
_secondary_view_idx: int | None
_focused_view_idx: int | None
```

派生规则：

- single mode：`primary = active`，`secondary = None`，`focused = active`。
- split mode：`primary = active`，`secondary = view_manager.split_with`。
- focus primary：`focused = primary`。
- focus secondary：`focused = secondary`。

辅助方法：

```python
def _view_index_for_canvas(self, canvas) -> int | None
def _canvas_for_view_index(self, idx: int)
def _focused_view_state(self) -> ViewState | None
def _capture_focused_view(self) -> None
def _project_view_controls(self, idx: int) -> None
def _render_view_to_canvas(self, idx: int, canvas, *, update_primary_ui: bool) -> None
```

原则：

- canvas 渲染使用 canvas 绑定的 view state。
- 全局控件显示 focused view state。
- 切换 focus/tab/split 前先 capture 当前 focused view，避免丢状态。

## 8. Bridge 责任调整

`view_bridge.py` 从「只捕获 active primary」扩展为三类小函数：

```python
def capture_controls_into(state: ViewState, window) -> None
def apply_controls_from_state(state: ViewState, window) -> None
def capture_canvas_ranges_into(state: ViewState, canvas) -> None
```

保留兼容函数：

```python
def capture_view(window) -> ViewState
def capture_into(state, window) -> None
def apply_view(state, window) -> None
def restore_axes(state, window) -> None
```

新旧关系：

- `capture_into(state, window)` = `capture_controls_into(state, window)` + 从 primary canvas 捕获 ranges。
- `apply_view(state, window)` = `apply_controls_from_state(state, window)`。
- secondary re-render 不直接读全局 active state；它先 `apply_controls_from_state(secondary_state)`，调用现有 `_plot_time_on_canvas(secondary)`，再把控件投影回 focused view。

这是最小改法：复用现有 plot 管线和 custom X/range filter 逻辑，避免一次性拆大函数。

## 9. 重绘与同步数据流

### 9.1 切换 view

1. `_capture_focused_view()`。
2. `view_manager.set_active(idx)`。
3. `_sync_pane_bindings_from_manager()`：
   - 若 active 有 partner：`chart_stack.enter_split()`。
   - 否则：`chart_stack.exit_split()`。
4. `_render_view_to_canvas(active, primary_canvas, update_primary_ui=True)`。
5. 若有 partner：`_render_view_to_canvas(partner, secondary_canvas, update_primary_ui=False)`。
6. 焦点默认回 primary，`_project_view_controls(active)`。

### 9.2 切换 pane 焦点

1. `_capture_focused_view()` 捕获旧 focused view 的控件状态。
2. 更新 `_focused_view_idx`。
3. `_project_view_controls(new_focused_idx)`。
4. 不重绘，仅同步控件与焦点边框。

### 9.3 通道勾选变化

1. focused view 必须已投影到控件。
2. `_ch_changed()` 调 `capture_controls_into(focused_state, window)`，写入该 view 的 checked/colors。
3. `_render_view_to_canvas(focused_idx, focused_canvas, update_primary_ui=(focused_canvas is primary))`。
4. 渲染结束后 `_project_view_controls(focused_idx)`，保证控件仍显示正在编辑的 pane。

### 9.4 分屏/叠加变化

1. `_on_plot_mode_changed(mode)` 找到 focused view。
2. 写 `focused_state.plot_mode = mode`。
3. 捕获当前 focused canvas 的 xlim/ylims。
4. 重绘 focused canvas，恢复可见范围。
5. 不影响另一 pane。

### 9.5 游标模式变化

1. 写 `focused_state.cursor_mode = mode`。
2. 只对 focused canvas 调 `set_cursor_visible` / `set_dual_cursor_mode`。
3. 保持现有 cursor pill snapshot/restore 测试不回退。

### 9.6 缩放/平移/Y 轴调整

新增 canvas 级范围变化通知：

```python
visible_range_changed = pyqtSignal()
```

触发点：

- X range 变化后，沿用现有 `_emit_xrange_changed` 的位置额外发 `visible_range_changed`。
- Y range 变化后，在 wheel Y、overlay Y drag、`restore_visible_ylims`、其他显式 `set_ylim` 用户交互路径发 `visible_range_changed`。

MainWindow 连接 primary 和 secondary：

```python
canvas.visible_range_changed.connect(
    lambda c=canvas: self._capture_canvas_ranges_for_bound_view(c)
)
```

捕获时根据 `_view_index_for_canvas(canvas)` 写回对应 `ViewState.xlim` / `ViewState.ylims`。若 `_applying_view` 为 True，则跳过，避免 apply/render 期间自我覆盖。

## 10. 取消合并数据流

右键菜单或状态片触发：

1. `_capture_focused_view()`。
2. `view_manager.clear_split_for(idx)`。
3. 若当前 active 属于被取消 pair：`chart_stack.exit_split()`，`_secondary_view_idx = None`，focused 回 active。
4. `_render_view_to_canvas(active, primary_canvas, update_primary_ui=True)`。
5. `_project_view_controls(active)`。

取消后两个 view 的各自状态保留，只是不再并排显示。

## 11. 测试策略

### 11.1 红灯回归测试

先新增或改写以下测试，确认当前实现失败：

1. active View 2 + split View 1，聚焦 View 1 pane 后切换叠加/分屏，secondary 仍显示 View 1 通道，不变成 View 2。
2. View 1 和 View 2 合并后，在两者之间切换，split 始终保持；切到未合并 View 3 为单栏，切回 View 1/2 恢复双栏。
3. secondary pane 缩放/平移后，View 1 的 `ViewState.xlim` / `ylims` 更新；之后单独打开 View 1 范围保持。
4. 右键菜单和 tabbar 状态片都能取消合并。

### 11.2 保留既有测试

现有测试中明确断言 split 切换退出的用例要改成新语义；其他测试应继续保留：

- `tests/ui/test_view_switch_integration.py`
- `tests/ui/test_split_routing.py`
- `tests/ui/test_split_focus_routing.py`
- `tests/ui/test_split_per_pane_controls.py`
- `tests/ui/test_view_tabbar.py`

### 11.3 人工视觉验证

完成实现后需要实际 TraceLab 窗口验证：

1. View 1 选 speed，View 2 选 torque，在 View 2 下合并 View 1。
2. 点击 View 1 pane，切换叠加/分屏，确认该 pane 仍是 speed，View 2 pane 仍是 torque。
3. 切到 View 1，再切回 View 2，确认合并关系常驻。
4. 对 View 1 pane 缩放/平移，再单独打开 View 1，确认范围保持。
5. 用右键菜单和状态片分别取消合并。

## 12. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 临时 apply secondary state 污染 active UI | 渲染后总是 `_project_view_controls(focused_idx)`；保留 `test_split_render_does_not_pollute_active_view_ui` 并扩展到 focused 控件 |
| focus 切换时全局控件代表哪个 view 不清晰 | 明确规则：split active 时全局控件永远代表 focused pane |
| pair index 在删除/排序后错位 | `ViewManager` 用 view 对象身份重排 pair；新增 reorder/delete pair 测试 |
| Y 范围没有信号导致状态不同步 | 新增 `visible_range_changed` 并覆盖 X/Y 用户交互路径 |
| 重绘 secondary 过重 | 本期接受 temporary apply + restore；max 2 pane、max 6 view，优先正确性 |
| 旧测试与新语义冲突 | 明确改写旧的 "switch exits split" 测试，不静默删除覆盖 |

## 13. 验收标准

- 三个用户反馈现象均有自动回归测试覆盖。
- split pair 在 View 1/View 2 间切换时保持，在未合并 view 上隐藏但不丢关系。
- 任何 pane 的通道、plot mode、cursor mode、xlim、ylims 改动都写回对应 `ViewState`。
- secondary 重绘不再使用 active view 的 checked channels。
- UI 有明确取消合并入口。
- focused UI 控件与 pane 绑定一致，没有出现“控件显示 View 2，实际在改 View 1”的状态。
