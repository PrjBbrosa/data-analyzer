---
id: pyqt-ui/2026-08-14-ultraview-card-context-follows-selection
status: active
owners: [codex]
keywords: [ultraview, CardContextIsland, selection, _selected, Esc, empty click, gesture]
paths: [mf4_analyzer/ui/chart_stack/ultraview/page.py, mf4_analyzer/ui/chart_stack/ultraview/widgets.py, tests/ui/test_ultraview_page.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_page.py -k "escape or card_context or empty_click or gutter_click or host_padding" -q]
tests: [tests/ui/test_ultraview_page.py]
---

# UltraView Card Context Follows Page Selection

Trigger: Changing UltraView `CardContextIsland`, Esc, empty-canvas click, `UltraViewPage._selected`, or `FreeGridBoard` gesture selection.

Past failure: Esc and empty-board press cleared free-grid rings via the gesture, but left `page._selected`. The 5-icon card-context island follows `_selected`, so it stayed up with no card selected.

Rule: Hide `CardContextIsland` only through `clear_card_selection()`, which drops `_selected`, free-grid gesture selection, and template `selected` flags together. Do not treat gesture rings as the only selection owner. Do not clear library row highlight; empty-slot place reads it. `eventFilter` branches that mention `_board_host` must `getattr` first: the canvas-host filter is installed before that attribute exists.

Verification: `test_free_grid_escape_clears_selection`, `test_template_escape_hides_card_context_island`, `test_free_grid_empty_click_hides_card_context_island`, `test_template_gutter_click_hides_card_context_island`, `test_board_host_padding_click_hides_card_context_island`.
