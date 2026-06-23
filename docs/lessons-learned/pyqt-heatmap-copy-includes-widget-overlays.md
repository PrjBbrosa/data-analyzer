---
id: pyqt-heatmap-copy-includes-widget-overlays
status: active
owners: [codex]
keywords: [pyqtgraph, heatmap, copy-image, grab_pixmap, slice-panel, qwidget-overlay]
paths:
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
  - mf4_analyzer/ui/chart_stack/stack.py
  - tests/ui/test_pg_heatmap_canvas.py
  - tests/ui/test_chart_stack.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_heatmap_canvas.py::test_grab_pixmap_includes_slice_info_panel tests/ui/test_chart_stack.py::test_analysis_copy_image_includes_slice_panel -q
---

# Pyqt Heatmap Copy Includes Widget Overlays

Trigger: Touching heatmap copy/export, `PgHeatmapCanvas.grab_pixmap`, or
ChartStack copy wiring for FFT-vs-Time / Order views with the lower slice panel.

Past failure: `PgHeatmapCanvas.grab_pixmap()` grabbed only the inner
`GraphicsLayoutWidget` (`_glw`), so the right-side `QWidget#slicePanel` that
shows the current slice direction/readout was visible in the UI but missing from
copied images.

Rule: For heatmap views that mix pyqtgraph scene items with QWidget overlays,
copy/export must grab the whole canvas widget (or explicitly composite overlays)
instead of assuming `_glw.grab()` captures everything.

Verification: Add a rendered pixel regression that paints the slice panel with a
known test color and asserts both `PgHeatmapCanvas.grab_pixmap()` and the
ChartStack analysis copy path include that color; run the focused tests plus
`git diff --check`.
