---
id: codex-rounded-qt-popups-need-translucent-shell
status: active
owners: [codex]
keywords: [pyqt, qmenu, popup, border-radius, WA_TranslucentBackground, rounded-corners, 圆角, 方框]
paths:
  - mf4_analyzer/ui/**
  - mf4_analyzer/acquisition_ui/**
  - mf4_analyzer/ui_kit/style.qss
checks:
  - rg -n "QMenu\\(|border-radius|WA_TranslucentBackground" mf4_analyzer tests
tests:
  - PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
---

# Rounded Qt Popups Need Translucent Shell

Trigger: Creating or editing a rounded Qt popup, menu, popover, hover card, or
any widget whose visual shell relies on QSS `border-radius`.

Past failure: Rounded QMenu surfaces looked correct in QSS but still showed a
rectangular native backing behind the rounded corners. The markup editor's
color/line-width menu repeated a bug already handled in other popups.

Rule: Pair any rounded popup shell with `Qt.WA_TranslucentBackground` on the
outer widget/window, then put the rounded background on the visible inner
surface. For native `QMenu`, set the attribute on the menu itself and add a
focused regression test for the popup in the feature's UI test module.

Verification: Grep for new/changed popup construction and confirm rounded
shells have `WA_TranslucentBackground`. Run the targeted UI test that asserts
the attribute, plus a screenshot/live check when the change is visual-only or
platform-sensitive.
