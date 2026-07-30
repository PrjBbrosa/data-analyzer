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

# Overlay Free-Phase Changes Need A Consumer Audit

Trigger: Changing an overlay or analysis Y-wheel transform from globally aligned
bounds to cursor-anchored free-phase bounds, or changing shared wheel-delta routing.

Past failure: Exact anchor and round-trip tests passed while free-phase float tails
made each auto-sized Y gutter wider, collapsing the plot area. Repin later reframed
the valid span, and a shared delta bridge interpreted a horizontal trackpad swipe as
vertical zoom.

Rule: Keep viewport bounds, tick values, and tick text as separate concerns. Derive
compact labels from `per_div`, measure the resulting gutter/plot geometry, keep repin
idempotent for an already-nice step, synchronize every canvas that pins ticks, and
dispatch only vertical wheel components into Y behavior. Do not quantize the viewport
phase merely to make labels look round.

Verification: Run the overlay real-wheel compact-label and repin tests, the
PgLineCanvas time-preview tick/aux synchronization test, the real horizontal pixel
wheel test, the three complete UI test modules listed above, and `git diff --check`.
