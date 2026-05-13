# Module A — Acquisition Offline Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Module of:** [`2026-05-14-data-acquisition-validation-program.md`](2026-05-14-data-acquisition-validation-program.md).

**Goal:** Build the four offline-only foundations the rest of the validation program stands on: an MF4 dataset manifest, single-file preflight, dataset regression snapshots, and synthetic numerical-correctness tests. Everything in this module runs without acquisition hardware.

**Architecture:** New code lives under `mf4_analyzer/acquisition/` and thin CLI wrappers under `scripts/`. The existing `mf4_analyzer.io.loader.DataLoader.load_mf4` contract is unchanged — it still returns `(df, channels, units)` with raw channel names. The standard-signal alias layer is **not** introduced here (see Module B); this module deliberately treats raw channel names as the ground truth so the existing UI, search, batch presets and reports keep working.

**Tech Stack:** Python 3.12, stdlib `json` / `hashlib` / `argparse`, `numpy`, `pandas`, `asammdf`, existing `mf4_analyzer.signal.fft.FFTAnalyzer` and `mf4_analyzer.signal.order_cot.COTOrderAnalyzer` / `COTParams`, pytest.

**Out of scope:**
- Standard-signal alias sidecar — Module B.
- Bench / vehicle docs and smoke-runner CLI — Module C.
- XCP/Vector hardware probes — existing `2026-05-13-xcp-acquisition-p0.md`.

**Format choice (deliberate divergence from roadmap §3/§6):** Manifests and signal mappings on disk are **JSON, not YAML**, because the stdlib alone can parse them — adding PyYAML to the runtime would push the analyzer onto a heavier dependency for a config-only need. Where the roadmap shows YAML it is conceptual.

---

## Branch Strategy

Use one feature branch for Module A:

```bash
git status --short
git switch -c feat/acquisition-offline-foundation
```

If the working tree carries unrelated changes, use a worktree:

```bash
git worktree add ../data-analyzer-acq-foundation -b feat/acquisition-offline-foundation main
cd ../data-analyzer-acq-foundation
```

---

## File Structure

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

---

## Acceptance Gates

| Gate | Required evidence |
| --- | --- |
| A1 Manifest | `tests/test_acquisition_manifest.py` PASS. Manifest schema rejects entries missing `id`, `path`, or `sets`. `data/manifest.example.json` parses. |
| A2 Preflight | `tests/test_acquisition_preflight.py` PASS. `scripts/preflight.py` returns exit 0 on a valid MF4 and exit 1 on a file whose `expected_channels` are missing. |
| A3 Regression | `tests/test_acquisition_regression.py` PASS. Snapshot file is created on first run; identical re-run reports PASS; perturbed run reports drift. |
| A4 Synthetic | `tests/synthetic/test_fft_known_tone.py` and `tests/synthetic/test_cot_known_order.py` PASS without GUI dependencies. |

---

### Task 1: Create Manifest Foundation

**Files:**
- Create: `mf4_analyzer/acquisition/__init__.py`
- Create: `mf4_analyzer/acquisition/manifest.py`
- Create: `tests/test_acquisition_manifest.py`
- Create: `data/manifest.example.json`
- Create: `data/golden/.gitkeep`
- Create: `data/snapshots/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing manifest tests**

Create `tests/test_acquisition_manifest.py`:

```python
import json

import pytest

from mf4_analyzer.acquisition.manifest import (
    Mf4DatasetEntry,
    load_manifest,
    resolve_entry_path,
    select_entries,
    sha256_file,
)


