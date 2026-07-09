---
role: pyqt-ui
tags: [popover, sizehint, adjustsize, cjk, font-metrics, reused-widget, translucent, layout-activate, deferred-refit, min-size, wa-translucentbackground, health-strip]
created: 2026-07-10
updated: 2026-07-10
cause: insight
supersedes: []
---

## Context

A single `HealthPopover` (CursorPill-style `WA_TranslucentBackground` +
self-painted rounded bg) is REUSED across chips: clicking a chip swaps its
detail rows in place via `set_rows()`. The FIRST chip (HW) rendered full
size, but every SUBSEQUENT chip collapsed to a tiny box with the row LEDs
stacked/overlapping and all CJK key labels ("总线负载"…) invisible — even
though the exact same code path produced a correct box for HW.

## Lesson

Freshly-created CJK `QLabel`s report a font-less, near-zero `sizeHint`
**synchronously** — the CJK-substituted font is only applied on a deferred
`QEvent.Polish` (next event-loop tick), so `adjustSize()`/`resize(sizeHint())`
called right after `set_rows()` squashes the whole grid. The FIRST `show()`
of a freshly-constructed popover hides this because the show sequence forces a
polish+layout pass; a REUSED (already-visible, free-floating child) popover
gets no such pass, so it freezes at the collapsed size and a later
`processEvents()` only re-lays-out children *inside* the frozen frame (hence
the overlap). `layout().activate()`, `updateGeometry()`, and even
`ensurePolished()` do NOT fix the hint synchronously — only a real event-loop
tick does. Also note the "first show works" illusion is timing, not a special
first-widget property: HW only looked right because a `processEvents()` ran
before its grab.

## How to apply

For any reused/in-place-updated floating widget containing CJK (or any
lazily-substituted-font) text: (1) set a DETERMINISTIC `setMinimumSize` from
content count (`margins + title + n*row_h`) so it never collapses/overlaps
before the loop settles, then `resize(max(sizeHint, minimum))`; (2) schedule a
one-shot `QTimer.singleShot(0, refit)` (guarded by a `_refit_pending` flag)
that re-runs `layout().activate()` + resize + reposition once labels are
polished. Verify onscreen by opening the SECOND element of a reused overlay
(not just the first) and reading the saved PNG — the first-element grab masks
the bug entirely.
