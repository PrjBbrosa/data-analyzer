---
id: fft-time-preview-empty-keeps-y-graticule
status: active
owners: [codex]
keywords: [fft, time-preview, graticule, empty, grid, overlay]
paths:
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - tests/ui/test_pg_line_canvas.py
checks:
  - rg -n "if not self._time_curves" mf4_analyzer/ui/pg_canvas/line_canvas.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py::test_time_preview_empty_keeps_shared_y_grid tests/ui/test_pg_line_canvas.py::test_time_preview_clear_rebuilds_grid_without_leak tests/ui/test_pg_line_canvas.py::test_empty_state_time_y_grid_stays_internal -q
---

# FFT Time Preview Empty Keeps Y Graticule

Trigger: Changing `PgLineCanvas` time-preview overlay grid, `_build_time_y_grid`, empty `plot_time_preview([])`, or `full_reset`.

Past failure: Native left-axis Y grid is off so overlay curves can share a fractional k/N graticule. `_build_time_y_grid` returned early when `_time_curves` was empty, and the empty `plot_time_preview` / `full_reset` paths never rebuilt it. Unchecked channels then showed only vertical X grid lines.

Rule: Keep the shared `[0,1]` InfiniteLine graticule on the time preview even with zero curves. Do not re-enable native left-axis Y grid. Empty and with-data charts both pin ticks to n+1 values; grid lines stay internal (`i/n`, not 0 or 1) so they do not double the plot frame.

Verification: `test_time_preview_empty_keeps_shared_y_grid`, `test_time_preview_clear_rebuilds_grid_without_leak`, and `test_empty_state_time_y_grid_stays_internal`.
