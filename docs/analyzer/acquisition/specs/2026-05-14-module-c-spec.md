# Module C — Validation Workflow & Documentation Spec Note

**Date:** 2026-05-14
**Module:** C — Templates, runbook, smoke runner
**Plan (source of truth for steps):** [`../plans/2026-05-14-acquisition-validation-workflow.md`](../plans/2026-05-14-acquisition-validation-workflow.md)
**Program index:** [`../plans/2026-05-14-data-acquisition-validation-program.md`](../plans/2026-05-14-data-acquisition-validation-program.md)

This spec note describes intent, gates, and execution boundaries. Workflow content and runner details live in the plan.

## Intent

Turn Module A's offline pipeline (and Module B's signal aliases, when present) into a usable workflow with checked-in artefacts:

1. Four markdown templates — vehicle baseline, bench validation, vehicle quick check, issue capture — that operators fill out instead of re-inventing the same form on every run.
2. A `Validation_Runbook.md` that encodes the change-type matrix from roadmap §15 and points at the templates, the L1.5 synthetic gate, and the Bug → Regression loop from roadmap §12.
3. A single cross-platform Python smoke runner (`scripts/acquisition_smoke.py`) that wraps the Module A test set plus the local manifest regression — so Windows benches can run it under `py -3.12` with no bash shell.

This is pure documentation plus one tiny CLI runner; no new analyzer modules.

## Scope

Plan §File Structure:

- Create: `scripts/acquisition_smoke.py`
- Delete (if present from older drafts): `scripts/acquisition_smoke.sh`
- Create: `docs/analyzer/acquisition/templates/vehicle_baseline.md`
- Create: `docs/analyzer/acquisition/templates/bench_validation.md`
- Create: `docs/analyzer/acquisition/templates/vehicle_quick_check.md`
- Create: `docs/analyzer/acquisition/templates/issue_capture.md`
- Create: `docs/analyzer/acquisition/Validation_Runbook.md`

Module C does **not** touch `mf4_analyzer/`, the loader, or the alias sidecar.

## Acceptance gates

From the program index Acceptance Gate Matrix:

- **C1 Templates** — All four `templates/*.md` files exist and are referenced from `Validation_Runbook.md` under §Template Locations.
- **C2 Smoke runner** — `.venv/bin/python scripts/acquisition_smoke.py` or `./scripts/acquisition_smoke.py` exits 0 when Module A tests pass and `data/manifest.local.json` is either valid or absent. Exits 1 only when underlying tests or regression actually fail. Skips local-MF4 smoke cleanly when the manifest is absent; does not require a bash shell.
- **C3 Workflow rule** — `Validation_Runbook.md` contains the change-type matrix from roadmap §15 with at minimum: UI changes, signal-processing algorithm changes, MF4 import / channel mapping changes, DBC/A2L or trigger config changes, new vehicle / ECU / harness / DAQ hardware, release candidate. Synthetic tests are listed as **required** (not optional) for algorithm changes.
- **C4 Bug→Regression** — `templates/issue_capture.md` encodes roadmap §12: capture a 10–60s clip, add a manifest entry under `sets: [issue]` with `issue_tags`, write a failing test **first**, fix, then optionally promote the clip.

## Execution environment

- Python 3.12; the smoke runner uses only stdlib (`argparse`, `os`, `shutil`, `subprocess`, `sys`, `pathlib`).
- Run pattern: `.venv/bin/python scripts/acquisition_smoke.py` or `./scripts/acquisition_smoke.py` (POSIX) / `py -3.12 scripts/acquisition_smoke.py` (Windows). The runner prefers `$PYTHON`, then the repo `.venv`, then `sys.executable`.
- Depends on Module A's scripts (`scripts/preflight.py`, `scripts/regression.py`) and test files. Stage 3 polish now keeps signal and smoke tests listed directly in `UNIT_TESTS`.
- Templates ship empty (no confidential vehicle/baseline data committed).
- No bash dependency: any stale `scripts/acquisition_smoke.sh` is removed during Task 3 Step 1.
- No CI integration in this module — that is deferred to future Module D.

## Out of scope

- CI integration (pre-commit, PR gates) — separate planned spec `2026-05-14-acquisition-ci-integration.md`.
- Bad-case synthetic MF4 corpus (roadmap L3) — separate planned spec `2026-05-14-acquisition-badcase-corpus.md`.
- XCP / Vector P0 execution — existing P0 plan; runbook only references `P0_Runbook.md`, it does not implement it.
- Changes to analyzer code (`mf4_analyzer/**`) or the alias sidecar.
- Filling out templates with real vehicle data — templates are blank fixtures; per-vehicle baselines are filed under `docs/vehicles/<id>/baseline.md` by the baseline owner, outside this module.

## Links

- Plan (source of truth for steps): [`../plans/2026-05-14-acquisition-validation-workflow.md`](../plans/2026-05-14-acquisition-validation-workflow.md)
- Program index & acceptance gate matrix: [`../plans/2026-05-14-data-acquisition-validation-program.md`](../plans/2026-05-14-data-acquisition-validation-program.md)
- Upstream Module A spec: [`./2026-05-14-module-a-spec.md`](./2026-05-14-module-a-spec.md)
- Sibling Module B spec: [`./2026-05-14-module-b-spec.md`](./2026-05-14-module-b-spec.md)
- P0 spec (referenced from the runbook's evidence section): [`./2026-05-14-p0-spec.md`](./2026-05-14-p0-spec.md)
- Roadmap (§10–§12, §15 rationale): [`../2026-05-14-data-acquisition-validation-roadmap.md`](../2026-05-14-data-acquisition-validation-roadmap.md)
