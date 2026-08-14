---
id: pyqt-ui/2026-08-14-ultraview-edge-shrinks-neighbors
status: active
owners: [codex]
keywords: [ultraview, free grid, out of grid, shrink, yield, FEEDBACK_OUT_OF_GRID, plan_boundary_yield]
paths: [mf4_analyzer/ui/chart_stack/ultraview/free_grid.py, mf4_analyzer/ui/chart_stack/ultraview/widgets.py, mf4_analyzer/ui/chart_stack/ultraview/page.py, tests/ui/test_ultraview_free_grid.py, tests/ui/test_ultraview_page.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_page.py -q]
tests: [tests/ui/test_ultraview_free_grid.py, tests/ui/test_ultraview_page.py]
---

# UltraView Edge Shrinks Neighbours Instead Of Dead-Ending

Trigger: Changing UltraView free-grid drag/resize commit, `FEEDBACK_OUT_OF_GRID`, `plan_boundary_yield`, or `plan_neighbor_shrink`.

Past failure: Dragging a card past the 12-column wall kept a useful red ghost but then toasted “不能移出网格”. Neighbours that could yield width (the two cards on the left in the screenshot) stayed put, so the grid felt like a dead-end.

Rule: Keep the red illegal ghost while dragging. On release, run Qt-free `plan_boundary_yield`: clamp into an empty in-board cell without a dialog; if the mover is stuck on the wall, shrink opposite-side neighbours down to `GRID_MIN_*` and grow the mover into that space after the same auto-avoid confirm. If shrinking still cannot fit, toast `FEEDBACK_OUT_OF_GRID`. Do not turn UltraView into an infinite canvas.

Verification: `test_boundary_yield_shrinks_left_neighbors_when_mover_hits_right_wall`, `test_boundary_yield_fails_when_left_neighbors_are_already_minimum`, `test_free_grid_edge_drop_prompts_and_shrinks_left_neighbors`, `test_free_grid_out_of_bounds_move_toasts_without_commit`.
