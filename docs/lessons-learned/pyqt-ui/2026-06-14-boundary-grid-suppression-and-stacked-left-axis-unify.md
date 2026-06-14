---
role: pyqt-ui
tags: [pyqtgraph, axisitem, generateDrawSpecs, grid, double-line, setWidth, stacked-plots, left-axis-align, single-pane, offscreen-testing, setGrid, top-right-axis, showgrid, context-menu]
created: 2026-06-14
updated: 2026-06-14
cause: insight
supersedes: []
---

## Context
The Order / FFT-vs-Time analysis canvases (``PgLineCanvas`` amp+time rows,
``PgHeatmapCanvas`` map+slice rows) showed a "double line" at the top/bottom
frame and misaligned left edges between the two stacked plots in single-pane
mode. Both are pure pyqtgraph axis-geometry artifacts, not data bugs.

## Lesson
(1) The top/bottom "double line" is the OUTERMOST grid line sitting ~8% inside
the frame because the plots keep deliberate Y whitespace (empty-state
``setYRange(0,1,padding=0.08)`` / autorange margin). Subclass ``AxisItem`` and
override ``generateDrawSpecs``: call ``super()`` (returns
``(axisSpec, tickSpecs, textSpecs)`` where each tickSpec is ``(pen, p1, p2)``),
then drop specs whose VALUE-axis coordinate ``p1[1 - axis]`` (axis=0 for
left/right → value is Y; axis=1 for top/bottom → value is X) is within ~1.5px of
the linked-view rect edge (``linkedView().mapRectToItem(self, ...)`` top/bottom
or left/right). Guard ``self.grid is False`` (passthrough) and ``specs is None``
(no realized geometry). Install via ``addPlot(axisItems={'left':…,'bottom':…})``
— only the grid-bearing axes; top/right stay stock. The subclass inherits every
later ``setPen``/``setStyle``/``setTickDensity`` mutation unchanged.
(2) Single-pane stacked left-axis alignment: the split path unifies left widths,
but the single-pane ``reset_split_layout_alignment`` only released them to their
NATURAL widths (``setWidth(None)``), so two plots with different y-tick-label
widths kept different left edges. Fix: after the release+realize, read each
left axis ``width()``, take the MAX, and ``setWidth(max)`` on both — here
``setWidth`` as a HARD CLAMP (the 2026-05-29 lesson) is exactly what you want:
it forces the narrower axis up to the shared width. Order matters in the heatmap:
unify LEFT first (shifts each plot's left edge), THEN ``_align_slice_to_main``
(right-edge match).

(3) The ``_BoundaryGridAxisItem`` subclass only suppresses the boundary line on
the axes it is INSTALLED on (left+bottom). ``showGrid(x=True, y=True)`` lights
the grid on ALL FOUR built-in axes, and top/right are PLAIN ``AxisItem``s that
re-draw the very boundary line left/bottom suppressed PLUS over-draw the interior
lines — so during zoom their sub-pixel offset doubles every grid line (offscreen:
right axis returned 6 horizontal gridlines vs left's 4). The other half of the
double-line fix is therefore ``getAxis('top').setGrid(False)`` +
``getAxis('right').setGrid(False)`` after EACH ``showGrid`` call, on every plot
(``line_canvas`` already did this; the heatmap map+slice did not). CAVEAT: the
SHARED ``context_menu._build_grid_submenu`` grid toggle calls
``plot_item.showGrid(x,y)`` again on user toggle, which RE-LIGHTS top/right and
undoes the constructor ``setGrid(False)`` — a cross-canvas trap affecting both
the line and heatmap canvases (the durable fix belongs in ``context_menu.py``:
re-disable top/right after its ``showGrid``, or toggle only left/bottom).

## How to apply
For a pyqtgraph "grid line doubles the frame" complaint when padding is
intentional: do NOT set padding=0 (the user rejected that) — subclass
``AxisItem.generateDrawSpecs`` and filter the boundary tickSpec by its
value-axis coordinate vs the linked-view rect edge. Test the FILTER in isolation
by monkeypatching ``pg.AxisItem.generateDrawSpecs`` to return synthetic specs —
do NOT drive the real method with ``QPainter(QPicture())``, it access-violates in
the text ``boundingRect`` path. For stacked single-pane plots that must share a
left edge, unify left-axis widths to their max only on the single-pane reset
path (the ≥2-pane page path already unifies); verify ``getAxis('left').width()``
equality AND ``vb.sceneBoundingRect().left()`` within ~2px on a shown+realized
canvas.
