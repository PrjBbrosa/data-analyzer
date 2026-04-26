# Decomposition — FFT vs Time 2D Module Implementation

**Date:** 2026-04-25
**User request (verbatim, this round):** "不用，直接开始。大的模块完成后，让 codex review。有问题直接优化好。记得每个工作都写好报告就行。"
**Prior round:** review of the new specs/plans was completed; `plan v2` exists and the `design` was synced.
**Reference:**
- `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-design.md` (revised 2026-04-25)
- `docs/superpowers/plans/2026-04-25-fft-vs-time-2d.md` (v2)
- `docs/superpowers/specs/2026-04-25-fft-vs-time-2d-squad-brief.md`

**Decomposition shape:** identical to the squad-brief recommendation
(T1–T10). The brief was authored against this codebase and design;
none of the consulted lessons contradict it. We add three execution
contracts on top of the brief without changing task boundaries:

1. Each subtask must write a per-task report at
   `docs/superpowers/reports/2026-04-25-fft-vs-time-T<n>-<slug>.md`
   containing `files_changed`, `symbols_touched`, `tests_run`
   (before/after counts and any failing names), key decisions, and
   any flagged issues. This is mandated explicitly in every brief.
2. Each subtask return JSON must include `symbols_touched` (per
   `silent-boundary-leak-bypasses-rework-detection`) so main Claude's
   rework-detect can verify forbidden-symbol absence.
3. Codex review checkpoints (advisory to main Claude — not specialist
   subtasks). Module boundaries:
   - Module A (signal layer): after T1.
   - Module B (UI skeleton + controls + canvas): after T2 + T3 + T4.
   - Module C (MainWindow integration + worker): after T5 + T6.
   - Module D (cache invalidation + export): after T7 + T8.
   - Module E (verification): after T9 + T10.
   Codex review fixes are dispatched as targeted follow-up subtasks
   (or absorbed by main Claude if mechanical) — they do not reopen
   the original task's report; they get an addendum report at
   `…-T<n>-<slug>-rev<k>.md`.

## Subtask table

| # | subtask | expert | depends_on | rationale |
|---|---|---|---|---|
| T1 | Plan Task 1 (scipy + shared FFT helpers + DC/Nyquist audit) **and** Plan Task 2 (SpectrogramAnalyzer with TDD) | signal-processing-expert | — | Pure numeric / signal-layer work. No GUI imports. TDD-first per spec §11. Bundling Task 1+2 into one specialist envelope avoids the move-then-tighten anti-pattern (`orchestrator/2026-04-22-move-then-tighten…`) — both edit `signal/fft.py` and `signal/__init__.py` and share window helpers. |
| T2 | Plan Task 3 (mode plumbing across toolbar / icons / chart_stack / inspector / inspector_sections / canvases skeleton + MainWindow canvas promotion) | refactor-architect | T1 | Cross-module wiring with no algorithmic content; canvas promotion is a structural move. T1 must exist for the spectrogram skeleton to import without resolution failures. T2's brief enumerates a forbidden-symbol list that protects T3/T4/T5's downstream surfaces (`refactor-then-ui-same-file-boundary-disjoint` precondition). |
| T3 | Plan Task 4 (FFTTimeContextual real controls + presets + disabled-button + selection-preservation) | pyqt-ui-engineer | T2 | Pure UI surface work — combo boxes, signal/slot, getters. `inspector_sections.py` and `inspector.py` only. T2 already created the skeleton classes; T3 fills bodies. |
| T4 | Plan Task 5 (SpectrogramCanvas rendering + vmin/vmax + freq_range + click + hover + lazy dB cache) | pyqt-ui-engineer | T2 | UI surface (canvas rendering + matplotlib events). Independent of T3 — different files. Can run parallel with T3 because their `files_changed` are disjoint (`inspector*.py` vs `canvases.py`). |
| T5 | Plan Task 6 (synchronous `do_fft_time` + cache + cache-hit status + failed-keep-old-chart) | pyqt-ui-engineer | T3, T4 | MainWindow integration; needs both inspector controls (T3) and canvas rendering API (T4) to wire. `main_window.py` only — no overlap with T3/T4 file scopes. |
| T6 | Plan Task 7 (worker thread + finished and cancel pytest-qt smokes) | pyqt-ui-engineer | T5 | Refactors the synchronous compute path inside `do_fft_time` to use a `QThread`-hosted worker. Same expert as T5 by design (same file, same domain) — avoids cross-expert rework on `main_window.py`. |
| T7 | Plan Task 8 (cache invalidation hooks at the five sites + targeted-clear helper) | refactor-architect | T5 | Hook placement is structural — locating the five canonical invalidation sites is refactor-architect's remit. Note: T7 also touches `main_window.py`, which T5 and T6 also touch — see "rework-detect note" below. |
| T8 | Plan Task 9 (export pixmap helpers + clipboard copy + has_result guard) | pyqt-ui-engineer | T4 | Canvas pixmap helpers live on `SpectrogramCanvas`; clipboard hookup lives on MainWindow. `_copy_fft_time_image` is a thin wire; T8's MainWindow edits are scoped to that one method. |
| T9 | Plan Task 10 Steps 1-3 (run pytest: algorithm tests, UI tests, full suite — collect outputs) | signal-processing-expert | T6, T7, T8 | Algorithm-suite owner runs the tests and gathers exit codes / failure names. No code changes; produces the test-output payload that T10 will paste into the validation report. |
| T10 | Plan Task 10 Steps 4-6 (manual UI smoke + write validation report with real observations + commit) | pyqt-ui-engineer | T9 | UI-side observations from manual smoke. Owns the validation report file. |

