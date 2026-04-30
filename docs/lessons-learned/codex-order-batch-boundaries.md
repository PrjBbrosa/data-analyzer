---
id: codex-order-batch-boundaries
status: active
owners: [codex]
keywords: [order, batch, preset, one_sided_amplitude, AnalysisPreset, BatchRunner, BatchSheet, current_single, free_config, gui-free]
paths: [mf4_analyzer/signal/order.py, mf4_analyzer/signal/fft.py, mf4_analyzer/batch.py, mf4_analyzer/ui/drawers/batch/*, mf4_analyzer/ui/main_window.py]
checks: [rg -n one_sided_amplitude, rg -n AnalysisPreset, rg -n BatchRunner]
tests: [tests/test_batch_runner.py, tests/ui/test_batch_input_panel.py]
---

# Codex Order Batch Boundaries

Trigger: Load for order-analysis changes, batch-runner work, batch preset UI, or anything touching `mf4_analyzer/signal/order.py`, `mf4_analyzer/batch.py`, or the batch drawer.

Past failure: Order and batch work regressed when it invented a parallel FFT/window scaling path, mixed GUI concerns into batch execution, or supported only one of the user's two expected batch entry modes.

Rule: Reuse `mf4_analyzer/signal/fft.py` helpers such as `get_analysis_window` and `one_sided_amplitude`, keep `BatchRunner` GUI-free, model task intent in `AnalysisPreset`, preserve tuple-returning public compatibility where it exists, and support both current-single reuse and free-config flows when adding batch preset behavior.

Verification: Grep the touched order and batch paths for canonical FFT helper usage, confirm UI shells remain thin around `BatchRunner`, and run focused batch/order tests before broader suites when behavior changes.
