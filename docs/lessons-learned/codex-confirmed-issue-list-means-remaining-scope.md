---
id: codex-confirmed-issue-list-means-remaining-scope
status: active
owners: [codex]
keywords: [scope-confirmation, ui-fixes, numbered-issues, execution]
paths: []
checks: [git status --short, git diff --stat]
tests: []
---

# Confirmed Issue List Means Remaining Scope

Trigger: A user references numbered issues from an earlier diagnosis and says
some subset is acceptable, done, or "no problem" before asking to proceed with
one remaining design choice.

Past failure: The user confirmed issues 1/2/4 were acceptable and asked only
which interaction model to use for issue 3. Codex implemented only issue 3,
mistaking the confirmation as an exclusion instead of approval for the full
1/2/3/4 repair scope.

Rule: Before executing, translate the numbered issue set into an explicit
implementation checklist and keep every approved issue in scope unless the user
clearly says to skip it. If a later question narrows only a design decision,
do not silently drop the already-approved items.

Verification: Check `git status --short` and `git diff --stat` against the
full numbered checklist before committing; the changed files and tests should
cover every approved issue, not only the last-discussed one.
