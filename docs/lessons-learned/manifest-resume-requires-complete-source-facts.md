---
id: manifest-resume-requires-complete-source-facts
status: active
owners: [codex]
keywords: [batch, manifest, resume, provenance, source-facts, fail-closed]
paths: [mf4_analyzer/batch_manifest.py]
checks: [git diff --check]
tests: [tests/test_batch_manifest.py]
---

# Manifest Resume Requires Complete Source Facts

Trigger: Changing manifest validation, resume lookup, source provenance facts,
or artifact checksum recovery.

Past failure: A render-group member missing `size` or `mtime_ns` could match a
current source whose explicit value was `None`, because `.get()` made an absent
key indistinguishable from a present null value. A valid image checksum could
then turn malformed provenance into an unsafe resume hit.

Rule: Resume-critical source facts must contain every required key and each
value must have a valid type before comparison. Recovery helpers must enforce
this fail-closed rule themselves instead of relying only on manifest loading;
never compare required provenance through `.get()` when key absence matters.

Verification: Run the missing-key, wrong-type, changed-stat, bad-checksum, and
post-checksum cancellation cases in `tests/test_batch_manifest.py`, then run
`git diff --check`.
