# Module B — Standard Signal Alias Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Module of:** [`2026-05-14-data-acquisition-validation-program.md`](2026-05-14-data-acquisition-validation-program.md).

**Goal:** Add a sidecar layer that maps each vehicle's raw MF4 channel names onto a small set of standard signal names (`vehicle_speed`, `torsion_bar_torque`, `steering_angle_speed`, …) and surface the resolution as preflight metadata.

**Architecture — deliberate divergence from roadmap §6:** Roadmap §6 proposes pushing standard-signal mapping down into the loader so upper-layer analysis sees only standard names. This module **does not** do that. The loader keeps returning raw channel names; the alias resolution sits as a sidecar above it. Reasons:

- Existing UI search, batch presets, plot legends, and reports refer to raw channel names. A loader-level rewrite would break all of them in one commit.
- Standard names will need iteration; bound them to a config file first, then consider sinking into the loader once the names stabilize.
- Sidecar resolution returns *both* sides, so analyses that want standard names get them and analyses that want raw names are unaffected.

Loader sinking is deferred to a separate spec after Module B ships and at least two vehicle mapping files exist.

**Tech Stack:** Python 3.12, stdlib `json` / `dataclasses` / `pathlib`, pytest.

**Depends on:** Module A (manifest, preflight) — `mf4_analyzer.acquisition.preflight.analyze_mf4` must exist before Task 2 of this module starts.

**Out of scope:**
- Modifying `mf4_analyzer/io/loader.py`.
- Adding standard names to UI search, batch presets, or reports — that is a separate UI-side spec.

**Format choice:** Vehicle mapping files are JSON (`.json`), not YAML, matching the manifest decision in Module A.

---

## Branch Strategy

Stack on top of Module A. If Module A has merged to `main`:

```bash
git switch -c feat/acquisition-signal-aliases
```

If Module A is still on a feature branch, branch off it:

```bash
git switch -c feat/acquisition-signal-aliases feat/acquisition-offline-foundation
```

---

## File Structure

- Create: `configs/signals/standard_signals.json`
- Create: `configs/signals/vehicles/X04C.example.json`
- Create: `mf4_analyzer/acquisition/signals.py`
- Create: `tests/test_acquisition_signals.py`
- Modify: `mf4_analyzer/acquisition/preflight.py`
- Modify: `scripts/preflight.py`
- Modify: `tests/test_acquisition_preflight.py`

Do **not** modify `mf4_analyzer/io/loader.py`.

---

## Acceptance Gates

| Gate | Required evidence |
| --- | --- |
| B1 Alias module | `tests/test_acquisition_signals.py` PASS. Mapping rejects malformed `aliases` blocks. |
| B2 Preflight integration | `tests/test_acquisition_preflight.py` continues to PASS without `signal_config_root`. New test confirms `resolved_signals` is populated when both `signal_config_root` and `vehicle` are supplied. |
| B3 Legacy parity | `analyze_mf4(...)` called with no signal-config arguments returns the exact same `missing_channels` it did in Module A — proven by a dedicated regression test. |
| B4 Configs | `configs/signals/standard_signals.json` parses; the X04C example mapping resolves at least one entry against a synthetic raw-channel list. |

---

### Task 1: Add Standard Signal Alias Module

**Files:**
- Create: `configs/signals/standard_signals.json`
- Create: `configs/signals/vehicles/X04C.example.json`
- Create: `mf4_analyzer/acquisition/signals.py`
- Create: `tests/test_acquisition_signals.py`

- [ ] **Step 1: Write the failing signal mapping tests**

Create `tests/test_acquisition_signals.py`:

```python
import json

import pytest

from mf4_analyzer.acquisition.signals import (
    VehicleSignalMapping,
    load_vehicle_mapping,
    resolve_standard_signals,
)


def test_resolve_standard_signals_maps_available_raw_channels(tmp_path):
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "X04C.json").write_text(
        json.dumps(
            {
                "vehicle": "X04C",
                "aliases": {
                    "vehicle_speed": [
                        "Rte_VehSpdMain_vAbsAvgVehicleSpeed_xdu16",
                        "VehSpdAvg",
                    ],
                    "torsion_bar_torque": ["Rte_TAS_mTorsionBarTorque_xds16"],
                },
            }
        ),
        encoding="utf-8",
    )

    mapping = load_vehicle_mapping(root, "X04C")
    assert isinstance(mapping, VehicleSignalMapping)
    resolved = resolve_standard_signals(
        ["Time", "Rte_VehSpdMain_vAbsAvgVehicleSpeed_xdu16"],
        mapping,
    )

    assert resolved == {"vehicle_speed": "Rte_VehSpdMain_vAbsAvgVehicleSpeed_xdu16"}


def test_resolve_standard_signals_uses_first_matching_alias(tmp_path):
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "CAR.json").write_text(
        json.dumps(
            {
                "vehicle": "CAR",
                "aliases": {"vehicle_speed": ["CAR_PrimarySpeed", "CAR_BackupSpeed"]},
            }
        ),
        encoding="utf-8",
    )

    mapping = load_vehicle_mapping(root, "CAR")
    resolved = resolve_standard_signals(
        ["CAR_PrimarySpeed", "CAR_BackupSpeed"], mapping
    )

    assert resolved == {"vehicle_speed": "CAR_PrimarySpeed"}


def test_load_vehicle_mapping_rejects_non_list_alias(tmp_path):
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "CAR.json").write_text(
        json.dumps(
            {"vehicle": "CAR", "aliases": {"vehicle_speed": "not-a-list"}}
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="aliases.vehicle_speed must be a list"):
        load_vehicle_mapping(root, "CAR")


def test_load_vehicle_mapping_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_vehicle_mapping(tmp_path / "signals", "DOES_NOT_EXIST")
```

