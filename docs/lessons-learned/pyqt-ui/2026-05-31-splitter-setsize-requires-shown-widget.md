---
role: pyqt-ui
tags: [splitter, visibility, offscreen, testing, widget-lifecycle]
created: 2026-05-31
updated: 2026-05-31
cause: insight
supersedes: []
---

## Context

`SidePanelController` tests needed `QSplitter.setSizes([250, 650])` to stick
and child `QWidget.isVisible()` to return `True` after `overlay.show()`.
Both assertions failed when the host `QWidget` was never shown and the
splitter had no allocated geometry.

## Lesson

`QSplitter.setSizes` is silently ignored (all slots return their minimum
size, typically 48px offscreen) when the splitter has zero width; likewise,
a child widget's `isVisible()` returns `False` even after an explicit
`.show()` call if its parent has never been shown. Both conditions require
`host.show()` AND `splitter.resize(w, h)` before the first `setSizes` call.

## How to apply

In any pytest-qt test fixture that constructs a `QSplitter` inside a
top-level `QWidget`: call `host.show()` then `splitter.resize(host_w,
host_h)` before `setSizes(...)`, and add `host` (not the splitter) to
`qtbot` for cleanup. Without these two lines, width assertions and
child-visible assertions will fail silently on offscreen platforms.
