---
id: codex-publish-flow-lightweight
status: active
owners: [codex]
keywords: [publish, push, pull-request, pr, commit, git, 发布, 推送]
paths: [AGENTS.md, .gitignore, docs/lessons-learned/*]
checks: [git status -sb, git diff --stat, git diff --name-status, git diff --check]
tests: []
---

# Codex Publish Flow Lightweight

Trigger: Load when the user asks to commit, push, open a PR, write a PR, or otherwise publish already-local changes.

Past failure: A simple publish request was treated like a large code audit: broad grep output, report reads, memory search, and full context gathering consumed excessive tokens without improving the publish decision.

Rule: For publish tasks, do release hygiene rather than implementation review. Confirm branch, changed-file scope, obvious generated artifacts, whitespace/conflict checks, and relevant existing tests; do not broaden into audit-style source exploration unless the user asks for review/sign-off, tests fail, or the diff contains a concrete danger signal.

Verification: Use `git status -sb`, `git diff --stat`, `git diff --name-status`, `git diff --check`, and at most a bounded untracked-file listing; summarize validation in the PR body and leave detailed correctness review to a review request or PR review.
