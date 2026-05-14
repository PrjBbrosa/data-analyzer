# Acquisition Docs/Code Review — 2026-05-14

## Verdict

**Offline validation track: usable but not fully trustworthy yet. Production DAQ / P1: not unblocked.**

Modules A/B/C are mostly present and the focused local suite passes, but the current checkout has three material gaps:

1. P0's Windows Vector/XCP probe modules are absent while the plan/spec/runbook still describe commands for them.
2. Regression snapshots can silently pass when a manifest requests a missing channel.
3. The documented alias preflight command uses `--vehicle X04C`, but the checked-in config is `X04C.example.json`; the command fails against a real MF4 unless a local `X04C.json` is created first.

## Scope Reviewed

Reviewed documents under `docs/analyzer/acquisition/`:

- Roadmap and feasibility: `2026-05-14-data-acquisition-validation-roadmap.md`, `CAN_Logger_Integration_Report.md`.
- P0, Module A, Module B, Module C specs and plans.
- Completion reports: `reports/2026-05-14-*.md`.
- Runbooks/templates: `P0_Runbook.md`, `Validation_Runbook.md`, `templates/*.md`.

Reviewed implementation and tests:

- `can_logger/p0/*`
- `mf4_analyzer/acquisition/*`
- `scripts/preflight.py`, `scripts/regression.py`, `scripts/acquisition_smoke.py`
- `configs/signals/*`, `data/*`
- `tests/test_acquisition_*.py`, `tests/test_p0_*.py`, `tests/synthetic/*`

## Live Verification

- Focused acquisition/P0 command: `TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_manifest.py tests/test_acquisition_preflight.py tests/test_acquisition_regression.py tests/test_acquisition_signals.py tests/synthetic tests/test_p0_mf4_probe.py tests/test_p0_a2l_probe.py -v`
  - Result: **22 passed, 1 skipped**. The skipped test is `tests/test_p0_a2l_probe.py`, gated on `P0_A2L_PATH`.
- Smoke runner command: `TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/acquisition_smoke.py`
  - Result: **21 passed**, then `data/manifest.local.json` absent was skipped cleanly.
- Preflight missing-file behavior:
  - Default missing path exits 0 with `skip: ... does not exist`.
  - `--require-exists` exits 2.
- Alias command probe:
  - `--vehicle X04C` with `configs/signals` fails with `FileNotFoundError: configs/signals/vehicles/X04C.json`.
  - `--vehicle X04C.example` resolves `vehicle_speed` successfully.
- Regression missing-channel probe:
  - `build_snapshot(path, channels=("missing",))` returned `{"channels": {}}`.
  - Comparing the same empty snapshot returned `[]`.

## Completion Matrix

| Area | Documented intent | Current code evidence | Status |
| --- | --- | --- | --- |
| P0 MF4 round trip | One generated MF4 must load through existing `DataLoader`. | `can_logger/p0/mf4_probe.py` writes via `asammdf.MDF` and test loads with `DataLoader.load_mf4` (`can_logger/p0/mf4_probe.py:7`, `tests/test_p0_mf4_probe.py:23`). | PASS |
| P0 A2L parse | Parse real A2L when `P0_A2L_PATH` is supplied. | Adapter/test exist, but current run is skip-gated (`can_logger/p0/a2l_probe.py:32`, `tests/test_p0_a2l_probe.py:8`). | PARTIAL / env-gated |
| P0 Vector/XCP | Plan/spec list `vector_probe.py` and `xcp_short_upload_probe.py` (`docs/analyzer/acquisition/specs/2026-05-14-p0-spec.md:31`, `docs/analyzer/acquisition/specs/2026-05-14-p0-spec.md:32`). | Negative evidence: `find can_logger/p0 -maxdepth 1 -type f` returned only `__init__.py`, `a2l_probe.py`, `mf4_probe.py`. | FAIL / not implemented |
| Module A manifest/preflight/regression/synthetic | A1-A4 required by plan (`docs/analyzer/acquisition/plans/2026-05-14-acquisition-offline-foundation.md:63`). | Files/tests exist and focused suite passes. Regression has missing-channel false-green risk below. | PASS with bug |
| Module B alias sidecar | Keep aliases above loader and add `resolved_signals` (`docs/analyzer/acquisition/specs/2026-05-14-module-b-spec.md:12`). | `analyze_mf4` loads mapping only when both `signal_config_root` and `vehicle` are supplied (`mf4_analyzer/acquisition/preflight.py:84`). | PASS with docs/CLI gap |
| Module C workflow/smoke | Python runner exits 0 when manifest valid or absent (`docs/analyzer/acquisition/plans/2026-05-14-acquisition-validation-workflow.md:51`). | Runner includes Module A + synthetic + auto-detected signal tests and skips absent manifest (`scripts/acquisition_smoke.py:21`, `scripts/acquisition_smoke.py:27`, `scripts/acquisition_smoke.py:76`). | PASS local, Windows unverified |
| Program gate | G★ requires A1-A4, B1-B4, C1-C4, and P0 met (`docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md:71`). | A/B/C mostly pass; P0 remains PARTIAL and Vector/XCP modules are absent. | NOT MET for production DAQ |

