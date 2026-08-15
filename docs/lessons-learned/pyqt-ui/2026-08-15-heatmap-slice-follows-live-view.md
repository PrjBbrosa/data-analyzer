---
id: pyqt-ui/2026-08-15-heatmap-slice-follows-live-view
status: active
owners: [codex]
keywords: [heatmap, slice, spectrogram, fft_time, order, viewRange, sigRangeChanged]
paths:
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
  - mf4_analyzer/ui/pg_canvas/slice_panel.py
  - tests/ui/test_pg_heatmap_canvas.py
checks:
  - rg -n "sigRangeChanged.connect\\(self._sync_slice_to_heatmap_view\\)|_heatmap_range_updating" mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py::test_x_slice_follows_live_heatmap_y_zoom tests/ui/test_pg_heatmap_canvas.py::test_y_slice_follows_live_heatmap_x_zoom tests/ui/test_pg_heatmap_canvas.py::test_home_restores_slice_to_full_heatmap_extents tests/ui/test_pg_heatmap_canvas.py::test_shift_wheel_on_map_refreshes_x_slice tests/ui/test_pg_heatmap_canvas.py::test_manual_panel_freq_range_ignores_heatmap_y_zoom -q
---

# Heatmap Slice Follows Live View

Trigger: Changing FFT-vs-Time / Order heatmap slice refresh, `sigRangeChangedManually`, `_handle_wheel_dispatch`, Home/`reset_view_to_data_extents`, or `_slice_axis_range`.

Past failure: Comments said an auto inspector axis lets the 1D slice follow the live heatmap view, but only `sigRangeChangedManually` was wired, and even that only toggled AA. Ctrl/Shift wheel, Home, and context-menu ranges use programmatic `setXRange`/`setYRange`, which do not emit the Manual signal, so the bottom slice stayed on the full axis after zoom/pan.

Rule: Re-clip the slice from the main plot's `sigRangeChanged` via `_sync_slice_to_heatmap_view`. Skip that path while `plot_or_update_heatmap` is applying its own ranges (`_heatmap_range_updating`). Inspector-manual panel ranges still win inside `_slice_axis_range`. Do not listen on the slice ViewBox, and do not emit layout chrome on the pan/zoom tick.

Verification: `test_x_slice_follows_live_heatmap_y_zoom`, `test_y_slice_follows_live_heatmap_x_zoom`, `test_home_restores_slice_to_full_heatmap_extents`, `test_shift_wheel_on_map_refreshes_x_slice`, `test_manual_panel_freq_range_ignores_heatmap_y_zoom`.
