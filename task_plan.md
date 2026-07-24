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
