---
id: project-restore-progress-yields-event-loop
status: active
owners: [codex]
keywords: [project-restore, progress-bar, processevents, beachball, qtimer, sip]
paths:
  - mf4_analyzer/ui/main_window/_analysis_mixin.py
  - mf4_analyzer/ui/main_window/window.py
checks:
  - rg -n "_pump_analysis_restore|_restore_progress_token|_abort_analysis_restore" mf4_analyzer/ui/main_window
tests:
  - tests/ui/test_compute_progress.py
  - tests/ui/test_project_session.py
---

# Project Restore Progress Yields The Event Loop

Trigger: Changing project open, analysis-view restore scheduling, compute progress, or any `processEvents` on the restore path.

Past failure: Opening a `.tlproj` queued every analysis View as `QTimer.singleShot(0)` and then time-plot `_begin_compute_progress(process_events=True)` drained them in one burst. The status bar never owned a restore token, the GUI thread stayed in compute, and macOS showed the beachball. Closing the window while a restore timer was armed painted a deleted `QProgressBar`.

Rule: Restore uses one `"restore"` progress token and pumps **one View per timer tick**. Nested time-plot / section `begin` must return that token and must not `processEvents` the restore pump. `flush_events` (ExcludeUserInput) is only for yielding inside a still-running View, and only **before** the next pump `singleShot` is posted. Close / teardown must abort the queue and no-op when `sip.isdeleted(self)` or the progress widget is gone. Do not assign `_analysis_restore_queue` from `window.py` (state-ownership ratchet).

Verification: `tests/ui/test_compute_progress.py` (`test_restore_progress_token_blocks_nested_process_events`, `test_analysis_restore_pump_survives_closed_window`). `tests/ui/test_project_session.py` asserts open leaves the queue undrained (`recomputed == []`) until `_drain_analysis_restore` pumps it, with label 「恢复分析」.