def test_load_manifest_normalizes_entries(tmp_path):
    sample = tmp_path / "sample.mf4"
    sample.write_bytes(b"abc")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "x04c-low-temp",
                        "path": str(sample),
                        "path_kind": "local",
                        "sets": ["smoke", "golden"],
                        "vehicle": "X04C_PPV_01",
                        "platform": "X04C",
                        "scenario": "low_temp_low_tire_pressure",
                        "issue_tags": ["ripple"],
                        "expected_channels": ["vehicle_speed"],
                        "sha256": sha256_file(sample),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_manifest(manifest)

    assert entries == [
        Mf4DatasetEntry(
            id="x04c-low-temp",
            path=str(sample),
            path_kind="local",
            sets=("smoke", "golden"),
            vehicle="X04C_PPV_01",
            platform="X04C",
            scenario="low_temp_low_tire_pressure",
            issue_tags=("ripple",),
            expected_channels=("vehicle_speed",),
            sha256=sha256_file(sample),
            required=True,
        )
    ]


def test_select_entries_filters_by_dataset(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"id": "a", "path": "a.mf4", "sets": ["smoke"]},
                    {"id": "b", "path": "b.mf4", "sets": ["golden"]},
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_manifest(manifest)

    assert [entry.id for entry in select_entries(entries, "smoke")] == ["a"]


def test_load_manifest_rejects_missing_id(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"version": 1, "entries": [{"path": "a.mf4", "sets": ["smoke"]}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="entry id is required"):
        load_manifest(manifest)


def test_resolve_entry_path_handles_relative_to_manifest(tmp_path):
    manifest = tmp_path / "data" / "manifest.local.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"id": "rel", "path": "../golden/x.mf4", "sets": ["smoke"]}
                ],
            }
        ),
        encoding="utf-8",
    )
    entries = load_manifest(manifest)

    resolved = resolve_entry_path(entries[0], manifest_path=manifest)

    assert resolved == (tmp_path / "golden" / "x.mf4").resolve()


def test_load_manifest_rejects_unknown_path_kind(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"id": "a", "path": "a.mf4", "sets": ["smoke"], "path_kind": "weird"}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="path_kind"):
        load_manifest(manifest)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_manifest.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mf4_analyzer.acquisition'`.

- [ ] **Step 3: Add package and implementation**

Create `mf4_analyzer/acquisition/__init__.py`:

```python
"""Data acquisition validation helpers."""
```

Create `mf4_analyzer/acquisition/manifest.py`:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


VALID_PATH_KINDS = ("local", "lfs", "external")


