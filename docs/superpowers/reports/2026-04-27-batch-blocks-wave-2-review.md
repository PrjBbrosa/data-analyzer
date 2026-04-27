# Wave-2 Review — Batch Blocks Redesign

**Date:** 2026-04-27
**Commit reviewed:** 7e33421
**Reviewer:** codex
**Verdict:** approved

## Summary
The Wave 2 backend diff is limited to `mf4_analyzer/batch.py` and `tests/test_batch_runner.py`, and the implementation conforms to the Wave 2 runner/event/cancel/loader plan. The two documented deviations are sound: the free-config legacy fallback preserves pre-W8 callers, and `SUPPORTED_METHODS` correctly excludes removed `order_rpm` because `_run_one` no longer has an `order_rpm` handler.

## Spec/plan conformance
- PASS: In-scope files only. `git show 7e33421 --name-only --format=''` reports only `mf4_analyzer/batch.py` and `tests/test_batch_runner.py`.
- PASS: Wave 2 Step 1 test source is present in `tests/test_batch_runner.py:147-430`; the added `test_supported_methods_excludes_removed_order_rpm` regression at `tests/test_batch_runner.py:433-440` pins documented deviation 2.
- PASS: Wave 2 Step 3 is implemented: `Callable` / `Literal` and `threading` are imported at `mf4_analyzer/batch.py:15-17`, `BatchProgressEvent` is defined at `mf4_analyzer/batch.py:121-133`, and `BatchRunResult.status` remains a free string at `mf4_analyzer/batch.py:114-118`, so `cancelled` is supported without a dataclass shape change.
- PASS: Wave 2 Step 4 is implemented: `_default_loader` calls the live `DataLoader.load_mf4` API and wraps `FileData` at `mf4_analyzer/batch.py:146-153`; `BatchRunner.__init__(files, loader=None)` sets `self._loader` and per-instance `self._disk_cache` at `mf4_analyzer/batch.py:159-162`.
- PASS: Deviation 2 is correct. `SUPPORTED_METHODS` is `{'fft', 'order_time', 'order_track'}` at `mf4_analyzer/batch.py:157`, matching the only live `_run_one` handlers at `mf4_analyzer/batch.py:400-414`; the regression test at `tests/test_batch_runner.py:433-440` asserts `order_rpm` stays removed.
- PASS: Wave 2 Step 5 is implemented: `current_single` resolution is at `mf4_analyzer/batch.py:284-291`, explicit `file_ids` and `file_paths` handling is at `mf4_analyzer/batch.py:302-319`, and `_LoadFailure` is defined at `mf4_analyzer/batch.py:136-143`.
- PASS: Deviation 1 is correct. The legacy fallback at `mf4_analyzer/batch.py:298-301` yields all registered `self.files` only when `preset.source == 'free_config'` and both runtime selections are empty; explicit `file_ids` / `file_paths` still take the new path at `mf4_analyzer/batch.py:302-319`. This bridges current callers until W8 removes the legacy `signal_pattern` UI route.
- PASS: Wave 2 Step 6 is implemented: `_expand_tasks` gates unsupported methods at `mf4_analyzer/batch.py:321-323`, short-circuits all-missing `target_signals` at `mf4_analyzer/batch.py:333-350`, treats `_LoadFailure` as present at `mf4_analyzer/batch.py:340-342`, and then yields the full file-by-signal product at `mf4_analyzer/batch.py:353-355`.
- PASS: Wave 2 Step 7 is implemented: the canonical `run(..., progress_callback=None, *, on_event=None, cancel_token=None)` signature is at `mf4_analyzer/batch.py:164-168`; output-dir failure handling is at `mf4_analyzer/batch.py:171-180`; cancellation is handled at task boundaries at `mf4_analyzer/batch.py:199-213`; task events and legacy progress ordering are at `mf4_analyzer/batch.py:221-260`; final status and `run_finished` are at `mf4_analyzer/batch.py:262-275`.
- PASS: The squad lesson added in 219f223 accurately describes the `SUPPORTED_METHODS` situation. The lesson says the plan had stale `order_rpm` at `docs/lessons-learned/signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md:12-19`, and current code confirms no live `order_rpm` handler exists at `mf4_analyzer/batch.py:400-414`.

