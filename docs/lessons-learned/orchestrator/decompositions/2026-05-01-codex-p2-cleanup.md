# Decomposition — Codex Review P2 Cleanup (2026-05-01)

Source spec: `docs/superpowers/specs/2026-05-01-codex-p2-cleanup-design.md`
Source plan: `docs/superpowers/plans/2026-05-01-codex-p2-cleanup.md`

Two P2 issues from the codex review of recent PRs, decomposed into two
serial waves with a codex-review gate after each.

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W4 — OrderWorker dead-code cleanup (P7-D1) | refactor-architect | (none) | Cross-method deletions in `main_window.py` plus removal of an entire test file = module-level cleanup; no signal-processing or UI redesign content. Refactor specialist owns mechanical removal + grep-zero verification. |
| W5 — QSS spinbox `[compact="true"]` dynamic-property convergence (P8-O1) | pyqt-ui-engineer | W4 | QSS selector authoring + Qt dynamic-property + setProperty timing is pyqt-ui surface work. Serial after W4 to keep the wave-gate cadence clean even though file-sets do not overlap. |

## Lessons consulted

- `docs/lessons-learned/README.md` (reflection protocol)
- `docs/lessons-learned/LESSONS.md` (master index)
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/refactor/2026-04-22-cross-layer-constant-promote-to-package-root.md`
- `docs/lessons-learned/pyqt-ui/2026-04-27-qss-padding-overrides-setcontentsmargins.md`
- `docs/lessons-learned/pyqt-ui/2026-04-28-qss-subcontrol-needs-explicit-arrow-glyph.md`

## Files in scope (no overlap between waves)

- W4: `mf4_analyzer/ui/main_window.py`, `tests/ui/test_order_worker.py` (delete)
- W5: `mf4_analyzer/ui/widgets/compact_spinbox.py`, `mf4_analyzer/ui/inspector_sections.py` (only `_no_buttons` helper), `mf4_analyzer/ui/drawers/batch/method_buttons.py`, `mf4_analyzer/ui/style.qss`, `tests/ui/test_compact_spinbox.py` (NEW)

W5 touches `inspector_sections.py` only inside the `_no_buttons` helper;
W1 from earlier work touched a different method (`_on_amp_unit_changed`).
That is not rework — but the W5 specialist must report `symbols_touched`
at method granularity so silent boundary leaks cannot hide.

## Wave gate cadence

Codex review gate after each wave. BLOCK verdicts must be resolved
before the next wave is dispatched. After W5 passes, run a final
end-to-end codex review covering both fixes together.
