---
id: codex-dialog-toolbutton-chrome-spares-search-field
status: active
owners: [codex]
keywords: [pyqt, qss, qtoolbutton, searchfield, specificity, channel-config, magnifier, white-chip]
paths:
  - mf4_analyzer/ui_kit/style.qss
  - mf4_analyzer/ui_kit/widgets/search_field.py
  - mf4_analyzer/ui/widgets/channel_config_manager.py
  - tests/ui/test_channel_config_manager.py
checks:
  - rg -n "QDialog#[A-Za-z0-9]+ QToolButton \\{" mf4_analyzer/ui_kit/style.qss
  - rg -n "QLineEdit\\[role=\"search\"\\] QToolButton#searchFieldIconButton" mf4_analyzer/ui_kit/style.qss
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_channel_config_manager.py::test_manager_search_icons_stay_transparent_chips_under_qss tests/ui_kit/test_search_field.py -q
---

# Dialog QToolButton Chrome Must Spare SearchField Icons

Trigger: Adding dialog-wide `QToolButton` / `QPushButton` QSS, embedding
`SearchField` in a dialog, or restyling a panel that already has a local
button family.

Past failure: `QDialog#channelConfigManagerHtml QToolButton` is specificity
`(1,0,2)` and beat `QToolButton#searchFieldIconButton` `(1,0,1)`. The 18px
magnifier became a white 8px-radius chip with `padding: 0 10px` and
`min-height` of the dialog's 32px controls — two ghost buttons in both
search fields of the channel-config manager.

Rule: Do not rely on the ID-only search-icon rule. Keep
`QLineEdit[role="search"] QToolButton#searchFieldIconButton` at `(1,1,2)` so
it wins over `QDialog#id QToolButton`. If a dialog still needs a local lock,
use two IDs: `QDialog#id QToolButton#searchFieldIconButton`. QSS
`min-width: 0` also overrides `setFixedSize`; lock compact widgets with
matching min and max.

Verification: Run the manager search-icon geometry test under production
QSS and confirm both SearchField magnifiers stay 18×18.
