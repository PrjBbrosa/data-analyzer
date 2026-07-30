---
id: codex-overlay-free-phase-consumer-audit
status: active
owners: [codex]
keywords: [overlay, wheel, free-phase, tick-labels, auto-width, repin, pixel-delta]
paths:
  - mf4_analyzer/ui_kit/ticks_math.py
  - mf4_analyzer/ui/pg_canvas/overlay_axes.py
  - mf4_analyzer/ui/pg_canvas/line_canvas.py
  - mf4_analyzer/ui/pg_canvas/viewbox.py
checks:
  - git diff --check
tests:
  - tests/ui/test_overlay_grid_ticks.py
  - tests/ui/test_pg_line_canvas.py
  - tests/ui/test_pg_timedomain_canvas.py
---

# Overlay Phase Policy Changes Need A Consumer Audit

Trigger: Changing aligned/free-phase policy for an overlay or analysis Y-wheel
transform, or changing shared wheel-delta routing.

Past failure: Exact anchor and round-trip tests passed while free-phase float
tails made each auto-sized Y gutter wider and made the graticule unreadable.
Repin later reframed the valid span, and a shared delta bridge interpreted a
horizontal trackpad swipe as vertical zoom.

Rule: Keep viewport bounds, tick values, and tick text as separate concerns.
The current phase table is: Shift-wheel selects an adjacent nice step and rounds
the lower bound to its nearest multiple; cursor anchoring is bounded by half a
division; plain-wheel pan moves one aligned division; repin is a no-op for an
aligned nice range; initial/box/density framing may use `_frame_to_nice()`; and
`PgLineCanvas` applies one delivered cursor fraction to every time-preview axis.
Derive truthful labels from `per_div`, measure gutter/plot geometry, and dispatch
only vertical wheel components into Y behavior. Any future phase-policy change
must audit every consumer rather than changing only the range transform.

Verification: Run the overlay real-wheel label/alignment/repin tests, the
PgLineCanvas main/aux-gutter synchronization and exception-consumption tests,
the real horizontal pixel-wheel test, the three complete UI test modules listed
above, and `git diff --check`.
