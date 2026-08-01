---
id: batch-register-lazy-locators-before-group-identity
status: active
owners: [codex]
keywords: [batch, lazy-loading, source-paths, locator, identity, manifest, resume, grouping, planning]
paths: [mf4_analyzer/batch.py, mf4_analyzer/batch_grouping.py]
checks: [git diff --check]
tests: [tests/test_batch_runner.py]
---

# Register Lazy Locators Before Group Identity

Trigger: Changing lazy batch `source_paths`, locator registration, pattern
expansion, task/group planning, manifest resume, source-major loading, or
manifest member linkage.

Past failure: Planning before locator registration split group and task IDs.
Later, post-probe lazy expansion replaced only the task list and left stale
empty groups. A zero-load resume shortcut then trusted any nonempty old task
subset, silently omitting newly added paths or pattern-matching channels.

Rule: Canonicalize known lazy locators before identity planning. Treat task
enumeration and every derivative—ordering, task identities, render tasks, and
render groups—as one atomic plan. Zero-load manifest task-universe recovery
also requires a complete execution-scope proof: exact canonical source paths,
exact pattern, full path coverage, and unchanged strict source facts. If any
proof is missing, load and expand the complete current scope, then apply exact
artifact recovery to the resulting tasks/groups; do not disable safe artifact
reuse or trust the old subset.

Verification: Run real-loader source-major, lazy-pattern grouping, and lazy
scope-proof resume tests in `tests/test_batch_runner.py`. Cover same-scope zero
load, old manifest, path add/remove, pattern expansion, changed source stats
with a new channel, exact member linkage, and preservation of independently
verified healthy artifacts; then run `git diff --check`.
