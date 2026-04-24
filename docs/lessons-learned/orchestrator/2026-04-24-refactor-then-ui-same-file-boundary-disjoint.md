# Refactor→UI sequential edits on the same file with disjoint method scope are OK

**Date:** 2026-04-24
**Tag:** cause: rework · boundary-adjustment
**Run:** 2026-04-23 Mac 3-pane UI refactor (Phase 2 squad execution)
**Touched specialists:** refactor-architect, pyqt-ui-engineer
**Overlapping file:** `mf4_analyzer/ui/main_window.py`

## What happened

Rework detection fired mechanically on six (S_i, S_j) pairs where
`refactor-architect` edited `main_window.py` in task S_i and
`pyqt-ui-engineer` edited the same file in a later task S_j:

| i → j | S_i (refactor) | S_j (pyqt-ui) |
|---|---|---|
| 14 → 15 | main-window-analysis-rewire | chart-stack-cursor-pill |
| 14 → 16 | main-window-analysis-rewire | chart-stack-stats-strip |
| 14 → 17 | main-window-analysis-rewire | navigator-activation-wiring |
| 14 → 19 | main-window-analysis-rewire | drawer-channel-editor |
| 14 → 21 | main-window-analysis-rewire | drawer-rebuild-time-popover |
| 14 → 22 | main-window-analysis-rewire | drawer-axis-lock-popover |
| 14 → 23 | main-window-analysis-rewire | ui-reset-methods-rewrite |

All six triggered the CLAUDE.md rule "files_changed intersection non-empty
AND experts differ → S_j reworked S_i". But **none of them were actual
rework**. Each pair's scope was disjoint at the method level:

- `main-window-analysis-rewire` owned the eleven analysis method bodies
  (`plot_time / do_fft / do_order_* / _get_sig / _get_rpm / _apply_xaxis
   / _update_combos / _on_span / _on_xaxis_mode_changed`) + the
  `combo_xaxis` wire in `_connect`.
- Each pyqt-ui consumer task owned a different method: `_on_file_activated`,
  `_show_rebuild_popover`, `_show_axis_lock_popover`, `open_editor /
  _apply_channel_edits`, `_reset_cursors / _reset_plot_state`.

No method was edited by two tasks; no line was rewritten.

## Why it worked

The orchestrator's brief for each task enumerated the methods the
specialist was allowed to touch AND the methods it must **not** touch
(with the forbidden list named explicitly: "do NOT touch plot_time /
do_fft / do_order_* / _get_sig / _get_rpm / _apply_xaxis"). That
up-front enumeration is what made parallel / sequential pyqt-ui
consumer edits after the refactor-architect surgery safe.

## Preventative guidance (for future decompositions)

When a cross-expert file overlap is structurally required:

1. **Enumerate forbidden methods** in each specialist's brief, not just
   the allowed methods. Forbidden lists catch mistakes faster than
   allow-lists because specialists default to "stay out of what I
   haven't been told to touch".
2. **Name the rewriter** of disputed helpers in the brief. E.g.,
   "`_reset_cursors` is Task 3.5 territory — if you find it crashing
   because it references a widget you deleted, add a defensive `getattr`
   or flag back; do NOT rewrite it in-place."
3. **Rework detection stays strict** — the mechanical rule above fires
   even when scopes are disjoint. That is the intended safety net. When
   a run produces "disjoint rework" like this batch, add the run to the
   `[boundary-adjustment]` lesson corpus so future orchestrators
   recognize the pattern and cite this lesson when decomposing similar
   multi-file multi-specialist tasks.

## What this lesson is NOT

- Not a rewrite of the rework-detection rule itself. The mechanical
  rule is correct; this lesson documents how to steer around it with
  tight briefs.
- Not a blanket permission to parallelise cross-expert file edits.
  Parallelising four `pyqt-ui-engineer` tasks on the same file caused
  a separate commit-collision pattern — see
  `2026-04-24-parallel-same-file-drawer-task-collision.md`.
