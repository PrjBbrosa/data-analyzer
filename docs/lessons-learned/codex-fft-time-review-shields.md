---
id: codex-fft-time-review-shields
status: active
owners: [codex]
keywords: [fft-time, fft_time, FFTTimeWorker, SpectrogramResult, amplitude, cache-key, clipboard, inspector, signal_changed]
paths: [mf4_analyzer/ui/main_window.py, mf4_analyzer/ui/inspector_sections.py, mf4_analyzer/ui/canvases.py, tests/ui/test_inspector.py, tests/ui/test_nonuniform_fft_full_flow.py]
checks: [rg -n fft_time, rg -n SpectrogramResult, rg -n _fft_time_cache_key]
tests: [tests/ui/test_inspector.py]
---

# Codex FFT Time Review Shields

Trigger: Load for FFT-vs-Time implementation or review work, especially signal plumbing, worker/cache behavior, inspector controls, export, or validation-report review.

Past failure: Reviews missed FFT-vs-Time risks when they checked widget existence but not candidate plumbing, trusted stale validation summaries, or forgot shape/cache/worker contracts established by live code.

Rule: Verify `fft_time_ctx` signal-candidate wiring, cache invalidation hooks, `FFTTimeWorker` as a `QObject`, display-only fields excluded from cache keys, and `SpectrogramResult.amplitude` shape before approving changes. Treat final validation reports as stale until fresh test output and per-file counts reconcile.

Verification: Grep `_update_combos`, `fft_time_signal_changed`, `_fft_time_cache_key`, export methods, and `SpectrogramResult`; for export helpers check whether `(freq_bins, frames)` data must be transposed before long-format output.
