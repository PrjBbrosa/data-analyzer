---
id: pyqt-ui/2026-08-16-ultraview-viewport-gesture-router
status: active
owners: [codex]
keywords: [ultraview, viewport, pan, zoom, QEvent, QApplication, event-filter, CanvasHost, QLineEdit, Cocoa]
paths:
  - mf4_analyzer/ui/chart_stack/ultraview/viewport_router.py
  - mf4_analyzer/ui/chart_stack/ultraview/page.py
  - mf4_analyzer/ui/chart_stack/ultraview/widgets.py
  - tests/ui/test_ultraview_viewport_router.py
checks:
  - rg -n "_forward_native_zoom|_forward_zoom_wheel|_handle_space_key|_handle_pan_press|_handle_pan_release" mf4_analyzer/ui/chart_stack/ultraview/widgets.py
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_viewport_router.py tests/ui/test_ultraview_structure.py -q
---

# UltraView Viewport Gestures Route At CanvasHost Scope

Trigger: Changing UltraView pan/zoom/pinch/space handling, adding an interactive
widget below `CanvasHost`, or moving an event handler between `page.py` and
`widgets.py`.

Past failure: Five different canvas children independently forwarded pan move,
press/release, space, wheel, and native-pinch events to Page. Qt's implicit
mouse grab delivers later moves to whichever child started the gesture, so a
new child or a boundary crossing could omit one forwarding branch and make the
pan silently stop. The duplicates also enlarged `_page_of`'s private surface
to eleven methods, making an otherwise local card change a Page-coupling risk.

Rule: Page owns one `ViewportGestureRouter` installed on `QApplication` only
while the Page is shown and active. It handles only `CanvasHost` descendants,
accepts and returns `True` only for a handled event, and otherwise lets the
receiver process the event normally. Preserve button matching through
`PanSession`, leave text input space unconsumed, and pass the original receiver
to wheel/pinch handling so cursor-anchor fallback can map it correctly. Keep
the existing hide/deactivate gesture cancellation path intact.

Verification: `test_ultraview_viewport_router.py` covers five start widgets,
middle and space-left pan across children, Ctrl/Cmd wheel, native pinch, text
focus, host scope, and hide/show lifecycle; `test_ultraview_structure.py`
keeps `_page_of` at its four card-only methods. Offscreen results do not prove
Cocoa input dispatch: complete the foreground gesture checklist when the Mac is
unlocked and record it in the seam-hardening verification directory.
