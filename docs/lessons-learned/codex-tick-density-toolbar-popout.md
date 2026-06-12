---
id: codex-tick-density-toolbar-popout
status: active
owners: [codex]
keywords: [tick-density, inspector, chart-toolbar, popout, pyqt]
paths:
  - mf4_analyzer/ui/chart_stack.py
  - mf4_analyzer/ui/inspector_sections.py
  - mf4_analyzer/ui/main_window.py
  - mf4_analyzer/ui_kit/style.qss
  - tests/ui/test_chart_stack.py
  - tests/ui/test_inspector.py
checks:
  - rg -n "坐标刻度密度|chartTickDensityButton|TickDensityPopover" mf4_analyzer/ui tests/ui
tests:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_inspector.py tests/ui/test_chart_stack.py::test_chart_cards_have_tick_density_popout_button tests/ui/test_chart_stack.py::test_tick_density_popout_preset_emits_and_updates_button tests/ui/test_chart_stack.py::test_chart_stack_relays_tick_density_popout_signal
---

# Tick Density Lives In Chart Toolbar Popout

Trigger: Touching global tick-density controls, Inspector persistent chart
settings, chart toolbar view controls, or tick-density project/view-state
plumbing.

Past failure: Tick density lived as a visible Inspector group, making a display
setting compete with analysis parameters and inviting future changes to keep
adding right-pane tick controls. The toolbar popout migration keeps the same
integer tick-count contract but changes the visible ownership.

Rule: Do not reintroduce the visible Inspector `坐标刻度密度` group. The user
entry point is the chart toolbar `Xn` button and `TickDensityPopover`; keep
hidden `PersistentTop` tick values only as compatibility state for existing
view/project capture paths.

Verification: Grep confirms there is no visible `坐标刻度密度` group and that
`chartTickDensityButton` / `TickDensityPopover` exist; run the Inspector and
chart-stack popout tests listed above.
