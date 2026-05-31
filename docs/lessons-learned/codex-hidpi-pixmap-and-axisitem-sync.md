---
id: codex-hidpi-pixmap-and-axisitem-sync
status: active
owners: [codex]
keywords: [hidpi, dpr, qpixmap, qgraphicspixmapitem, pyqtgraph, viewbox, axisitem, setxrange]
paths:
  - mf4_analyzer/ui/chart_stack.py
  - mf4_analyzer/ui/markup/editor.py
  - mf4_analyzer/ui/pg_canvases.py
  - tests/ui/test_chart_stack.py
  - tests/ui/test_markup_editor.py
  - tests/ui/test_pg_timedomain_canvas.py
checks:
  - rg -n "devicePixelRatioF|setDevicePixelRatio|setRange|blockSignals" mf4_analyzer/ui tests/ui
tests:
  - PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_chart_stack.py tests/ui/test_markup_editor.py tests/ui/test_pg_timedomain_canvas.py -q
---

# HiDPI Pixmaps And Blocked Axis Sync

Trigger: Copy/edit chart pixmaps or signal-blocked pyqtgraph X range sync.

Past failure: On macOS Retina, copied chart pixmaps carried DPR 2 metadata while
downstream painter/editor code used physical pixel coordinates. The cursor pill
could be composited outside the copied image, and the markup editor scene could
be double-sized. Separately, signal-blocked `ViewBox.setXRange()` moved curves
without notifying the linked bottom `AxisItem`, so tick numbers stayed stale.

Rule: Normalize high-DPI copied pixmaps to DPR 1 image pixels before downstream
painting/editor layout, and when blocking `ViewBox` signals for range
propagation, explicitly sync the linked bottom `AxisItem` with the same X range.

Verification: Add or run regressions that assert DPR-normalized copied pixmaps,
markup scene bounds matching the visible pixmap, and bottom `AxisItem.range`
matching programmatic X-range changes in subplot and overlay mode.
