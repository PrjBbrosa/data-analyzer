---
role: signal-processing
tags: [cache-key, fallback, delegate, shadow-implementation, invalidation, unified-entry-point, dict-get-none-trap, auto-nfft]
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
entries.  A second regression (whole-branch audit) occurred after the fix
switched to delegating: in auto-nfft mode `get_params()` emits
`nfft=None, nfft_effective=None` (both keys present, values None); the primary
key function does `int(p.get('nfft_effective', p.get('nfft')))` — the key is
present so `.get()` returns `None` (not the default), giving `int(None)` →
`TypeError`.

## Lesson
When a secondary code path (fallback, error-recovery, early-exit) needs to
produce the same cache key as the primary path, it MUST call the primary key
function — not hand-build a parallel dict.  A parallel dict is a shadow
implementation: it diverges silently on any future field addition to the primary.
Additionally: before passing the input dict to the primary function, the fallback
must resolve any intentionally-None values that the primary cannot handle.
`dict.get(key, default)` returns `None` when the key exists with value `None`
— the default is only used when the key is ABSENT.  The fix is to patch the
dict at the call-site only, never inside the primary function body (which
expects already-resolved inputs on the happy path).

## How to apply
When writing a fallback branch that delegates to a primary key function: (1) call
the primary, do NOT construct a new dict; (2) patch any None-valued inputs that
the primary cannot handle (use `or`-chain: `nfft_effective or nfft or nfft_preview`)
in a shallow copy dict before passing; (3) never alter the primary function body to
accept None — it will silently weaken the primary path's validation.  When writing
cache-invalidation logic: create one named helper that clears every cache for a
resource, then grep all "compute input changed" call sites and route them through it.
