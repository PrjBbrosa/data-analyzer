---
role: pyqt-ui
tags: [qicon, qpixmap, qpainter, dpr, ultraview, icon-only]
created: 2026-08-22
updated: 2026-08-22
cause: insight
supersedes: []
---

## Context

An UltraView rail must render the same icon-only glyph at fixed 20px compact
and 24px desktop targets.

## Lesson

A QIcon with only a 20px source is enlarged at 24px, softening thin QPainter
strokes even though the vector paths themselves are correct.

## How to apply

Add a DPR-aware raster for every supported target, paint both from the same
design grid, and assert the source sizes and optical ink bounds in focused
tests.
