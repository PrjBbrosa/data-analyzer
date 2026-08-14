---
id: pyqt-ui/2026-08-14-ultraview-island-sizehint-uses-ishidden
status: active
owners: [codex]
keywords: [ultraview, GlobalIsland, sizeHint, isVisible, isHidden, floating chrome, stacked icons]
paths: [mf4_analyzer/ui/chart_stack/ultraview/chrome.py, tests/ui/test_ultraview_chrome.py, tests/ui/test_ultraview_page.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_chrome.py::test_global_island_size_hint_ignores_unshown_ancestors tests/ui/test_ultraview_page.py::test_global_island_buttons_do_not_stack -q]
tests: [tests/ui/test_ultraview_chrome.py, tests/ui/test_ultraview_page.py]
---

# UltraView Island SizeHint Uses isHidden

Trigger: Changing UltraView floating-island `sizeHint`, `GlobalIsland.set_edit_visible`, or `_chrome_sizes` / `_apply_floating_layout` geometry.

Past failure: `GlobalIsland.sizeHint` counted `button.isVisible()`. That stays False until the island and every ancestor are shown, so the first layout reserved a one-button 40×40 square. Display, export, and presentation icons stacked in the top-right.

Rule: Size chrome from explicit hide state (`not isHidden()`), never from `isVisible()`. `isHidden()` is the per-widget flag `setVisible(False)` sets; `isVisible()` also requires every ancestor to be shown. Keep presentation mode shrinking via `set_edit_visible(False)`. Assert the unshown sizeHint already fits three buttons, and that applied page geometry does not overlap them.

Verification: `test_global_island_size_hint_ignores_unshown_ancestors` and `test_global_island_buttons_do_not_stack`.
