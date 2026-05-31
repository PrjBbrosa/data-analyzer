# Decomposition — pyqtgraph TimeDomain three UI fixes

**Date:** 2026-05-29
**Branch:** plan/pyqtgraph-timedomain-migration
**Mode:** plan
**Slug:** pyqtgraph-timedomain-three-ui-fixes

## Task summary

Fix three UI problems in `TimeDomainCanvasPG` (the pyqtgraph time-domain
renderer now live on the migration branch), all rooted in
`mf4_analyzer/ui/pg_canvases.py`:

1. **Split (subplot) mode x-axis misalignment** — each channel is an
   independent `PlotItem`; pyqtgraph auto-sizes each left axis by its own
   tick-label width, so each row's plot-area left edge lands at a
   different screen x, skewing the shared time axis / grid. Range is
   already synced via `_propagate_xlim_to_siblings`; geometry is not.
   Fix: after build, unify left-axis width to the max across subplots
   (`handle._ax('left').setWidth(w)`), re-check in `resizeEvent` and
   after `set_tick_density`.

2. **Overlay mode curves cannot be individually selected/Y-dragged** —
   `select_overlay_channel` / `_begin_overlay_y_drag_at` /
   `_apply_overlay_y_drag_at` / `_apply_overlay_emphasis` exist but are
   not wired to mouse events. `eventFilter` only handles double-click +
   cursor press/move. Need: press→nearest-curve/axis hit→select,
   move→Y-drag, blank-click→deselect, disable default pan during drag.
   matplotlib reference: `_select_overlay_channel_from_event`
   (canvases.py:850-895) + `_update_overlay_y_drag` (canvases.py:916),
   pick radius `_overlay_pick_radius_px=12.0`.

3. **Overlay-mode left-axis (first) channel cannot be made target** —
   first channel uses the main PlotItem's main ViewBox (also X owner /
   default mouse receiver / geometry anchor); channels 2..N get isolated
   aux ViewBox + right axis via `_add_overlay_axis_handle`. The first
   channel shares the X/pan ViewBox so Y-drag fights X padding (see the
   1767-1787 X-pin hack). Fix (structural): make overlay layout
   symmetric — every channel (including the first) gets its own aux
   ViewBox + Y axis; main ViewBox demoted to X-master / mouse-capture
   only (no curves). Reuse `_sync_overlay_aux_viewboxes` /
   `_connect_overlay_view_sync` to fold in the first channel.

## Constraints

- All work is pure UI/PyQt → routes to `pyqt-ui-engineer`.
- Preserve W0 contract (signals / methods / attributes surface
  unchanged); existing tests must pass; offscreen Qt
  (`QT_QPA_PLATFORM=offscreen`).
- Files: primarily `mf4_analyzer/ui/pg_canvases.py`; possibly
  `tests/ui/` and `tests/perf/`.
- Problems 2 & 3 are tightly coupled (shared overlay event layer +
  symmetric layout) → bundle into one change. Problem 1 is independent.

## Routing decision

All three problems are UI/PyQt surface work (canvas geometry, axis
width, mouse-event wiring, ViewBox layout) → `pyqt-ui-engineer` per the
"surface-vs-computation" rule (these are plot/canvas/axis surfaces, not
FFT/Welch/filter computations).

**Serialization (NOT parallel):** all subtasks edit the SAME file
`mf4_analyzer/ui/pg_canvases.py` and likely the same `tests/ui/` files.
Per `orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`,
two specialists editing the same file in parallel race `git add` and
produce commits whose titles don't match contents. Therefore the two
subtasks MUST run sequentially. Subtask B `depends_on` A so its diff is
written on top of A's committed state.

Why two subtasks and not one: Problem 1 (left-axis width unification) is
mechanically and conceptually disjoint from Problems 2+3 (overlay event
layer + symmetric ViewBox layout). Splitting keeps each commit
bisectable. They are serialized, so no `git add` race. Per the
boundary-leak lesson, each brief enumerates the symbols/regions it owns
and forbids touching the other's regions, and asks the specialist to
report `symbols_touched`.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| A: split-mode left-axis width unification (Problem 1) | pyqt-ui-engineer | (none) | Canvas/axis geometry surface fix; independent, disjoint region from overlay code. |
| B: overlay event layer + symmetric ViewBox layout (Problems 2+3) | pyqt-ui-engineer | A | Mouse-event wiring + ViewBox layout surface; tightly coupled per user; serialized after A to avoid same-file `git add` race. |

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
- `docs/lessons-learned/pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md`
- `docs/lessons-learned/pyqt-ui/2026-05-28-arraytoqpath-not-byte-identical-to-moveto-lineto-loop.md`
- `docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md`

## Missed-keyword note

The user request ("你编排一下执行吧" = "go ahead and orchestrate
execution") did not literally match a squad keyword. Main Claude routed
it under the missed-triggers rule. Recorded here for the corpus; no
roster gap (the routing itself is unambiguous — clear multi-fix UI work
on a known file). No new routing lesson warranted because the existing
"orchestrate / 编排" phrasing is an imperative to run the squad, already
covered conceptually by the squad-runbook trigger set; this is a
phrasing-coverage note, not a roster keyword the orchestrator must own.
