# Decomposition — Non-uniform FFT block + RebuildTimePopover offscreen

**Date:** 2026-04-26
**User request (verbatim, in CN):**

> 这有两个问题。
> 1. 触发这个提示之后，手动输入频率也无法计算。
> 2. 弹出的自定义时间轴在窗口外面，得缩小软件才能看得到。
> /Users/donghang/Downloads/data analyzer/testdoc/TLC_TAS_RPS_2ms.mf4 我用的文件是这个，随便选一个通道都不行。fft vstime 都做不出。

**Failing artefact:** `testdoc/TLC_TAS_RPS_2ms.mf4` (jitter≈2.36 in the toast).
**Triggering toast:** "时间轴非均匀（jitter≈2.36），无法直接做时频分析。已为你打开『重建时间轴』，请确认 Fs 后重试。"

**Routing override note:** the user's verbatim message did NOT contain
any of the squad keywords (`agent`/`squad`/`refactor`/`重构`/`分工`/`团队`/
`多专家`/`multi-agent`). However, the user has a project-level memory
entry stating that the squad runbook should be used; main Claude is
respecting that and routed through plan mode anyway. Recorded here so
the missed-trigger note in the next reflection can reference this run
without re-investigation.

## Code site map (read by orchestrator before planning)

- `mf4_analyzer/ui/main_window.py:409` — `_show_rebuild_popover` opens
  `RebuildTimePopover`, calls its `show_at(anchor)`, then on Accept
  invokes `fd.rebuild_time_axis(new_fs)`, clears the per-fid FFT-vs-Time
  cache, pushes new `fs` to all three contextuals, and replots.
- `mf4_analyzer/ui/main_window.py:1054` — `_get_sig` returns
  `(fd.time_array, fd.data[ch].values, fd.fs)` directly, with no
  monotonicity check or auto-rebuild fallback.
- `mf4_analyzer/ui/main_window.py:1133` — `do_fft` uses `_get_sig`'s `t`
  only as a range mask; `fs` for FFT comes from
  `self.inspector.fft_ctx.fs()`. So the inspector's manual Fs *does*
  reach the FFT compute, but the path makes no call to fix
  `fd.time_array`. Whether the user's "fft 做不出" is from a downstream
  exception or from a guard added by T11 (non-uniform UX) needs the
  signal-processing specialist to confirm.
- `mf4_analyzer/ui/main_window.py:1712` — `do_fft_time` enforces a
  uniform time axis via `SpectrogramAnalyzer.compute`, which raises
  `non-uniform time axis` for jitter > tolerance. The error path at
  `_on_fft_time_failed` (line 1861) auto-opens the rebuild popover and,
  on Accept, retries `do_fft_time` once.
- `mf4_analyzer/ui/drawers/rebuild_time_popover.py:46` — `show_at()`
  does `self.move(anchor.mapToGlobal(rect.bottomLeft()))` and `show()`
  without ANY clamping against the screen's available geometry or the
  parent main-window's frame geometry. This is the popover-offscreen
  bug.
- `mf4_analyzer/io/file_data.py:37` — `rebuild_time_axis(fs)` resets
  `time_array = arange(n)/fs`. There is no other write site for
  `time_array` after construction. The inspector's `spin_fs` therefore
  cannot mutate `fd.time_array`; only the popover (or a new explicit
  hook) can.

## Hypothesis matrix for Bug #1 ("manual Fs still cannot compute")

