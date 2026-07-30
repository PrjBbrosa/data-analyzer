---
id: codex-numeric-hazard-rate-needs-caller-path
status: active
owners: [codex]
keywords: [numeric, floating-point, hazard-rate, reproducer, caller, frame-to-nice]
paths:
  - mf4_analyzer/ui_kit/ticks_math.py
checks: [git diff --check]
tests: []
---

# Numeric Hazard Rates Need The Real Caller Path

Trigger: Using a numerical sweep or extracted-expression probe to justify a
production floating-point change.

Past failure: A bare `math.floor((m*p)/p) != m` probe reported 281 failures in
8010 inputs and that figure was attributed to `_frame_to_nice()`. Driving the
same domain through the real helper produced 114 material failures in 24360
cases, with a different signature: the guard loop inflated the span after a
one-division floor drop. An exact-equality last-bit reproducer was also mistaken
for a lost division.

Rule: Quote a hazard rate only for the path that will actually change. Exercise
the complete caller, classify impact in domain units, and distinguish harmless
ULP representation differences from behavior changes. If a proposed tolerance
changes additional cases, report that population too and move the change into a
separate investigation when its blast radius is not part of the active task.

Verification: Keep a caller-level reproducer, assert the material outcome (for
example span inflation or a >0.5-division shift), record numerator and
denominator for both baseline and candidate behavior, and run every consumer's
focused tests before modifying a shared numeric helper.
