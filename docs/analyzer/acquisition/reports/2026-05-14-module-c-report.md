# Module C — Validation Workflow & Documentation

**Branch:** `feat/acquisition-validation-program` @ `616b5d5`
**Status:** done

## Summary

Module C delivered the validation workflow and documentation layer for the acquisition program in three commits. Task 1 added four markdown templates under `docs/analyzer/acquisition/templates/`, Task 2 introduced the consolidated `Validation_Runbook.md` (Change Type Matrix + Template Locations), and Task 3 replaced the earlier bash draft with a cross-platform Python smoke runner at `scripts/acquisition_smoke.py`. All four acceptance gates (C1–C4) PASS. The runner stays inside repo-owned tooling discipline: `sys.executable` over bare `python`, `pathlib` over string path math, `subprocess.call(cmd, cwd=REPO_ROOT, env=env)` with no shell, and an explicit `os.name == 'nt'` branch for Windows venv layout.

## Acceptance gates

| Gate | Status | Evidence |
| --- | --- | --- |
| C1 | PASS | All 4 templates exist under `docs/analyzer/acquisition/templates/` and are referenced from `Validation_Runbook.md` §Template Locations. |
| C2 | PASS | `.venv/bin/python scripts/acquisition_smoke.py --skip-regression` returns exit 0 after the acquisition/signal/smoke/synthetic test targets pass. `./scripts/acquisition_smoke.py` is also runnable from the repo root; avoid bare `python` on this macOS host because no `python` shim is installed. |
| C3 | PASS | Change Type Matrix in `Validation_Runbook.md` covers UI / signal-algorithm / MF4-import / DBC-A2L / new-vehicle / release-candidate per roadmap. |
| C4 | PASS | `templates/issue_capture.md` encodes the full roadmap §12 procedure: 10–60s clip, `sets:[issue]`, failing test FIRST, fix, promote. |

## Commits

| Task | SHA | Title |
| --- | --- | --- |
| Task 1 — Documentation templates | `7f78caf` | docs: add acquisition validation templates |
| Task 2 — Validation runbook | `b104e67` | docs: add acquisition validation runbook |
| Task 3 — Cross-platform smoke runner | `2718c7f` | chore: add cross-platform acquisition smoke runner |

## Tests

The smoke runner is self-checking: its exit code IS the acceptance signal, and Stage 3 polish now adds `tests/test_acquisition_smoke.py` to pin the runner's own control flow.

- **`--skip-regression` mode, current checkout:** targets 39 acquisition/synthetic test functions by inventory: manifest 10 + preflight 8 + regression 11 + signals 5 + smoke 3 + synthetic 2. This corrects the stale 19-test claim; the runner/pytest output remains the execution evidence.
- **Default mode:** runs the same unit/synthetic target list first. If `data/manifest.local.json` is absent, it prints the skip note and exits 0; if present, it runs `scripts/regression.py smoke --manifest <path>` and propagates failure as exit 1.

## Files changed

- `docs/analyzer/acquisition/templates/vehicle_baseline.md`
- `docs/analyzer/acquisition/templates/bench_validation.md`
- `docs/analyzer/acquisition/templates/vehicle_quick_check.md`
- `docs/analyzer/acquisition/templates/issue_capture.md`
- `docs/analyzer/acquisition/Validation_Runbook.md`
- `scripts/acquisition_smoke.py`
- `tests/test_acquisition_smoke.py` (Stage 3 polish coverage for the runner)

## Symbols touched

The only code symbols touched in Module C live inside `scripts/acquisition_smoke.py`: the module-level constants `REPO_ROOT` and `UNIT_TESTS`; and the helper functions `_python_executable`, `_run`, and `main`. The earlier `SIGNAL_TESTS` constant has been removed by Stage 3 polish; signal and smoke tests are now listed directly in `UNIT_TESTS`. Every other Module C deliverable is markdown (templates and the runbook) or runner-focused tests, so there are no other code surfaces in scope.

## Cross-platform discipline

- Uses `sys.executable` rather than a bare `python` invocation.
- Uses `pathlib` for all path construction instead of `os.path` string operations.
- Calls `subprocess.call(cmd, cwd=REPO_ROOT, env=env)`, without `shell=True`.
- Branches on `os.name == 'nt'` to resolve the venv interpreter path (`Scripts` on Windows vs `bin` on POSIX).
- Has no bash shebang in the `.py` file.
- No stale `acquisition_smoke.sh` existed in the tree; the planned `rm` step was a no-op.

## Concurrency observation

During Wave 3, the smoke runner transiently exited 1 because Module B had uncommitted preflight edits in flight and had landed a new legacy-parity test that depended on `PreflightResult.resolved_signals` before the supporting code was on disk. Once Module B's resume specialist committed at `616b5d5`, stage 1 went green and the runner returned 0 as designed. This is the fail-fast contract working — the runner correctly refused to advance to stage 2 while the regression suite was red — and not a runner bug.

## Residual risk and follow-up

- `data/manifest.local.json` is intentionally untracked; team members create it locally from `data/manifest.example.json` before exercising the round-trip path.
- CI integration (roadmap §14) is deferred to a future Module D — the current smoke runner is local-only.
- Cross-platform claims are theoretical on Windows until somebody actually runs it there; Module D should include a Windows CI matrix to convert the claim into evidence.
- Templates ship empty by design — do not fill in real vehicle data on commit.

## Lessons learned

- `docs/lessons-learned/signal-processing/2026-04-27-pathlib-text-io-needs-explicit-utf8-on-windows.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
- `docs/lessons-learned/signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md`
