---
role: signal-processing
tags: [testing, decoder, timestamp, dto, regression-gap, evidence-quality]
created: 2026-05-19
updated: 2026-05-19
cause: rework
supersedes: []
---

# "Branch reached" is not "behavior correct" — assert the values, not the path

## Context

The prior real-A2L follow-up report (`reports/2026-05-19-stage-8-real-a2l-followup-report.md`) cited `tests/test_dto_decode.py::test_decode_no_timestamp_uses_base` as proof that `daq_timestamp_size = 0` was "handled" and downgraded the fix to a PR-4 bench cross-check. The test was real and green. The next chain scan found that `decode_dto` actually returned `base_monotonic_s` (a single fixed value captured at session start) for every sample across an entire recording — the MF4 time axis collapsed to a single point. The test had only proved the `timestamp_size == 0` branch executed; it had not proved that the resulting timestamps were useful.

## Lesson

A decoder test that asserts `samples == [(name, base_value, payload)]` for a single frame demonstrates the code path was reached, not that the time-series output is correct. Time-series correctness requires showing that consecutive inputs at different times produce different outputs — i.e. two frames driven at different arrival moments yield strictly increasing timestamps. The single-frame assertion is a tautology when the constant is the input: a decoder that returns `base_monotonic_s` regardless of frame content trivially satisfies it.

When the next layer up (a follow-up report, a downstream PR plan, a code review) cites such a test as "handled", the citation propagates the gap. The real T1-5 coverage now uses three orthogonal asserts:
1. `frame_arrival_monotonic_s` provided → that arrival becomes the sample timestamp.
2. Two arrivals 10 ms apart → second sample timestamp > first by ≈10 ms (the property-level claim).
3. ECU clock present (`timestamp_size > 0`) + arrival hint provided → ECU clock wins (no override).

## How to apply

When testing any decoder where the output is a function of time-varying input state (timestamps, sequence numbers, cumulative counters): write at least one test that drives the decoder twice with *different* input states and asserts the outputs **differ** in the expected direction. Do NOT rely on a single-frame "branch executed" assertion to cover the contract. When a follow-up report cites a test as evidence for a "handled" condition, grep the test body for `>` / `!=` / `len(set(...))` style multi-frame assertions before accepting the claim.
