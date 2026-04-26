---
role: signal-processing
tags: [cache, hot-path, dead-code, envelope, monotonicity, refresh, audit]
created: 2026-04-25
updated: 2026-04-25
cause: insight
supersedes: []
---

# A cache that is reachable but unconsumed is dead code on the hot path

## Context
Phase 1 item 6 of the time-domain plot performance work plumbed a
monotonicity cache (`_is_monotonic` cached method + 5 main_window
invalidation call sites) but `_envelope`'s body still called the
module-level uncached `_is_monotonic_array(t)` on every viewport
refresh. `grep "self\._is_monotonic\b"` returned 0 hits. Two prior code
reviews verified the cache *exists* and *invalidates* correctly; neither
verified it is *consumed* on the per-frame hot path.

## Lesson
On a DSP refresh path that runs O(n) per `xlim_changed` (where n is the
full sample count), a cache that is built and invalidated but never
read is strictly worse than no cache: the `np.diff(t) >= 0` allocation
still happens every frame AND the maintenance cost of the unused cache
infrastructure is paid. The non-obvious verification step is that
"cache method exists" + "invalidation API exists" + "tests for both
pass" does not imply "cache is on the hot path". You must grep the
*consumer* — the function whose cost the cache is meant to amortize —
and confirm it routes through the cache method, not the underlying
uncached helper.

## How to apply
For any cache added to a per-frame DSP path, write the verification as
two separate checks, not one:
1. `grep <cached_method_name>` from the producer side (does the cache
   method exist and does invalidation reach it?).
2. `grep <uncached_helper_name>` from the consumer side (does the hot
   path call the uncached helper directly? if yes, the cache is dead
   code regardless of how clean the producer side looks).
Bonus: the consumer-side test should assert call counts via a
monkeypatch counter on the uncached helper (e.g. wrap
`_is_monotonic_array` to increment a box, then call the refresh entry
point N times across distinct viewports and assert the counter is
bounded by the number of plot builds, not by N). Smoke tests that only
exercise `cache_method(args)` directly will pass while the production
caller bypasses the cache entirely.
