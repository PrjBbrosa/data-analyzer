---
role: pyqt-ui
tags: [qdialog, accept, reject, windowdeactivate, race, idempotency, popover, focus-out, offscreen]
created: 2026-04-26
updated: 2026-04-26
cause: insight
supersedes: []
---

## Context

`RebuildTimePopover` is a frameless `QDialog` that pairs an explicit
accept/reject pair of buttons with a `QEvent.WindowDeactivate`-driven
focus-out auto-close (the popover should self-close when the user
clicks elsewhere). On macOS Cocoa, clicking 确定 produced
`QDialog.Rejected` from `exec_()` even though the user actually
clicked the accept button — so the host
(`MainWindow._show_rebuild_popover`) skipped
`fd.rebuild_time_axis(new_fs)`, the time axis stayed non-uniform, and
the next compute popped the same toast again. The user was stuck in a
loop with no way out.

Trace of the failing sequence:

1. `btn_ok.clicked → self.accept() → done(Accepted)` sets the result
   code to `Accepted` and synchronously calls `hide()`.
2. `hide()` synchronously dispatches `QEvent.WindowDeactivate` to the
   dialog **while `isVisible()` is still `True`** (the visibility
   flag has not been flushed yet on this platform).
3. The custom `event()` saw `WindowDeactivate && self.isVisible()`
   and called `self.reject()`.
4. `reject() → done(Rejected)` overwrote the prior `done(Accepted)`.
5. `exec_()` returned `Rejected`.

## Lesson

`QDialog.done(r)` is **not idempotent**: a second `done(r')` after the
first one silently overwrites the result code. Any "auto-close on
WindowDeactivate" handler that calls `reject()` from inside the event
loop must be guarded against re-entry from the very `accept`/`reject`
path that just set the result. The simplest guard is an `_is_closing`
boolean flipped by `accept`/`reject` overrides, checked in `event`
before the auto-reject fires.

A subtler trap: under `QT_QPA_PLATFORM=offscreen` with
`qtbot.addWidget`, the platform plugin does NOT synthesize a
`WindowDeactivate` during `hide()` — so a literal `btn_ok.click()`
inside a regression test will return `Accepted` and silently fail to
catch the bug. To lock the timing in CI, drive the race manually:
`pop.accept()` → `pop.show()` (re-establish `isVisible() == True`
without resetting the result code) → `pop.event(QEvent(QEvent.WindowDeactivate))`.
That recreates the macOS Cocoa state (`result == Accepted`,
`isVisible() == True`, deactivate fires) without depending on
platform-level event generation.

## How to apply

Whenever a custom `QDialog` (frameless popover, modeless tool
window, etc.) overrides `event()` to auto-close on a focus-out
event:

1. Add an `_is_closing` flag to the dialog and override `accept` and
   `reject` to flip it before calling `super()`.
2. Gate the auto-close branch in `event` on `not self._is_closing` in
   addition to whatever visibility/state check it already has.
3. In tests, do NOT rely on a literal button click + `exec_()` to
   reproduce the race under offscreen Qt + qtbot. Instead drive the
   sequence manually: set the result code via `accept()`, restore
   `isVisible() == True` with `show()`, then call `event()` directly
   with a constructed `WindowDeactivate`. Verify
   `pop.result() == QDialog.Accepted` survives.
4. Keep a third regression case for the focus-out path with no
   pending close: `event(WindowDeactivate)` on a freshly-shown
   dialog must still call `reject()`. The fix MUST NOT regress the
   original "click outside the popover dismisses it" intent.
