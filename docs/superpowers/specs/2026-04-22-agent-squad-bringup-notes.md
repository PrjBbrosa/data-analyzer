# Squad Bring-Up Notes — 2026-04-22

## Dry-run (Task 8)

### Attempt 1 — blocked, revealed architectural gap

**Dispatch:** `Task(squad-orchestrator, "add docstring to FFTAnalyzer ...")` single call, per the original plan.

**Outcome:** `top_level_status: blocked, reason: Task tool not available in orchestrator's tool list`.

**Root cause:** Claude Code's subagent runtime does NOT grant `Task` to
subagents (anti-recursion safety). The original design assumed
orchestrator would dispatch specialists — wrong assumption.

**Artifacts from the failed run (kept, correct):**
- `docs/lessons-learned/orchestrator/decompositions/2026-04-22-fftanalyzer-docstring-smoke-test.md` — decomposition audit file.
- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md` — lesson capturing the discovery (later rewritten to reflect the pivot).
- `.state.yml` untouched (blocked runs do NOT increment), correct.

### Architectural pivot (commit `9c5e421` + `ddebfb3`)

**Change:** planner-executor split. orchestrator becomes a planner
only; main Claude becomes the sole dispatcher.

Files:
- `.claude/agents/squad-orchestrator.md` — rewritten.
- `CLAUDE.md` — four-phase runbook (Plan / Execute / Aggregate / State).
- Specialists' return-contract prose updated ("to main Claude dispatcher").
- Spec addendum explaining the pivot.
- Plan Task 8 step rewritten to match runbook.
- Stale lesson rewritten in-place.

### Attempt 2 — full runbook exercised

**Phase 1 — Plan.** `Task(squad-orchestrator, "mode: plan ...")` →
returned `mode: plan, status: ok, decomposition: [{expert: signal-processing-expert, depends_on: [], ...}], applicable_lessons: [...], decomposition_audit_path: ...`.

Correct plan-mode contract. Reused the prior decomposition audit file
(`updated` bumped).

**Phase 2 — Execute.** `Task(signal-processing-expert, <brief>)` →
returned `status: done, files_changed: ["MF4 Data Analyzer V1.py"],
tests_run: [], notes: "docstring-only, TDD not applicable..."`.

Correct TDD exclusion behavior.

**Phase 3 — Aggregate.** Single subtask, no rework detection possible
(needs ≥ 2 subtasks for overlap check). No flagged entries. Aggregated
object:

```json
{
  "top_level_status": "done",
  "done": ["Add class-level docstring to FFTAnalyzer"],
  "blocked": [],
  "flagged": [],
  "subtasks": [{
    "expert": "signal-processing-expert",
    "status": "done",
    "files_changed": ["MF4 Data Analyzer V1.py"],
    "tests_run": [],
    "flagged": [],
    "lessons_added": [],
    "lessons_merged": [],
    "notes": "docstring-only, TDD not applicable. Inserted class-level docstring on FFTAnalyzer immediately after the class declaration at line 227; no numeric behavior or signatures changed."
  }],
  "lessons_added": [],
  "lessons_merged": [],
  "prune_report_path": null
}
```

**Phase 4 — State.** `.state.yml` RMW: `top_level_completions 0 → 1`;
`schema_version: 1` and `last_prune_at: 0` preserved. No prune (1 < 20).

### Pass / Fail

**PASS on second attempt.** Architecture pivot was the mandatory
follow-up; the runbook now works end-to-end for a single-specialist
task. TDD exclusion for docstring edits is honored. State counter
advances on completion, not on blocked runs.

### Monolith diff scope (confirms boundary discipline)

`git diff --stat "MF4 Data Analyzer V1.py"` → 5 lines inserted
(docstring + blank), no other changes. Specialist stayed in lane.

### Follow-ups for Task 9

- Two-specialist decomposition will exercise the rework detector
  (non-trivial only with cross-subtask `files_changed` overlap — Task
  9's trap is that `amplitude` and `label` are two different domains
  so overlap SHOULD be zero; rework is not expected on first attempt).
- Verify `ui_verified` branching: the UI agent must report `false` on
  a docstring-adjacent edit or emit a headless-environment note.
- Confirm `top_level_completions` goes to 2, not 3 (no rework
  double-increment).
