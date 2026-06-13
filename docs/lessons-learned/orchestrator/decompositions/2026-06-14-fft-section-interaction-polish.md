# Decomposition — FFT section interaction polish (R1-R4)

**Date:** 2026-06-14
**Mode:** plan
**Top-level request:** "codex那边完成了，你安排agent执行吧。" — execute the
already-written FFT section interaction-polish plan.
**Plan:** `docs/superpowers/plans/2026-06-14-fft-section-interaction-polish.md`
**Spec:** `docs/superpowers/specs/2026-06-14-fft-section-interaction-polish-design.md`
**Baseline:** codex divider/collapse finalization committed at `0f7338e`;
`line_canvas.py` is clean and point-editable.

## Routing summary

All four requirements are PyQt5/pyqtgraph UI changes with NO numeric/DSP
algorithm work, so every subtask routes to `pyqt-ui-engineer`. The roster's
surface-vs-computation rule confirms this: the keywords here (font, grid,
axis, ViewBox, LinearRegionItem, antialias, drag) are all rendering/interaction
surfaces, not FFT/Welch/filter computations.

## Serialization decision (load-bearing)

- R4/R2/R3 all mutate `line_canvas.py`; R2 and R3 both edit `__init__`
  → **hard same-file serialization** (cite `parallel-same-file-drawer-task-collision`).
- R1 touches only `app.py` + `pg_canvas/fonts.py` (disjoint from
  `line_canvas.py`), BUT per `parallel-mutators-share-git-index-even-disjoint-files`,
  disjoint-file mutators on the same branch still contend on the shared
  git index/HEAD. Therefore R1 is NOT parallelized either — the whole
  chain runs **strictly serial**.
- Within-file ordering follows the plan: R4 (Task 2) → R2 (Task 3) →
  R3 (Task 4, which internally covers 4a region/signals then 4b drag
  ViewBox). R1 (Task 1) has no `line_canvas.py` dependency and can run
  first or last; placed first so it lands as an independent commit while
  the `line_canvas.py` chain proceeds after it.

## Decomposition table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| R1 global CJK chart font (app.py + fonts.py) | pyqt-ui-engineer | (none) | QApplication.setFont + pg font fallback; UI surface, disjoint files, but serialized vs the chain per git-index lesson |
| R4 sink interactive AA onto rendered child curve (line_canvas.py) | pyqt-ui-engineer | R1 | pyqtgraph PlotDataItem→child PlotCurveItem antialias; first line_canvas.py edit, serialized after R1 |
| R2 drop top/right grid + pad empty-state Y (line_canvas.py __init__/full_reset) | pyqt-ui-engineer | R4 | AxisItem.setGrid + setYRange; same file as R4, must serialize |
| R3 left-drag time preview = region select for FFT (line_canvas.py __init__ + new ViewBox) | pyqt-ui-engineer | R2 | LinearRegionItem + _TimePreviewViewBox; same __init__ as R2, must serialize; biggest item (4a+4b) |

## Forbidden-scope notes per brief (anti-rework)

Because R4/R2/R3 share `line_canvas.py` and R2/R3 share `__init__`, each
brief names its allowed symbols AND the symbols it must NOT touch, per
`refactor-then-ui-same-file-boundary-disjoint`:

- R4 owns ONLY `_set_curve_aa`. Must not touch `__init__`, `full_reset`,
  grid setup, or any ViewBox.
- R2 owns ONLY the `showGrid` loop in `__init__` and the empty-state Y
  branch in `full_reset`. Must not touch `_set_curve_aa` or add region/ViewBox.
- R3 owns the region item block at end of `__init__`, the new
  `select_time_region`/`clear_time_region`/`_on_time_region_changed`
  methods, the new `_TimePreviewViewBox` class, the `_plot_time` viewBox
  swap, and the context-menu "clear selection" wire. Must not re-touch
  the grid loop (R2) or `_set_curve_aa` (R4).

## Lessons consulted (step 4)

- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`

## Specialist-facing pyqt lessons to cite in briefs

- `docs/lessons-learned/pyqt-ui/2026-05-29-pyqtgraph-axisitem-setwidth-clamp-and-builtin-right-column-spacing.md`
  (R2: `showGrid(y)` lights both built-in axes; x-only / per-axis setGrid)
- `docs/lessons-learned/pyqt-ui/2026-06-11-sigmouseclicked-fires-after-viewbox-menu.md`
  (R3: ViewBox event-order / context-menu interaction)
- `docs/lessons-learned/pyqt-ui/2026-06-04-dynamic-property-border-needs-styledbackground-and-padding.md`
  (R2/R3 visual verification: trust saved PNG over a pixel probe; assert
  object state, not aggregate ink)
- `docs/lessons-learned/pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap.md`
  (R3: grep tests AND production for ViewBox/canvas attribute surface
  before swapping `_plot_time`'s ViewBox)
