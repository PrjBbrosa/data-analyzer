---
role: pyqt-ui
tags: [pyqtgraph, sigmouseclicked, context-menu, viewbox, event-order, remarks]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
PgHeatmapCanvas remarks (M3) routed right-click-deletes-nearest through
`GraphicsScene.sigMouseClicked` with `ev.accept()`, expecting the accept
to suppress the ViewBox context menu — measured: the menu still popped.

## Lesson
In pg 0.14.0 `GraphicsScene.sendClickEvent` dispatches the click to
items FIRST (where `ViewBox.mouseClickEvent` raises the context menu on
RightButton) and emits `sigMouseClicked` only at the very end, so
`ev.accept()` inside a `sigMouseClicked` slot is structurally too late
to block the menu. The menu's actual gate is `ViewBox.menuEnabled()` —
checked before raising — so `vb.setMenuEnabled(False)` while an
annotation mode is active suppresses the popup yet still lets the
un-consumed right-click reach the `sigMouseClicked` slot for deletion
(re-enable on mode exit). The heavier alternative is overriding
`raiseContextMenu` (pg_canvas/viewbox.py:21 precedent), needed only
when the menu must stay reachable in the same mode.

## How to apply
When a pg canvas needs right-click behavior that must beat the ViewBox
menu, do not rely on `ev.accept()` in `sigMouseClicked`; toggle
`vb.setMenuEnabled(not mode_active)` with the mode, or intercept
`raiseContextMenu`. Verify by counting `raiseContextMenu` calls under a
real `QTest.mouseClick` right-click, not by reading the slot.
