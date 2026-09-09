---
id: binary-channel-type-before-float-cast
status: active
owners: [codex]
keywords: [head-hdf, UINT32, FLOAT32, warning, signaling-nan]
paths:
  - mf4_analyzer/io/head_hdf.py
  - tests/test_head_hdf.py
checks: []
tests:
  - .venv/bin/python -m pytest tests/test_head_hdf.py tests/test_head_hdf_loader.py -q
---

# Binary Channel Type Before Float Cast

Trigger: Changing mixed-type binary demultiplexing or investigating HEAD HDF invalid-value cast warnings.

Past failure: The parser cast the full interleaved matrix from float32 to float64 before skipping unsupported UINT32 channels. Integer words resembling signaling NaNs emitted RuntimeWarning even though the offending channel was subsequently dropped.

Rule: Select supported channel slots before numerical conversion; preserve offsets, factors, sample order and the float64 output contract. Do not suppress invalid-value warnings globally: genuine FLOAT32 non-finite samples must remain observable.

Verification: Synthetic UINT32 signaling-NaN bit patterns at each channel position, zero/short scans and unequal factors parse without invalid casts; supported FLOAT32 signaling NaNs still warn. Compare supported real-file samples elementwise against the old parser and keep unsupported-channel reporting intact.
