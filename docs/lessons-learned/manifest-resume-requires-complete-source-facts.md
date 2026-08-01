---
id: manifest-resume-requires-complete-source-facts
status: active
owners: [codex]
keywords: [batch, manifest, resume, provenance, source-facts, checksum, fail-closed]
paths: [mf4_analyzer/batch_manifest.py, mf4_analyzer/batch.py]
checks: [git diff --check]
tests: [tests/test_batch_manifest.py, tests/test_batch_runner.py]
---

# Manifest Resume Requires Complete Source Facts

Trigger: Changing manifest validation, grouped resume planning, source
provenance facts, duplicate task handling, or artifact checksum recovery.

Past failure: Missing `size`/`mtime_ns` facts could match explicit nulls, and a
consumer later accepted `bool` as `int`, allowing `True == 1` to reuse the
wrong source. A duplicate task-ID scan also verified one entry's checksum but
returned a different, invalid candidate artifact.

Rule: Every resume consumer—not only the manifest loader—must require all
source-fact keys, a nonempty string identity, and stats that are either
non-boolean integers or explicit `None`. Never use `.get()` where key absence
matters. Bind path/checksum proof to the exact entry returned; when duplicate
IDs are tolerated, object/candidate identity must not drift across a rescan.

Verification: Run missing-key, wrong-type (including bool), duplicate-ID,
changed-stat, bad-path/checksum, post-checksum cancellation, and grouped lazy
resume cases in `tests/test_batch_manifest.py` and `tests/test_batch_runner.py`;
then run `git diff --check`.
