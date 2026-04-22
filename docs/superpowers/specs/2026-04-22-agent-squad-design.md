# Agent Squad for MF4-data-analyzer — Design Spec

**Date:** 2026-04-22
**Author:** Hang (brainstormed with Claude)
**Scope:** Stand up a repository-scoped agent squad with orchestrator + 3 technical
experts and a lessons-learned discipline. This spec covers ONLY the squad
infrastructure. The first real task the squad will execute — refactoring
`MF4 Data Analyzer V1.py` into modules — is a separate sub-project and gets its
own spec/plan.

---

## 1. Goal

Build a lightweight, repository-internal agent squad that:

1. Breaks user requests into subtasks and routes each to a specialist.
2. Enforces hard domain boundaries so specialists stay in their lane.
3. Captures non-obvious insights as lessons-learned on every rework and every
   top-level task completion.
4. Grows safely — lessons are indexed, merged on conflict, and periodically
   reviewed so the corpus does not bloat.

Non-goals: a cross-project personal knowledge base, slash-command ergonomics,
chat UIs, or any automatic code-level self-modification of the squad itself.

## 2. Architecture

### 2.1 Substrate

Claude Code subagents (`.claude/agents/*.md`). Each role is a markdown file
with frontmatter declaring `name`, `description`, and `tools`. The main Claude
invokes a subagent via `Task(subagent_type=<name>, prompt=...)`; the subagent
runs in an isolated context with its own token budget and returns a single
structured message.

### 2.2 Repository layout added by this spec

```
.claude/agents/
  squad-orchestrator.md
  signal-processing-expert.md
  pyqt-ui-engineer.md
  refactor-architect.md

docs/lessons-learned/
  README.md                        # Reflection + write protocol (agent-facing)
  LESSONS.md                       # Master one-line index across all roles
  orchestrator/
  signal-processing/
  pyqt-ui/
  refactor/

CLAUDE.md                          # Repo-root routing rules (new or updated)
```

Existing locations (unchanged):

- `docs/superpowers/specs/` — brainstorming outputs
- `docs/superpowers/plans/` — writing-plans outputs

### 2.3 Invocation flow

```
user message
  │
  ▼
main Claude
  │  (detects keyword: agent / squad / 团队 / 分工 / 重构 …)
  ▼
Task(subagent_type=squad-orchestrator, prompt="<verbatim user request>")
  │
  ▼
squad-orchestrator
  │ 1. Read docs/lessons-learned/LESSONS.md
  │ 2. Grep role-specific lessons by task keywords
  │ 3. Decompose into subtasks; pick an expert per subtask
  │ 4. Dispatch (sequential or parallel as dependencies allow):
  │      Task(subagent_type=<expert>, prompt=<subtask brief>)
  │ 5. Collect returns; handle rework flags; merge results
  │ 6. Trigger top-level reflection for every role that participated
  ▼
return { done, blocked, lessons_added, lessons_merged } to main Claude
```

### 2.4 Triggering rules (keyword-based, no slash command)

Main Claude MUST route the task to `squad-orchestrator` whenever the user
message contains any of the following tokens (case-insensitive, substring
match, in Chinese or English):

- `agent`, `squad`
- `团队`, `分工`
- `重构`, `refactor`
- `多专家`, `multi-agent`

This rule is codified in the repository's `CLAUDE.md`. The keyword list itself
is part of squad behavior — missed triggers should be written as lessons under
`orchestrator/` so the list can be iterated.

Explicit bypass: if the user's message starts with `skip squad:` or `直接改：`,
the main Claude handles it without dispatching. This escape hatch exists so
trivial edits do not pay the orchestration overhead.

## 3. Agent Contracts

Each `.claude/agents/<name>.md` is structured as:

```yaml
---
name: <name>
description: <one-line purpose>
tools: <comma-separated>
---

<system prompt>
```

System prompt sections (common to all four agents):

1. **Role & domain** — what the agent owns.
2. **Hard boundaries** — what the agent must NOT touch.
3. **Startup protocol** — fixed steps to read lessons before acting.
4. **Output contract** — required return shape.
5. **Reflection protocol** — when and how to write lessons.
6. **Superpowers skills to honor** — which skills to invoke and when.

