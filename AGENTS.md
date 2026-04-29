# Repository Instructions

This repo uses an agent squad with a **planner-executor split**:

- **Planner:** the `squad-orchestrator` subagent — produces a
  decomposition plan from the user's request and consults the
  lessons-learned corpus. Does NOT dispatch specialists (Codex's
  subagent runtime does not grant `Task` to subagents).
- **Executor:** main Codex — receives the plan and is the sole
  dispatcher of specialists (`signal-processing-expert`,
  `pyqt-ui-engineer`, `refactor-architect`). Also owns the
  `.state.yml` counter, rework detection, and aggregation.

See `docs/superpowers/specs/2026-04-22-agent-squad-design.md` for the
full design, and `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md`
for why the split is mandatory.

## CLAUDE.md parity

`AGENTS.md` is the Codex-facing mirror of `CLAUDE.md`. When `CLAUDE.md`
changes, compare both files and port any repository-level workflow,
routing, lessons-learned, state-management, or skill instructions into
`AGENTS.md`, translating Claude-specific wording to Codex-specific
wording. Do not copy personal/local Claude-only settings unless they are
clearly useful for all agents working in this repository.

## Squad routing (MANDATORY for main Codex)

If the user's message contains any of these tokens (case-insensitive,
substring match, Chinese or English), you MUST run the **Squad runbook**
below:

- `agent`, `squad`
- `团队`, `分工`
- `重构`, `refactor`
- `多专家`, `multi-agent`

While the runbook is active, you MUST NOT author or edit `.py` source
files yourself — all code changes flow through specialist subagents.

## Squad runbook (four phases)

### Phase 1 — Plan

```
Task(subagent_type=squad-orchestrator,
     prompt="mode: plan\n\nuser request:\n<verbatim user message>")
```

The orchestrator returns a JSON plan with a `decomposition[]` array and
`applicable_lessons[]`. Parse it. If `status: blocked`, surface to the
user.

### Phase 2 — Execute

For each item in `decomposition[]`, respecting `depends_on`:

```
Task(subagent_type=<item.expert>,
     prompt=item.brief + <any upstream outputs> + <applicable_lessons citations>)
```

Sequential where `depends_on` is non-empty; parallel otherwise (send
parallel dispatches in one message block).

Collect each specialist's return JSON. Do NOT drop role-specific
fields (`ui_verified`, `tests_run`, `tests_before`, `tests_after`,
`files_moved`).

### Phase 3 — Aggregate & rework-detect

Build the final return object:

```json
{
  "top_level_status": "done" | "partial" | "blocked",
  "done": ["<subtask>..."],
  "blocked": [{"subtask": "...", "reason": "..."}],
  "flagged": [{"from": "<expert>", "for": "<expert>", "issue": "..."}],
  "subtasks": [<each specialist's full return>],
  "lessons_added": [<union across subtasks>],
  "lessons_merged": [<union across subtasks>],
  "prune_report_path": null
}
```

**Rework detection:** for every ordered pair of subtasks
`(S_i, S_j)` with `i < j`, if `S_j.files_changed ∩ S_i.files_changed`
is non-empty and `S_j.expert != S_i.expert`, `S_j` reworked `S_i`.
Write a `cause: rework` lesson to `docs/lessons-learned/orchestrator/`
naming both experts and the overlapping files. Update `LESSONS.md`
index row under `## orchestrator` (dual-write). Include the new
lesson path in `lessons_added`.

**Flagged handling:** any `flagged[]` entry whose `for` specialist was
NOT already in any subtask's `depends_on` → either re-dispatch that
specialist (append to `subtasks[]`) or surface to the user. Write a
decomposition lesson when re-dispatch was needed.

**Retry cap:** if the same `(subtask_slug, expert)` pair returns
`blocked`/`needs_info` twice consecutively, STOP; return
`top_level_status: blocked` with both traces.

### Phase 4 — Update state, maybe prune

Read-modify-write `docs/lessons-learned/.state.yml`:
- Parse ALL fields (`schema_version`, `top_level_completions`,
  `last_prune_at`).
- If `top_level_status == done` or `partial`, increment
  `top_level_completions` by 1. (`blocked` runs do NOT increment.)
- Write the full file back preserving all fields.

If `top_level_completions - last_prune_at >= 20`:

```
Task(subagent_type=squad-orchestrator, prompt="mode: prune")
```

Receive `{prune_report_path, counts}`. Set `last_prune_at :=
top_level_completions` in `.state.yml`. Attach `prune_report_path`
to the aggregated return.

Finally, relay a plain-text summary of the aggregated object to the
user, and attach the JSON in a fenced block.

## Escape hatch (opt-out)

If the user's message starts with `skip squad:` or `直接改：`, handle it
directly without routing. Use this for trivial one-line fixes where
orchestration overhead is not worth paying.

## Missed triggers

If you believe a message SHOULD have been routed but did not match any
keyword, route it anyway and note the missed keyword in the
orchestrator prompt so it can be recorded under `orchestrator/` lessons.

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

The squad and main Codex both honor `superpowers:*` skills. See each
agent's system prompt for per-role skill obligations. When running the
runbook, the orchestrator may tell you (via `notes`) that a specific
skill should be invoked before dispatch — honor that.
