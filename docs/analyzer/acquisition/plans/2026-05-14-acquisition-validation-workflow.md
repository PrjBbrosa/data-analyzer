# Module C — Validation Workflow & Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Module of:** [`2026-05-14-data-acquisition-validation-program.md`](2026-05-14-data-acquisition-validation-program.md).

**Goal:** Turn Module A's offline pipeline (and Module B's signal aliases) into a usable workflow with documentation templates, a single cross-platform smoke runner, and a written rule for when each layer of validation must run. Encodes roadmap §10–§12 and §15 into checked-in artefacts.

**Architecture:** Pure documentation plus one tiny CLI runner. No new analyzer modules.

**Tech Stack:** Python 3.12 (cross-platform `scripts/acquisition_smoke.py`), markdown templates.

**Depends on:** Module A (`scripts/preflight.py`, `scripts/regression.py`, the test modules). Module B is optional — if absent, the smoke runner skips alias-related smoke automatically.

**Out of scope:**
- CI integration (pre-commit, PR CI) — separate spec `2026-05-14-acquisition-ci-integration.md` (planned).
- Bad-case synthetic MF4 corpus (roadmap L3) — separate spec `2026-05-14-acquisition-badcase-corpus.md` (planned).
- XCP/Vector P0 execution — existing `2026-05-13-xcp-acquisition-p0.md`.

---

## Branch Strategy

Stack on top of Module A (Module B not required):

```bash
git switch -c feat/acquisition-validation-workflow
```

---

## File Structure

- Create: `scripts/acquisition_smoke.py`
- Delete (if present from older drafts): `scripts/acquisition_smoke.sh`
- Create: `docs/analyzer/acquisition/templates/vehicle_baseline.md`
- Create: `docs/analyzer/acquisition/templates/bench_validation.md`
- Create: `docs/analyzer/acquisition/templates/vehicle_quick_check.md`
- Create: `docs/analyzer/acquisition/templates/issue_capture.md`
- Create: `docs/analyzer/acquisition/Validation_Runbook.md`

A cross-platform Python smoke runner replaces the bash variant from earlier drafts so Windows test rigs do not need a bash shell.

---

## Acceptance Gates

| Gate | Required evidence |
| --- | --- |
| C1 Templates | All four `templates/*.md` files exist and are referenced from `Validation_Runbook.md`. |
| C2 Smoke runner | `.venv/bin/python scripts/acquisition_smoke.py` or `./scripts/acquisition_smoke.py` returns exit 0 when Module A tests pass and `data/manifest.local.json` is either valid or absent. Returns exit 1 only when underlying tests or regression actually fail. |
| C3 Workflow rule | `Validation_Runbook.md` contains the change-type matrix from roadmap §15 with at minimum: UI changes, algorithm changes, MF4 import changes, DBC/A2L changes, new vehicle, release candidate. |
| C4 Bug→Regression loop | `templates/issue_capture.md` encodes roadmap §12: capture clip, add manifest entry under `sets: [issue]` with `issue_tags`, write a failing test first, then fix. |

---

### Task 1: Documentation Templates

**Files:**
- Create: `docs/analyzer/acquisition/templates/vehicle_baseline.md`
- Create: `docs/analyzer/acquisition/templates/bench_validation.md`
- Create: `docs/analyzer/acquisition/templates/vehicle_quick_check.md`
- Create: `docs/analyzer/acquisition/templates/issue_capture.md`

- [ ] **Step 1: Create vehicle baseline template**

Create `docs/analyzer/acquisition/templates/vehicle_baseline.md`:

