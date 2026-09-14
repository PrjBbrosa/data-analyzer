---
id: analysis-line-ranges-use-raw-valid-window
status: active
owners: [codex]
keywords: [auto-range, spectrum, slice, validity-mask, viewport]
paths:
  - mf4_analyzer/signal/display_ranges.py
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - mf4_analyzer/ui/pg_canvas/slice_panel.py
  - mf4_analyzer/batch_render_qt/_builder.py
checks:
  - git diff --check
tests:
  - tests/signal/test_display_ranges.py
  - tests/ui/test_pg_heatmap_canvas.py::test_slice_db_mask_excludes_zero_but_preserves_real_deep_valley
  - tests/test_batch_render_qt.py::test_fft_auto_y_uses_visible_original_values
---

# Analysis Line Ranges Use The Raw Valid Window

Trigger: Changing automatic FFT or heatmap-slice amplitude ranges, dB reference
conversion, or viewport-dependent spectrum drawing.

Past failure: A shared 200 dB rejection heuristic discarded valid Linear values
and real deep dB valleys. Batch also used an out-of-window peak to set visible
Y limits. Full-spectrum peak traces lost narrow-window resolution; dropping
NaN coordinates while clipping created false connecting segments.

Rule: Derive amplitude bounds from raw values in the actual visible window,
with a same-shape validity mask derived from original linear data. Keep
contrast/color limits separate. Preserve finite segment boundary intersections
and NaN breaks. Use viewport-decimated data only for drawing, never to derive
raw bounds. Preserve each axis's explicit user intent during restoration.

Verification: Cover Linear 0..1000, a valid -300 dB valley beside zero input,
manual X with an out-of-window peak, sparse boundary crossings and NaN gaps.
Compare actual GUI and Batch ranges, and verify visible trace rebuilding with
a real Cocoa large-NFFT probe.
