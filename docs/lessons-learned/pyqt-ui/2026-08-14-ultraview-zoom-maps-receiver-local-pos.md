---
id: pyqt-ui/2026-08-14-ultraview-zoom-maps-receiver-local-pos
status: active
owners: [codex]
keywords: [ultraview, zoom-at-cursor, QWheelEvent, QNativeGestureEvent, globalPosition, mapToGlobal, pinch, pixelDelta, QCursor]
paths: [mf4_analyzer/ui/chart_stack/ultraview/page.py, mf4_analyzer/ui/chart_stack/ultraview/viewport.py, tests/ui/test_ultraview_viewport.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_viewport.py -q]
tests: [tests/ui/test_ultraview_viewport.py]
---

# UltraView Zoom Maps Receiver Local Pos

Trigger: UltraView board zoom, Ctrl+wheel, trackpad pinch, `handle_zoom_wheel`, `handle_pinch`, or `_cursor_in_scroll_viewport`.

Past failure: Zoom math kept the logical point fixed, but the cursor was taken from `event.globalPosition()`. Cocoa pinch/wheel often reports `(0, 0)` there. `mapFromGlobal(0, 0)` is outside the viewport, `QScrollBar.setValue` clamps to 0, and the board grows from the top-left. `viewport.mapFrom(card, local)` also segfaults because that API requires an ancestor, not a descendant. A follow-up miss: preferring `event.position()` unconditionally still failed on a real Mac, because Cocoa pinch/wheel also reports local `(0, 0)`. Mapping that through the receiver anchors on the widget origin — same top-left grow.

Rule: Resolve the zoom anchor in this order, keeping only points that land inside the scroll viewport: (1) non-zero `globalPosition`, (2) non-zero local `position()`/`pos()` via `widget.mapToGlobal` then `viewport.mapFromGlobal`, (3) `QCursor.pos()`. Treat `(0, 0)` as missing, not as the widget origin. Never call `viewport.mapFrom(descendant, …)`. When `angleDelta` is 0, use `pixelDelta` on the same 120-unit scale.

Verification: `test_ctrl_wheel_keeps_the_logical_point_under_the_cursor`, `test_ctrl_wheel_anchors_when_global_position_is_zero`, `test_ctrl_wheel_anchors_when_local_and_global_are_zero`, `test_pinch_anchors_when_native_gesture_positions_are_zero`, `test_ctrl_wheel_zooms_from_pixel_delta_when_angle_delta_is_zero`.
