---
role: pyqt-ui
tags: [qtabbar, settabvisible, overflow-menu, density, dynamic-property, unpolish, stylechange, sizehint-cache, currentchanged, index-identity, tab-drag, ordinal-label, view-tabbar, width-budget]
created: 2026-07-16
updated: 2026-07-16
cause: insight
supersedes: []
---

## Context

T3/T4 of the 12-View tab bar: kill `_sync_tabbar_width`'s `setFixedWidth`
(which told Qt the strip could never overflow, keeping the already-configured
`setUsesScrollButtons(True)` permanently inert) and add compact density +
a `»` overflow menu. §5.5 forbade `removeTab` because six call sites in
`view_tabbar.py` treat "QTabBar tab i" and `manager.views[i]` as one index.

## Lesson

Four Qt 5.15.2 facts, all measured, none guessable from the docs:

1. **`setTabVisible(i, False)` on the CURRENT tab emits `currentChanged`.**
   Qt moves the selection to a neighbour, so a bar that retires tail tabs on
   resize would silently switch the user's active View just because the window
   got narrower. Never hide the current tab — then the emit cannot happen by
   construction (do NOT paper over it with a `blockSignals`/suppress flag: that
   swallows the emit while leaving `currentIndex` desynced from the manager).
   Everything else about `setTabVisible` is safe for index identity: `count()`,
   `tabData()` and `tabText()` on a hidden tab all keep working, and
   `sizeHint()` sums only the VISIBLE tabs — which is what makes the
   hide-until-it-fits loop terminate.

2. **A QSS density flip needs an explicit `QEvent.StyleChange`.**
   `style().unpolish(w); style().polish(w)` after `setProperty("density", …)`
   updates `tabSizeHint(i)` (91→77px) but leaves QTabBar's CACHED layout — and
   therefore `sizeHint()` — at the OLD value (stayed 1110px). A fit decision
   that compares `sizeHint()` to a budget then reads the stale width and never
   degrades: a false green with no visible symptom. `QApplication.sendEvent(
   tabs, QEvent(QEvent.StyleChange))` is what runs `QTabBarPrivate::refresh()`.
   It is safe *here* only because `changeEvent` re-derives `usesScrollButtons`/
   `elideMode` from the style **unless the user set them** — `setUsesScrollButtons`
   in `__init__` marks the flag user-set. On a bar that never called it, the same
   StyleChange would silently reset scroll buttons.

3. **A positional label + the mid-drag `refresh()` ban = scrambled ordinals.**
   The §5.1 use-after-free guard skips `refresh()` during a live `tabMoved`
   because "nothing visible needs it" — true while labels are full names, which
   Qt's `moveTab` legitimately carries along with the tab. A *positional*
   compact label (the ordinal) breaks that premise: dragging tab 0 to slot 4
   leaves the strip reading `2,3,4,5,1`. Re-label on the drag's **mouse
   release** (an `eventFilter` on the QTabBar + `QTimer.singleShot(0, …)` so
   `mouseReleaseEvent` finishes first), never inside `tabMoved` and never on a
   bare next tick — both are still inside the live drag.

4. **`QTest.mouseMove` can never drive a tab drag.** It synthesizes
   `buttons() == NoButton`, and `QTabBar::mouseMoveEvent` returns immediately
   (calling `moveTabFinished`) unless LeftButton is held, so a "real drag" test
   built from `QTest.mousePress/mouseMove/mouseRelease` reorders NOTHING and
   passes vacuously. Send `QMouseEvent(MouseMove, pos, Qt.NoButton,
   Qt.LeftButton, …)` via `sendEvent` for the moves; press/release stay QTest.

Corollary on budgets (confirms `2026-07-10-facts-degrade-budget-from-measured-
not-literal-px`): the plan modelled a tab at the QSS `min-width: 58px` and the
old code comment said ~49px, but a real roomy tab measures **91px** — the
min-width never binds because icon + text + padding + margins already clear it.
Any threshold copied from either number sits on the wrong side of reality; derive
the fit from `sizeHint()` vs a budget measured off the live row.

## How to apply

Retiring tabs into an overflow menu: use `setTabVisible` (never `removeTab`)
whenever tab index == model index, skip the current tab in the hide loop, and
assert a resize emits NO `switch_requested`. When a QSS dynamic property changes
a QTabBar's metrics, send `QEvent.StyleChange` after unpolish/polish and verify
`sizeHint()` actually moved — assert the pre/post widths differ, or the degrade
branch is untested. If tab labels become positional, re-label on the drag's mouse
release, and drive drag tests with button-held `QMouseEvent`s, asserting the
order really changed before asserting anything else.