## Findings

### F1 — P0 references Windows Vector/XCP probes that do not exist

Severity: **High**

The P0 plan and spec both require creating `can_logger/p0/vector_probe.py` and `can_logger/p0/xcp_short_upload_probe.py` (`docs/analyzer/acquisition/plans/2026-05-13-xcp-acquisition-p0.md:34`, `docs/analyzer/acquisition/plans/2026-05-13-xcp-acquisition-p0.md:35`, `docs/analyzer/acquisition/specs/2026-05-14-p0-spec.md:31`, `docs/analyzer/acquisition/specs/2026-05-14-p0-spec.md:32`). The runbook points Windows users to those module commands (`docs/analyzer/acquisition/P0_Runbook.md:100`, `docs/analyzer/acquisition/P0_Runbook.md:126`), and the P0 report even discusses "the current XCP probe" at `can_logger/p0/xcp_short_upload_probe.py` (`docs/analyzer/acquisition/reports/2026-05-14-p0-report.md:81`, `docs/analyzer/acquisition/reports/2026-05-14-p0-report.md:82`).

Current tree only contains `can_logger/p0/__init__.py`, `a2l_probe.py`, and `mf4_probe.py`. So the documented Windows resume path is not runnable. This is more than a hardware-blocked status: the source modules that should fail or pass on Windows are missing.

Impact: P0 cannot be cleared by moving to the Windows/Vector workstation; the documented command fails before it reaches hardware.

Minimum fix:

- Either implement `vector_probe.py` and `xcp_short_upload_probe.py` with the planned platform-gated behavior, or revise the P0 spec/runbook/report to state that Tasks 4-6 are **not authored yet**, not merely hardware-blocked.
- Add at least one import/CLI smoke test that proves the modules exist and fail gracefully on macOS.

### F2 — Regression snapshots silently pass when expected channels are missing

Severity: **High**

Module A positions regression snapshots as the relative-correctness layer and says metrics should capture stable per-channel values including `samples_sha256`, `len`, `finite_count`, `first_sample`, and `last_sample` (`docs/analyzer/acquisition/specs/2026-05-14-module-a-spec.md:50`). The regression CLI feeds `entry.expected_channels` into `build_snapshot` (`scripts/regression.py:45`).

But `build_snapshot` filters requested channels down to only channels that already exist:

- `target_channels = [ch for ch in channels if ch in df.columns]` (`mf4_analyzer/acquisition/regression.py:48`)
- the returned snapshot only includes metrics for `target_channels` (`mf4_analyzer/acquisition/regression.py:60`)

Live probe: an MF4 containing only `actual`, when snapshotted with `channels=("missing",)`, produced `"channels": {}` and comparing that snapshot to itself produced no diffs.

Impact: a manifest typo or channel-mapping regression can create or preserve an empty golden snapshot and still pass. This undermines the roadmap goal that L2 historical MF4 replay catch parsing/channel regressions.

Minimum fix:

- Make `build_snapshot` or `scripts/regression.py` report requested-but-missing channels as failure.
- Add a regression test where `expected_channels=("missing",)` must fail before snapshot creation or comparison.
- Consider running preflight before snapshot creation so `expected_channels` semantics are shared.

### F3 — The documented alias preflight command fails with the checked-in config name

Severity: **Medium**

`Validation_Runbook.md` tells users to run preflight with `--signal-config-root configs/signals --vehicle X04C` (`docs/analyzer/acquisition/Validation_Runbook.md:35`, `docs/analyzer/acquisition/Validation_Runbook.md:36`). The loader resolves vehicle config paths as `<root>/vehicles/<vehicle>.json` and raises `FileNotFoundError` if absent (`mf4_analyzer/acquisition/signals.py:25`, `mf4_analyzer/acquisition/signals.py:26`, `mf4_analyzer/acquisition/signals.py:28`).

The checked-in file is `configs/signals/vehicles/X04C.example.json`, not `X04C.json`; its `vehicle` field is `X04C` (`configs/signals/vehicles/X04C.example.json:2`). Live probe confirmed:

- `--vehicle X04C` fails with `FileNotFoundError: configs/signals/vehicles/X04C.json`.
- `--vehicle X04C.example` succeeds.

Impact: the standard command in the runbook is not copy/paste runnable on a real MF4 in the clean repo.

Minimum fix:

- Add a runbook step: copy `configs/signals/vehicles/X04C.example.json` to local/untracked `X04C.json` before using `--vehicle X04C`; or
- Change the runbook demo command to `--vehicle X04C.example`; or
- Teach `load_vehicle_mapping` to fall back to `<vehicle>.example.json` with an explicit warning for examples.

Also add a test that reads the checked-in `configs/signals` files, not only temporary test fixtures.

