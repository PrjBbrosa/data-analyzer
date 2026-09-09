---
id: codex-batch-reparented-controls-and-guidance-lifecycle
status: active
owners: [codex]
keywords: [batch, reparent, method, run-lock, guidance, locate, validation]
paths: [mf4_analyzer/ui/drawers/batch/sheet.py, mf4_analyzer/ui/drawers/batch/frf_pair_editor.py]
checks: [git diff --check]
tests: [tests/ui/test_batch_review_regressions.py, tests/ui/test_batch_frf_pair_editor.py]
---

# Reparented Batch Controls Must Keep Run Locks and Guidance Ownership

Trigger: Moving controls across Qt parents or adding validation-driven guidance.

Past failure: Moving method tabs out of AnalysisPanel bypassed its run-time
disable state. Completion left the running hint stale. Generic locate targets
pointed at a valid directory or FRF group instead of the field needing repair.

Rule: Audit inherited enabled state after reparenting and lock/unlock the new
host symmetrically. Refresh guidance on completion without replacing result
status. Resolve live controls from structured validation fields; pair-group
validation owns both its message and repair target. Pending/source errors must
not be overwritten by empty-input hints.

Verification: Exercise mouse and keyboard during locking and after unlocking;
test completion without a subsequent configuration edit. Assert focus on the
actual invalid output, interval, axis and slice control, and each error type in
a second FRF group. Verify Windows native geometry separately from offscreen
screens that may clamp the dialog to 780 logical pixels.
