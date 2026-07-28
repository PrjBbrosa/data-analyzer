---
id: batch-task-list-information-weighted-height
status: active
owners: [codex]
keywords: [BatchTaskList, QListWidget, empty state, maximumHeight, collapsible]
paths: [mf4_analyzer/ui/drawers/batch/task_list.py, mf4_analyzer/ui/drawers/batch/sheet.py]
checks: [1080x760 empty and populated geometry, offscreen screenshot, Cocoa screenshot]
tests: [tests/ui/test_batch_task_list.py, tests/ui/test_batch_smoke.py]
---

# Batch Task List Height Follows Its Information

Trigger: Changing BatchSheet task preview rows, task statuses, disclosure behavior, or the bottom task-list layout.

Past failure: The empty task list kept its populated `180 px` body visible, so the full task region consumed `222 px` of a `760 px` dialog while showing no information. The three configuration panes lost almost one third of the available height.

Rule: Hide the task body when there are no task rows. When rows exist, keep the header visible, cap the body at a compact height, and let the list scroll internally; collapsing must preserve the footer and configuration-pane space.

Verification: At 1080×760, assert the empty task body is hidden and the task region is header-only. Populate more rows than fit, assert the body is capped at `120 px` with a non-zero vertical scroll range, run the Batch UI tests, and inspect both offscreen and Cocoa screenshots.
