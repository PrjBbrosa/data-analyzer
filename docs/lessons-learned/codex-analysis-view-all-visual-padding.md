---
id: codex-analysis-view-all-visual-padding
status: active
owners: [codex]
keywords: [pyqtgraph, analysis, view-all, home, tick-label, padding, fft, order, fft-time]
paths:
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
  - tests/ui/test_pg_line_canvas.py
  - tests/ui/test_pg_heatmap_canvas.py
checks:
  - rg -n "_visual_padded_bounds|reset_view_to_data_extents|test_toolbar_home_keeps_.*visual_padding" mf4_analyzer/ui/pg_canvas tests/ui
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_toolbar_home_keeps_full_fft_range_with_visual_padding tests/ui/test_pg_line_canvas.py::test_toolbar_home_preview_only_keeps_time_padding_without_amp_autorange tests/ui/test_pg_heatmap_canvas.py::test_toolbar_home_keeps_heatmap_extents_with_visual_padding
---

# Analysis View-All Visual Padding

Trigger: Touching pyqtgraph analysis canvas Home/View-All behavior for FFT,
Order, or FFT-vs-Time.

Past failure: Analysis canvases restored full data ranges with `padding=0`.
When a full range started at zero, the boundary tick label was drawn directly
on the plot frame and looked like the coordinate axis had shifted or leaked
outside the chart after every `查看全部` action.
Follow-up failure: FFT preview-only state had no `_last_xlim` because no
spectrum had been computed, so `查看全部` fell back to native `autoRange()` on
the empty upper spectrum plot and recreated the same visual drift.

Rule: Home/View-All should include the full data extents while adding a tiny
visual-only margin around finite non-degenerate ranges. Keep the toolbar path
under test because the visible command routes through `PgNavigationToolbar.home`
and the context menu `查看全部` action uses the same canvas reset helper.
For FFT preview-only state, reset the lower time preview from its plotted time
curve bounds and leave the empty spectrum plot alone; do not autoRange an empty
upper plot.

Verification: Run the FFT line-canvas and heatmap visual-padding regressions,
then run the related analysis UI tests when changing split/layout behavior.
