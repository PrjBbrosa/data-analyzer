---
id: pyqt-ui/2026-05-27-overlay-selection-drops-pan
status: active
owners: [main]
keywords: [pyqt, matplotlib, timedomain, overlay, selection, pan, chart-stack, toolbar]
paths: [mf4_analyzer/ui/canvases.py, mf4_analyzer/ui/chart_stack.py, tests/ui/test_chart_stack.py]
checks: [QT_QPA_PLATFORM=offscreen PYTHONPATH=. MPLCONFIGDIR=.pytmp/mpl PYTEST_DEBUG_TEMPROOT=.pytmp .venv/Scripts/python.exe -m pytest tests/ui/test_chart_stack.py -q]
tests: [tests/ui/test_chart_stack.py::test_overlay_curve_drag_leaves_toolbar_idle_during_selection, tests/ui/test_chart_stack.py::test_overlay_blank_click_clears_selection_after_curve_drag]
---

# Overlay Selection Drops Pan (Blank-Click Deselect)

Trigger: Implementing a click-to-exit gesture on a matplotlib canvas
while the NavigationToolbar2 is in pan or zoom mode.

Rule: When a click-to-enter gesture also requires a click-to-exit gesture
on the SAME canvas, the enter handler must force the matplotlib nav
toolbar OUT of pan/zoom (call `toolbar.pan()` if pan is active, or
`toolbar.zoom()` if zoom is active — both toggle off). NavigationToolbar2
consumes button_press events as the start of a pan drag whenever pan is
the active tool; a blank-area click then registers as a zero-distance pan
gesture and never reaches the application's click handler. Restoring pan
on exit re-creates the trap on the next selection cycle, so do NOT
auto-restore — let the user re-engage pan explicitly via shortcut (Ctrl+G
in this app) if they want it back.

Past failure (lesson 2026-05-26): Chart card restored pan after every
overlay curve drag, which meant the user had to manually drop pan
themselves before a blank-area click would clear the overlay selection.
The tests passed because the press-side deselect gate was wired
correctly, but the matplotlib pan tool intercepted the press event in
the Qt-native path long before the deselect gate ran.

Verification: Run
`tests/ui/test_chart_stack.py::test_overlay_curve_drag_leaves_toolbar_idle_during_selection`
and
`tests/ui/test_chart_stack.py::test_overlay_blank_click_clears_selection_after_curve_drag`.
Both assert `'pan' not in str(toolbar.mode).lower()` after selection.
