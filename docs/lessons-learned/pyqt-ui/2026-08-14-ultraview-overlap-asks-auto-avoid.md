---
id: pyqt-ui/2026-08-14-ultraview-overlap-asks-auto-avoid
status: active
owners: [codex]
keywords: [ultraview, free grid, overlap, auto-avoid, collision, toast, LayoutPlan, plan_layout]
paths: [mf4_analyzer/ui/chart_stack/ultraview/free_grid.py, mf4_analyzer/ui/chart_stack/ultraview/widgets.py, mf4_analyzer/ui/chart_stack/ultraview/page.py, tests/ui/test_ultraview_free_grid.py, tests/ui/test_ultraview_page.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_page.py -q]
tests: [tests/ui/test_ultraview_free_grid.py, tests/ui/test_ultraview_page.py]
---

# UltraView Overlap Previews Then Translates Without A Modal

Trigger: Changing UltraView free-grid drag/resize commit, overlap toasts, `plan_layout`, or `plan_overlap_avoidance`.

Past failure: Dropping onto a neighbour aborted with only a red ghost and “目标位置与其他卡片重叠”. The red state was useful; the silent fail was not. The next rule asked “是否自动避让” via `QMessageBox` and then translated blockers. The modal blocked preview, and a declined dialog was easy to confuse with a failed drop.

Rule: Direct manipulation computes a Qt-free `LayoutPlan` while dragging. Ghost shows the mover and every displaced card at the geometry that will be committed. Move keeps every span; resize may change only the mover span. Blockers translate same-size. No `QMessageBox` on routine collision. Success is a non-modal toast such as “已重排 3 张 · Ctrl+Z 撤销” as one undo command. If no legal layout exists, reject ghost + short status; Esc / focus-loss / release do not commit. Neighbour shrink remains an explicit arrange path, not this gesture.

Verification: `test_plan_layout_move_keeps_every_span`, `test_free_grid_overlap_drop_moves_blocker_without_modal`, `test_free_grid_overlap_drop_does_not_construct_message_box`, `test_free_grid_collision_commit_is_one_undo_restoring_all_cards`.
