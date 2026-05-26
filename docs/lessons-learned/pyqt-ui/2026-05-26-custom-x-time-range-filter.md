---
id: pyqt-ui/2026-05-26-custom-x-time-range-filter
status: active
owners: [codex]
keywords: [pyqt, matplotlib, custom-xaxis, time-range, inspector, plot_time]
paths: [mf4_analyzer/ui/main_window.py, tests/ui/test_main_window_smoke.py]
checks: [QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/ui/test_main_window_smoke.py::test_custom_xaxis_time_range_filters_by_file_time_axis tests/ui/test_main_window_smoke.py::test_custom_xaxis_length_mismatch_warns -q]
tests: [tests/ui/test_main_window_smoke.py::test_custom_xaxis_time_range_filters_by_file_time_axis]
---

# Custom X Axis Keeps Time Range Filtering

Trigger: Touching `plot_time`, Inspector range controls, custom X-axis channel
selection, or time-domain plot filtering.

Past failure: A custom X-axis channel replaced the variable later used for the
range mask, so Inspector's "selected time range" filtered by angle/force/etc.
instead of by `FileData.time_array`.

Rule: Keep the display X array separate from the acquisition time axis. Range
controls always mask against `FileData.time_array`; custom X values are only
for plotting the already-selected samples.

Verification: Add or run a regression where `time=0..9`, custom X is
`100..109`, range is `2..4`, and the plotted custom-X points are
`102,103,104`.
