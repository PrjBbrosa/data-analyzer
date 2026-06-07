---
id: codex-cursor-pill-view-apply
status: active
owners: [codex]
keywords: [cursor-pill, view-state, split-pane, cursor-mode, chart-stack]
paths:
  - mf4_analyzer/ui/main_window.py
  - mf4_analyzer/ui/chart_stack.py
  - tests/ui/test_split_routing.py
  - tests/ui/test_split_per_pane_controls.py
checks:
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_split_routing.py tests/ui/test_split_per_pane_controls.py -v
tests:
  - tests/ui/test_split_routing.py::test_new_view_does_not_carry_cursor_pill_from_previous_view
  - tests/ui/test_split_routing.py::test_switch_to_cursor_off_view_clears_pill
  - tests/ui/test_split_per_pane_controls.py::test_secondary_canvas_cursor_readout_reaches_shared_pill
---

# Cursor Pill View Apply

Trigger: Touching view-tab apply/render paths, cursor mode restoration, or split-pane cursor pill routing.

Past failure: Gating `_render_view_to_canvas` pill snapshot/restore fixed one leak path but still left stale text because `ViewBridge.apply_controls_from_state()` uses `set_cursor_mode_for_canvas()`, a silent path that does not emit `_on_time_cursor_mode_changed()` and therefore does not clear the pill when applying `cursor_mode="off"`. A broad fix in `ChartStack.set_cursor_mode_for_canvas()` then disturbed secondary-pane readouts; the shared pill tests caught that secondary cursor info must still update the primary shared pill.

Rule: Primary view renders that apply `cursor_mode="off"` must explicitly clear the shared cursor pill in `MainWindow`, while secondary/off-screen renders should rely on snapshot/restore. Do not route secondary readouts to a hidden separate pill unless all shared-pill tests and copy/export paths are updated together.

Verification: Run the split routing and per-pane controls suites together so both sides are covered: view switch/new-view stale pill clearing and secondary cursor readout preservation.
