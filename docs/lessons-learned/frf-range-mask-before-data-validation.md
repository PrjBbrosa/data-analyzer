---
id: frf-range-mask-before-data-validation
status: active
owners: [codex]
keywords: [frf, time-range, preflight, alignment]
paths:
  - mf4_analyzer/batch_compute.py
  - mf4_analyzer/ui/main_window/_frf_mixin.py
checks: []
tests:
  - tests/test_batch_frf_export.py
  - tests/ui/test_frf_main_window.py
---

# Validate FRF Data After Applying The Shared Physical-Time Mask

Trigger: Changing FRF range selection, timebase validation, or GUI/Batch
preflight order.

Past failure: GUI and Batch validated the complete time arrays before applying
the requested physical-time range, so a sampling jitter outside an otherwise
valid selection blocked the FRF task.

Rule: After basic array shape and dtype checks, build one mask from the real
physical time axis, apply it consistently to time/input/output, and validate
finite values, strict increase, uniformity, alignment, and segment sufficiency
on the selected arrays. Full-range mode naturally validates the complete data.

Verification: Keep paired regressions proving that jitter outside the selected
range is ignored while the same jitter inside the selected range is rejected,
in both GUI and Batch adapters.
