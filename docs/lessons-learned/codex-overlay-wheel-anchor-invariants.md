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
were floored to the tick step. The span changed correctly, but the data value
under an off-center cursor moved on every notch and equal in/out gestures
accumulated a one-sided vertical drift. After free-phase bounds fixed that drift,
fixed-precision labels exposed long float tails, four auto-sized Y gutters cut a
900 px plot from 568.9 px to 256.9 px, and a later repin expanded a valid 4.0 span
to 5.0.

Rule: Treat zoom span, cursor anchor, and tick projection as separate
invariants. Select the adjacent nice step for span, construct viewport bounds
directly around the delivered cursor fraction without phase quantization, then
derive ticks from those final bounds. Test exact round trips from nice-step
frames; arbitrary non-nice spans may normalize on the first notch and must not
be made reversible with hidden zoom history. Do not restore readable labels by
rounding the viewport phase: measured round-quantization failed 315 of 630 round
trips and accumulated 19 divisions of drift. Instead, format tick text from the
active division step, audit auto-width geometry, and make repin idempotent when
the current per-division value is already nice. Whenever bounds stop being
globally grid-aligned, audit every consumer of those bounds—not only the range
transform—including label formatting, auto-width, repin, and any reachable snap
path.

Verification: Run `tests/ui/test_overlay_grid_ticks.py` with real and direct
off-center Shift-wheel cases. Require anchor preservation at top/center/bottom,
equal-notch round trips from nice-step frames, strict span monotonicity for
densities 3 through 20, unchanged X and gutter scoping, compact unique labels,
plot/gutter width stability, and no-op repin for a free-phase nice-step range.
Then run `git diff --check`.
