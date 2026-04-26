# T2 — Fix: Pre-flight uniformity gate for `do_fft_time` / `do_fft`

**Date:** 2026-04-26
**Subtask:** T2 (implementation; depends on T1 diagnosis at
`docs/superpowers/reports/2026-04-26-nonuniform-fft-T1-diagnosis.md`).
**User report:** "触发这个提示之后，手动输入频率也无法计算。"
(Sample file: `testdoc/TLC_TAS_RPS_2ms.mf4`, jitter ~2.36.)

## Root cause (recap from T1)

`FileData.rebuild_time_axis(fs)` is the SOLE writer of
`fd.time_array`. The Inspector's three `spin_fs` widgets
(`FFTContextual`, `FFTTimeContextual`, `OrderContextual`) have ZERO
`valueChanged` / `editingFinished` connections — they are decorative
display widgets. Manual Fs entry never propagated to
`fd.time_array`; the next click on FFT vs Time / FFT therefore re-ran
`do_fft_time` / `do_fft` against the unchanged raw non-uniform axis,
and `SpectrogramAnalyzer._validate_time_axis` re-raised
`ValueError('non-uniform time axis: relative_jitter=2.36 …')`. The
post-worker auto-rebuild handler at `_on_fft_time_failed` then
auto-opened the rebuild popover — but Bug #2 (popover offscreen, T3)
made it un-clickable, so the user could not break out of the loop.

## Fix shape (Option A from T1)

Pre-flight uniformity check at the **entry of `do_fft_time` / `do_fft`**
that routes non-uniform axes through `_show_rebuild_popover` BEFORE
dispatching the FFT worker. The popover Accept branch already does the
rebuild + cache-clear + Fs-broadcast side effects (main_window.py:441).
After Accept the time axis is `arange(n)/fs` — guaranteed uniform —
and `do_fft_time` / `do_fft` proceed normally with refreshed locals.

This collapses the prior **worker -> failed handler -> popover -> deferred
retry** round-trip into a single synchronous gate.

## H4 latent bug — handled by deletion

T1 flagged a latent contract bug at main_window.py:1933-1946: the
`_fft_time_retry_pending` flag was cleared in `_retry`'s `finally`
**before** `thread.start()`'s deferred worker could fail. The
documented "retry capped at 1" guarantee was therefore unbounded.

**T2 deletion:** the entire post-worker non-uniform branch in
`_on_fft_time_failed` is removed. The `_fft_time_retry_pending`
attribute (only ever read via `getattr(..., False)`, never initialized
in `__init__`) is dropped from the codebase. With pre-flight catching
non-uniform inputs synchronously, the retry path was dead code; deleting
it is the simplest way to also eliminate H4.

The simplified `_on_fft_time_failed` now surfaces every worker error
verbatim (`toast(msg, "error")` + status-bar message) — no special-case
branching.

## Files changed

- `mf4_analyzer/io/file_data.py`
  - **Added** `FileData.is_time_axis_uniform(tolerance=None) -> bool`.
    Mirrors `SpectrogramAnalyzer._validate_time_axis` rule by rule:
    short axis -> True; non-monotonic -> False;
    `max|dt - 1/fs| / (1/fs) > tolerance` -> False; else True.
    Default tolerance reads from
    `mf4_analyzer.signal.spectrogram.DEFAULT_TIME_JITTER_TOLERANCE` so
    the predicate cannot drift away from the worker's validator.
  - **Added** `FileData.suggested_fs_from_time_axis() -> float` —
    median(dt of strictly positive gaps) reciprocal, with current
    `self.fs` as fallback. Used by the pre-flight to seed the popover's
    spin_fs.
- `mf4_analyzer/signal/spectrogram.py`
  - **Added** module-level constant `DEFAULT_TIME_JITTER_TOLERANCE = 1e-3`.
  - Bound the existing `time_jitter_tolerance` kwarg default through
    that constant (literal value unchanged). Algorithm logic unchanged.
