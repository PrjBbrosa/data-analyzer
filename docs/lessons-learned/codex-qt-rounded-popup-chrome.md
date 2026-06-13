---
id: codex-qt-rounded-popup-chrome
status: active
owners: [codex]
keywords: [qt, pyqt, qmenu, qcombobox, qss, rounded, popup, focus-frame, popupWidth]
paths: [mf4_analyzer/ui_kit/style.qss, mf4_analyzer/ui_kit/menus.py, mf4_analyzer/ui_kit/combo_popup_shell.py, mf4_analyzer/ui_kit/widgets/searchable_combo.py, mf4_analyzer/ui/view_tabbar.py, mf4_analyzer/ui/inspector_sections.py]
checks: [rg -n "QMenu\\(" mf4_analyzer -g "*.py", rg -n "prepare_combo_popup|popupWidth|popupMinWidth|popupMaxWidth" mf4_analyzer/ui_kit tests/ui/test_combo_popup_shell.py, git diff --check]
tests: [tests/ui/test_combo_popup_shell.py, tests/ui/test_view_tabbar.py, tests/ui/test_inspector.py]
---

# Codex Qt Rounded Popup Chrome

Trigger: Changing rounded popup/dropdown/menu styling or adding a new `QMenu`,
`QComboBox` popup, custom completer popup, or hover card in PyQt UI.

Past failure: Rounded QSS was added to popup content while the native Qt popup
window, item-view outline, or focus rectangle remained active. Users saw square
frames behind rounded menus and double blue outlines around selected combo rows.

Rule: Rounded popup visuals must suppress the native backing chrome as well as
draw the custom content before the first visible frame. For `QMenu`, route new
project menus through `apply_rounded_menu_chrome()` or an equivalent
transparent, frameless, no-drop-shadow shell. For `QComboBox`, keep popup
shell, first-frame list/viewport background, and width policy centralized in
`prepare_combo_popup()`; use `popupWidth`, `popupMinWidth`, or `popupMaxWidth`
dynamic properties for width changes instead of per-combo ad hoc geometry. For
`QComboBox QAbstractItemView`, suppress `border` and `outline` on the item view
and draw selected/hover state on `::item`.

Verification: Grep new `QMenu(` call sites for shared chrome handling, run
`tests/ui/test_combo_popup_shell.py`, `tests/ui/test_view_tabbar.py`, and
`tests/ui/test_inspector.py`, and finish with `git diff --check`.
