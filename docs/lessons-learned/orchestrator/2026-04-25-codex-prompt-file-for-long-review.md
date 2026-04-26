---
role: orchestrator
tags: [codex, review, tooling, shell]
created: 2026-04-25
updated: 2026-04-25
cause: insight
supersedes: []
---

## Context
A Codex review handoff embedded a long prompt in a shell double-quoted argument. The prompt contained backticked commands and also required Codex to write a markdown report artifact.

## Lesson
Shell interpolation can execute prompt snippets before Codex receives them, corrupting the handoff while still letting a partial Codex run start. Review or diagnosis tasks that must write a report also need write-capable Codex sandbox mode, even if they do not edit source files.

## How to apply
For Codex rescue/review handoffs with long prompts, shell syntax, or required report files, write the prompt to `/tmp` and invoke `task --prompt-file ... --write`. If pytest is part of the prompt contract, specify `TMPDIR=/tmp` so the test runner has a writable temporary directory.
