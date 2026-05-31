---
id: codex-pg-subplot-layout-settle
status: active
owners: [codex]
keywords: [pyqtgraph, subplot, x-grid, AxisItem, GraphicsLayout, first-frame, geometry]
paths: [mf4_analyzer/ui/pg_canvases.py, tests/ui/test_pg_timedomain_canvas.py]
checks: [rg -n "_unify_subplot_left_axis_widths|test_subplot_x_grid_geometry_is_aligned_before_first_frame"]
tests: [tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSubplotMode::test_subplot_x_grid_geometry_is_aligned_before_first_frame]
---

# Pyqtgraph Subplot Layout Settle

Trigger: Load when changing pyqtgraph TimeDomain subplot axes, grid, tick
density, inside-label placement, resize handling, or first-frame geometry.

Past failure: Subplot X ranges were numerically synchronized, but one row's
left AxisItem width changed after the early width pin. The first rendered frame
mapped the same data X to a different scene X, so vertical X grid lines looked
misaligned even though a later Qt event pass could hide the problem.

Rule: After late AxisItem-affecting work such as data-union X seeding or tick
density changes, re-run the subplot left-axis width unifier and force the
GraphicsLayout to `invalidate()` and `activate()` before claiming first-frame
grid alignment.

Verification: Add or run a regression that measures
`ViewBox.mapViewToScene(QPointF(x, 0.0)).x()` across all subplot rows before an
extra Qt event pass; all rows should match within pixel tolerance.
