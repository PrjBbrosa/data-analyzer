---
id: 2026-08-19-ultraview-microgrid-coordinate-space
status: active
owners: [codex]
keywords: [ultraview, free-grid, micro-grid, persistence, edge-pan]
paths:
  - mf4_analyzer/ui/ultraview_state.py
  - mf4_analyzer/ui/chart_stack/ultraview/free_grid.py
  - mf4_analyzer/ui/chart_stack/ultraview/page.py
checks:
  - legacy pixel geometry stays unchanged after a schema migration
  - native drag replacement hover stays armed through edge-pan timer ticks
tests:
  - tests/ui/test_ultraview_state.py
  - tests/ui/test_ultraview_free_grid.py
  - tests/ui/test_ultraview_page.py
---

# UltraView Micro-grid Coordinate Space

Trigger: Increasing Free Grid placement precision or changing its persisted coordinate scale.

Past failure: A 2× coordinate migration can preserve rect numbers incorrectly,
which changes on-screen geometry; an edge-pan timer sampling a stale cursor can
also clear a native-drag replacement hover between drag events.

Rule: Migrate every legacy coordinate and span at the persistence boundary,
then use the micro-cell pixel pitch everywhere viewport, workspace, card, and
export geometry are calculated. During an external drag, retain the most
recent event position for timer ticks instead of replacing it with a stale
global cursor query.

Verification: Assert legacy versus migrated pixel geometry, check an odd
micro-grid aspect candidate improves the shared preview reading box, and run
the focused state/free-grid/page tests plus a Cocoa component screenshot.
