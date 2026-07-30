---
id: codex-nice-step-tolerance-checks-neighbors
status: active
owners: [codex]
keywords: [nice-step, tolerance, repin, floating-point, overlay]
paths:
  - mf4_analyzer/ui_kit/ticks_math.py
  - mf4_analyzer/ui/pg_canvas/overlay_axes.py
checks:
  - git diff --check
tests:
  - tests/ui/test_overlay_grid_ticks.py
---

# Nice-Step Tolerance Must Check Neighboring Candidates

Trigger: Adding an approximate nice-step guard around a helper that deliberately
returns the smallest nice value greater than or equal to its input.

Past failure: A repin idempotence guard compared only `_nice_per_div(raw)` with
`raw`. For `8.000000005`, the ceiling-oriented helper returned `10`, so a value
within the required relative tolerance of `8` was treated as non-nice and a
free-phase range was moved from `(0.317, 80.31700005)` to `(0, 100)`.

Rule: When approximate equality is intended, compare the raw value with both the
ceiling nice candidate and its lower adjacent nice candidate. Keep exact range
bounds when either comparison passes; do not replace the active step with the
candidate merely because it is close.

Verification: Test mantissa-boundary noise such as `8.000000005` through the real
repin path, assert the exact free-phase range remains unchanged, run the complete
overlay grid-tick suite, and run `git diff --check`.