```markdown
# Vehicle Acquisition Baseline

Vehicle ID:
Platform:
ECU software:
DBC/A2L version:
DAQ hardware:
DAQ firmware:
Harness ID:
Time sync method:
Baseline owner:
Baseline date:

## Connection Evidence

- Connector location:
- Harness route:
- Power source:
- Ground point:
- Photos stored at:

## Acquisition Setup

| Item | Value |
| --- | --- |
| Channel set | |
| Sampling rate | |
| Trigger condition | |
| File split rule | |
| Save path | |

## Reference MF4

| Item | Value |
| --- | --- |
| File path | |
| SHA256 | |
| Duration | |
| Scenario | |

## Health Reference Values

| Metric | Expected range | Source MF4 |
| --- | --- | --- |
| Idle torsion-bar torque RMS | | |
| Static steering speed range | | |
| Vehicle speed at static check | | |
| Key order amplitude range | | |

## Refresh Rule

Refresh this baseline after any hardware, ECU software, DBC/A2L, harness, power, ground, sync, trigger, or DAQ firmware change.
```

- [ ] **Step 2: Create bench validation template**

Create `docs/analyzer/acquisition/templates/bench_validation.md`:

```markdown
# Bench Validation Record

Date:
Operator:
DAQ hardware:
Signal source:
CAN/LIN/Ethernet interface:
Config version:

## Checks

| Check | Result | Evidence |
| --- | --- | --- |
| Config loads | | |
| DBC/A2L matches target | | |
| Key channels present | | |
| Timestamp monotonic | | |
| Trigger condition works | | |
| File split works | | |
| Power cycle recovery works | | |
| MF4 opens in analyzer | | |
| `scripts/preflight.py` passes | | |

## Verdict

Verdict: UNKNOWN

Allowed verdicts: PASS, PARTIAL, BLOCKED, FAIL.
```

- [ ] **Step 3: Create vehicle quick-check template**

Create `docs/analyzer/acquisition/templates/vehicle_quick_check.md`:

```markdown
# Vehicle Quick Check Record

Date:
Vehicle ID:
Operator:
Config version:
Baseline file:

## Static Check

| Step | Result | Evidence |
| --- | --- | --- |
| Wiring matches baseline photos | | |
| DAQ powers on | | |
| Device is online after ignition | | |
| Key channels have values | | |
| 1-3 minute idle/static steering recording saved | | |
| MF4 opens in analyzer | | |
| `scripts/preflight.py` passes (or manual channel/time check passes) | | |

## Dynamic Check

Only fill this section when the change requires road-condition validation.

| Scenario | Result | MF4 |
| --- | --- | --- |
| Low speed steering | | |
| Target issue reproduction | | |

## Verdict

Verdict: UNKNOWN

Allowed verdicts: PASS, PARTIAL, BLOCKED, FAIL.
```

- [ ] **Step 4: Create issue-capture template (Bug → Regression loop)**

Create `docs/analyzer/acquisition/templates/issue_capture.md`. This is the canonical procedure for turning a real-world bug into a permanent regression. Encodes roadmap §12.

```markdown
# Issue Capture & Regression Procedure

Use this template every time a real vehicle / bench / customer report reveals
an analyzer or acquisition bug. The goal is a permanently-failing test that
goes green only when the bug is actually fixed.

## 0. Trigger

Describe the symptom in one paragraph:

- What you saw:
- What you expected:
- Where it was observed (vehicle ID, bench rig, customer ticket):

## 1. Capture the clip

- Trim the source MF4 to **10–60 seconds** that demonstrate the issue.
- Save to `data/local/issue/<short-slug>.mf4` (gitignored).
- Compute SHA256:

  ```bash
  python -c "from mf4_analyzer.acquisition.manifest import sha256_file; print(sha256_file('data/local/issue/<slug>.mf4'))"
  ```

## 2. Add a manifest entry

Append to `data/manifest.local.json` under `entries`:

```json
{
  "id": "<short-slug>",
  "path": "local/issue/<short-slug>.mf4",
  "path_kind": "local",
  "sets": ["issue"],
  "vehicle": "<vehicle id or 'unknown'>",
  "platform": "<platform>",
  "scenario": "<short scenario>",
  "issue_tags": ["<tag1>", "<tag2>"],
  "expected_channels": ["<channel-or-standard-signal>", "..."],
  "sha256": "<hash from step 1>",
  "required": false
}
```

Use `path_kind: "lfs"` instead if the clip will be checked in.

## 3. Write a failing test

Add a test under `tests/issue/test_<short-slug>.py` that asserts the **correct**
behavior. Run it first; it must FAIL before any code changes.

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/issue/test_<short-slug>.py -v
```

