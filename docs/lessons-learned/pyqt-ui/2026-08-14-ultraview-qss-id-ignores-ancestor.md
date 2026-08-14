---
id: pyqt-ui/2026-08-14-ultraview-qss-id-ignores-ancestor
status: active
owners: [codex]
keywords: [ultraview, QSS, ID selector, descendant, presentation, GlobalIsland, presentationExit]
paths: [mf4_analyzer/ui_kit/style.qss, mf4_analyzer/ui/chart_stack/ultraview/chrome.py, tests/ui/test_ultraview_chrome.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_chrome.py::test_idle_presentation_button_is_not_exit_fill tests/ui/test_ultraview_chrome.py::test_presentation_exit_qss_does_not_use_page_descendant_id -q]
tests: [tests/ui/test_ultraview_chrome.py]
---

# UltraView QSS ID Ignores Ancestor Qualifier

Trigger: Styling an UltraView control with a page-level QSS descendant plus a child `#objectName`, especially `ultraViewGlobalPresentationButton`.

Past failure: `QWidget#ultraViewPage[presentation="true"] QToolButton#ultraViewGlobalPresentationButton` painted solid `#1769e0`. Qt ID matching applied that fill even when the page was not in presentation mode, so the idle 演示 button looked turned on.

Rule: Drive on/off chrome from the button's own `active` / `role` properties. Do not qualify a unique `#id` with an ancestor dynamic property. Idle stays `role="icon"`; presentation-exit sets `role="presentationExit"` and `active="true"`. Match QSS min/max size to `setFixedSize`, paint the island itself in the exit fill so 4px padding is not a white square, and swap the QIcon to a light glyph — `color:` in QSS does not recolor a `QIcon`. Assert the QSS file no longer contains the page-descendant ID selector, and grab an idle corner pixel that is not accent fill.

Verification: `test_presentation_exit_qss_does_not_use_page_descendant_id` and `test_idle_presentation_button_is_not_exit_fill`.
