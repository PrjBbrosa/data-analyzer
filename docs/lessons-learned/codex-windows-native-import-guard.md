---
id: codex-windows-native-import-guard
status: active
owners: [codex]
keywords: [windows, pyqt, pyxcp, pya2l, native-import, access-violation, cockpit, vector]
paths:
  - can_logger/p0/a2l_probe.py
  - mf4_analyzer/acquisition_capture/backends.py
  - mf4_analyzer/acquisition_capture/vector_hw_probe.py
  - mf4_analyzer/acquisition_ui/
checks:
  - rg -n "from pya2l|import pya2l|from pyxcp|import pyxcp" can_logger mf4_analyzer
tests:
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/ui/test_analyzer_opens_cockpit.py tests/test_vector_xcp_backend.py tests/test_vector_hw_probe.py tests/acquisition_ui/test_record_backend_swap.py -q
---

# Windows Native Imports Need Isolated Probe

Trigger: Touching Windows acquisition backends, Cockpit startup/import paths, or optional native dependencies such as `pya2l`, `pyxcp`, or Vector `python-can`.

Past failure: On Windows, Cockpit/Vector tests exited with `0xC0000005` when `pyxcp.master` was imported inside an already-PyQt process. The crash bypassed `try/except`. Cockpit startup also imported `pya2l` before the user selected an A2L file, so a broken optional parser could take down the launch path.

Rule: Keep optional/native acquisition dependencies out of module load and out of Cockpit startup. If a dependency can terminate the process, do not rely on `try/except`; guard UI-path imports with an isolated subprocess probe that mimics the PyQt-loaded context, then surface failure as a normal unavailable backend/status message.

Verification: Add a regression that blocks eager parser imports on Cockpit startup, and one that converts native-import probe failure into `RecorderBackendUnavailableError` or a red connection result. Run the focused Cockpit/A2L/Vector tests.
