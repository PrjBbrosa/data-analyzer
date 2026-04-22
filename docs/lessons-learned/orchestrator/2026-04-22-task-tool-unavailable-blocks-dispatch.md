---
role: orchestrator
tags: [dispatch, tooling, architecture, planner-executor-split]
created: 2026-04-22
updated: 2026-04-22
cause: insight
supersedes: []
---

## Context

During the Task 8 dry-run (2026-04-22), the orchestrator was invoked
and found `Task` absent from its tool list. The original design
assumed the orchestrator would dispatch specialists itself — that
assumption is wrong. Claude Code's subagent runtime intentionally
does NOT grant `Task` to subagents (to prevent runaway recursive
delegation).

## Lesson

The orchestrator's role is **planning only**, not dispatching. Task
absence is **expected behavior**, not a blocker. The architecture was
pivoted to a planner-executor split: orchestrator produces a
decomposition plan; main Claude (with its native `Task` tool)
executes the plan by dispatching specialists.

## How to apply

If you are the orchestrator:
- NEVER treat Task-tool absence as a blocker. It is structural.
- In `plan` mode, always return a decomposition JSON per the
  "Plan-mode return contract" in your system prompt. Fields are
  `mode`, `status`, `decomposition[]`, `applicable_lessons[]`,
  `decomposition_audit_path`, `notes`. Do NOT use the legacy
  `top_level_status / done / blocked / subtasks[]` shape — that is
  main Claude's aggregation contract, not yours.
- In `prune` mode, walk the lessons corpus and return the report path
  per the "Prune-mode return contract".
- You MAY return `status: blocked` in plan mode ONLY if the request
  is ambiguous or none of the specialist keywords match — in that
  case surface to main Claude rather than guess.

If you are main Claude:
- You are the dispatcher. See the Squad runbook in `CLAUDE.md`.
- `.state.yml` is yours to write; orchestrator is read-only on it.