## Boundary check
- `BatchPresetIO`: absent from the `7e33421` diff.
- `BatchBlocksDialog`: absent from the `7e33421` diff.
- `BatchBlocksController`: absent from the `7e33421` diff.
- `mf4_analyzer/ui/`: absent from the `7e33421` diff.
- `mf4_analyzer/batch_preset_io.py`: absent from the `7e33421` diff.

## Invariant audit
- 7a PASS: `progress_callback` is invoked only after `task_done` at `mf4_analyzer/batch.py:235-246`; the `task_failed` branch at `mf4_analyzer/batch.py:247-260` and `task_cancelled` branch at `mf4_analyzer/batch.py:199-213` do not call it.
- 7b PASS: `task_done` is emitted before `progress_callback` in the same success branch at `mf4_analyzer/batch.py:235-246`, matching the dual-callback ordering in spec section 4.4.
- 7c PASS: normal, partial, blocked-all-failed, and cancelled runs emit `run_finished` after the loop at `mf4_analyzer/batch.py:271-275`; output-dir failure and zero-task blocked paths emit only `run_finished` before returning at `mf4_analyzer/batch.py:171-190`.
- 7d PASS: once `cancel_token.is_set()` is observed, the loop emits `task_cancelled` for every remaining task index from the current task through `total` at `mf4_analyzer/batch.py:199-213`.
- 7e PASS: output-dir create failure is handled before `tasks = list(self._expand_tasks(preset))` at `mf4_analyzer/batch.py:171-182`, so the only event on that path is `run_finished(final_status='blocked')` at `mf4_analyzer/batch.py:175-179`.
- 7f PASS: loader failure is converted to `_LoadFailure` at `mf4_analyzer/batch.py:310-317`, counted as present during target-signal phase 1 at `mf4_analyzer/batch.py:340-342`, yielded through phase 2 at `mf4_analyzer/batch.py:353-355`, and emitted as `task_failed` by `run` at `mf4_analyzer/batch.py:228-260`. The legacy pattern fallback skips `_LoadFailure` at `mf4_analyzer/batch.py:359-361`; without `target_signals`, that route has no signal task list to mark failed.
- 7g PASS: two-phase `_expand_tasks` behavior is explicit at `mf4_analyzer/batch.py:333-355`: phase 1 returns zero tasks when no file/signal pair exists, `_LoadFailure` counts as present, and phase 2 yields the full cartesian product.
- 7h PASS: status precedence is implemented as cancelled first, then all-failed blocked, then partial, then done at `mf4_analyzer/batch.py:262-269`.
- 7i PASS: cancellation is checked only at the task boundary before `task_started` at `mf4_analyzer/batch.py:199-213`; an in-flight task completes `_run_one` and its data/image writes at `mf4_analyzer/batch.py:232-246` and `mf4_analyzer/batch.py:418-421` before later tasks are cancelled.
- 8a PASS: `cancel_token` is typed as `threading.Event | None` with default `None` at `mf4_analyzer/batch.py:168`, and the code calls `cancel_token.is_set()` at `mf4_analyzer/batch.py:199`.
- 8b PASS: `_disk_cache` is per-instance in `BatchRunner.__init__` at `mf4_analyzer/batch.py:159-162`, not class-level.
- 8c PASS: `Callable` and `Literal` are imported once at module top at `mf4_analyzer/batch.py:15`; no redundant method-local typing imports were introduced.
- 8d PASS: `BatchProgressEvent.kind` is required at `mf4_analyzer/batch.py:123-126`, and all other fields default to `None` at `mf4_analyzer/batch.py:127-133`.

