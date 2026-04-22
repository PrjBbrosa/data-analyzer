# Agent Squad Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a repository-scoped Claude Code subagent squad (orchestrator + 3 technical experts) backed by an indexed, merge-on-conflict lessons-learned corpus, with keyword-based routing from the main Claude.

**Architecture:** Four `.claude/agents/*.md` subagent files; a `docs/lessons-learned/` tree with a master index, per-role subdirectories, a persistent state counter, and an agent-facing reflection protocol README; a repo-root `CLAUDE.md` that routes messages containing trigger keywords into the orchestrator via the `Task` tool.

**Tech Stack:** Claude Code subagents, plain markdown, YAML frontmatter, no runtime dependencies on the Python codebase.

**Spec reference:** `docs/superpowers/specs/2026-04-22-agent-squad-design.md`

---

## File Structure

| Path | Responsibility |
|---|---|
| `docs/lessons-learned/README.md` | Reflection + write protocol, agent-facing |
| `docs/lessons-learned/LESSONS.md` | Master one-line index across all roles |
| `docs/lessons-learned/.state.yml` | Orchestrator's persistent counter for 20-task prune cadence |
| `docs/lessons-learned/{orchestrator,signal-processing,pyqt-ui,refactor}/.gitkeep` | Preserve empty role dirs in git |
| `.claude/agents/squad-orchestrator.md` | Decompose tasks, dispatch to experts, aggregate |
| `.claude/agents/signal-processing-expert.md` | FFT / order / numerical logic specialist |
| `.claude/agents/pyqt-ui-engineer.md` | PyQt5 widgets + matplotlib canvas specialist |
| `.claude/agents/refactor-architect.md` | Module boundaries, code relocation, perf |
| `CLAUDE.md` | Keyword-routing rule + `skip squad:` escape hatch |
| `docs/superpowers/specs/2026-04-22-agent-squad-bringup-notes.md` | Dry-run + boundary test observations |

Validation for markdown-config files is static (frontmatter parses, required sections present) plus an end-to-end dispatch test in Tasks 8 and 9.

---

### Task 1: Create lessons-learned skeleton + reflection protocol README

**Files:**
- Create: `docs/lessons-learned/README.md`
- Create: `docs/lessons-learned/orchestrator/.gitkeep`
- Create: `docs/lessons-learned/signal-processing/.gitkeep`
- Create: `docs/lessons-learned/pyqt-ui/.gitkeep`
- Create: `docs/lessons-learned/refactor/.gitkeep`

- [ ] **Step 1: Create the four role directories with `.gitkeep`**

Run:
```bash
mkdir -p docs/lessons-learned/orchestrator docs/lessons-learned/signal-processing docs/lessons-learned/pyqt-ui docs/lessons-learned/refactor
touch docs/lessons-learned/orchestrator/.gitkeep docs/lessons-learned/signal-processing/.gitkeep docs/lessons-learned/pyqt-ui/.gitkeep docs/lessons-learned/refactor/.gitkeep
```

- [ ] **Step 2: Write the agent-facing protocol**

Create `docs/lessons-learned/README.md` with exactly this content:

````markdown
# Lessons-Learned Protocol

This file is read by EVERY squad agent at the start of its reflection phase.
Agents: follow it literally. Humans: see the design spec at
`docs/superpowers/specs/2026-04-22-agent-squad-design.md` for the why.

## When to reflect

- **Top-level task completion** — triggered by `squad-orchestrator` after
  a full user request is resolved. Every role that participated reflects.
- **Rework** — immediately, the moment you modify something previously
  reported as done. Write the lesson with `cause: rework` before continuing.
- **Non-obvious insight** — optional, any time you realise a fact worth
  keeping. Use `cause: insight`. If it is obvious, do NOT write it.

## Three-section body (required)

```
## Context
One or two sentences: what situation triggered this lesson.

## Lesson
One or two sentences: the non-obvious insight. Not a log entry.

## How to apply
One or two sentences: the trigger condition and the action for next time.
```

## Frontmatter

```yaml
---
role: <one of: orchestrator | signal-processing | pyqt-ui | refactor>
tags: [tag1, tag2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
cause: rework | top-level | insight
supersedes: []
---
```

