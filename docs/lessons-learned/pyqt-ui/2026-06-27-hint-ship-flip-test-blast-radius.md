---
role: pyqt-ui
tags: [hints, quickref, ship-flip, test-blast-radius, mark-discovered, retire-on, soon-badge, context-list, plot-modes, surface-choice, nudge-vs-discovery, retire-coverage, mode-gating, degrade-regimes]
created: 2026-06-27
updated: 2026-07-16
cause: insight
supersedes: []
---

## Context

Releasing the staged 共轴 (shared-axis) hints — flip `coaxis.merge`/`coaxis.gesture`
from `ship="later"` to `now`, add `"subplot"` to their `plot_modes`, drop the
quickref `soon` badge, and wire the missing `mark_discovered("coaxis.merge")`
retire event in `MultiFileChannelWidget._on_context_menu` — under a change set
whose named test pathspec was only `test_hints.py` + `test_quickref.py`.

**2026-07-16 follow-up** — adding `view.compact_tabs` (the footer answer to "窄
窗口 View 标签只剩编号，悬停可看全名") after the 12-View tab bar landed. Same
registry, three further traps: which *surface* a situational-feeling hint may
use, how many *retire points* a degrade-mode hint needs, and which exact-match
lists a mode-gated addition can (not) shift.

## Lesson

A hint ship-flip's test blast radius is wider than the registry plus its own
width/staging tests, in three non-obvious ways: (1) adding a `plot_mode` to a
`surface="context"` hint silently shifts every EXACT-MATCH `context_hints` /
`rotation_hints` list assertion for those modes — the newly-surfaced id must be
appended in `_context_sort_key` order (tier S before A, then -priority), e.g.
`coaxis.gesture` lands AFTER `overlay.drag_y` and after `subplot.shift_y`.
(2) A SEPARATE panel-RENDERING test (`test_quickref_panel.py`) asserts the
rendered `即将` badge by `QLabel.objectName() == "quickrefSoon"` — it breaks
when `soon=True` is removed, yet lives outside the `quickref.py`-data test the
brief names. (3) `mark_discovered(settings, hint_id)` takes the HINT'S id
(`"coaxis.merge"`), NOT the `retire_on` descriptor string; `retire_on` is just
documentation — `discovery_hint` retires on `hint.id not in state.discovered`.

### 2026-07-16 addendum: adding a hint (three more non-obvious rules)

4. **`surface="nudge"` is only available to signals the CHART CARD owns.**
   A nudge predicate reads `HintState` fields, and the only thing that
   populates them is `_ChartCard._nudge_signals()` (canvas facts + stamped
   attributes). A confusion whose trigger lives in a *sibling* widget
   (`ViewTabBar` next to the card, not inside it) cannot be a nudge without new
   plumbing through `cards.py` — pick `surface="discovery"`, which reaches the
   same footer slot with no feed. "Feels situational" is not the deciding
   question; "who owns the signal" is.

5. **A degrade-mode hint needs one retire point per REGIME, not per feature.**
   The obvious `mark_discovered` site for the tab bar was the `»` overflow menu
   — and it is wrong on its own: compact and overflow are *different* regimes,
   and a row routinely compacts while `overflow_indices() == []` (measured: 10
   Views), so those users have no `»` to click and the hint nags forever. The
   symmetric trap is retiring on *entering* compact — that is the confusion
   moment itself, i.e. exactly when the hint must appear. Retire on the
   **taught gesture**: the compact tab's `QEvent.ToolTip` (gate on
   `_density_compact` + `tabAt(pos) >= 0`, don't consume it — Qt still shows the
   tip), plus the `»` menu. `mark_discovered` syncs QSettings to disk on every
   call and tooltips fire on every hover, so guard with a session flag.

6. **A mode-gated addition cannot shift the discovery exact-match lists.**
   Every ordering assertion in `test_hints.py` builds `HintState()` with the
   default `mode=""`, so a hint carrying `modes={"time"}` never matches them —
   the 06-27 shift rule bites `surface="context"`/rotation lists (which the
   tests DO drive per-mode), not `discovery`. Pin the new hint's queue seat with
   its own exact-match walk (`while (h := discovery_hint(walked))`) instead, or
   the priority choice is untested. `ship="now"` is the correct value whenever
   the feature is already in HEAD — `_is_shipped` filters `later` out of every
   surface, registering a hint that shows nowhere. `ship` also does not
   mechanically drive the quickref `soon` badge; that mirror is convention only,
   so a `now` hint beside an already-badge-free quickref row touches neither the
   `quickrefSoon` render test nor `test_no_soon_row_*`.

## How to apply

Before flipping any hint's `ship`/`plot_modes` (a recurring `/update-hints`
operation that maintains BOTH the footer and the quickref panel), grep ALL of
`tests/ui/` for the hint id AND the rendered-state objectName (`quickrefSoon`),
not just the registry's own test module; expect exact-match context/rotation
lists to need the newly-surfaced id appended. Run the panel-render test, not
only the catalog-data test. If a needed test file falls outside a brief's named
pathspec, fix it to keep the suite green and flag the pathspec deviation rather
than shipping a red test.

When ADDING a hint: choose the surface by asking who owns the trigger signal
(sibling widget → `discovery`, chart-card/canvas fact → `nudge`); enumerate the
degrade REGIMES the hint describes and give each one a retire point, rejecting
"entering the state" as a retire event; and verify on the real renderer that the
hint's own wording is true (grab the footer + the degraded widget in one frame —
`window.grab()` at a width that really compacts), because a hint whose text
misdescribes the state is invisible to every unit test.
