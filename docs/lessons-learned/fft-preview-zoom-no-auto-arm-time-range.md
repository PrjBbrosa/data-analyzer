---
id: fft-preview-zoom-no-auto-arm-time-range
status: active
owners: [codex]
keywords: [fft, time-range, preview, checkbox, set_range_from_span, manual-check]
paths:
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/inspector_sections/persistent_top.py
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
checks: []
tests:
  - tests/ui/test_inspector.py
  - tests/ui/test_analysis_multiview_integration.py
---

# FFT Preview Zoom Does Not Auto-Arm Time Range

Trigger: Changing FFT time-preview pan/zoom wiring, shared `chk_range`
behavior, or `_on_fft_preview_range_changed`.

Past failure: Preview zoom called `set_range_from_span`, force-checking
「使用选定时间范围」so the same Inspector control behaved unlike Time-Domain
(manual check). Users could not draft a window without arming compute, and
unchecking did not restore a full-span preview.

Rule: FFT preview pan/zoom only `set_range_values` (draft start/end). Write
`pane.time_range` only while `range_enabled()`. Keep `set_range_from_span` for
explicit arming (FRF「取时域范围」, compute confirm). 「全部」is view-all only
and must not call `set_range_from_span`. On FFT checkbox toggle, capture
then refresh the time preview; on uncheck also reset preview X to data extents.

Verification:
```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_inspector.py::test_main_window_fft_preview_path_does_not_auto_check \
  tests/ui/test_inspector.py::test_fft_preview_zoom_updates_pane_time_range_when_checked \
  tests/ui/test_inspector.py::test_fft_uncheck_range_clears_pane_and_refreshes_preview \
  tests/ui/test_analysis_multiview_integration.py::test_fft_time_preview_drag_updates_analysis_time_range \
  -q
```
