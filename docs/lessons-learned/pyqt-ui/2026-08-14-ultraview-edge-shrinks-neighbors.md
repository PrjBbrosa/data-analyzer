---
id: pyqt-ui/2026-08-14-ultraview-edge-shrinks-neighbors
status: active
owners: [codex]
keywords: [ultraview, free grid, out of grid, shrink, yield, FEEDBACK_OUT_OF_GRID, plan_boundary_yield, plan_layout]
paths: [mf4_analyzer/ui/chart_stack/ultraview/free_grid.py, mf4_analyzer/ui/chart_stack/ultraview/widgets.py, mf4_analyzer/ui/chart_stack/ultraview/page.py, tests/ui/test_ultraview_free_grid.py, tests/ui/test_ultraview_page.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_page.py -q]
tests: [tests/ui/test_ultraview_free_grid.py, tests/ui/test_ultraview_page.py]
---

# UltraView Edge Rejects Instead Of Shrinking Neighbours

Trigger: Changing UltraView free-grid drag/resize commit, `FEEDBACK_OUT_OF_GRID`, `plan_layout`, `plan_boundary_yield`, or `plan_neighbor_shrink`.

Past failure: Dragging a card past the 12-column wall kept a useful red ghost but then toasted “不能移出网格”. Neighbours that could yield width stayed put, so the grid felt like a dead-end. The first fix grew the mover by shrinking opposite-side neighbours on routine drop. That silently changed other cards’ spans and conflicted with direct-manipulation size invariants.

Rule: Ordinary move/resize is size-preserving. If the clamped in-board hole is empty, commit that translation. If the mover is stuck on the wall with no same-size hole, show a reject ghost (outline plus mark, not color-only) and keep the original layout; toast `FEEDBACK_OUT_OF_GRID`. Neighbour shrink / mover grow belong only to an explicit arrange/organize command, never to routine drag/resize.

Verification: `test_plan_layout_edge_without_hole_rejects_without_grow_or_shrink`, `test_boundary_yield_rejects_wall_instead_of_shrinking_neighbors`, `test_free_grid_edge_drop_rejects_without_shrinking_neighbors`, `test_free_grid_out_of_bounds_move_toasts_without_commit`.
