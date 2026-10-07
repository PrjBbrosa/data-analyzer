---
id: pin-tests-must-cover-real-creation-and-source-roles
status: active
owners: [codex]
keywords: [FRF, pinned cursor, source roles, pin creation, physical Hz]
paths:
  - mf4_analyzer/ui/pg_canvas/frf_canvas.py
  - mf4_analyzer/ui/chart_stack/pinning/sampling.py
checks: [git diff --check]
tests:
  - tests/ui/test_frf_pinning.py
---

# Pin tests must cover real creation and source roles

Trigger: Adding Pin support to an analysis canvas or changing its sampling/identity adapter.

Past failure: FRF sampling and overlay geometry tests passed with prebuilt pin records, while real P-button and keyboard creation produced no records. FRF samples had no source bindings and single hover had no physical-frequency query. Successful creation also lacked the live-line consume seam.

Rule: Test real creation before seeded restore/geometry. Keep source identities and input/output roles separate from magnitude, phase, and coherence rows. Preserve physical Hz on log axes, consume live lines without changing mode or A/B placement, and refuse to resample a pin against a different source pair.

Verification: `tests/ui/test_frf_pinning.py` covers button/keyboard creation, linear/log Hz, source-role identity, dedupe, live consume, empty replacement/restore, and mismatched-source resampling. Native Cocoa screenshots and actions verify the real widget path; Windows frozen acceptance is separate.
