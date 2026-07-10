---
role: pyqt-ui
tags: [splitter, pane-removal, blast-radius, min-width, toolbar-clamp, width-threshold, index-assertion, compact-stats, cockpit]
created: 2026-07-10
updated: 2026-07-10
cause: insight
supersedes: []
---

## Context

Dropping the capture `RightPanel` from a 3-column `QSplitter` body (→ left +
center only). A symbol grep for `RightPanel`/`_right_panel`/the refresh methods
passed clean, yet `test_toolbar_overflow_priority` and the on-screen tour still
broke, and the card compact-stats invariant flipped from PASS to FAIL.

## Lesson

Two removals hide from a class-name grep. (1) Splitter-column deletion breaks
*positional* assertions that key on the splitter + a numeric index, not the
removed class: `isCollapsible(2)` (silent warning → False) and `sizes[2]`
(hard IndexError), plus `setSizes([a,b,c])` extra-value drops. (2) The window's
`setMinimumSize(960, …)` was a TOOLBAR clamp (keep primary action + REC
indicator un-clipped), NOT a body constraint — with one fewer pane the lone
full-width cards stay ~490px wide at that 960 minimum, so a card width-threshold
feature (`_STATS_COLLAPSE_MIN_CARD_W = 430`) becomes UNREACHABLE by window
resize; its trigger regime moves to splitter distribution (widen the left pane
so the center drops below the threshold).

## How to apply

Before deleting a splitter column, grep `isCollapsible(`, `sizes\[`,
`setSizes(`, `\.count()`, and the splitter objectName across tests AND scripts
(the tour), then re-check any width-threshold feature whose collapse regime
relied on that column's width — if the window min-clamp belongs to a different
subsystem (toolbar), drive the regime via `splitter.setSizes` in the test, not
by resizing the window.
