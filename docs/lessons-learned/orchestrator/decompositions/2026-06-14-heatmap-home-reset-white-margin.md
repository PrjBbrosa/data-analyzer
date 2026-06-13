# Decomposition — heatmap Home/reset white-margin fix

**Date:** 2026-06-14
**User request (verbatim summary):** After clicking "查看全部" (Home /
`reset_view_to_data_extents`) on heatmap-class views (FFT-vs-Time spectrogram
and Order analysis, both via shared `PgHeatmapCanvas`), white margins appear at
the image edges. Initial render has no margin; only Home introduces it.

**Diagnosis (provided by main Claude via systematic-debugging — do NOT
re-diagnose):**
- File: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Initial render `plot_result` (~777–781): `setXRange(x0,x1,padding=0)` /
  `setYRange(y0,y1,padding=0)` → image fills, no margin.
- `reset_view_to_data_extents` (~937–941): uses `_visual_padded_bounds(...)` +
  `setRange(padding=0)` → adds 1.5% per side.
- `_visual_padded_bounds` (~363): `pad = span*0.015; return lo-pad, hi+pad`.
- ImageItem rect (~753 `setRect`) only spans exact `[x0,x1]×[y0,y1]`, so the
  Home over-expansion exposes white ViewBox bottom (`setBackground("#ffffff")`).

**Fix direction (decided; details to specialist):**
- Make heatmap `reset_view_to_data_extents` mirror `plot_result` lines 777–781:
  exact extents + `padding=0`, dropping the `_visual_padded_bounds` calls so
  Home matches the initial flush-edge render.
- Reset should still honor existing manual x/y range semantics if present; the
  current reset returns to full-data extents, so exact extents is correct.
- KEEP `_visual_padded_bounds` shared helper — `line_canvas.py` line-plot reset
  still needs the 1.5% breathing room (white-bg line plots avoid touching the
  frame). Do NOT touch the line-plot path.
- MUST verify with real rendering per `feedback-verify-ui-visually`: screenshot
  before/after Home and confirm no white edge — not "padding=0 set + unit test
  green".

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| S1: In `PgHeatmapCanvas.reset_view_to_data_extents`, replace `_visual_padded_bounds` calls with exact-extents `setXRange/setYRange(padding=0)` mirroring `plot_result` (~777–781); leave `_visual_padded_bounds` and the line-canvas reset path untouched; verify flush-edge Home via real-render screenshot on both spectrogram and order views | pyqt-ui-engineer | [] | View-range / ViewBox / ImageItem rendering surface on a PyQt/pyqtgraph canvas — a UI surface concern (range, axis, background), not a computation. Roster routes surface keywords to pyqt-ui-engineer; single file, single expert, no split needed. |

## Lessons consulted (read in step 4)

- `docs/lessons-learned/orchestrator/2026-05-30-ui-redesign-verb-missed-squad-trigger.md`
  — confirms 优化/optimize UI bug-fix verbs route to pyqt-ui-engineer via the
  act ("does it ask for `.py` edits?"), keyword-bare phrasing is expected here.
- `docs/lessons-learned/pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md`
  — the 2026-06-11 heatmap update documents `reset_view_to_data_extents` /
  `axes_list` as INDEPENDENT contract surfaces on `PgHeatmapCanvas` and that
  "Home works" ≠ pan/zoom wired; relevant because S1 edits the Home path and
  must verify on the live canvas (both with_slice=False Order and with_slice=
  True FFT-vs-Time sections), not just unit tests.

## Routing notes

- No `brainstorming`: request is unambiguous (single fix direction already
  decided).
- No `writing-plans`: 1 specialist dispatch, well below the >3 threshold.
- No roster gap: "view range / canvas / background" is a UI surface → clean
  pyqt-ui-engineer match. No `[routing][roster-gap]` lesson warranted.
