---
role: signal-processing
tags: [batch, dispatch, supported-methods, plan-staleness, removal, gate-vs-handler]
created: 2026-04-27
updated: 2026-04-27
cause: insight
supersedes: []
---

## Context

`batch.BatchRunner.SUPPORTED_METHODS` was set to `{'fft', 'order_time',
'order_rpm', 'order_track'}` because the Wave-2 plan transcribed that line
verbatim. But two earlier commits on this branch (06d17a8 baseline and
cfb301b refactor) had already deleted the entire `order_rpm` chain — the
`_run_one` dispatcher only handles `fft`, `order_time`, `order_track`. Adding
`order_rpm` back into the gate set lets a stale preset slip past
`_expand_tasks` and fall through to the `else: raise ValueError` in
`_run_one` — silent / undefined behaviour disguised as "forward compat".

## Lesson

A method enum / `SUPPORTED_*` set is a gate that must be a strict subset of
what the dispatcher (e.g., `_run_one`) actually handles. When a plan
prescribes a verbatim source block, cross-check enums and sets against
recent `git log -- <path>` removals — plans are snapshots, and removed code
paths drift from "supported" to "ghost handler" between plan-write and
plan-execute.

## How to apply

Before pasting a plan-verbatim source block that defines a `SUPPORTED_*`
set, function-name registry, or method-dispatch enum: grep the current
dispatcher for each value (`grep -n "method == '<value>'"` or equivalent)
and run `git log -p --since=<plan-date> -- <module>` for any removal
commits. If a value has no live handler, drop it from the set and pin the
invariant with a one-line `assert SUPPORTED_X == {...}` regression test so
later plans can't silently re-introduce the ghost.
