---
date: 2026-05-14
task: Execute the acquisition validation program (Modules A, B, C) plus the executable subset of P0 on `feat/acquisition-validation-program`, following each plan TDD-verbatim and writing a work report per module.
branch: feat/acquisition-validation-program
mode: plan
---

# Decomposition

## Inputs

- Branch already exists at HEAD `6da3a36`. Plans already committed:
  - `docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md` (master index)
  - `docs/analyzer/acquisition/plans/2026-05-14-acquisition-offline-foundation.md` (Module A, 4 tasks)
  - `docs/analyzer/acquisition/plans/2026-05-14-acquisition-signal-aliases.md` (Module B, 2 tasks)
  - `docs/analyzer/acquisition/plans/2026-05-14-acquisition-validation-workflow.md` (Module C, 3 tasks)
  - `docs/analyzer/acquisition/plans/2026-05-13-xcp-acquisition-p0.md` (P0, 7 tasks)

## Routing notes

- All four plans are detailed line-level TDD scripts. Implementation = follow the plan verbatim. Specialist must red→green→commit per task.
- Plans live; specs requested by user already exist in the form of these plan docs plus the roadmap. We treat the plan files as the spec-of-record and add only a thin **per-module spec note** that records intent, acceptance gates, and the explicit subset to be executed on macOS (specifically for P0). This avoids redundant spec drafting and aligns with the program already on disk.
- Module A is foundational (manifest, preflight, regression, synthetic). Modules B and C both depend on A's `acquisition/` package being in place — A's preflight CLI and manifest schema are consumed by B's alias wiring and C's smoke runner.
- All Module A tasks (1–4) live under `mf4_analyzer/acquisition/` and `tests/` and `tests/synthetic/`. None of them belong to UI surface — these are computation/IO/CLI concerns. Route them to `signal-processing-expert`. No `pyqt-ui-engineer` involvement (no canvases, widgets, dialogs).
- Module B is also `signal-processing-expert` (acquisition signal alias resolution, preflight integration). It edits `mf4_analyzer/acquisition/preflight.py` and `analyze_mf4.py` (a CLI/script). Surface vs computation: these are computations + IO, not Qt UI.
- Module C is mostly **documentation + a Python smoke-runner script**. There is no algorithm work and no Qt UI. The closest specialist is `refactor-architect` — its role per CLAUDE.md is non-signal Python work and cross-module changes, and a cross-platform smoke runner is a Python orchestration script. Templates and runbook are pure markdown content under `docs/analyzer/acquisition/templates/` and `docs/analyzer/acquisition/Validation_Runbook.md`. Route to `refactor-architect`.
- P0 on macOS is partially executable. Tasks 1, 2, 3 are pure Python (dependency probe, MF4 load against existing analyzer, A2L parse) — `signal-processing-expert`. Tasks 4, 5 require Vector hardware on Windows → BLOCKED. Task 6 also requires hardware → BLOCKED. Task 7 (runbook writeup) reflects results and BLOCKED verdicts → `refactor-architect` (pure docs/orchestration).

## Serialization vs parallel

- **Specs phase (specs-A, specs-B, specs-C, specs-P0)** — emit short spec notes referencing the existing plans, listing acceptance gates and macOS-execution scope. These docs land under `docs/analyzer/acquisition/specs/`. They are docs-only and live in different files → can be authored in parallel by `refactor-architect`. We bundle all four spec notes into a single subtask (one specialist, one commit) to avoid four parallel commits and decomposition overhead — single specialist authoring four files in one wave is cheaper than four parallel dispatches.
- **Module A implementation** — single specialist (`signal-processing-expert`), four tasks in the same wave but executed sequentially per the plan (Task 1→2→3→4 each red→green→commit). One dispatch covers all four tasks.
- **Module A report + Module B impl + Module C impl** — after A merges/lands, B and C can parallelize because their file scopes are disjoint:
  - B touches: `mf4_analyzer/acquisition/signals.py` (new), `analyze_mf4.py`, `configs/standard_signals.json` (new), `tests/test_acquisition_signals.py` (new).
  - C touches: `docs/analyzer/acquisition/templates/*.md` (new), `docs/analyzer/acquisition/Validation_Runbook.md` (new), `scripts/acquisition_smoke.py` (new), `tests/test_acquisition_smoke.py` (new).
  - **Shared-file risk check:** B and C do NOT share any file. C may *reference* preflight CLI behaviour in its runbook prose but does not edit B's modules. Safe to parallelize.
  - **CAUTION:** Module A's report (a docs-only file under `docs/analyzer/acquisition/reports/`) must be authored serially after Module A completes — it cites A's actual test counts and gate results. Bundle Module A's report into the same `signal-processing-expert` dispatch that does the A implementation, OR have `refactor-architect` author it after A lands and before B/C dispatch. Choosing the latter keeps the implementation specialist focused on code/tests, and gives the report writer Module A's full return JSON to cite.
