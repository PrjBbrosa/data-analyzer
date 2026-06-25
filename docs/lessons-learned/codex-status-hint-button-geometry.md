---
id: codex-status-hint-button-geometry
status: active
owners: [codex]
keywords: [pyqt, qss, statusbar, hint-bar, quickref, qtoolbutton, clipped]
paths:
  - mf4_analyzer/ui_kit/style.qss
  - mf4_analyzer/ui/chart_stack/stack.py
  - mf4_analyzer/ui/chart_stack/cards.py
  - tests/ui/test_main_window_smoke.py
checks:
  - inspect the rendered QToolButton geometry after style.qss is applied
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py::test_status_hint_quickref_button_stays_inside_bar_under_qss -q
---

# Status Hint Buttons Need Rendered Geometry

Trigger: Changing the bottom status-line hint bar, the quickref `?` button, or
QSS dimensions for compact `QToolButton` controls hosted inside `QStatusBar`.

Past failure: The quickref `?` button looked fine by QSS tokens, but Qt added
border/margin to the styled size. In the real status-bar host it rendered as
`22x20` inside a `20px` hint bar at `y=1`, so the rounded bottom was clipped by
the white status-bar background.

Rule: For compact status/hint-bar buttons, do not trust QSS `min-height` alone.
Load the real `style.qss`, render the main-window status host, and assert the
button geometry stays inside the parent hint bar.

Verification: Run the focused geometry regression plus nearby hint-bar layout
tests before claiming the visual fix.
