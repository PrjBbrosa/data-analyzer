---
id: codex-superseded-plans-use-new-dated-files
status: active
owners: [codex]
keywords: [plans, specs, supersedes, provenance, stale-plan]
paths:
  - docs/superpowers/plans
  - docs/superpowers/specs
checks: [git status --short, git diff --check]
tests: []
---

# Superseded Plans Use New Dated Files

Trigger: Revising an approved or committed implementation plan after its core
strategy, invariant, or acceptance contract has changed.

Past failure: An updated strategy existed only as working-tree edits to the same
plan path while a stale committed copy remained authoritative to another
executor. Commit `e448708` consequently implemented the obsolete strategy even
though its replacement had already been drafted.

Rule: Never rewrite a superseded plan in place. Preserve it as historical
evidence, create a new dated plan, and put an explicit `Supersedes:` reference to
the old artifact near the top. Update the governing design document when the
behavioral contract changes, and make the implementation task name the exact new
path.

Verification: Before execution, read the complete plan from the target branch,
confirm its `Supersedes:` chain and referenced spec, grep for retired strategy
terms, and verify `git status` does not reveal a newer uncommitted version of the
same artifact.
