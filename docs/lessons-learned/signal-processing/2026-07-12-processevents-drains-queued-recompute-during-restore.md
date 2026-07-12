---
role: signal-processing
tags: [project-restore, qtimer, processevents, event-loop, shared-navigator, reentrancy, guard-test]
created: 2026-07-12
updated: 2026-07-13
cause: insight
supersedes: []
---

## Context

Writing a Task 8 regression test (`test_project_save_in_time_mode_does_not_replace_inactive_analysis_sources`), a FULL `save_project()` → fresh-window `open_project()` round-trip synchronously corrupted the FFT analysis view's restored `(fid, ch)` source with the Time-domain view's checked channels — with no explicit `qtbot.wait()`/event-loop pump in the test. `open_project()` queues a post-load auto-recompute for each analysis section with populated-but-uncached sources via `QTimer.singleShot(0, ...)` (deferred), then later calls `_apply_active_view()` for the Time-domain view when `doc.current_mode == 'time'`. That path's `_plot_time_on_canvas()` calls `_begin_compute_progress(process_events=True)`, which calls `QApplication.processEvents()` — synchronously, still inside the same `open_project()` call. That drains the pending `QTimer.singleShot`, running `do_fft()`'s "capture current live state before compute" step, which reads the FFT/Time-domain SHARED `navigator.get_checked_channels()` — by then already overwritten with the Time view's own just-restored checklist. FFT's freshly restored source is silently replaced before `open_project()` even returns.

## Lesson

A `QTimer.singleShot(0, ...)` queued mid-restore is not actually deferred past the end of the restore function if ANY later step in the SAME call chain invokes `QApplication.processEvents()` (progress-bar / status-message patterns are a common source). When two different chart sections share one live-selection widget (a checkbox tree navigator used both as Time-domain's visible-channel state AND FFT's analysis source), any "capture current live selection" step run at the wrong moment captures the WRONG section's state — and it's invisible in a synchronous test unless the test happens to reach the exact widening code path (save-while-displaying-Time-mode, not save-while-displaying-any-analysis-section).

## How to apply

When writing a project-restore round-trip test, do not assume `QTimer.singleShot(0, ...)` stays queued until the test explicitly pumps the event loop — grep every restore-path call chain for `QApplication.processEvents()` (progress dialogs, status-bar-then-compute helpers) between the schedule site and the function return; if found, either test the SAVE-time (pre-serialization) invariant instead of a full reopen when the reopen path is out of your current task's ownership, or flag the restore-ordering issue to the owner of that restore code (progress/event-loop wiring is UI orchestration territory, not a numeric/domain bug) rather than silently rewriting the assertion to match the corrupted value.

**Fixed 2026-07-13** (not just deferred/flagged): widen the existing `_opening_project` reentrancy flag so it stays `True` for the FULL `open_project()` body, including the vulnerable `_apply_active_view()` step (not just the narrower `toolbar._set_mode()` sub-call it originally wrapped) — `finally` still resets it on every return path, including the render-failure early `return`. Then gate the ONE vulnerable capture site (`_capture_analysis_sources`'s `section == 'fft'` branch, the only section reading the shared Time/FFT navigator instead of a per-section combo) on that flag: while restoring, skip re-deriving `pane.sources` from the live navigator and trust the already-restored `AnalysisViewState.panes[*].sources` as-is. This is the smaller, principle-aligned fix over threading a "trusted state" parameter through `do_fft()`'s public signature. Proven via a NEW full-reopen test (`test_project_reopen_in_time_mode_does_not_replace_inactive_analysis_sources`) alongside the pre-existing save-time-only test it was previously scoped down to.
