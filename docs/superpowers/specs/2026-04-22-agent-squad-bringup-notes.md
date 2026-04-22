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

---

## Cross-domain boundary (Task 9) — PASS first try

### Phase 1 — Plan

Orchestrator returned the plan-mode contract with exactly 2 subtasks,
both with `depends_on: []` → dispatchable in parallel:

| subtask_slug | expert | rationale |
|---|---|---|
| `fft-ylabel-to-zh` | `pyqt-ui-engineer` | Y-label is a surface-keyword; route to UI even though "FFT" matches computation |
| `fft-amp-window-mean-normalization-sanity` | `signal-processing-expert` | numeric scaling is sig-proc domain |

Audit: `docs/lessons-learned/orchestrator/decompositions/2026-04-22-fft-ylabel-zh-and-amp-scaling-sanity.md`.

### Phase 2 — Execute (parallel)

**pyqt-ui-engineer** → `status: done`, `ui_verified: false` (headless
env, per agent's headless-detection rule). Changed both FFT amplitude
Y-labels to `'幅值'` at lines 2038 and 2173. Left the colorbar at line
2142 alone (correct — that's an order-spectrum colorbar, different
visual concern). `files_changed: ["MF4 Data Analyzer V1.py"]`.

**signal-processing-expert** → `status: done`, all 6 expected-value
tests pass. Confirmed `amp = 2 * |FFT| / n / mean(w)` is the correct
normalization for Hanning/Hamming/Blackman, survives DC offset
rejection, and is invariant under 4x zero-padding. Did NOT edit the
monolith — only added `tests/test_fft_amplitude_normalization.py`.
Noted a non-obvious technical detail: the test uses `ast.unparse` +
`exec` to import `FFTAnalyzer` in isolation because the main file
eagerly imports PyQt5 / matplotlib / asammdf at module scope, which
would drag the whole UI stack into every unit test. `files_changed:
["tests/test_fft_amplitude_normalization.py"]`.

Main Claude re-ran the tests locally via `unittest` (pytest not in the
venv): 6/6 OK, 48 ms. Specialist's claim verified independently.

### Phase 3 — Aggregate + rework detection

- `subtasks[0].files_changed ∩ subtasks[1].files_changed = ∅`
  (`MF4 Data Analyzer V1.py` vs `tests/test_fft_amplitude_normalization.py`)
  → **no rework detected**.
- `flagged: []` on both → no re-dispatch.
- Boundary discipline held: UI specialist did not touch any numeric
  code; sig-proc specialist did not touch any UI code and did not
  edit the monolith at all (correctly deferred to "no fix needed").

Aggregated:

```json
{
  "top_level_status": "done",
  "done": ["fft-ylabel-to-zh", "fft-amp-window-mean-normalization-sanity"],
  "blocked": [],
  "flagged": [],
  "subtasks": [
    {
      "expert": "pyqt-ui-engineer",
      "status": "done",
      "ui_verified": false,
      "files_changed": ["MF4 Data Analyzer V1.py"],
      "notes": "Changed 2 FFT Y-labels to '幅值'. Headless env → ui_verified:false."
    },
    {
      "expert": "signal-processing-expert",
      "status": "done",
      "tests_run": ["tests/test_fft_amplitude_normalization.py::FFTAmplitudeNormalizationTests::test_hanning_recovers_unit_amplitude_within_1pct", "...", "..."],
      "files_changed": ["tests/test_fft_amplitude_normalization.py"],
      "notes": "Amp normalization correct; added 6 TDD expected-value tests, all pass."
    }
  ],
  "lessons_added": [],
  "lessons_merged": [],
  "prune_report_path": null
}
```

### Phase 4 — State

`.state.yml`: `top_level_completions 1 → 2`. `last_prune_at: 0`
(1 < 20, no prune). `schema_version: 1` preserved.

### PASS

First try on the new runbook. Boundary discipline verified across both
"easy" (UI text change) and "tricky" (sig-proc sanity check with
potential temptation to edit correct code) subtasks. Squad architecture
works end-to-end.
