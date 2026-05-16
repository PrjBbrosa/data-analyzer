# Module A — Offline Foundation Spec Note

**Date:** 2026-05-14
**Module:** A — Offline foundation (manifest, preflight, regression, synthetic)
**Plan (source of truth for steps):** [`../plans/2026-05-14-acquisition-offline-foundation.md`](../plans/2026-05-14-acquisition-offline-foundation.md)
**Program index:** [`../plans/2026-05-14-data-acquisition-validation-program.md`](../plans/2026-05-14-data-acquisition-validation-program.md)

This spec note describes intent, gates, and execution boundaries. It does **not** restate algorithms or step-by-step actions; those live in the plan.

## Intent

Land the four offline-only foundations the rest of the validation program stands on:

1. An MF4 dataset manifest (JSON, stdlib-parseable) that registers files with `id`, `path`, `sets`, optional `vehicle` / `platform` / `scenario` / `issue_tags` / `expected_channels` / `sha256`.
2. Single-file preflight that produces a structured health report (rows, channels, duration, fs estimate, missing expected channels, problems, sha256) usable both as a Python API and a CLI script.
3. Dataset regression snapshots that capture stable per-channel metrics (incl. `samples_sha256`) and diff later runs against a golden JSON.
4. Synthetic numerical-correctness tests proving FFT peak/amplitude on a known tone and COT order detection on a known synthetic order — independent of any GUI dependency.

Everything in Module A runs without acquisition hardware. The existing `mf4_analyzer.io.loader.DataLoader.load_mf4` contract is untouched — it still returns `(df, channels, units)` with raw channel names.

## Scope

New code lives under `mf4_analyzer/acquisition/` with thin CLI wrappers under `scripts/`. The plan §File Structure is authoritative:

- Create: `mf4_analyzer/acquisition/__init__.py`
- Create: `mf4_analyzer/acquisition/manifest.py`
- Create: `mf4_analyzer/acquisition/preflight.py`
- Create: `mf4_analyzer/acquisition/regression.py`
- Create: `scripts/preflight.py`
- Create: `scripts/regression.py`
- Modify: `.gitignore`
- Create: `data/manifest.example.json`
- Create: `data/golden/.gitkeep`
- Create: `data/snapshots/.gitkeep`
- Create: `tests/test_acquisition_manifest.py`
- Create: `tests/test_acquisition_preflight.py`
- Create: `tests/test_acquisition_regression.py`
- Create: `tests/synthetic/__init__.py`
- Create: `tests/synthetic/test_fft_known_tone.py`
- Create: `tests/synthetic/test_cot_known_order.py`

Do **not** modify `mf4_analyzer/io/loader.py` in this module.

## Acceptance gates

From the program index Acceptance Gate Matrix:

- **A1 Manifest** — `tests/test_acquisition_manifest.py` PASS. JSON schema rejects entries missing `id`, `path`, or `sets`; `data/manifest.example.json` parses.
- **A2 Preflight** — `tests/test_acquisition_preflight.py` PASS. `scripts/preflight.py` returns exit 0 on a valid MF4 and exit 1 on a file whose `expected_channels` are missing. CLI `--require-exists` flips the missing-file behavior from skip-and-exit-0 to exit 2.
- **A3 Regression** — `tests/test_acquisition_regression.py` PASS. Snapshot file is created on first run; identical re-run reports PASS; perturbed run reports drift. Metrics include `samples_sha256`, `len`, `finite_count`, `first_sample`, `last_sample` — not only mean/std.
- **A4 Synthetic** — `tests/synthetic/test_fft_known_tone.py` and `tests/synthetic/test_cot_known_order.py` PASS with no GUI dependency and finish in seconds.

Gate G★ (program-level) requires A1–A4 plus B1–B4, C1–C4, and the P0 verdict; that aggregate gate is enforced by the master plan, not by this module.

## sha256 policy

Manifest entries with `required: true` and `path_kind` set to `local` or `lfs` must include a non-empty `sha256`. Optional entries with `required: false` may omit `sha256`, so placeholder examples remain parseable. Entries with `path_kind: external` may also omit `sha256` because the remote file may not be locally hashable during manifest loading.

## Execution environment

- Python 3.12, stdlib (`json`, `hashlib`, `argparse`), `numpy`, `pandas`, `asammdf`, plus the existing `mf4_analyzer.signal.fft.FFTAnalyzer` and `mf4_analyzer.signal.order_cot.COTOrderAnalyzer` / `COTParams`. Pytest for tests.
- Run pattern: `PYTHONPATH=. .venv/bin/python -m pytest <path>`.
- Manifests and signal mappings are JSON, not YAML, because the stdlib alone parses them — deliberate divergence from roadmap §3/§6.
- Module A is hardware-free. No CAN bus, no Vector driver, no XCP, no live ECU.
- LFS install is intentionally deferred to the first commit that adds a real golden MF4; the `.gitkeep` documents the intent but does not run `git lfs install`.

## Out of scope

- Standard-signal alias sidecar — that is Module B; the loader keeps emitting raw channel names here.
- Bench / vehicle templates, runbook, and smoke-runner CLI — Module C.
- XCP / Vector hardware probes and seed/key handshakes — P0 plan.
- CI hookups (pre-commit, PR CI) — future Module D.
- Bad-case synthetic MF4 corpus (roadmap L3) — future Module E.
- Loader-level rewriting to standard signal names — deferred until at least two vehicle mapping files exist.

## Links

- Plan (source of truth for steps): [`../plans/2026-05-14-acquisition-offline-foundation.md`](../plans/2026-05-14-acquisition-offline-foundation.md)
- Program index & acceptance gate matrix: [`../plans/2026-05-14-data-acquisition-validation-program.md`](../plans/2026-05-14-data-acquisition-validation-program.md)
- Roadmap (rationale): [`../2026-05-14-data-acquisition-validation-roadmap.md`](../2026-05-14-data-acquisition-validation-roadmap.md)
- Downstream Module B spec: [`./2026-05-14-module-b-spec.md`](./2026-05-14-module-b-spec.md)
- Downstream Module C spec: [`./2026-05-14-module-c-spec.md`](./2026-05-14-module-c-spec.md)
