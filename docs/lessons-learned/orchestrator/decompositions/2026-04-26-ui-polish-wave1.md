# Decomposition audit — Wave 1 of UI polish + Order-RPM removal

**Date:** 2026-04-26
**Plan:** `docs/superpowers/plans/2026-04-26-ui-polish-and-order-rpm-removal.md`
**Spec:** `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md` (rev 4, codex approved)
**Wave:** 1 of 3 (Order-RPM chain removal)
**Mode:** plan only — Waves 2 and 3 will be re-planned via separate
`mode: plan` calls after their preceding wave's codex review gate
clears. This audit covers Wave 1 only.

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W1-A · signal+batch RPM removal (Tasks 1.1, 1.2) | signal-processing-expert | — | Spec §7 file-ownership table assigns `signal/**`, `batch.py`, `tests/test_order_analysis.py`, `tests/test_batch_runner.py` to signal-processing-expert. Tasks 1.1+1.2 are pure deletions of `OrderRpmResult`, `compute_rpm_order_result`, `compute_order_spectrum`, `OrderAnalysisParams.rpm_res`, batch `'order_rpm'` method + `_compute_order_rpm_dataframe` + `params['rpm_res']`, plus their corresponding pytest cases. All within the signal/computation surface. |
| W1-B · UI RPM removal (Tasks 1.3, 1.4, 1.5, 1.6, 1.7) | pyqt-ui-engineer | — | Spec §7 assigns `ui/**` (incl. `drawers/`) and `tests/ui/**` to pyqt-ui-engineer. Tasks 1.3–1.7 delete `OrderContextual.btn_or` + `spin_rpm_res` + `order_rpm_requested` signal in `inspector_sections.py`, the relay in `inspector.py`, `do_order_rpm` / `_render_order_rpm` / OrderWorker `'rpm'` branch / "当前转速-阶次" string in `main_window.py`, the `combo_method` entry + `spin_rpm_res` in `drawers/batch_sheet.py`, and their pytest-qt assertions. All UI surface — dispatch to pyqt-ui-engineer. |
| Wave-1 verification (Task 1.8) | pyqt-ui-engineer | W1-A, W1-B | No `.py` source mutations — only the unified S4-T1 grep, the `'rpm'` worker-kind grep, full `pytest tests/`, and a Qt smoke launch confirming OrderContextual now shows three buttons. The smoke step requires QApplication startup so route to pyqt-ui-engineer rather than signal-processing-expert. The Wave-1 codex review gate itself is dispatched by main Claude per CLAUDE.md runbook (`Agent subagent_type=codex:codex-rescue`) and is NOT part of this decomposition. |

## File-set disjointness check (parallel-safety)

W1-A files:
- `mf4_analyzer/signal/order.py`
- `mf4_analyzer/signal/__init__.py`
- `mf4_analyzer/batch.py`
- `tests/test_order_analysis.py`
- `tests/test_batch_runner.py`

W1-B files:
- `mf4_analyzer/ui/inspector_sections.py`
- `mf4_analyzer/ui/inspector.py`
- `mf4_analyzer/ui/main_window.py`
- `mf4_analyzer/ui/drawers/batch_sheet.py`
- `tests/ui/test_order_worker.py`
- `tests/ui/test_inspector.py`

Intersection: ∅ (verified by spec §7 ownership table and plan §"Pre-flight File Layout").
Therefore W1-A ‖ W1-B is safe per
`orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` —
no shared file means no `git add` race.

## Forbidden-symbols boundary discipline

Per `orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`,
each brief explicitly enumerates files-it-may-not-touch and demands
`symbols_touched` + `forbidden_symbols_check` in the return JSON so
main Claude can rework-grep before the codex gate.

W1-A forbidden symbols (must NOT appear in W1-A's diff):
- Any `mf4_analyzer/ui/**` file modification
- `tests/ui/**` modification
- `compute_order_spectrum_time_based` (kept — `compute_order_spectrum` is the deletion target; do not co-delete the time-based variant)
- `compute_time_order_result`, `extract_order_track_result`, `OrderTimeResult`, `OrderTrackResult`, `OrderAnalyzer` class itself, `_order_amplitudes_batch`, `_order_amplitudes`, `build_envelope`

W1-B forbidden symbols:
- `mf4_analyzer/signal/**` modification
- `mf4_analyzer/batch.py` modification
- `tests/test_order_analysis.py`, `tests/test_batch_runner.py`
- The four `tight_layout` rewrites in `main_window.py` and `canvases.py` (those are S1, deferred to Wave 2 — no co-mingling)
- The S2/S3 changes (`chart_stack.py` set_mode visibility, `_BUILTIN_PRESET_DISPLAY` rename) — Wave-2 scope only
- `chart_stack.py`, `canvases.py`, `_axis_interaction.py` (new), `_toolbar_i18n.py` (new) — all Wave-2

## Lessons consulted (read in step 4)

- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md` — orchestrator plans, main Claude dispatches.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — file-set disjointness check above.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — forbidden-symbol enumeration above.
- `docs/lessons-learned/orchestrator/2026-04-25-codex-prompt-file-for-long-review.md` — main Claude must use `--prompt-file --write` for the Wave-1 codex gate.
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — Tasks 1.1+1.2 stay within W1-A (one specialist), Tasks 1.3–1.7 stay within W1-B; we do NOT split "delete file body" from "tighten imports" across specialists.
- `docs/lessons-learned/pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md` — Wave 1 deletes `OrderWorker._kind == 'rpm'` branch only, not OrderWorker plumbing; the QThread teardown contract for `'time'`/`'track'` branches is preserved.
