---
role: pyqt-ui
tags: [pyqtgraph, tick-density, set-tick-density, inspector-contract, unit-mismatch, visual-verification]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
PgHeatmapCanvas's skeleton implemented `set_tick_density(x, y)` as pg
density factors (0.2–5.0), but the Inspector contract emits integer
tick COUNTS (PersistentTop spinboxes x 3–30 / y 3–20, defaults 10/10 —
the values mpl fed into `MaxNLocator(nbins=...)`), so counts clamped to
max and the knob silently died.

## Lesson
`set_tick_density(x, y)` is a project-wide contract in tick COUNTS,
and the count→density conversion (x_n/10.0, y_n/6.0, clamp
[0.35, 3.0]) lives INLINE in `TickDensityController`
(pg_canvas/tick_density.py:69/:123, backref-bound) — it is not
importable, so each new pg canvas re-implements it and can drift.
Also, pg `AxisItem.tickSpacing` quantizes to nice 1/2/5 steps, so
mid-range densities (e.g. 0.5 vs 1.33) often render IDENTICAL ticks at
typical sizes; only extremes visibly differ.

## How to apply
Any new pg canvas exposing `set_tick_density` must accept counts and
mirror the tick_density.py conversion (or a shared helper once one is
extracted). Verify the knob visually at extreme counts (3,3 vs 30,20)
— adjacent values rendering identically is step quantization, not a
dead knob.
