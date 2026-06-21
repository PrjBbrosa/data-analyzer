---
role: signal-processing
tags: [cache-key, fallback, delegate, shadow-implementation, invalidation, unified-entry-point]
created: 2026-06-21
updated: 2026-06-21
cause: insight
supersedes: []
---

# A fallback key branch that hand-builds what the primary computes is a shadow implementation

## Context
`_analysis_cache_key` had a fallback branch for the fft_time section that
constructed a params dict in-line when `_fft_time_effective_params_for_source`
returned None.  The fallback omitted `weighting` and used different nfft
resolution logic from the primary `_fft_time_analysis_cache_key`, so
A-weighted lookups always missed and the secondary invalidation paths
(`_show_rebuild_popover`, channel-editor, auto-rebuild) only cleared the legacy
LRU but left `analysis_caches['fft']` and `analysis_caches['order']` with stale
entries.

## Lesson
When a secondary code path (fallback, error-recovery, early-exit) needs to
produce the same cache key as the primary path, it MUST call the primary key
function — not hand-build a parallel dict.  A parallel dict is a shadow
implementation: it diverges silently on any future field addition to the primary.
Separately, whenever multiple call sites each need to clear a set of caches,
consolidate them into a single named entry point (e.g.
`_invalidate_all_analysis_caches_for_fid`) so adding a new cache only requires
one edit.  Leaving individual call sites to clear caches piecemeal guarantees
that a future "add cache X" PR will miss at least one site.

## How to apply
When writing a fallback branch that builds a cache key: search for the primary
key function and call it, passing the same inputs.  Do NOT construct a new dict.
When writing cache-invalidation logic: create one named helper that clears every
cache for a resource, then grep all "compute input changed" call sites and route
them through it.  The grep list must be explicit in the PR (as done in Task 4's
report), not just assumed.
