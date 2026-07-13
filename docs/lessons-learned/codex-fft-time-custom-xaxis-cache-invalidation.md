---
id: codex-fft-time-custom-xaxis-cache-invalidation
status: active
owners: [codex]
keywords: [fft_time, cache, custom_xaxis, invalidation, analysis_cache]
paths: [mf4_analyzer/ui/main_window/window.py, mf4_analyzer/ui/main_window/_fft_time_mixin.py, tests/ui/test_task4_cache_invalidation.py]
checks: [rg -n "_fft_time_cache", tests/ui/test_task4_cache_invalidation.py]
tests: [test_apply_custom_xaxis_invalidates_fft_time_analysis_cache]
---

# FFT-vs-Time Custom-X Cache Invalidation

Trigger: Change a display control whose semantics are absent from the
FFT-vs-Time compute key, especially custom X-axis selection.

Past failure: `_apply_xaxis` cleared only the retired legacy LRU while
`do_fft_time` read `analysis_caches['fft_time']` first, allowing a stale result
to render after a custom X-axis change.

Rule: Route every cache invalidation through the actual active result store.
When a control changes FFT-vs-Time display semantics outside the key, clear the
whole FFT-vs-Time section cache unless a narrower, proven-safe scope exists.
Do not use a legacy-store clear as evidence that the primary cache is invalid.

Verification: Add or run
`test_apply_custom_xaxis_invalidates_fft_time_analysis_cache`, then audit
`rg -n "_fft_time_cache" mf4_analyzer tests` after legacy retirement.
