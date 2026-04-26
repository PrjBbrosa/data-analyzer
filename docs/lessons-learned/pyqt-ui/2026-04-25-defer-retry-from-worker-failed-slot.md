---
role: pyqt-ui
tags: [qthread, worker, signal-slot, retry, qtimer, re-entry-guard]
created: 2026-04-25
updated: 2026-04-25
cause: insight
supersedes: []
---

## Context

T11 added an auto-retry path to `_on_fft_time_failed`: when the
analyzer raises a non-uniform-time-axis error, open the 重建时间轴
popover and (on Accept) call `self.do_fft_time(force=force)` again.
A naive synchronous retry inside the failed handler silently no-ops
because `do_fft_time` early-returns under its
`self._fft_time_thread.isRunning()` re-entry guard.

## Lesson

`worker.failed -> _on_fft_time_failed` is delivered as a queued slot
on the main thread. At that moment `worker.failed -> thread.quit`
has been queued but the worker QThread has NOT actually exited yet,
and `thread.finished -> _on_fft_time_thread_done` (the slot that
clears `self._fft_time_thread`) is still pending in the main-thread
queue. So `self._fft_time_thread.isRunning()` is still `True` inside
the failed handler — any synchronous redispatch of the same compute
hits the re-entry guard and is silently dropped.

## How to apply

When a worker-failed handler needs to retry the same compute on the
same QThread-owning host, defer the retry with
`QTimer.singleShot(0, retry)`. The 0-ms timer event is enqueued
behind the already-pending `thread.finished` slot, so by the time
`retry` runs, the cleanup slot has cleared the thread reference and
the re-entry guard lets the new dispatch through. Pair the deferred
retry with a one-shot instance flag (`_fft_time_retry_pending`) set
BEFORE scheduling the timer and cleared in the retry's `finally`,
so that a second consecutive failure does not loop the rebuild +
retry sequence.