- [ ] **Step 2: Run tests to verify failure**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_signals.py -v
```

Expected: FAIL with missing `mf4_analyzer.acquisition.signals`.

- [ ] **Step 3: Implement signal alias module**

Create `mf4_analyzer/acquisition/signals.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class VehicleSignalMapping:
    vehicle: str
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=lambda: MappingProxyType({}))


def _coerce_aliases(raw: dict) -> Mapping[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for standard, raw_channels in raw.items():
        if not isinstance(raw_channels, list):
            raise ValueError(f"aliases.{standard} must be a list")
        out[str(standard)] = tuple(str(ch) for ch in raw_channels)
    return MappingProxyType(out)


def load_vehicle_mapping(root: str | Path, vehicle: str) -> VehicleSignalMapping:
    path = Path(root) / "vehicles" / f"{vehicle}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    aliases = _coerce_aliases(raw.get("aliases", {}))
    return VehicleSignalMapping(vehicle=str(raw.get("vehicle", vehicle)), aliases=aliases)


def resolve_standard_signals(
    raw_channels: list[str] | tuple[str, ...],
    mapping: VehicleSignalMapping,
) -> dict[str, str]:
    raw_set = set(raw_channels)
    resolved: dict[str, str] = {}
    for standard, candidates in mapping.aliases.items():
        for raw in candidates:
            if raw in raw_set:
                resolved[standard] = raw
                break
    return resolved
```

- [ ] **Step 4: Add example configs**

Create `configs/signals/standard_signals.json`:

```json
{
  "version": 1,
  "signals": {
    "vehicle_speed": {
      "unit": "km/h",
      "description": "Vehicle speed used for driving-state filtering."
    },
    "torsion_bar_torque": {
      "unit": "Nm",
      "description": "Torsion bar torque used for steering feel and ripple analysis."
    },
    "steering_angle_speed": {
      "unit": "deg/s",
      "description": "Steering angle speed used as order-analysis speed source when available."
    }
  }
}
```

Create `configs/signals/vehicles/X04C.example.json`:

```json
{
  "vehicle": "X04C",
  "aliases": {
    "vehicle_speed": ["Rte_VehSpdMain_vAbsAvgVehicleSpeed_xdu16"],
    "torsion_bar_torque": ["Rte_TAS_mTorsionBarTorque_xds16"],
    "steering_angle_speed": ["calculation_vSteeringAngleSpeed_xds16"]
  }
}
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_signals.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add configs/signals mf4_analyzer/acquisition/signals.py tests/test_acquisition_signals.py
git commit -m "feat: add standard signal alias sidecar"
```

---

### Task 2: Wire Aliases Into Preflight Without Breaking Legacy Callers

**Files:**
- Modify: `mf4_analyzer/acquisition/preflight.py`
- Modify: `scripts/preflight.py`
- Modify: `tests/test_acquisition_preflight.py`

- [ ] **Step 1: Add a legacy-parity test FIRST**

This test must be added **before** any preflight edits, to lock the Module A behavior in place.

Append to `tests/test_acquisition_preflight.py`:

```python
import json


def test_analyze_mf4_without_signal_config_keeps_legacy_behavior(tmp_path):
    """Module A contract: without signal_config_root/vehicle, expected_channels
    are interpreted as raw channel names and missing_channels reports raw names.
    """
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="actual")

    result = analyze_mf4(mf4, expected_channels=("missing",))

    assert not result.ok
    assert result.missing_channels == ("missing",)
    assert result.resolved_signals == {}
```

Run the suite — it FAILS because `PreflightResult` doesn't have `resolved_signals` yet.

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_preflight.py -v
```

- [ ] **Step 2: Extend `PreflightResult` with `resolved_signals`**

Modify `mf4_analyzer/acquisition/preflight.py`:

