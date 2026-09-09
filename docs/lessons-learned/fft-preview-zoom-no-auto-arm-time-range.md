---
id: fft-preview-zoom-no-auto-arm-time-range
status: active
owners: [codex]
keywords: [fft, time-range, preview, checkbox, set_range_from_span, view-only]
paths:
  - mf4_analyzer/ui/main_window/window.py
  - mf4_analyzer/ui/inspector_sections/persistent_top.py
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
checks: []
tests:
  - tests/ui/test_inspector.py
  - tests/ui/test_analysis_time_range_intent.py
  - tests/ui/test_analysis_multiview_integration.py
---

# FFT Preview Zoom Is View-Only

Trigger: Changing FFT time-preview pan/zoom wiring, shared `chk_range`
behavior, or `_on_fft_preview_range_changed`.

Past failure: Preview zoom used to write Inspector start/end (and once
auto-checked「使用选定时间范围」). Users thought a camera gesture had
selected a compute window. The later “draft via `set_range_values`”
compromise still minted a fake user edit.

Rule: Preview pan/zoom is camera-only. Do not call `set_range_values` or
`set_range_from_span`. Do not write `pane.time_range` or create a
controller draft. Manual start/end commit is the only draft path.
`set_range_from_span` stays for explicit arming (compute confirm). Keep
`range_enabled()` / uncheck → full / preview-reset-on-uncheck.

Verification:
```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_inspector.py::test_main_window_fft_preview_path_does_not_auto_check \
  tests/ui/test_inspector.py::test_fft_preview_zoom_does_not_update_pane_time_range_when_checked \
  tests/ui/test_inspector.py::test_fft_uncheck_range_clears_pane_and_refreshes_preview \
  tests/ui/test_analysis_time_range_intent.py::test_fft_preview_pan_does_not_create_draft_or_change_enabled \
  -q
```
