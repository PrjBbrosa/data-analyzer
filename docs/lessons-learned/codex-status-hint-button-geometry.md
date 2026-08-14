---
id: codex-status-hint-button-geometry
status: active
owners: [codex]
keywords: [pyqt, qss, statusbar, hint-bar, quickref, qtoolbutton, clipped, showMessage, inspector-help]
paths:
  - mf4_analyzer/ui_kit/style.qss
  - mf4_analyzer/ui/chart_stack/stack.py
  - mf4_analyzer/ui/chart_stack/cards.py
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/compute_progress.py
  - mf4_analyzer/ui/inspector.py
  - tests/ui/test_main_window_smoke.py
  - tests/ui/test_compute_progress.py
checks:
  - inspect the rendered QToolButton geometry after style.qss is applied
  - QStatusBar.showMessage must not paint left of the QuickRef '?'
  - Inspector 「使用说明」 must sit inside the help button and the card radius
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py::test_status_hint_quickref_button_stays_inside_bar_under_qss tests/ui/test_compute_progress.py::test_status_bar_single_file_can_label_is_fully_visible_under_qss -q
---

# Status Chrome Must Keep Glyphs Inside Rounded Hosts

Trigger: Changing the bottom status-line hint bar, the quickref `?` button,
QSS dimensions for compact status/inspector chrome, compute-progress labels,
or Inspector's `? 使用说明` link.

Past failure: QSS tokens looked fine while three glyphs still clipped or
leaked: the QuickRef `?` was shaved by the 32px pill; `QStatusBar.showMessage`
painted crushed copy (`1%`) in the native left gutter beside `?`; a
contents-rect mask on `#computeProgressLabel` shaved 1px off `%`; and an
empty-text `QPushButton` ignored its child-label layout so 「说明」 ran into
Inspector's 7px corner.

Rule: Load `style.qss` and assert rendered geometry, not tokens. Do not let
the native status-bar message painter occupy the left gutter once the hint
bar is docked (`currentMessage()` can stay for callers). A progress-label
mask may clip in X but must leave vertical slack for glyph descent.
`QPushButton` sizeHint must include the inner layout when the button text is
empty, and the help link must clear the card radius.

Verification: Run the status-hint geometry regression and the compute-progress
full-label test before claiming the visual fix.

