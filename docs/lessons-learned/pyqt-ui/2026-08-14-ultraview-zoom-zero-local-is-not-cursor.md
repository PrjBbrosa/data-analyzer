---
id: pyqt-ui/2026-08-14-ultraview-zoom-zero-local-is-not-cursor
status: active
owners: [codex]
keywords: [ultraview, zoom-at-cursor, QNativeGestureEvent, QWheelEvent, QCursor, position, pinch]
paths: [mf4_analyzer/ui/chart_stack/ultraview/page.py, tests/ui/test_ultraview_viewport.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_viewport.py -q]
tests: [tests/ui/test_ultraview_viewport.py]
---

# UltraView Zoom Zero Local Is Not Cursor

Trigger: UltraView board zoom, Ctrl+wheel, trackpad pinch, `_cursor_in_scroll_viewport`, or any fix that maps `event.position()` as the zoom anchor.

Past failure: Mapping receiver-local pos via `mapToGlobal` still zoomed from the top-left on a real Mac. Cocoa pinch/wheel reports both `globalPosition()` and `position()` as `(0, 0)`. Treating local origin as the cursor anchors on the widget top-left; `QScrollBar.setValue` clamps; the board grows from the corner. Offscreen tests that send a non-zero local pos with zero global all passed.

Rule: `(0, 0)` is missing, not a point under the cursor. Prefer non-zero global, then non-zero local mapped through `widget.mapToGlobal` + `viewport.mapFromGlobal`, then `QCursor.pos()` if it lands in the viewport. Never `viewport.mapFrom(descendant, …)`.

Verification: `test_ctrl_wheel_anchors_when_local_and_global_are_zero`, `test_pinch_anchors_when_native_gesture_positions_are_zero`.
