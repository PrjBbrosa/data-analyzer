---
id: codex-pg-heatmap-split-layout-alignment
status: active
owners: [codex]
keywords: [pyqtgraph, heatmap, split, fft-time, colorbar, title, viewbox, layout]
paths:
  - mf4_analyzer/ui/pg_canvas/heatmap_canvas.py
  - mf4_analyzer/ui/analysis_section_page.py
  - tests/ui/test_analysis_section_page.py
checks:
  - rg -n "sync_heatmap_layouts|layout_geometry_changed|slice_right_reserve" mf4_analyzer/ui tests/ui
tests:
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_section_page.py::test_split_fft_time_heatmap_and_slice_plot_areas_align -q
---

# Pyqtgraph Heatmap Split Layout Alignment

Trigger: Touching Analysis split panes for Order or FFT-vs-Time heatmaps,
especially pyqtgraph titles, left axes, colorbars, slice rows, or ViewBox
geometry.

Past failure: QSplitter equalized the outer analysis cards, but each
PgHeatmapCanvas auto-sized its own PlotItem internals. Different frequency
tick widths, long channel titles, and the FFT-vs-Time colorbar caused the two
main ViewBoxes to start at different x positions. The lower frequency-slice
row also lacked a right-side colorbar reserve, so it was wider than the
heatmap above it.

Rule: Do not treat equal splitter sizes as proof of aligned plots. In split
heatmap pages, coalesce layout changes after render, constrain long titles so
they cannot widen the scene, pin shared left/bottom axis reserves to maxima,
and add a transparent right-side spacer for FFT-vs-Time slice rows to match
the heatmap/colorbar reserve.

Verification: Run the split geometry regression and inspect a rendered split
PNG when changing this surface. The regression must compare
``ViewBox.sceneBoundingRect()`` for both panes and for the main heatmap versus
the slice row, not just check that screenshots are nonblank.