## Tests run
```text
============================= test session starts =============================
platform win32 -- Python 3.13.1, pytest-9.0.2, pluggy-1.6.0 -- D:\Python\python.exe
PySide6 6.10.2 -- Qt runtime 6.10.2 -- Qt compiled 6.10.2
rootdir: D:\Pycharm_file\MF4-data-analyzer\data-analyzer
plugins: anyio-4.12.1, qt-4.5.0
collected 25 items

tests/test_batch_runner.py::test_current_single_fft_preset_exports_data PASSED [  4%]
tests/test_batch_runner.py::test_current_single_fft_preset_exports_image PASSED [  8%]
tests/test_batch_runner.py::test_current_single_fft_preset_handles_auto_nfft PASSED [ 12%]
tests/test_batch_runner.py::test_matrix_to_long_dataframe_vectorize_shape PASSED [ 16%]
tests/test_batch_runner.py::test_analysis_preset_replace_after_frozen_removed PASSED [ 20%]
tests/test_batch_runner.py::test_free_config_order_track_preset_selects_matching_signals PASSED [ 24%]
tests/test_batch_runner.py::test_batch_order_time_csv_shape PASSED       [ 28%]
tests/test_batch_runner.py::test_event_kinds_emitted_in_order PASSED     [ 32%]
tests/test_batch_runner.py::test_cancel_token_stops_after_current_task PASSED [ 36%]
tests/test_batch_runner.py::test_loader_injection_for_disk_paths PASSED  [ 40%]
tests/test_batch_runner.py::test_loader_failure_marks_files_tasks_failed PASSED [ 44%]
tests/test_batch_runner.py::test_target_signals_all_missing_returns_blocked PASSED [ 48%]
tests/test_batch_runner.py::test_target_signals_partial_missing_yields_failed_rows PASSED [ 52%]
tests/test_batch_runner.py::test_legacy_progress_callback_still_works PASSED [ 56%]
tests/test_batch_runner.py::test_progress_callback_count_excludes_failed_tasks PASSED [ 60%]
tests/test_batch_runner.py::test_all_disk_files_failed_yields_per_task_failures PASSED [ 64%]
tests/test_batch_runner.py::test_target_signals_multi_signal_expansion PASSED [ 68%]
tests/test_batch_runner.py::test_cancel_no_half_written_files PASSED     [ 72%]
tests/test_batch_runner.py::test_dual_callback_ordering PASSED           [ 76%]
tests/test_batch_runner.py::test_output_dir_create_failure_returns_blocked PASSED [ 80%]
tests/test_batch_runner.py::test_supported_methods_excludes_removed_order_rpm PASSED [ 84%]
tests/test_batch_preset_dataclass.py::test_free_config_accepts_target_signals PASSED [ 88%]
tests/test_batch_preset_dataclass.py::test_free_config_rejects_runtime_only_fields PASSED [ 92%]
tests/test_batch_preset_dataclass.py::test_from_current_single_rejects_free_config_fields PASSED [ 96%]
tests/test_batch_preset_dataclass.py::test_runtime_selection_via_replace PASSED [100%]

============================= 25 passed in 5.89s ==============================
```

Command used: `py -3 -m pytest tests/test_batch_runner.py tests/test_batch_preset_dataclass.py -v --basetemp=.pytest-tmp -p no:cacheprovider`

Counts: 7 legacy runner + 13 new W2 + 1 regression-pin + 4 W1 dataclass = 25 passed.

## Re-run note
Original codex sandbox could not create pytest tmp dirs (Windows %TEMP% lock). Re-run from main shell with --basetemp=.pytest-tmp -p no:cacheprovider produced 25/25 green. Same env workaround as W1 review.

## Findings
1. note: `mf4_analyzer/batch.py:314-315` caches `_LoadFailure` sentinels, while the Step 5 source block yielded uncached failures. This is compatible with the per-instance cache at `mf4_analyzer/batch.py:162` and the sentinel handling at `mf4_analyzer/batch.py:340-355` / `mf4_analyzer/batch.py:228-260`, but it is an implementation detail beyond the two documented source deviations.

## Verdict reasoning
The reviewed implementation satisfies the Wave 2 backend contract: event payloads and ordering are in place, cancellation happens at task boundaries with `run_finished` last, output-dir failures short-circuit before task events, disk loader failures surface as per-task failures on the target-signal path, and status precedence matches the spec. The boundary grep is clean, both documented deviations are justified by current code evidence, and the re-run pytest suite is green under the documented W1 workaround.

Wave 3 may proceed.
