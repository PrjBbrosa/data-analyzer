# Module B — Standard Signal Alias Sidecar Spec Note

**Date:** 2026-05-14
**Module:** B — Standard signal alias sidecar
**Plan (source of truth for steps):** [`../plans/2026-05-14-acquisition-signal-aliases.md`](../plans/2026-05-14-acquisition-signal-aliases.md)
**Program index:** [`../plans/2026-05-14-data-acquisition-validation-program.md`](../plans/2026-05-14-data-acquisition-validation-program.md)

This spec note describes intent, gates, and execution boundaries. Implementation details live in the plan.

## Intent

Add a **sidecar layer** that maps each vehicle's raw MF4 channel names onto a small set of standard signal names (`vehicle_speed`, `torsion_bar_torque`, `steering_angle_speed`, …) and surfaces the resolution as preflight metadata. Standard names become a parallel handle on top of raw names — they do not replace them.

This is a deliberate divergence from roadmap §6, which proposed sinking the mapping into the loader. Module B keeps the mapping above the loader so existing UI search, batch presets, plot legends, and reports — all of which refer to raw channel names today — continue to work unchanged. Loader sinking is explicitly deferred to a later spec, evaluated only after at least two vehicle mapping files exist and the names stabilize.

## Scope

Sidecar layer above `DataLoader.load_mf4`. Plan §File Structure:

- Create: `configs/signals/standard_signals.json`
- Create: `configs/signals/vehicles/X04C.example.json`
- Create: `mf4_analyzer/acquisition/signals.py`
- Create: `tests/test_acquisition_signals.py`
- Modify: `mf4_analyzer/acquisition/preflight.py` (add `signal_config_root`, `vehicle` keyword args; add `resolved_signals` field to `PreflightResult`)
- Modify: `scripts/preflight.py` (add `--vehicle`, `--signal-config-root` flags)
- Modify: `tests/test_acquisition_preflight.py` (legacy-parity test plus alias-positive tests)

**Hard constraint — must not change `DataLoader.load_mf4`.** The loader continues to return raw channel names; alias resolution happens entirely in the sidecar, and the legacy-parity gate (B3) regression-tests this.

## Local vs example mapping files

The repo ships only `configs/signals/vehicles/X04C.example.json`. To use the
real X04C mapping in a deployment, copy it locally (the local file is
gitignored — see `.gitignore` patterns for `configs/signals/vehicles/*.json`
excluding `*.example.json`):

```bash
cp configs/signals/vehicles/X04C.example.json configs/signals/vehicles/X04C.json
# Edit X04C.json with actual ECU signal names if they differ from the example
```

Then `--vehicle X04C` resolves to `X04C.json`. Runbook standard commands use
`X04C.example` for clean-repo reproducibility. `load_vehicle_mapping` should
continue to resolve exactly the requested `<vehicle>.json`; it must not fall
back from `X04C` to `X04C.example`.

## Acceptance gates

From the program index Acceptance Gate Matrix:

- **B1 Alias module** — `tests/test_acquisition_signals.py` PASS. Mapping rejects malformed `aliases` blocks (non-list value raises `ValueError`).
- **B2 Preflight integration** — `tests/test_acquisition_preflight.py` continues to PASS without `signal_config_root`. A new test confirms `resolved_signals` is populated when both `signal_config_root` and `vehicle` are supplied, and standard names in `expected_channels` get resolved against the live channel list.
- **B3 Legacy parity** — `analyze_mf4(...)` called with no signal-config arguments returns the exact same `missing_channels` it did in Module A. Proven by a dedicated regression test that lands **before** any preflight edit.
- **B4 Configs** — `configs/signals/standard_signals.json` parses and the X04C example mapping resolves at least one entry against a synthetic raw-channel list.

## Execution environment

- Python 3.12, stdlib (`json`, `dataclasses`, `pathlib`, `types.MappingProxyType`). Pytest for tests.
- Run pattern: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_signals.py tests/test_acquisition_preflight.py -v`.
- Depends on Module A — `mf4_analyzer.acquisition.preflight.analyze_mf4` and its tests must exist before Task 2 of this module starts.
- Mapping files are JSON, matching the manifest decision in Module A.
- `VehicleSignalMapping.aliases` is `Mapping[str, tuple[str, ...]]` wrapped in `MappingProxyType` — immutable by construction.
- No hardware. No CAN, Vector, or XCP. Sidecar is pure-Python text processing on top of an already-loaded DataFrame.

## Out of scope

- Modifying `mf4_analyzer/io/loader.py`. The loader contract stays raw-name-only.
- Pushing standard names into UI search, batch presets, plot legends, or reports — that is a separate UI-side spec.
- Adding loader-level rewriting of channel names — deferred until at least two vehicle mapping files exist.
- Standard-signal coverage beyond the three seed names in `standard_signals.json` (`vehicle_speed`, `torsion_bar_torque`, `steering_angle_speed`). New signals are an iterative follow-up.
- Committing confidential vehicle mappings — the only checked-in mapping is `X04C.example.json`, copied to `X04C.json` locally.

## Links

- Plan (source of truth for steps): [`../plans/2026-05-14-acquisition-signal-aliases.md`](../plans/2026-05-14-acquisition-signal-aliases.md)
- Program index & acceptance gate matrix: [`../plans/2026-05-14-data-acquisition-validation-program.md`](../plans/2026-05-14-data-acquisition-validation-program.md)
- Upstream Module A spec: [`./2026-05-14-module-a-spec.md`](./2026-05-14-module-a-spec.md)
- Downstream Module C spec: [`./2026-05-14-module-c-spec.md`](./2026-05-14-module-c-spec.md)
- Roadmap (rationale for sidecar vs loader-sink): [`../2026-05-14-data-acquisition-validation-roadmap.md`](../2026-05-14-data-acquisition-validation-roadmap.md)
