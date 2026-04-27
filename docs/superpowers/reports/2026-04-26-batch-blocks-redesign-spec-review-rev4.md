---
# Spec Review Rev 4 — Batch Blocks Redesign

**Verdict:** approved

## NF-3 Status: resolved

Verified §4.3 phase 1: lines 331-339 define `has_any_runnable = any(...)` across `files_iter` and `preset.target_signals`, then `if not has_any_runnable: return`, with the comment that this produces `BatchRunResult(status='blocked', blocked=['no matching batch tasks'])`. Verified §4.3 phase 2: lines 341-347 yield the full `(file x signal)` cartesian product only after at least one runnable pair exists, and lines 342-343 state missing pairs fail in `_run_one` as `"missing signal: X"`.

Cross-checks pass: §6.2.1 lines 521-524 maps `_expand_tasks` producing 0 tasks to `BatchRunResult(status='blocked', blocked=['no matching batch tasks'])`; §7 lines 565-566 keeps partial-missing imported `target_signals` runnable while all-unavailable `target_signals` disables Run; §8 lines 588-589 requires all-missing `target_signals` to be blocked and partial-missing `target_signals` to produce `task_failed` rows.

## Remaining Issues

None.

## Summary

Rev 4 resolves NF-3: the runner now has a backend all-missing guard, a zero-task blocked path, and matching partial-missing behavior across error handling and tests. No new cross-section inconsistencies were found in the requested sections.
---
