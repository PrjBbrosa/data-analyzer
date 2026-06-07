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
  - tests/ui/test_split_per_pane_controls.py::test_secondary_canvas_cursor_readout_reaches_secondary_pill
  - tests/ui/test_split_per_pane_controls.py::test_split_dual_cursor_results_show_on_both_pane_pills
---

# Cursor Pill View Apply

Trigger: Touching view-tab apply/render paths, cursor mode restoration, or split-pane cursor pill routing.

Past failure: Gating `_render_view_to_canvas` pill snapshot/restore fixed one leak path but still left stale text because `ViewBridge.apply_controls_from_state()` uses `set_cursor_mode_for_canvas()`, a silent path that does not emit `_on_time_cursor_mode_changed()` and therefore does not clear the pill when applying `cursor_mode="off"`. A broad fix in `ChartStack.set_cursor_mode_for_canvas()` then disturbed split-pane readouts. The product contract is not one global shared readout: in split mode each pane needs its own pill so both views can show independent dual-cursor results.

Rule: Primary view renders that apply `cursor_mode="off"` must explicitly clear the primary cursor pill in `MainWindow`, while secondary/off-screen renders should rely on snapshot/restore. In split mode, route secondary cursor and dual-cursor readouts to the secondary pill, not the primary pill, so both panes can show their own results concurrently.

Verification: Run the split routing and per-pane controls suites together so both sides are covered: view switch/new-view stale pill clearing, secondary cursor readout preservation, and both-pane dual-cursor pill results.
