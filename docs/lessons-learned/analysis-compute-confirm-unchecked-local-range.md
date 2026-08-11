---
id: analysis-compute-confirm-unchecked-local-range
status: active
owners: [codex]
keywords: [time-range, checkbox, compute, confirm, fft, frf, order]
paths:
  - mf4_analyzer/ui/main_window/_analysis_mixin.py
  - mf4_analyzer/ui/main_window/_fft_mixin.py
  - mf4_analyzer/ui/main_window/_fft_time_mixin.py
  - mf4_analyzer/ui/main_window/_order_mixin.py
  - mf4_analyzer/ui/main_window/_frf_mixin.py
checks: []
tests:
  - tests/ui/test_analysis_time_range_confirm.py
---

# Confirm Unchecked Local Time Range Before Compute

Trigger: Wiring analysis compute entry points (`do_fft` / `do_fft_time` /
`do_order_time` / `do_frf`) or shared time-range checkbox semantics.

Past failure: After preview zoom only drafted start/end (no auto-check), a
compute click silently used the full span while the inspector still showed a
local window — users thought they had selected a window.

Rule: Before `_capture_active_analysis_view` on those four user compute
entries, call `_offer_analysis_time_range_before_compute`. If unchecked
start/end is a proper local subset of data extent, ask「用局部范围」/
「用全时段」/「取消」; local arms via `set_range_from_span`. Do not prompt on
project-restore auto-recompute or Batch.

Verification:
```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_analysis_time_range_confirm.py -q
```
