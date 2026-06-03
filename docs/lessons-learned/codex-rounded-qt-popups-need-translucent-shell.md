---
id: codex-rounded-qt-popups-need-translucent-shell
status: active
owners: [codex]
keywords: [pyqt, qmenu, popup, border-radius, WA_TranslucentBackground, NoDropShadowWindowHint, rounded-corners, 圆角, 方框, 阴影]
paths:
  - mf4_analyzer/ui/**
  - mf4_analyzer/acquisition_ui/**
  - mf4_analyzer/ui_kit/style.qss
checks:
  - rg -n "QMenu\\(|border-radius|WA_TranslucentBackground|NoDropShadowWindowHint|FramelessWindowHint" mf4_analyzer tests
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
surface. For native top-level `QMenu` / `Qt.Popup` surfaces on macOS, also set
`Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint` before showing the popup
when the native rectangular shadow can leak past the radius. Attribute-only
tests are not enough for this class of bug: add a feature-level regression test
for the shell flags and use a screenshot, pixel harness, or live check when the
visual risk is platform-sensitive.

Verification: Grep for new/changed popup construction and confirm rounded
shells have `WA_TranslucentBackground` plus native-shadow flags where applicable.
Run the targeted UI test that asserts the attributes/flags, plus a screenshot or
live check when the change is visual-only or platform-sensitive.
