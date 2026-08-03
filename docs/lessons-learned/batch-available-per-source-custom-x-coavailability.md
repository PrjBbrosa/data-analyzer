---
id: batch-available-per-source-custom-x-coavailability
status: active
owners: [codex]
keywords: [batch, time, custom-x, x-channel, target-policy, available-per-source, logical-source, sample-rate]
paths: [mf4_analyzer/batch.py, mf4_analyzer/ui/drawers/batch/sheet.py, mf4_analyzer/ui/drawers/batch/method_buttons.py, tests/test_batch_runner.py, tests/ui/test_batch_smoke.py]
checks: [git diff --check]
tests: [tests/test_batch_runner.py, tests/ui/test_batch_smoke.py, tests/ui/test_batch_method_buttons.py]
---

# Available-Per-Source Custom X Must Share a Logical Source With Its Target

Trigger: Changing Batch time-chart custom-X candidates, task expansion,
preview, or X-unit validation while the target policy is
`available_per_source`.

Past failure: The X picker used the intersection across every loaded logical
source. A container with multiple sampling-rate groups therefore displayed
every channel as partial and disabled it, even when the intended target and X
channel coexisted in one group. Enabling the union alone would instead create
missing-X task failures for the other groups.

Rule: For `available_per_source`, make a custom X selectable only when it
coexists with at least one selected target signal in a logical source. Filter
the same source/target pairs in the UI dry-run, X-unit validation, and runner
task expansion. Keep the all-source contract for common and exact-pair scopes.

Verification: Add a Qt test with two logical rows where target/X coexist in
only one row and assert the partial X is enabled, no false mixed-unit error is
reported, and dry-run lists only that row. Add a runner test that asserts the
missing-X row is skipped rather than failed. Run the focused UI/form tests,
the full `tests/test_batch_runner.py`, and `git diff --check`.