### 3.1 `squad-orchestrator`

- **Domain:** Task decomposition, expert dispatch, result aggregation.
- **Tools:** `Task, Read, Grep, Glob, Write, Edit, Bash`.
- **Hard boundaries:** Does not author business code (algorithms, UI, or
  package-level refactors). May write lessons files and decomposition notes.
- **Startup protocol (fixed, in order):**
  1. `Read docs/lessons-learned/LESSONS.md`.
  2. `Grep` lessons in `orchestrator/` by task keywords.
  3. Emit a decomposition table: subtasks × assigned expert × dependencies.
  4. Dispatch via `Task(subagent_type=<expert>, ...)`.
- **Return contract:**
  ```json
  {
    "done": ["<subtask>..."],
    "blocked": [{"subtask": "...", "reason": "..."}],
    "flagged": [{"from": "<expert>", "for": "<expert>", "issue": "..."}],
    "lessons_added": ["<path>..."],
    "lessons_merged": ["<path>..."]
  }
  ```
- **Reflection triggers:** Top-level task completion; any expert returning
  `cause: rework`; any `flagged` entry that the orchestrator had not
  anticipated in decomposition.
- **Skills:** `superpowers:brainstorming` when the request is ambiguous;
  `superpowers:writing-plans` when the task is clear but large.

### 3.2 `signal-processing-expert`

- **Domain:** FFT, order analysis, windowing, filtering, numerical correctness,
  sampling/resampling, averaging (Welch), tacho processing.
- **Tools:** `Read, Edit, Write, Grep, Glob, Bash` (bash to run pytest or
  throwaway numeric scripts).
- **Hard boundaries:** Does not modify PyQt widgets, dialogs, layouts, or
  matplotlib canvas classes. On spotting a UI defect, returns a `flagged`
  entry; does not fix.
- **Startup protocol:**
  1. `Read docs/lessons-learned/LESSONS.md`.
  2. Restrict to rows under the `## signal-processing` heading, then
     keyword-match bracketed content tags (`[fft]`, `[window]`, `[order]`,
     etc.). Also `Grep docs/lessons-learned/signal-processing/` by task
     keywords for body content. (README.md is authoritative on the
     reading protocol; `[signal]` is NOT a valid content tag — role lives
     in its own frontmatter field and in the heading.)
  3. `Read` the ≤ 5 most relevant lesson bodies.
- **Return contract (same for every expert):**
  ```json
  {
    "status": "done" | "blocked" | "needs_info",
    "files_changed": ["<path>..."],
    "tests_run": ["<pytest nodeid>..."],
    "flagged": [{"for": "<other-expert>", "issue": "..."}],
    "lessons_added": ["<path>..."],
    "lessons_merged": ["<path>..."],
    "notes": "<optional freeform summary for orchestrator>"
  }
  ```
- **Reflection triggers:** Rework (immediate); top-level task completion
  (orchestrator-initiated).
- **Skills:** `superpowers:test-driven-development` is REQUIRED for any change
  to numeric logic. Write the expected-value test first, then modify the
  implementation.

### 3.3 `pyqt-ui-engineer`

- **Domain:** PyQt5 widgets, dialogs, layouts, signal/slot wiring, matplotlib
  canvases, interaction (zoom/pan/span-select, axis editing, annotations),
  Chinese font setup.
- **Tools:** `Read, Edit, Write, Grep, Glob, Bash`.
- **Hard boundaries:** Does not alter numeric formulas, FFT/order algorithm
  internals, or file loaders. On spotting an algorithm defect, returns a
  `flagged` entry.
- **Startup protocol:** Same pattern as §3.2 step 2, but restrict to the
  `## pyqt-ui` heading and keyword-match content tags (`[widget]`,
  `[canvas]`, `[axis-edit]`, etc.).
- **Skills:** No automatic skill invocation. Follows the CLAUDE.md rule that
  UI changes must be verified by starting the app and exercising the feature;
  if the agent cannot start the app, it explicitly says so in its return
  rather than claiming success.

### 3.4 `refactor-architect`

- **Domain:** Module boundaries, package structure, import graph, performance
  hotspots, backwards-compatibility of public APIs, large-scale code motion.
