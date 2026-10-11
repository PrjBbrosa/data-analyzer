---
id: analysis-cache-is-not-result-publication-authority
status: active
owners: [codex]
keywords: [analysis, cache, draft, compute, display-refresh, restore]
paths: [mf4_analyzer/ui/analysis_result_state.py, mf4_analyzer/ui/main_window/_analysis_mixin.py]
checks: []
tests: [tests/ui/test_analysis_explicit_refresh_contract.py, tests/ui/test_analysis_explicit_family.py, tests/ui/test_frf_explicit_result_contract.py, tests/ui/test_analysis_project_explicit_compute.py]
---

# Cache availability does not authorize result publication

Trigger: Changing analysis parameter signals, cache restoration, display-only callbacks, project restoration, or asynchronous result admission.

Past failure: A display helper named cache-only called do_fft_time/do_order_time and computed on misses. Parameter edits published any cache hit, while display edits with a draft cache miss erased the previous graph. Source-bearing project drafts were silently computed on reopen. A narrow editor fix missed the same dialog route.

Rule: Keep draft intent separate from the session-local accepted result binding. Only explicit calculation may accept a new request, including cache hits. Refresh reads accepted keys and request source context plus current display settings. Project reopen restores intent without calculating. Validate pane identity and request revision before adopting completions; rejecting a cached completion must also restore the accepted pin set.

Verification: Exercise real editor and dialog signals, cached/uncached draft changes, display edits, View/compare restoration, project reopen and stale asynchronous completions. Assert compute counts AND result identity, labels, stale facts and pins. Run the listed focused tests; a helper name or cache-only unit assertion is insufficient.
