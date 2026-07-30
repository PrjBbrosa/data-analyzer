---
id: codex-overlay-wheel-anchor-invariants
status: active
owners: [codex]
keywords: [overlay, wheel, zoom, cursor-anchor, round-trip, pyqtgraph]
paths: [mf4_analyzer/ui/pg_canvas/overlay_axes.py, tests/ui/test_overlay_grid_ticks.py]
checks: [git diff --check]
tests: [tests/ui/test_overlay_grid_ticks.py]
---

# Codex Overlay Wheel Anchor Invariants

Trigger: Load when changing overlay wheel zoom, nice-step selection, tick
framing, or viewport-bound calculations in the pyqtgraph TimeDomain canvas.

Past failure: Span-only monotonic tests passed while Shift-wheel range bounds
were floored to the tick step. The span changed correctly, but equal in/out
gestures accumulated one-sided vertical drift. A free-phase correction then
preserved the cursor exactly but exposed unreadable tick values such as
`0.0283967`; formatting those tails separately led to significant-digit loss
and wider gutters.

Rule: Treat zoom span, cursor anchor, tick phase, and tick text as separate
invariants. Select the adjacent nice step, construct the raw cursor-anchored
lower bound, then round it to the nearest multiple of that step. Aligned values
are the read-out priority; the cursor value is allowed to move by at most half
of the new division. Never use one-sided `floor()` phase snapping. Test exact
round trips only from globally aligned nice-step frames; arbitrary external
ranges may normalize on the first notch. Format labels from the real tick and
active `per_div`, and make repin idempotent for an already aligned nice range.

Verification: Run `tests/ui/test_overlay_grid_ticks.py` with real and direct
off-center Shift-wheel cases. Require a half-division anchor bound,
integer-multiple tick values, equal-notch round trips from aligned nice frames,
strict span monotonicity for densities 3 through 20, unchanged X and gutter
scoping, truthful labels, plot/gutter width stability, and no-op repin. Then run
`git diff --check`.
