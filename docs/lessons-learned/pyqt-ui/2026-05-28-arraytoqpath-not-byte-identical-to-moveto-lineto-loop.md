---
role: pyqt-ui
tags: [qpainterpath, arraytoqpath, pyqtgraph, perf, vectorize, geometry-parity, nan-gap, singleton-marker]
created: 2026-05-28
updated: 2026-08-09
cause: insight
supersedes: []
---

## Context
Replacing a per-point `QPainterPath.moveTo/lineTo` loop with the
C-level `pyqtgraph.functions.arrayToQPath(x, y, ...)` cut the pyqtgraph
TimeDomain pan P50 from 10.7 ms to ~0.74 ms (14×), but `arrayToQPath`
is NOT byte-identical to the hand loop: `connect='all'` bridges NaN
gaps with a spurious line, `connect='finite'` backfills non-finite
samples with their neighbour (extra duplicate elements) and drops
single-point chunks, and `connect='all'` on a lone finite sample
returns `elementCount()==0` where the loop emitted a bare `moveTo`
(count 1).
The same geometry rule applies one layer up to `PlotDataItem`: a finite
sample isolated by NaN gaps (or an only-DC linear spectrum) has no segment to
stroke, so a logically valid result can render with zero ink.

## Lesson
`arrayToQPath` only reproduces a `moveTo`/`lineTo` polyline exactly in
the all-finite, n>=2 case (then it matches: 1 MoveTo + N-1 LineTo, same
coords/order). For byte-identical visual output you must gate the
vectorized build to that case and route NaN-gap and single-point inputs
through the original interpreted loop. Pass `finiteCheck=False` only
after you have proven finiteness yourself, and `np.ascontiguousarray(...,
dtype=float64)` the slices because a view of a larger buffer is not
C-contiguous.
For display curves, keep line rendering for runs of length at least two and
add marker items only for finite singleton runs. A marker on every sample
changes the visual contract and render cost; a full-length all-NaN scatter
also triggers pyqtgraph `nanmin`/`nanmax` warnings.

## How to apply
When vectorizing a `QPainterPath` builder for perf, first probe both the
old loop and `arrayToQPath` (`connect='all'` and `'finite'`) on the SAME
small inputs — all-finite, single NaN gap, double NaN, leading NaN,
single point, empty — and diff `elementCount()` + every `(type, x, y)`
tuple. Keep the loop as a named fallback for any case that diverges, and
lock the parity with a regression test asserting the actual element
coords (not "looks similar"). Verify the win with the END-TO-END perf
test, not a micro-bench.
For `PlotDataItem`, derive singleton masks from contiguous finite runs, feed
scatter items finite singleton coordinates only, and test that multi-point
runs create no markers, NaN gaps are not bridged, and zero-singleton inputs
produce no all-NaN scatter warnings.
