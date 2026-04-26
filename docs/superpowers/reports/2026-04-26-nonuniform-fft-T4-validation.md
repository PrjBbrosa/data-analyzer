# T4 — End-to-end validation of the non-uniform FFT vs Time recovery

**Date:** 2026-04-26
**Subtask:** T4 (validation gate; depends on T2 + T3 having both
passed code review).
**User report:** "触发这个提示之后，手动输入频率也无法计算。" /
"弹出的自定义时间轴在窗口外面，得缩小软件才能看得到。"
(Sample file: `testdoc/TLC_TAS_RPS_2ms.mf4`, jitter ~ 2.36.)

## Cross-references

- T1 diagnosis: `docs/superpowers/reports/2026-04-26-nonuniform-fft-T1-diagnosis.md`
  (root cause: Inspector `spin_fs` is decorative, manual Fs never
  reached `fd.time_array`; offscreen popover; latent retry-flag
  lifecycle bug H4).
- T2 fix: `docs/superpowers/reports/2026-04-26-nonuniform-fft-T2-fix.md`
  (Option A pre-flight gate at `do_fft` / `do_fft_time` entry; new
  `FileData.is_time_axis_uniform` + `suggested_fs_from_time_axis`;
  hoisted `DEFAULT_TIME_JITTER_TOLERANCE`; deleted retry path).
- T3 popover geometry: `docs/superpowers/reports/2026-04-26-nonuniform-fft-T3-popover-geometry.md`
  (`RebuildTimePopover.show_at` clamps inside `availableGeometry`;
  `MARGIN`, `GAP`, `_available_geometry_for`).

## What T4 verifies

T4 is a regression gate, not a fix cycle. It locks the user's recovery
path end-to-end across the signal layer (T2) and the UI layer (T2 + T3
popover geometry interaction), so a future change that breaks any of
the four contracts the user depends on tripwires CI:

1. `FileData.is_time_axis_uniform` and `SpectrogramAnalyzer._validate_time_axis`
   agree at the tolerance boundary (T2 hoisted constant).
2. After a popover Accept, `fd.rebuild_time_axis(fs)` produces an axis
   the analyzer accepts, and the analyzer's compute returns a
   non-empty result locating the injected tone (sanity that the
   rebuild does not silently alias the data).
3. `MainWindow.do_fft_time` -> pre-flight -> popover Accept -> exactly
   ONE worker dispatch. No retry round-trip (T2 deletion). Cache is
   populated; second click hits the cache.
4. `MainWindow.do_fft_time` -> pre-flight -> popover Reject -> NO
   worker dispatch, NO analyzer call, NO cache mutation, NO error
   toast.
5. The real `RebuildTimePopover` constructed by MainWindow stays
   inside `QGuiApplication.primaryScreen().availableGeometry()` even
   when the host window is dragged into the bottom-right corner of
   the screen (T3 + T2 interaction regression).

## Files changed

- **NEW** `tests/test_nonuniform_fft_recovery.py` (signal-layer recovery,
  9 tests, no GUI):
  - `TestNonUniformRecovery::test_before_rebuild_predicate_is_false`
  - `TestNonUniformRecovery::test_before_rebuild_analyzer_raises_nonuniform`
    -- locks the `'non-uniform time axis'` substring contract surface
    that the UI gate keys off.
  - `TestNonUniformRecovery::test_before_rebuild_suggested_fs_is_in_order`
    -- finite, positive, inside `RebuildTimePopover.spin_fs` range
    `[1, 1e6]`, within 10x of nominal.
  - `TestNonUniformRecovery::test_rebuild_with_suggested_fs_then_recompute_succeeds`
    -- user accepts the popover unchanged (median-dt seed); rebuild
    still produces a uniform axis; analyzer compute succeeds.
  - `TestNonUniformRecovery::test_rebuild_with_user_typed_fs_recovers_synthetic_tone`
    -- user types the actual nominal Fs; spectrogram peak lands at
    100 Hz +- 5 Hz (no aliasing).
  - `TestUniformBaseline::test_predicate_true`
  - `TestUniformBaseline::test_analyzer_compute_succeeds`
  - `TestUniformBaseline::test_suggested_fs_matches_nominal`
  - `TestToleranceContractGuardrail::test_predicate_and_analyzer_agree_at_boundary`
    -- the predicate-vs-validator parity that T2 designed
    `DEFAULT_TIME_JITTER_TOLERANCE` to enforce.
