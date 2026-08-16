---
id: pyqt-ui/2026-08-16-shared-pill-needs-section-gate
status: active
owners: [codex]
keywords: [cursor pill, ChartStack, FRF, FFT, _on_cursor_info, section gate]
paths:
  - mf4_analyzer/ui/chart_stack/stack.py
  - tests/ui/test_project_session.py
  - tests/ui/test_split_routing.py
checks:
  - rg -n "_cursor_source_on_screen|_on_cursor_info|_on_dual_cursor_info" mf4_analyzer/ui/chart_stack/stack.py
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_project_session.py -k pill tests/ui/test_split_routing.py tests/ui/test_pill_switch.py -q
---

# Shared Cursor Pill Needs A Section Gate

Trigger: Routing time-domain cursor / dual-cursor readout into the shared ChartStack pill from an analysis canvas, View restore, or FRF/FFT tab switch.

Past failure: An off-screen FRF or FFT canvas emitted empty cursor info during restore. The shared pill handler treated that as "clear the time dual-cursor readout", so a saved time View lost its A/B items after reopen or after switching to FRF and back.

Rule: `ChartStack` cursor handlers must ignore sources whose card is not the on-screen section (`_cursor_source_on_screen`). Do not clear the shared pill because a hidden analysis canvas has no cursor. The analysis canvas may still clear its own readout when it is on screen.

Verification: `test_reopen_with_frf_view_keeps_time_dual_cursor_pill`, `test_switch_to_frf_and_back_keeps_time_pill`.
