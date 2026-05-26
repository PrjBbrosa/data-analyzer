---
id: pyqt-ui/2026-05-26-timedomain-state-preservation
status: active
owners: [codex]
keywords: [pyqt, matplotlib, timedomain, xlim, pan, toolbar, channel-selection]
paths: [mf4_analyzer/ui/main_window.py, mf4_analyzer/ui/chart_stack.py, mf4_analyzer/ui/canvases.py, tests/ui/test_main_window_smoke.py, tests/ui/test_chart_stack.py]
checks: [QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/ui/test_main_window_smoke.py tests/ui/test_chart_stack.py tests/ui/test_canvases.py tests/ui/test_dialogs.py -q]
tests: [tests/ui/test_main_window_smoke.py::test_channel_selection_change_preserves_xlim, tests/ui/test_main_window_smoke.py::test_channel_editor_apply_preserves_checked_xlim, tests/ui/test_main_window_smoke.py::test_returning_to_time_mode_preserves_xlim, tests/ui/test_chart_stack.py::test_overlay_curve_drag_returns_to_pan_after_y_move]
---

# TimeDomain State Preservation

Trigger: Touching TimeDomain replots, channel selection/editing, plot mode
switching, or chart toolbar pan/zoom behavior.

Past failure: Non-semantic TimeDomain operations rebuilt the Matplotlib axes and
autoscaled X back to the full data extent. Overlay curve selection also
deactivated the default pan tool and left the toolbar in idle mode after the
interaction.

Rule: Preserve the visible X window for TimeDomain replots whose data extent
still overlaps the previous view. Do not preserve X when the X-axis semantics or
file time axis changed. Temporary toolbar deactivation for overlay series drag
must restore zoom if zoom was active, otherwise restore pan.

Verification: Add regression tests for channel selection, channel edits, and
returning to TimeDomain preserving X limits, plus overlay drag returning to pan.
Run the focused PyQt/Matplotlib UI suite listed in `checks`.
