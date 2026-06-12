---
id: codex-shared-viewtabbar-and-pg-frames
status: active
owners: [codex]
keywords: [viewtabbar, view-tabs, qss, pyqtgraph, frame, border, analysis-section]
paths:
  - mf4_analyzer/ui_kit/style.qss
  - mf4_analyzer/ui/view_tabbar.py
  - mf4_analyzer/ui/analysis_section_page.py
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
checks:
  - rg -n "QWidget#viewTabBar|QFrame#timeViewBottomDock QTabBar#viewTabs|_apply_neutral_axis_frame|setBorder" mf4_analyzer/ui_kit/style.qss mf4_analyzer/ui/pg_canvas
tests:
  - .\.venv\Scripts\python.exe -m pytest tests/ui/test_view_tabbar.py tests/ui/test_view_tabbar_mount.py tests/ui/test_analysis_section_page.py::test_analysis_tabbar_uses_active_pane_split_controls tests/ui/test_pg_heatmap_canvas.py::test_heatmap_plots_draw_full_neutral_axis_frame_without_viewbox_overlap tests/ui/test_pg_line_canvas.py::test_line_plots_draw_full_neutral_axis_frame_without_viewbox_overlap -q
---

# Shared ViewTabBar And Pyqtgraph Frames

Trigger: Touching ViewTabBar QSS, TimeDomain or analysis-section view tab
chrome, or pyqtgraph analysis PlotItem frame styling.

Past failure: ViewTabBar chrome was scoped under `#timeViewBottomDock`, so
analysis-section tabs fell back to platform QTabBar styling. FFT, FFT-vs-Time,
and Order pyqtgraph plots either lacked the neutral frame or used ViewBox
borders that overlapped the visible left/bottom axis lines.

Rule: Scope shared tab chrome to `QWidget#viewTabBar` and its children, not a
specific parent container. Pyqtgraph analysis PlotItems that represent a
visible chart area should build the full neutral frame from axes: left/bottom
stay visible as normal axes, top/right are visible line-only axes with
`showValues=False` and zero tick length, and the ViewBox border stays unset so
the axis lines are not double-painted.

Verification: Run the ViewTabBar, analysis-tabbar, and pg heatmap/line frame
tests listed above, plus `git diff --check`.
