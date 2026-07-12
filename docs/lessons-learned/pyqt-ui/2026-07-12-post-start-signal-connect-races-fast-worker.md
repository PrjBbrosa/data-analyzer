---
role: pyqt-ui
tags: [qthread, pyqtsignal, race-condition, cross-thread, connect-order, batchrunner, test-flakiness]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

## Context

A `BatchSheet._on_run_clicked` regression test (dB-reference-defaults Task 10
Part A) needed the final `BatchRunResult` after driving the LIVE click
handler (which internally builds the `BatchRunnerThread` and calls
`thread.start()`). The first draft connected a spy AFTER the click handler
returned: `sheet._on_run_clicked(); sheet._runner_thread.finished_with_result
.connect(results.append); qtbot.waitUntil(lambda: len(results) == 1)`. It
passed in isolated runs, but is a genuine, silent race.

## Lesson

`pyqtSignal.emit()` dispatches only to receivers connected AT THE MOMENT of
emission. `thread.start()` hands the worker's `run()` to a real OS thread
that can execute concurrently with the Python code immediately following
`start()` — if that worker thread finishes fast enough (a small single-file
FFT job easily can) and calls `self.finished_with_result.emit(result)` BEFORE
the main thread's next line executes `.connect(...)`, the one-shot signal is
gone: nothing was listening at emission time, so the spy never fires and
`qtbot.waitUntil` times out. This is invisible in a quick/isolated test run
(the window between `start()` returning and the following Python line is
often just wide enough) but is a real, reproducible flake under load or on a
faster machine — not a hypothetical concern to wave away.

## How to apply

Never connect a listener to a `QThread`-owned signal AFTER the code path that
calls `thread.start()`. If the thread is built and started INSIDE a method
you don't control the internals of (e.g. a click handler), do not try to
grab `host._runner_thread` and connect post-hoc — instead read the result
back through whatever state the HOST's OWN handlers already stash safely
(those were connected before `start()`, by construction). Concretely: poll
`host._running is False` (bound to the safe `QThread.finished` signal, wired
pre-start) and then read `host._last_result`, mirroring this project's own
established `test_sheet_cancel_button_unlocks_editing` convention, rather
than inventing a second, racy listener.
