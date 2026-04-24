# Decomposition — Modern UI Visual System

**Date:** 2026-04-24
**Plan:** `docs/superpowers/plans/2026-04-24-modern-ui-visual-system.md`
**Reference:** `docs/ui-design-showcase.html`
**Mode:** plan (orchestrator audit for later agent execution)

## Context

The user requested modern/high-end UI design directions, confirmed that a PyQt implementation is acceptable, and asked to write a superpowers-style plan/report so agents can execute later. The app already has the 3-pane topology from the previous Mac-style refactor. This task is visual-system polish, not architecture replacement.

Default design direction is **Precision Light**. The agent definitions have been updated so this direction persists in future UI tasks:

- `.claude/agents/pyqt-ui-engineer.md`
- `.claude/agents/squad-orchestrator.md`

## Routing Decision

This task routes entirely to `pyqt-ui-engineer`.

Rationale:

- Keywords: UI, visual, QSS, icons, toolbar, pane, drawer, Inspector, chart workspace, cursor pill, stats strip.
- These are all surface/widget concerns.
- No numeric formulas, loaders, channel math, or signal-processing APIs are involved.
- No package/module relocation is planned.

`refactor-architect` is held in reserve only if implementation later discovers a true module-boundary or import-graph issue.

`signal-processing-expert` is not involved.

## Decomposition Table

| # | subtask | expert | depends_on | rationale |
|---|---|---|---|---|
| 1 | `qss-token-baseline` | pyqt-ui-engineer | — | Establish global QSS/palette tokens before individual widget polish. |
| 2 | `icon-system-and-toolbar` | pyqt-ui-engineer | qss-token-baseline | Replaces emoji/default-button look; touches `icons.py` and `toolbar.py`. |
| 3 | `left-pane-polish` | pyqt-ui-engineer | icon-system-and-toolbar | Updates file rows, channel hierarchy, search/actions, and color swatches. |
| 4 | `chart-workspace-polish` | pyqt-ui-engineer | left-pane-polish | Updates chart surface, matplotlib styling, cursor pill, and stats strip. |
| 5 | `inspector-and-drawers-polish` | pyqt-ui-engineer | chart-workspace-polish | Updates right pane sections and drawer/sheet/popover surfaces. |
| 6 | `final-ui-verification` | pyqt-ui-engineer | inspector-and-drawers-polish | Runs focused/full tests and desktop visual smoke verification. |

## Parallelism

No planned parallelism.

This is intentional. Prior lessons show UI subtasks that look independent can still collide through shared files (`widgets.py`, `main_window.py`, `drawers/__init__.py`, drawer tests). The work is visual and sequential, so the speed benefit of parallel dispatch is lower than the risk of confusing shared-file commits.

## Cross-File / Rework Risk Forecast

| Earlier | Later | File(s) | Risk | Mitigation |
|---|---|---|---|---|
| `qss-token-baseline` | all later tasks | `style.qss` | medium | Later tasks may need selector additions; they should append targeted selectors instead of reworking tokens. |
| `left-pane-polish` | `chart-workspace-polish` | `widgets.py` | medium | Serialize waves; chart task must inspect existing `StatsStrip`/channel edits before touching `widgets.py`. |
| `chart-workspace-polish` | `inspector-and-drawers-polish` | `style.qss` | low | Inspector task may add section/drawer selectors only; do not change base tokens. |
| drawer polish subtasks | drawer polish subtasks | `drawers/__init__.py`, `tests/ui/test_drawers.py` | high if parallel | Bundle all drawer polish into one task. |

## Specialist Briefs

Use the briefs embedded in:

`docs/superpowers/plans/2026-04-24-modern-ui-visual-system.md`

Each brief is self-contained and points to the exact phase it owns.

## Lessons Consulted

- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md` — confirms orchestrator plans and main Claude/dispatcher executes.
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — informs the decision not to split mechanical styling/import cleanup across specialists.
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md` — informs method/file boundary warnings.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — directly informs the no-parallel drawer/shared-file decision.

## Notes for Dispatcher

- Start with `qss-token-baseline`.
- Do not let later agents redesign the visual direction; Precision Light is already selected.
- If a task needs to alter behavior beyond visual polish, it must flag the owning specialist rather than silently broadening scope.
- Manual desktop verification is required before final completion because headless Qt tests cannot validate visual quality.