- **Tools:** `Read, Edit, Write, Grep, Glob, Bash`.
- **Hard boundaries:** Does not introduce new features. Does not change
  numeric results or user-visible UI behavior.
- **Startup protocol:** Same pattern as §3.2 step 2, but restrict to the
  `## refactor` heading and keyword-match content tags (`[arch]`,
  `[perf]`, `[import-cycle]`, etc.).
- **Privilege:** The only agent allowed to move code across modules in bulk.
  When the move crosses a domain (e.g., pulling `FFTAnalyzer` out of the
  monolith), it may execute the relocation but must NOT change function
  signatures, algorithmic bodies, or UI behavior. Allowed: moving files,
  renaming modules, adjusting imports, adding `__init__.py` re-exports.
  Forbidden without owning-expert sign-off: editing function bodies, renaming
  public symbols, splitting a class into multiple classes.
- **Skills:** `superpowers:writing-plans` REQUIRED before any cross-file
  refactor touching more than 3 files. Full test suite must pass before and
  after.

## 4. Lessons-Learned System

### 4.1 Writing format

Single lesson file frontmatter:

```yaml
---
role: signal-processing
tags: [signal, fft]
created: 2026-04-22
updated: 2026-04-22
cause: rework          # rework | top-level | insight
supersedes: []         # file names of lessons merged into this one
---
```

Body has three fixed sections:

- **Context** — the specific situation that prompted the lesson.
- **Lesson** — the non-obvious insight. One or two sentences.
- **How to apply** — the future trigger: "next time you see X, do Y".

Water content (e.g., "I used Grep to find the file") is forbidden. If the
lesson cannot be stated as a non-obvious insight, it must not be written.

### 4.2 Master index `LESSONS.md`

One line per lesson, ≤ 150 characters:

```
- [<slug>](<role>/<YYYY-MM-DD-slug>.md) [tag1][tag2] — one-line hook
```

The file has no frontmatter. It is append-only except for in-place updates
when a lesson is merged (see 4.3).

### 4.3 Merge-on-conflict write protocol

When an agent decides to write a lesson, it MUST execute these steps in
order:

1. Read `docs/lessons-learned/README.md` (the protocol itself).
2. `Grep` the agent's role directory for same-topic lessons using the new
   lesson's tags and keywords.
3. **If a same-topic lesson exists:** update the existing file — bump
   `updated`, integrate the new Context/Lesson/How-to-apply into the body,
   and update the existing row in `LESSONS.md` in place. Do NOT create a new
   file. Add the prior file name to `supersedes` only when the old file is
   being replaced rather than extended.
4. **If no same-topic lesson exists:** create a new file and append a new row
   to `LESSONS.md`.
5. Return `lessons_added` and `lessons_merged` arrays to the caller.

Rework lessons (`cause: rework`) MUST be written immediately at the moment
the rework is detected, not deferred to task completion.

### 4.4 Reading protocol

At agent startup, to keep token cost constant as the corpus grows:

1. `Read docs/lessons-learned/LESSONS.md` once.
2. Restrict to rows under the agent's `## <role>` heading, then
   keyword-match the bracketed content tags against the incoming task.
   (Role lives in its own heading and frontmatter field — it is NOT a
   content tag. See README.md §"tags rule".)
3. `Read` at most 5 full lesson bodies (highest keyword hit count wins ties).

### 4.5 Anti-bloat review

The orchestrator keeps a persistent counter in
`docs/lessons-learned/.state.yml` (gitignored is NOT required; committing the
counter keeps the 20-task cadence consistent across machines):

```yaml
top_level_completions: 17
last_prune_at: 0
```

On every successful top-level completion the orchestrator increments the
counter. When `top_level_completions - last_prune_at >= 20`, it MUST produce
a pruning candidate report:

- Lessons not referenced (via grep in the last 20 dispatches' decomposition
  notes) for the prior 6 months.
- Lessons with overlapping tags that could be merged.

The report is returned to the user and `last_prune_at` is set to the current
`top_level_completions`. The orchestrator does NOT auto-delete or
auto-archive. The user decides whether to merge (`supersedes`) or move files
to `docs/lessons-learned/archive/<role>/`.

## 5. Superpowers Skills Integration

