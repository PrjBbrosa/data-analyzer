---
role: pyqt-ui
tags: [layout, footer, hint-bar, elide, qsizepolicy, qlabel, anchor, rotation, stable-placement, centered-group, separator-visibility]
created: 2026-06-15
updated: 2026-06-17
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
left edge wandered. A 2026-06-17 follow-up changed the direction: real-window
feedback was that left-anchored row + right-anchored discovery left a big empty
middle, so the user chose to center the **whole group** (rotating row + ` · ` +
discovery) with symmetric side padding instead.

## Lesson

Two distinct anchoring regimes for the same eliding footer row:

1. **Left-anchored**: eliding label as the *first* layout item with
   `QSizePolicy(Ignored, Preferred)` + `ElideRight` (the project's
   `file_navigator._ElidedLabel` default) pins its left edge, never demands
   width, and elides instead of widening; give the right sibling
   `QSizePolicy.Maximum` so the row yields to it rather than squeezing it to 0.

2. **Centered group**: `addStretch(1) | group | addStretch(1)` where the group
   is a hug-content child `QWidget` (`QSizePolicy.Maximum`) holding the rotating
   row + separator + discovery. The critical gotcha: `Ignored` horizontal policy
   makes the eliding label **collapse to zero** when centered/hugged (it claims
   no width, so the group has nothing to size to). Override that specific
   instance to `QSizePolicy.Preferred` (NOT the shared `_ElidedLabel` default,
   which left-anchored file rows still need) so the group sizes to the text yet
   still shrinks below sizeHint (min width 0) and elides under a narrow bar.
   A conditional ` · ` separator must be a dedicated `QLabel` toggled
   `setVisible(bool(discovery_text))` at the *single* site that sets the
   discovery text (here `_refresh_bottom_hint`), so a retired/empty discovery
   never leaves a dangling dot.

In BOTH regimes the non-obvious trap is identical: once a label elides,
`QLabel.text()` returns the **elided** string (with the …), NOT the logical
value — so any equality assertion or production read-back must go through a
`full_text()` accessor. This bites hardest in unshown/zero-width test widgets
(a bare card never laid out): a centered `Preferred` label there collapses to
`''`, so even a substring `in text()` check fails — assert `full_text()`.

## How to apply

When replacing a fixed footer/status element with a variable-length one, fix it
at the container level first and pick the regime: left-anchored (Ignored + first
item + stretch + Maximum sibling) for "pin the left edge", or centered group
(symmetric stretches around a Maximum hug-content container, eliding child
flipped to `Preferred`) for "fill the empty middle". Verify with a real render
under THREE states — discovery non-empty (separator shows, symmetric L/R gaps),
discovery empty (separator hidden, lone row still centered), and a *forced*
narrow bar (`bar.setFixedWidth`) to prove the eliding child yields first and the
group stays inside the bar (no negative stretch / overflow). Read
`child.mapTo(bar, QPoint(0,0))` geometry + grab pixmaps; offscreen geometry is
enough for edge math, load the app QSS for the visual. In tests and any code
that reads the value back, assert on `full_text()`, never `text()`.
