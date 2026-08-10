---
id: codex-analysis-mode-entry-apply-view-params
status: active
owners: [codex]
keywords: [fft, mode-entry, apply_params, analysis-view, source-isolation, inspector]
paths: [mf4_analyzer/ui/main_window/window.py, mf4_analyzer/ui/main_window/_analysis_mixin.py, tests/ui/test_analysis_source_scope.py, tests/ui/test_analysis_multiview_integration.py]
checks: [rg -n "apply_params=False|_capture_active_analysis_view\\('fft'\\)" mf4_analyzer/ui/main_window/window.py]
tests: [tests/ui/test_analysis_source_scope.py -k mode_switch, tests/ui/test_analysis_multiview_integration.py -k weighting_drift]
---

# Codex Analysis Mode Entry Applies View Params

Trigger: Load when changing analysis mode entry (`_on_mode_changed` / `_enter_fft_mode`) or any path that can capture live Inspector params into an analysis View.

Past failure: Entering FFT with `apply_params=False` then `_capture_active_analysis_view` let live Inspector drift overwrite the destination View's params (review F2). Cross-section edits while away looked like intentional View state.

Rule: On analysis mode entry, apply the target View's params/sources/range to live controls first. `_enter_fft_mode` may sync navigator checkboxes into focused pane sources, but must not capture live params back onto the View. Live == state after entry; canvas reuse stays signature-based.

Verification: Assert mode-switch restores View nfft over poisoned live values; returning from fft_time after live weighting poison keeps spectrum and restores View weighting.