## 4. Fix the bug

Implement the smallest change that turns the test green. Do not weaken the
test. If the assertion shape is wrong, fix the assertion in a separate commit
with a written reason.

## 5. Promote the clip

If the clip is genuinely useful as a permanent fixture:

- If it can be checked in: move to `data/golden/issue/<slug>.mf4` (Git LFS),
  flip the manifest entry's `sets` to `["issue", "golden"]` and `path_kind` to `lfs`.
- If it cannot be checked in: leave under `data/local/`, update the team-shared
  NAS index per roadmap §4 with the SHA256.

## 6. Record the lesson

If the bug revealed a durable analyzer rule (e.g., "loader must keep raw names")
write it to `docs/lessons-learned/<area>/<date>-<slug>.md` and update
`LESSONS.md`.
```

- [ ] **Step 5: Commit**

```bash
git add docs/analyzer/acquisition/templates
git commit -m "docs: add acquisition validation templates"
```

---

### Task 2: Validation Runbook

**Files:**
- Create: `docs/analyzer/acquisition/Validation_Runbook.md`

- [ ] **Step 1: Create the runbook**

Create `docs/analyzer/acquisition/Validation_Runbook.md`:

````markdown
# Acquisition Validation Runbook

Use this runbook to decide how far a change must be validated before merge or
release. Source of decisions is the program plan
`docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md`
and the roadmap `docs/analyzer/acquisition/2026-05-14-data-acquisition-validation-roadmap.md`.

## Change Type Matrix

| Change type | Minimum checks |
| --- | --- |
| UI, plot, report formatting | `.venv/bin/python scripts/acquisition_smoke.py` (covers unit + smoke dataset) |
| Signal processing algorithm | `.venv/bin/python scripts/acquisition_smoke.py` **and** `.venv/bin/python -m pytest tests/synthetic -v` (synthetic = absolute correctness — required for algorithm changes) |
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
.venv/bin/python scripts/acquisition_smoke.py

# Per-piece
.venv/bin/python -m pytest tests/synthetic -v
.venv/bin/python scripts/regression.py smoke --manifest data/manifest.local.json
.venv/bin/python scripts/regression.py golden --manifest data/manifest.local.json
.venv/bin/python scripts/preflight.py path/to/file.mf4
.venv/bin/python scripts/preflight.py path/to/file.mf4 \
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
.venv/bin/python scripts/acquisition_smoke.py
```

If `data/manifest.local.json` is missing, the runner still runs unit and
synthetic checks and skips only the private local MF4 dataset, exiting 0 with
a clear note.
````

- [ ] **Step 2: Commit**

```bash
git add docs/analyzer/acquisition/Validation_Runbook.md
git commit -m "docs: add acquisition validation runbook"
```

---

### Task 3: Cross-Platform Smoke Runner

**Files:**
- Create: `scripts/acquisition_smoke.py`
- Delete: `scripts/acquisition_smoke.sh` (only if a previous draft created it)

A Python entry point replaces the bash script so Windows benches can run it
under `py -3.12 scripts/acquisition_smoke.py` without a bash shell.

- [ ] **Step 1: Remove any stale bash runner**

```bash
[ -f scripts/acquisition_smoke.sh ] && git rm scripts/acquisition_smoke.sh || true
```

- [ ] **Step 2: Create `scripts/acquisition_smoke.py`**

Create `scripts/acquisition_smoke.py`:

