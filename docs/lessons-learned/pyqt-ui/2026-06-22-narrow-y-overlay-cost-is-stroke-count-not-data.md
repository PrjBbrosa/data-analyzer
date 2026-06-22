---
role: pyqt-ui
tags: [pyqtgraph, perf, overlay, envelope, bucket-count, narrow-y, raster-fill, y-clip, time-domain, density-gate]
created: 2026-06-22
updated: 2026-06-22
cause: rework
supersedes: []
---

# Narrow-Y overlay paint cost is raster fill linear in envelope BUCKET count, not data volume — Y-clip is a no-op, bucket-cap is the lever

## Context
Time-domain overlay of 6 ~129.5 kHz acceleration channels: zooming Y to a
tiny span while X is zoomed in turns each envelope bucket's min/max pair into
a full-height vertical stroke spanning the canvas. Measured offscreen
`QWidget.grab()` medians: full-X/wide-Y 13 ms vs narrow-Y/X-zoom 58 ms — yet
displayed point count was essentially CONSTANT (~20k) across both. A spec
proposed clipping the displayed envelope to the visible Y range as the fix.

## Lesson
In this regime the paint cost is RASTER FILL, linear in the NUMBER of vertical
strokes (= envelope bucket count), and independent of data volume (~constant
displayed pts, 4–5× cost swing). Clipping ±large amplitudes into the narrow Y
window is a no-op for perf: on-screen strokes stay full-height and Qt already
clips off-screen segments, so clipping changes neither stroke count nor
on-screen height. The only lever that scales cost down ~linearly is reducing
the bucket count (measured 58 → 30 → 16 ms as buckets drop 19932 → 8400 →
4200). Because overlay aux ViewBoxes fully overlap at one full-plot rect, all
curves repaint as one region, so cap per-curve buckets by channel count:
`min(pixel_width, int(_AA_OVERLAY_SEGMENT_OFF * K / (2*curve_count)))` (×2 = ~2
envelope samples/bucket). Subplot/single keep full `pixel_width` — disjoint
short rows never hit the full-height-stroke wall. This is a DIFFERENT cost
axis than the DeviceCoordinateCache/AA-compositing lesson (that was AA raster
cost); here AA is already off and the wall persists.

CAP-SIZING TRAP (this is the K): a bare `// (2*curve_count)` makes the SUMMED
displayed-point count `≈ 2 × cap × N ≈ _AA_OVERLAY_SEGMENT_OFF` — i.e. it lands
AT the AA-off threshold, and integer truncation can dip it BELOW. But the AA
quality gate drops AA only on `metric > off_budget` (strict), so a sum
at-or-below 7000 silently re-enables the expensive AA compositing in exactly
the dense overlay the cap is meant to accelerate (self-defeating). Multiply the
cap by `K = _OVERLAY_BUCKET_BUDGET_MULT = 1.3` so the sum sits ~1.3× the
threshold (~9098 pts at 7000) and AA stays reliably OFF across 2..8 channels,
while buckets stay far below `pixel_width` (most of the speedup survives). N=2
on a wide canvas is pixel-width-bound (cap > pixel_width) and rides just above
the threshold without the cap biting — still AA OFF, and 2 curves is not the
dense case anyway.

## How to apply
When an overlay/dense-stroke pyqtgraph plot is slow but the displayed-point
count is flat across fast/slow cases, suspect per-stroke raster fill, not data
volume or AA — cap the envelope bucket count (gate to overlay only, key it off
the same constant the AA density gate uses) and prove it with before/after
`grab()` medians on real data, not a Y-clip. Feed the same effective width
into the refresh cache key (`_quantize_range_key`) or a stale full-width
envelope survives the change.
