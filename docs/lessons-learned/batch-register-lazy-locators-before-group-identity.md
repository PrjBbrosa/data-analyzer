---
id: batch-register-lazy-locators-before-group-identity
status: active
owners: [codex]
keywords: [batch, lazy-loading, source-paths, locator, identity, manifest, grouping, planning]
paths: [mf4_analyzer/batch.py, mf4_analyzer/batch_grouping.py]
checks: [git diff --check]
tests: [tests/test_batch_runner.py]
---

# Register Lazy Locators Before Group Identity

Trigger: Changing lazy batch `source_paths`, locator registration, pattern
expansion, task/group planning, source-major loading, or manifest member
linkage.

Past failure: Explicit groups were first planned before lazy physical locators
were registered, so group and task IDs used different source identities. A
later probe-order fix then re-enumerated lazy pattern tasks after the renderer
probe but replaced only the task list; stale empty `render_groups` made an
explicit grouped run silently fall back to per-task images.

Rule: Register and canonicalize every known lazy locator before identity
planning. Treat task enumeration and every derived value—canonical ordering,
task output identities, render tasks, and render groups—as one atomic planning
operation. Whenever lazy pattern expansion replaces the task list, rebuild the
entire plan; never patch one derived collection in place.

Verification: Run the real injected-loader source-major and lazy-pattern
grouping tests in `tests/test_batch_runner.py`. Assert one load per physical
source, exact manifest task/member linkage, and the expected source/channel
group image and journal counts after post-probe expansion; then run
`git diff --check`.
