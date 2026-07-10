---
id: b5-status-facts-preserve-field-semantics
status: active
owners: [codex]
keywords: [acquisition, cockpit, status-bar, acceptance]
paths:
  - mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py
  - tests/acquisition_ui/test_status_bar_text.py
  - scripts/cockpit_ui_tour.py
checks:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui/test_status_bar_text.py -q
tests:
  - tests/acquisition_ui/test_status_bar_text.py::test_recording_status_bar_text
---

# Status Facts Preserve Their Field Semantics

Trigger: Editing the Acquisition Cockpit recording fact stream or its
end-to-end assertions.

Past failure: A zero-byte recording rendered the file-size slot as `缓冲中`.
The stream therefore changed a promised fact field into a state word at the
start of recording, while the tour only checked for broadly Chinese text.

Rule: Keep every B5 priority slot semantically stable from the first visible
recording frame. In particular, the size slot is always a numeric `MB` value
(`0.0 MB` before the writer flushes); acceptance must assert the named facts,
not merely localized text.

Verification: Run the focused status-bar test and the asserted cockpit tour;
the recording message must include `录制中`, `磁盘剩`, samples, numeric `MB`, and
`样本/s`.
