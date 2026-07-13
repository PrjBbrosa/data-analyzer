---
id: shared-wheel-dispatch-needs-event-route-coverage
status: active
owners: [codex]
keywords: [pyqt, pyqtgraph, wheel, event-routing, callback-contract, regression]
paths: [mf4_analyzer/ui/pg_canvas/viewbox.py, mf4_analyzer/ui/pg_canvas/line_canvas.py, mf4_analyzer/ui/pg_canvas/heatmap_canvas.py, tests/ui/test_pg_line_canvas.py, tests/ui/test_pg_heatmap_canvas.py]
checks: [rg -n "scene_pos=scene_pos|axis=axis|def _handle_wheel_dispatch" mf4_analyzer/ui/pg_canvas, .\.venv\Scripts\python.exe -m pytest -q tests/ui/test_pg_line_canvas.py tests/ui/test_pg_heatmap_canvas.py --basetemp D:\tmp\pytest-wheel]
tests: [tests/ui/test_pg_line_canvas.py, tests/ui/test_pg_heatmap_canvas.py]
---

# Shared Wheel Dispatch Needs Event-Route Coverage

Trigger: Changing the shared pyqtgraph ``_ModifierWheelViewBox`` wheel-dispatch payload or any canvas ``_handle_wheel_dispatch`` callback signature.

Past failure: The dispatcher began passing ``scene_pos`` and ``axis`` for an overlay use case, while the FFT line and heatmap callbacks still accepted only ``view_box``. The resulting ``TypeError`` occurred only when a real Qt wheel event reached the ViewBox, so direct unit calls of the handlers all passed while Ctrl/Shift wheel zoom was dead in FFT, FFT-vs-Time, and Order.

Rule: Keep every owner callback compatible with the dispatcher payload (accept and intentionally ignore optional shared context where it is not needed). Verify wheel behavior by delivering an actual ``QWheelEvent`` through the ``GraphicsLayoutWidget`` viewport; do not rely solely on direct handler tests.

Verification: Test Ctrl and Shift wheel delivery on both ``PgLineCanvas`` and ``PgHeatmapCanvas`` through the viewport, asserting the expected X-only/Y-only range change and no Qt exception. Run the two pg-canvas test modules with a writable pytest base temp directory.
