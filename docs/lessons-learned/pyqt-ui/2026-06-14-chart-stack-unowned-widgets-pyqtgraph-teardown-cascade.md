# chart_stack tests: un-owned ChartStack → pyqtgraph LabelItem teardown cascade

**Date:** 2026-06-14
**Status:** Known pre-existing issue, descoped from the 2026-06-14 review-fixes
batch (finding C3). The two stale-shortcut FAILURES (C1) are fixed; these
teardown ERRORS are a separate, module-wide infra issue.

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

## What WOULD fix it (deferred)

Give **every** `ChartStack()` in the module `qtbot` ownership (so pytest-qt keeps
it alive and drains its events at teardown before deletion), OR cancel/flush a
canvas's pending `singleShot` layout callbacks on destruction (production-side).
Owning ~60 constructions is large, mechanical churn and was deferred because
`heatmap_canvas.py` / `line_canvas.py` were being refactored in parallel (codex
`_CollapsedRail` / `_position_collapse_layout`), so a sweeping test edit risked
colliding. Do it as a dedicated test-infra pass when the canvas refactor settles
— ideally via a shared `chart_stack` fixture that all these tests adopt.

## Scope note

Not introduced by the FFT/heatmap polish batch under review, nor by the A/B/C1/C2
fixes. The C1 commit removed the only real assertion FAILURES (stale Alt
shortcut asserts → Ctrl). These ERRORS predate the batch.
