---
role: pyqt-ui
tags: [pyqtgraph, colorbaritem, heatmap, imageitem, label-axis, setlevels, signals]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
PgHeatmapCanvas (pg 0.14.0) needed to update the colorbar label on the
reuse path and to relay user level-drags without programmatic
`setLevels` calls masquerading as drags.

## Lesson
On a vertical `pg.ColorBarItem` the `label=` kwarg is applied to the
LEFT axis (`getAxis('left').setLabel`), while tick values render on the
right axis — updating `getAxis('right').setLabel` silently writes to
the wrong axis and the visible label never changes. Also,
`ColorBarItem.setLevels` does NOT emit `sigLevelsChanged` in 0.14.0
(only interactive region drags via `_regionChanging` do), so a
programmatic-update guard must be `blockSignals` defensive, not relied
upon as the only barrier.

## How to apply
When mutating an existing vertical ColorBarItem's label, target
`getAxis('left')`; verify against the installed pg version's
`ColorBarItem.__init__` source (orientation decides the axis). When
wiring `sigLevelsChanged`, treat it as user-drag-only in 0.14.0 but
still wrap programmatic `setLevels` in `blockSignals(True/False)` so a
future pg version cannot turn refreshes into phantom drags.