```python
#!/usr/bin/env python3
"""Run the offline acquisition validation smoke suite.

Stages:
1. Unit + synthetic tests under tests/ (must exist; failure exits 1).
2. Optional local MF4 dataset smoke (skipped cleanly if manifest absent).

Cross-platform: works on macOS, Linux, Windows.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
UNIT_TESTS = [
    "tests/test_acquisition_manifest.py",
    "tests/test_acquisition_preflight.py",
    "tests/test_acquisition_regression.py",
    "tests/synthetic",
]
SIGNAL_TESTS = ["tests/test_acquisition_signals.py"]


def _python_executable() -> list[str]:
    env_python = os.environ.get("PYTHON")
    if env_python:
        return [env_python]
    venv = REPO_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    if venv.exists():
        return [str(venv)]
    return [sys.executable]


def _run(cmd: list[str], *, env: dict[str, str]) -> int:
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=REPO_ROOT, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquisition smoke runner.")
    parser.add_argument(
        "--manifest",
        default="data/manifest.local.json",
        help="Local manifest to drive the smoke regression set.",
    )
    parser.add_argument(
        "--skip-regression",
        action="store_true",
        help="Run only unit + synthetic; do not touch any MF4 dataset.",
    )
    args = parser.parse_args()

    python = _python_executable()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)

    pytest_targets = list(UNIT_TESTS)
    if (REPO_ROOT / "tests" / "test_acquisition_signals.py").exists():
        pytest_targets.extend(SIGNAL_TESTS)

    rc = _run(python + ["-m", "pytest", *pytest_targets, "-v"], env=env)
    if rc != 0:
        return 1

    if args.skip_regression:
        return 0

    manifest_path = REPO_ROOT / args.manifest
    if not manifest_path.exists():
        print(f"{manifest_path} not found; skipped local MF4 smoke dataset")
        return 0

    if shutil.which(python[0]) is None and not Path(python[0]).exists():
        print(f"python executable {python[0]} missing; skipped regression")
        return 0

    rc = _run(
        python
        + [
            "scripts/regression.py",
            "smoke",
            "--manifest",
            str(manifest_path),
        ],
        env=env,
    )
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Make it executable on POSIX**

```bash
chmod +x scripts/acquisition_smoke.py
```

- [ ] **Step 4: Run locally**

```bash
.venv/bin/python scripts/acquisition_smoke.py
```

Expected outcomes:

- All Module A tests pass; the run exits 0.
- If `data/manifest.local.json` exists and snapshots match: prints `<id>: PASS` per entry, exits 0.
- If `data/manifest.local.json` is absent: prints the skip note, exits 0.
- If unit tests fail or a real regression drift occurs: exits 1 with the failing entries listed.

- [ ] **Step 5: Commit**

```bash
git add scripts/acquisition_smoke.py
[ -e scripts/acquisition_smoke.sh ] || git add -u scripts/acquisition_smoke.sh 2>/dev/null || true
git commit -m "chore: add cross-platform acquisition smoke runner"
```

---

## Final Verification

```bash
git status --short
.venv/bin/python scripts/acquisition_smoke.py
ls docs/analyzer/acquisition/templates docs/analyzer/acquisition/Validation_Runbook.md
```

Expected:

- Templates and runbook exist; runbook references all four template paths.
- Smoke runner exits 0 with the local manifest either valid or absent.

---

## Self-Review Checklist For The Implementer

- [ ] Validation_Runbook references `templates/issue_capture.md` (the Bug → Regression loop is documented, not just verbal).
- [ ] No `.sh` shell script remains; smoke runner is pure Python.
- [ ] Smoke runner skips the regression step cleanly when `data/manifest.local.json` is absent — exit code is 0, not 1.
- [ ] No confidential vehicle baseline filled into the template files; templates ship empty.
- [ ] The change-type matrix lists synthetic tests as **required** for algorithm changes — not optional.
