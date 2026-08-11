# Plan: FFT 时域预览对齐 TimeDomain 叠加（overlay）逻辑

日期：2026-08-12  
范围：`mf4_analyzer/ui/pg_canvas/line_canvas.py` + `tests/ui/test_pg_line_canvas.py`  
对照：`canvas.py` / `overlay_axes.py` 的 `set_tick_density` → `_repin_overlay_channel_ticks`、`fit_y_to_visible_x`

## 0. 是否改善？

**是，只会更好或持平，不会更差。**

| 现状 | 对齐后 | 用户影响 |
|------|--------|----------|
| 调 Y 疏密 → 全曲线 Y reframe，冲掉当前缩放 | 从**当前 Y 范围** repin（同 overlay） | 疏密只改格子密度，不再偷改范围 |
| Y 适应 → fit 可见 X 后立刻全数据 reframe | fit 后对**已 fit 的范围** repin | Y 适应真正生效 |
| 首次绘图 / 查看全部 | 仍走全数据 `_reframe` | 复位语义不变 |

唯一行为变化：以前误把「调疏密」当成软 Y 复位的用户，需改用 Y 适应 / 查看全部——这与 TimeDomain 一致，是纠正而非回退。

## 1. 目标

把 FFT 下图（`_plot_time`）的 **Y 疏密 / Y 适应 / 格子钉轴** 对齐 TimeDomain overlay 堆叠后的契约：

1. **全量 reframe**（`_reframe_time_y_to_grid`）：仅用于新数据、空→有、查看全部、显式复位。
2. **当前范围 repin**（新建 `_repin_time_y_to_grid`，镜像 `_repin_overlay_channel_ticks`）：用于 `set_tick_density`、Y 适应收尾、Shift 滚轮后已有路径保持。
3. X 密度：继续走 `_apply_target_bottom_ticks`；补回归，确保目标数量在矮预览条上可见生效（失败不得 silently 刷出过密标签而不告警——优先修好拟合/回退）。

非目标：不改 FFT 可见 X = 分析窗的数据契约；不合并进 `TimeDomainCanvasPG` 类。

## 2. Tasks

### T1 — 拆分 reframe / repin

- 抽取 `_pin_time_axis_ticks(vb, axis, bottom, top, n)`：设 Y、写 `setTicks`、关 SI。
- `_reframe_time_y_to_grid`：每条曲线 **全长** Y → `_frame_to_nice` → pin + `_build_time_y_grid`（保持现语义，供 plot / reset）。
- 新增 `_repin_time_y_to_grid`：读**当前** `viewRange()[1]`，按 overlay 同款逻辑（当前 per_div 已是 nice 则只重钉；否则 `_frame_to_nice(lo, hi, n)`）→ pin + rebuild grid。`n = _effective_time_divisions()`。

### T2 — 接线改调用方

- `set_tick_density`：`_time_divisions = …` 后改调 `_repin_time_y_to_grid()`（禁止全量 reframe）。
- `_fit_y_to_visible_x(time)`：`setYRange(fit)` 后改调 `_repin_time_y_to_grid()`。
- `plot_*` / `_reset_time_preview_to_extents` / `reset_view_to_data_extents`：仍 `_reframe_time_y_to_grid()`。

### T3 — X 密度矮条回归

- 在已实现 geometry 的预览条上：设 X 目标=10、缩窄 X 窗后，主刻度数量应接近目标且无文字互叠（用现有 `_apply_target_bottom_ticks`；若回退 density 路径产生 >2×target 标签则修回退条件或强制再试更粗 step）。

### T4 — 测试

- 调 Y 疏密：Y 范围（中心/跨度量级）保持，仅 tick 数随 `n` 变。
- Y 适应：可见 X 内平台段 → Y 紧贴该段，不再回到全曲线含上升沿的大跨度。
- 既有 share-grid / shift-wheel / height-cap 用例仍绿。

## 3. 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py -q
```

## 5. Follow-up（2026-08-12 同日）：overlay 网格 / 右轴 / 设为左轴

已落地（与 TimeDomain overlay 同契约，非整类合并）：

- 时域预览关闭原生 Y `showGrid`，只保留 fractional `_build_time_y_grid`（消双网格）
- 拖动/缩放结束后 idle `_repin_time_y_to_grid`（刻度不再缺）
- 右轴 aux ViewBox `mouseEnabled(y=True)`（轴槽可拖该通道 Y）
- 预览右键「设为左轴」→ `promote_time_entry_to_left`（通道树「设为左轴」仍只服务 TD overlay，不冒充）
