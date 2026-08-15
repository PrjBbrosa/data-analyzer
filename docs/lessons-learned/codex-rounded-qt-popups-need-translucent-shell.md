---
id: codex-rounded-qt-popups-need-translucent-shell
status: active
owners: [codex]
keywords: [pyqt, qmenu, popup, border-radius, WA_TranslucentBackground, NoDropShadowWindowHint, rounded-corners, 圆角, 方框, 阴影]
paths:
  - mf4_analyzer/ui/**
  - mf4_analyzer/acquisition_ui/**
  - mf4_analyzer/ui_kit/style.qss
  - mf4_analyzer/ui_kit/combo_popup_shell.py
checks:
  - rg -n "QMenu\\(|border-radius|WA_TranslucentBackground|NoDropShadowWindowHint|FramelessWindowHint" mf4_analyzer tests
tests:
  - PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
  - PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_combo_popup_shell.py tests/ui/test_qmenu_density.py -q
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
when the native rectangular shadow can leak past the radius. `QMenu.addMenu()`
creates a *separate* top-level window; the parent's shell does not inherit.
Route nested menus through `add_rounded_submenu()` / `apply_rounded_menu_chrome`
(the helper walks children and re-applies on `aboutToShow`). Attribute-only
tests are not enough for this class of bug: add a feature-level regression test
for the shell flags and use a screenshot, pixel harness, or live check when the
visual risk is platform-sensitive.

Verification: Grep for new/changed popup construction and confirm rounded
shells have `WA_TranslucentBackground` plus native-shadow flags where applicable.
Run the targeted UI test that asserts the attributes/flags, plus a screenshot or
live check when the change is visual-only or platform-sensitive.

## QComboBox dropdowns: covered centrally (do not patch per call site)

`QComboBox` popups are the same bug with a twist: the dropdown is a
top-level `QComboBoxPrivateContainer` window, and `style.qss` only rounds
the *inner* `QComboBox QAbstractItemView`, so the square container + native
shadow leaked behind every dropdown's rounded corners. There are ~30
`QComboBox(...)` call sites across Analyzer and Cockpit — patching each is
fragile, and the next one forgets.

Structural guard: an application event filter
(`mf4_analyzer/ui_kit/combo_popup_shell.py::install_combo_popup_shell`)
applies the shell (`WA_TranslucentBackground` +
`FramelessWindowHint | NoDropShadowWindowHint`) to *every* combo popup
window the first time the combo is shown, while its container is still
hidden (no re-show flicker). It is installed once from the shared
`ui_kit/stylesheet.py::load_stylesheet` chokepoint that both processes
already call, so no current or future combo needs to opt in.

Translucency is NOT enough on its own. `WA_TranslucentBackground` only
removes the opaque square *fill*; `QComboBoxPrivateContainer` still paints
a 1px square *frame* in its own paintEvent (via the style, independent of
`frameShape`), leaving a gray rectangle line outside the rounded list. A
GLOBAL `app.setStyleSheet` rule does NOT reach this private top-level
window (verified — the frame survived), so `_apply_shell` sets
`QComboBoxPrivateContainer { border: none; background: transparent; }`
directly on the container.

Rule for new work: do NOT add per-combo shell code — the filter handles it.
Still apply the manual shell for *new popup TYPES* (custom `QMenu`,
`Qt.Popup` `QWidget`, frameless `QDialog`). Regression test:
`tests/ui/test_combo_popup_shell.py`. Note: the type-ahead *completer*
popup of editable combos (`SearchableComboBox`) is a separate top-level
surface not yet covered — fold it in if it shows a square box in the real
app.
