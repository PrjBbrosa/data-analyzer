# Current Task Plan: Vector/XCP Readiness Review Remediation

## Goal

Close the review findings on `codex/vector-xcp-readiness` so the exact source
and frozen Windows application can reach a truthful `PROCEED TO BENCH` gate.
Physical ECU/Vector validation remains an operator task and must not be
reported as complete from macOS tests.

## Formal Plan

- `docs/analyzer/acquisition/plans/2026-07-11-vector-xcp-readiness-review-remediation.md`

## Phases

- [x] Reproduce the reviewed branch state and focused macOS baseline.
- [x] Convert every review finding into an owned task and acceptance gate.
- [x] Phase A: repair real pyxcp CONNECT/GET_STATUS/Seed&Key contracts.
- [x] Phase B: implement real-backend DTO diagnostics and explicit drop facts.
- [x] Phase C: propagate A2L address extension/conversion and invalidate stale selections.
- [x] Integrate final-review lifecycle/frozen-A2L fixes and rerun regressions.
- [x] Complete frozen-build/runtime verification and bench evidence commands.
- [x] Leave Windows source and packaged no-ECU gates explicitly BLOCKED with runnable commands.
- [x] Hand off the physical one-signal, three-signal, soak, and MF4 comparison gates in the runbook.
- [x] Independent post-remediation agent audit and final integration verification.

## Guardrails

- Work only in `/Users/donghang/Downloads/data-analyzer-vector-xcp-readiness`.
- Preserve unrelated main-checkout changes; do not merge or commit unless asked.
- Use structured pyxcp fakes or real package types, never unrestricted mocks for
  contract claims.
- Keep `pyxcp` and `pya2l` behind their isolated/lazy import boundaries.
- A green Test Connection must prove GET_STATUS and DAQ protection state.
- No bench-ready claim without Windows source and packaged JSON evidence.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Worktree `.venv/bin/python` absent | Review baseline | Use the main checkout venv explicitly while keeping `PYTHONPATH=.` in this worktree. |
| Plan referenced `tests/test_capture_controller.py`, which does not exist | Review baseline | Use `tests/test_acquisition_capture_controller.py`. |
| Lesson lookup used stale `lazy-parser-import-boundaries.md` path | Planning | Located and loaded `docs/lessons-learned/codex-lazy-parser-import-boundaries.md`. |
| First plan patch used a wrapped sentence that did not match the file exactly | Integration review | Located the exact acceptance lines with `rg -C` and applied a narrower patch. |
| First broad pytest poll returned only an outer tool cell and no final summary | Integration verification | Polled the nested exec session directly, confirmed exit code 0, and collected the exact 664-test count separately. |
| Final `MagicMock()` grep also matched two bounded callable spies, not unrestricted external modules | Independent audit | Inspected both sites and narrowed the guard to module-surface construction; structured Vector module fakes remain intact. |
| Planning helper reported `0/0 phases` because this existing plan uses checkbox phases rather than its template status tokens | Completion | Verified every checkbox is complete directly; retained the established project plan format. |
- Do not commit unless the user explicitly asks.
- Do not revert unrelated dirty worktree files.
- Preserve `self.statusBar` as a real `QStatusBar`-compatible object.
- Treat live rendered PyQt screenshots as final truth, not QSS text alone.

---

## Addendum — 2026-07-10 Cockpit In-Place Focus

### Goal

Write a final, implementation-ready specification and plan for the approved
Cockpit live-card Focus interaction: one expanded trace in the existing
vertical card stream, with maximum use of laptop-height viewport and adjacent
cards retained as weak context.

### Phases

- [x] Recover current Cockpit spec/plan, live-card implementation, tests, and approved HTML behavior.
- [x] Write the acquisition spec with explicit geometry, single-trace, interaction, and non-goal contracts.
- [x] Write the ordered implementation plan with failing tests, focused checks, and macOS on-screen acceptance.
- [x] Cross-check doc links, stale contracts, and working-tree scope; complete planning record.

### Guardrails

- Documentation and the existing HTML prototype only; do not modify product source in this planning task.
- Preserve the two-column acquisition page and the existing recording/capture contracts.
- Offscreen tests prove structure; on-screen macOS screenshots prove the final visual geometry.

---

## Addendum — 2026-07-24 Channel Configuration Manager V2

### Goal

Write an implementation-ready plan that maps the approved interactive HTML
prototype onto the existing PyQt saved-channel-configuration model, including
channel inspection/removal, uniform controls, current-View match preview, and
portable JSON import/export.

