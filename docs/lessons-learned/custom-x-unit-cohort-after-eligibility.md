---
id: custom-x-unit-cohort-after-eligibility
status: active
owners: [codex]
keywords: [pyqt, timedomain, custom-xaxis, unit-cohort, time-range, finite-mask]
paths: [mf4_analyzer/ui/time_xaxis.py, mf4_analyzer/ui/main_window/window.py]
checks: ["TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. '/Users/donghang/Downloads/data analyzer/.venv/bin/python' -m pytest tests/ui/test_main_window_smoke.py::test_custom_xaxis_unit_cohort_uses_only_range_finite_sources tests/ui/test_main_window_smoke.py::test_custom_xaxis_empty_unit_cohort_does_not_fall_back_to_first_provider -q"]
tests: [tests/ui/test_main_window_smoke.py::test_custom_xaxis_unit_cohort_uses_only_range_finite_sources, tests/ui/test_main_window_smoke.py::test_custom_xaxis_empty_unit_cohort_does_not_fall_back_to_first_provider]
---

# Custom X Unit Cohort Follows Drawable Eligibility

Trigger: Changing multi-source TimeDomain custom-X range filtering, finite-X
masking, unit compatibility, or rendered X-axis unit selection.

Past failure: Unit voting happened before the active acquisition-time range and
finite-X checks. A numerically larger unit group with no drawable X values in
the selected range could suppress the only drawable group and produce an empty
plot. The result unit also collapsed a known empty unit to the same sentinel as
an unresolved unit, allowing the title to borrow an unrelated provider's unit.

Rule: Establish each source's actual drawable eligibility after acquisition-time
masking and finite-X validation, then select the largest normalized-unit cohort
from eligible sources only. Preserve three states for the result unit: unresolved,
known empty, and known non-empty; never treat an empty unit as a wildcard or as
permission to fall back to another provider.

Verification: Run the two targeted offscreen regressions. They prove that an
in-range drawable `deg` source wins over two out-of-range/non-finite `rpm`
sources, and that a winning empty-unit cohort renders without borrowing `rpm`
for the axis title.
