---
id: batch-register-lazy-locators-before-group-identity
status: active
owners: [codex]
keywords: [batch, lazy-loading, source-paths, locator, identity, manifest, grouping]
paths: [mf4_analyzer/batch.py, mf4_analyzer/batch_grouping.py]
checks: [git diff --check]
tests: [tests/test_batch_runner.py]
---

# Register Lazy Locators Before Group Identity

Trigger: Changing lazy batch `source_paths`, locator registration, task/group
planning, source-major loading, or manifest member linkage.

Past failure: Explicit groups were planned before lazy physical locators were
registered. Group members used a fallback `file_id:path` identity while loaded
tasks used the resolved absolute path, so render-group member task IDs no
longer matched the manifest task entries even though each source loaded once.

Rule: Register and canonicalize every lazy physical source locator before
building task identities or render groups. Planning and execution must consume
the same canonical source identity; do not repair group membership after task
IDs have already been fingerprinted.

Verification: Run the real injected-loader source-major test in
`tests/test_batch_runner.py` and assert both one load per physical source and
exact equality between manifest task IDs and every render-group member task
ID; then run `git diff --check`.