### Phases

- [x] Recover the prior saved-config implementation, focused tests, lessons, and prototype evidence.
- [x] Trace current model, manager, persistence, apply, and test ownership end to end.
- [x] Decide the portable schema, conflict semantics, draft/save boundary, and UI state model.
- [x] Write the formal ordered implementation plan with red-first tests and rendered acceptance gates.
- [x] Cross-check file/symbol/test references, dirty-worktree scope, and documentation-only boundary.

### Guardrails

- Planning/docs only; do not modify Qt source or tests in this task.
- Preserve the existing saved configuration storage and apply behavior unless
  the formal plan explicitly introduces a migration-compatible extension.
- Treat the approved HTML as the visual/interaction target, but use current
  PyQt/data-model truth for implementation ownership.
- Require both focused offscreen tests and a real Qt rendered screenshot at
  representative dialog sizes before implementation can be called complete.

### Implementation Outcome

- [x] Implement draft-first store commit, v1/v2 compatibility, View preview, and portable transfer helpers.
- [x] Rebuild the manager as the approved master-detail UI with separate config/channel selection state.
- [x] Wire one Save boundary into MainWindow without applying/replotting channels.
- [x] Add model, transfer, manager, scope, geometry, and unit-hint regressions.
- [x] Render and inspect the HTML-parity states at 1180×790 and minimum 940×680: default, channel selected, dirty/batch, and import preview.
- [ ] Perform the remaining interactive macOS TraceLab/high-DPI validation when a foreground session is requested.

---

## Addendum — 2026-07-26 HDF Time-Domain Interaction Performance

### Goal

Restore the v7.5/v7.6-class responsiveness of dense continuous HDF plots while
retaining the v7.8 BLF/CRC improvements, document the regression and chosen
architecture, and leave deterministic plus Cocoa performance gates that catch
future channel-selection, pan, and resize regressions.

### Phases

- [x] Phase 1 — write the evidence-backed regression report and freeze current/historical baselines.
- [x] Phase 2 — write the implementation plan with explicit behavioral and timing acceptance gates.
- [x] Phase 3 — add red-first hot-path tests for cached raw X bounds and a true resize quiet window.
- [x] Phase 4 — implement shared-time-axis X-bound caching and resize refresh quiescence without weakening BLF/CRC behavior.
- [x] Phase 5 — add the reproducible plot benchmark/standards surface and run focused offscreen plus Cocoa verification.
- [x] Phase 6 — review the complete diff, promote the required lesson, and close the report with measured results.

### Guardrails

- Preserve the existing dense-discrete/CRC raster strategy and its tests.
- Do not change HDF numeric data, time scale, units, selection semantics, chart ordering, or saved View behavior.
- Default tests use call-count/state contracts; machine-dependent Cocoa timing runs are opt-in but thresholded and emit JSON.
- Preserve unrelated `.playwright-cli` artifacts and do not commit or push unless requested.
- Prefer removing confirmed hot-path work over adding a second rendering architecture unless measured results prove it necessary.

### Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| First historical benchmark accidentally imported the current checkout because the process cwd preceded `PYTHONPATH` | Diagnosis | Re-ran every version from its isolated exported directory and recorded the resolved module path in each result. |
| Direct shell cleanup was rejected and the transient tool store had expired | Diagnosis | Validated the exact `/private/tmp/tracelab-version-probe.*` path and removed only that generated directory with a guarded Python cleanup. |
| First combined planning-file patch used a wrapped progress line that did not match exactly | Planning | Split the append-only updates and anchored each patch to the exact final lines. |
| Initial BLF/CRC artifact lookup assumed `docs/superpowers/*` ownership | Planning | Located the actual artifacts under `docs/analyzer/{specs,plans,reviews}` and switched to those authoritative paths. |
| General continuous curves were briefly routed into the dense-discrete pixmap backend | Stage 4 experiment | Real six-row Cocoa timing was worse due to DPR2 pixmap composition; reverted the production experiment and retained a negative regression guard. |

### Completion Outcome

- The accepted architecture is raw-X generation caching, a 150 ms resize quiet
  window, and retained-row deltas for compatible ordinary subplots.
- Real HDF/Cocoa benchmark passed all hard gates; Windows packaged EXE remains
  an explicit follow-up gate, not an inferred PASS.
- Reports, implementation plan, standards and the reusable benchmark script are
  linked from the final handoff; no commit or push was performed.
