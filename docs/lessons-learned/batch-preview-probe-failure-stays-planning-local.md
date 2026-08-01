---
id: batch-preview-probe-failure-stays-planning-local
status: active
owners: [codex]
keywords: [batch, preview, probe, source-unavailable, exception-boundary, qt]
paths: [mf4_analyzer/batch.py, mf4_analyzer/io/source_adapters.py]
checks: [git diff --check]
tests: [tests/test_batch_runner.py, tests/test_source_adapters.py, tests/ui/test_batch_smoke.py]
---

# Batch Preview Probe Failure Stays Planning-Local

Trigger: Adding metadata-only source probing to a no-load preview that runs
from Qt signals or precedes the authoritative batch load.

Past failure: A file row had already been accepted by the UI, but its MDF path
was absent when output preview recomputed. The third-party `MdfException`
escaped the adapter and Qt event loop because it was neither an `OSError` nor a
project domain exception.

Rule: Translate backend-specific file/probe exceptions into a narrow project
source-unavailable error at the adapter boundary. A no-load preview may catch
only that domain error and ordinary filesystem errors, cache the failed probe
attempt, and continue with a deterministic unresolved identity. Do not swallow
`ValueError`, ordinary `RuntimeError`, or programming errors. The preview cache
must never bypass the later authoritative load; execution still reports the
real load failure and publishes no artifact.

Verification: Make a metadata-cost probe raise the domain unavailable error and
assert preview returns without reserving output while a same-runner execution
still calls `load_sources`, fails/blocks, retains the planned identity, and
writes nothing. Assert generic runtime/programming errors still propagate.
Translate real MDF backend file exceptions in adapter tests and run the Qt smoke
case where the selected `x.mf4` path is absent, then run `git diff --check`.
