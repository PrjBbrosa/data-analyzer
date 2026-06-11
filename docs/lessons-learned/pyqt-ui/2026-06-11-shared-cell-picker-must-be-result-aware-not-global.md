---
role: pyqt-ui
tags: [pyqtgraph, heatmap, hover, readout, value-at, argmin, floor-fraction, db, unit, caliber, single-source-of-truth, shared-method]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
`PgHeatmapCanvas` serves two modes from one widget: the always-on Order
map (`with_slice=False`, rendered via `plot_or_update_heatmap`, no
`result`) and the FFT-vs-Time slice (`with_slice=True`, via `plot_result`,
which sets `self._result` with `times`/`frequencies` arrays). Its hover
readout (`_on_scene_hover`) picked a cell by argmin-nearest over the
result axes, but the remark picker (`_value_at`) used floor-fraction over
the image extent — so on the SAME canvas, hovering a boundary cell and
dropping a remark there reported DIFFERENT values. Separately, the hover
unit was hard-coded to the channel unit (`result.unit`, e.g. 'g') even in
dB mode, where the matrix already holds dB numbers.

## Lesson
Two coupled traps when porting an mpl canvas's readout to pg. (1) dB-mode
readouts must label the value `'dB'`, not the channel unit — the display
matrix is dB, so `result.unit` is a unit error (mpl parity:
`SpectrogramCanvas._on_motion` / `_format_remark_label`,
`unit = 'dB' if amplitude_mode=='amplitude_db' else (result.unit or '')`).
Pin `amplitude_mode` as an instance field in `plot_result`, not just a
local. (2) When one value-picker (`_value_at`) is shared by a mode that
HAS axis arrays (slice: argmin over `result.times/frequencies` is the
correct, axis-grounded cell) and a mode that does NOT (Order: only an
extent → floor-fraction), do NOT flip the global picker to argmin to
unify with hover — that silently shifts Order's annotation values and
breaks its floor-fraction tests. Make the picker RESULT-AWARE: argmin when
`self._result is not None`, floor-fraction otherwise. Floor-fraction and
argmin-nearest coincide in cell interiors but diverge in the upper half of
each cell (argmin snaps to the nearest bin VALUE, which sits at the cell's
lower edge under `imshow(origin='lower')`), so the desync only surfaces on
boundary cells — invisible in a midpoint smoke test.

## How to apply
When a hover/cursor readout and an annotation/remark on the same canvas
must agree, route both through ONE cell-picker helper, and make that
helper branch on whether the axis arrays exist rather than forcing every
caller onto one mapping. Verify with a test that (a) searches for a
coordinate where floor-fraction and argmin DISAGREE and asserts that
divergence as a precondition, then asserts hover-value == remark-value
there, and (b) asserts the dB-mode readout trailing token is `' dB'` (not
`' g'`) and the linear-mode token is the channel unit. Compare the
remark's full-precision value formatted with the SAME `%.4g` as the hover
pill, not raw floats, or the assert fails on a rounding artifact.
