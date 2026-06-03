---
role: pyqt-ui
tags: [qtreewidget, checkbox, hit-area, subelementrect, styleoption, offscreen, mousepress]
created: 2026-06-03
updated: 2026-06-03
cause: insight
supersedes: []
---

## Context

To widen the *clickable* hit area of a QTreeWidget column-0 checkbox
(without enlarging the indicator's visual size), I needed the exact
indicator rect via
`QStyle.subElementRect(SE_ItemViewItemCheckIndicator, opt, tree)`. With a
freshly `initFrom`-ed `QStyleOptionViewItem` whose `rect` was set to
`visualRect(index)`, the call returned a NULL rect, so the tolerance band
could never be computed.

## Lesson

`SE_ItemViewItemCheckIndicator` only yields a real rect when the option
advertises a check indicator: you must set
`opt.features |= QStyleOptionViewItem.HasCheckIndicator` AND
`opt.checkState = item.checkState(0)` before the call — `initFrom` does
not populate these from the item. Even then, some styles under
`QT_QPA_PLATFORM=offscreen` report a degenerate rect, so keep a fallback
that derives the band from `visualRect(index).left()` plus
`pixelMetric(PM_IndicatorWidth, opt, tree)`. To make the widened band
toggle exactly once, route through `item.setCheckState(0, ...)` (so the
existing `itemChanged` cascade runs) and `return` from `mousePressEvent`
WITHOUT calling `super()` — otherwise Qt's own indicator handling toggles
a second time and the net effect is no change.

## How to apply

When building a tolerance/hit-area around a view checkbox: populate
`opt.features` + `opt.checkState` on the `QStyleOptionViewItem` before
`subElementRect`, add a `PM_IndicatorWidth`-based fallback for offscreen,
toggle via `setCheckState` to reuse existing signal cascades, and consume
the press (no `super()`) inside the band to avoid double-toggle. Verify
the band toggles AND that a click on the name/content column does NOT
(it must fall through to selection / context-menu).
