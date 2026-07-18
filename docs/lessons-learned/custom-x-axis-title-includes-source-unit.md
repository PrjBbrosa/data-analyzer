---
id: custom-x-axis-title-includes-source-unit
status: active
owners: [codex]
keywords: [pyqt, timedomain, custom-xaxis, channel_units, axis-title]
paths: [mf4_analyzer/ui/main_window/window.py, tests/ui/test_main_window_smoke.py]
checks: [TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_main_window_smoke.py::test_custom_xaxis_axis_title_includes_source_unit -q]
tests: [tests/ui/test_main_window_smoke.py::test_custom_xaxis_axis_title_includes_source_unit]
---

# Custom X Axis Title Includes Source Unit

Trigger: Changing the TimeDomain label used for a channel-backed custom X axis.

Past failure: The selected channel's unit was already available in FileData,
but the rendered bottom-axis title used only the editable label/channel name.

Rule: For a custom X source, build the rendered title from the editable label
plus its channel unit (metadata first, then channel_units). Keep the editable
label and persisted View state unchanged, and never append an already-present
unit twice.

Verification: Run the targeted offscreen regression. It asserts that a
channel with `deg` renders `angle (deg)` and that `Rotor angle (deg)` stays
single-suffixed after reapplying.