- **P0** runs in its own track. Tasks 1–3 (`signal-processing-expert`) are pure Python and can run in parallel with Modules B and C since they touch different files (`scripts/p0_dependency_probe.py`, `scripts/p0_mf4_load_check.py`, `mf4_analyzer/acquisition/xcp/a2l.py` or similar — per plan §Task 3). Task 7 (P0 runbook) is sequential after Tasks 1–3 land their evidence.
- **Reports** for each module are docs-only writeups under `docs/analyzer/acquisition/reports/YYYY-MM-DD-module-<X>-report.md`. Author by `refactor-architect`. They citation-link the specialist's return JSON (tests run, files changed, blocked items).

## Lesson-driven brief content (must be cited in every specialist brief)

1. **`signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md`** — when the plan prescribes a verbatim source block that defines a `SUPPORTED_*` set / method enum / function-name registry, the specialist must cross-check it against current dispatcher handlers and `git log` removals before pasting. Particularly relevant to Module A Task 2 (preflight CLI: any method/check enum), Module B Task 2 (preflight integration may reference a method set), Module C Task 2 (Change Type Matrix referencing `analyze_mf4` methods).
2. **`orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`** — every specialist must return `symbols_touched` in addition to `files_changed`. Pre-flight self-grep against the brief's forbidden-symbol list.
3. **`orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`** — applied at decomposition level: B and C are scheduled in parallel because no shared file. We pin this in the audit.
4. **`orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`** — applied: we bundle "implementation + import hygiene + docstrings" inside one specialist's brief per module to avoid handoff rework.
5. **`orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md`** — applied to Module B: alias-resolution may change a return shape from `dict` to `dict + resolved_signals`. The brief must list call sites of `analyze_mf4` and either bundle the call-site adaptation into B's scope OR explicitly sequence it. We pre-grep this in the brief.

## Decomposition table

