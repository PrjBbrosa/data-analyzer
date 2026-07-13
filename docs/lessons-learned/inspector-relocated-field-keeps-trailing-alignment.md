---
id: inspector-relocated-field-keeps-trailing-alignment
status: active
owners: [codex]
keywords: [pyqt, inspector, qformlayout, alignment, db-reference, narrow-pane]
paths: [mf4_analyzer/ui/inspector_sections/_helpers.py, mf4_analyzer/ui/inspector_sections/contextual_fft.py, mf4_analyzer/ui/inspector_sections/contextual_fft_time.py, mf4_analyzer/ui/inspector_sections/contextual_order.py, tests/ui/test_inspector.py]
checks: [.\\.venv\\Scripts\\python.exe -m pytest -q tests/ui/test_inspector.py -k db_reference_compound_row_precedes_axis_header_and_fits_within_320px --basetemp D:\\tmp\\pytest-db-reference-alignment]
tests: [tests/ui/test_inspector.py]
---

# Relocated Inspector Fields Keep Their Trailing Alignment

Trigger: Moving a capped Inspector control from a `QFormLayout` into a
custom row or group header, especially a compound dB reference control.

Past failure: The dB reference control was correctly moved above the axis
auto/min/max header, but the custom row appended its stretch after the
control. At 288px the control ended at x=187 while the standard field right
edge was x=269, visibly breaking the existing Inspector alignment datum.

Rule: Preserve the Inspector field geometry when relocating a compound
control. Give the compound control stretch so its editor fills the available
field and its trailing button stays right-aligned. If the control has a
second source/provenance line, place its label in an editor-height host and
center it on the editor, never on the compound widget's full height.

Verification: Run `tests/ui/test_inspector.py` with the dB reference narrow
layout test. It must expand the parameter section and assert the dB control
right edge matches `dbReferenceAxisRow`, its editor expands, and the dB label
center is within one pixel of the editor center at 288px and 320px for FFT,
FFT-vs-Time, and Order.
