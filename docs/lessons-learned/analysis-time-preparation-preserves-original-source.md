---
id: analysis-time-preparation-preserves-original-source
status: active
owners: [codex]
keywords: [time-axis, fft, fft-time, frf, source-identity, effective-facts]
paths: [mf4_analyzer/analysis_time_axis.py, mf4_analyzer/ui/main_window/]
checks: [original timestamp equality, candidate and worker cache-key equality]
tests: [tests/test_analysis_time_axis.py, tests/ui/test_analysis_time_isolation.py]
---

# Analysis Time Preparation Preserves Original Source

Trigger: Changing analysis time reconstruction, sampling settings, original Plot timing, or effective-facts provenance.

Past failure: FFT/FRF preflight rewrote shared FileData.time_array and replotted Plot. Analysis processing therefore changed other views, while a global chip incorrectly called index-based reconstruction resampling.

Rule: Crop on original physical time before preparing an analysis grid. Preserve the crop origin and signal values; never mutate shared source time or sampling metadata for an analysis. Verify FRF pair alignment before assigning a common grid. Carry processing facts with the result through caches, not through source state, and use the same effective rate for lookup and worker dispatch. Reconstruction is not interpolation resampling.

Verification: Assert exact original arrays before/after real FFT, FFT-time and FRF jobs; verify nonzero crop origins, manual View intent round-trips, cache hits, and hidden Plot processing chips. Run the two focused test files and inspect the effective-facts card on Cocoa.
