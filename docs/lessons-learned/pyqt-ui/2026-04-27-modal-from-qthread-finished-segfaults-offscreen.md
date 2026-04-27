---
role: pyqt-ui
tags: [qmessagebox, qthread, offscreen, segfault, testing, isvisible]
created: 2026-04-27
updated: 2026-04-27
cause: insight
supersedes: []
---

## Context

W6 wired `BatchSheet._on_thread_finished` (slot for `QThread.finished`)
to call `_show_result_toast`, which used `QMessageBox.information(...)`.
Under `QT_QPA_PLATFORM=offscreen` on Windows, the cancel test invoked
`qtbot.waitUntil(lambda: sheet._running is False, ...)`; when
`_on_thread_finished` ran inside that nested wait loop, opening the
modal `QMessageBox` produced a `Windows fatal exception: access
violation` instead of just blocking.

## Lesson

Opening a modal `QMessageBox` (even via the non-modal `.show()`) from a
slot dispatched through a nested `qtbot.waitUntil`/`exec_` loop on the
Windows offscreen Qt platform is unsafe — the window-system layer trips
on the missing real surface during the modal's own paint pump. A
non-blocking `.show()` does not save you, because the box still tries to
paint immediately. The only reliable cross-platform guard is to skip the
toast entirely when the host dialog is not currently visible
(`if not self.isVisible(): return`), which also matches user intent (no
sense popping a toast on a hidden dialog).

## How to apply

Any user-facing toast / message box driven by a worker-thread completion
signal should gate on `self.isVisible()` (or another "are we actually
shown?" predicate) before constructing the message box. This keeps unit
tests passing under offscreen Qt without changing production semantics —
production paths always have `isVisible() == True` because the dialog
was opened via `exec_()` / `show()` before the run started.
