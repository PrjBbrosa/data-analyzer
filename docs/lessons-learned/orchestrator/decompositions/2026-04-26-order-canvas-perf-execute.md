# Decomposition — Order Canvas Perf Execute (T1–T6)

**Date:** 2026-04-26
**Trigger:** User asked main Claude to dispatch the squad to execute the
already-authored plan at
`docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md`. Plan, design
spec, and codex-reviewed report are all in place; this is pure execution —
no re-design.

**State at planning time:** `top_level_completions = 10`, `last_prune_at = 0`
(no prune trigger — needs ≥ 20 to fire).

## Task ownership table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| T1 — `signal/order.py` math fixes + chunked vectorize + tests in `tests/test_order_analysis.py` | signal-processing-expert | (none) | Plan §"Task 1" + spec §5 lock `signal/order.py` to signal-processing. Pure computation: counts semantics, broadcast argmin, `_order_amplitudes_batch`, window hoist, Nyquist metadata, chunk-budget memory profile. No UI keywords. |
| T2 — `batch.py` engineering fixes + tests in `tests/test_batch_runner.py` | signal-processing-expert | (none) | Plan §"Task 2" + spec §5. `'自动'` nfft fallback, `_matrix_to_long_dataframe` vectorize, `_write_image` finally-cleanup + cmap='turbo', `AnalysisPreset` un-frozen, `_matches` docstring. Loader/CSV/data-shape territory routes to signal-processing-expert. |
| T3 — order/batch test coverage backfill (cancel_token, progress_callback, batch order_time/order_rpm csv shape) | signal-processing-expert | T1, T3 needs the chunked path landed (cancel checkpoints) and T2 needs the batch fixes + vectorized long-df / un-frozen preset to land first | Plan §"Task 3" pulls together coverage that depends on both T1's `cancel_token`/`progress_callback` plumbing and T2's batch fixes; deliberately separated so T1 / T2 stay narrow. |
| T4 — `canvases.py` extract module-level `build_envelope`, add `PlotCanvas.plot_or_update_heatmap`, new `tests/ui/test_canvases_envelope.py` | pyqt-ui-engineer | (none) | Plan §"Task 4" + spec §5. Canvas refactor is UI surface; envelope helper extraction is the same file `canvases.py` boundary; lessons in `pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md` apply. No cross-module refactor — stays inside canvases.py. |
| T5 — `main_window.py` introduce `OrderWorker(QThread)` + dispatcher with generation token + closeEvent + render methods + `tests/ui/test_order_worker.py` | pyqt-ui-engineer | T1 (uses chunked compute paths' cancel/progress callbacks), T4 (uses `plot_or_update_heatmap` + `build_envelope`) | Plan §"Task 5". Pure Qt threading + signal/slot + render plumbing. Lessons `qthread-wait-deadlocks-queued-quit`, `defer-retry-from-worker-failed-slot`, `matplotlib-axes-callbacks-lifecycle` are all directly applicable. |
| T6 — Cancel button on `OrderContextual`, `open_batch` stale-preset downgrade, `tests/ui/test_order_smoke.py`, manual smoke checklist | pyqt-ui-engineer | T5 (cancel button wires into `_dispatch_order_worker`'s `_order_worker.cancel()`; stale-preset path lives in `MainWindow.open_batch`) | Plan §"Task 6". Touches `inspector_sections.py` (UI widget) and `main_window.py` (orchestration). pyqt-ui-engineer owns both per spec §5. The manual-smoke `.md` lives under `docs/superpowers/reports/` — informational, written by specialist. |

## Boundary discipline (lessons applied)

- **No cross-specialist file overlap:** signal-processing owns `signal/order.py`,
  `batch.py`, and the two `tests/test_*.py` files; pyqt-ui owns `canvases.py`,
  `main_window.py`, `inspector_sections.py`, and `tests/ui/*`. T3 and T2 both
  touch `tests/test_batch_runner.py` — both go to signal-processing, so no
  cross-specialist rework. T5 and T6 both touch `main_window.py` — both go
  to pyqt-ui, sequential (T6 depends on T5). No parallel writes to the same
  file. Lessons applied:
  - `orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
  - `orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
  - `orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- **Forbidden symbols enumerated per brief:** to prevent silent boundary leak
  (lesson 2026-04-25-silent-boundary-leak), each brief lists what the
  specialist must NOT touch — e.g., T1 brief forbids touching any UI module,
  T4 brief forbids touching `signal/order.py` or `main_window.py`. Each
  specialist's return JSON must include `symbols_touched` (additions /
  modifications only).

## Parallel / sequential schedule

```
Wave 1 (parallel): T1, T2, T4
Wave 2 (sequential):  T3 after (T1 ∧ T2)
                       T5 after (T1 ∧ T4)
Wave 3:               T6 after T5
```

T3 and T5 can run in parallel only if both T1 + T2 + T4 have finished, since
T3 and T5 touch disjoint files (signal-processing tests vs pyqt-ui main_window).
But because T3 is signal-processing-expert and T5 is pyqt-ui-engineer, they
also won't collide — main Claude may launch T3 and T5 concurrently.

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md` — confirms planner-executor split (this orchestrator doesn't dispatch).
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — fold mechanical metadata into body creator's brief; bundle related edits per file.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — never parallelise tasks that touch the same file, even 1-line edits.
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md` — cite forbidden methods in briefs to keep rework detection meaningful.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — specialists must list `symbols_touched`; reviewers must grep forbidden symbols.
- `docs/lessons-learned/pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md` — applicable to T5 worker tests.
- `docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md` — applicable to T4 (heatmap rebuild), T5 (canvas.clear before track plot).
- `docs/lessons-learned/pyqt-ui/2026-04-25-defer-retry-from-worker-failed-slot.md` — applicable to T5 dispatcher's wait/terminate fallback.
- `docs/lessons-learned/signal-processing/2026-04-25-envelope-cache-bucket-width-quantization.md` — applicable to T4 build_envelope helper.

## Pre-dispatch skill notes for main Claude

- `superpowers:writing-plans` already satisfied — plan exists and is the
  authoritative artifact for this run.
- `superpowers:subagent-driven-development` is the recommended execution
  sub-skill (called out in plan's preamble); main Claude should pass each
  brief as a self-contained TDD-shaped task.
- No ambiguity that needs `superpowers:brainstorming` — plan, spec, and
  review are converged.
