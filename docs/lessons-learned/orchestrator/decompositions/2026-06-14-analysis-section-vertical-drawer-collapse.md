# Decomposition — Analysis-section vertical fold → drawer-style thin rail

**Date:** 2026-06-14
**Mode:** plan
**Trigger keyword:** `agent 串行` (squad keyword `agent`)
**Top-level request:** Execute the already-written TDD plan to convert the
FFT-line / FFT-time-Order-heatmap vertical (top/bottom) collapse from a
left-gutter triangle button (`_PlotCollapseControl`) to a drag-divider-near-bottom
collapse + a bottom thin rail (`_CollapsedRail`) with a small gray ▴ to expand.
Keep the draggable `_SplitDivider`.

**Authoritative documents (execute, do NOT redesign):**
- Plan (TDD, bite-sized, verbatim code): `docs/superpowers/plans/2026-06-14-analysis-section-vertical-drawer-collapse.md`
- Spec: `docs/superpowers/specs/2026-06-14-analysis-section-vertical-drawer-collapse-design.md`

## Routing decision

All five tasks are PyQt5/pyqtgraph UI work (widget creation, layout
positioning, drag/signal wiring, QSS object-name swap, visual verification).
No numerical/DSP algorithm is touched — the FFT/Order *computation* is not
modified, only the *collapse surface* of the canvases that display it. Per the
surface-vs-computation rule, all five route to `pyqt-ui-engineer`.

## Serialization decision (MANDATORY)

The plan's five tasks share heavily-coupled files. Confirmed clean baseline:
`line_canvas.py`, `heatmap_canvas.py`, `mf4_analyzer/ui_kit/style.qss` all clean;
`test_pg_line_canvas` + `test_pg_heatmap_canvas` = 125 passed baseline.

Shared-file map:
- `heatmap_canvas.py` — edited by T1, T3, T4
- `line_canvas.py` — edited by T2, T4
- `tests/ui/test_pg_line_canvas.py` — edited by T2
- `tests/ui/test_pg_heatmap_canvas.py` — edited by T1, T3
- `mf4_analyzer/ui_kit/style.qss` — edited by T4

Because the same files are mutated by multiple tasks (and ALL file-mutating
subagents share one git index even on disjoint files), the entire chain MUST run
strictly serial: T1 → T2 → T3 → T4 → T5. No parallelism. Only read-only review
may overlap. This is dictated by both
`parallel-same-file-drawer-task-collision` and
`parallel-mutators-share-git-index-even-disjoint-files`.

## Codex coexistence constraint (MANDATORY in every brief)

The working tree has uncommitted codex changes (`main_window.py`,
`test_main_window_smoke.py`, two analysis-interaction-review-fixes docs). These
do NOT overlap our target files. Every specialist MUST stage with an explicit
pathspec `git add <only-its-own-target-files>` and MUST NEVER run `git add -A`
or `git add .`, and MUST NOT touch/commit any codex file.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| T1 add `_CollapsedRail` + `_SPLIT_COLLAPSE_AT` + `_position_collapse_layout` to heatmap_canvas.py (pure additive) + migrate matching tests | pyqt-ui-engineer | — | New PyQt widget + layout positioning helper; pure additive, no DSP. Owns the new symbols only. |
| T2 wire line_canvas.py (`_collapsed_rail` + drag-to-collapse + `_set_bottom_collapsed`), migrate test_pg_line_canvas | pyqt-ui-engineer | T1 | Consumes T1's `_CollapsedRail`/`_SPLIT_COLLAPSE_AT`/`_position_collapse_layout`; drag + signal/slot wiring is UI. Shares heatmap_canvas import surface from T1. |
| T3 wire PgHeatmapCanvas in heatmap_canvas.py (keep slice_panel linkage), migrate test_pg_heatmap_canvas | pyqt-ui-engineer | T1, T2 | Edits heatmap_canvas.py again (after T1) so must follow T1; mirrors T2's line wiring pattern; preserves slice_panel coupling. |
| T4 delete `_PlotCollapseControl` + old `_position_split_controls`; QSS swap `#plotCollapseBar`→`#plotCollapsedRail` in ui_kit/style.qss | pyqt-ui-engineer | T1, T2, T3 | Removal must come AFTER all new wiring lands or the old path is still referenced; touches heatmap_canvas.py + line_canvas.py + style.qss — pure cleanup, must be last code task. |
| T5 visual verification of all three sections (real render screenshots) + full regression | pyqt-ui-engineer | T1, T2, T3, T4 | Verify-UI-visually mandate: real-render screenshots, not "属性设上了+单测过"; runs full test suite as the green gate. |

## Lessons consulted (step 4)

- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/pyqt-ui/2026-05-31-splitter-setsize-requires-shown-widget.md`

## Expected rework-detection hits (predicted, accept as cost of serial chain)

Because heatmap_canvas.py is edited by T1, T3, T4 and line_canvas.py by T2, T4 —
all same expert (`pyqt-ui-engineer`) — the cross-EXPERT rework rule does NOT
fire (it requires differing experts). Same-expert sequential edits on a shared
file are the intended serial pattern here, not rework. No rework lesson expected.
