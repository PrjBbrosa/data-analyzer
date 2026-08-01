---
id: batch-preview-never-escalates-full-cost-probes
status: active
owners: [codex]
keywords: [batch, preview, source-adapter, probe-cost, lazy-loading, identity]
paths: [mf4_analyzer/batch.py, mf4_analyzer/io/source_adapters.py]
checks: [git diff --check]
tests: [tests/test_batch_runner.py, tests/test_batch_source_integration.py]
---

# Batch Preview Never Escalates Full-Cost Probes

Trigger: Resolving lazy source descriptors or output identities during a batch
preview or other explicitly no-load planning path.

Past failure: The runner called `probe_sources()` because its name sounded
lightweight. For HDF, CSV, and other adapters whose `probe_cost` is `full`, that
method delegates to `load_sources()`, so opening the run dialog could load the
entire source. A fake registry with a cheap probe hid the production behavior.

Rule: Inspect an explicit adapter capability before descriptor probing. Only a
metadata-cost probe is allowed on a no-load path; full-cost or unknown adapters
must use a clearly unresolved but deterministic source identity. Execution must
reuse that planned identity so loading cannot silently rename artifacts or
change conflict counts. Do not infer cost from a method name or from a fake
implementation being fast.

Verification: Exercise the production registry path with a full-cost HDF
adapter and spy on `DataLoader.load_hdf`; preview must make zero load calls.
Then run the same preset and assert preview/run task, group, stem, and manifest
member identities agree. Keep a metadata-cost multi-descriptor test for the
single-probe/all-descriptors cache path, and run `git diff --check`.
