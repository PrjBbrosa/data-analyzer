---
id: pyqt-ui/2026-05-26-overlay-deselect-pan-restore
status: superseded
superseded_by: pyqt-ui/2026-05-27-overlay-selection-drops-pan
owners: [codex]
keywords: [pyqt, matplotlib, timedomain, overlay, selection, pan, chart-stack]
paths: [mf4_analyzer/ui/canvases.py, mf4_analyzer/ui/chart_stack.py, tests/ui/test_chart_stack.py, tests/ui/test_canvases.py]
checks: []
tests: []
---

# Overlay Deselect After Pan Restore (superseded)

This lesson described how to make blank-click deselect coexist with the
"auto-restore pan after curve drag" behavior in TimeChartCard. That
auto-restore mechanism was removed on 2026-05-27 — the chart card now
switches the matplotlib nav toolbar OUT of pan/zoom when a curve is
selected and does NOT auto-restore on deselect. Blank-click deselect
therefore runs without contention because the toolbar is already idle
during selection.

See [[2026-05-27-overlay-selection-drops-pan]] for the current design.