| H | Hypothesis | Why plausible | Disproof signal |
|---|---|---|---|
| H1 | Inspector `spin_fs` only updates `fft_ctx.fs()`, never calls `fd.rebuild_time_axis`; so `do_fft_time` re-checks `t = fd.time_array` (still non-uniform) and re-fails. | Code-path read above — only the popover's Accept calls `rebuild_time_axis`. | Repro: type Fs in inspector, click 计算, expect identical `非均匀` toast. |
| H2 | `do_fft_time`'s cache key includes `time_range=(t[0], t[-1])` from the still-non-uniform `t`; even after a popover Accept, a stale cached result keyed on the OLD time_range could shadow the rebuild — but T7 added `_fft_time_cache_clear_for_fid` precisely for this. Verify the per-fid clear actually fires for the active `target_fid`. | The cache invalidation hook exists, but `silent-boundary-leak` lesson reminds us "exists" ≠ "consumed at the right moment". | Repro: set breakpoint on `_fft_time_cache_clear_for_fid`; verify it's hit between popover Accept and the retry. |
| H3 | `do_fft` (the regular FFT, not vs-Time) raises in the range-mask branch (`m = (t >= lo) & (t <= hi)`) when `t` is duplicated/non-monotonic, producing an empty `sig` and the "请选择有效信号" toast. | `_get_sig` returns the raw non-uniform `t`. The user reports "fft 也做不出" but the screenshot is on the FFT vs Time tab — the regular `do_fft` may have a separate failure mode. | Repro: switch to FFT (not vs-Time), click 计算 with the same file. |
| H4 | `_fft_time_retry_pending` flag never clears (e.g. if user cancels the popover, the `finally` should clear it; if they Accept, `_retry()` runs — but if the retry compute itself fails again, the flag is cleared inside `_retry`'s `finally`, not in the failed handler — so a 2nd manual click later may take the `'non-uniform time axis' in msg AND not _fft_time_retry_pending` branch incorrectly). | Re-entry guards around QTimer.singleShot retries are a known foot-gun (lesson: defer-retry-from-worker-failed-slot). | Read `_retry` lifetime. |
| H5 | The popover updates `fft_time_ctx.fs(new_fs)` for the contextual whose dropdown points at `target_fid`, but does NOT update `fft_ctx.fs()` if the user's later FFT click happens on a DIFFERENT contextual whose Fs box still shows the old value — and FFT pulls `fs` from its own contextual (line 1145). | Cross-contextual Fs sync logic at line 451-458 walks all three contextuals but only sets when `sig_data[0] == target_fid`. | Cross-contextual repro. |

The signal-processing specialist must walk these in order and report
which actually fires. H1 is the strongest prior; do not assume.

## Subtask table

| # | subtask | expert | depends_on | rationale |
|---|---|---|---|---|
| T1 | Diagnose Bug #1 root cause (`testdoc/TLC_TAS_RPS_2ms.mf4`, FFT and FFT-vs-Time both blocked after the 非均匀 toast even when the user types Fs into the inspector). Walk H1–H5 above against the actual code; confirm which fires; produce a `diagnosis_report.md` with: (a) for each H, evidence path through `do_fft`/`do_fft_time`/`_show_rebuild_popover`/`rebuild_time_axis` with exact line numbers, (b) chosen root cause, (c) proposed minimal fix sketch (DO NOT implement yet — just the sketch; T2 implements). Output: report path + chosen H. | signal-processing-expert | — | The blocked path is computational (uniformity check, cache key, FFT/Welch fs handling). Surface keywords (popover, button) are present but the failure mode is in the Fs/time-array contract, which is signal-layer ground. |
| T2 | Implement the fix from T1's chosen root cause. Constrained by T1's sketch — no scope creep beyond the chosen H. Most likely change shape: (i) add an inspector-side `apply_fs` action that, in addition to setting `ctx.fs`, calls `fd.rebuild_time_axis(new_fs)` + per-fid cache clear (mirroring the popover's side-effects) so manual Fs entry behaves identically to the popover Accept; OR (ii) hook `do_fft`/`do_fft_time` to detect non-uniform `t` and surface a single error path through `_show_rebuild_popover` rather than letting compute proceed with a stale time_array. Pick whichever T1's diagnosis identifies. Edits stay inside `mf4_analyzer/io/file_data.py` and/or `mf4_analyzer/ui/main_window.py`; UI-side mutator helpers may live on the contextual. Return `files_changed` + `symbols_touched`. | signal-processing-expert | T1 | Same expert as T1 — the fix sketch is an extension of the diagnosis, splitting across experts would invoke the move-then-tighten anti-pattern (`orchestrator/2026-04-22-move-then-tighten…`). If T1 turns out to need PyQt-side state plumbing (e.g. ctx → main_window slot wiring), T2 may flag for re-dispatch. |
| T3 | Fix Bug #2: clamp `RebuildTimePopover.show_at` so the dialog frame stays inside the screen's `availableGeometry()` (and inside the parent main-window's frame geometry as a tighter prior). Algorithm: compute desired top-left at `anchor.mapToGlobal(anchor.rect().bottomLeft())`; after `adjustSize()` (or with `sizeHint()`) compute the popover's expected `QRect`; intersect with the available rect; if the right edge overflows, slide left by overflow; if bottom overflows, place above the anchor (`topLeft` minus popover height) instead of below; never allow x<rect.left() or y<rect.top(). Add a small `MARGIN` (e.g. 8px) so the popover does not hug the screen edge. Add a pytest-qt smoke that simulates an anchor at `screen.availableGeometry().right() - 20` and asserts the popover's final geometry is fully inside the screen rect. Edits: `mf4_analyzer/ui/drawers/rebuild_time_popover.py` only; the test file under `tests/ui/`. Return `files_changed`, `symbols_touched`, `tests_run`, and a screenshot path if interactive verification was performed. | pyqt-ui-engineer | — | Surface keyword (popover, geometry, screen) — pure PyQt geometry/widget-anchoring work, no signal logic. Disjoint files from T1/T2 → can run in parallel. |
| T4 | Regression + UI verification. Two parts: (a) signal-processing pytest that loads `testdoc/TLC_TAS_RPS_2ms.mf4` (or a synthetic non-uniform fixture if test ought to stay deterministic without the binary), simulates "user types Fs into inspector and hits 计算" — asserts that AFTER the simulated input the FFT and FFT-vs-Time computations succeed (i.e. T2's fix held). (b) UI smoke covering both: the popover anchored near the right edge of the inspector lands fully on-screen (T3 regression) AND the inspector's Fs-apply action now triggers a successful compute on the same non-uniform file (T2 cross-cutting verification). | signal-processing-expert | T2, T3 | Algorithm-suite owner runs the algo regression; pytest-qt UI smoke is bundled in the same envelope to avoid splitting test ownership across experts (one report, one `tests_run`). The UI smoke is mechanical assertion-on-geometry, well within signal-processing-expert's pytest scope. If the UI smoke needs widget-painting introspection beyond `geometry().intersects()`, T4 may flag for pyqt-ui-engineer follow-up. |

## Lessons consulted

- `docs/lessons-learned/README.md` — read protocol.
- `docs/lessons-learned/LESSONS.md` — index review.
- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md` — main Claude is the dispatcher.
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — kept T1 (diagnose) + T2 (fix) inside one specialist envelope (signal-processing-expert) to avoid file-level rework when the fix touches the same files the diagnosis points at.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — T2 and T3 edit disjoint files (`main_window.py`/`file_data.py` vs `drawers/rebuild_time_popover.py`), so parallel dispatch is pre-cleared.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — every brief requires `symbols_touched` in the return JSON and a forbidden-symbols self-attestation.
- `docs/lessons-learned/orchestrator/decompositions/2026-04-25-fft-vs-time-2d-implementation.md` — prior decomposition that introduced `_show_rebuild_popover`, `_fft_time_cache_clear_for_fid`, and the `non-uniform time axis` retry path; cited so T1 knows what's already wired and where to look for stale state.
- `docs/lessons-learned/pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md` — informs T1's H2: cache invalidation must be tied to a state-diff, not "handler entered". If the rebuild popover Accept runs but the cache clear is gated incorrectly, the same root cause as the time-domain plot bug applies.
- `docs/lessons-learned/signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md` — informs T1's H2 verification step: confirm `_fft_time_cache_clear_for_fid` is *consumed* in the right place, not just *defined*.
- `docs/lessons-learned/pyqt-ui/2026-04-25-defer-retry-from-worker-failed-slot.md` — informs T1's H4: the QTimer-deferred retry pattern is already cited at line 1923; T1 should verify `_fft_time_retry_pending` lifecycle covers Cancel and double-failure paths.
- `docs/lessons-learned/pyqt-ui/2026-04-24-responsive-pane-containers.md` — informs T3 indirectly: a popover anchored on a right-pane button must NOT fall off-screen even when the right pane is wide. The T3 brief explicitly enumerates the wide-pane case as a regression scenario.

## Parallelism plan

- Wave 1 (sequential): T1 (diagnosis blocks T2's fix shape).
- Wave 2 (parallel): T2 ‖ T3 — disjoint files (`main_window.py`/`file_data.py` vs `drawers/rebuild_time_popover.py`). Pre-cleared per `parallel-same-file-drawer-task-collision`.
- Wave 3 (sequential): T4 (regression depends on both T2 and T3 having landed).

## Rework-detect hint for main Claude (Phase 3)

T2's most likely surface is `main_window.py` (the `_show_rebuild_popover`
flow plus a new inspector-side handler) and possibly
`inspector_sections.py` (a new `apply_fs` button or hook on the
contextual). If T2 ends up writing to `inspector_sections.py`, that
overlaps with prior pyqt-ui specialist territory; main Claude should
verify by symbol that T2 only added a new method (no edits to existing
contextual methods). If T2 must edit existing contextual UI to add the
hook, T2 should flag for pyqt-ui-engineer re-dispatch rather than
silently mutate UI surface — the brief enumerates this.

T3 stays inside `rebuild_time_popover.py`; expect zero overlap with T1/T2.

T4's pytest files under `tests/ui/` and `tests/` do not overlap any
production source file; rework detection should not fire.

## Brainstorming check

The user's bug report names two distinct pain points and a concrete
file. There is no ambiguity in scope. `superpowers:brainstorming` is
NOT needed. `superpowers:writing-plans` is NOT needed (4 subtasks ≤ 3
specialist *types*, only 2 if T2 stays signal-processing).