- Add `resolved_signals: dict[str, str]` field to `PreflightResult`.
- In the file-missing early-return path, set `resolved_signals={}`.
- In the success path, set `resolved_signals=resolved_signals` (computed in Step 3).

- [ ] **Step 3: Resolve aliases inside `analyze_mf4` when both inputs are supplied**

Modify the signature:

```python
def analyze_mf4(
    path: str | Path,
    *,
    expected_channels: tuple[str, ...] = (),
    expected_sha256: str | None = None,
    signal_config_root: str | Path | None = None,
    vehicle: str = "",
) -> PreflightResult:
```

Insert alias resolution before the existing missing-channel computation:

```python
resolved_signals: dict[str, str] = {}
expected_raw = expected_channels
if signal_config_root and vehicle:
    from .signals import load_vehicle_mapping, resolve_standard_signals

    mapping = load_vehicle_mapping(signal_config_root, vehicle)
    resolved_signals = resolve_standard_signals(channel_tuple, mapping)
    expected_raw = tuple(
        resolved_signals.get(ch, ch) for ch in expected_channels
    )
missing = tuple(ch for ch in expected_raw if ch not in channel_tuple)
```

Crucial: when `signal_config_root` is `None` **or** `vehicle` is empty, `expected_raw` must remain equal to `expected_channels` and `resolved_signals` must remain `{}`. The legacy-parity test from Step 1 enforces this.

- [ ] **Step 4: Add the alias-positive test**

Append to `tests/test_acquisition_preflight.py`:

```python
def test_analyze_mf4_reports_resolved_standard_signals(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="raw_speed", unit="km/h")
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "CAR.json").write_text(
        json.dumps(
            {"vehicle": "CAR", "aliases": {"vehicle_speed": ["raw_speed"]}}
        ),
        encoding="utf-8",
    )

    result = analyze_mf4(
        mf4,
        expected_channels=("vehicle_speed",),
        signal_config_root=root,
        vehicle="CAR",
    )

    assert result.ok
    assert result.resolved_signals == {"vehicle_speed": "raw_speed"}
    assert result.missing_channels == ()


def test_analyze_mf4_reports_unresolved_standard_signal_as_missing(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="something_else")
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "CAR.json").write_text(
        json.dumps(
            {"vehicle": "CAR", "aliases": {"vehicle_speed": ["raw_speed"]}}
        ),
        encoding="utf-8",
    )

    result = analyze_mf4(
        mf4,
        expected_channels=("vehicle_speed",),
        signal_config_root=root,
        vehicle="CAR",
    )

    assert not result.ok
    # Standard name passes through unchanged when no alias matches.
    assert result.missing_channels == ("vehicle_speed",)
    assert result.resolved_signals == {}
```

- [ ] **Step 5: Add CLI flags**

Modify `scripts/preflight.py` — add to the argparse block:

```python
parser.add_argument("--vehicle", default="")
parser.add_argument("--signal-config-root", default="")
```

and pass to `analyze_mf4`:

```python
signal_config_root=args.signal_config_root or None,
vehicle=args.vehicle,
```

- [ ] **Step 6: Run all preflight + signal tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
    tests/test_acquisition_preflight.py \
    tests/test_acquisition_signals.py -v
```

Expected: PASS — including the legacy-parity test that proves no behavior changed when the new flags are absent.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/acquisition/preflight.py scripts/preflight.py tests/test_acquisition_preflight.py
git commit -m "feat: connect preflight to standard signal aliases"
```

---

## Final Verification

```bash
git status --short
PYTHONPATH=. .venv/bin/python -m pytest \
    tests/test_acquisition_signals.py \
    tests/test_acquisition_preflight.py -v
```

Expected:
- Only the files in this module's File Structure are modified.
- Both test files pass.
- Module A's other tests (`tests/test_acquisition_manifest.py`, `tests/test_acquisition_regression.py`, `tests/synthetic`) still pass — alias work must not regress Module A.

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
    tests/test_acquisition_manifest.py \
    tests/test_acquisition_regression.py \
    tests/synthetic -v
```

---

## Self-Review Checklist For The Implementer

- [ ] `DataLoader.load_mf4` still returns raw channel names — no loader edits.
- [ ] `analyze_mf4` without `signal_config_root`/`vehicle` is byte-for-byte equivalent to its Module A behavior (legacy-parity test passes).
- [ ] `VehicleSignalMapping` aliases is `Mapping[str, tuple[str, ...]]` wrapped in `MappingProxyType` — immutable.
- [ ] No confidential vehicle mapping committed; example file is named `X04C.example.json` and uses the same `X04C` `vehicle` key so downstream code can copy it to `X04C.json` locally.
- [ ] Module C (validation workflow) can call `analyze_mf4` with `--signal-config-root configs/signals --vehicle X04C` without any code changes.