### 5.1 Skill obligations per role

| Agent | Required skills |
|---|---|
| `squad-orchestrator` | `brainstorming` when task is ambiguous; `writing-plans` when task is clear but large |
| `signal-processing-expert` | `test-driven-development` for every numeric change |
| `pyqt-ui-engineer` | None automatic; honor repo CLAUDE.md UI-verification rule |
| `refactor-architect` | `writing-plans` before any >3-file refactor |

### 5.2 Boilerplate in each agent's system prompt

Each agent ends with:

```
## Skills you must honor
- At startup, check superpowers:using-superpowers; invoke any skill that
  applies to the incoming task.
- Skill obligations specific to this role: <see table>.
- Do NOT skip skills because "the task seems simple".
```

### 5.3 CLAUDE.md layering

- Repo-root `CLAUDE.md` — routing rules only: the keyword list, the
  `skip squad:` escape hatch, and the instruction that main Claude must not
  author business code when routing applies.
- Each `agents/*.md` — domain rules, hard boundaries, required-lessons paths,
  skill obligations.

Rules are not duplicated between the two layers.

## 6. Data Flow Example (first real task will exercise this)

```
User: "重构 MF4 Data Analyzer 为模块化"
  (matches "重构" keyword → route)
main Claude → Task(squad-orchestrator, "<user message>")

squad-orchestrator
  reads LESSONS.md; grep "refactor", "module" → 0 hits (fresh squad)
  decomposes:
    S1  refactor-architect        design package layout, migration plan
    S2  signal-processing-expert  move FFTAnalyzer/OrderAnalyzer + tests  (blocked by S1)
    S3  pyqt-ui-engineer          move PlotCanvas/dialogs                  (blocked by S1)
    S4  refactor-architect        wire new entry point, update imports     (blocked by S2, S3)
  dispatches S1 → ... → S4
  collects returns; no rework
  triggers top-level reflection in all four roles
  returns summary to main Claude
```

## 7. Error Handling

- **Expert returns `blocked`:** orchestrator re-plans or escalates to the
  user; does not silently swallow.
- **Expert violates hard boundary** (detected by file diff outside its
  declared domain): orchestrator rejects the result, writes a
  `cause: rework` lesson under the offender's role, and re-dispatches with a
  narrower prompt.
- **Same subtask fails twice:** orchestrator stops, returns to user with the
  decomposition notes and failure traces.
- **Lessons write fails** (e.g., `LESSONS.md` merge conflict): agent surfaces
  the error instead of continuing; lessons are never silently dropped.

## 8. Testing the Squad Itself

Two kinds of verification on squad bring-up:

1. **Dry-run task:** a trivial task (e.g., "add a docstring to FFTAnalyzer")
   must flow user → main Claude → orchestrator → signal-processing-expert →
   back, with a non-empty decomposition note and an empty `lessons_added`
   (no insight worth keeping).
2. **Boundary test:** route a cross-domain task (e.g., "the FFT plot's Y
   axis label is wrong and the amplitude scaling is also off") — must result
   in two subtasks dispatched to two experts, not one expert touching both.

These are executed once after the squad files are authored and are not
recurring CI tests.

## 9. Out of Scope

- The actual refactor of `MF4 Data Analyzer V1.py`.
- Any changes to `numpy`/`asammdf`/`PyQt5` dependencies.
- A global (cross-project) agent or lessons library.
- Automatic archiving/deletion of lessons.
- Slash-command UX.

## 10. Deliverables Checklist

- [ ] `.claude/agents/squad-orchestrator.md`
- [ ] `.claude/agents/signal-processing-expert.md`
- [ ] `.claude/agents/pyqt-ui-engineer.md`
- [ ] `.claude/agents/refactor-architect.md`
- [ ] `docs/lessons-learned/README.md` (reflection + write protocol)
- [ ] `docs/lessons-learned/LESSONS.md` (empty with header)
- [ ] `docs/lessons-learned/{orchestrator,signal-processing,pyqt-ui,refactor}/`
      with a `.gitkeep`
- [ ] Repo-root `CLAUDE.md` updated with keyword routing and escape hatch
- [ ] Dry-run + boundary test recorded in a follow-up note under
      `docs/superpowers/specs/`