## Lessons consulted

- `docs/lessons-learned/README.md` — read protocol.
- `docs/lessons-learned/LESSONS.md` — index review.
- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md` — main Claude is the dispatcher.
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — folded Task 1+2 into one envelope (T1) instead of splitting "create skeleton" from "fill bodies" across specialists.
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md` — applies to T2→T3/T4/T5 forbidden-method enumeration on `canvases.py` and `inspector_sections.py`.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — only T3 ‖ T4 are dispatched in parallel (different files; no shared `main_window.py` edit). T5/T6/T7/T8 all touching `main_window.py` are serialized.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — every brief requires `symbols_touched` in the return JSON and a `forbidden_symbols_check` self-attestation.
- `docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md` — relevant to T4. `SpectrogramCanvas.plot_result` calls `self.fig.clear()` via `clear()`; mpl_connect callbacks (`button_press_event`, `motion_notify_event`) use figure-level events (NOT axes callbacks) so the lifecycle issue is structurally avoided here, but the brief still cites this lesson because cursor lines and `_ax_spec` references must not leak across `clear()`.
- `docs/lessons-learned/pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md` — informs T5 and T7. `do_fft_time` is button-triggered (not handler-replayed by `QTimer.singleShot`), so unconditional cache check is fine; but the lesson reminds T7 to keep cache *invalidation* hooks at state-change sites, not at every status-bar tick.
- `docs/lessons-learned/signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md` — applies to T7/T9 review: after T7 lands, T9 must grep that `_fft_time_cache_get` is reachable from `do_fft_time` (consumer-side), not just that the cache exists (producer-side).

## Parallelism plan

- Wave 1 (sequential): T1.
- Wave 2 (sequential): T2 (depends on T1).
- Wave 3 (parallel): T3 ‖ T4 — disjoint files (`inspector*.py` vs `canvases.py`). No shared file edits. Pre-cleared per `parallel-same-file-drawer-task-collision`.
- Wave 4 (sequential): T5 (depends on T3, T4).
- Wave 5 (sequential): T6 (depends on T5).
- Wave 6 (sequential): T7 (depends on T5; serialized after T6 to avoid `main_window.py` race with T6's worker edits).
- Wave 7 (parallel-eligible): T8 (depends on T4 only) — but T8 touches `main_window.py` so it MUST be serialized after T7. Run T8 after T7.
- Wave 8 (sequential): T9 (depends on T6, T7, T8).
- Wave 9 (sequential): T10 (depends on T9).

## Rework-detect note for main Claude (Phase 3)

Mechanical file-overlap on `main_window.py` will fire across pairs
{T2, T5, T6, T7, T8}. Their method-level scopes are disjoint:
- T2: canvas promotion + mode wiring; `_connect` mode bits only.
- T5: `do_fft_time`, `_render_fft_time`, `_get_fft_time_signal`, cache fields, `_fft_time_cache_*` helpers.
- T6: refactors `do_fft_time`'s compute branch into worker; adds `FFTTimeWorker` class.
- T7: edits five existing methods (`close_all`, `_on_close_all_requested`, file-load, `_show_rebuild_popover`, custom-x change) to add `self._fft_time_cache.clear()` / `_fft_time_cache_clear_for_fid`. Adds the helper.
- T8: adds `_copy_fft_time_image` and inspector-relay wiring.

Each brief enumerates the methods it owns AND the forbidden methods
(per `refactor-then-ui-same-file-boundary-disjoint`). After each
specialist returns, main Claude greps the diff for any forbidden
symbol that appears in the changed file (per
`silent-boundary-leak-bypasses-rework-detection` step 3).

If post-task grep finds a forbidden symbol mutated, treat as flagged
and re-dispatch the rightful owner; otherwise the file-overlap rework
hits are expected and lesson-cited, no new lesson required.

## Codex review checkpoints (advisory)

These are NOT subtasks in `decomposition[]`. They are points where
main Claude is expected to invoke `codex` (per the user's instruction
"大的模块完成后，让 codex review") between waves:

| Checkpoint | After waves | Scope |
|---|---|---|
| Module A | T1 done | Signal layer numeric correctness, TDD coverage, scipy delegation, DC/Nyquist audit. |
| Module B | T2 + T3 + T4 done | UI skeleton wiring + inspector controls + canvas rendering. |
| Module C | T5 + T6 done | MainWindow integration + cache + worker. |
| Module D | T7 + T8 done | Cache invalidation hooks + export. |
| Module E | T9 + T10 done | Validation report quality + suite cleanliness. |

If codex flags issues that are mechanical and within an already-touched
file, main Claude may apply them directly; if they require fresh
domain work, dispatch a follow-up specialist subtask (e.g. `T5b`,
`T7b`) with the same expert as the original task. Codex follow-ups
write addendum reports under
`docs/superpowers/reports/2026-04-25-fft-vs-time-T<n>-<slug>-rev<k>.md`.
