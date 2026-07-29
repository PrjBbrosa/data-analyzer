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
accumulated a one-sided vertical drift.

Rule: Treat zoom span, cursor anchor, and tick projection as separate
invariants. Select the adjacent nice step for span, construct viewport bounds
directly around the delivered cursor fraction without phase quantization, then
derive ticks from those final bounds. Test exact round trips from nice-step
frames; arbitrary non-nice spans may normalize on the first notch and must not
be made reversible with hidden zoom history.

Verification: Run `tests/ui/test_overlay_grid_ticks.py` with real and direct
off-center Shift-wheel cases. Require anchor preservation at top/center/bottom,
equal-notch round trips from nice-step frames, strict span monotonicity for
densities 3 through 20, unchanged X and gutter scoping, then run
`git diff --check`.
