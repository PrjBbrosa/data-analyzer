---
id: codex-stateful-icon-button-active-qss
status: active
owners: [codex]
keywords: [pyqt, qtoolbutton, qss, active-property, hover, follow-link, autoAttachFiles]
paths:
  - mf4_analyzer/ui/file_navigator.py
  - mf4_analyzer/ui_kit/style.qss
  - tests/ui/test_file_navigator.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_file_navigator.py::test_follow_link_active_chrome_survives_hover_and_idle_stays_plain -q
---

# Stateful Icon Buttons Need active QSS And String Attrs

Trigger: Adding or changing a non-checkable icon `QToolButton` whose on/off
look is driven by a dynamic property (follow-link, navActive, similar).

Past failure: `btn_auto_attach` set `property("active", bool)` and swapped
link/link-off icons, but QSS only styled generic `role="icon":hover/pressed`.
Active wash disappeared on hover; idle clicks flashed a misleading wash.

Rule: Drive chrome with string attrs (`"true"`/`"false"`), add explicit
`#objectName[active="true|false"]` rules that cover `:hover`, `:pressed`, and
`:focus`, and keep idle presses transparent when icon swap already signals off.
Verify with rendered corner pixels, not property assertions alone.

Verification: Run the follow-link active/idle chrome test under the real
stylesheet.
