# Feedback & Presets Iteration Report

**Date:** 2026-04-25
**Scope:** Inspector presets (3 named slots per FFT/Order context),
cursor value color, FFT autoscale logic, mode-area tinting, Y-axis unit
chip, and a unified non-blocking toast system covering action feedback
across the application.
**Status:** Implemented; AST verified; not run interactively in this
environment (no PyQt5/numpy locally).

## Why this iteration

The user surfaced five pain points across four turns:

1. Cursor read-out values rendered in a single neutral color, even when
   plotted channels each have their own color → hard to map the number
   back to its trace.
2. The "自适应频率范围" (FFT autoscale) checkbox could produce a
   *worse* range than not checking it at all.
3. The mode-specific Inspector areas (FFT and Order) were visually
   indistinguishable from the persistent top — users had no cue that
   those controls "belong to" the current analysis mode.
4. The Y axis title bundled `(unit)` into the rotated label, but there
   is no horizontal unit chip at the top of the axis the way professional
   tools (Origin, PicoScope) draw it.
5. Most action buttons gave no visible acknowledgement — copy-as-image,
   export, file load/close, FFT/Order completion, cursor reset, etc.
   The status bar message at the bottom was easy to miss, and the
   modal `QMessageBox.information` for export was intrusive.

A follow-up turn requested two refinements once the toast system was in
place:

6. Toasts disappeared too quickly to read.
7. The three preset slots needed user-supplied names (right-click rename),
   plus a clear / discard affordance.

## What changed

### Cursor color matches channel color
*Files:* `ui/canvases.py`, `ui/chart_stack.py`

- `_update_single` now emits HTML; each `name=value` segment is wrapped
  in a `<span style="color:{channel_color};">` so the floating cursor pill
  reads the same color as the line.
- `_update_dual` passes the channel `color` into the dual-readout tuple;
  `_format_dual_html` colors the bold channel name and the four
  Min/Max/Avg/RMS numeric cells with that color. The header label
  (Min/Max/Avg/RMS) stays grey for legibility.
- `CursorPill._primary` switched to `Qt.RichText` so HTML actually renders.

### FFT autoscale — robust low-frequency-friendly cutoff
*File:* `ui/main_window.py::_fft_auto_xlim`

The previous algorithm computed the 99% cumulative-energy frequency.
That is dominated by the DC bin and large low-frequency components, and
collapses the window to a tiny range. The replacement:

1. Skip index 0 (DC).
2. Find the **highest** index where amplitude ≥ 1% of the max amplitude
   in the non-DC body.
3. Multiply by 1.3× margin.
4. Clamp to Nyquist.
5. Round up to the 1/2/5×10ⁿ nice-number ladder.

This matches what a user actually wants: "show me everything that has
non-trivial energy, plus a bit of headroom."

### Mode-area tinting for FFT/Order
*Files:* `ui/inspector_sections.py`, `ui/style.qss`

- `FFTContextual` and `OrderContextual` set `objectName` and
  `WA_StyledBackground` so QSS background takes effect.
- QSS adds two subtle tinted cards: FFT light blue (`#eef4ff`,
  `#dde7f5` border), Order light warm (`#fff5e8`, `#f1e3cf` border),
  both with 10px rounded corners and 10/8 padding. Inner `QGroupBox`
  remains transparent so the tint shows through and inputs still read
  on white.

### Y-axis unit chip
*File:* `ui/canvases.py`

- `_compact_axis_label` no longer appends `(unit)`.
- `_set_series_ylabel(ax, label, color, labelpad, unit, side)` now
  draws a horizontal unit chip at the very top of the axis using
  `ax.text(transAxes, x=0/1, y=1.012, ha=side, va='bottom')`. Color
  matches the channel; rotation is 0 (the label below remains rotated 90°).
- All three plot modes (subplot per channel, overlay with twinx,
  single-channel) pass the right `side` so the chip sits above the
  matching spine. For `outward`-shifted twinx spines (≥3rd channel),
  the chip stays at the axes-rect right edge — close enough to be
  readable, not perfectly aligned with the moved spine.

