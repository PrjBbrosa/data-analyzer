---
role: pyqt-ui
tags: [layout, inspector, navigator, responsive-pane, rework]
created: 2026-04-24
updated: 2026-04-24
cause: rework
supersedes: []
---

## Context

After the Precision Light UI pass, narrow-window screenshots showed right
Inspector controls overlapping and the left file list showing only one
loaded file. The first follow-up changed form rows into vertical field
blocks, but the user clarified that the desired behavior was container
scrolling/resizing, not a different form layout.

## Lesson

Responsive pane defects should be solved at the container level before
changing control semantics. In this app, right Inspector overflow belongs
to a pane-level `QScrollArea`, while left file-list capacity belongs to a
splitter or resizable file region.

## How to apply

When screenshot feedback mentions narrow panes, clipping, overlap, or
too little list space, inspect `QScrollArea`, `QSplitter`, stretch
factors, and min/max heights first. Preserve compact `QFormLayout` rows
unless the user explicitly asks for label-over-control form styling, and
verify both narrow Inspector and multi-file navigator states.
