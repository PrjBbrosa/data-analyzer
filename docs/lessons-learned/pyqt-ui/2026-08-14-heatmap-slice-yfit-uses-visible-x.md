---
id: pyqt-ui/2026-08-14-heatmap-slice-yfit-uses-visible-x
status: active
owners: [codex]
keywords: [ultraview, heatmap, slice, y-fit, Y适应, fft_time, spectrogram]
paths:
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
  - mf4_analyzer/ui/pg_canvas/slice_panel.py
  - tests/ui/test_pg_heatmap_canvas.py
checks:
  - rg -n "y_autofit_handler|_fit_slice_y_to_visible_x|fit_y_to_visible_x" mf4_analyzer/ui/pg_canvas/heatmap_canvas.py mf4_analyzer/ui/pg_canvas/slice_panel.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py::test_heatmap_context_menu_y_fit_stays_disabled_on_map tests/ui/test_pg_heatmap_canvas.py::test_slice_context_menu_y_fit_keeps_x_and_fits_visible_amp -q
---

# Heatmap Slice Y-Fit Uses Visible X

Trigger: Changing FFT-vs-Time / Order slice context menus, `y_autofit_handler`, or slice amplitude ranging.

Past failure: The spectrogram context menu passed `y_autofit_handler=None` for every ViewBox, so 「Y适应」 stayed disabled on the 1D slice. The slice is a line plot (frequency/order × amplitude); users who zoomed its Y axis had no way to fit it.

Rule: Enable Y-fit only on the slice ViewBox. Keep the current X window and fit amplitude from visible curve samples via `_slice_amp_bounds` (dead dB-floor bins stay out). Do not enable Y-fit on the 2D map (Y is frequency/order). Do not recompute DSP or retarget the colorbar.

Verification: `test_heatmap_context_menu_y_fit_stays_disabled_on_map`, `test_slice_context_menu_y_fit_keeps_x_and_fits_visible_amp`.
