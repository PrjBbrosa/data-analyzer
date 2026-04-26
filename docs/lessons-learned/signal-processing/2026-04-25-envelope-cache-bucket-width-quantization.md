---
role: signal-processing
tags: [envelope, downsample, cache, viewport, time-domain]
created: 2026-04-25
updated: 2026-04-25
cause: insight
supersedes: []
---

# Bucket-width quantization is the right key granularity for an envelope LRU cache

## Context
While implementing viewport-aware min/max envelope downsampling for
`TimeDomainCanvas`, the spec asked for an LRU cache keyed by
`(data_id, channel_name, quantized_xlim, pixel_width)`, with
quantization in the "0.5%-1% of view span" range. During continuous
pan, two consecutive frames typically differ in xlim by far less than
that, so without quantization every frame misses.

## Lesson
The non-obvious bit is that the right quantum is **one bucket
width = (x1 - x0) / pixel_width**, not a fixed percentage. The
envelope output literally cannot change unless xlim moves by more than
one pixel — sub-pixel jitter selects the same set of buckets and
emits the same min/max samples. Snapping the cache key to integer
multiples of the bucket width is therefore both the *coarsest*
quantization that produces a bit-identical envelope, and a numeric
tie-in to the same constant that drives bucket placement. A fixed
percentage (0.5%) is either coarser than necessary at narrow zoom
levels or too tight at wide-zoom levels.

## How to apply
When caching any viewport-quantized result, derive the quantum from
the same parameter that drives the result's discretization (here,
`pixel_width`). Avoid magic percentages — they hide a coupling and
desynchronize when one side changes.