### Preset bar (3 named slots) — FFT and Order
*Files:* `ui/inspector_sections.py` (`PresetBar` class), `ui/inspector.py`,
`ui/style.qss`

- Two-row 3-column grid inside a "预设配置" group:
  - Top row: load buttons; show the slot name; disabled (dashed
    border) when the slot is empty.
  - Bottom row: `存为 1/2/3` save buttons; secondary visual weight.
- **Storage** via `QSettings("MF4Analyzer", "DataAnalyzer")`:

  ```json
  {"name": "<user name>", "params": {...}}
  ```

  with backwards-compat read for the flat-dict legacy format.
- **Naming**: right-click a load button → context menu「重命名…」/「清空」.
  Both are disabled when the slot is empty (rename has nothing to
  rename onto; clear has nothing to clear). Names are clamped to 12
  chars to keep buttons in the 3-column grid.
- **What is saved:** spectral params and options only. Signal source /
  Fs / RPM channel are intentionally *not* persisted because they
  follow the active file; recalling a preset against a different file
  must use that file's signal source, not the one captured a week ago.
  - FFT: `window`, `nfft`, `overlap`, `autoscale`, `remark`.
  - Order: `rpm_factor`, `max_order`, `order_res`, `time_res`,
    `rpm_res`, `nfft`, `target_order`.
- **Feedback:** the bar emits `acknowledged(level, msg)` →
  `Inspector.preset_acknowledged` → `MainWindow.toast(msg, level)`.

### Toast system
*Files:* `ui/widgets.py` (`Toast` class), `ui/main_window.py`,
`ui/style.qss`

- `Toast` is a single floating pill bottom-center of the main window:
  white card with a circular semantic icon (✓ / ! / ✕). Four levels
  drive both border/background tint and icon color via QSS
  `level` properties.
- One toast at a time per parent: a new message replaces the current
  one instead of stacking, so the bottom edge stays calm.
- Fades in/out with `QGraphicsOpacityEffect` + `QPropertyAnimation`
  (180ms).
- Hold durations after the duration tweak: info/success 3500ms,
  warning 5000ms, error 7000ms.
- `MainWindow.toast(msg, level='info')` is the single entry point;
  `resizeEvent` recenters when visible.

### Action feedback coverage

| Action | Before | After |
|---|---|---|
| 复制为图片 | statusBar (one-shot) | + Toast `success` |
| 导出 Excel 成功 | `QMessageBox.information` (modal) | Toast `success` (non-blocking) + statusBar |
| 重置游标 | statusBar | + Toast `info` |
| 应用横坐标 | statusBar | + Toast `success`; validation warnings → Toast `warning` |
| 重建时间轴 | statusBar | + Toast `success` |
| 编辑通道完成 | statusBar | + Toast `success` |
| 文件加载完成 | statusBar | + Toast `success` |
| 文件关闭 / 全部关闭 | statusBar | + Toast `info` |
| FFT 完成 | statusBar (峰值) | + Toast `success` (峰值) |
| 时间-阶次 / 转速-阶次 / 阶次跟踪 完成 | statusBar | + Toast `success` (网格大小) |
| 预设保存 / 加载 / 重命名 / 清空 / 空槽 | none | Toast (success/info/warning) |
| 校验类拒绝（请先选择信号 / 转速 / 文件 等） | `QMessageBox.warning` (modal) | Toast `warning` (non-blocking) |
| 真实错误（asammdf 缺失 / 计算异常 / 文件解析失败） | `QMessageBox.critical` | **kept** — errors must be acknowledged |

Critical errors deliberately stay modal: the user needs to read the
exception text and click OK, not have it expire after 7 seconds.

## Design tradeoffs called out for the user

- **3 fixed slots, no growth.** The user explicitly asked for "3 buttons,
  save-as 1/2/3". I kept the count fixed and added rename instead of
  expanding to N. Rationale: the right-pane vertical budget is tight
  and overflowing into a popover would add a click for the most
  common action ("recall my usual config").
- **Single-toast policy (overwrite, not stack).** Multiple stacked
  toasts compete for attention and visually crowd the status bar.
  Latest-wins matches "the latest action is what the user just took".
