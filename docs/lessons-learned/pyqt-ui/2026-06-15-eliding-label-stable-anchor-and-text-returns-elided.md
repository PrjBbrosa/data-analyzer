---
role: pyqt-ui
tags: [layout, footer, hint-bar, elide, qsizepolicy, qlabel, anchor, rotation, stable-placement]
created: 2026-06-15
updated: 2026-06-15
cause: insight
supersedes: []
---

## Context

The chart-card bottom hint bar retired its fixed left-anchored static label and
replaced it with a single variable-length rotating row (per-section base-gesture
anchor + context tips, weight-ordered). The hard acceptance gate was 提示位置:
the rotating row must not jump left/right as text length changes between laps,
and must not push the right-anchored discovery slot. The naive `QLabel` grows to
its text width, so a long rotating string shoved the discovery slot left and the
left edge wandered.

## Lesson

Anchor a variable-content footer row with `QSizePolicy(Ignored, Preferred)` +
`ElideRight` (the project's `file_navigator._ElidedLabel` already does both): as
the *first* layout item it pins its left edge at the bar's left, it never demands
width so it cannot push a right-anchored sibling, and over-long text elides
instead of widening. Give the right sibling `QSizePolicy.Maximum` so the eliding
row yields space to it rather than squeezing it to zero. The non-obvious trap:
once a label elides, `QLabel.text()` returns the **elided** string (with the …),
NOT the logical value — so any equality assertion or production read-back must go
through a `full_text()` accessor that returns the stored full string, or it will
spuriously mismatch at narrow widths (and in unshown/zero-width test widgets,
where elision is maximal).

## How to apply

When replacing a fixed footer/status element with a variable-length one that must
stay put, fix it at the container level first: make it an eliding label with
`Ignored` horizontal policy as the left-anchored item, a stretch, then the
right-anchored sibling with `Maximum` policy — verify with a real render that the
left edge and the sibling's right edge are pixel-stable across long/short
strings (read `mapTo(parent, ...)` geometry + grab pixmaps; offscreen geometry is
enough for edge math, load the app QSS for the visual). In tests and any code
that reads the value back, assert on `full_text()`, never `text()`.
