---
id: codex-rounded-child-widgets-need-pixel-corner-check
status: active
owners: [codex]
keywords: [pyqt, qframe, child-widget, cursorPill, border-radius, rounded-corners, transparent-corners, grab, render, 截图, 方框]
paths:
  - mf4_analyzer/ui/chart_stack.py
  - mf4_analyzer/ui_kit/style.qss
  - tests/ui/test_chart_stack.py
checks:
  - rg -n "cursorPill|paintEvent|WA_TranslucentBackground|border-radius" mf4_analyzer/ui/chart_stack.py mf4_analyzer/ui_kit/style.qss tests/ui/test_chart_stack.py
tests:
  - PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_chart_stack.py::test_cursor_pill_renders_transparent_rounded_corners -q
---

# Rounded Child Widgets Need Pixel Corner Check

Trigger: Load when changing child-widget floating pills, hover cards, chart
overlays, or copied/exported UI elements whose visual shape relies on rounded
corners.

Past failure: `CursorPill` used QSS `border-radius` on a child `QFrame`, but
rendering/grabbing the widget still produced opaque rectangular corner pixels,
so screenshots showed a square backing behind the rounded pill.

Rule: For rounded child widgets that are grabbed/rendered or visually float over
charts, do not trust `border-radius` alone. Use a transparent outer widget and
paint/draw only the rounded surface, or otherwise prove the corner pixels remain
transparent.

Verification: Add or run a pixel-level regression that renders the widget into a
transparent `QImage` and asserts corner alpha is near zero while the body stays
opaque.
