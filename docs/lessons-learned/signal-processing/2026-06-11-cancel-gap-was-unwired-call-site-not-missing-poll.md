---
role: signal-processing
tags: [cancel-token, plan-staleness, call-site-wiring, capability-gap, worker]
created: 2026-06-11
updated: 2026-06-11
cause: insight
supersedes: []
---

## Context

A flag-driven brief asked to "add cancel polling to
`COTOrderAnalyzer.compute`"; a `main_window.py` comment and a pyqt-ui
lesson both stated the COT loop "has no per-frame poll point". In fact
the analyzer had shipped `cancel_token` + a per-frame `_check_cancel()`
since its very first commit (917d3e42) — the only real gaps were
`do_order_time`'s job closure never passing
`cancel_token=worker.cancelled`, and a message outside the
`'... computation cancelled'` family used by `order.py`/`spectrogram.py`.

## Lesson

A "missing capability" premise can be stale in the PRESENT direction:
the algorithm may already expose the hook while a single call site fails
to wire it, and a comment written at that call site then propagates the
false "no poll point" claim into lessons and briefs. Cancellation bugs
in worker pipelines are as often wiring gaps (token never passed) as
algorithm gaps (no poll loop).

## How to apply

Before implementing a capability a brief claims is missing, grep the
target function's signature/body for the parameter first
(`grep -n "cancel_token" <module>`). If it exists, the task shrinks to
call-site wiring + contract alignment, locked by characterization tests
(never-true token => `assert_array_equal` bit-identity; counting token
=> mid-loop raise) — and fix the stale call-site comment so the false
premise stops propagating.
