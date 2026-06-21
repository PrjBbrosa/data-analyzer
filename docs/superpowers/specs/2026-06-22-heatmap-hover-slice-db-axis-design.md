# Heatmap Hover, Slice, and dB Axis Design

## Goal

Fix three related analysis-display defects as one coherent display contract:
heatmap hover must not create floating XYZ readouts, slice curves must use the
same visible coordinate range as the main heatmap, and FFT dB auto Y ranges
must avoid expanding to the deep noise floor when the user chooses frequency
priority or any other dB FFT view.

## User Decisions

- Do not retain heatmap hover XYZ readout. Heatmap coordinates are available
  through explicit annotations and slice selection, not passive floating hover.
- Right-side manual coordinate ranges are authoritative for the main heatmap
  and the bottom slice curve.
- Order already has the useful dB-auto idea: robust high-percentile ceiling
  plus a bounded display span. Reuse that principle for FFT line Y ranges, but
  compute from the visible frequency span, not from the whole matrix.

## Current Evidence

- `PgHeatmapCanvas._on_scene_hover()` emits `cursor_info` for every heatmap
  hover and formats it with the annotation XYZ formatter.
- `ChartStack` connects heatmap `cursor_info` to the floating cursor pill for
  FFT-vs-Time and Order, so a passive hover can show the XYZ pill even when the
  annotation toolbar button is off.
- FFT-vs-Time and Order manual X/Y ranges are applied to the main heatmap
  `ViewBox`, while `_apply_slice()` still feeds the bottom curve with full
  coordinate arrays.
- `PgLineCanvas.plot_spectra()` delegates automatic FFT dB Y range to
  pyqtgraph autorange, which includes very low finite dB bins and can produce
  a range near -100 dB.
- Order and FFT-vs-Time heatmap color auto levels already use
  `_auto_db_window(matrix)`, which anchors a fixed span under a robust
  high-percentile ceiling.

## Display Contract

### Heatmap Hover and Annotation

Heatmap hover is no longer a readout feature. Moving the mouse over FFT-vs-Time
or Order must clear any floating cursor pill and must not emit an XYZ string.
Annotation mode remains click-based: when the annotation toolbar button is on,
left-click adds a fixed annotation and right-click removes the nearest one.
This avoids conflating passive hover, annotation creation, and persistent
readouts.

### Heatmap Slice Domain

The main heatmap and the bottom slice row share a visible-domain contract.

- In `x` slice mode, the user fixes time and sees amplitude versus frequency
  or order. The slice curve X values must be clipped to the main heatmap's
  current visible Y range.
- In `y` slice mode, the user fixes frequency or order and sees amplitude
  versus time. The slice curve X values must be clipped to the main heatmap's
  current visible X range.
- When the visible range contains no sample center, the slice may fall back to
  the nearest coordinate point so the plot never becomes empty during a narrow
  zoom.
- Slice markers and hints still describe the fixed coordinate. The curve domain
  describes the visible variable.

This contract applies to both FFT-vs-Time and Order because both use
`PgHeatmapCanvas(with_slice=True)`.

### FFT dB Auto Y Range

FFT line dB auto range is a display-only policy. It does not change FFT
amplitude calculation, dB conversion, cache keys, or preset parameters.

When `plot_spectra(..., amp_label="Amplitude (dB)", y_auto=True)` is used, the
top FFT line plot should compute a robust visible Y range:

- gather finite y-values from all plotted spectrum entries whose frequency lies
  in the requested `xlim`;
- compute a robust high-percentile ceiling using the same percentile constant
  as heatmap dB auto levels;
- set the lower bound to `ceiling - _AUTO_SPAN_DB`;
- include the literal visible peak when it sits above the robust ceiling so
  narrow tonal peaks are not clipped;
- leave non-dB and manual-Y modes unchanged.

This reuses the Order auto-color idea without treating line axes as colorbars.
The range is based on visible frequencies because the user's current X range is
the context they are trying to inspect.

## Files

- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`: gate heatmap hover readouts and
  centralize visible-domain slice extraction.
- `mf4_analyzer/ui/pg_canvas/line_canvas.py`: add dB-aware auto Y range for FFT
  line spectra.
- `tests/ui/test_pg_heatmap_canvas.py`: regression tests for hover suppression
  and visible-domain slice clipping.
- `tests/ui/test_chart_stack.py`: regression test that heatmap direct
  `cursor_info` does not surface as a floating pill.
- `tests/ui/test_pg_line_canvas.py`: regression tests for dB auto Y range and
  non-dB/manual behavior.

## Verification

Focused checks:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_heatmap_cursor_info_does_not_show_pill_in_fft_time_or_order \
  tests/ui/test_pg_heatmap_canvas.py::test_heatmap_hover_does_not_emit_xyz_readout \
  tests/ui/test_pg_heatmap_canvas.py::test_x_slice_uses_visible_frequency_range \
  tests/ui/test_pg_heatmap_canvas.py::test_y_slice_uses_visible_time_range \
  tests/ui/test_pg_heatmap_canvas.py::test_order_x_slice_uses_visible_order_range \
  tests/ui/test_pg_line_canvas.py::test_db_auto_y_range_uses_robust_visible_span \
  tests/ui/test_pg_line_canvas.py::test_linear_auto_y_range_still_uses_pyqtgraph_autorange \
  -q
```

Broader checks:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_heatmap_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_chart_stack.py -q

git diff --check
/usr/bin/python3 scripts/lessons/check.py --status
```

## Self-Review

- No passive heatmap XYZ readout remains in the intended UI contract.
- Slice range behavior is defined by visible coordinates rather than by the full
  matrix extent.
- dB auto Y range is display-only and reuses the existing robust dB span idea
  without changing compute results.
- The implementation scope is focused on the heatmap canvas, FFT line canvas,
  and tests.