- `mf4_analyzer/ui/main_window.py`
  - **Added** `MainWindow._check_uniform_or_prompt(fd, mode) -> bool`.
    Duck-typed (the `hasattr` guards keep prior smoke-test fakes that
    return `object()` as `fd` working).
  - **Modified** `MainWindow.do_fft` — pre-flight at entry; refresh
    `t/sig/fs` from `_get_sig` after a popover Accept.
  - **Modified** `MainWindow.do_fft_time` — pre-flight at entry;
    refresh `(fid, ch, t, sig, fd)` from `_get_fft_time_signal` after
    Accept; dropped the now-unused `'force'` key from
    `_fft_time_pending`.
  - **Modified** `MainWindow._on_fft_time_failed` — removed the entire
    `'non-uniform time axis' in msg` branch (~58 lines including
    docstring). Handler now just `toast(msg, "error")` +
    `statusBar.showMessage`. The `_fft_time_retry_pending` flag is
    no longer referenced anywhere.
- `tests/test_nonuniform_fft_preflight.py` (NEW, 13 tests)
  - Predicate boundaries vs `_validate_time_axis`.
  - Suggested-Fs estimator behavior.
  - The shared module constant exists and the analyzer default tracks
    it.
- `tests/ui/test_main_window_smoke.py`
  - Rewrote three tests that previously asserted the deleted
    post-worker retry contract:
    - `test_fft_time_non_uniform_friendly_toast` — now asserts the
      pre-flight emits the toast and NO worker is dispatched.
    - `test_fft_time_non_uniform_accept_dispatches_worker_once`
      (renamed from `_auto_opens_rebuild_and_retries`) — asserts
      exactly one worker dispatch after a popover Accept (NOT two:
      there is no retry in the new model).
    - `test_fft_time_non_uniform_user_cancel_skips_worker` (renamed
      from `_does_not_retry`) — asserts pre-flight bails before any
      worker thread is created when the user rejects the popover.
  - Added `_NonUniformFakeFD` and `_stub_fft_time_signal_nonuniform`
    helper to wire a duck-typed fake `fd` whose
    `is_time_axis_uniform()` returns False (the existing
    `_stub_fft_time_signal` returns `object()`, which the new
    pre-flight skips by `hasattr`).

## symbols_touched

(per orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection)

- `mf4_analyzer/io/file_data.py`: `FileData.is_time_axis_uniform`
  (NEW), `FileData.suggested_fs_from_time_axis` (NEW).
- `mf4_analyzer/signal/spectrogram.py`: `DEFAULT_TIME_JITTER_TOLERANCE`
  (NEW module constant); `SpectrogramAnalyzer.compute` signature
  default re-bound through the constant (same value).
- `mf4_analyzer/ui/main_window.py`:
  `MainWindow._check_uniform_or_prompt` (NEW),
  `MainWindow.do_fft` (modified — pre-flight + refresh locals),
  `MainWindow.do_fft_time` (modified — pre-flight + refresh locals,
  drop `'force'` from `_fft_time_pending`),
  `MainWindow._on_fft_time_failed` (modified — non-uniform branch
  deleted),
  `_fft_time_retry_pending` (REMOVED — unused after deletion).
- `tests/test_nonuniform_fft_preflight.py` (NEW): three test classes
  `TestIsTimeAxisUniform`, `TestSuggestedFs`,
  `TestSpectrogramConstantExposure` (13 tests total).
- `tests/ui/test_main_window_smoke.py`: rewrote three non-uniform
  tests (see Files changed); added `_NonUniformFakeFD` and
  `_stub_fft_time_signal_nonuniform`.

## Tests run

- **Before:** 219 collected (full suite, `tests/`).
- **After:** 232 collected; 232 passed, 0 failed.
- New tests: 13 (in `tests/test_nonuniform_fft_preflight.py`).
- Smoke tests for non-uniform paths rewritten in place; no net change
  in test count from that file.

```
$ PYTHONPATH=. .venv/bin/pytest -q tests/
232 passed, 16 warnings in 7.78s
```

## Key decisions

### Why Option A, not Option B

Option B (wire `spin_fs.editingFinished` → `_apply_inspector_fs` slot)
would have required edits to the contextual `__init__`s in
`mf4_analyzer/ui/inspector_sections.py` — that crosses the
signal-processing-expert boundary into pyqt-ui's lane (the brief
explicitly forbids touching existing contextual methods and would
have required a flag-and-handoff). Option A keeps the entire fix in
the signal-processing layer (`file_data.py` + `main_window.py`
methods) and incidentally fixes H4 by eliminating the retry path.

### Why hoist `1e-3` to a module constant

