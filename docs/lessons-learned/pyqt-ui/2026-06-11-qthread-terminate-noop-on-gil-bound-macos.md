---
role: pyqt-ui
tags: [qthread, terminate, closeevent, qfatal, macos, pthread-cancel, gil, worker, offscreen]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context
closeEvent's order-thread drain needed the same `quit() + wait(2000)
→ terminate() + wait(500)` backstop as fft_time, because a COT job
with no cancel poll point that outlives wait(2000) leaves `QThread(self)`
running at destruction → Qt5 qFatal (`exit 134`,
"QThread: Destroyed while thread is still running").

## Lesson
On macOS, `QThread::terminate()` (pthread_cancel, deferred) only kills
a thread parked at a C cancellation point: a `QThread.msleep` run() died
in <2 s, but a GIL-holding numpy compute worker was still alive 20 s
after terminate, and a Python `time.sleep(10)` worker never died — so
the terminate fallback does NOT prevent the qFatal for compute-bound
PyQt workers on macOS (it does on Windows, where TerminateThread is
forceful). Also beware false verification: a "stuck" job must be
calibrated — my 2.5 s numpy job finished naturally inside wait(2000)
and masqueraded as terminate success until timed per-iteration.

## How to apply
When adding a terminate backstop for a Python worker, treat it as
Windows-only protection; the cross-platform fix is a cancel poll point
inside the compute loop (flag signal-processing-expert if that loop is
algorithm code). When verifying thread-teardown paths, calibrate the
stuck job's natural duration first (≥10× the wait budget) and
reproduce the qFatal (exit 134) on the old code before trusting a
green run on the new code.
