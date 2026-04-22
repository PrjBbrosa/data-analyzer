---
role: orchestrator
tags: [dispatch, tooling, smoke-test, blocker]
created: 2026-04-22
updated: 2026-04-22
cause: insight
supersedes: []
---

## Context
During the Task 8 smoke test of the agent-squad plan, the orchestrator was invoked but its available tool list did not include `Task`, so dispatching `signal-processing-expert` to add a docstring to `FFTAnalyzer` was impossible.

## Lesson
The orchestrator's ability to fulfil ANY top-level request is conditional on the `Task` tool being present in its tool list; absence of `Task` is a hard blocker, not a recoverable error, because the orchestrator cannot author `.py` edits itself.

## How to apply
At startup, confirm `Task` is in the tool list before accepting a request. If missing, return `top_level_status: blocked` with reason `task_tool_unavailable` on the first turn — do not write partial audit trails or attempt workarounds.