### F4 — Roadmap says every manifest row must verify `sha256`; current schema makes it optional

Severity: **Medium**

The roadmap makes two hard claims: each manifest entry must fill `sha256`, and loading should verify it to avoid silent file replacement (`docs/analyzer/acquisition/2026-05-14-data-acquisition-validation-roadmap.md:97`, `docs/analyzer/acquisition/2026-05-14-data-acquisition-validation-roadmap.md:100`). Module A narrowed that to optional `sha256` (`docs/analyzer/acquisition/specs/2026-05-14-module-a-spec.md:14`), and the parser preserves that optionality (`mf4_analyzer/acquisition/manifest.py:24`, `mf4_analyzer/acquisition/manifest.py:71`). The checked-in example manifest has no `sha256` (`data/manifest.example.json:2`, `data/manifest.example.json:13`).

Preflight can compare a hash only when `expected_sha256` is supplied (`mf4_analyzer/acquisition/preflight.py:76`), and regression does not verify `entry.sha256` before snapshotting (`scripts/regression.py:45`).

Impact: this is acceptable for a placeholder optional sample, but it does not yet implement the roadmap's reproducibility rule. A local file can be replaced and then used to update a snapshot without a manifest-level identity check.

Minimum fix:

- Decide explicitly: is `sha256` mandatory for `required: true` and all non-placeholder entries?
- If yes, validate it in `load_manifest` or before `scripts/regression.py` snapshots.
- Keep `required: false` examples exempt only if the exemption is documented.

### F5 — Completion reports contain stale or inaccurate execution/process claims

Severity: **Low/Medium**

Examples:

- Program branch strategy says one feature branch per module and P0 does not mix into offline branches (`docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md:121`, `docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md:123`). The reports record A/B/C/P0 on `feat/acquisition-validation-program` (`docs/analyzer/acquisition/reports/2026-05-14-module-a-report.md:4`, `docs/analyzer/acquisition/reports/2026-05-14-module-b-report.md:3`, `docs/analyzer/acquisition/reports/2026-05-14-module-c-report.md:3`, `docs/analyzer/acquisition/reports/2026-05-14-p0-report.md:4`).
- Module C report says `--skip-regression` mode has 19 tests (`docs/analyzer/acquisition/reports/2026-05-14-module-c-report.md:31`), but the runner currently targets manifest, preflight, regression, synthetic, and signals (`scripts/acquisition_smoke.py:21`, `scripts/acquisition_smoke.py:27`), and the live default run collected 21.
- Module C report says it calls `subprocess.run(shell=False)` (`docs/analyzer/acquisition/reports/2026-05-14-module-c-report.md:51`), while current code uses `subprocess.call(cmd, cwd=..., env=...)` (`scripts/acquisition_smoke.py:42`). This is behaviorally still shell-free, but the report's exact API claim is wrong.

Impact: these do not directly break the analyzer, but they reduce report trust. The branch drift matters most because it weakens the intended independent review/rollback boundary.

Minimum fix:

- Add a short "post-merge correction" section to the reports or a new roll-up report that states the actual branch strategy used.
- Refresh Module C test counts from the current runner.
- Correct `subprocess.run` to `subprocess.call` in the report, or update the code if `run` semantics are desired.

## Positive Findings

- `DataLoader.load_mf4` was not modified in the acquisition modules; alias handling stays as sidecar logic, matching Module B's hard constraint.
- Module A/B/C focused tests are present and pass locally.
- `scripts/acquisition_smoke.py` uses the repo venv when present and falls back to `sys.executable` (`scripts/acquisition_smoke.py:34`, `scripts/acquisition_smoke.py:37`).
- Missing `data/manifest.local.json` is handled cleanly by the smoke runner (`scripts/acquisition_smoke.py:74`, `scripts/acquisition_smoke.py:76`).
- The current signal sidecar does resolve the checked-in example if invoked as `--vehicle X04C.example`, and `resolve_standard_signals` preserves the first matching alias (`mf4_analyzer/acquisition/signals.py:35`, `mf4_analyzer/acquisition/signals.py:44`).

## Recommended Fix Order

1. Fix regression missing-channel false green and add the failing test first.
2. Resolve the P0 probe-file truth mismatch: implement modules or downgrade the docs from "hardware-blocked" to "not authored".
3. Make the alias runbook command clean-repo runnable.
4. Decide/enforce the `sha256` policy for required manifest entries.
5. Patch stale report claims and branch-process drift.

## Go / No-Go

- **Go** for continued offline validation work after fixing F2, because the existing foundation is close and tests are already green.
- **No-Go** for production DAQ / P1 UI work from this evidence set. P0 remains PARTIAL, Tasks 4-6 are not runnable in the current tree, and the runbook itself says not to proceed to P1 until Vector/XCP gates are completed (`docs/analyzer/acquisition/P0_Runbook.md:180`, `docs/analyzer/acquisition/P0_Runbook.md:181`).
