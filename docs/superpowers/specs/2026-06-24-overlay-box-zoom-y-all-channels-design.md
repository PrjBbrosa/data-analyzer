# overlay 框选缩放：同步缩放所有通道的 Y

**日期**：2026-06-24
**状态**：已确认设计，待实现
**改动面**：单函数 `OverlayAxisManager._apply_overlay_box_zoom_y`（`mf4_analyzer/ui/pg_canvas/overlay_axes.py`）+ 对应测试

## 背景 / 问题

多视图叠加（overlay）模式下，用工具栏放大镜（框选缩放，`pg.ViewBox.RectMode`）拖框，**只缩 X 不缩 Y**。

根因在 `_apply_overlay_box_zoom_y`（`overlay_axes.py:853-905`）：
- overlay 各通道量纲不同（方向盘扭矩 Nm、电机转速 rpm、电流 A…），共用一套 `[0,1]` 的屏幕网格层（X-master ViewBox 的 Y 被锁在 `[0,1]`）。
- 框选拖拽发生在 X-master 上，框出的 Y 落在 `[0,1]` 网格坐标里，函数先把 X-master 的 Y 锁回 `[0,1]`（line 870-871），再 **只对"当前选中通道" `sel`** 把框的 Y 比例映射到它的数据 ylim（line 892-901）。
- `if sel is None: return`（line 874-878）——**没选中任何通道时 Y 直接丢弃，只剩 X 生效**。这就是用户看到的"只缩 X"。

## 目标

overlay 框选时：X 共享缩放（已有，保持）+ **所有通道各自按框的屏幕比例同步缩 Y**（"框啥得啥"），**不需要先选中通道**。

## 非目标

- 不改非 overlay 单通道（pyqtgraph 原生 RectMode 已同时缩 X/Y，不碰）。
- 不改 X 缩放、滚轮手势（含滚轮 `Shift` 缩 Y 的 overlay 分支 `overlay_axes.py:1315-1363`）。
- 不改"选中通道"的其它用途（曲线强调显示 `_apply_overlay_emphasis`、滚轮在 Y 轴栏单通道缩放）。
- **不额外加 margin**（已与用户确认）。

## 设计

### "框啥得啥"在 overlay 的含义

框出的是屏幕高度上的一段比例 `[f0, f1]`（0=底、1=顶）。对每条曲线，按这个比例切它当前可见的 ylim `[clo, chi]`：

```
span   = chi - clo
new_lo = clo + f0 * span
new_hi = clo + f1 * span
```

每条曲线都收窄到"框住的那段屏幕高度对应的它自己的数据段"——视觉上即框啥得啥。各通道量纲不同，但都按同一屏幕比例切自己的范围，物理上自洽。

### 改动：`_apply_overlay_box_zoom_y`

1. **保留**：overlay 守卫、取 X-master handle、读框后的 X-master Y 范围 `[y0, y1]`、把 X-master Y 锁回 `[0,1]`（line 870-871）、`already_locked` 早退（框未真正改 Y 时不动）。
2. **保留**：把 `[y0, y1]` clamp 成屏幕比例 `f0, f1 ∈ [0,1]`（line 879-880）；框太矮 `f1 - f0 < 1e-6` → 只缩 X，直接 `draw_idle` 返回（line 881-884）。
3. **改**：删掉 `sel = self._selected_overlay_axes(); if sel is None: return`。改成**遍历 `self.axes_list`** 里每个非空通道 handle（与滚轮 overlay 分支 `overlay_axes.py:1308` 同一来源、同一遍历方式，保证手势一致）。
4. **抽 helper** `_frame_channel_y_to_box(handle, f0, f1, n)`，把现有 line 886-901 对单通道的"读 ylim → 按比例切 → `_frame_to_nice(new_lo, new_hi, n)` → `set_ylim` + 设 Y 轴刻度（`maxTickLevel=0` + `setTicks`）"逻辑收进去。循环里对每个通道调用它，复用而非复制。
5. 每个通道独立 try/except：取数失败 / `span` 非有限或 ≤ 0 → `continue` 跳过该通道，其它照常。
6. 末尾 `self._refresh = True; self.draw_idle()`（保持）。

`n = self._current_overlay_divisions()`（line 894）所有通道共用 → `_frame_to_nice` 后各通道 ylim 虽不同，但都切成同样 n 格 → 共享水平网格线视觉对齐不变。margin = 0，留白由 `_frame_to_nice` 的整刻度向外取整天然提供。

## 边界

| 情况 | 行为 |
|------|------|
| 框太矮（`f1-f0 < 1e-6`） | 只缩 X，所有通道 Y 不变 |
| 某通道取数失败 / `span ≤ 0` | 跳过该通道，其它通道照常缩 |
| 无通道 / 框未真正改 Y（`already_locked`） | 等同旧行为，仅 X |
| 非 overlay 单通道 | 不走本函数，pyqtgraph 原生已 X/Y 同缩 |

## 要验证的回归点

框选缩 Y 后按 **Home** 仍能复位所有通道 Y（overlay 复位逻辑在 `canvas.py:1519 / 1573` 一带）。改完手动 + 单测确认未破坏。

## 测试（pytest-qt，`tests/ui/test_overlay_grid_ticks.py`）

现有 3 个测试编码旧契约，需调整：

1. `test_box_zoom_locks_xmaster_y_and_zooms_selected_channel`（line 376）—— 旧断言"未选中的 ch1 不动"（line 408-409）。**改写**：框选后 **ch0 与 ch1 都按比例收窄**（断言两者 span 都 < 原 span，且都落在框的中段区域）；X-master Y 仍锁回 `[0,1]`、网格线数不变、X 仍缩这几条保留。重命名为 `test_box_zoom_zooms_all_channels`。
2. `test_box_zoom_no_selection_is_x_only`（line 411）—— 旧断言"没选中只缩 X"。**改写**为 `test_box_zoom_no_selection_zooms_all_channels`：`select_overlay_channel(None)` 后框选，**所有通道 Y 都收窄**，X-master Y 仍锁回 `[0,1]`。
3. `test_box_zoom_override_calls_y_handler_only_on_xmaster_finish`（line 431）—— 只测 dispatch 路由（RectMode finish 才调 handler），改动不碰路由，**保持不变**。

新增（可选，若 helper 行为值得单独锁）：
- 框太矮 → 所有通道 ylim 不变（只缩 X）。
- 某通道数据异常 → 跳过该通道、其它通道仍缩。

全量 `pytest`（默认 `-m "not slow"`）零回归。
