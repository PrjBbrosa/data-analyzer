---
role: pyqt-ui
tags: [pyqtgraph, perf, devicecoordinatecache, viewbox, overlay, end-to-end, repaint, density-gate, two-budget]
created: 2026-05-31
updated: 2026-05-31
cause: insight
supersedes: []
---

## Context
Fix D of the overlay-AA interaction work set
`QGraphicsItem.DeviceCoordinateCache` on every `PlotCurveItem` when idle
AA flips on, to stop hover/`draw_idle` repaints re-rasterizing the
overlaid AA curves. An end-to-end repaint-frame measurement (real
`GraphicsLayoutWidget.grab()` of a 5-channel × 6000-pt plot, offscreen
raster) showed the cache gives subplot mode a 15× win (11.7 ms → 0.78 ms)
but ZERO win for overlay mode (20.9 ms → 22.6 ms, slightly worse).

## Lesson
`DeviceCoordinateCache` only pays off when each cached item owns a
small, stable, NON-overlapping device rectangle. In this canvas's
overlay mode every channel gets its own aux ViewBox but
`_sync_overlay_aux_viewboxes` sets them all to the X-master's FULL plot
rect, so the N curves' caches are N full-size, fully-overlapping bitmap
layers that must be alpha-composited every frame — the compositing cost
cancels the rasterization saving. Subplot mode wins because its N
ViewBoxes occupy disjoint short rows. So the cache helps exactly the
case that was already fast (single curve / separated rows) and not the
overlay-stack case it was added to fix. A `cacheMode()==DeviceCoordinateCache`
state assertion is necessary but NOT sufficient evidence that the frame
got faster.

## How to apply
Before claiming a `setCacheMode(DeviceCoordinateCache)` perf fix, time
the END-TO-END repaint frame (`widget.grab()` or a real paint pass) with
cache ON vs OFF for the actual layout, and first check whether the
cached items overlap: `len({id(it.getViewBox()) for it in items})` vs
their `sceneBoundingRect()` overlap. Fully-overlapping full-size layers
get no benefit (or a regression). If the target is an overlay/shared-rect
stack, the cache must be gated to that geometry or replaced by a
single-layer strategy (one cached composite, OpenGL, or fewer/smaller
cached rects) — not applied per fully-overlapping item.

## Follow-up (2026-05-31): the cache asymmetry forces a TWO-budget gate

Acting on the measurement above, the cache was gated to subplot only
(`setCacheMode(DeviceCoordinateCache)` iff `not self._overlay_mode`;
`NoCache` unconditionally on disable so no stale cache survives a mode
swap). That asymmetry then propagates into the idle-AA density gate: a
SINGLE density budget cannot serve both modes, because subplot is now
cached (an AA-on frame is ~0.3–0.9 ms at any width, measured 5×6000
subplot 25.3 ms → 0.86 ms) while overlay is uncached and its AA cost is
LINEAR in the per-frame drawn-point SUM (measured AA-on-minus-AA-off
delta: sum 4000 → +10 ms, 6000 → +17 ms, 9000 → +31 ms, 15000 → +69 ms).
A subtle trap also surfaced: overlay's per-channel aux ViewBoxes are
DISTINCT objects (just geometrically overlapping), so a per-ViewBox-MAX
density metric undercounts overlay to ≈ one curve — the metric MUST be
the SUM across all curves in overlay, and the MAX over rows in subplot.
The landed gate therefore branches on `_overlay_mode` for BOTH the metric
(sum vs max) AND the threshold pair: tight overlay budget (ON=5000 /
OFF=7000, so dense ≥3-curve overlays gate off) and generous subplot
budget (ON=10000 / OFF=12000, so a 4K single curve's ~7700-pt envelope
still gets AA, since it is cached and cheap).

## How to apply (follow-up)

When a perf fix is gated to one geometry (here: cache subplot only), any
downstream "cost budget" that was a single number probably has to split
along the same axis — the cached branch can afford a generous ceiling,
the uncached branch needs a tight one keyed to the real per-frame cost
metric. And before reusing a per-item/per-ViewBox aggregation as a "cost"
metric, check whether the items you are grouping by are distinct-but-
overlapping (overlay aux ViewBoxes): if they repaint as one region, the
metric must SUM them, not MAX over the (misleading) groups.
