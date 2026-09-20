---
id: popup-trigger-hover-must-bind-each-entry
status: active
owners: [codex]
keywords: [pyqt, qmenu, popup, hover, WA_UnderMouse, kebab, QToolButton]
paths:
  - mf4_analyzer/ui_kit/popup_trigger.py
  - mf4_analyzer/ui/file_navigator.py
  - mf4_analyzer/ui/toolbar.py
  - mf4_analyzer/ui/chart_stack/cards.py
  - tests/ui_kit/test_popup_trigger.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui_kit/test_popup_trigger.py tests/ui/test_file_navigator.py::test_kebab_menu_dismiss_clears_stale_hover_without_mousemove tests/ui/test_toolbar.py::test_save_caret_menu_dismiss_clears_stale_hover_on_caret tests/ui/test_chart_stack.py::test_cursor_display_settings_button_clears_hover_when_popover_hides -q
---

# Popup Trigger Hover Must Bind Each Entry

Trigger: Adding or changing a button that opens `QMenu.exec_`, `QMenu.popup`,
or a custom `Qt.Popup`.

Past failure: Cursor settings already cleared stale `WA_UnderMouse` in a local
hide callback, but FileNavigator ⋮ / follow menus and the save caret did not.
After the popup grabbed the mouse, QSS `:hover` stayed until the next move.

Rule: Bind `ui_kit.popup_trigger.bind_popup_trigger(popup, trigger)` to the
actual trigger widget. Do not copy a one-off callback, and do not clear
checked / `active` / focus. Sync from the live pointer after hide; queue past
`aboutToHide` if the grab is still held.

Verification: Run the shared helper tests plus kebab, save-caret, and cursor
popover hover tests under the production stylesheet.
