---
id: codex-pg-timedomain-frame-and-spacing
status: active
owners: [codex]
keywords: [pyqtgraph, timedomain, subplot, ViewBox, AxisItem, frame, spacing]
paths:
  - mf4_analyzer/ui/pg_canvases.py
  - tests/ui/test_pg_timedomain_canvas.py
checks:
  - rg -n "setBorder|_unify_subplot_bottom_axis_heights|test_dense_subplots_do_not_reserve_hidden_xaxis_label_height|test_plot_items_draw_full_neutral_viewbox_frame" mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
tests:
  - PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGVisualStyleDefaults tests/ui/test_pg_timedomain_canvas.py::TestOverlayGridSingleAxis -q
---

# Pyqtgraph TimeDomain Frame And Dense Spacing

Trigger: Touching pyqtgraph TimeDomain PlotItem/ViewBox frame styling,
subplot bottom-axis heights, hidden X tick labels, or dense multi-channel
subplot layout.

Past failure: The pyqtgraph TimeDomain canvas visually lost the top plot
frame because the ViewBox border used a too-light default pen, and five-row
subplot mode had large blank vertical gaps because hidden upper X axes reserved
the same full tick-label height as the visible bottom X axis.

Rule: Use the ViewBox border for the full plot frame with the project neutral
axis pen. Keep the two-row subplot equal-height reserve, but for three or more
subplot rows collapse hidden upper bottom-axis heights so only the final row
reserves X tick/label space.

Verification: Run the targeted visual-style and overlay-grid tests, and inspect
a rendered dense subplot screenshot when changing this area.
