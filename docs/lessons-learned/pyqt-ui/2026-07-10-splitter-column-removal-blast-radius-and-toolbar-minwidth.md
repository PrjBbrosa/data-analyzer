---
role: pyqt-ui
tags: [splitter, pane-removal, blast-radius, min-width, toolbar-clamp, width-threshold, index-assertion, compact-stats, cockpit, screenshot-evidence, md5, false-green, view-tabbar]
created: 2026-07-10
updated: 2026-07-16
cause: insight
supersedes: []
---

## Context

Dropping the capture `RightPanel` from a 3-column `QSplitter` body (→ left +
center only). A symbol grep for `RightPanel`/`_right_panel`/the refresh methods
passed clean, yet `test_toolbar_overflow_priority` and the on-screen tour still
broke, and the card compact-stats invariant flipped from PASS to FAIL.

**2026-07-16 recurrence (View tab bar T3/T4).** The same trap produced FALSE
SCREENSHOT EVIDENCE. "Narrowing" proof for "the tab strip compresses before the
right-hand actions yield" was two `win.resize()` frames at 1000px and 960px —
but `MainWindow.minimumWidth()` is 1100, so both landed on the identical real
width and the two PNGs were **byte-identical (same md5)**. The run's own log
printed `bar w=546` twice and it read as "consistent behaviour" instead of "the
second resize never happened", so the acceptance criterion had zero evidence
behind it while looking fully evidenced.

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

The 2026-07-16 recurrence adds the *evidence* half: an outer min-clamp does not
just make a width feature untestable, it makes narrowing **screenshots** silently
duplicate. A rendered-evidence set is only evidence if the frames can prove they
differ — identical md5 across two "different" widths means the width never moved,
NOT that behaviour is width-stable. Read the ACTUAL width back (`win.width()` /
`bar.width()`) after every resize and assert it reached the target; a request is
not a measurement. In this app the ViewTabBar's width IS the centre splitter
column (`bar.width() == ChartStack.width()`), so `splitter.setSizes([left,
centre, right])` drives it far below the 1100 window clamp (816→646→546→500→460→
420→400, all distinct), while `ChartStack.setMinimumWidth(400)` is the real floor.

## How to apply

Before deleting a splitter column, grep `isCollapsible(`, `sizes\[`,
`setSizes(`, `\.count()`, and the splitter objectName across tests AND scripts
(the tour), then re-check any width-threshold feature whose collapse regime
relied on that column's width — if the window min-clamp belongs to a different
subsystem (toolbar), drive the regime via `splitter.setSizes` in the test, not
by resizing the window.

For any narrowing/width screenshot set: name each frame by its MEASURED width,
write the measured geometry to a JSON sidecar beside the PNGs, and fail the run
when two frames share an md5 or when fewer than N distinct widths were reached.
Identical output across two requested widths is the signature of an outer
`minimumWidth`/`minimumSizeHint` clamp — find the clamp (often a child's
`minimumSizeHint`, not an explicit `setMinimumWidth`) and drive the container
directly instead.