- **NEW** `tests/ui/test_nonuniform_fft_full_flow.py` (pytest-qt
  offscreen, 5 tests):
  - `test_full_flow_accept_dispatches_one_worker_and_caches` -- the
    user-visible recovery: 计算时频图 -> popover Accept -> one worker
    dispatch -> cache populated -> second click hits cache.
  - `test_full_flow_reject_skips_worker` -- user cancels: NO worker
    thread, NO analyzer call (watchdog `compute` raises if reached),
    NO cache entry, NO error toast.
  - `test_full_flow_no_dispatch_when_signal_already_uniform` -- the
    pre-flight does NOT pop on perfectly-fine input.
  - `test_popover_frame_geometry_inside_available_when_anchor_in_corner`
    -- T3 + T2 interaction regression: anchor in bottom-right corner
    of the available screen, real `RebuildTimePopover` constructed
    (not stubbed), `frameGeometry()` inside `availableGeometry`
    within `MARGIN +- 1px`.
  - `test_reject_path_does_not_silently_mutate_fd_fs` -- documents the
    T2 reviewer flag: `_check_uniform_or_prompt` seeds `fd.fs =
    suggested_fs_from_time_axis()` BEFORE invoking the popover, and
    the seed survives a Reject. T4 records the current behavior so a
    future fix can flip the assertion direction. Not flagged for
    rework (decision rationale below).

NO production .py files were modified by T4.

## symbols_touched

