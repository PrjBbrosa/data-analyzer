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

# Confirm Controller Draft Before Compute

Trigger: Wiring analysis compute entry points (`do_fft` / `do_fft_time` /
`do_order_time` / `do_frf`) or shared time-range checkbox semantics.

Past failure: After preview zoom drafted start/end without checking, a
compute click silently used the full span while the inspector still
showed a local window. The follow-up 1% plotted-extent heuristic then
false-prompted or swallowed a 1-hour-minus-1-second cut.

Rule: Before `_capture_active_analysis_view` on those four user compute
entries, flush pending spin edits and query the controller draft for the
frozen panes (matching source signature). Do not infer locality from a
1% camera/spin heuristic. Ask once; default button is 取消; the local
button is「用选定范围」(disabled when the draft is invalid). Full span
uses `ActionRole`, never `DestructiveRole`. Cancel submits nothing.
Project-restore auto-recompute and Batch do not prompt.

Verification:
```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/ui/test_analysis_time_range_confirm.py -q
```
