# Phase C: chart_stack.py → chart_stack/ Package Decomposition Plan

**Date**: 2026-06-18  
**Branch**: refactor/large-file-decomp-abc  
**Scope**: Convert `mf4_analyzer/ui/chart_stack.py` (3008 lines) to a same-named package.

---

## Summary

Pure relocation (Form A). No behavior/signature/logic changes. Verbatim class/function bodies.

## Re-export surface (exhaustive, from grep of tests + application code)

From `tests/ui/test_chart_stack.py`:
- `ChartStack` (lines 11, 81, 129, 156, 1583, 1595, 1610, 1621, 1633, 1649, ...)
- `_CURSOR_HTML_SEP` (line 11)
- `_apply_mdi_icons` (line 16)
- `_MDI_NAV_ICONS` (line 16)
- `CursorPill` (line 92)
- `TimeChartCard` (line 1633)
- `_ChartCard` (lines 1908, 1925)
- `_BOTTOM_HINT_PERSISTENT` (line 2118)

From `mf4_analyzer/ui/main_window.py`:
- `ChartStack` (line 90)
- `_STATS_STRIP_ENABLED` (line 2894)

All of the above must be in `__init__.py`.

## Target layout

```
mf4_analyzer/ui/chart_stack/
├── __init__.py       # re-exports: ChartStack, CursorPill, TimeChartCard,
│                     #  _ChartCard, _CURSOR_HTML_SEP, _apply_mdi_icons,
│                     #  _MDI_NAV_ICONS, _BOTTOM_HINT_PERSISTENT, _STATS_STRIP_ENABLED
├── _helpers.py       # lines 1–89 (pixmap/html helpers)
│                     # + lines 328–411 (toolbar helpers: _strip_subplots_action,
│                     #   _find_action, _apply_mdi_icons, _install_nav_shortcuts,
│                     #   _install_button_shortcut, _vline)
│                     # + constant: _MDI_NAV_ICONS (line 310–317)
│                     # + module-level constants: _HIDPI_EXPORT_SCALE, _CURSOR_PILL_*,
│                     #   _ICON_COLOR, _ICON_ACTIVE, _TOOLBAR_COMPACT_WIDTH,
│                     #   _QT_WIDGETSIZE_MAX, _STATS_STRIP_ENABLED, _NAV_SHORTCUTS,
│                     #   _TIME_CARD_SHORTCUTS
├── cursor_pill.py    # lines 90–328: CursorPill, _QualityStatusIndicator
│                     # + constant: _CURSOR_HTML_SEP (line 307)
├── toolbar.py        # lines 276–282 (external imports for PgNavigationToolbar)
│                     # + lines 413–1096: _TickDensityPopover, PgNavigationToolbar
├── cards.py          # lines 1097–1933: _ChartCard, TimeChartCard
└── stack.py          # lines 1934–3008: ChartStack
```

## Import wiring between sub-files

- `_helpers.py`: top-level imports only (PyQt5, qtawesome, hints, QKeySequence etc.)
- `cursor_pill.py`: from `._helpers` import `_format_mini_html`; external import `from .canvases import _format_dual_html` stays in the method (already a local import)
- `toolbar.py`: from `._helpers` import `_grab_pixmap_hidpi`; external imports at top
- `cards.py`: from `._helpers` import `_strip_subplots_action, _find_action, _apply_mdi_icons, _install_nav_shortcuts, _install_button_shortcut, _vline, _ICON_COLOR, _ICON_ACTIVE, _TOOLBAR_COMPACT_WIDTH, _QT_WIDGETSIZE_MAX`; from `.toolbar` import `PgNavigationToolbar, _TickDensityPopover`; from `.cursor_pill` import `_QualityStatusIndicator`
- `stack.py`: from `._helpers` import `_grab_pixmap_hidpi, _pixmap_as_device_pixels, _HIDPI_EXPORT_SCALE, _STATS_STRIP_ENABLED, _MODE_TO_INDEX, _INDEX_TO_MODE, _BOTTOM_HINT_PERSISTENT`; from `.cards` import `_ChartCard, TimeChartCard`; from `.cursor_pill` import `CursorPill`; from `.toolbar` import `PgNavigationToolbar`

Note: `_MODE_TO_INDEX`, `_INDEX_TO_MODE`, `_BOTTOM_HINT_PERSISTENT` live in `_helpers.py` since stack.py is the only consumer.

## Monkeypatch check

No monkeypatch targets in `tests/ui/test_chart_stack.py` for module-level names. Verified by grep: tests only import names, no `monkeypatch.setattr("mf4_analyzer.ui.chart_stack.*")` calls.

## Task steps

1. Read the full source file (DONE)
2. Grep exhaustive import surface (DONE)
3. Create `mf4_analyzer/ui/chart_stack/` directory
4. Write `_helpers.py`
5. Write `cursor_pill.py`
6. Write `toolbar.py`
7. Write `cards.py`
8. Write `stack.py`
9. Write `__init__.py`
10. Delete `mf4_analyzer/ui/chart_stack.py` via git rm
11. Run targeted tests: `test_chart_stack.py` — must pass
12. Run full suite — GREEN (<=2 known-flaky)
13. Commit with explicit pathspec

## Test command

```
.venv/Scripts/python.exe -m pytest tests/ui/test_chart_stack.py -q --basetemp=.pytest_tmp
.venv/Scripts/python.exe -m pytest -q --basetemp=.pytest_tmp
```