| # | subtask | expert | depends_on | rationale |
|---|---|---|---|---|
| 1 | specs: write per-module spec notes (A/B/C/P0) under `docs/analyzer/acquisition/specs/`, each cross-linking the corresponding plan doc, recording the acceptance gates, and (P0 only) marking macOS-executable subset = Tasks 1–3 + Task 7-BLOCKED-verdict | refactor-architect | — | Docs-only, multi-file under `docs/`. No Python code. `refactor-architect` is the non-signal Python/docs owner per CLAUDE.md routing. Single specialist authors all four files in one commit to avoid parallel-file overhead. |
| 2 | implement Module A end-to-end: Tasks 1 (manifest) → 2 (preflight) → 3 (regression) → 4 (synthetic), strictly TDD per plan; return symbols_touched and forbidden-symbols self-check | signal-processing-expert | 1 | Pure Python computation/IO (manifest schema, preflight CLI, regression snapshots, synthetic FFT/COT tests). No UI. Plan is detailed line-level TDD; one specialist takes it linearly. |
| 3 | write Module A work report under `docs/analyzer/acquisition/reports/2026-05-14-module-a-report.md`: summary, acceptance gates A1–A4 status, tests run with counts, files changed, residual risks | refactor-architect | 2 | Docs-only writeup citing specialist 2's return JSON. Pure prose. |
| 4 | implement Module B: Task 1 (alias module + tests) → Task 2 (preflight integration + legacy-parity test), TDD per plan; pre-grep callers of `analyze_mf4` preflight functions in the brief; return `symbols_touched` | signal-processing-expert | 2 | Acquisition signal alias resolution + preflight integration. Computation/IO. Depends on A's `mf4_analyzer/acquisition/` package existing. |
| 5 | implement Module C: Task 1 (4 templates) → Task 2 (Validation_Runbook.md) → Task 3 (smoke runner `scripts/acquisition_smoke.py` + tests), TDD per plan | refactor-architect | 2 | Docs templates, runbook prose, and a cross-platform Python orchestration script. No signal algorithms; no Qt UI. Maps to `refactor-architect` (non-signal Python + docs). |
| 6 | write Module B work report under `docs/analyzer/acquisition/reports/2026-05-14-module-b-report.md` | refactor-architect | 4 | Docs-only. |
| 7 | write Module C work report under `docs/analyzer/acquisition/reports/2026-05-14-module-c-report.md` | refactor-architect | 5 | Docs-only. |
| 8 | implement P0 executable subset on macOS: Tasks 1 (clean branch + env), 2 (MF4 load), 3 (A2L parse), TDD per plan. Tasks 4–6 are explicitly out of scope (Vector hardware on Windows required); the specialist must NOT mock or fake hardware steps — they must record `status: blocked, reason: hardware-required-windows-vector` for those subtasks in its return JSON | signal-processing-expert | 1 | Pure Python: dependency probe, MF4 IO roundtrip against existing loader, A2L parser. Tasks 4–6 require physical Vector CAN hardware and Windows; on macOS they are intentionally skipped, not faked. |
| 9 | write P0 Runbook (Task 7 of P0 plan) under `docs/analyzer/acquisition/P0_Runbook.md` and a work report under `docs/analyzer/acquisition/reports/2026-05-14-p0-report.md`. Verdict = PARTIAL with the BLOCKED rows for Tasks 4–6 documented per plan §Task 7 template | refactor-architect | 8 | Docs-only. Reflects executable evidence from 8 and explicit BLOCKED rows. |

## Wave plan (main Claude executes)

- **Wave 1:** subtask 1 (specs) — one specialist.
- **Wave 2:** subtask 2 (Module A impl) and subtask 8 (P0 Tasks 1–3) in **parallel** — different specialists, no shared files (P0 lives under `scripts/p0_*` and a new `mf4_analyzer/acquisition/xcp/`, not under the Module A scope of `mf4_analyzer/acquisition/{manifest,preflight,regression,synthetic}.py`). Cross-check: A's plan does not write to `mf4_analyzer/acquisition/xcp/` per §File Structure; P0's plan does not write to `manifest.py`/`preflight.py`. Confirmed disjoint.
- **Wave 3:** subtask 3 (Module A report) — serial after Wave 2.
- **Wave 4:** subtask 4 (Module B impl) and subtask 5 (Module C impl) in **parallel** — disjoint files per the routing notes above.
- **Wave 5:** subtask 6 (B report) and subtask 7 (C report) and subtask 9 (P0 runbook+report) in **parallel** — three different files, no overlap.

## Shared-files audit (zero overlap required for any parallel wave)

| pair | shared file | mitigation |
|---|---|---|
| 2 vs 8 | none | confirmed via plan §File Structure of each |
| 4 vs 5 | none | B touches `acquisition/signals.py`, `analyze_mf4.py`, `configs/standard_signals.json`, `tests/test_acquisition_signals.py`; C touches `docs/analyzer/acquisition/templates/*`, `Validation_Runbook.md`, `scripts/acquisition_smoke.py`, `tests/test_acquisition_smoke.py` |
| 6 vs 7 vs 9 | none | three different report files under `docs/analyzer/acquisition/reports/` and `docs/analyzer/acquisition/P0_Runbook.md` |

## Lessons consulted

- `docs/lessons-learned/README.md`
- `docs/lessons-learned/LESSONS.md`
- `docs/lessons-learned/.state.yml`
- `docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
- `docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md`
- `docs/lessons-learned/signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md`
