---
id: batch-nonfinite-values-stay-out-of-identity-and-warning-bounds
status: active
owners: [codex]
keywords: [batch, nan, infinity, slice, fingerprint, warning]
paths:
  - mf4_analyzer/batch_recipe.py
  - mf4_analyzer/batch.py
  - mf4_analyzer/batch_render_qt/_builder.py
checks:
  - git diff --check
tests:
  - tests/test_batch_recipe.py
  - tests/test_batch_render_qt_heatmap.py
  - tests/test_batch_runner.py
---

# Batch Non-Finite Values Stay Out Of Identity And Warning Bounds

Trigger: Changing batch recipe normalization, recipe fingerprints, heatmap
slice planning, or slice clamp warnings.

Past failure: A NaN slice position survived normalization and made equivalent
recipes order-sensitive, while a NaN coordinate made clamp warnings disclose
`[nan, nan]` even though finite grid bounds were available.

Rule: Filter non-finite numeric recipe positions before dedupe/sort/fingerprint,
and calculate displayed coordinate bounds from finite values only. Keep the
planner's finite landed positions as the authority for slice behavior.

Verification: Run the focused recipe, Qt heatmap, and runner regression tests;
assert equivalent NaN-containing recipes fingerprint identically and both
render/workbook clamp warnings contain finite bounds without `RuntimeWarning`.
