# Decomposition — TraceLab three-pane panel spacing / margin / radius

**Date:** 2026-06-19
**Mode:** plan
**Routing note:** Missed squad trigger — routed via CLAUDE.md "Missed
triggers" clause. Incoming phrasing (圆角 / 间距 / 面板 / playground 落地)
matched none of the squad trigger tokens. Recorded as a roster-gap lesson.

## Task

Land a playground-tuned change to the TraceLab v7.0 main-window three-pane
layout, scoped to exactly three style/layout knobs:

1. 3px spacing between the left / center / right panes (replacing the
   current 1px hairline separators).
2. 5px outer margin between the pane row and the window edge.
3. 10px border-radius on the outer pane containers (currently square).

Red lines (do NOT touch): pane widths (left pane 272px historical red
line), pyqtgraph canvas, signal processing, control logic. Nested inner
cards and tray background color are explicitly out of scope this round.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| Apply 3px inter-pane spacing, 5px outer margin, 10px outer-panel border-radius to the main-window three-pane container layout/QSS, preserving pane widths and all canvas/logic | pyqt-ui-engineer | (none) | Pure surface/layout styling: spacing, margins, border-radius on panel containers. All keywords name surfaces (panel/layout/margin/corner), not computations. Not a package/module refactor, so it stays with pyqt-ui-engineer per the persistent-UI-design routing rule. |

Single subtask — no cross-specialist dependency, no parallelization, no
rework surface. The red lines forbid the only boundary that another
specialist could own (canvas/DSP/logic).

## Lessons consulted

- docs/lessons-learned/orchestrator/2026-04-26-interactive-playground-unblocks-ui-alignment.md
- docs/lessons-learned/orchestrator/2026-05-30-ui-redesign-verb-missed-squad-trigger.md
- docs/lessons-learned/pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md
- docs/lessons-learned/pyqt-ui/2026-04-26-action-button-on-group-title-needs-qframe-header.md

## Skills assessment

- brainstorming: not invoked — task is unambiguous (three numeric knobs,
  source values copied out of the playground).
- writing-plans: not invoked — single specialist dispatch, well under the
  >3-dispatch threshold.
