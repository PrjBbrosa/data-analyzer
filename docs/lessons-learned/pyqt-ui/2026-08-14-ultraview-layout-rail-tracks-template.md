---
id: pyqt-ui/2026-08-14-ultraview-layout-rail-tracks-template
status: active
owners: [codex]
keywords: [ultraview, ToolRail, layout, free-grid, active, template]
paths: [mf4_analyzer/ui/chart_stack/ultraview/chrome.py, tests/ui/test_ultraview_chrome.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_chrome.py::test_tool_rail_free_grid_sits_between_library_and_layout tests/ui/test_ultraview_chrome.py::test_tool_rail_layout_is_active_when_a_template_is_current -q]
tests: [tests/ui/test_ultraview_chrome.py]
---

# UltraView Layout Rail Tracks Template Mode

Trigger: Changing UltraView `ToolRail` button order, layout/free-grid `active` chrome, or `_sync_button_states`.

Past failure: The layout rail button only lit while its popover was open. Free-grid already kept a persistent mode highlight, so a selected template (3×3, 4×3, …) looked unselected after the picker closed.

Rule: Visual order is Library, FreeGrid, Layout, Filter, divider, Unplaced. Layout `active` is true when the current board is a template (`not _free_grid_enabled`) or the layout panel is open. Keep `setChecked` for the open panel only. Mirror the filter pattern (`PANEL_FILTER and self._filter_active`).

Verification: `test_tool_rail_free_grid_sits_between_library_and_layout` and `test_tool_rail_layout_is_active_when_a_template_is_current`.
