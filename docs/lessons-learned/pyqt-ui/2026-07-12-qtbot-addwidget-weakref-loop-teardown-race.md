---
role: pyqt-ui
tags: [qtbot, addwidget, weakref, garbage-collection, eventfilter, presetbar, teardown-race, offscreen]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

## Context

A new narrow-pane geometry test constructed six real `Contextual` widgets
(3 classes × 2 pane widths) in one test function, reassigning the same
loop-local `ctx` name each iteration, then `.show()` + `qtbot.waitExposed()`
+ `qtbot.wait(20)` per widget. This crashed the Qt event loop with an
unrelated `AttributeError: 'PresetBar' object has no attribute '_load_btns'`
raised from `PresetBar.eventFilter`, even though `_load_btns = {}` is set
unconditionally at the top of `PresetBar.__init__` before any
`installEventFilter` call.

## Lesson

`qtbot.addWidget(widget)` (pytest-qt) stores only a `weakref.ref(widget)` for
end-of-test cleanup — it does **not** keep the widget alive. A test loop that
reassigns the same local name each iteration (`ctx = cls()`) drops the ONLY
strong Python reference to the previous widget, so it can be garbage
collected mid-test while its child buttons (which had
`installEventFilter(self)` registered on the PresetBar) still have events
in flight from the just-processed `show()`/`wait()`. The resulting crash
surfaces as a confusing unrelated `AttributeError` on the destroyed
object's instance state, not the expected `RuntimeError: wrapped C/C++
object has been deleted`.

## How to apply

When a test constructs multiple heavyweight widgets (especially ones with
`installEventFilter`-based hover/interaction machinery like `PresetBar`) in
a loop and calls `.show()`/`qtbot.waitExposed()`/`qtbot.wait()` on each,
keep every instance alive in an explicit list (e.g. `_keep_alive.append(ctx)`)
for the whole test — do not rely on `qtbot.addWidget`'s weakref bookkeeping
to prevent early GC. `ctx.hide()` at the end of each iteration is good
hygiene but the strong-reference list is the actual fix.