T1 directed: "容差按现有 `_validate_time_axis` 标准 ... 复用 spectrogram.py
里的同款判定常量，**不要硬编码**". The value `1e-3` previously lived
ONLY as a kwarg default on `SpectrogramAnalyzer.compute`. Reading the
default at call time via `inspect.signature(...).parameters[...].default`
works but couples the predicate to the analyzer's signature shape.
Hoisting to a named module constant
(`spectrogram.DEFAULT_TIME_JITTER_TOLERANCE`) makes the cross-module
contract explicit and grep-able. The `compute` signature now binds the
same name as its default, so a future change to the constant
propagates to both predicate and validator atomically. The algorithm
itself is unchanged — this is a one-line metadata extraction, not a
core-logic edit.

### Why duck-typed `hasattr` guards in `_check_uniform_or_prompt`

The pre-existing `tests/ui/test_main_window_smoke.py` stubs
`_get_fft_time_signal` to return `object()` as `fd`. Calling
`is_time_axis_uniform()` on a bare `object()` would crash those tests.
Two options:

1. Hard-code `isinstance(fd, FileData)` — tightly couples the
   pre-flight to the production type; tests would need real
   `FileData` instances.
2. `hasattr(fd, 'is_time_axis_uniform')` — duck-typed, lets fakes
   pass through; the worker still gets the real (`SpectrogramAnalyzer`)
   validator as a backstop if a fake somehow encodes a non-uniform
   axis.

Chose (2). The new `_NonUniformFakeFD` class in the smoke tests
exercises the pre-flight path explicitly; the legacy `object()`
stubs are intact for the cache-hit / force / failure tests that do
not care about uniformity.

### Why retry deletion (not just lifecycle fix)

The brief offered: "如果 Option A 的 pre-flight 已让 retry 路径成为
dead code，可以删掉 retry 相关字段与方法". Confirmed dead code:

- The pre-flight catches every user-facing non-uniform case
  synchronously.
- The only way the worker can still raise `non-uniform time axis` is a
  TOCTOU race (axis mutated between pre-flight and worker `run()`),
  which the user cannot trigger with the current UI. In that
  pathological case the user sees the raw error string verbatim and
  can click 重建时间轴 manually — preferable to silently retry-looping
  with a broken lifecycle flag.

Deleted:
- `_on_fft_time_failed`'s `'non-uniform time axis' in msg` branch
  (~58 lines incl. its docstring paragraph).
- All references to `_fft_time_retry_pending` in code (the attribute
  was only ever read via `getattr(..., False)`, so no `__init__`
  cleanup needed).
- The `'force'` key in `_fft_time_pending` (only consumed by the
  deleted `_retry`).

## Lessons consulted

- `docs/lessons-learned/README.md` (read protocol).
- `docs/lessons-learned/LESSONS.md` (index).
- `docs/lessons-learned/signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md`
  — drove the consumer-side grep on `rebuild_time_axis` and
  `is_time_axis_uniform` (verified the only call site for the predicate
  is the new `_check_uniform_or_prompt` and that the worker still uses
  the same constant via `time_jitter_tolerance`).
- `docs/lessons-learned/pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md`
  — confirmed pre-flight does NOT need a "last-state" diff guard:
  `do_fft_time` is button-triggered, not handler-replayed via
  `QTimer.singleShot`; the same justification at main_window.py:1685
  applies to the new gate.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
  — drove the explicit `symbols_touched` enumeration above.
- `docs/lessons-learned/pyqt-ui/2026-04-25-defer-retry-from-worker-failed-slot.md`
  (cross-referenced via T1 H4): re-read; confirmed the deferred-retry
  pattern is gone from the FFT vs Time path. Other workers (order
  analyzer) are not in scope for this fix.

## Out of scope

- Bug #2 (popover offscreen geometry) — owned by T3, pyqt-ui-engineer.
- `OrderContextual.btn_rebuild` is wired into `_check_uniform_or_prompt`
  (the `mode='order'` branch), but `do_order_*` methods are NOT
  pre-flighted in T2 because order analysis runs through
  `OrderAnalyzer.compute_*` which has its own non-uniformity tolerance
  story (see spec §6 for the order pipeline). Adding a similar
  pre-flight to order paths is a follow-up task.
- Multi-file Fs sync gap (T1 H5) — defer.
- A genuine integration test that loads `testdoc/TLC_TAS_RPS_2ms.mf4`
  end-to-end — owned by T4 after T2 lands.
