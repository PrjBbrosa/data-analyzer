---
id: codex-fft-spectrum-peak-hold
status: active
owners: [codex]
keywords: [fft, spectrum, envelope, peak-hold, antialias, overlay-axis, PgLineCanvas]
paths:
  - mf4_analyzer/signal/envelope.py
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - tests/ui/test_pg_line_canvas.py
  - tests/ui/test_canvases_envelope.py
checks:
  - spectra must call build_peak_trace, not build_envelope
  - time-preview overlay axes must realize a right-hand column
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_canvases_envelope.py::test_build_peak_trace_emits_one_max_per_bucket tests/ui/test_pg_line_canvas.py::test_fft_dense_spectrum_uses_peak_hold_not_minmax_ribbon tests/ui/test_pg_line_canvas.py::test_fft_screenshot_scale_spectrum_stays_antialiased tests/ui/test_pg_line_canvas.py::test_time_preview_overlay_axes_sit_right_of_viewbox -q
---

# FFT Spectra Must Peak-Hold, Not Min/Max-Fill

Trigger: Changing `PgLineCanvas` spectrum plotting, `_spectrum_plot_arrays`,
spectrum AA budgets, or time-preview overlay Y axes.

Past failure: Dense dBA overlays reused time-domain `build_envelope` (min AND
max per pixel). Each column became a vertical sawtooth, four traces painted
as a filled blur, and the AA gate (ON=2000/OFF=3000) turned antialiasing off.
Separately, overlay `AxisItem`s added at grid columns 3+ were never activated,
so coloured tick text sat at the origin on top of the left axis.

Rule: Spectra use `build_peak_trace` (one max per bucket). Time-domain preview
keeps `build_envelope`. Do not reuse min/max envelopes on FFT amplitude. The
spectrum AA budget must keep a screenshot-width 4-curve peak-hold overlay
crisp. After pinning overlay ticks, measure axis width and
`_activate_graphics_layout()` so the gutters occupy the right side; assert
`axis.sceneBoundingRect()` sits to the right of the time ViewBox.

Verification: Run the peak-hold unit test plus the line-canvas spectrum AA and
overlay-axis geometry tests.

## Naming collision: two unrelated "peak hold"s

`mf4_analyzer.signal.fft.compute_peak_hold_fft` and
`mf4_analyzer.signal.envelope.build_peak_trace` are both called "peak hold"
in code/comments and are easy to conflate — they solve different problems
one layer apart:

- **`compute_peak_hold_fft`** (compute layer): takes the per-bin **max
  across overlapping FFT segments**. This changes the data — the output
  is a different, smaller frequency series than any single segment's
  spectrum. Feeds the FFT 1D "峰值保持" averaging mode.
- **`build_peak_trace`** (render layer, this doc's subject): takes the
  per-**pixel-bucket** max of an already-computed series so a dense
  spectrum draws as one clean line instead of a filled ribbon. This is
  pure downsampling for display — it never changes the underlying data.

The two docstrings cross-reference each other; keep that pointer intact if
either function moves or gets renamed.
