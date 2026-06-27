---
role: pyqt-ui
tags: [hints, quickref, ship-flip, test-blast-radius, mark-discovered, retire-on, soon-badge, context-list, plot-modes]
created: 2026-06-27
updated: 2026-06-27
cause: insight
supersedes: []
---

## Context

Releasing the staged 共轴 (shared-axis) hints — flip `coaxis.merge`/`coaxis.gesture`
from `ship="later"` to `now`, add `"subplot"` to their `plot_modes`, drop the
quickref `soon` badge, and wire the missing `mark_discovered("coaxis.merge")`
retire event in `MultiFileChannelWidget._on_context_menu` — under a change set
whose named test pathspec was only `test_hints.py` + `test_quickref.py`.

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

## How to apply

Before flipping any hint's `ship`/`plot_modes` (a recurring `/update-hints`
operation that maintains BOTH the footer and the quickref panel), grep ALL of
`tests/ui/` for the hint id AND the rendered-state objectName (`quickrefSoon`),
not just the registry's own test module; expect exact-match context/rotation
lists to need the newly-surfaced id appended. Run the panel-render test, not
only the catalog-data test. If a needed test file falls outside a brief's named
pathspec, fix it to keep the suite green and flag the pathspec deviation rather
than shipping a red test.
