---
role: pyqt-ui
tags: [qgraphicsgridlayout, qgraphicslayoutitem, destructor, mutation-testing, colorbaritem, teardown, pyqtgraph]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
Mutation-red verification of `PgHeatmapCanvas.full_reset` regression
tests: neutering only the `plot.layout.removeItem(self._cbar)` line
left the layout-count assertions GREEN.

## Lesson
Qt's `~QGraphicsLayoutItem` removes itself from its parent layout, so
when the subsequent `scene.removeItem` + Python ref drop destroy the
item synchronously, `QGraphicsGridLayout.count()` self-heals even with
the explicit `layout.removeItem` call skipped — but only if the object
actually dies (holding any extra Python reference, e.g. in a test
probe, keeps the count stale). The explicit removeItem is therefore
defensive, not load-bearing, and is unfalsifiable by single-line
mutation.

## How to apply
When mutation-testing a teardown path, mutate the GUARD of the whole
teardown block (`if obj is not None:` → `if False and ...`), not an
individual detach call that object destruction makes redundant; and
pin teardown tests to observable invariants (layout item count
restored across reset+replot) rather than to which internal API
performed the detach.
