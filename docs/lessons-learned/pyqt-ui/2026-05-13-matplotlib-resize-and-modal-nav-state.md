---
id: pyqt-ui/2026-05-13-matplotlib-resize-and-modal-nav-state
status: active
owners: [codex]
keywords: [matplotlib, resize, tight_layout, inspector, chart-options, pan, toolbar, shortcuts]
paths: [mf4_analyzer/ui/canvases.py, mf4_analyzer/ui/chart_stack.py, tests/ui/test_canvases.py, tests/ui/test_chart_stack.py]
checks: [TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_canvases.py tests/ui/test_chart_stack.py tests/ui/test_axis_interaction.py tests/ui/test_canvas_compactness.py -q]
tests: [tests/ui/test_canvases.py, tests/ui/test_chart_stack.py, tests/ui/test_axis_interaction.py, tests/ui/test_canvas_compactness.py]
---

# Matplotlib Resize And Modal Nav State

Trigger: Touching Matplotlib-backed PyQt canvases, splitter/inspector resize behavior, chart-options double-click flows, or chart toolbar navigation actions.

Past failure: Time-domain subplots computed `tight_layout` at the old canvas width and were then squeezed by channel changes or inspector toggles, pushing tick labels outside the canvas. A double-click chart-options modal also reused the same mouse press while the default pan tool was active, so returning to the plot could continue a stale pan drag and shift the curve.

Rule: For size-dependent Matplotlib layout, debounce a layout refresh after the canvas receives its new widget size. Before opening a modal from a canvas mouse event, deactivate pan/zoom and clear canvas pointer state so later motion cannot inherit the press.

Verification: Add regression tests that first prove tick labels stay visible after a post-plot resize and that double-click chart options followed by motion does not change axes limits; run the focused PyQt/Matplotlib suite listed in `checks`.
