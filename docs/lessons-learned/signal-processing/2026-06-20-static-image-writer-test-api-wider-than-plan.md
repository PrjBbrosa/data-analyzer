---
role: signal-processing
tags: [batch, write-image, backward-compat, static-method, test-api-surface]
created: 2026-06-20
updated: 2026-06-20
cause: insight
supersedes: []
---

# Static batch image-writer tests call the method directly with old payload type

## Context

`BatchRunner._write_image` was refactored to accept `_Spectro2D` instead of a
long-format DataFrame. The plan correctly noted to preserve old method names as
thin wrappers, but did not account for tests that call `_write_image` DIRECTLY
with a DataFrame payload (bypassing `_run_one`). Two existing tests
(`test_batch_heatmap_image_applies_xyz_axis_params` and
`test_batch_heatmap_image_can_render_linear_z_scale`) construct a DataFrame and
pass it as `("order_time", df)` to `_write_image`. Had the method been changed
to a pure `_Spectro2D`-only API, those tests would have crashed with an
`AttributeError` on `df.matrix`.

## Lesson

A plan that narrows a static method's accepted payload type must grep the test
files for DIRECT calls to that method (not just end-to-end `runner.run()` calls)
to discover the full test API surface. Static helpers in batch pipelines are
often exercised directly in unit tests with the OLD payload type to isolate
rendering from computation.

## How to apply

Before narrowing any `@staticmethod` batch helper's input type, run
`grep -n "_write_image\|_write_dataframe" tests/` (or the analogous grep for the
target method) to find all direct call sites. If any pass the old payload type,
implement a dual-accept branch (new type via `isinstance`, old via a legacy
fallback path) rather than a hard replacement. Mark the legacy branch with a
comment so it can be pruned when the direct-call tests are eventually updated.
