---
id: ultraview-time-capture-ink-and-stable-digest
status: active
owners: [codex]
keywords: [ultraview, capture, preview, dense-raster, curve_count, digest, source_revision]
paths:
  - mf4_analyzer/ui/main_window/ultraview_coordinator.py
  - mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py
  - tests/ui/test_ultraview_capture.py
  - tests/ui/test_ultraview_mode_integration.py
checks:
  - rg -n "curve_count" mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py
  - rg -n "_stable_source_revision|_channel_lines|dense-raster" mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_capture.py::test_time_canvas_dense_raster_captures_when_native_curve_count_is_zero tests/ui/test_ultraview_capture.py::test_time_digest_stable_when_numpy_wrappers_churn tests/ui/test_ultraview_mode_integration.py::test_open_ultraview_captures_plotted_time_view -q
---

# UltraView Time Capture Uses Plotted Ink And Stable Digest

Trigger: Changing UltraView preview capture, `_host_has_real_result`, presentation digest, or `source_revision_for` in the time-preview path.

Past failure: Time View cards showed「尚无可用结果」even with plotted traces. Two stacked bugs: (1) emptiness used `quality_status()["curve_count"]`, which counts native-AA PlotCurveItems and is 0 once dense-raster covers them, including ordinary green plots; (2) the digest inlined `source_revision_for` ndarray `id()` values, and `to_numpy()`/`np.asarray` mint a new wrapper each call, so queued grabs always saw `current != digest` and dropped the frame.

Rule: Time emptiness is plotted channel tables (`_channel_lines` / `channel_data`) or `render_path == "dense-raster"`, not AA color and not native curve_count alone. UltraView digest must drop ndarray ids and keep size/dtype/crc so consecutive `current_digest_for` calls match for unchanged samples. Do not treat an uncomputed FFT/FRF/order View as a capture failure — missing is correct until that section has a result.

Verification: `test_time_canvas_dense_raster_captures_when_native_curve_count_is_zero`, `test_time_digest_stable_when_numpy_wrappers_churn`, and `test_open_ultraview_captures_plotted_time_view`.
