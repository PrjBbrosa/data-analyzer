# Acquisition Validation Runbook

Use this runbook to decide how far a change must be validated before merge or
release. Source of decisions is the program plan
`docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md`
and the roadmap `docs/analyzer/acquisition/2026-05-14-data-acquisition-validation-roadmap.md`.

## Change Type Matrix

| Change type | Minimum checks |
| --- | --- |
| UI, plot, report formatting | `python scripts/acquisition_smoke.py` (covers unit + smoke dataset) |
| Signal processing algorithm | `python scripts/acquisition_smoke.py` **and** `pytest tests/synthetic -v` (synthetic = absolute correctness — required for algorithm changes) |
| MF4 import or channel mapping | smoke + `scripts/regression.py golden` + cross-vehicle manifest set |
| DBC/A2L or trigger config | preflight on real MF4 + bench validation template filled |
| New vehicle / ECU / harness / DAQ hardware | bench validation + vehicle quick check (using the templates) |
| Release candidate | smoke + golden + issue + bench or vehicle check when acquisition link changed |

Synthetic tests cover roadmap layer L1.5 — **absolute** numerical correctness.
Regression snapshots cover roadmap layer L2 — **relative** correctness vs the
last known-good output. Changing an algorithm without rerunning L1.5 risks
"the snapshot still matches but the math became wrong".

## Standard Commands

```bash
# Cross-platform smoke runner
python scripts/acquisition_smoke.py

# Per-piece
python -m pytest tests/synthetic -v
python scripts/regression.py smoke --manifest data/manifest.local.json
python scripts/regression.py golden --manifest data/manifest.local.json
python scripts/preflight.py path/to/file.mf4
python scripts/preflight.py path/to/file.mf4 \
    --signal-config-root configs/signals --vehicle X04C \
    --expected-channel vehicle_speed --expected-channel torsion_bar_torque
```

## Template Locations

- Bench validation: `docs/analyzer/acquisition/templates/bench_validation.md`
- Vehicle baseline: `docs/analyzer/acquisition/templates/vehicle_baseline.md`
- Vehicle quick check: `docs/analyzer/acquisition/templates/vehicle_quick_check.md`
- Issue capture (Bug → Regression loop): `docs/analyzer/acquisition/templates/issue_capture.md`
- XCP P0 evidence: `docs/analyzer/acquisition/P0_Runbook.md`

## When Vehicle Testing Is Still Required

Encoded from roadmap §11.

Still go on the vehicle:

- New car model
- New ECU
- New wiring harness
- New DAQ hardware or firmware
- Power / ground / sync / wake-sleep changes
- Major DBC / A2L / sampling-strategy change
- Trigger-logic / file-split / long-duration changes
- Real-world road-condition issue reproduction
- Release-candidate acceptance

Skip the vehicle:

- UI / plot / interaction / report formatting
- Post-processing tweaks already covered by historical MF4
- Channel-name display, export-field, chart-style adjustments
- Issue analysis where existing data already reproduces the problem

## Bug → Regression Procedure

Every real-world bug must become a permanent failing-then-passing test before
the fix is merged. See `templates/issue_capture.md`.

## Local Smoke Runner

Before committing acquisition validation changes:

```bash
python scripts/acquisition_smoke.py
```

If `data/manifest.local.json` is missing, the runner still runs unit and
synthetic checks and skips only the private local MF4 dataset, exiting 0 with
a clear note.
