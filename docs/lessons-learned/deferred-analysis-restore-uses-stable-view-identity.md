---
id: deferred-analysis-restore-uses-stable-view-identity
status: active
owners: [codex]
keywords: [analysis-view, view-id, project-restore, async, generation, pane]
paths:
  - mf4_analyzer/ui/main_window/_analysis_mixin.py
  - mf4_analyzer/ui/main_window/frf_coordinator.py
checks:
  - rg -n "_analysis_restore_pending|invalidate_pane" mf4_analyzer/ui/main_window
tests:
  - tests/ui/test_frf_main_window.py
  - tests/ui/test_frf_coordinator.py
---

# Deferred Analysis Restore Uses Stable View Identity

Trigger: Adding deferred project restore or asynchronous compute for analysis
Views with reorderable tabs or multiple panes.

Past failure: FRF restore keyed pending work by list index and called the normal
compute action, so reordering could redirect the callback and live focused
controls could replace persisted inactive or split-pane source intent.

Rule: Key deferred work by persisted `view_id`, build every candidate from the
saved pane state, and invalidate in-flight work by `(view_id, pane_idx)` without
cancelling the section FIFO. Read live controls only for an explicit user
action on the focused pane.

Verification: Reorder the target before the deferred callback and assert the
same `view_id` dispatches; restore a two-pane View and assert both persisted
pairs submit; invalidate one in-flight pane and assert another pane completes.
