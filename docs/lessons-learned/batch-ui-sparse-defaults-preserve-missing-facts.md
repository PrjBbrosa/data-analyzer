---
id: batch-ui-sparse-defaults-preserve-missing-facts
status: active
owners: [codex]
keywords: [batch, ui, preset, defaults, sparse-params, units, validation]
paths: [mf4_analyzer/ui/batch/sheet.py, mf4_analyzer/ui/batch/dynamic_form.py]
checks: [git diff --check]
tests: [tests/ui/test_batch_smoke.py, tests/ui/test_batch_method_buttons.py]
---

# Batch UI Separates Sparse Defaults From Missing Facts

Trigger: Applying full batch recipes, incremental parameter patches, or
aggregating per-source metadata for UI validation.

Past failure: Applying a full recipe with sparse `{}` parameters left five
controls at values from the previous recipe. Unit aggregation also dropped an
empty source unit, so a known `rpm` source plus an unknown-unit source passed as
if every source were known-compatible.

Rule: Materialize schema defaults at the boundary for a full recipe apply, but
keep partial parameter patches incremental. Preserve missing runtime facts
while aggregating source metadata, and fail closed when known values are mixed
with unknown ones instead of silently treating the unknown facts as absent.

Verification: Start from non-default controls and apply a sparse full recipe;
assert every transient control resets. Assert an empty incremental patch remains
a no-op. Cover known-plus-empty and all-empty unit combinations in the UI tests,
then run `git diff --check`.
