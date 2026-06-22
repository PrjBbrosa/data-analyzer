---
role: pyqt-ui
tags: [pyqtgraph, perf, subplot, envelope, bucket-count, dense-channel, raster-fill, initial-bind, show-original, setvisible, time-domain]
created: 2026-06-23
updated: 2026-06-23
cause: insight
supersedes: []
---

# Subplot dense-stack bucket cap must hit the INITIAL bind, not just the refresh path; and "re-show original" was never re-computing the envelope

## Context
"重新勾选显示原始 → 卡顿" on 6 × 129.5 kHz (1.19 M-pt) subplot channels with a
low-pass overlay. The overlay narrow-Y bucket cap
(`renderer._effective_pixel_width`) covered overlay only; subplot returned full
`pixel_width`, so re-showing the 6 hidden originals repainted 6 full-height
"satin竖线墙" raster walls. Suspected cause was envelope recompute on re-show
plus a synchronous `draw()`.

## Lesson
Two findings. (1) `set_original_lines_visible(False/True)` was ALREADY a pure
`pdi.setVisible` + async `draw()` (`draw_idle` = `_glw.update()`, deferred —
not synchronous); a `positions_envelope` spy proved ZERO recompute on the
hide/show round-trip. So the +0.7 s on re-show is NOT a recompute or a blocking
draw — it is pyqtgraph regenerating + rasterizing the newly-visible curve paths
on the FIRST paint after `setVisible(True)`, i.e. the same dense raster-fill
wall, just paid lazily. The lever is fewer envelope buckets, exactly like the
overlay narrow-Y lesson, but extended to subplot for HIGH-DENSITY channels
(`source_len / pixel_width >= _SUBPLOT_DENSE_DECIMATION`) when ≥2 are stacked
(single/low-density rows keep full resolution — fidelity red line). (2) THE
TRAP: capping only inside `_refresh_visible_data` (the pan/zoom hot path) does
NOT change the FIRST painted frame, because the curve's initial `setData`
happens in `overlay_axes._bind_channel` / `_bind_companion` via
`_initial_bind_pixel_width`, and the post-build range-key gate then makes the
first `_refresh_visible_data` a no-op (key already matches). Probe proof: a
forced `_last_range_key.clear() + _refresh_visible_data()` dropped summed
displayed pts 31992→8400, but a plain `plot_time()` stayed at 31992 — the cap
silently missed the build. Fix: compute `dense_count` up-front in
`plot_channels` (store `self._subplot_dense_count`), and apply the cap in BOTH
`_initial_bind_pixel_width(handle, source_len=...)` AND the per-channel branch
of `_refresh_visible_data`. After: build summed pts 31992→10392, offscreen
first-repaint-after-toggle proxy (`viewport.repaint()` timed) 217→103 ms (≈2.1×;
on-screen Mac/Win wall ~10× the proxy but scales with the same stroke count).

## How to apply
For any "re-show / re-check makes the chart janky" pyqtgraph perf task: first
spy `positions_envelope` to rule out recompute and confirm `draw()` is async
before assuming layer A — the toggle path is often already clean and the cost is
deferred path-regen on the next paint. When a bucket-count cap must affect the
FIRST frame (not just pan/zoom), apply it at the INITIAL bind site
(`_initial_bind_pixel_width`) too, because the post-build range-key gate
no-ops the first refresh. Measure displayed-point/stroke count (deterministic,
linear with the raster wall per the narrow-Y lesson) AND the first-repaint-
after-toggle proxy — offscreen `grab()` after a settle is a cached blit and
reads ~1 ms, hiding the wall entirely; time `viewport.repaint()` on the FIRST
paint after the `setVisible` toggle instead.
