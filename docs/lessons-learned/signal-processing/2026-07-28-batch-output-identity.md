---
id: signal-processing/2026-07-28-batch-output-identity
status: active
owners: [codex]
keywords: [batch, output-identity, atomic-write, collision, unicode, rollback, ownership]
paths: [mf4_analyzer/batch.py, mf4_analyzer/batch_output.py]
checks: [git diff --check]
tests: [tests/test_batch_output.py, tests/test_batch_runner.py]
role: signal-processing
tags: [batch, output-identity, atomic-write, collision, unicode, rollback]
created: 2026-07-28
updated: 2026-07-28
cause: insight
supersedes: []
---

# Batch Output Identity Must Survive Publish Races

## Context

Trigger: Batch exports derive or publish paths for multiple sources, groups, channels, recipes, or coordinated artifact sets, especially when names contain Unicode or an output directory is reused concurrently.

Past failure: A display stem built from basename, channel, and method collapsed distinct tasks and overwrote existing files. Later, coordinated rollback unlinked a published path without checking whether a non-cooperating writer had replaced it, so rollback could delete someone else's complete file.

## Lesson

Rule: Treat the readable stem as presentation only. Build task identity from canonical source, group, channel, method, and normalized recipe; reserve and stage the complete artifact set in the destination directory. On publication failure, roll back only paths still proven to belong to this reservation. If ownership changed or cannot be proven, leave the path untouched, preserve any recoverable backup, and fail explicitly instead of deleting or overwriting unknown data.

## How to apply

Verification: Run `tests/test_batch_output.py` and the identity/collision tests in `tests/test_batch_runner.py`; include outsider replacement races for both no-replace and overwrite policies. Confirm outsider bytes survive, an incomplete rollback is reported, all ordinary final paths stay distinct, and normal completion leaves no temporary files or reservation tokens.
