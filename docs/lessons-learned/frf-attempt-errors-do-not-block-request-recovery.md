---
id: frf-attempt-errors-do-not-block-request-recovery
status: active
owners: [codex]
keywords: [frf, validation, retry, view, pane, time-range]
paths:
  - mf4_analyzer/ui/inspector_sections/contextual_frf.py
  - mf4_analyzer/ui/main_window/_frf_mixin.py
checks:
  - git diff --check
  - Native styled FRF full-range selection and compute-button click
tests:
  - tests/ui/test_frf_validation_recovery.py
---

# FRF Attempt Errors Do Not Block Request Recovery

Trigger: Changing FRF validation, retry, range correction, or View/pane projection.

Past failure: Project restore reported an out-of-source range. Switching to full
cleared the execution range but retained the shared Inspector error and disabled
the compute button. Another View with identical compute parameters inherited it.
Tests checked the initial restore rejection, but omitted the correction/retry loop.

Rule: Separate a previous attempt's diagnostic from current pair/scope blockers.
A retry must enter normal range confirmation and preflight, never bypass them.
Transient diagnostics belong to the projected View, pane, composite sources,
physical range and compute parameters; changing that context discards them.
Display-only edits preserve them. Current missing/same/out-of-scope sources take
priority, and hidden or background failures cannot replace the focus status.
Do not persist transient diagnostics in project or preset state.

Verification: Exercise restore rejection → full/valid range → real button click,
cancel/confirm, same-parameter View switch, split and cross-View focus, pair
correction, display-only edits, and repeated invalid preflight with zero jobs.
