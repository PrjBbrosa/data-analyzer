---
id: codex-pg-timedomain-frame-and-spacing
status: active
owners: [codex]
keywords: [pyqtgraph, timedomain, subplot, ViewBox, AxisItem, frame, spacing]
paths:
  - mf4_analyzer/ui/pg_canvases.py
  - tests/ui/test_pg_timedomain_canvas.py
checks:
  - rg -n "setBorder|_unify_subplot_bottom_axis_heights|test_dense_subplots_do_not_reserve_hidden_xaxis_label_height|test_two_subplots_do_not_reserve_hidden_top_axis_height|test_plot_items_draw_full_neutral_viewbox_frame" mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
tests:
  - .\.venv\Scripts\python.exe -m pytest tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGVisualStyleDefaults tests/ui/test_pg_timedomain_canvas.py::TestOverlayGridSingleAxis -q
---

# Pyqtgraph TimeDomain Frame And Dense Spacing

Trigger: Touching pyqtgraph TimeDomain PlotItem/ViewBox frame styling,
subplot bottom-axis heights, hidden X tick labels, or dense multi-channel
subplot layout.

Past failure: The pyqtgraph TimeDomain canvas visually lost the top plot
frame because the ViewBox border used a too-light default pen, and subplot mode
had large blank vertical gaps because hidden upper X axes reserved the same full
tick-label height as the visible bottom X axis. The first fix carved out the
two-row case to keep equal ViewBox heights, but that reserve IS the gap — a
two-channel plot showed a wide blank band between the rows.

Rule: Use the ViewBox border for the full plot frame with the project neutral
axis pen. For two or more subplot rows, collapse the hidden upper bottom-axis
heights to ~1 px so only the final row reserves X tick/label space — favour
flush adjacency over pixel-equal ViewBox heights (the bottom row ends up
~one-axis-height shorter, which is the intended stacked-shared-X look). Do not
special-case the two-row count.

Verification: Run the targeted visual-style and overlay-grid tests, and inspect
a rendered two-row and dense subplot screenshot when changing this area. See
docs/superpowers/specs/2026-06-02-subplot-vertical-spacing-design.md.
