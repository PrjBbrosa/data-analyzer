---
role: pyqt-ui
tags: [pyqtgraph, perf, narrow-y, raster-fill, envelope, bucket-count, range-key, y-span, aa-gate, wall-guard, time-domain, display-only]
created: 2026-06-23
updated: 2026-06-23
cause: insight
supersedes: []
---

# Universal data≫Y-window wall guard: fold Y-span into the range key, and preserve the wall flag on a cache-HIT refresh

## Context
The two earlier narrow-Y bucket caps (`renderer._effective_pixel_width`) key off
STATIC density only — overlay channel COUNT and subplot decimation ratio
(`source_len/pixel_width`). They never see the GENERAL trigger of the 满高竖线墙:
a curve whose data amplitude far exceeds its current Y view window (single dense
channel manually zoomed to a thin Y band, box-zoom Y, scroll-zoom Y, a stale
narrow Y carried across a view switch). All such paths funnel into ONE
`setData` per line in `_refresh_visible_data`, which read NO Y range, so no
guard could fire.

## Lesson
Add a per-line "data extent vs Y window" guard at the single `setData`
convergence point: `data_span` comes FREE from the envelope's own min/max
(`np.isfinite(env_s)` then max−min), `y_span` from `axis_facade.get_ylim()`;
when `data_span/y_span > K` (K=4.0 empirical) recompute the envelope ONCE at a
capped width and hold AA off. Two non-obvious mechanics make or break it:
(1) THE RANGE-KEY TRAP — `_refresh_visible_data`'s cache key was
`_quantize_range_key(name, xlim, effective_width)`, i.e. X-only. A pure-Y narrow
leaves xlim AND effective_width unchanged, so the key matches and the refresh is
gated out as a no-op — the guard never runs. Fold a quantized Y-span bucket into
the key (APPEND it: `key + (y_key,)`, do NOT nest as `(x_key, y_key)`, or every
consumer that reads `key[0]==channel` breaks). Quantize y_span on a LOG grid
(`round(log2(y_span)*30)`) so a real Y zoom always crosses a bucket boundary but
sub-percent autorange jitter on a static window stays put. (2) THE CACHE-HIT
STATE TRAP — once you DO gate the wall frame out (key unchanged, still narrow Y),
the per-frame `frame_wall` flag would reset to False and the idle-AA timer
re-arms AA over the still-present wall. Persist a per-line `_line_wall_state`
dict and, on a cache HIT, OR its stored value back into the frame flag so AA
stays off until the user actually widens Y. Wire the flag into the EXISTING AA
gate (`_idle_aa_density_ok` hard-fails on `_y_overflow_wall_active`) — do not
build a second AA pathway. This is a PURE display-only perf guard: it changes no
Y range, no autorange, no data; it only reduces drawn strokes + holds AA for the
wall frame. The recompute cost is paid ONLY in the wall case (ms-level numpy
over the window); normal frames (data hugs window) skip it entirely.

## How to apply
For any "narrow-Y / data-overflows-viewport makes a pyqtgraph dense trace slow"
兜底: put the guard at the single envelope `setData` site, derive data_span from
the envelope min/max (free), and BEFORE trusting it, audit the refresh cache key
— if it omits the axis (Y here) the guard silently no-ops on axis-only changes,
so fold a quantized bucket of that axis in (appended, log-quantized) AND
preserve the guard's per-line decision across cache-HIT no-op refreshes or the
AA gate flickers back on. Prove load-bearing by neutralizing the predicate
(`return False`) → the e2e wall-flag/cap tests must go RED. Mac offscreen has no
paint-ms delta for the transient (Windows event-loop timing), so lock by
mechanism: assert `_y_overflow_wall_active`, displayed-point cap, and
`_idle_aa_density_ok() is False`.
