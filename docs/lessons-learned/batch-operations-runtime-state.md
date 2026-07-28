---
id: batch-operations-runtime-state
status: active
owners: [codex]
keywords: [batch, qthread, resume, retry, manifest, runtime-state]
paths: [mf4_analyzer/ui/drawers/batch/sheet.py, mf4_analyzer/ui/drawers/batch/runner_thread.py]
checks: [git diff --check]
tests: [tests/ui/test_batch_runner_thread.py, tests/ui/test_batch_smoke.py]
---

# Batch Operations Keep Runtime State Out Of Presets

Trigger: Changing BatchSheet run lifecycle, manifest resume, retry-failed, worker arguments, or consecutive-run result handling.

Past failure: Resume and retry choices shared UI state without a complete reset contract. Selecting retry after resume could leave manifest auto-resume enabled, and a new worker lifecycle could retain the previous run result before its own terminal signal arrived.

Rule: Treat selected manifest paths and the last worker result as runtime-only state. Resume and retry paths are mutually exclusive; selecting retry resets resume policy, every run clears `_last_result` before starting, and editing unlock remains driven only by `QThread.finished`. Portable presets may store the resume policy but never a selected manifest path or prior result.

Verification: Run `tests/ui/test_batch_runner_thread.py` and the Phase 3 runtime-state cases in `tests/ui/test_batch_smoke.py`; exercise resume then retry, a second-run crash, and cancellation, then confirm no manifest path enters exported preset JSON and controls always unlock through `QThread.finished`.
