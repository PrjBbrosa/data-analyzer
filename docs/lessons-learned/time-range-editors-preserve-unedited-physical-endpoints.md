---
id: time-range-editors-preserve-unedited-physical-endpoints
status: active
owners: [codex]
keywords: [time range, precision, spinbox, quantization, boundary alignment]
paths:
  - mf4_analyzer/ui/inspector_sections/persistent_top.py
  - mf4_analyzer/ui/main_window/analysis_time_range.py
  - mf4_analyzer/ui/main_window/_analysis_mixin.py
checks:
  - Native range editing and styled confirmation dialog inspection
  - git diff --check
tests:
  - tests/ui/test_analysis_time_range_intent.py
  - tests/ui/test_analysis_time_range_confirm.py
---

# Time Range Editors Preserve Unedited Physical Endpoints

Trigger: Editing, restoring or validating physical time endpoints through rounded numeric widgets.

Past failure: A source started at 0.0170556 s but the editor and error displayed 0.017. Editing only the end reparsed both displayed strings, making the unchanged start fail strict coverage. QDoubleSpinBox also rounds its minimum and maximum, so preserving only the projected value was insufficient.

Rule: Keep exact projected/committed values and limits with one widget owner; parse only edited endpoints. Full-versus-draft equivalence must match editor precision and must not erase intentional submillisecond selections. Keep physical coverage strict. Offer explicit overlap alignment with a preview, preserve already-covered endpoints, and revalidate all panes and source identities before any commit. Invalid, missing or disjoint sources cannot be repaired by an implicit tolerance.

Verification: Cover one-end editing, repeated valid steps, invalid text, exact boundary projection, negative times, near-full edits, stale proposals and multi-pane atomicity. Native styled dialogs must show readable deltas and fully fitting buttons; apply semantic button styles before measuring text widths.
