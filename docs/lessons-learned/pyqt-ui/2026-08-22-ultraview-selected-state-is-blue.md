---
id: pyqt-ui/2026-08-22-ultraview-selected-state-is-blue
status: active
owners: [codex]
keywords: [ultraview, selected, blue, warning, amber, overlay, CanvasHost, pointer, laser]
paths:
  - mf4_analyzer/ui_kit/ultraview_style.py
  - mf4_analyzer/ui_kit/style.qss
  - mf4_analyzer/ui/chart_stack/ultraview/chrome.py
  - mf4_analyzer/ui/chart_stack/ultraview/author_tools.py
checks:
  - rg -n "qlineargradient.*UV_AMBER|UV_RAIL_ACTIVE_|Titanium Amber" mf4_analyzer/ui_kit/style.qss mf4_analyzer/ui_kit/ultraview_style.py mf4_analyzer/ui/chart_stack/ultraview/chrome.py
  - rg -n "def reassert_stacking|pointer_mode|OVERLAY_AUTHOR_POINTER" mf4_analyzer/ui/chart_stack/ultraview
tests:
  - tests/ui_kit/test_ultraview_style.py
  - tests/ui/test_ultraview_author_chrome.py
  - tests/ui/test_ultraview_author_tools.py
---

# UltraView Selected State Is Blue

Trigger: Changing UltraView rail, island, presentation, library selected-row, canvas glow, or CanvasHost flyout stacking.

Past failure: Regular UltraView chrome used Titanium Amber gradients for selected/current/open states, so warning badges could not be distinguished from "this is the current tool". Flyouts also lost z-order after island/toolbar `raise_()`, and `QMenu.exec_()` in tests blocked the offscreen suite.

Rule: Selected, current-tool, panel-open, and presentation chrome share `UV_SELECTED` / `UV_SELECTED_WASH`. `UV_WARNING` is only for unplaced, stale, sync, and risk. Pointer/laser are `TOOL_SELECT` session modes, not author objects. All app flyouts go through `CanvasHost.open_overlay()`; after any chrome `raise_()`, call `reassert_stacking()` so the active overlay stays on top. Native menus use `popup()` after closing the active overlay, not a blocking `exec_()`.

Verification: `tests/ui_kit/test_ultraview_style.py`, `tests/ui/test_ultraview_author_chrome.py`, `tests/ui/test_ultraview_author_tools.py`. Grep must not find regular-chrome amber gradients.