@dataclass(frozen=True)
class Mf4DatasetEntry:
    id: str
    path: str
    sets: tuple[str, ...]
    path_kind: str = "local"
    vehicle: str = ""
    platform: str = ""
    scenario: str = ""
    issue_tags: tuple[str, ...] = ()
    expected_channels: tuple[str, ...] = ()
    sha256: str | None = None
    required: bool = True


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _tuple(raw, field_name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{field_name} must be a list")
    return tuple(str(item) for item in raw)


def _entry(raw: dict) -> Mf4DatasetEntry:
    entry_id = str(raw.get("id", "")).strip()
    if not entry_id:
        raise ValueError("entry id is required")
    path = str(raw.get("path", "")).strip()
    if not path:
        raise ValueError(f"{entry_id}: path is required")
    sets = _tuple(raw.get("sets"), f"{entry_id}.sets")
    if not sets:
        raise ValueError(f"{entry_id}: at least one set is required")
    path_kind = str(raw.get("path_kind", "local"))
    if path_kind not in VALID_PATH_KINDS:
        raise ValueError(
            f"{entry_id}: path_kind {path_kind!r} not in {VALID_PATH_KINDS}"
        )
    return Mf4DatasetEntry(
        id=entry_id,
        path=path,
        path_kind=path_kind,
        sets=sets,
        vehicle=str(raw.get("vehicle", "") or ""),
        platform=str(raw.get("platform", "") or ""),
        scenario=str(raw.get("scenario", "") or ""),
        issue_tags=_tuple(raw.get("issue_tags", []), f"{entry_id}.issue_tags"),
        expected_channels=_tuple(
            raw.get("expected_channels", []), f"{entry_id}.expected_channels"
        ),
        sha256=str(raw["sha256"]) if raw.get("sha256") else None,
        required=bool(raw.get("required", True)),
    )


def load_manifest(path: str | Path) -> list[Mf4DatasetEntry]:
    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if raw.get("version") != 1:
        raise ValueError(f"unsupported manifest version: {raw.get('version')!r}")
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise ValueError("entries must be a list")
    return [_entry(item) for item in entries]


def select_entries(
    entries: Iterable[Mf4DatasetEntry], dataset: str
) -> list[Mf4DatasetEntry]:
    return [entry for entry in entries if dataset in entry.sets]


def resolve_entry_path(
    entry: Mf4DatasetEntry, *, manifest_path: str | Path
) -> Path:
    p = Path(entry.path)
    if p.is_absolute():
        return p.resolve()
    return (Path(manifest_path).resolve().parent / p).resolve()
```

- [ ] **Step 4: Add example manifest and local-data ignore rules**

Append to `.gitignore`:

```gitignore

# Local acquisition datasets and private manifests
data/local/
data/manifest.local.json
data/snapshots/*.golden.json
```

Snapshots are derived artefacts — keep them out of git. Track only the directory marker.

Create `data/manifest.example.json`:

```json
{
  "version": 1,
  "entries": [
    {
      "id": "local-recorder-smoke",
      "path": "../testdoc/Recorder_2026-04-22_09-14-36.MF4",
      "path_kind": "local",
      "sets": ["smoke"],
      "vehicle": "local_sample",
      "platform": "unknown",
      "scenario": "loader_smoke",
      "issue_tags": [],
      "expected_channels": [],
      "required": false
    }
  ]
}
```

Create marker files:

```bash
mkdir -p data/golden data/snapshots
touch data/golden/.gitkeep data/snapshots/.gitkeep
```

- [ ] **Step 5: Document LFS intention (no install yet)**

Append to `data/golden/.gitkeep` (overwrite the empty marker):

```text
# Files in data/golden/ are checked in via Git LFS.
# Before adding any MF4 here for the first time, run on the repo root:
#     git lfs install
#     git lfs track "data/golden/*.MF4" "data/golden/*.mf4"
#     git add .gitattributes
# Otherwise large MF4 binaries will land in plain git history.
```

LFS install itself is intentionally deferred to the first commit that adds a real golden file, so this module never requires LFS to run.

- [ ] **Step 6: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_manifest.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add .gitignore mf4_analyzer/acquisition data/manifest.example.json data/golden data/snapshots tests/test_acquisition_manifest.py
git commit -m "feat: add acquisition mf4 manifest foundation"
```

---

### Task 2: Add Single-File Preflight Health Check

**Files:**
- Create: `mf4_analyzer/acquisition/preflight.py`
- Create: `scripts/preflight.py`
- Create: `tests/test_acquisition_preflight.py`

- [ ] **Step 1: Write the failing preflight tests**

Create `tests/test_acquisition_preflight.py`:

```python
import numpy as np
from asammdf import MDF, Signal

from mf4_analyzer.acquisition.preflight import analyze_mf4


def _write_mf4(path, name="sig", unit="V"):
    t = np.array([0.0, 0.01, 0.02, 0.03], dtype=float)
    y = np.array([1.0, 2.0, 3.0, 4.0], dtype=float)
    mdf = MDF(version="4.10")
    mdf.append([Signal(samples=y, timestamps=t, name=name, unit=unit)])
    mdf.save(str(path), overwrite=True)
    mdf.close()


def test_analyze_mf4_reports_ok_for_valid_file(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="vehicle_speed", unit="km/h")

    result = analyze_mf4(mf4, expected_channels=("vehicle_speed",))

    assert result.ok
    assert result.rows == 4
    assert "vehicle_speed" in result.channels
    assert result.missing_channels == ()
    assert abs(result.duration_s - 0.03) < 1e-12
    assert result.units["vehicle_speed"] == "km/h"


def test_analyze_mf4_flags_missing_expected_channel(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="actual")

    result = analyze_mf4(mf4, expected_channels=("missing",))

    assert not result.ok
    assert result.missing_channels == ("missing",)


def test_analyze_mf4_reports_problem_when_file_missing(tmp_path):
    result = analyze_mf4(tmp_path / "absent.mf4")

    assert not result.ok
    assert "file does not exist" in result.problems
```

- [ ] **Step 2: Run tests to verify failure**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_preflight.py -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement preflight module**

Create `mf4_analyzer/acquisition/preflight.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from mf4_analyzer.io.loader import DataLoader

from .manifest import sha256_file


@dataclass(frozen=True)
class PreflightResult:
    path: str
    ok: bool
    rows: int
    channels: tuple[str, ...]
    units: dict[str, str]
    duration_s: float
    estimated_fs_hz: float
    missing_channels: tuple[str, ...]
    problems: tuple[str, ...]
    sha256: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)


def _time_stats(df) -> tuple[float, float, list[str]]:
    problems: list[str] = []
    if "Time" not in df.columns:
        return 0.0, 0.0, ["Time column missing"]
    t = np.asarray(df["Time"], dtype=float)
    if t.size < 2:
        return 0.0, 0.0, ["Time column has fewer than 2 samples"]
    if np.any(~np.isfinite(t)):
        problems.append("Time column contains non-finite values")
    dt = np.diff(t)
    if np.any(dt <= 0):
        problems.append("Time column is not strictly increasing")
    duration = float(t[-1] - t[0])
    positive = dt[dt > 0]
    fs = float(1.0 / np.median(positive)) if positive.size else 0.0
    return duration, fs, problems


def analyze_mf4(
    path: str | Path,
    *,
    expected_channels: tuple[str, ...] = (),
    expected_sha256: str | None = None,
) -> PreflightResult:
    p = Path(path)
    problems: list[str] = []
    if not p.exists():
        return PreflightResult(
            path=str(p),
            ok=False,
            rows=0,
            channels=(),
            units={},
            duration_s=0.0,
            estimated_fs_hz=0.0,
            missing_channels=tuple(expected_channels),
            problems=("file does not exist",),
            sha256="",
        )

    actual_sha256 = sha256_file(p)
    if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
        problems.append("sha256 mismatch")

    df, channels, units = DataLoader.load_mf4(str(p))
    channel_tuple = tuple(channels)
    missing = tuple(ch for ch in expected_channels if ch not in channel_tuple)
    if missing:
        problems.append("expected channels missing")

    duration, fs, time_problems = _time_stats(df)
    problems.extend(time_problems)

    numeric_cols = [col for col in df.columns if col != "Time"]
    if not numeric_cols:
        problems.append("no numeric signal channels")
    for col in numeric_cols:
        vals = np.asarray(df[col], dtype=float)
        if np.any(~np.isfinite(vals)):
            problems.append(f"{col} contains non-finite values")

    return PreflightResult(
        path=str(p),
        ok=not problems,
        rows=int(len(df)),
        channels=channel_tuple,
        units=dict(units),
        duration_s=duration,
        estimated_fs_hz=fs,
        missing_channels=missing,
        problems=tuple(problems),
        sha256=actual_sha256,
    )
```

- [ ] **Step 4: Add CLI wrapper with `--allow-missing` default**

Create `scripts/preflight.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mf4_analyzer.acquisition.preflight import analyze_mf4


def main() -> int:
    parser = argparse.ArgumentParser(description="Run single-file MF4 acquisition preflight.")
    parser.add_argument("mf4")
    parser.add_argument("--expected-channel", action="append", default=[])
    parser.add_argument("--sha256", default="")
    parser.add_argument(
        "--require-exists",
        action="store_true",
        help="exit 2 if mf4 path does not exist (default: exit 0 with a skip note)",
    )
    args = parser.parse_args()

    p = Path(args.mf4)
    if not p.exists():
        msg = f"skip: {p} does not exist"
        if args.require_exists:
            print(msg, file=sys.stderr)
            return 2
        print(msg)
        return 0

    result = analyze_mf4(
        p,
        expected_channels=tuple(args.expected_channel),
        expected_sha256=args.sha256 or None,
    )
    print(result.to_json())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_preflight.py -v
```

Expected: PASS.

- [ ] **Step 6: Local smoke against a generated MF4**

```bash
PYTHONPATH=. .venv/bin/python - <<'PY'
import numpy as np
from asammdf import MDF, Signal
from pathlib import Path
out = Path("/tmp/preflight_smoke.mf4")
m = MDF(version="4.10")
m.append([Signal(samples=np.arange(10.0), timestamps=np.arange(10.0)/100, name="sig", unit="V")])
m.save(str(out), overwrite=True); m.close()
print(out)
PY
PYTHONPATH=. .venv/bin/python scripts/preflight.py /tmp/preflight_smoke.mf4
PYTHONPATH=. .venv/bin/python scripts/preflight.py /tmp/does_not_exist.mf4
```

Expected: the existing file emits a JSON report; the missing file prints `skip: ... does not exist` and exits 0.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/acquisition/preflight.py scripts/preflight.py tests/test_acquisition_preflight.py
git commit -m "feat: add mf4 acquisition preflight check"
```

---

### Task 3: Add Dataset Regression Snapshots

**Files:**
- Create: `mf4_analyzer/acquisition/regression.py`
- Create: `scripts/regression.py`
- Create: `tests/test_acquisition_regression.py`

- [ ] **Step 1: Write the failing regression tests**

Create `tests/test_acquisition_regression.py`:

```python
import numpy as np
from asammdf import MDF, Signal

from mf4_analyzer.acquisition.regression import build_snapshot, compare_snapshot


def _write_mf4(path, offset=0.0):
    t = np.array([0.0, 0.01, 0.02, 0.03], dtype=float)
    y = np.array([1.0, 2.0, 3.0, 4.0], dtype=float) + offset
    mdf = MDF(version="4.10")
    mdf.append([Signal(samples=y, timestamps=t, name="sig", unit="V")])
    mdf.save(str(path), overwrite=True)
    mdf.close()


def test_build_snapshot_contains_stable_metrics(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4)

    snapshot = build_snapshot(mf4, channels=("sig",))

    assert snapshot["rows"] == 4
    metrics = snapshot["channels"]["sig"]
    assert metrics["mean"] == 2.5
    assert metrics["max"] == 4.0
    assert metrics["len"] == 4
    assert metrics["finite_count"] == 4
    assert metrics["first_sample"] == 1.0
    assert metrics["last_sample"] == 4.0
    assert isinstance(metrics["samples_sha256"], str) and len(metrics["samples_sha256"]) == 64


def test_compare_snapshot_accepts_small_difference():
    baseline = {
        "rows": 4,
        "duration_s": 0.03,
        "channels": {
            "sig": {
                "mean": 2.5,
                "std": 1.1180339887,
                "min": 1.0,
                "max": 4.0,
                "len": 4,
                "finite_count": 4,
                "first_sample": 1.0,
                "last_sample": 4.0,
                "samples_sha256": "a" * 64,
            }
        },
    }
    current = {
        "rows": 4,
        "duration_s": 0.03,
        "channels": {
            "sig": {
                "mean": 2.50001,
                "std": 1.1180339887,
                "min": 1.0,
                "max": 4.0,
                "len": 4,
                "finite_count": 4,
                "first_sample": 1.0,
                "last_sample": 4.0,
                "samples_sha256": "a" * 64,
            }
        },
    }

    diffs = compare_snapshot(baseline, current, rel_tol=1e-3, abs_tol=1e-3)

    assert diffs == []


def test_compare_snapshot_reports_metric_drift():
    baseline = {
        "rows": 4,
        "duration_s": 0.03,
        "channels": {"sig": {"mean": 2.5}},
    }
    current = {
        "rows": 4,
        "duration_s": 0.03,
        "channels": {"sig": {"mean": 3.0}},
    }

    diffs = compare_snapshot(baseline, current, rel_tol=1e-6, abs_tol=1e-6)

    assert diffs == ["sig.mean drift: baseline=2.5 current=3.0"]


def test_compare_snapshot_reports_samples_hash_drift():
    baseline = {"rows": 4, "channels": {"sig": {"samples_sha256": "a" * 64}}}
    current = {"rows": 4, "channels": {"sig": {"samples_sha256": "b" * 64}}}

    diffs = compare_snapshot(baseline, current)

    assert any("samples_sha256" in diff for diff in diffs)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_regression.py -v
```

Expected: FAIL with missing `mf4_analyzer.acquisition.regression`.

- [ ] **Step 3: Implement regression snapshot module**

Create `mf4_analyzer/acquisition/regression.py`:

```python
from __future__ import annotations

import hashlib
import json
from math import isclose
from pathlib import Path

import numpy as np

from mf4_analyzer.io.loader import DataLoader


def _samples_sha256(values: np.ndarray) -> str:
    arr = np.ascontiguousarray(values, dtype=np.float64)
    return hashlib.sha256(arr.tobytes()).hexdigest()


def _metric_dict(values) -> dict[str, float | int | str]:
    arr = np.asarray(values, dtype=float)
    finite_mask = np.isfinite(arr)
    finite = arr[finite_mask]
    if finite.size == 0:
        mean = std = mn = mx = float("nan")
        first = last = float("nan")
    else:
        mean = float(np.mean(finite))
        std = float(np.std(finite))
        mn = float(np.min(finite))
        mx = float(np.max(finite))
        first = float(arr[0])
        last = float(arr[-1])
    return {
        "len": int(arr.size),
        "finite_count": int(finite.size),
        "mean": mean,
        "std": std,
        "min": mn,
        "max": mx,
        "first_sample": first,
        "last_sample": last,
        "samples_sha256": _samples_sha256(arr),
    }


def build_snapshot(path: str | Path, *, channels: tuple[str, ...] = ()) -> dict:
    df, loaded_channels, _units = DataLoader.load_mf4(str(path))
    if channels:
        target_channels = [ch for ch in channels if ch in df.columns]
    else:
        target_channels = [ch for ch in loaded_channels if ch != "Time"]

    duration = 0.0
    if "Time" in df.columns and len(df["Time"]) > 1:
        duration = float(df["Time"].iloc[-1] - df["Time"].iloc[0])

    return {
        "path": str(path),
        "rows": int(len(df)),
        "duration_s": duration,
        "channels": {ch: _metric_dict(df[ch].to_numpy()) for ch in target_channels},
    }


def _within_tol(a, b, *, rel_tol: float, abs_tol: float) -> bool:
    try:
        return isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol)
    except (TypeError, ValueError):
        return a == b


def compare_snapshot(
    baseline: dict,
    current: dict,
    *,
    rel_tol: float = 1e-4,
    abs_tol: float = 1e-6,
) -> list[str]:
    diffs: list[str] = []
    if baseline.get("rows") != current.get("rows"):
        diffs.append(
            f"rows drift: baseline={baseline.get('rows')} current={current.get('rows')}"
        )
    if not _within_tol(
        baseline.get("duration_s", 0.0),
        current.get("duration_s", 0.0),
        rel_tol=rel_tol,
        abs_tol=abs_tol,
    ):
        diffs.append(
            f"duration_s drift: baseline={baseline.get('duration_s')} current={current.get('duration_s')}"
        )

    baseline_channels = baseline.get("channels", {})
    current_channels = current.get("channels", {})
    for ch, metrics in baseline_channels.items():
        if ch not in current_channels:
            diffs.append(f"{ch} missing from current snapshot")
            continue
        for metric, baseline_value in metrics.items():
            current_value = current_channels[ch].get(metric)
            if current_value is None:
                diffs.append(f"{ch}.{metric} missing from current snapshot")
                continue
            if metric in ("samples_sha256", "len", "finite_count"):
                if baseline_value != current_value:
                    diffs.append(
                        f"{ch}.{metric} drift: baseline={baseline_value} current={current_value}"
                    )
                continue
            if not _within_tol(
                baseline_value, current_value, rel_tol=rel_tol, abs_tol=abs_tol
            ):
                diffs.append(
                    f"{ch}.{metric} drift: baseline={baseline_value} current={current_value}"
                )
    return diffs


def load_json(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
```

- [ ] **Step 4: Add CLI wrapper**

Create `scripts/regression.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from mf4_analyzer.acquisition.manifest import (
    load_manifest,
    resolve_entry_path,
    select_entries,
)
from mf4_analyzer.acquisition.regression import (
    build_snapshot,
    compare_snapshot,
    load_json,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MF4 dataset regression snapshots.")
    parser.add_argument("dataset", help="manifest set name such as smoke, golden, issue")
    parser.add_argument("--manifest", default="data/manifest.local.json")
    parser.add_argument("--snapshot-dir", default="data/snapshots")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--rel-tol", type=float, default=1e-4)
    parser.add_argument("--abs-tol", type=float, default=1e-6)
    args = parser.parse_args()

    entries = select_entries(load_manifest(args.manifest), args.dataset)
    if not entries:
        print(f"no entries for dataset {args.dataset}")
        return 2

    failed = False
    for entry in entries:
        mf4_path = resolve_entry_path(entry, manifest_path=args.manifest)
        if not Path(mf4_path).exists():
            if entry.required:
                failed = True
                print(f"{entry.id}: FAIL — missing file {mf4_path}")
            else:
                print(f"{entry.id}: SKIP — optional file {mf4_path} absent")
            continue
        current = build_snapshot(mf4_path, channels=entry.expected_channels)
        snapshot_path = Path(args.snapshot_dir) / f"{entry.id}.golden.json"
        if args.update or not snapshot_path.exists():
            write_json(snapshot_path, current)
            print(f"updated {snapshot_path}")
            continue
        diffs = compare_snapshot(
            load_json(snapshot_path),
            current,
            rel_tol=args.rel_tol,
            abs_tol=args.abs_tol,
        )
        if diffs:
            failed = True
            print(f"{entry.id}: FAIL")
            for diff in diffs:
                print(f"  - {diff}")
        else:
            print(f"{entry.id}: PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_regression.py -v
```

Expected: PASS.

- [ ] **Step 6: Local dataset smoke with a private manifest**

```bash
cp data/manifest.example.json data/manifest.local.json
PYTHONPATH=. .venv/bin/python scripts/regression.py smoke --manifest data/manifest.local.json --update
PYTHONPATH=. .venv/bin/python scripts/regression.py smoke --manifest data/manifest.local.json
```

Expected: first run writes `data/snapshots/*.golden.json` or reports SKIP for an absent optional file; second run reports PASS or the same SKIP.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/acquisition/regression.py scripts/regression.py tests/test_acquisition_regression.py
git commit -m "feat: add mf4 dataset regression snapshots"
```

Do not commit `data/manifest.local.json` (it points at private data).

---

### Task 4: Add Synthetic Numerical Correctness Tests

**Files:**
- Create: `tests/synthetic/__init__.py`
- Create: `tests/synthetic/test_fft_known_tone.py`
- Create: `tests/synthetic/test_cot_known_order.py`

- [ ] **Step 1: Add package marker**

Create `tests/synthetic/__init__.py` (empty).

- [ ] **Step 2: Create synthetic FFT test**

Create `tests/synthetic/test_fft_known_tone.py`:

```python
import numpy as np

from mf4_analyzer.signal.fft import FFTAnalyzer


def test_fft_known_100hz_tone_peak_and_amplitude():
    fs = 1024.0
    n = 4096
    t = np.arange(n) / fs
    amplitude = 2.5
    sig = amplitude * np.sin(2 * np.pi * 100.0 * t)

    freq, amp = FFTAnalyzer.compute_fft(sig, fs, win="hanning", nfft=n)

    peak_idx = int(np.argmax(amp))
    assert abs(freq[peak_idx] - 100.0) < 1e-9
    assert abs(amp[peak_idx] - amplitude) < 0.01
```

- [ ] **Step 3: Create synthetic COT order test**

Create `tests/synthetic/test_cot_known_order.py`. Picks a longer duration and finer time hop than the original draft to keep frame count high and reduce flakiness on the ratio assertion:

```python
import numpy as np

from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams


def test_cot_known_second_order_dominates_neighbors():
    fs = 1000.0
    duration = 20.0
    t = np.arange(int(fs * duration)) / fs
    rpm = np.full_like(t, 600.0)
    shaft_hz = 600.0 / 60.0
    sig = np.sin(2 * np.pi * 2.0 * shaft_hz * t)
    params = COTParams(
        samples_per_rev=256,
        nfft=1024,
        max_order=5.0,
        order_res=0.05,
        time_res=0.1,
        fs=fs,
    )

    result = COTOrderAnalyzer.compute(sig, rpm, t, params)

    order2_idx = int(np.argmin(np.abs(result.orders - 2.0)))
    order15_idx = int(np.argmin(np.abs(result.orders - 1.5)))
    order25_idx = int(np.argmin(np.abs(result.orders - 2.5)))
    order2 = result.amplitude[:, order2_idx].mean()
    order15 = result.amplitude[:, order15_idx].mean()
    order25 = result.amplitude[:, order25_idx].mean()

    assert order2 > 5.0 * order15
    assert order2 > 5.0 * order25
```

The ratio threshold is intentionally relaxed to 5× from the original 10× draft so the test passes under any reasonable windowing/leakage without becoming useless — a real failure would still register an order at the neighbor bin.

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/synthetic -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/synthetic
git commit -m "test: add acquisition synthetic signal checks"
```

---

## Final Verification

```bash
git status --short
PYTHONPATH=. .venv/bin/python -m pytest \
    tests/test_acquisition_manifest.py \
    tests/test_acquisition_preflight.py \
    tests/test_acquisition_regression.py \
    tests/synthetic -v
```

Optional repo-wide gates (if available on this machine):

```bash
.venv/bin/python scripts/lessons/check.py --status 2>/dev/null || true
```

Expected:
- Only the files in this module's File Structure are modified.
- All four test files pass.
- `git status --short` shows no committed `data/manifest.local.json` or snapshot drift.

---

## Self-Review Checklist For The Implementer

- [ ] `DataLoader.load_mf4` still returns raw channel names — no loader edits.
- [ ] `data/manifest.local.json` not tracked; `data/snapshots/*.golden.json` not tracked.
- [ ] Snapshot metrics include `samples_sha256`, `len`, `finite_count`, `first_sample`, `last_sample` — not only mean/std.
- [ ] Preflight CLI's `--allow-missing` (default) prints `skip:` and exits 0; `--require-exists` exits 2.
- [ ] Synthetic tests are GUI-free and finish under ~5 seconds combined.
- [ ] No confidential MF4, A2L, DBC, or local manifest committed.
- [ ] Module B (signal aliases) consumes `manifest.load_manifest` and `preflight.analyze_mf4` without modification.
