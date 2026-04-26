---
role: signal-processing
tags: [fft, batch, chunk, memory, tracemalloc, vectorize, in-place]
created: 2026-04-26
updated: 2026-04-26
cause: insight
supersedes: []
---

# Batched FFT pipelines hold 3-4× the chunk-frames buffer transiently

## Context
While vectorizing `OrderAnalyzer._order_amplitudes_batch` with chunked
frame stacking (`_ORDER_BATCH_FRAMES = 256`), a tracemalloc test asserted
peak memory < 4× the raw chunk-frames upper bound (`BATCH * nfft * 8B`).
The chunk loop was correctly bounded, yet the assertion failed at peak
~37 MB against a 32 MB headroom because `frames`, `work = frames - mean`,
`work * window_array`, the complex `rfft` output, and `np.abs(...)` all
existed concurrently inside one call to `_order_amplitudes_batch`. This
quantization-style sibling of the envelope-cache lesson surfaced when
the implementation passed every functional test but flunked the memory
budget.

## Lesson
The non-obvious insight: a batched FFT pipeline transiently holds
roughly **3-4 buffers of chunk-frames size simultaneously** —
demeaned-windowed work, complex spectra (twice the size of float per
element), and the absolute-amplitude float buffer. A "4× chunk_budget"
headroom is therefore *just barely* enough on paper, and any extra
intermediate (separate `windowed = work * window_array` buffer) blows
through it. Two fixes apply jointly:
1. Mutate the demeaned buffer in place (`work *= window_array`) instead
   of allocating a new `windowed` array.
2. `del` references as soon as they are not needed (release `work`
   before allocating `amps`; release the complex `spectra` before
   the `amps /= nfft` chain).

These are not micro-optimizations: they bring peak memory back from
~4.5× chunk_budget to ~3× and let the chunk-budget test's headroom
contract hold.

## How to apply
When a batched DSP pipeline takes a chunk-shaped input through
`(demean → window → rfft → abs → scale)`, account for **at least
3-4× chunk_frames-bytes** of transient memory, not 1×. If a memory
assertion is set to "k× chunk_budget" with k ≤ 4, you must (a) use
in-place arithmetic between chunk-sized intermediates, and (b)
explicitly `del` the chunk-sized buffers (especially the complex
`rfft` output) before the next chunk-sized allocation. Verify with
`tracemalloc.start()` ... `get_traced_memory()` *after* test inputs
are allocated, so the input arrays do not eat your headroom.
