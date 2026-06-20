---
role: pyqt-ui
tags: [pyqtgraph, heatmap, colorbar, levels, z_auto, z_floor, z_ceiling, absolute-db, peak-relative, write-back, blocksignals, auto-manual-jump]
created: 2026-06-21
updated: 2026-06-21
cause: insight
supersedes: []
---

## Context

`PgHeatmapCanvas.plot_result` (FFT-vs-Time) computes an *absolute*-dB
matrix via `amplitude_to_db(amplitude, db_ref=1.0)`, where the matrix
peak is NOT 0 dB (e.g., −34.65 dB for a 0.02 Pa sine).  The auto
color-window function `_auto_db_level_window(matrix, z_floor, z_ceiling)`
returned `[peak + z_floor, peak + z_ceiling]` — treating `z_floor` as a
peak *offset*.  The manual path in the same function returned
`[z_floor, z_ceiling]` — treating them as *absolute* values.
With z_floor=−40/z_ceiling=0, auto gave (−74.65, −34.65) while manual
gave (−40, 0): a 34.65 dB shift.  Dragging the colorbar (→ manual) or
re-computing (→ auto) caused the entire image to jump by the signal's
absolute dB level.

Note: `plot_or_update_heatmap`'s own `amplitude_db` branch did NOT have
this bug because it first normalises the matrix peak to 0 dB (so peak +
z_floor == z_floor exactly).  The bug only existed in `plot_result`'s
absolute-dB path.

## Lesson

When a render path produces an *absolute*-dB matrix (peak ≠ 0), the auto
color window must be data-anchored via a fixed span:
`[peak − _AUTO_SPAN_DB, peak]`, NOT `[peak + z_floor, peak + z_ceiling]`.
After rendering, write `(vmin, vmax)` back to the inspector spins under
`blockSignals` so that toggling auto off leaves the spins holding the
*current on-screen* window — making auto→manual a zero-jump transition.
The fixed span constant must NOT be read from the spin widgets to avoid a
feedback loop.  The Order path (pre-converted dB passed as
`amplitude='amplitude'`) has the same problem at `plot_or_update_heatmap`'s
`_finite_data_bounds` fallback; fix it symmetrically in the render caller
by passing explicit `vmin/vmax` when `z_auto=True`.

## How to apply

When adding or auditing a heatmap render that uses absolute (not peak-
normalised) dB values: (1) check whether the auto-level code branches on
`z_floor/z_ceiling` — if so, replace with `[peak − FIXED_SPAN, peak]` and
store the result in `canvas._last_auto_levels`; (2) in the render caller,
after the plot call, read `_last_auto_levels` and `blockSignals`-write
the two inspector spins; (3) add an invariant test that calls
`plot_result(z_auto=True)`, reads `_last_auto_levels`, then calls again
with `z_auto=False, z_floor/z_ceiling = _last_auto_levels` and asserts
levels agree within 0.5 dB.
