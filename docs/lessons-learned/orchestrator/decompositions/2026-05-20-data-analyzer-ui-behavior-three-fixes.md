---
role: orchestrator
tags: [decomposition, pyqt-ui, behavior-fix, audit-only]
created: 2026-05-20
updated: 2026-05-20
cause: top-level
supersedes: []
---

# Decomposition Audit — Data Analyzer UI Behavior, three fixes

User request (verbatim, translated context preserved):

1. Loading a file must NOT auto-plot the first channel. Open empty;
   user picks channels manually.
2. Toggling between split (`subplot`) and overlay (`overlay`) modes
   must preserve the current x-axis range. Do not reset zoom/pan.
3. In overlay mode, after a curve is selected and dragged vertically,
   clicking on a blank region of the canvas should deselect.

## Subtasks

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| Suppress auto-plot of channel[0] on file load; open with empty canvas; UI affordance unchanged elsewhere | pyqt-ui-engineer | [] | Pure surface/behavior; channel-list selection + canvas first-plot trigger live in `file_navigator.py` / `main_window.py` / `chart_stack.py`. No DSP. |
| Preserve x-axis range across `subplot` ↔ `overlay` toggle | pyqt-ui-engineer | [] | Mode-toggle handler currently re-plots and lets matplotlib reset xlim; fix is to capture xlim before rebuild and re-apply after. Surface concern, not computation. |
| Add blank-canvas-click deselect for overlay-mode curve selection | pyqt-ui-engineer | [] | Selection state and mpl_connect plumbing are in `mf4_analyzer/ui/canvases.py` (`_select_overlay_channel_from_event`, `select_overlay_channel`). Pure canvas-event handler change. |

All three subtasks are independent and can be dispatched in parallel.
They all touch the same module(s); bundle into a SINGLE specialist
dispatch to avoid parallel same-file collisions (see
`orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`).

## Bundling decision

Despite three logical changes, all three target the same expert
(`pyqt-ui-engineer`) and the same file cluster
(`mf4_analyzer/ui/canvases.py`, `chart_stack.py`, possibly
`main_window.py`). Bundling into ONE brief avoids:
- parallel same-file `git add` races
- duplicate xlim-callback wiring churn between subtasks 2 and 3

## Lessons consulted

- `docs/lessons-learned/pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md`
  — flush/mutation ordering when set_xlim re-fires xlim_changed.
  Directly applies to subtask 2.
- `docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md`
  — Axes.callbacks survive fig.clear; mode toggle that rebuilds axes
  must re-wire xlim listeners and re-apply xlim AFTER reconnect.
  Directly applies to subtask 2.
- `docs/lessons-learned/pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md`
  — Mode-toggle handler may also be a QTimer-replay target; gate
  envelope invalidation on a state diff so the preserved xlim's
  envelope cache survives. Applies to subtask 2.
- `docs/lessons-learned/pyqt-ui/2026-05-13-matplotlib-resize-and-modal-nav-state.md`
  — Click-to-deselect must not collide with pan/zoom or be inherited
  by a stale press. Applies to subtask 3.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
  — Reason these three subtasks are bundled into one dispatch.

## Routing-keyword observation (for CLAUDE.md owner)

The user's message did NOT contain any of CLAUDE.md's trigger tokens
(`agent` / `squad` / `团队` / `分工` / `重构` / `refactor` /
`多专家` / `multi-agent`), yet the request is clearly squad-shaped
(three coordinated PyQt UI behavior changes, all needing
`pyqt-ui-engineer`'s discipline + reflection protocol). Main Claude
made the correct call to route it anyway.

Recommendation: extend CLAUDE.md routing tokens with at least:
- `data analyzer` (Chinese-mixed product name)
- `分和叠` / `分/叠` / `叠加图` (split-vs-overlay mode language)
- `取消选中` (deselect)
- `保持横坐标` / `保持坐标` (axis-preserve language)

This is product-domain UI language. We should not write a new
orchestrator lesson yet — one missed-match is below the threshold —
but if a second similar miss happens, add the
`[routing][roster-gap]` lesson and propose CLAUDE.md edits.
