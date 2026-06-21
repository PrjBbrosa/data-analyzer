---
role: signal-processing
tags: [order, cot, phantom-field, guard-test, compute-contract, tdd, consumption-map]
created: 2026-06-21
updated: 2026-06-21
cause: insight
supersedes: []
---

# Promoting a carry-through field to a real compute input requires a simultaneous guard-test update

## Context

`COTParams.time_res` was classified as a "phantom" carry-through field (the
guard test listed it in `_COT_NOT_CONSUMED`) because `COTOrderAnalyzer.compute`
hardcoded `hop_angle = nfft * 0.25` and never read it. Task 5 wired
`time_res → hop_angle` via `round(time_res / dt_angle)`. Without updating
`_COT_NOT_CONSUMED → _COT_CONSUMED_BY_COMPUTE`, the introspection guard
`test_cot_consumed_fields_are_actually_read_by_compute` would have silently
passed (it only checks the consumed set, not the not-consumed set), while
`test_cot_consumption_map_partitions_every_field` would have continued to
classify `time_res` as non-consumed — contradicting the implementation.

## Lesson

When a "carry-through" / not-consumed dataclass field is promoted to a genuine
compute input, the consumption-map guard must be updated in the SAME commit:
move the field from the not-consumed set to the consumed set. Failing to do so
creates a silent contradiction: the introspection guard reports the field as
non-consumed while the implementation reads it, so cache-key audits will
produce incorrect conclusions. The TDD RED test (two different `time_res` values
produce the same `n_frames`) is the reliable signal that the field is still a
phantom; promotion is complete only when that test goes GREEN.

## How to apply

Whenever you move a field from a "carry-through" exemption set to the real
compute inputs: (1) wire the field in `compute()`, (2) update the guard-test
consumption map in the same diff, (3) verify `test_cot_consumed_fields_are_actually_read_by_compute`
passes on the promoted field. Use a behavior-level TDD test (two inputs →
strictly different outputs) rather than a branch-coverage test to prove the
wiring is live, not just reachable.
