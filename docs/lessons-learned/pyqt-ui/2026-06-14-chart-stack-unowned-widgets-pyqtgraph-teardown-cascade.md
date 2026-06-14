# chart_stack tests: un-owned ChartStack → pyqtgraph LabelItem teardown cascade

**Date:** 2026-06-14
**Status:** RESOLVED 2026-06-14 via a tracking autouse fixture (see "The fix
that works" below). Originally descoped from the review-fixes batch (C3) while
the canvas was mid-refactor; fixed once the drawer-collapse refactor settled.

## Symptom

`tests/ui/test_chart_stack.py` runs `76 passed, 8 errors`. The errors are all
TEARDOWN errors, not assertion failures:

```
ERROR at teardown of test_chart_stack_set_mode
TEARDOWN ERROR: Exceptions caught in Qt event loop:
  File ".../pyqtgraph/graphicsItems/LabelItem.py", line 132, in sizeHint
    if hint not in self._sizeHint:
AttributeError: 'LabelItem' object has no attribute '_sizeHint'
```

Each erroring test PASSES, then errors at teardown. Run any one of them in
isolation and it passes cleanly with no error — the failure is order-dependent.

## Root cause

~60 tests in this module construct `cs = ChartStack()` **without** `qtbot`
ownership and **without** spinning the event loop. ChartStack construction (its
pyqtgraph canvases) queues `QTimer.singleShot(0, ...)` layout callbacks
(quality-indicator positioning, heatmap-layout sync). Because the test never
calls `processEvents`, those callbacks stay queued.

At function return the test's local `cs` is dropped; CPython refcount-GC deletes
the C++ ChartStack tree (Python owns a parent-less QWidget), destroying the plot
title `LabelItem`s. pytest-qt's per-test teardown then calls
`qapp.processEvents()`, which fires the still-queued `singleShot` on a child
whose C++ is gone → pyqtgraph's `LabelItem.sizeHint` touches `self._sizeHint` on
a half-dead object → `AttributeError`. pytest-qt's Qt-exception capture records
it as a teardown error and attributes it to whichever test's loop fired it, so
it cascades across the trailing tests.

## What does NOT fix it

- A module `autouse` fixture that `processEvents()` after `yield`: by then `cs`
  is already GC'd, so it fires the bad callback itself — error just relocates.
- Adding `qtbot.addWidget(cs)` to only the currently-erroring tests: **whack-a-
  mole** — owning 7 dropped errors 8→4 but shifted them onto 4 previously-green
  tests. The leak is cumulative/ordering, not localized.

## The fix that works

A single module `autouse` fixture that monkeypatches `ChartStack.__init__` to
record every instance, then — at teardown — drains the event loop **while the
widgets are still referenced (alive)**, and only then `deleteLater()`s them:

```python
@pytest.fixture(autouse=True)
def _own_chartstacks(qapp, monkeypatch):
    created = []
    orig_init = ChartStack.__init__
    def _tracking_init(self, *a, **k):
        orig_init(self, *a, **k); created.append(self)
    monkeypatch.setattr(ChartStack, "__init__", _tracking_init)
    yield
    qapp.processEvents()          # fire queued callbacks on LIVE widgets
    for cs in created:
        cs.deleteLater()
    created.clear()
    qapp.processEvents()          # let deferred deletes complete
```

Why it works where the alternatives didn't: the cascade is caused by the local
`cs` being GC'd at function return (deleting the C++ tree) BEFORE the queued
callback fires. Holding a ref in `created` keeps every ChartStack alive past the
test body, so the drain fires the `singleShot` callbacks on live objects (no
`sizeHint` on a half-dead `LabelItem`), and the explicit `deleteLater` + drain
disposes them cleanly. Result: `76 passed, 0 errors` (was `76 passed, 9 errors`),
no per-test churn, no production change.

Rejected alternatives: a plain post-yield `processEvents` (cs already GC'd by
then — fires the bad callback itself); `qtbot.addWidget` on only the erroring
tests (whack-a-mole — shifts the error onto other previously-green tests).

## Scope note

Not introduced by the FFT/heatmap polish batch under review, nor by the A/B/C1/C2
fixes. The C1 commit removed the only real assertion FAILURES (stale Alt
shortcut asserts → Ctrl). These ERRORS predate the batch.
