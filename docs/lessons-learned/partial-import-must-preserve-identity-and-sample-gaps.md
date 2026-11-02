---
id: partial-import-must-preserve-identity-and-sample-gaps
status: active
owners: [codex]
keywords: [import, diagnostics, WWT, CSV, TDMS, ZFD, nonfinite, batch]
paths: [mf4_analyzer/io/, mf4_analyzer/batch_preprocess.py, mf4_analyzer/signal/]
checks: [git diff --check]
tests: [tests/test_import_diagnostics.py, tests/test_tabular_recovery.py, tests/signal/test_analysis_missing_samples.py, tests/ui/test_import_diagnostics.py]
---

# Partial Imports Preserve Identity And Sample Gaps

Trigger: Relaxing file-import rejection or carrying partial-import diagnostics through GUI, project reload, or Batch.

Past failure: A zero-length WWT time record rejected a file whose measurement blocks were complete. Separately, table cleaning silently interpolated invalid timestamps and signal gaps, while Batch finite cleanup could delete gaps before a new spectral validation guard saw them.

Rule: Recover only at verified record boundaries; preserve physical indices and time ownership. Distinguish complete, warning, partial, and unknown diagnostics, and carry them to every consumer. Preserve missing samples and original time coordinates; validate the selected computational interval before any cleanup can erase evidence. Never certify pandas datetime integers or milliseconds as seconds. Existing legacy diagnostics may be suppressed only when a structured issue actually covers them.

Verification: Synthetic owner tests must cover zero-record references, invalid table time, preserved gaps, units, and channel identity. Exercise the real GUI loader and BatchRunner through result/manifest paths, including a gapped calculation that fails while retaining import facts. A core FFT exception alone does not prove end-to-end protection.
