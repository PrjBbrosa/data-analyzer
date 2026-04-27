# Decomposition audit — UI polish Wave 3 (Tasks 3.1 + 3.2)

**Date:** 2026-04-26
**Mode:** plan
**Source plan:** `docs/superpowers/plans/2026-04-26-ui-polish-and-order-rpm-removal.md` (lines 1913–1990)
**Spec:** `docs/superpowers/specs/2026-04-26-ui-polish-and-order-rpm-removal-design.md` (rev 4 — codex approved)
**Wave-1 gate report:** `docs/superpowers/reports/2026-04-26-ui-polish-wave1-review.md` (approved)
**Wave-2 gate report:** `docs/superpowers/reports/2026-04-26-ui-polish-wave2-review-rev2.md` (approved; rev1's only "minor revision" was a codex misread of the W1 acceptance grep)

## Wave-3 character

Wave 3 is an **acceptance-only wave**. No `.py` source-file edits.
Outputs are entirely under `docs/superpowers/reports/`:
- 4 PNG screenshots in a sibling directory.
- 1 final-acceptance report markdown file.
- 1 codex final-sign-off report (written by codex itself).

This changes the routing calculus. The squad runbook's "Phase 2 only
through specialists" rule applies to **`.py` source changes**; report
artifacts and screenshots are not in scope for that rule (compare
Wave-2's Task 2.14 codex gate, which was likewise main-Claude direct,
per `feedback_squad_wave_review.md`).

## Routing decisions per subtask

### 3.1 — 4-mode screenshots

**Decision:** Surface to user; do NOT dispatch a specialist.

Rationale:
- Screenshots require launching the **real** Qt GUI
  (`python "MF4 Data Analyzer V1.py"`), loading an `mf4` fixture from
  `testdoc/`, switching modes, and grabbing the full window. The plan
  step 1 says exactly `python "MF4 Data Analyzer V1.py"` (not
  `QT_QPA_PLATFORM=offscreen`).
- Subagents in Claude Code's runtime run in a sandbox that is not
  guaranteed to have a visible display server. Even where
  `QT_QPA_PLATFORM=offscreen` works (e.g., the
  `tightbbox-survives-offscreen-qt` lesson) the *result* is a buffer
  fed to matplotlib; full-window OS-level screenshots of a live PyQt
  app windowed on a desktop are NOT reproducible from a subagent.
- The plan's Step 4 says "目测对比 Image 11" — manual visual
  comparison is part of the acceptance criterion. That is a human
  action by definition.
- Even if a specialist could `xvfb-run` + `import` a screenshot, the
  resulting PNG is not "what the user sees" — Wave 3 is a
  **user-facing acceptance** wave; the human who will use the app must
  produce the artifacts.

Therefore 3.1 is the kind of work `feedback_squad_wave_review.md` and
`feedback_no_direct_edit.md` do NOT cover (no code change, no review
to gate). Main Claude should ask the user to produce the 4 PNGs and
commit them, then proceed.

### 3.2 — final grep + pytest + report + codex sign-off

**Decision:** Main-Claude direct, NOT specialist dispatch.

Rationale:
- Step 1 ("S4 unified grep, must be 0") is a shell command. Main
  Claude runs `Bash` in the squad runbook all the time (state file
  RMW, status checks). Running a `grep` is not a code change.
- Step 2 ("'rpm' literal grep, must be 0") — same as Step 1.
- Step 3 ("full pytest tail -10") — same as Step 1.
- Step 4 ("write final-report markdown") — output path is
  `docs/superpowers/reports/2026-04-26-ui-polish-final-report.md`.
  Reports under `docs/superpowers/reports/` are squad-managed artifacts;
  Wave-2 Task 2.14 review was likewise written by main Claude (or
  codex) directly, not via a `pyqt-ui-engineer` brief.
- Step 5 (codex final sign-off) — this IS the wave-end codex gate
  required by `feedback_squad_wave_review.md`. The runbook explicitly
  routes this through `Agent subagent_type=codex:codex-rescue`, NOT
  through `pyqt-ui-engineer`. Per
  `2026-04-25-codex-prompt-file-for-long-review.md` the prompt must
  use `--prompt-file` + `--write` because the artifact contract names
  a report path.
- Step 6 (commit) — main Claude.

Dispatching a specialist (e.g., `pyqt-ui-engineer`) for 3.2 would
introduce dispatch overhead, a non-trivial brief authoring cost, and
two layers of return-JSON shuffling, all to run three shell commands
and write a markdown summary. None of those steps need PyQt domain
expertise; they need shell + plan-line bookkeeping, which main Claude
already has.

### Caveat: pytest failures

If Step 3's pytest tail shows ANY failure, the rule
`feedback_no_direct_edit.md` re-engages — fixing a failing test means
editing `.py`, which MUST go through a specialist. In that case main
Claude pauses 3.2, dispatches an isolated `pyqt-ui-engineer` (or
`signal-processing-expert`, depending on which file owns the failure)
brief to repair, gates that repair through codex per
`feedback_squad_wave_review.md`, then resumes 3.2 from Step 1. This
caveat is captured in the brief notes for Step 3.

## Subtask table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| w3-1-four-mode-screenshots-user-task | main-claude (surface to user) | — | Live PyQt GUI required; subagent sandbox cannot produce reproducible OS-level full-window screenshots. Manual visual comparison ("目测对比 Image 11") is part of the acceptance criterion. |
| w3-2-final-grep-pytest-report-codex | main-claude (direct) | w3-1 | Three shell commands + one markdown summary + a codex-rescue dispatch — no `.py` changes; matches Wave-2 Task 2.14 precedent. Codex IS the wave-end review gate, not a `pyqt-ui-engineer` brief. |

## Lessons consulted (Step 4)

- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md`
  — re-confirms orchestrator plans, main Claude dispatches; unrelated
  to this wave's content but used as the framework for the
  main-claude routing carve-out.
- `docs/lessons-learned/orchestrator/2026-04-25-codex-prompt-file-for-long-review.md`
  — Step 5 codex prompt must be passed via `--prompt-file` plus
  `--write` since the contract names a report path.
- `docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md`
  — relevant ONLY to clarify that offscreen Qt buffers CAN feed
  matplotlib bbox crops (i.e., why we still consider whether a
  specialist could screenshot). Concludes against because the plan
  needs the live desktop window, not a matplotlib axes crop.
- Project memory `feedback_squad_wave_review.md` — codex review is the
  wave-end gate; reviewer scope is "files changed in this wave". For
  Wave 3 the only artifacts are the 4 PNGs, the final report, and the
  cumulative grep/pytest evidence.
- Project memory `feedback_module_review.md` — codex is the default
  reviewer; dispatch via `Agent subagent_type=codex:codex-rescue`
  without asking the user.
- Project memory `feedback_no_direct_edit.md` — applies only if a
  pytest failure forces a `.py` edit; documented as a caveat in 3.2's
  brief.

## Brief construction notes for main Claude

For **w3-1-four-mode-screenshots-user-task**: do not dispatch any
specialist. Compose a clear user-facing message that:
- explains why a subagent cannot do this step,
- gives the exact reproduction recipe from plan lines 1921–1932,
- lists the 4 target paths,
- offers to handle the commit (Step 5) once the user confirms the
  PNGs are in place.

Pause the wave at this point until the user confirms PNGs landed.

For **w3-2-final-grep-pytest-report-codex**, after PNG confirmation:
- Run the two greps, capture their (expected-empty) output.
- Run `pytest tests/ -v 2>&1 | tail -10`, capture output.
- If pytest fails, STOP and trigger the
  `feedback_no_direct_edit.md` repair sub-loop described above.
- Write the final report at
  `docs/superpowers/reports/2026-04-26-ui-polish-final-report.md`
  with the 5 required sections (acceptance check, screenshot links,
  pytest tail, grep evidence, per-wave review links).
- Dispatch codex with the prompt verbatim from plan line 1981, via
  `--prompt-file` + `--write` per
  `2026-04-25-codex-prompt-file-for-long-review.md`. Output report:
  `docs/superpowers/reports/2026-04-26-ui-polish-wave3-review.md`.
- Commit final report once codex approves.

## Notes

- Total dispatched specialists: **0**. Both Wave-3 subtasks are
  main-Claude direct.
- This is consistent with the squad runbook: "out of scope" includes
  "running builds" and Q&A. Acceptance verification (grep + pytest +
  evidence) is closer to ops than to specialist code work.
- Skill check: no `superpowers:brainstorming` invocation needed
  (request is unambiguous). `superpowers:writing-plans` already
  satisfied by the existing plan; no new plan artifact needed.
- `.state.yml` increment for this top-level (Wave 3) task is main
  Claude's responsibility on completion, per the planner-executor
  split.
