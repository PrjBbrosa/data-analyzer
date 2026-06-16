---
role: pyqt-ui
tags: [pyqtgraph, tick-density, bottom-ticks, target-count, min-gap, fft-frequency-axis, heatmap, right-edge-truncation, sibling-divergence]
created: 2026-06-17
updated: 2026-06-17
cause: insight
supersedes: []
---

## Context
The computed FFT frequency plot (and FFT-vs-Time / Order heatmaps) rendered
non-round, right-truncated X ticks: e.g. on view range `[0, 7.162]` the bottom
axis showed `0.21, 0.69, 1.16, … 4.57` and then NOTHING for the remaining ~36%
up to the right frame. The time-domain bottom axis, over the same kind of
non-round range, never had this — it stayed on clean `1, 2, 3, …` reaching the
edge.

Both axes run a "target tick COUNT → fitted nice ticks" algorithm, but in TWO
sibling functions:
- time-domain: `tick_density.py:_fit_x_tick_labels`
- FFT line + heatmaps: `heatmap_canvas.py:_apply_target_bottom_ticks`

Both enumerate nice steps over `range(exponent-2, exponent+4)`, which admits
steps up to ~100× finer than `raw_step` (so a step like `0.01` is a candidate).
The divergence was the min-gap collision branch:
- `_fit_x_tick_labels` → `return None` (REJECT the whole step).
- `_apply_target_bottom_ticks` → `continue` (THIN: drop that one tick, keep the
  step).

Thinning let the over-fine `0.01` step survive: its 700+ raw values were greedy-
thinned down to *exactly* the target count (10) at arbitrary non-round positions,
so it scored `abs(len-target)=0` and BEAT the genuine nice steps (`0.5`→14 ticks,
`1.0`→7 ticks). The thinned set also starts at the first label that clears the
left edge-pad and stops once labels run out under the gap rule, so it truncates
well short of the right frame.

## Lesson
For target-COUNT nice-tick fitters, an interior min-gap collision means the step
is simply too fine — REJECT the candidate, do not thin it. Thinning an over-fine
step into a target-count set of non-round ticks makes it win on count and
truncate the axis. Thinning is only legitimate as a last resort in
`extreme_narrow` mode (`width < target*8`, where `min_gap`/`edge_pad` are forced
to 0 and there is no room for any nice step) — keep `continue` there only.

## How to apply
Any pg target-count tick fitter must, on an interior `min_gap` violation, drop
the WHOLE candidate (mirror `_fit_x_tick_labels`'s `return None`), guarded so
`extreme_narrow` still thins. When you touch one of the two sibling fitters,
check the other for drift (they are not shared code — see
[[2026-06-11-inspector-tick-counts-vs-pg-density-factors]]). Verify on a
non-round auto range like FFT `[0, 7.162]`: ticks must be round AND the rightmost
tick must sit within ~1 spacing of the view edge. Regression tests:
`tests/ui/test_pg_heatmap_canvas.py::test_bottom_ticks_span_to_right_edge_for_nonround_range`
and `::test_bottom_ticks_use_round_grid_for_nonround_range`.
