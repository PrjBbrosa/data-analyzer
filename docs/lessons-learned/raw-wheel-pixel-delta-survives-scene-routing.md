---
id: raw-wheel-pixel-delta-survives-scene-routing
status: active
owners: [codex]
keywords: [pyqt, pyqtgraph, wheel, pixelDelta, touchpad, event-routing]
paths:
  - mf4_analyzer/ui/pg_canvas/viewbox.py
  - mf4_analyzer/ui/pg_canvas/canvas.py
  - tests/ui/test_pg_timedomain_canvas.py
checks:
  - git diff --check
tests:
  - tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSetDataHotPathContract::test_real_viewport_shift_pixel_wheel_zooms_overlay_y
---

# Raw Wheel Pixel Delta Survives Scene Routing

Trigger: Changing pyqtgraph wheel routing, modifier zoom behavior, the
GraphicsLayoutWidget host, or precision-touchpad support.

Past failure: The ViewBox read only `QGraphicsSceneWheelEvent.delta()`. Qt can
reduce a pixel-only `QWheelEvent` to a scene event whose legacy delta is zero,
so Shift+Y zoom lost the touchpad direction and appeared one-way or inert.
Angle-delta tests all passed and hid the missing route.

Rule: Capture the signed raw wheel delta before the viewport converts the
event, prefer angle delta, fall back to pixel delta, and expose that fallback
only for the synchronous scene dispatch. Test positive and negative
pixel-only `QWheelEvent` delivery through the real viewport.

Verification: Run `git diff --check` and
`.\.venv\Scripts\python.exe -m pytest -q
tests\ui\test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSetDataHotPathContract::test_real_viewport_shift_pixel_wheel_zooms_overlay_y
--basetemp D:\tmp\pytest-wheel-pixel`.
