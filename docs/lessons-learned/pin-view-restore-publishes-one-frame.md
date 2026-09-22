---
id: pin-view-restore-publishes-one-frame
status: active
owners: [codex]
keywords: [pinned-cursor, view-restore, page-transition, pending]
paths:
  - mf4_analyzer/ui/main_window/_view_mixin.py
  - mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py
  - mf4_analyzer/ui/chart_stack/pinning/presentation.py
  - mf4_analyzer/ui/chart_stack/stack.py
checks: [git diff --check]
tests:
  - tests/ui/test_pinned_cursor_lifecycle.py::test_restore_batch_reveals_every_pin_without_a_pending_frame
  - tests/ui/test_pinned_cursor_lifecycle.py::test_direct_collection_replace_still_shows_pending_before_sample
  - tests/ui/test_page_transition_integration.py::test_paint_ack_waits_for_pin_restore_commit_then_fades
---

# Pin View Restore Publishes One Frame

Trigger: Changing time-domain View restore, pinned-cursor projection, or the page-transition accept path.

Past failure: `set_collection` projected pending pills and raised them before the target curves settled. Those widgets sit on the stack, outside canvas update suppression, so they covered the transition mask and then jumped from "更新中" to final values.

Rule: A view-restore batch samples and lays out every target pin once, after X/Y/ticks settlement, and publishes them together. Ordinary recomputes still show pending immediately. The page transition fades only after that commit and the canvas paint ack; pin `raise_()` must not cover a visible transition overlay.

Verification: Run the restore-batch, ordinary-pending, and paint-ack pin-wait tests with offscreen Qt, plus `git diff --check`.
