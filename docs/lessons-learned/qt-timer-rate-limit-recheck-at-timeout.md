---
id: qt-timer-rate-limit-recheck-at-timeout
status: active
owners: [codex]
keywords: [qt, qtimer, rate-limit, monotonic, pyqtgraph, interaction]
paths:
  - mf4_analyzer/ui/pg_canvas/canvas.py
checks:
  - rg -n "_COARSE_REFRESH_MS|_last_coarse_refresh_at|_run_coarse_refresh" mf4_analyzer/ui/pg_canvas/canvas.py
tests:
  - tests/ui/test_pg_timedomain_canvas.py::TestInteractiveRefreshScheduler::test_drag_leaving_buffer_gets_rate_limited_coarse_coverage
---

# Qt Timer Rate Limits Need A Timeout-Time Guard

Trigger: Implementing or reviewing a hard interaction refresh-rate ceiling with
`QTimer` and a monotonic timestamp.

Past failure: The coarse TimeDomain refresh scheduled the remaining interval in
rounded milliseconds but did not recheck elapsed time when the timer fired.
Qt consistently woke early enough for six refreshes in about 0.54 seconds,
violating the stated 10 Hz ceiling even though the scheduling math looked right.

Rule: Treat a Qt timer delay as an earliest-request hint, not proof that a hard
rate limit elapsed. At timeout, re-read the monotonic clock and defer again when
the minimum interval has not passed. Do not weaken the test count to hide early
wakeups.

Verification: Run the focused scheduler test repeatedly and verify every pair of
recorded coarse refresh timestamps is separated by at least the configured
interval (with only an explicit, documented clock-resolution tolerance).
