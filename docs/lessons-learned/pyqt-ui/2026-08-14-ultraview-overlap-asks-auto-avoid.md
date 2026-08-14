---
id: pyqt-ui/2026-08-14-ultraview-overlap-asks-auto-avoid
status: active
owners: [codex]
keywords: [ultraview, free grid, overlap, auto-avoid, collision, toast, CardContextIsland]
paths: [mf4_analyzer/ui/chart_stack/ultraview/free_grid.py, mf4_analyzer/ui/chart_stack/ultraview/widgets.py, mf4_analyzer/ui/chart_stack/ultraview/page.py, tests/ui/test_ultraview_free_grid.py, tests/ui/test_ultraview_page.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_page.py -q]
tests: [tests/ui/test_ultraview_free_grid.py, tests/ui/test_ultraview_page.py]
---

# UltraView Overlap Asks Then Auto-Avoids

Trigger: Changing UltraView free-grid drag/resize commit, overlap toasts, or `plan_overlap_avoidance`.

Past failure: Dropping onto a neighbour aborted with only a red ghost and “目标位置与其他卡片重叠”. The red state was useful; the silent fail was not. Pushing without asking would also violate the old P2 no-reflow rule.

Rule: Keep the red illegal ghost while dragging. On release, if blockers can move, ask “是否自动避让” and commit mover+blockers atomically via `group_geometry_requested`. If a blocker is boxed in, try `plan_neighbor_shrink` before toasting `FEEDBACK_AVOID_BOUNDARY`. Cancel leaves cards where they were. Out-of-grid drops go through `plan_boundary_yield` (clamp / shrink neighbours) rather than toasting `FEEDBACK_OUT_OF_GRID` first.

Verification: `test_overlap_avoidance_slides_blocker_down_when_right_is_blocked`, `test_overlap_avoidance_fails_when_board_is_packed`, `test_free_grid_overlap_drop_prompts_and_moves_blocker`, `test_free_grid_overlap_drop_declined_does_not_commit`, `test_free_grid_overlap_at_boundary_toasts_without_commit`.
