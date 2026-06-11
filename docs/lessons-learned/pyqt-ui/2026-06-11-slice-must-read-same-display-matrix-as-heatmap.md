---
role: pyqt-ui
tags: [pyqtgraph, heatmap, slice, spectrogram, display-space, vmin-vmax, db, single-source-of-truth, plot-or-update-heatmap]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
PgHeatmapCanvas (M7) gained an FFT-vs-Time frequency-slice row that must
plot the SAME display-space (dB) values as the column under the selected
frame, while the shared `plot_or_update_heatmap` already has its own
internal `amplitude_mode='amplitude_db'` conversion + auto-level branch.

## Lesson
`plot_result` does the dB conversion itself (memoized
`(id(result), db_reference)`), then hands the ALREADY-converted matrix to
`plot_or_update_heatmap` with `amplitude_mode='amplitude'` plus EXPLICIT
`vmin`/`vmax`. Two coupled reasons: (1) `plot_or_update_heatmap`'s linear
branch only fills `vmin`/`vmax` from `nanmin/nanmax` when they are `None`,
so passing explicit values makes them survive — but passing
`amplitude_mode='amplitude_db'` would re-derive the matrix AND the levels
(`vmax` defaults to `0.0`, not your ceiling), silently overriding the
caller's window; (2) the slice curve reads `self._matrix_disp[:, idx]`,
and `plot_or_update_heatmap` stores whatever matrix it was handed into
`_matrix_disp` — so the slice is display-space-correct ONLY because the
heatmap was handed the display matrix, not the raw amplitude. Let the
heatmap do the dB conversion instead and the slice would plot dB while the
image plots... also dB, but recomputed against a different `nanmax`
reference — a subtle desync, not an obvious crash.

## How to apply
When a secondary 1D view must mirror a 2D pg heatmap's exact rendered
values, convert ONCE in the caller, hand the display matrix + explicit
`vmin`/`vmax` to `plot_or_update_heatmap` with `amplitude_mode='amplitude'`,
and re-pin `self._matrix_disp` to that same matrix so the slice/remarks
read identical values. Never split the dB/level derivation across the
caller and the shared heatmap method. Verify by asserting
`slice_curve.getData()[1] == _matrix_disp[:, idx]` AND that
`_img.getLevels()` equals the explicit window (not the data's
nanmin/nanmax) — the second assert is what catches a re-derived-levels
regression.
