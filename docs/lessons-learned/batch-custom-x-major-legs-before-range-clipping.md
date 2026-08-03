---
id: batch-custom-x-major-legs-before-range-clipping
status: active
owners: [codex]
keywords: [batch, chart-statistics, custom-x, hysteresis, noise, range, finite]
paths: [mf4_analyzer/batch_statistics.py, tests/test_batch_statistics.py]
checks: [git diff --check]
tests: [tests/test_batch_statistics.py, tests/test_batch_runner.py]
---

# Batch Custom-X Statistics Need Major Legs Before Range Clipping

Trigger: Changing Batch time-chart statistics for channel-backed X, especially
hysteresis detection, custom ranges, or in-chart diagnostics.

Past failure: The implementation clipped to the selected X range and then
classified every adjacent `dx` sign. Quantisation chatter, finite-data gaps,
and short boundary visits were turned into many false physical reversals, while
full-range lead-in remnants created a spurious third path.

Rule: Split finite acquisition segments first; derive a data-only turn policy,
confirm and merge major legs in acquisition order, then clip each leg to the
statistics range. Keep raw in-range X/Y sample pairing for values and markers.
Treat undersized contributions as non-paths, but retain their data in the
single-row fallback. Do not derive the turn threshold from selection bounds.

Verification: Run `tests/test_batch_statistics.py` for noisy cycles, full-range
short residues, finite gaps, narrow ranges, and repeated paths; run the
statistics-focused runner tests to confirm preview/run/manifest consistency;
then run `git diff --check`.
