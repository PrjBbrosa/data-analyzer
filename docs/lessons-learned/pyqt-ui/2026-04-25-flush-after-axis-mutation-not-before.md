---
role: pyqt-ui
tags: [debounce, qtimer, xlim-changed, event-handler, ordering]
created: 2026-04-25
updated: 2026-04-25
cause: insight
supersedes: []
---

## Context
`TimeDomainCanvas._on_release` flushed a pending QTimer-debounced viewport
refresh BEFORE the rubber-band branch's `ax.set_xlim(...)` call. The
`set_xlim` synchronously fired matplotlib's `xlim_changed`, which our
listener turned into a freshly scheduled 40 ms QTimer — leaving a pending
debounce after the release returned and deferring the post-zoom envelope
frame.

## Lesson
A "drain pending work" call inside an event handler must run AFTER any
state mutation in the same handler that synchronously re-schedules the
same kind of pending work. With debounce + xlim_changed callbacks, the
ordering is `mutate → flush`, not `flush → mutate`. A `try/finally`
around the handler body gives a single tail-call flush that covers
every early-return path without bookkeeping.

## How to apply
Whenever a release/finalize handler both (a) drains a debounced refresh
and (b) calls a matplotlib axes mutator (`set_xlim`/`set_ylim`/
`set_xscale`/etc.) that you also listen to for change notifications,
put the flush in a `finally` block at the bottom of the handler. Verify
by asserting `_refresh_pending is False` AND `_refresh_timer.isActive()
is False` after the handler returns in a regression test.