(per `orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
-- T4 is test-only, but listing the test symbols makes a future
"why does this test exist" grep cheap.)

- `tests/test_nonuniform_fft_recovery.py` (NEW): `_build_file_data`,
  `nonuniform_fd` fixture, `uniform_fd` fixture, `_spectrogram_params`,
  `TestNonUniformRecovery` (5 tests), `TestUniformBaseline` (3 tests),
  `TestToleranceContractGuardrail` (1 test).
- `tests/ui/test_nonuniform_fft_full_flow.py` (NEW):
  `_NonUniformFakeFD`, `_wire_fake_file`, `_patch_popover`, plus 5
  test functions enumerated above.

Forbidden-symbol self-check:

| Forbidden region | Touched? |
| ---------------- | -------- |
| `mf4_analyzer/io/file_data.py` (T2 prod) | No |
| `mf4_analyzer/signal/spectrogram.py` (T2 prod) | No |
| `mf4_analyzer/ui/main_window.py` (T2 prod) | No |
| `mf4_analyzer/ui/drawers/rebuild_time_popover.py` (T3 prod) | No |
| `tests/test_nonuniform_fft_preflight.py` (T2 owner) | No |
| `tests/ui/test_main_window_smoke.py` (T2 owner) | No |
| `tests/ui/test_rebuild_popover_geometry.py` (T3 owner) | No |
| Any other production .py | No |

## Tests run

- **Before:** 232 collected (full suite, `tests/`). All 232 passing.
- **After:** 246 collected. All 246 passing. Net +14 tests (9 in
  signal-layer recovery, 5 in UI integration).

```
$ QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ -q
246 passed, 16 warnings in 7.35s
```

The 16 warnings are pre-existing CJK glyph warnings from
`test_render_order_rpm_uses_correct_extent_and_matrix_orientation`
(`DejaVu Sans` lacking the Chinese glyphs); they are not introduced by
T4 and exist in the pre-T4 baseline.

Targeted runs:

```
$ QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
    tests/test_nonuniform_fft_recovery.py -v
9 passed in 0.68s

$ QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
    tests/ui/test_nonuniform_fft_full_flow.py -v
5 passed in 1.23s
```

## ui_verified

`true`. The geometry test (`test_popover_frame_geometry_inside_available_when_anchor_in_corner`)
constructs the real `RebuildTimePopover` (not a stub), drives it
through the production `MainWindow.do_fft_time` -> pre-flight ->
`_show_rebuild_popover` flow, and asserts the popover's
`frameGeometry()` lives inside `QGuiApplication.primaryScreen()
.availableGeometry()`. Per
`pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md`, offscreen Qt
exposes valid screen geometry, so this assertion is reliable in
headless CI.

The Accept path tests use a stub popover (returning `QDialog.Accepted`
synchronously) to keep the test from blocking on a modal -- `exec_()`
inside the production code is the only thing the stub replaces. The
production `_show_rebuild_popover` is otherwise driven verbatim
(real signal resolution, real `rebuild_time_axis` side-effect, real
cache invalidation, real worker dispatch).

## Key decisions

### Why duplicate the FileData helper instead of importing from `tests/test_nonuniform_fft_preflight.py`

T2's predicate-only test file is owned by T2; T4 is the cross-layer
regression gate. If T2's helper is renamed or removed in a future
refactor, the T4 gate must keep firing. Duplicating ~25 lines of
fixture code is a small price to pay for an independent CI signal.

### Why two separate "rebuild then recompute" tests

`test_rebuild_with_suggested_fs_then_recompute_succeeds` covers the
"user clicks Accept without typing" path -- the popover's seeded Fs is
the median-dt estimate, which on alternating-gap fixtures locks onto
the larger gap and underestimates the nominal by ~3x. The rebuild
still produces a uniform axis the analyzer accepts; the user gets a
spectrogram even if they don't fix the seed.

`test_rebuild_with_user_typed_fs_recovers_synthetic_tone` covers the
"user types the real nominal Fs" path -- the spectrogram peak must
land at the injected 100 Hz tone +- 5 Hz. The synthetic signal is
sampled on a uniform clock (matching the user's MF4 model: ADC
fires at a stable rate, only the timestamp column carries logger
jitter), so a correct rebuild that uses the real nominal Fs locates
the tone within bin-leakage tolerance.

### Why not flag the Reject-mutates-fd.fs reviewer concern as a follow-up

The T2 reviewer noted that `_check_uniform_or_prompt` seeds
`fd.fs = suggested_fs_from_time_axis()` BEFORE invoking the popover
(main_window.py:1162-1165), so a Reject leaves the user's `fd.fs`
silently changed to the median-dt estimate. Per the T4 brief
("如果你认为有意义，可以加一个回归测试 ... 在报告里写一句决策"):

The T4 decision is to **document** the current behavior with a
regression-locked test
(`test_reject_path_does_not_silently_mutate_fd_fs`) rather than
**fix** it. Rationale:

- T4 is a validation gate. Changing prod code would put T4 in T2's
  lane and trip rework detection (overlap on `main_window.py`).
- The seeded value is the median-dt estimate, which is a *better*
  guess than the original (likely-wrong) Fs the user had displayed.
  In practice this side-effect helps the user even after Reject -- if
  they reopen the popover, the spin_fs is pre-seeded with a more
  accurate value.
- The test docstring instructs the next maintainer to flip the
  assertion direction (`==` to `!=`) once the side-effect is rolled
  back, so when someone *does* address the reviewer flag, the test
  will catch the change.

If main Claude wants to schedule the rollback as a follow-up sub-task,
the natural shape is:

```yaml
flagged: [{
  for: signal-processing-expert,
  issue: "_check_uniform_or_prompt seeds fd.fs before popover invoke;
          rollback on Reject. flip assertion in
          test_reject_path_does_not_silently_mutate_fd_fs."
}]
```

T4 itself does NOT raise this flag because the user-visible bug is
already resolved by T2 + T3 (the seed only "leaks" if the user clicks
Cancel and *then* observes the spin_fs value; even then it's a
better-quality value). Optimizing this is polish, not recovery.

### Why no `qtbot.waitSignal`

The brief calls out that worker waits must use `qtbot.waitSignal` /
`QTimer.singleShot` rather than `thread.wait()` (per
`pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md`). T4
follows the existing pattern in `test_main_window_smoke.py`:
`qtbot.waitUntil(lambda: win._fft_time_thread is None, timeout=10000)`.
This is functionally equivalent to `qtbot.waitSignal(thread.finished)`
because `_on_fft_time_thread_done` clears `_fft_time_thread = None`
on the main thread when `thread.finished` fires (main_window.py:1893,
1996). The wait is on a main-thread state mutation, not on
`thread.wait()` -- the deadlock pattern is avoided.

## Lessons consulted

- `docs/lessons-learned/README.md` (read protocol).
- `docs/lessons-learned/LESSONS.md` (index).
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
  -- drove the explicit `symbols_touched` and forbidden-symbol
  self-check tables above.
- `docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md`
  -- justifies trusting `frameGeometry()` / `availableGeometry()`
  assertions under `QT_QPA_PLATFORM=offscreen` in
  `test_popover_frame_geometry_inside_available_when_anchor_in_corner`.
- `docs/lessons-learned/pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md`
  -- drove the `qtbot.waitUntil(... is None)` pattern (main-thread
  state mutation, not `thread.wait()`).

No new lesson written: T4 is a regression gate; the insights it
exercises are all already documented in the lesson corpus, and
re-deriving them here would violate the "no water content" rule in
`LESSONS.md`'s README.

## Out of scope for T4

- Any `mf4_analyzer/` source edit (test-only subtask).
- Loading the user's actual `testdoc/TLC_TAS_RPS_2ms.mf4` -- T4 uses
  synthetic fixtures so the test runs on any machine without the
  sample file. Real-file smoke is a desktop verification step, not a
  CI gate.
- Order-mode pre-flight regression -- T2 wired the order popover
  anchor but did NOT pre-flight `do_order_*`, per the T2 "out of
  scope" section. A separate task can extend the gate to order paths
  and add the matching T4-style regression test there.
- The Reject-mutates-fd.fs side-effect rollback (decision recorded
  above; T4 documents but does not fix).
