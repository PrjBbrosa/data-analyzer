---
id: overlay-right-axis-columns-need-post-tick-realize
status: active
owners: [codex]
keywords: [overlay, axisitem, view-restore, setWidth, plotitem, layout, textWidth]
paths:
  - mf4_analyzer/ui/pg_canvas/overlay_axes.py
  - mf4_analyzer/ui/pg_canvas/canvas.py
  - mf4_analyzer/ui/pg_canvas/tick_density.py
checks:
  - git diff --check
tests:
  - TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_overlay_grid_ticks.py::TestOverlaySwitchGeometry tests/ui/test_pg_timedomain_canvas.py::TestOverlayAxisLabelGeometry::test_overlay_right_axes_do_not_overlap_with_wide_numbers tests/ui/test_pg_timedomain_canvas.py::TestViewRestoreSettlement -q
---

# Overlay Right Axis Columns Need A Post-Tick Realize

Trigger: Changing TimeDomain overlay right Y-axes, View restore, `_settle_layout()`, overlay `setWidth`, or PlotItem extra columns.

Past failure: Switching an overlay View stacked coloured right-axis numbers until the user dragged. `_settle_layout()` only activated `glw.ci.layout`, not the PlotItem cells that own columns 3+. `AxisItem.textWidth` is only refreshed during paint, and View switch does not resize the widget, so `_on_resize_settled()` never ran. `setWidth(w)` as a "floor" jammed wide tick strings.

Rule: After final overlay ticks land, seed `AxisItem.textWidth` from the current tick strings, release with `setWidth(None)`, activate the PlotItem layout AND `glw.ci`, then sync aux ViewBoxes. Run this from plot closeout, `settle_view_restore()`, overlay `set_tick_density()`, and `_on_resize_settled()`. Do not wait for a drag. Never pin `setWidth` as a floor. Assert adjacent right-axis `sceneBoundingRect`s are separated without a resize.

Verification: `tests/ui/test_overlay_grid_ticks.py::TestOverlaySwitchGeometry::test_view_restore_right_axes_stay_separated_without_resize` plus `test_overlay_right_axes_do_not_overlap_with_wide_numbers` and `TestViewRestoreSettlement`, offscreen Qt, `git diff --check`.
