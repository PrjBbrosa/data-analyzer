---
id: pyqt-channel-universe-refresh
status: active
owners: [codex]
keywords: [pyqt, channel, candidates, custom xaxis, channel editor]
paths:
  - mf4_analyzer/ui/main_window.py
  - mf4_analyzer/ui/inspector_sections.py
  - tests/ui/test_main_window_smoke.py
checks:
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/ui/test_main_window_smoke.py tests/ui/test_inspector.py tests/ui/test_file_navigator.py tests/ui/test_batch_input_panel.py -q
tests:
  - tests/ui/test_main_window_smoke.py
---

# PyQt Channel Universe Refresh

Trigger: Touching file load/close, channel editor application, or any live
selector populated from `FileData.channels`, `FileData.get_signal_channels()`,
or `fd.data.columns`.

Past failure: The channel editor added derivative channels to `fd.data` and
`fd.channels`, but the already-visible custom X-axis selector stayed stale
because only FFT/Order combos were refreshed. Loading another file while the X
source was already in channel mode had the same stale-selector gap, and deleting
the applied custom-X source left `_custom_xaxis_*` state pointing at a removed
column.

Rule: Channel universe changes must refresh every live selector from one
MainWindow path and must validate persisted custom-X state. Do not update only
the widget that triggered the change.

Verification: Add regression coverage for channel-edit additions, file-load
additions while X-axis channel mode is active, and removal of the applied
custom-X source. Run the focused PyQt suites listed in `checks`.
