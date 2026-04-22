# Repository Instructions

This repo uses an agent squad. Main Claude is a router, not an author of
business code here. See
`docs/superpowers/specs/2026-04-22-agent-squad-design.md` for the design.

## Squad routing (MANDATORY for main Claude)

If the user's message contains any of these tokens (case-insensitive,
substring match, Chinese or English), you MUST dispatch the task via
`Task(subagent_type=squad-orchestrator, prompt=<verbatim user request>)`:

- `agent`, `squad`
- `团队`, `分工`
- `重构`, `refactor`
- `多专家`, `multi-agent`

When routing, you MUST NOT author or edit `.py` source files yourself.
Your job reduces to: dispatch, relay the orchestrator's summary, and
surface any blocked subtasks back to the user.

## Escape hatch (opt-out)

If the user's message starts with `skip squad:` or `直接改：`, handle it
directly without routing. Use this for trivial one-line fixes where
orchestration overhead is not worth paying.

## Missed triggers

If you believe a message SHOULD have been routed but did not match any
keyword, route it anyway and note the missed keyword in the orchestrator
prompt so it can be recorded under `orchestrator/` lessons.

## Out of scope for the squad

- Non-code conversations (pure Q&A about the codebase).
- Running builds, installing dependencies, or other ops the user is
  clearly asking YOU to do (`pip install`, etc.).
- Questions that start with `how` or `what` unless they entail code
  changes.

**Precedence:** out-of-scope rules override keyword triggers. A
conversational "how should we refactor module X?" is Q&A — answer
directly, do not route, even though `refactor` matches.

## Skills

The squad and main Claude both honor `superpowers:*` skills. See each
agent's system prompt for per-role skill obligations.
