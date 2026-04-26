---
role: pyqt-ui
tags: [qthread, worker, signal-slot, deadlock, testing]
created: 2026-04-25
updated: 2026-04-25
cause: insight
supersedes: []
---

## Context

Plan Task 7 introduced `FFTTimeWorker(QObject)` running on a
`QThread`. The plan's verbatim test code wired
`worker.finished.connect(thread.quit)` with default `AutoConnection`
and called `thread.wait(5000)` synchronously on the main thread.
`thread.wait` always timed out and the test failed with no error,
just a deadlock.

## Lesson

`thread.wait()` blocks the calling thread's event loop. When the
worker's `finished` signal is emitted on the worker thread and the
receiver slot lives on the main thread (e.g. `QThread.quit`, which
is owned by whichever thread created the QThread — usually the main
one), `AutoConnection` resolves to `QueuedConnection` — and the
queued post never drains, because the main thread is parked in
`thread.wait()`. The fix in standalone tests is `Qt.DirectConnection`
on slots documented as thread-safe (`QThread.quit`, `QThread.exit`,
`QThread.requestInterruption` per Qt docs); inside a real
`MainWindow` where the event loop is running, AutoConnection is
correct.

## How to apply

When writing a synchronous `thread.wait()` test for a
`QObject + moveToThread` worker, use `Qt.DirectConnection` for the
`worker.finished -> thread.quit` (and `failed -> thread.quit`)
connections. Production wiring inside a live MainWindow keeps
`AutoConnection`. If you find yourself adding `app.processEvents()`
loops to drain `thread.wait`, you have the wrong connection type.
