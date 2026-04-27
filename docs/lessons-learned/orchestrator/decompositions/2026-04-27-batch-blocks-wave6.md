# Wave 6 — Task list + runner thread + cancel button

**Date:** 2026-04-27
**Plan:** docs/superpowers/plans/2026-04-27-batch-blocks-redesign.md §Wave 6 (lines 1805-2104)
**Spec:** docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md §3.5, §4.5, §6.2

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| w6-task-list-runner-and-sheet-wiring | pyqt-ui-engineer | (none) | All five files (`task_list.py`, `runner_thread.py`, `sheet.py` edit, two test files) form one tightly coupled unit: `sheet.py` imports both new modules, the cancel-button test exercises the full sheet+thread wiring, and `runner_thread.py` is a pure QThread wrapper that only `sheet.py` consumes. Splitting across specialists would either parallelise same-file edits (sheet.py is the integration point) or serialize redundantly. Single PyQt5 brief avoids the rework risk documented in `orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`. |

Decomposition is intentionally a single subtask. Wave 5 / Wave 4 used the same shape and avoided commit-collision races.

## Lessons consulted

- docs/lessons-learned/README.md
- docs/lessons-learned/LESSONS.md
- docs/lessons-learned/.state.yml
- docs/lessons-learned/pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md — `Qt.DirectConnection` for `worker.finished -> thread.quit` in standalone tests; production AutoConnection is fine.
- docs/lessons-learned/pyqt-ui/2026-04-25-defer-retry-from-worker-failed-slot.md — `thread.finished` slot ordering: cleanup slot is queued; re-entry guards stay True until it drains. Relevant for reasoning about the unlock sequence.
- docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md — Don't parallelise tasks that share `sheet.py`. (Already satisfied — single specialist.)
- docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md — Specialist must enumerate `symbols_touched` and stay inside the W6 surface in `sheet.py`.

## Boundary discipline (forbidden in this subtask)

The specialist MUST NOT touch any of the following — main Claude will run a forbidden-symbol grep against the diff before review:

- `mf4_analyzer/batch.py` — owned by W2. Do not edit `BatchRunner`, `AnalysisPreset`, `BatchProgressEvent`, `BatchOutput`, `BatchRunResult`. Read-only consumer.
- `mf4_analyzer/batch_preset_io.py` — owned by W2.
- All files closed before W3.
- `mf4_analyzer/ui/main_window.py` — owned by W7. Do not wire any toolbar button or open the sheet from main_window in this wave.
- `tests/ui/test_inspector.py` (long/short field test) — explicitly out of scope.
- In `sheet.py`: only edit (a) detail-row insertion of `TaskListWidget`, (b) footer button swap region, (c) `closeEvent` confirmation, (d) new methods `_build_dry_run_preview`, `_on_run_clicked`, `_on_cancel_clicked`, `_on_runner_progress`, `_on_runner_finished_with_result`, `_on_thread_finished`, `lock_editing`, `unlock_editing`, plus `_running` state init in `__init__`. Do NOT refactor any pre-W6 method body.

## Hard invariants (specialist must obey verbatim)

1. **Unlock binds to `QThread.finished`, not `finished_with_result`.** The `finished_with_result` handler stores result on `self._last_result`; the `QThread.finished` handler does `unlock_editing()` + toast based on `self._last_result`. This way an exception in `runner.run` that the try/except catches still leaves the dialog unlockable — `finished_with_result` is emitted with the blocked result AND `QThread.finished` fires when `run` returns normally.

2. **`_running=True` and Run-button disable happen synchronously BEFORE `thread.start()`** to prevent double-click reentrance.

3. **Dry-run preview reads UI-cached state ONLY.** `_build_dry_run_preview` MUST NOT call `BatchRunner._expand_tasks` (that path triggers `_resolve_files` → `loader(path)` on the UI thread → potential deadlock/freeze). Implementation:
   - For each `fid in InputPanel.file_ids()`: read `fd = self._files[fid]`; iterate target_signals; append a row regardless of whether the signal is in `fd.data.columns` (runner emits ✗ at run time if missing).
   - For each `path in InputPanel.file_paths()`: read the cached probed signal set from `FileListWidget` (W5); append rows.

4. **closeEvent confirmation:** if `_running`, show a `QMessageBox.question`; on Yes → `request_cancel()` and IGNORE the event until `QThread.finished` clears `_running`; on No → IGNORE the event.

5. **Plan §Step 6.5 has a broken import.** The verbatim test reads:
   ```python
   sheet.apply_outputs(__import__("mf4_analyzer").batch.BatchOutput(...))
   ```
   Specialist MUST replace it with:
   ```python
   from mf4_analyzer.batch import BatchOutput
   ...
   sheet.apply_outputs(BatchOutput(export_data=True, export_image=False, data_format="csv"))
   ```

6. **Plan §Step 8 git commit is deferred.** Specialist MUST NOT run `git add` or `git commit`. Main Claude runs the commit after Phase 3 aggregation.

7. **Plan §Step 7 (manual end-to-end smoke)** is main Claude's responsibility, not the specialist's.

## Test command (Windows project venv)

```
.venv\Scripts\python.exe -m pytest tests/ui/test_batch_task_list.py tests/ui/test_batch_runner_thread.py -v --basetemp=.pytest-tmp -p no:cacheprovider
```

Plus a regression sweep:

```
.venv\Scripts\python.exe -m pytest tests/ui -v --basetemp=.pytest-tmp -p no:cacheprovider
```
