---
id: codex-analysis-view-restore-projection-guards
status: active
owners: [codex]
keywords: [analysis-view, restore, projection, delayed-compute, navigator]
paths:
  - mf4_analyzer/ui/main_window/_analysis_mixin.py
  - mf4_analyzer/ui/main_window/_view_mixin.py
  - mf4_analyzer/ui/main_window/_project_io_mixin.py
  - mf4_analyzer/ui/main_window/window.py
checks:
  - Programmatic View application must not enter user-edit callbacks or submit analysis jobs.
  - A hidden section must not project its controls or owner text onto the shared navigator.
tests:
  - tests/ui/test_analysis_multiview_integration.py::test_order_view_switch_with_cold_cache_does_not_submit_worker
  - tests/ui/test_project_session.py::test_open_project_keeps_analysis_empty_owner_after_time_view_restore
---

# Guard programmatic analysis-View restore at both signal and projection boundaries

Trigger: Changing analysis View application, project restore, shared Inspector
signals, or the shared navigator projection.

Past failure: Applying a saved dB reference emitted a delayed user-edit callback
that submitted a cold-cache Order job. Separately, project reopen restored the
visible FRF View and then projected the hidden Time View, changing the left-rail
owner text to `时域 · View 2` while FRF remained active.

Rule: Treat View restore as projection, not user input. Guard callbacks for the
entire programmatic apply interval, and project a section onto shared controls
only while that section is visible. Do not infer correctness from serialized
state alone; drain deferred callbacks and inspect the live owner/projection.

Verification: Run the two focused tests listed above, assert zero
`AnalysisJobService.submit_batch` calls after the event queue drains, and reopen
a non-Time project whose Time and analysis managers both use a nonzero active
View. For UI acceptance, verify the visible section and left-rail owner agree in
the real Cocoa app.
