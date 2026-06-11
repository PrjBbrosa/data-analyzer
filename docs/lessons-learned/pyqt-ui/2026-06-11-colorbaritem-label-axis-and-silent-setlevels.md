---
role: pyqt-ui
tags: [pyqtgraph, colorbaritem, heatmap, imageitem, label-axis, setlevels, signals, scene-rect, hit-test, colormapmenu]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
PgHeatmapCanvas (pg 0.14.0) needed to update the colorbar label on the
reuse path and to relay user level-drags without programmatic
`setLevels` calls masquerading as drags. Later the same canvas's
remark-mode right-click deleted remarks when clicking the colorbar.

## Lesson
On a vertical `pg.ColorBarItem` the `label=` kwarg is applied to the
LEFT axis (`getAxis('left').setLabel`), while tick values render on the
right axis — updating `getAxis('right').setLabel` silently writes to
the wrong axis and the visible label never changes. Also,
`ColorBarItem.setLevels` does NOT emit `sigLevelsChanged` in 0.14.0
(only interactive region drags via `_regionChanging` do), so a
programmatic-update guard must be `blockSignals` defensive, not relied
upon as the only barrier.

Hit-testing: `setImageItem(img, insert_in=plot)` nests the bar inside
the host PlotItem's layout, so `plot.sceneBoundingRect()` INCLUDES the
colorbar column — a scene-click handler gated only on that rect treats
colorbar clicks as plot clicks (measured: remark-mode right-click on
the bar deleted the nearest remark). Guard with data-extent containment
of the mapped view point, not the plot rect. Also, ColorBarItem is
itself a PlotItem with its own ViewBox: right-clicking it raises pg's
built-in `ColorMapMenu` regardless of the HOST ViewBox's
`setMenuEnabled(False)` (measured via `QApplication.activePopupWidget`
under a real QTest right-click; the bar's own `vb.menuEnabled()` was
already False — the menu comes from the colormap machinery, not the
ViewBox gate).

## How to apply
When mutating an existing vertical ColorBarItem's label, target
`getAxis('left')`; verify against the installed pg version's
`ColorBarItem.__init__` source (orientation decides the axis). When
wiring `sigLevelsChanged`, treat it as user-drag-only in 0.14.0 but
still wrap programmatic `setLevels` in `blockSignals(True/False)` so a
future pg version cannot turn refreshes into phantom drags. When a
scene-click feature must exclude the colorbar, check the mapped point
against the data extents instead of `plot.sceneBoundingRect()`, and do
not expect host `setMenuEnabled(False)` to silence the bar's own
ColorMapMenu.