- **Validation toasts are non-blocking.** This is a UX bet: a missed
  warning toast is recoverable (user notices nothing happened, looks
  again) while a modal warning interrupts every flow including the
  rapid "click around to explore" workflow. Real failures stay modal.

## Files touched

- `mf4_analyzer/ui/canvases.py` — cursor HTML output; unit chip helper.
- `mf4_analyzer/ui/chart_stack.py` — CursorPill RichText.
- `mf4_analyzer/ui/inspector_sections.py` — `PresetBar`, FFT/Order
  contextual integration, `objectName`/`WA_StyledBackground` on the
  contextual roots, `_collect_preset` / `_apply_preset` per side.
- `mf4_analyzer/ui/inspector.py` — `preset_acknowledged` signal; wire
  PresetBar acknowledgements upward.
- `mf4_analyzer/ui/main_window.py` — `_fft_auto_xlim` rewrite; `Toast`
  instance + `toast()` helper; `resizeEvent` reposition; replaced
  `QMessageBox.warning` (validation) and `QMessageBox.information`
  (export success) with toasts; added toast acknowledgements at all
  action completion points.
- `mf4_analyzer/ui/widgets.py` — `Toast` widget.
- `mf4_analyzer/ui/style.qss` — FFT/Order tints, preset button styles,
  toast styles for all four levels.

## Verification

- `python3 -c "import ast; ast.parse(...)"` runs clean for all six
  edited modules.
- Existing test suite under `tests/ui/` was not exercised because the
  local environment lacks `numpy` and `PyQt5`; the changes are
  additive (new attributes, new signals) and don't rename existing
  public methods, so the existing inspector / chart-stack / toolbar
  tests should not need updates. **Recommend** running `pytest tests/`
  in an environment with `requirements.txt` installed before merge.
- Interactive smoke test recommendations:
  - Load an MF4 with multi-channel signal; confirm cursor pill
    primary line shows each `name=value` in the channel's color.
  - Toggle 自适应频率范围 with a signal that has DC offset; confirm
    new behavior shows usable range.
  - Save a preset, rename it via right-click, switch files, load it,
    confirm signal-source dropdown is *not* affected (intentional).
  - Trigger every entry in the action-feedback table; confirm toast
    appears bottom-center, holds long enough to read, and fades.
  - Resize the window; confirm toast recenters.

## Known limitations

- Twinx spines that are `outward`-shifted leave the unit chip on the
  axes rect rather than on the moved spine. Acceptable for now;
  fixing it requires a post-`tight_layout` pixel-coord recompute.
- The single-toast overwrite policy will drop a fast burst (e.g. two
  saves in 200ms). For interactive operation this is fine; if a future
  long-running pipeline emits many events it would warrant a queue.
- Preset names are clamped to 12 characters to fit the 3-column grid.
  Longer names truncate silently; we don't surface this to the user.

## Codex review (post-implementation, 2026-04-25)

A second-pass review by the Codex rescue agent flagged two real bugs
and two nits. Resolution:

- **should-fix — Toast `finished` signal stale connection.** First
  fade-out connected `_anim.finished → self.hide`. The next
  `show_message` reused the same animation for fade-in, so its
  finish would also fire `hide`, dismissing the toast immediately.
  Fixed: both `show_message` and `_fade_out` now disconnect any
  existing `finished` slot before configuring the new direction
  (`widgets.py::Toast.show_message`, `Toast._fade_out`).
- **should-fix — `tests/ui/test_main_window_smoke.py::test_custom_xaxis_length_mismatch_warns`
  was patching `QMessageBox.warning`** which the production code no
  longer calls; the assertion would have silently passed forever.
  Fixed: the test now patches `MainWindow.toast` and asserts a
  `warning`-level call was made.
- **nit — empty-slot tooltip mentioned "right-click to rename"** but
  empty slots are disabled and the context menu cannot fire. Tooltip
  reworded to "保存后可右键重命名 / 清空" to match reality.
- **nit — duplicate Qt imports inside `_init_ui`.** Pre-existing,
  unrelated to this iteration; left for a future cleanup pass.