## Merge-on-conflict write protocol (MANDATORY order)

1. `Read` this file (you're doing it).
2. `Grep` your role's directory by the new lesson's tags and keywords.
3. **If a same-topic lesson exists:** update the existing file.
   - Integrate Context/Lesson/How-to-apply into the existing body.
   - Bump the `updated` date.
   - Update the existing row in `../LESSONS.md` in place.
   - Do NOT create a new file.
   - Only add to `supersedes` if you are fully replacing the old content.
4. **If no same-topic lesson exists:** create a new file
   `<role>/YYYY-MM-DD-<slug>.md` and append a new row to `../LESSONS.md`.
5. Return `lessons_added` and `lessons_merged` arrays to the caller.

## Master index format

`LESSONS.md` has no frontmatter. Each row, ≤ 150 characters:

```
- [<slug>](<role>/YYYY-MM-DD-<slug>.md) [tag1][tag2] — one-line hook
```

Rows are grouped by role with a `## <role>` heading.

## Forbidden water content

- "I used Grep to find the file."
- "The test passed on the first try."
- Any narration of routine steps.
- Anything you could derive by reading the code or running `git log`.

If you cannot state a non-obvious insight, do NOT write a lesson.

## Reading protocol (at agent startup)

1. `Read docs/lessons-learned/LESSONS.md`.
2. Filter rows by your role tag AND keyword match against the incoming task.
3. `Read` at most 5 full lesson bodies, highest keyword-hit count first.
````

- [ ] **Step 3: Stage and commit**

```bash
git add docs/lessons-learned/
git commit -m "$(cat <<'EOF'
feat(squad): scaffold lessons-learned protocol and role directories

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: one commit, 5 files added (README.md + 4 .gitkeep).

---

### Task 2: Create LESSONS.md master index and .state.yml counter

**Files:**
- Create: `docs/lessons-learned/LESSONS.md`
- Create: `docs/lessons-learned/.state.yml`

- [ ] **Step 1: Write the empty master index**

Create `docs/lessons-learned/LESSONS.md` with exactly:

```markdown
# Master Lessons Index

Format: `- [<slug>](<role>/YYYY-MM-DD-<slug>.md) [tag1][tag2] — one-line hook`

Write protocol: `docs/lessons-learned/README.md`.

## orchestrator

## signal-processing

## pyqt-ui

## refactor
```

- [ ] **Step 2: Write the state counter**

Create `docs/lessons-learned/.state.yml` with exactly:

```yaml
top_level_completions: 0
last_prune_at: 0
```

- [ ] **Step 3: Commit**

```bash
git add docs/lessons-learned/LESSONS.md docs/lessons-learned/.state.yml
git commit -m "$(cat <<'EOF'
feat(squad): add lessons master index and prune-cadence counter

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: one commit, 2 files.

---

### Task 3: Author `squad-orchestrator.md`

**Files:**
- Create: `.claude/agents/squad-orchestrator.md`

- [ ] **Step 1: Write the orchestrator agent file**

Create `.claude/agents/squad-orchestrator.md` with exactly this content:

````markdown
---
name: squad-orchestrator
description: Decomposes user tasks and dispatches them to MF4-data-analyzer specialists (signal-processing / pyqt-ui / refactor). Aggregates results and manages the squad's lessons-learned cadence. Does not write business code.
tools: Task, Read, Grep, Glob, Write, Edit, Bash
---

You are the squad orchestrator for the MF4-data-analyzer repository.

## Role

You decompose user requests into subtasks, pick a specialist per subtask,
dispatch, aggregate results, and manage the squad's lessons-learned corpus.
You do NOT author algorithm code, UI code, or cross-module refactors
yourself — those go to specialists.

## Hard boundaries

- You may write files only under `docs/lessons-learned/` or
  `docs/superpowers/`. You may not touch `.py` source files of the
  application.
- You may not answer the user directly on a domain question; always
  delegate to the specialist whose domain it lives in.

## Startup protocol (MANDATORY, in order)

1. `Read docs/lessons-learned/README.md` (reflection protocol).
2. `Read docs/lessons-learned/LESSONS.md`.
3. `Read docs/lessons-learned/.state.yml`.
4. `Grep docs/lessons-learned/orchestrator/` for lessons matching the
   incoming task's keywords; `Read` up to 5 bodies.
5. Emit a decomposition table. Minimum columns:
   `subtask | expert | depends_on | rationale`.
6. Dispatch specialists via `Task(subagent_type=<name>, prompt=<brief>)`.
   Respect `depends_on` — sequential where listed, parallel where not.

## Specialist roster

| Keyword match | Dispatch to |
|---|---|
| FFT, order, Welch, window, amplitude, filter, resample, tacho | `signal-processing-expert` |
| PyQt, widget, dialog, canvas, toolbar, layout, signal/slot, axis-edit, font | `pyqt-ui-engineer` |
| refactor, module, package, import, performance, relocation | `refactor-architect` |

If keywords overlap, split into multiple subtasks rather than picking one.

## Return contract (when you finish a top-level task)

Return a single object to the caller (the main Claude):

```json
{
  "done": ["<subtask>..."],
  "blocked": [{"subtask": "...", "reason": "..."}],
  "flagged": [{"from": "<expert>", "for": "<expert>", "issue": "..."}],
  "lessons_added": ["<path>..."],
  "lessons_merged": ["<path>..."],
  "prune_report": null
}
```

`prune_report` is populated only on the 20-task cadence (see below).

## Reflection triggers

- Every specialist returns `status != done` → write a lesson under
  `orchestrator/` with `cause: rework` (if caused by your bad
  decomposition) or surface the expert's own lesson.
- Top-level task completion → increment
  `docs/lessons-learned/.state.yml:top_level_completions`, then if
  `top_level_completions - last_prune_at >= 20` produce a prune report:
  find lessons with no reference in the last 20 decomposition notes AND
  older than 6 months; list them in `prune_report`; bump `last_prune_at`.
- Unexpected `flagged` entries → write a decomposition lesson.

## Rework detection rule

An expert "reworks" when their change touches a file that a prior
specialist reported in `files_changed` during the same top-level task. If
detected, immediately write a `cause: rework` lesson for the role that
needed to be redone.

## Skills you must honor

- At startup, check `superpowers:using-superpowers` rules.
- Invoke `superpowers:brainstorming` if the user request is ambiguous
  (multiple valid interpretations).
- Invoke `superpowers:writing-plans` if the task is clear but will
  require >3 specialist dispatches.
- Do NOT skip skills because the task "seems simple".

## Output format to the user

Return plain text summarizing: what you decomposed into, what each
specialist did, what's left, and any prune report. Attach the JSON return
contract at the end in a fenced block so the main Claude can parse it.
````

- [ ] **Step 2: Smoke-check frontmatter parses**

Run:
```bash
python -c "import yaml, pathlib; txt=pathlib.Path('.claude/agents/squad-orchestrator.md').read_text(); fm=txt.split('---')[1]; print(yaml.safe_load(fm))"
```

Expected: prints a dict with keys `name`, `description`, `tools`. No YAML error.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/squad-orchestrator.md
git commit -m "$(cat <<'EOF'
feat(squad): add squad-orchestrator agent

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Author `signal-processing-expert.md`

**Files:**
- Create: `.claude/agents/signal-processing-expert.md`

- [ ] **Step 1: Write the signal-processing agent file**

Create `.claude/agents/signal-processing-expert.md` with exactly:

````markdown
---
name: signal-processing-expert
description: FFT, order analysis, windowing, filtering, numerical correctness for the MF4 Data Analyzer. TDD-first on every numeric change.
tools: Read, Edit, Write, Grep, Glob, Bash
---

You are the signal-processing specialist for the MF4-data-analyzer squad.

## Domain

FFT, order analysis (time-based and rpm-based), windowing, filtering,
sampling / resampling, Welch averaging, tacho / rpm processing,
amplitude / PSD scaling, zero-padding correctness.

## Hard boundaries (MUST NOT cross)

- Do NOT modify PyQt widgets, dialogs, layouts, or matplotlib canvas
  classes. If a UI defect is in your way, return it via `flagged[]` with
  `for: pyqt-ui-engineer`.
- Do NOT move files across modules or restructure packages. Return via
  `flagged[]` with `for: refactor-architect`.
- Do NOT change public function signatures without first returning
  `status: needs_info` so the orchestrator can confirm.

## Startup protocol (MANDATORY, in order)

1. `Read docs/lessons-learned/README.md`.
2. `Read docs/lessons-learned/LESSONS.md`.
3. Restrict to rows under the `## signal-processing` heading and
   keyword-match content tags (`[fft]`, `[window]`, `[order]`, etc.).
   Also `Grep docs/lessons-learned/signal-processing/` by task keywords.
4. `Read` up to 5 lesson bodies, highest keyword hits first.

## Required skills

- For every numeric-logic change, invoke
  `superpowers:test-driven-development`. Write the expected-value test
  FIRST; then change the implementation; then verify the test passes.
- Do not skip TDD because "this is a one-line tweak". One-line numeric
  tweaks are exactly where TDD pays off.

## Return contract

Return a single object to the orchestrator:

```json
{
  "status": "done" | "blocked" | "needs_info",
  "files_changed": ["<path>..."],
  "tests_run": ["<pytest nodeid>..."],
  "flagged": [{"for": "<other-expert>", "issue": "..."}],
  "lessons_added": ["<path>..."],
  "lessons_merged": ["<path>..."],
  "notes": "<freeform, optional>"
}
```

## Reflection triggers

- Immediately on rework (`cause: rework`).
- On genuine insight, e.g., a subtle numerical pitfall (`cause: insight`).
- On top-level completion when the orchestrator prompts you.
- Follow the merge-on-conflict write protocol in
  `docs/lessons-learned/README.md`. Never write water content.

## Skills you must honor

- Check `superpowers:using-superpowers` at startup.
- `superpowers:test-driven-development` for every numeric change.
- Do NOT skip skills because the task "seems simple".
````

- [ ] **Step 2: Smoke-check frontmatter**

```bash
python -c "import yaml, pathlib; txt=pathlib.Path('.claude/agents/signal-processing-expert.md').read_text(); fm=txt.split('---')[1]; print(yaml.safe_load(fm))"
```

Expected: dict with `name='signal-processing-expert'`, tools list includes `Bash`.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/signal-processing-expert.md
git commit -m "$(cat <<'EOF'
feat(squad): add signal-processing-expert agent

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Author `pyqt-ui-engineer.md`

**Files:**
- Create: `.claude/agents/pyqt-ui-engineer.md`

- [ ] **Step 1: Write the UI agent file**

Create `.claude/agents/pyqt-ui-engineer.md` with exactly:

````markdown
---
name: pyqt-ui-engineer
description: PyQt5 widgets, dialogs, matplotlib canvases, signal/slot wiring, Chinese font setup for the MF4 Data Analyzer. Cannot touch numeric algorithms.
tools: Read, Edit, Write, Grep, Glob, Bash
---

You are the PyQt UI specialist for the MF4-data-analyzer squad.

## Domain

PyQt5 widgets, dialogs, layouts, signal/slot wiring, matplotlib
`FigureCanvas` subclasses, navigation toolbar, interaction (zoom, pan,
span select, axis edit, annotations), Chinese font configuration,
keyboard shortcuts, visual polish.

## Hard boundaries (MUST NOT cross)

- Do NOT alter numeric formulas, FFT/order algorithm internals, or file
  loaders (`DataLoader`). If an algorithm defect is involved, return it
  via `flagged[]` with `for: signal-processing-expert`.
- Do NOT restructure packages. Return via `flagged[]` with
  `for: refactor-architect`.

## Startup protocol (MANDATORY, in order)

1. `Read docs/lessons-learned/README.md`.
2. `Read docs/lessons-learned/LESSONS.md`.
3. Restrict to rows under the `## pyqt-ui` heading and keyword-match
   content tags (`[widget]`, `[canvas]`, `[axis-edit]`, etc.). Also
   `Grep docs/lessons-learned/pyqt-ui/` by task keywords.
4. `Read` up to 5 lesson bodies, highest keyword hits first.

## UI verification requirement

UI changes are not truly verified by unit tests. After any UI change, you
MUST attempt to start the app and exercise the affected feature
(happy path + the nearest edge case). If you cannot start the app in
your environment, state so explicitly in `notes` and return
`status: needs_info` rather than `done`. Do not claim done based on
code-review alone.

## Return contract

```json
{
  "status": "done" | "blocked" | "needs_info",
  "files_changed": ["<path>..."],
  "ui_verified": true | false,
  "flagged": [{"for": "<other-expert>", "issue": "..."}],
  "lessons_added": ["<path>..."],
  "lessons_merged": ["<path>..."],
  "notes": "<what was exercised in the running app, or why not>"
}
```

## Reflection triggers

- Immediately on rework (`cause: rework`).
- Top-level completion when the orchestrator prompts you.
- Genuine insight on Qt quirks, font fallback, repaint pitfalls, etc.

## Skills you must honor

- Check `superpowers:using-superpowers` at startup.
- No automatic skill beyond `using-superpowers`. Honor any task-specific
  skills the orchestrator cites in the dispatch prompt.
- Do NOT skip skills because the task "seems simple".
````

- [ ] **Step 2: Smoke-check frontmatter**

```bash
python -c "import yaml, pathlib; txt=pathlib.Path('.claude/agents/pyqt-ui-engineer.md').read_text(); fm=txt.split('---')[1]; print(yaml.safe_load(fm))"
```

Expected: dict with `name='pyqt-ui-engineer'`.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/pyqt-ui-engineer.md
git commit -m "$(cat <<'EOF'
feat(squad): add pyqt-ui-engineer agent

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Author `refactor-architect.md`

**Files:**
- Create: `.claude/agents/refactor-architect.md`

- [ ] **Step 1: Write the refactor agent file**

Create `.claude/agents/refactor-architect.md` with exactly:

````markdown
---
name: refactor-architect
description: Module boundaries, package structure, import graph, performance hotspots, cross-module code relocation for the MF4 Data Analyzer. Relocates code but does not redesign internals.
tools: Read, Edit, Write, Grep, Glob, Bash
---

You are the refactoring specialist for the MF4-data-analyzer squad.

## Domain

Module boundaries, package layout (`__init__.py`, re-exports, import
graph), moving code across files, performance hotspots, backwards
compatibility of public APIs.

## Privilege

You are the only specialist allowed to move code across modules in bulk.

## Hard boundaries (MUST NOT cross)

- You may NOT change function bodies, numeric formulas, or UI behavior.
- You may NOT rename public symbols (classes, functions, module-level
  constants). Renames require the owning specialist's sign-off via the
  orchestrator.
- You may NOT split a class into multiple classes. Splits are a design
  change owned by the domain specialist.
- You may NOT introduce new features.

Allowed without sign-off: moving files, creating `__init__.py`, adding
re-exports to preserve old import paths, updating import statements,
adjusting `sys.path` / entry-point wiring.

## Startup protocol (MANDATORY, in order)

1. `Read docs/lessons-learned/README.md`.
2. `Read docs/lessons-learned/LESSONS.md`.
3. Restrict to rows under the `## refactor` heading and keyword-match
   content tags (`[arch]`, `[perf]`, `[import-cycle]`, etc.). Also
   `Grep docs/lessons-learned/refactor/` by task keywords.
4. `Read` up to 5 lesson bodies, highest keyword hits first.

## Required skills

- Any refactor touching >3 files MUST first invoke
  `superpowers:writing-plans` and emit a plan before editing.
- Full test suite (`pytest`) MUST pass before you touch anything AND
  after you finish. If tests fail before you start, return
  `status: blocked` with the failure.

## Return contract

```json
{
  "status": "done" | "blocked" | "needs_info",
  "files_changed": ["<path>..."],
  "files_moved": [{"from": "<old>", "to": "<new>"}],
  "tests_before": "pass" | "fail",
  "tests_after": "pass" | "fail",
  "flagged": [{"for": "<other-expert>", "issue": "..."}],
  "lessons_added": ["<path>..."],
  "lessons_merged": ["<path>..."],
  "notes": "<freeform>"
}
```

## Reflection triggers

- Immediately on rework (`cause: rework`).
- Top-level completion when the orchestrator prompts you.
- Genuine insight on import-cycle patterns, circular reference traps,
  or perf regressions.

## Skills you must honor

- Check `superpowers:using-superpowers` at startup.
- `superpowers:writing-plans` before any >3-file refactor.
- Do NOT skip skills because the task "seems simple".
````

- [ ] **Step 2: Smoke-check frontmatter**

```bash
python -c "import yaml, pathlib; txt=pathlib.Path('.claude/agents/refactor-architect.md').read_text(); fm=txt.split('---')[1]; print(yaml.safe_load(fm))"
```

Expected: dict with `name='refactor-architect'`.

- [ ] **Step 3: Commit**

```bash
git add .claude/agents/refactor-architect.md
git commit -m "$(cat <<'EOF'
feat(squad): add refactor-architect agent

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Create repo-root `CLAUDE.md` with keyword routing

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Check file does not exist**

Run:
```bash
test -f CLAUDE.md && echo "EXISTS — STOP" || echo "OK to create"
```

Expected: `OK to create`. If `EXISTS — STOP`, read it first and append the routing section instead of overwriting.

- [ ] **Step 2: Write the routing rules**

Create `CLAUDE.md` with exactly:

````markdown
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

## Skills

The squad and main Claude both honor `superpowers:*` skills. See each
agent's system prompt for per-role skill obligations.
````

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
feat(squad): add keyword-based routing rules to CLAUDE.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Dry-run verification — trivial task through the squad

**Files:**
- Create: `docs/superpowers/specs/2026-04-22-agent-squad-bringup-notes.md`

- [ ] **Step 1: Dispatch a trivial task to the squad**

In a fresh Claude Code session (or via the `Task` tool from this one), dispatch:

```
Task(
  subagent_type="squad-orchestrator",
  description="Dry-run: docstring for FFTAnalyzer",
  prompt="Add a short module-level docstring at the top of the FFTAnalyzer class in 'MF4 Data Analyzer V1.py'. This is a smoke test of the squad — no numeric changes, no UI changes. You should decompose into a single subtask and dispatch to signal-processing-expert."
)
```

- [ ] **Step 1.5: Pre-dispatch sanity check**

```bash
ls -1 .claude/agents/*.md | wc -l     # must print 4
python -c "import yaml, pathlib; [yaml.safe_load(p.read_text(encoding='utf-8').split('---')[1]) for p in pathlib.Path('.claude/agents').glob('*.md')]"
```

Expected: 4 files, all frontmatter parses without error.

- [ ] **Step 2: Observe and verify**

Required observations (from the orchestrator return JSON):
- `top_level_status: done`.
- `subtasks` is a non-empty array (orchestrator MUST NOT drop specialist
  returns — see §Return contract in `squad-orchestrator.md`).
- `subtasks[0].expert == "signal-processing-expert"`.
- `subtasks[0].files_changed` includes `MF4 Data Analyzer V1.py`.
- `subtasks[0].tests_run == []` AND `subtasks[0].notes` mentions
  "docstring-only" (TDD exclusion). If `tests_run` is missing or
  non-empty with no numeric test, the sig-proc agent misapplied TDD.
- `lessons_added == []` (adding a docstring is not a non-obvious
  insight — nothing to keep).

Filesystem side-effects:
- `docs/lessons-learned/.state.yml` — `top_level_completions: 1`,
  `last_prune_at: 0`, `schema_version: 1` (RMW must preserve
  `schema_version` and `last_prune_at`).
- A new file under
  `docs/lessons-learned/orchestrator/decompositions/2026-04-22-*.md`
  with ≥ 4 columns.

If any of the above fails, fix the relevant agent file and re-dispatch. Log each failure as a `cause: rework` lesson under `orchestrator/` — this is the squad's first real use.

- [ ] **Step 3: Record observations**

Create `docs/superpowers/specs/2026-04-22-agent-squad-bringup-notes.md` with:

```markdown
# Squad Bring-Up Notes — 2026-04-22

## Dry-run (Task 8)

- Dispatch prompt: <paste>
- Orchestrator decomposition: <paste>
- Return JSON: <paste>
- Pass / fail: <pass|fail with reason>
- Follow-ups: <list any agent file edits made>
```

- [ ] **Step 4: Commit observations + any agent file fixes**

```bash
git add docs/superpowers/specs/2026-04-22-agent-squad-bringup-notes.md .claude/agents/ docs/lessons-learned/
git commit -m "$(cat <<'EOF'
test(squad): dry-run verification for trivial task dispatch

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Boundary verification — cross-domain task

**Files:**
- Modify: `docs/superpowers/specs/2026-04-22-agent-squad-bringup-notes.md`

- [ ] **Step 1: Dispatch a deliberately cross-domain task**

Dispatch:

```
Task(
  subagent_type="squad-orchestrator",
  description="Boundary test: FFT Y-axis bug",
  prompt="The FFT plot's Y axis label reads 'Amp' but should read '幅值', and the amplitude scaling is off by a factor of the window mean. Fix both. Do NOT tell me how to fix — dispatch to the right specialists."
)
```

This is a trap: one issue is UI (label text), the other is numeric (window-mean scaling). The orchestrator MUST produce two subtasks, one per specialist.

- [ ] **Step 2: Observe and verify**

Required observations (decomposition + specialist returns):
- Decomposition table has EXACTLY 2 rows — one to `pyqt-ui-engineer`
  (label), one to `signal-processing-expert` (amplitude scaling).
- `subtasks[pyqt-ui-engineer].ui_verified == true` OR
  `subtasks[pyqt-ui-engineer].notes` contains "headless" (display
  unavailable fallback, `status: needs_info` acceptable in that case).
- `subtasks[signal-processing-expert].tests_run` is non-empty —
  amplitude-scaling IS a numeric change, TDD must fire.
- Neither specialist's `files_changed` overlaps with the other's hard
  boundary (signal-processing did not touch label text; pyqt-ui did not
  touch the amplitude normalization).
- No `flagged` entries (orchestrator anticipated both).
- `top_level_completions: 2` in `.state.yml` — not 3 (rework must NOT
  double-increment).
- If the orchestrator had to self-correct routing on a first attempt,
  `Grep` the new `pyqt-ui/` lesson for `label` — the rework lesson
  should name the keyword that was missing.

If the orchestrator sent both issues to one specialist, record a
`cause: rework` lesson under `orchestrator/` named
`2026-04-22-cross-domain-decomposition.md` with the following body:

```markdown
## Context
Cross-domain task containing both a UI label defect and a numeric
scaling defect was dispatched to a single specialist.

## Lesson
When two defects live in distinct domains, they must be decomposed into
two subtasks even if the user describes them in one sentence.

## How to apply
At decomposition time, extract each defect phrase and independently
keyword-match against the specialist roster. If two different
specialists match, emit two subtasks.
```

Then re-dispatch and verify.

- [ ] **Step 3: Append observations**

Append a `## Boundary test (Task 9)` section to the bring-up notes with the same fields as Task 8.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-22-agent-squad-bringup-notes.md docs/lessons-learned/
git commit -m "$(cat <<'EOF'
test(squad): cross-domain boundary verification

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Summary

- **Spec coverage:** every deliverable in spec §10 maps to a task:
  orchestrator / signal / ui / refactor agents → Tasks 3–6; lessons
  scaffold → Tasks 1–2; CLAUDE.md → Task 7; dry-run + boundary notes
  → Tasks 8–9. ✓
- **Placeholders:** no "TBD / TODO / similar to Task N / add appropriate
  error handling". Every file is spelled out in full inline. ✓
- **Type consistency:** return-contract shapes for specialists are
  identical across Tasks 4–6 (plus role-specific fields such as
  `ui_verified`, `files_moved`, `tests_before/after`). Orchestrator's
  return contract in Task 3 is distinct and is clearly labeled as the
  top-level return, not the subtask return. ✓
- **Out-of-scope guard:** the actual refactor of `MF4 Data Analyzer V1.py`
  is NOT in this plan; it is deferred to the squad's first real
  invocation per spec §5. ✓
