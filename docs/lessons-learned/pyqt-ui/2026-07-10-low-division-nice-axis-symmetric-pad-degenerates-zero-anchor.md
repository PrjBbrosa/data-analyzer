---
role: pyqt-ui
tags: [tick-scale, nice-ticks, padding, zero-baseline, sparkline, live-cards, frame-to-nice, low-division, axis-readability, cockpit]
created: 2026-07-10
updated: 2026-07-10
cause: insight
supersedes: []
---

## Context
Cockpit live-card A-4 gives each sparkline a compact 3-label y axis via
`_spark_scale(ymin, ymax)` → `_frame_to_nice(lo, hi, 2)` (only 2 divisions =
bottom/mid/top). The plan spelled the pipeline as "min-span expand → **5–10%
symmetric padding** → `_frame_to_nice(.., 2)`". Implemented literally, a
zero-anchored signal `0..2360` rpm rendered as a half-empty `[-3000, 0, 3000]`
axis with the trace crushed into a thin band — the exact readability
regression A-4 exists to fix.

## Lesson
Under a *low-division* nice-tick grid, symmetric padding that pushes the low
bound even slightly below a natural zero baseline is catastrophic: `pad`
sends `lo` to `-141.6`, then `_frame_to_nice` floors it a **whole nice-step**
below zero (`floor(-141.6/1500)*1500 = -1500`), and the guard loop must then
escalate `per_div` (1500→2000→2500→3000) so `bottom + n·per_div` can reach the
top — yielding `[-3000, 0, 3000]`. With only 2 divisions there is no room to
absorb the floor slack, so a tiny negative pad blows the whole frame up. The
fix is NOT a smaller pad (any negative-crossing pad triggers it): pad the real
data bounds but **clamp the low bound back to 0 for non-negative data**, route
flat/near-constant signals through a value-aware `min_span =
max(1.0, |center|·0.02)` regime, and let `_frame_to_nice`'s own floor/extend
supply the remaining headroom while keeping the baseline on the data. That
gives `0..2360 → [0, 1200, 2400]`, `-50..50 → [-60, 0, 60]`, constant
`54.30..54.34 → [53.6, 54.4, 55.2]` (span 1.6, not collapsed).

## How to apply
When a spec says "add N% padding then snap to nice ticks" for a compact axis
with few divisions (2–3), do NOT feed a symmetric-padded `lo` across a natural
zero baseline into the fitter — clamp the baseline (or anchor the floor to the
data span) first. Verify with a zero-anchored range (`0..2360` must give
`[0, 1200, 2400]`, never `[-3000, 0, 3000]`) AND a near-constant range (span
must stay ≥ the min-span floor). Sibling nice-tick pitfall (over-fine step on
min-gap collision → reject, don't thin):
[[2026-06-17-bottom-tick-fitter-reject-overfine-not-thin]]. Shared math lives
in `mf4_analyzer/ui_kit/ticks_math._frame_to_nice`.
