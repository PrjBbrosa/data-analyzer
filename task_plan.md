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
