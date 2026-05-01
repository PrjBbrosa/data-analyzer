---
date: 2026-05-01
slug: codex-review-fixes
mode: plan
source_review: docs/code-reviews/2026-05-01-recent-prs-deep-review.md
spec: docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md
plan: docs/superpowers/plans/2026-05-01-codex-review-fixes.md
---

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W1 — Inspector OrderContextual + FFTTimeContextual `_on_amp_unit_changed` reset z range; new `mf4_analyzer/ui/_axis_defaults.py` | pyqt-ui-engineer | [] | All edits live in PyQt widget surface (`inspector_sections.py`) and a tiny UI-side constants module; behavior is widget signal/slot wiring + `blockSignals` isolation, which is the UI engineer's surface, not signal processing. |
| W2 — Batch OutputPanel `combo_amp_unit` handler aligned with W1; reuse `z_range_for` from `_axis_defaults` | pyqt-ui-engineer | ["W1"] | Same widget-handler pattern reused from `_axis_defaults`; W2 must wait for W1's new module to land + its codex pass before importing `z_range_for`. PyQt-UI specialist owns the OutputPanel widget. |
| W3 — `ChartOptionsDialog._apply_axis` log-scale non-positive limit validation + warning + dialog-keep-open | pyqt-ui-engineer | [] | Dialog's `_apply_axis` is widget-side scale/lim wiring, `QMessageBox.warning` UX, and `accept()` flow; pure UI surface concerns. Independent of W1/W2 (different file, no shared symbol). |

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol.
- `docs/lessons-learned/LESSONS.md` — master index (filtered to `## pyqt-ui` heading by relevant tags).
- `docs/lessons-learned/.state.yml` — counters (read-only): `top_level_completions=34`, `last_prune_at=21`. No prune trigger this run (gap=13).
- `docs/lessons-learned/pyqt-ui/2026-04-29-spinbox-button-removal-needs-widget-and-qss.md` — spinbox-side construction-site idiom (how-to-apply pattern: helper + per-call wrap).
- `docs/lessons-learned/pyqt-ui/2026-04-27-modal-from-qthread-finished-segfaults-offscreen.md` — `QMessageBox` under offscreen Qt: gate on visibility / monkeypatch in tests; relevant to W3 dialog warning.
- `docs/lessons-learned/pyqt-ui/2026-04-26-popover-accept-deactivate-race.md` — `QDialog.done` not idempotent + offscreen-test driving idiom; W3 must not let warning path silently flip the apply result.
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md` — conditional setEnabled state must be flushed at the end of mutation; relevant to `_sync_axis_enabled()` ordering after `chk_z_auto.setChecked(True)` + `setValue`.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — same-expert serial scheduling: W1/W2/W3 are all `pyqt-ui-engineer`; serialize per the depends_on graph (W1 → W2; W3 standalone) plus the explicit codex-review gate between every wave.
- `docs/lessons-learned/orchestrator/2026-04-25-codex-prompt-file-for-long-review.md` — wave-gate codex review must use `--prompt-file` and `--write` when reports are emitted.

## Cadence

- `top_level_completions = 34`, `last_prune_at = 21`, gap = 13 (< 20). No prune dispatch needed at the end of this run; main Claude still increments on completion.

## Routing notes

- All three subtasks match the `axis-edit / dialog / spinbox / amp_unit / log-scale / QMessageBox` surface keywords → pyqt-ui-engineer per roster.
- No keyword overlap with signal-processing-expert (no FFT computation, filter design, loader concerns) — `_axis_defaults.py` only stores UI default tuples.
- No refactor-architect overlap — no module relocation; new file is a leaf addition.

## Wave gating (for main Claude)

- After W1: dispatch codex review of working tree; if any P1/P2 issue, stop and re-dispatch pyqt-ui-engineer with the codex feedback before starting W2.
- After W2: same.
- After W3: same.
- Do NOT run W2 in parallel with W1 — depends_on is hard. W3 may dispatch in parallel with W1 (independent files), but the project policy here is per-wave codex-gate, so default to fully serial W1 → W2 → W3 unless main Claude explicitly opts into the W3‖W1 path.
