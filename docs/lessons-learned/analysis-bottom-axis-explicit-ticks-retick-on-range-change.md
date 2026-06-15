---
id: analysis-bottom-axis-explicit-ticks-retick-on-range-change
status: active
owners: [codex]
keywords: [pyqtgraph, analysis, ticks, axis, range-change]
paths:
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_fft_line_canvas_bottom_ticks_recompute_after_x_range_change tests/ui/test_pg_line_canvas.py::test_fft_line_canvas_unshown_bottom_ticks_fall_back_to_density tests/ui/test_pg_heatmap_canvas.py::test_heatmap_bottom_ticks_recompute_after_x_range_change tests/ui/test_pg_heatmap_canvas.py::test_heatmap_unshown_bottom_ticks_fall_back_to_density -q
---

# Analysis Bottom Axis Explicit Ticks Retick On Range Change

Trigger: Changing pyqtgraph Analysis bottom-axis tick generation from adaptive density to explicit `AxisItem.setTicks(...)`.

Past failure: A one-shot explicit bottom X tick fit looked correct immediately after `set_tick_density()`, but normal pan/zoom or programmatic `setXRange()` left labels pinned to the previous view range. An unshown FFT line canvas also used phantom axis geometry to pin ticks before layout was real.

Rule: Store the requested X tick target as canvas state and reapply explicit bottom ticks from `sigXRangeChanged`, `sigResized`, `resizeEvent`, and `showEvent`; when the canvas is not visible or geometry is not real, reset to adaptive tick density instead of pinning explicit ticks.

Verification: Run the focused range-change and unshown fallback tests for line and heatmap canvases, plus `git diff --check`.
