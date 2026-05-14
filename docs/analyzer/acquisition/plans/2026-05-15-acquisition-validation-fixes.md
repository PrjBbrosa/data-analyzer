# Acquisition Validation Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the correctness, truth-up, and polish gaps surfaced by two reviews of the 2026-05-14 Acquisition Validation Program (Modules A/B/C + P0). The program currently has 22 passing tests but several silent-failure paths and document-vs-code drift; this plan fixes them without re-litigating the program's architecture.

**Architecture invariant (unchanged from program plan):** `DataLoader.load_mf4` stays as-is — no loader edits. Standard signal mapping stays as a sidecar above the loader. Manifests and signal configs stay JSON.

**Tech Stack:** Python 3.12, stdlib `json` / `hashlib` / `argparse`, `numpy`, `pandas`, `asammdf`, existing `mf4_analyzer.io.loader.DataLoader`, existing signal modules, pytest, optional `pya2ldb` (P0 A2L), optional `python-can[vector]` + `pyxcp` on Windows (P0 hardware path).

---

## Source Inputs

This plan consolidates findings from two reviews of the 2026-05-14 program:

- External review: `docs/analyzer/acquisition/reviews/2026-05-14-acquisition-docs-code-review.md` — findings F1–F5.
- Internal review (in-session): `🔴 B1–B6`, `🟡 S1–S12`, `🟢 P1–P12`.

The 2026-05-14 program plans and reports stay valid; this plan supersedes only where it conflicts:

- `docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md`
- `docs/analyzer/acquisition/plans/2026-05-14-acquisition-offline-foundation.md`
- `docs/analyzer/acquisition/plans/2026-05-14-acquisition-signal-aliases.md`
- `docs/analyzer/acquisition/plans/2026-05-14-acquisition-validation-workflow.md`
- `docs/analyzer/acquisition/plans/2026-05-13-xcp-acquisition-p0.md`

---

## Branch Strategy

Three independent branches by stage so each can land/revert separately:

```bash
# Stage 1 — correctness gates (must merge first)
git switch -c fix/acquisition-correctness-gates feat/acquisition-validation-program

# Stage 2 — truth-up gaps (rebases on Stage 1 once merged)
git switch -c fix/acquisition-p0-truth-up <Stage 1 base>

# Stage 3 — docs and polish (rebases on Stage 2 once merged)
git switch -c fix/acquisition-docs-and-polish <Stage 2 base>
```

If the `feat/acquisition-validation-program` branch has not merged to `main` yet, use it as the base.

Avoid bundling all three stages into one branch — Stage 1 has correctness urgency, Stage 2 needs decision review, Stage 3 is low-risk polish.

---

## Stage Map

| Stage | Concern | Tasks | Risk |
| --- | --- | --- | --- |
| 1 | Correctness — close silent-failure paths | 1.1–1.4 | Blocks any later validation work; merge first |
| 2 | Truth-up — make plan/spec/runbook match code reality | 2.1–2.4 | Requires policy decisions (sha256, P0 stub vs downgrade) |
| 3 | Polish — docs corrections, dataclass consistency, tests, friendlier CLI | 3.1–3.7 | Low risk; merge last |

---

## Acceptance Gates (Program-Level Rollup)

| Gate | Required evidence |
| --- | --- |
| Fix-1 | `scripts/regression.py` exits 1 (not 0) when a manifest entry's `expected_channels` includes a name absent from the MF4. Test: `test_compare_snapshot_reports_missing_requested_channel` GREEN. |
| Fix-2 | `analyze_mf4` on a corrupt/empty MF4 returns `ok=False` with `problems` containing `loader failed: …`, never raises. Test: `test_analyze_mf4_reports_loader_failure_as_problem` GREEN. |
| Fix-3 | `compare_snapshot` treats `(NaN, NaN)` as equal; reports new channels in current. Tests: `test_compare_snapshot_treats_nan_pair_as_equal` + `test_compare_snapshot_reports_new_channel_in_current` GREEN. |
| Fix-4 | `_samples_sha256` byte-order portable. Test: `test_samples_sha256_is_byte_order_stable` asserts the fixed little-endian hex literal `6bab56d2f81d4b5a2dbf102bf6a6ff7d5211a475fc5f97813f977e8ba714b07d`. |
| Fix-5 | `can_logger/p0/vector_probe.py` + `xcp_short_upload_probe.py` exist and import cleanly on macOS; `vector_probe.py` emits a clear "Vector interface is only supported on Windows" runtime error on non-Windows; `xcp_short_upload_probe.py` keeps pure decode helpers hardware-free; `P0_Runbook.md` Vector/XCP sections reference real file paths. |
| Fix-6 | `python scripts/preflight.py <fixture.mf4> --signal-config-root configs/signals --vehicle X04C.example` succeeds in a clean checkout. Test reads the **checked-in** `configs/signals/vehicles/X04C.example.json`, not a tmp fixture. |
| Fix-7 | `load_manifest` raises `ValueError` for a `required: true` + local entry missing `sha256`. `data/manifest.example.json` continues to parse (it's `required: false`). |
| Fix-8 | `tests/test_acquisition_smoke.py` covers three paths: `--skip-regression` happy path, manifest-absent exit 0 with skip note, pytest-failure exit 1. |
| Fix-9 | Combined test suite (Module A + B + C + P0 hardware-free + Stage 1/2/3 additions) GREEN; count ≥ original 22 + at least 8 new tests = 30. |

---

## Stage 1 — Correctness Gates

These four fixes close silent-failure paths. Merge Stage 1 before any further validation work on this branch.

---

### Task 1.1: Regression must fail loudly on missing requested channels

**Origin:** External F2 + internal S6.

**Files:**
- Modify: `mf4_analyzer/acquisition/regression.py`
- Modify: `scripts/regression.py`
- Modify: `tests/test_acquisition_regression.py`

- [ ] **Step 1: Write failing tests FIRST**

Append to `tests/test_acquisition_regression.py`:

```python
import pytest


def test_build_snapshot_raises_when_requested_channel_absent(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4)  # writes only channel "sig"

    with pytest.raises(ValueError, match="requested channel not in MF4: missing"):
        build_snapshot(mf4, channels=("missing",))


def test_build_snapshot_silently_excludes_time_when_passed(tmp_path):
    """Even if caller passes 'Time', it must not appear as a tracked channel."""
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4)

    snapshot = build_snapshot(mf4, channels=("sig", "Time"))

    assert "Time" not in snapshot["channels"]
    assert "sig" in snapshot["channels"]


def test_compare_snapshot_reports_new_channel_in_current():
    baseline = {"rows": 4, "duration_s": 0.0, "channels": {"sig": {"mean": 1.0}}}
    current = {
        "rows": 4,
        "duration_s": 0.0,
        "channels": {"sig": {"mean": 1.0}, "extra": {"mean": 9.0}},
    }

    diffs = compare_snapshot(baseline, current, rel_tol=1e-6, abs_tol=1e-6)

    assert any("extra" in d and "new in current" in d for d in diffs)
```

- [ ] **Step 2: Run tests to verify failure**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_regression.py -v
```

Expected: three new tests FAIL.

- [ ] **Step 3: Implement loud failure in `build_snapshot`**

Modify `mf4_analyzer/acquisition/regression.py` — `build_snapshot`:

```python
def build_snapshot(path: str | Path, *, channels: tuple[str, ...] = ()) -> dict:
    df, loaded_channels, _units = DataLoader.load_mf4(str(path))
    if channels:
        missing = [ch for ch in channels if ch != "Time" and ch not in df.columns]
        if missing:
            raise ValueError(
                f"requested channel not in MF4: {missing[0]}"
                + (f" (+{len(missing)-1} more)" if len(missing) > 1 else "")
            )
        target_channels = [ch for ch in channels if ch != "Time" and ch in df.columns]
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
```

- [ ] **Step 4: Add "new channel" detection in `compare_snapshot`**

After the existing baseline-iteration loop, append:

```python
for ch in current_channels:
    if ch not in baseline_channels:
        diffs.append(f"{ch} new in current")
```

- [ ] **Step 5: Propagate to `scripts/regression.py`**

In the per-entry loop, catch `ValueError` from `build_snapshot` and convert to FAIL row:

```python
try:
    current = build_snapshot(mf4_path, channels=entry.expected_channels)
except ValueError as exc:
    failed = True
    print(f"{entry.id}: FAIL — {exc}")
    continue
```

- [ ] **Step 6: Run all regression tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_regression.py -v
```

Expected: 7 tests GREEN (4 existing + 3 new).

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/acquisition/regression.py scripts/regression.py tests/test_acquisition_regression.py
git commit -m "fix(acquisition): fail loud when manifest requests missing channels"
```

---

### Task 1.2: Preflight wraps loader exceptions

**Origin:** Internal B3.

**Files:**
- Modify: `mf4_analyzer/acquisition/preflight.py`
- Modify: `tests/test_acquisition_preflight.py`

- [ ] **Step 1: Write failing test FIRST**

Append to `tests/test_acquisition_preflight.py`:

```python
def test_analyze_mf4_reports_loader_failure_as_problem(tmp_path):
    """A corrupt/empty MF4 must produce ok=False with a loader-failure problem,
    not raise an exception out of analyze_mf4.
    """
    bogus = tmp_path / "bogus.mf4"
    bogus.write_bytes(b"")  # zero-byte file with .mf4 suffix

    result = analyze_mf4(bogus)

    assert not result.ok
    assert any("loader failed" in p for p in result.problems)
```

- [ ] **Step 2: Run test to verify failure**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_preflight.py::test_analyze_mf4_reports_loader_failure_as_problem -v
```

Expected: FAIL with raw exception from `DataLoader.load_mf4`.

- [ ] **Step 3: Wrap loader call**

Modify `mf4_analyzer/acquisition/preflight.py` — inside `analyze_mf4`, replace the bare loader call with:

```python
try:
    df, channels, units = DataLoader.load_mf4(str(p))
except Exception as exc:
    return PreflightResult(
        path=str(p),
        ok=False,
        rows=0,
        channels=(),
        units={},
        duration_s=0.0,
        estimated_fs_hz=0.0,
        missing_channels=tuple(expected_channels),
        problems=(f"loader failed: {exc!r}",),
        sha256=actual_sha256 if expected_sha256 else "",
        resolved_signals={},
    )
```

Note: `actual_sha256` is computed before the loader call. After Task 2.4 lands, it will be guarded by `if expected_sha256`.

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_preflight.py -v
```

Expected: all preflight tests GREEN.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition/preflight.py tests/test_acquisition_preflight.py
git commit -m "fix(preflight): trap loader exceptions instead of propagating"
```

---

### Task 1.3: NaN parity in regression compare

**Origin:** Internal S5.

**Files:**
- Modify: `mf4_analyzer/acquisition/regression.py`
- Modify: `tests/test_acquisition_regression.py`

- [ ] **Step 1: Write failing test FIRST**

Append to `tests/test_acquisition_regression.py`:

```python
def test_compare_snapshot_treats_nan_pair_as_equal():
    baseline = {
        "rows": 4,
        "duration_s": 0.0,
        "channels": {"sig": {"mean": float("nan"), "std": float("nan")}},
    }
    current = {
        "rows": 4,
        "duration_s": 0.0,
        "channels": {"sig": {"mean": float("nan"), "std": float("nan")}},
    }

    diffs = compare_snapshot(baseline, current)

    assert diffs == []
```

- [ ] **Step 2: Run test to verify failure**

Expected: FAIL because `math.isclose(nan, nan) == False`.

- [ ] **Step 3: Update `_within_tol`**

```python
import math


def _within_tol(a, b, *, rel_tol: float, abs_tol: float) -> bool:
    try:
        af, bf = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    if math.isnan(af) and math.isnan(bf):
        return True
    return math.isclose(af, bf, rel_tol=rel_tol, abs_tol=abs_tol)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_regression.py -v
```

Expected: all GREEN.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition/regression.py tests/test_acquisition_regression.py
git commit -m "fix(regression): treat NaN/NaN as equal in snapshot compare"
```

---

### Task 1.4: Portable samples sha256

**Origin:** Internal B4.

**Files:**
- Modify: `mf4_analyzer/acquisition/regression.py`
- Modify: `tests/test_acquisition_regression.py`

- [ ] **Step 1: Write failing test FIRST**

Append to `tests/test_acquisition_regression.py`:

```python
def test_samples_sha256_is_byte_order_stable():
    """Hash must be stable across CPU architectures — assert a fixed hex literal
    for a known float64 sequence under little-endian byte order.
    """
    import numpy as np

    from mf4_analyzer.acquisition.regression import _samples_sha256

    arr = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    expected = "6bab56d2f81d4b5a2dbf102bf6a6ff7d5211a475fc5f97813f977e8ba714b07d"

    assert _samples_sha256(arr) == expected
```

This test is self-validating: if the implementation uses native byte order, the test still passes on x86 (which is little-endian) but fails on big-endian. The point of pinning is to **specify** little-endian rather than rely on host.

- [ ] **Step 2: Run test**

Expected: PASS on x86 even without the fix (native is little-endian). To prove the fix, also add an architectural assertion test:

```python
def test_samples_sha256_uses_explicit_little_endian():
    """Inspect implementation — refuse the `tobytes()` default path."""
    import inspect

    from mf4_analyzer.acquisition import regression

    src = inspect.getsource(regression._samples_sha256)
    assert "<f8" in src or "little" in src.lower(), (
        "samples sha256 must specify little-endian explicitly, not rely on host"
    )
```

- [ ] **Step 3: Update `_samples_sha256`**

```python
def _samples_sha256(values: np.ndarray) -> str:
    arr = np.ascontiguousarray(values, dtype="<f8")
    return hashlib.sha256(arr.tobytes()).hexdigest()
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_regression.py -v
```

Expected: all GREEN, including the source-inspection test.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition/regression.py tests/test_acquisition_regression.py
git commit -m "fix(regression): pin samples sha256 to little-endian for portability"
```

**Note on snapshot churn:** Existing `data/snapshots/*.golden.json` produced by the old code happen to use little-endian on x86 hosts; no churn on x86. On big-endian hosts (rare) snapshots regenerated under the old code would be invalid; document this as a one-time invalidation under "Migration notes" in the next Module C runbook update.

---

## Stage 2 — Truth-up Gaps

Decisions required. Each task starts with a Decision section.

---

### Task 2.1: P0 Vector/XCP probe stubs (resolve doc vs code drift)

**Origin:** External F1.

**Decision:** Author the stubs with platform-gated runtime errors so the Windows resume path is real code. Alternative — downgrade the docs to "not authored" — is rejected because the modules are small and Windows execution should not require a new authoring loop.

**Files:**
- Create: `can_logger/p0/vector_probe.py`
- Create: `can_logger/p0/xcp_short_upload_probe.py`
- Create: `tests/test_p0_vector_probe.py`
- Create: `tests/test_p0_xcp_probe.py`
- Modify: `docs/analyzer/acquisition/P0_Runbook.md` (Vector + XCP sections, verdict reasoning)
- Modify: `docs/analyzer/acquisition/specs/2026-05-14-p0-spec.md` (status of Tasks 4–6)

- [ ] **Step 1: Write failing tests FIRST**

Create `tests/test_p0_vector_probe.py`:

```python
import sys

import pytest


def test_vector_probe_imports_on_any_platform():
    """Import must succeed on macOS — no top-level python-can dependency."""
    from can_logger.p0 import vector_probe  # noqa: F401


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behavior only")
def test_vector_probe_raises_clear_error_off_windows():
    from can_logger.p0.vector_probe import list_vector_channels

    with pytest.raises(RuntimeError, match="(?i)vector|windows"):
        list_vector_channels()
```

Create `tests/test_p0_xcp_probe.py`:

```python
import sys

import pytest


def test_xcp_probe_imports_on_any_platform():
    from can_logger.p0 import xcp_short_upload_probe  # noqa: F401


def test_decode_raw_independent_of_hardware():
    """decode_raw is pure: must work on macOS without can/pyxcp installed."""
    from can_logger.p0.xcp_short_upload_probe import decode_raw

    assert decode_raw(b"\x00\x00\x80\x3f", "f32", "little") == pytest.approx(1.0)
    assert decode_raw(b"\xff\xff\xff\xff", "u32", "little") == 0xFFFFFFFF
```

- [ ] **Step 2: Run tests to verify failure**

Expected: ImportError or AttributeError at collection — modules don't exist.

- [ ] **Step 3: Implement `vector_probe.py` with lazy import + platform gate**

Create `can_logger/p0/vector_probe.py`:

```python
"""Vector hardware access probe. python-can is imported lazily so this module
can be imported on macOS/Linux for static checks without the Vector driver."""
from __future__ import annotations

import argparse
import sys


def _ensure_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError(
            "Vector interface is only supported on Windows; current platform: "
            f"{sys.platform}"
        )


def list_vector_channels() -> list:
    _ensure_windows()
    from can.interfaces import vector  # type: ignore[import-not-found]

    return list(vector.get_channel_configs())


def open_vector_bus(*, channel: int, bitrate: int, app_name: str):
    _ensure_windows()
    import can  # type: ignore[import-not-found]

    return can.Bus(interface="vector", channel=channel, bitrate=bitrate, app_name=app_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe python-can Vector access.")
    parser.add_argument("--channel", type=int, default=0)
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--app-name", default="CANalyzer")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()

    if sys.platform != "win32":
        print(
            "Vector interface is expected to run on Windows; current platform:",
            sys.platform,
        )
        return 2

    channels = list_vector_channels()
    print(f"vector_channels: {len(channels)}")
    for ch in channels:
        print(ch)

    if args.open:
        bus = open_vector_bus(
            channel=args.channel, bitrate=args.bitrate, app_name=args.app_name
        )
        try:
            print("vector_open: ok")
        finally:
            bus.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Implement `xcp_short_upload_probe.py` with lazy imports**

Create `can_logger/p0/xcp_short_upload_probe.py`:

```python
from __future__ import annotations

import argparse
import struct
import time
from typing import Any


CMD_CONNECT = 0xFF
CMD_DISCONNECT = 0xFE
CMD_SHORT_UPLOAD = 0xF4
RESP_OK = 0xFF


def parse_int(text: str) -> int:
    return int(text, 0)


class RawXcpCanProbe:
    def __init__(self, bus: Any, *, cmd_id: int, resp_id: int, timeout: float = 0.5):
        self.bus = bus
        self.cmd_id = cmd_id
        self.resp_id = resp_id
        self.timeout = timeout

    def send(self, payload: bytes) -> None:
        import can  # type: ignore[import-not-found]

        msg = can.Message(
            arbitration_id=self.cmd_id,
            data=payload.ljust(8, b"\x00"),
            is_extended_id=False,
        )
        self.bus.send(msg)

    def recv(self) -> bytes:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            msg = self.bus.recv(timeout=0.05)
            if msg is None:
                continue
            if msg.arbitration_id == self.resp_id:
                data = bytes(msg.data)
                if not data:
                    raise RuntimeError("empty XCP response")
                return data
        raise TimeoutError(f"no XCP response on CAN ID 0x{self.resp_id:X}")

    def command(self, payload: bytes) -> bytes:
        self.send(payload)
        response = self.recv()
        if response[0] != RESP_OK:
            code = response[1] if len(response) > 1 else 0
            raise RuntimeError(
                f"negative XCP response: pid=0x{response[0]:02X}, code=0x{code:02X}"
            )
        return response

    def connect(self) -> bytes:
        return self.command(bytes([CMD_CONNECT, 0x00]))

    def disconnect(self) -> None:
        self.send(bytes([CMD_DISCONNECT]))

    def short_upload(
        self, *, address: int, size: int, address_extension: int = 0
    ) -> bytes:
        payload = struct.pack(
            "<BBBBI", CMD_SHORT_UPLOAD, size, 0x00, address_extension, address
        )
        response = self.command(payload)
        return response[1 : 1 + size]


def decode_raw(raw: bytes, dtype: str, endian: str):
    endian_prefix = ">" if endian == "big" else "<"
    formats = {
        "u8": "B",
        "s8": "b",
        "u16": "H",
        "s16": "h",
        "u32": "I",
        "s32": "i",
        "f32": "f",
        "f64": "d",
    }
    fmt = formats[dtype]
    needed = struct.calcsize(endian_prefix + fmt)
    if len(raw) < needed:
        raise ValueError(f"not enough data for {dtype}: {raw.hex()}")
    return struct.unpack(endian_prefix + fmt, raw[:needed])[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="P0 raw XCP CONNECT + SHORT_UPLOAD probe.")
    parser.add_argument("--interface", default="vector")
    parser.add_argument("--channel", default="0")
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--app-name", default="CANalyzer")
    parser.add_argument("--cmd-id", type=parse_int, required=True)
    parser.add_argument("--resp-id", type=parse_int, required=True)
    parser.add_argument("--address", type=parse_int, required=True)
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--address-extension", type=parse_int, default=0)
    parser.add_argument(
        "--dtype",
        choices=["u8", "s8", "u16", "s16", "u32", "s32", "f32", "f64"],
        default="f32",
    )
    parser.add_argument("--endian", choices=["little", "big"], default="little")
    args = parser.parse_args()

    import can  # type: ignore[import-not-found]

    bus_kwargs = {
        "interface": args.interface,
        "channel": args.channel,
        "bitrate": args.bitrate,
    }
    if args.interface == "vector":
        bus_kwargs["app_name"] = args.app_name

    bus = can.Bus(**bus_kwargs)
    probe = RawXcpCanProbe(bus, cmd_id=args.cmd_id, resp_id=args.resp_id)
    try:
        connect_response = probe.connect()
        print("connect_response:", connect_response.hex())
        raw = probe.short_upload(
            address=args.address,
            size=args.size,
            address_extension=args.address_extension,
        )
        print("raw:", raw.hex())
        print("decoded:", decode_raw(raw, args.dtype, args.endian))
    finally:
        try:
            probe.disconnect()
        finally:
            bus.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_vector_probe.py tests/test_p0_xcp_probe.py -v
```

Expected: 4 tests GREEN on macOS.

- [ ] **Step 6: Update P0 Runbook**

`docs/analyzer/acquisition/P0_Runbook.md`:

- `## Vector Access` and `## XCP CONNECT And SHORT_UPLOAD` sections: change from "BLOCKED — code not authored" to:
  ```
  BLOCKED on macOS — hardware not available. Code is on disk at
  can_logger/p0/vector_probe.py (and xcp_short_upload_probe.py). Resume command
  on Windows:
      .\.venv\Scripts\python.exe -m can_logger.p0.vector_probe --open
      .\.venv\Scripts\python.exe -m can_logger.p0.xcp_short_upload_probe ...
  ```
- `## Final Verdict`: keep PARTIAL. Add a line: "Resume path verified to import on macOS; full PASS requires Vector hardware on Windows."

- [ ] **Step 7: Update P0 spec**

`docs/analyzer/acquisition/specs/2026-05-14-p0-spec.md`: rewrite the "Tasks 4-6 are HARDWARE-BLOCKED" section to "Tasks 4-6 are HARDWARE-BLOCKED on the current macOS host; code modules exist and import cleanly."

- [ ] **Step 8: Commit**

```bash
git add can_logger/p0/vector_probe.py can_logger/p0/xcp_short_upload_probe.py \
    tests/test_p0_vector_probe.py tests/test_p0_xcp_probe.py \
    docs/analyzer/acquisition/P0_Runbook.md \
    docs/analyzer/acquisition/specs/2026-05-14-p0-spec.md
git commit -m "feat(p0): add vector and xcp probe stubs with platform gating"
```

---

### Task 2.2: Alias runbook command runnable in clean repo

**Origin:** External F3.

**Decision:** Change the runbook demo command to `--vehicle X04C.example`, and document the example→local copy step. Do NOT teach `load_vehicle_mapping` to fall back to `*.example.json` automatically — that would mask "I forgot to install the local mapping" in production.

**Files:**
- Modify: `.gitignore`
- Modify: `docs/analyzer/acquisition/Validation_Runbook.md`
- Modify: `docs/analyzer/acquisition/specs/2026-05-14-module-b-spec.md`
- Modify: `tests/test_acquisition_signals.py`

- [ ] **Step 1: Write checked-in config guard FIRST**

Append to `tests/test_acquisition_signals.py`:

```python
def test_load_vehicle_mapping_resolves_checked_in_example_config():
    """The repo ships an example config; the runbook demo command must
    resolve against that exact file in a clean checkout.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    mapping = load_vehicle_mapping(repo_root / "configs" / "signals", "X04C.example")

    assert mapping.vehicle == "X04C"
    assert "vehicle_speed" in mapping.aliases
```

- [ ] **Step 2: Run guard test**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_signals.py::test_load_vehicle_mapping_resolves_checked_in_example_config -v
```

Expected: PASS (the file `configs/signals/vehicles/X04C.example.json` exists). This is a regression guard — if someone renames or deletes the example, the test catches it.

- [ ] **Step 3: Fix runbook**

`docs/analyzer/acquisition/Validation_Runbook.md` Standard Commands section, change:

```diff
- python scripts/preflight.py path/to/file.mf4 \
-     --signal-config-root configs/signals --vehicle X04C \
+ python scripts/preflight.py path/to/file.mf4 \
+     --signal-config-root configs/signals --vehicle X04C.example \
```

Add a new subsection before Standard Commands:

```markdown
## Local vs example signal mappings

The repo ships only `configs/signals/vehicles/X04C.example.json`. To use the
real X04C mapping in a deployment, copy it locally (the local file is
gitignored — see `.gitignore` patterns for `configs/signals/vehicles/*.json`
excluding `*.example.json`):

```bash
cp configs/signals/vehicles/X04C.example.json configs/signals/vehicles/X04C.json
# Edit X04C.json with actual ECU signal names if they differ from the example
```

Then `--vehicle X04C` resolves to `X04C.json`. The standard commands below
use `X04C.example` for clean-repo reproducibility.
```

- [ ] **Step 4: Update `.gitignore` to allow this pattern**

Append to `.gitignore`:

```gitignore

# Local-only signal mappings; example files are tracked.
configs/signals/vehicles/*.json
!configs/signals/vehicles/*.example.json
```

- [ ] **Step 5: Update Module B spec**

`docs/analyzer/acquisition/specs/2026-05-14-module-b-spec.md`: add a "Local vs example mapping files" section that mirrors the runbook copy.

- [ ] **Step 6: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_signals.py -v
```

Expected: all GREEN, including the new checked-in-config test.

- [ ] **Step 7: Commit**

```bash
git add docs/analyzer/acquisition/Validation_Runbook.md \
    docs/analyzer/acquisition/specs/2026-05-14-module-b-spec.md \
    .gitignore \
    tests/test_acquisition_signals.py
git commit -m "docs(acquisition): fix runbook alias command and cover checked-in example config"
```

---

### Task 2.3: sha256 policy enforcement

**Origin:** External F4.

**Decision:**

- `required: true` AND `path_kind in ("local", "lfs")` → `sha256` MUST be present and non-empty.
- `required: false` → `sha256` is optional (placeholder/example tolerated).
- `path_kind == "external"` → `sha256` is optional (remote file, hash may not be locally computable).

Validation happens in `load_manifest`. `data/manifest.example.json` stays compatible because its single entry is `required: false`.

**Files:**
- Modify: `mf4_analyzer/acquisition/manifest.py`
- Modify: `tests/test_acquisition_manifest.py`
- Modify: `docs/analyzer/acquisition/specs/2026-05-14-module-a-spec.md`

- [ ] **Step 1: Write failing tests FIRST**

Append to `tests/test_acquisition_manifest.py`:

```python
def test_load_manifest_rejects_required_local_entry_without_sha256(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "needs-hash",
                        "path": "a.mf4",
                        "sets": ["smoke"],
                        "required": True,
                        "path_kind": "local",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="needs-hash.*sha256"):
        load_manifest(manifest)


def test_load_manifest_accepts_optional_entry_without_sha256(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "placeholder",
                        "path": "a.mf4",
                        "sets": ["smoke"],
                        "required": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_manifest(manifest)

    assert entries[0].sha256 is None


def test_load_manifest_accepts_external_entry_without_sha256(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "remote",
                        "path": "s3://bucket/key.mf4",
                        "sets": ["golden"],
                        "required": True,
                        "path_kind": "external",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_manifest(manifest)

    assert entries[0].sha256 is None
```

- [ ] **Step 2: Run tests to verify failure**

Expected: the first test FAILS (currently accepts missing sha256 silently).

- [ ] **Step 3: Add validation in `_entry`**

```python
sha256_raw = raw.get("sha256")
sha256 = str(sha256_raw) if sha256_raw else None
required = bool(raw.get("required", True))
if required and path_kind in ("local", "lfs") and not sha256:
    raise ValueError(
        f"{entry_id}: sha256 is required for required={required} "
        f"path_kind={path_kind!r} entries"
    )
```

Update existing manifest tests that are not about the sha256 policy to remain intentional:

- In `test_select_entries_filters_by_dataset`, add `"required": False` to the two placeholder entries.
- In `test_resolve_entry_path_handles_relative_to_manifest`, add `"required": False` to the relative-path placeholder entry.

- [ ] **Step 4: Update example manifest's documentation comment**

`data/manifest.example.json` already has `required: false` so it is exempt. No change needed in the data file itself.

- [ ] **Step 5: Update Module A spec**

`docs/analyzer/acquisition/specs/2026-05-14-module-a-spec.md`: add a "sha256 policy" subsection citing the rule above.

- [ ] **Step 6: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_manifest.py -v
```

Expected: all GREEN.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/acquisition/manifest.py \
    tests/test_acquisition_manifest.py \
    docs/analyzer/acquisition/specs/2026-05-14-module-a-spec.md
git commit -m "feat(manifest): enforce sha256 on required local/lfs entries"
```

---

### Task 2.4: Preflight hashes only when verification requested

**Origin:** Internal B2.

**Files:**
- Modify: `mf4_analyzer/acquisition/preflight.py`
- Modify: `tests/test_acquisition_preflight.py`

- [ ] **Step 1: Write failing test FIRST**

Append to `tests/test_acquisition_preflight.py`:

```python
def test_analyze_mf4_skips_sha256_when_not_requested(tmp_path, monkeypatch):
    """Hashing a multi-GB MF4 is expensive; do it only when expected_sha256 is set."""
    from mf4_analyzer.acquisition import preflight as preflight_module

    calls = {"count": 0}

    def fake_sha(_path):
        calls["count"] += 1
        return "0" * 64

    monkeypatch.setattr(preflight_module, "sha256_file", fake_sha)

    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4)

    analyze_mf4(mf4)
    assert calls["count"] == 0, "sha256_file must not be called without expected_sha256"

    analyze_mf4(mf4, expected_sha256="ignored")
    assert calls["count"] == 1, "sha256_file must be called once when verification requested"
```

- [ ] **Step 2: Run test to verify failure**

Expected: FAIL — currently `analyze_mf4` always hashes.

- [ ] **Step 3: Guard the hash call**

```python
actual_sha256 = sha256_file(p) if expected_sha256 else ""
if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
    problems.append("sha256 mismatch")
```

`PreflightResult.sha256` field stays — empty string when not computed. Document in docstring.

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_preflight.py -v
```

Expected: all GREEN.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition/preflight.py tests/test_acquisition_preflight.py
git commit -m "perf(preflight): skip sha256 unless caller requests verification"
```

---

## Stage 3 — Docs & Polish

Low-risk fixes. Merge after Stage 2.

---

### Task 3.1: Smoke runner tests

**Origin:** Internal B6.

**Files:**
- Create: `tests/test_acquisition_smoke.py`

- [ ] **Step 1: Author the test file**

Create `tests/test_acquisition_smoke.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _patched_subprocess_call(exit_codes):
    """Returns a callable that yields the next exit code each invocation."""
    iterator = iter(exit_codes)

    def fake_call(cmd, *_, **__):
        try:
            return next(iterator)
        except StopIteration:
            return 0

    return fake_call


def test_smoke_runner_skip_regression_returns_zero(monkeypatch, capsys):
    from scripts import acquisition_smoke

    monkeypatch.setattr(subprocess, "call", _patched_subprocess_call([0]))
    monkeypatch.setattr(sys, "argv", ["acquisition_smoke.py", "--skip-regression"])

    rc = acquisition_smoke.main()

    assert rc == 0


def test_smoke_runner_returns_one_on_pytest_failure(monkeypatch):
    from scripts import acquisition_smoke

    monkeypatch.setattr(subprocess, "call", _patched_subprocess_call([3]))  # pytest fail
    monkeypatch.setattr(sys, "argv", ["acquisition_smoke.py", "--skip-regression"])

    rc = acquisition_smoke.main()

    assert rc == 1


def test_smoke_runner_skips_manifest_absent_with_zero_exit(monkeypatch, tmp_path, capsys):
    from scripts import acquisition_smoke

    # pytest passes (stage 1), then stage 2 must not invoke subprocess.call
    monkeypatch.setattr(subprocess, "call", _patched_subprocess_call([0]))
    absent = tmp_path / "absent.json"
    monkeypatch.setattr(
        sys, "argv", ["acquisition_smoke.py", "--manifest", str(absent)]
    )

    rc = acquisition_smoke.main()
    captured = capsys.readouterr()

    assert rc == 0
    assert "not found" in captured.out
```

`from scripts import acquisition_smoke` works in this repository via Python's
namespace-package import from the repo root; do not add `scripts/__init__.py`.

- [ ] **Step 2: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_smoke.py -v
```

Expected: 3 GREEN.

- [ ] **Step 3: Commit**

```bash
git add tests/test_acquisition_smoke.py
git commit -m "test(smoke): add subprocess-monkeypatched smoke runner tests"
```

---

### Task 3.2: Non-conditional signal test inclusion

**Origin:** Internal B5.

**Files:**
- Modify: `scripts/acquisition_smoke.py`

- [ ] **Step 1: Update UNIT_TESTS list**

```python
UNIT_TESTS = [
    "tests/test_acquisition_manifest.py",
    "tests/test_acquisition_preflight.py",
    "tests/test_acquisition_regression.py",
    "tests/test_acquisition_signals.py",   # was conditional; now always
    "tests/test_acquisition_smoke.py",
    "tests/synthetic",
]
```

Delete the `SIGNAL_TESTS` constant and the conditional `if exists` block.

- [ ] **Step 2: Run smoke runner**

```bash
.venv/bin/python scripts/acquisition_smoke.py --skip-regression
```

Expected: exit 0 with all listed test files.

- [ ] **Step 3: Commit**

```bash
git add scripts/acquisition_smoke.py
git commit -m "fix(smoke): make signal test inclusion non-conditional"
```

---

### Task 3.3: Stale report corrections

**Origin:** External F5.

**Files:**
- Modify: `docs/analyzer/acquisition/reports/2026-05-14-module-c-report.md`
- Modify: `docs/analyzer/acquisition/reports/2026-05-14-module-a-report.md` (if needed)
- Modify: `docs/analyzer/acquisition/reports/2026-05-14-module-b-report.md` (if needed)
- Modify: `docs/analyzer/acquisition/reports/2026-05-14-p0-report.md` (if needed)
- Modify: `docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md` (branch strategy note)

- [ ] **Step 1: Module C report**

- Test count: 19 → 36 after Stage 3.2 (manifest 8 + preflight 8 + regression 10 + signals 5 + smoke 3 + synthetic 2).
- `subprocess.run(shell=False)` → `subprocess.call(cmd, cwd=, env=)` — or change the code if `run` is preferred.

- [ ] **Step 2: Master program plan — branch strategy note**

In the Branch Strategy section, add:

```markdown
**Post-execution note (2026-05-15):** The 2026-05-14 execution used a single
`feat/acquisition-validation-program` branch for all four modules (A/B/C/P0)
instead of one branch per module. This worked because specialists' file scopes
were disjoint, but it weakens the independent-revert boundary the plan
originally specified. Follow-up plan
`2026-05-15-acquisition-validation-fixes.md` uses one branch per stage.
```

- [ ] **Step 3: Sweep other reports for similar claims**

Read each report, fix exact API/command/test-count claims that no longer match code reality after Stages 1–2.

- [ ] **Step 4: Commit**

```bash
git add docs/analyzer/acquisition/reports docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md
git commit -m "docs(reports): correct stale execution claims"
```

---

### Task 3.4: Frozen dataclass / immutable mapping consistency

**Origin:** Internal S2.

**Files:**
- Modify: `mf4_analyzer/acquisition/preflight.py`
- Modify: `mf4_analyzer/acquisition/signals.py`

- [ ] **Step 1: Extract module-level empty mapping constant**

In `mf4_analyzer/acquisition/signals.py`, add:

```python
from types import MappingProxyType

_EMPTY_ALIAS_MAP: Mapping[str, tuple[str, ...]] = MappingProxyType({})


@dataclass(frozen=True)
class VehicleSignalMapping:
    vehicle: str
    aliases: Mapping[str, tuple[str, ...]] = _EMPTY_ALIAS_MAP
```

Drop `field(default_factory=lambda: MappingProxyType({}))`.

- [ ] **Step 2: Apply same pattern to `PreflightResult`**

In `mf4_analyzer/acquisition/preflight.py`:

```python
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping

_EMPTY_SIGNAL_MAP: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True)
class PreflightResult:
    # ... existing fields ...
    resolved_signals: Mapping[str, str] = _EMPTY_SIGNAL_MAP

    def to_json(self) -> str:
        payload = {
            "path": self.path,
            "ok": self.ok,
            "rows": self.rows,
            "channels": list(self.channels),
            "units": dict(self.units),
            "duration_s": self.duration_s,
            "estimated_fs_hz": self.estimated_fs_hz,
            "missing_channels": list(self.missing_channels),
            "problems": list(self.problems),
            "sha256": self.sha256,
            "resolved_signals": dict(self.resolved_signals),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
```

Update both call sites that construct `PreflightResult(resolved_signals={...})`:

- File-missing early return: `resolved_signals=_EMPTY_SIGNAL_MAP`
- Success return: `resolved_signals=MappingProxyType(resolved_signals)` (wrap the local dict)
- Loader-failure return (added in Task 1.2): `resolved_signals=_EMPTY_SIGNAL_MAP`

Add this assertion to `test_analyze_mf4_reports_resolved_standard_signals` so
`MappingProxyType` never regresses JSON export:

```python
payload = json.loads(result.to_json())
assert payload["resolved_signals"] == {"vehicle_speed": "raw_speed"}
```

- [ ] **Step 3: Run all preflight + signals tests**

Expected: all GREEN. Tests assert `result.resolved_signals == {"vehicle_speed": "raw_speed"}`. `MappingProxyType({...}) == {...}` is True in Python, so equality tests pass without change.

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_preflight.py tests/test_acquisition_signals.py -v
```

- [ ] **Step 4: Commit**

```bash
git add mf4_analyzer/acquisition/preflight.py mf4_analyzer/acquisition/signals.py
git commit -m "refactor(acquisition): use MappingProxyType for resolved_signals to match frozen=True"
```

---

### Task 3.5: A2L probe raises on missing address

**Origin:** Internal S7.

**Files:**
- Modify: `can_logger/p0/a2l_probe.py`
- Modify: `tests/test_p0_a2l_probe.py`

- [ ] **Step 1: Write failing test FIRST**

Append to `tests/test_p0_a2l_probe.py`:

```python
def test_address_of_raises_when_attribute_missing():
    from can_logger.p0.a2l_probe import _address_of

    class FakeMeasurement:
        name = "BadMeasurement"
        # no ecu_address attribute

    with pytest.raises(ValueError, match="BadMeasurement.*ecu_address"):
        _address_of(FakeMeasurement())
```

- [ ] **Step 2: Run test to verify failure**

Expected: FAIL — currently returns 0.

- [ ] **Step 3: Update `_address_of`**

```python
def _address_of(measurement) -> int:
    ecu_address = getattr(measurement, "ecu_address", None)
    address = getattr(ecu_address, "address", ecu_address)
    if address is None:
        name = getattr(measurement, "name", "<unknown>")
        raise ValueError(f"measurement {name!r} has no ecu_address")
    return int(address)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_a2l_probe.py -v
```

Expected: env-gated real-A2L test still SKIPPED; new unit test GREEN.

- [ ] **Step 5: Commit**

```bash
git add can_logger/p0/a2l_probe.py tests/test_p0_a2l_probe.py
git commit -m "fix(a2l): raise on missing ecu_address instead of silent 0 fallback"
```

---

### Task 3.6: Manifest entry id character validation

**Origin:** Internal S12.

**Files:**
- Modify: `mf4_analyzer/acquisition/manifest.py`
- Modify: `tests/test_acquisition_manifest.py`

- [ ] **Step 1: Write failing tests FIRST**

```python
@pytest.mark.parametrize("bad_id", ["a/b", "..", "with space", "a..b"])
def test_load_manifest_rejects_id_with_unsafe_chars(tmp_path, bad_id):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"id": bad_id, "path": "a.mf4", "sets": ["smoke"], "required": False}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid"):
        load_manifest(manifest)


@pytest.mark.parametrize("good_id", ["abc", "x04c-low-temp", "test_case_01", "abc123"])
def test_load_manifest_accepts_safe_ids(tmp_path, good_id):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {"id": good_id, "path": "a.mf4", "sets": ["smoke"], "required": False}
                ],
            }
        ),
        encoding="utf-8",
    )

    entries = load_manifest(manifest)
    assert entries[0].id == good_id
```

- [ ] **Step 2: Run tests to verify failure**

Expected: bad_id parametrize all FAIL.

- [ ] **Step 3: Add regex check in `_entry`**

```python
import re

_VALID_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _entry(raw: dict) -> Mf4DatasetEntry:
    entry_id = str(raw.get("id", "")).strip()
    if not entry_id:
        raise ValueError("entry id is required")
    if not _VALID_ID.match(entry_id):
        raise ValueError(
            f"entry id {entry_id!r} contains invalid characters "
            f"(allowed: alphanumeric, dash, underscore)"
        )
    # ... rest of validation ...
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_manifest.py -v
```

Expected: all GREEN.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition/manifest.py tests/test_acquisition_manifest.py
git commit -m "fix(manifest): restrict entry id to alphanumeric, dash, underscore"
```

---

### Task 3.7: Miscellaneous polish

**Origin:** Internal S1, S3, S4, S9, S10, S11, P1, P2, P3, P5, P10, P11, P12.

One commit bundling small clarity fixes.

**Files:**
- Modify: `mf4_analyzer/acquisition/manifest.py`
- Modify: `mf4_analyzer/acquisition/preflight.py`
- Modify: `mf4_analyzer/acquisition/signals.py`
- Modify: `can_logger/p0/mf4_probe.py`
- Modify: `scripts/preflight.py`
- Modify: `scripts/regression.py`
- Modify: `scripts/acquisition_smoke.py`
- Modify: `tests/test_acquisition_preflight.py`
- Create: `tests/_helpers/__init__.py`
- Create: `tests/_helpers/mf4_factory.py`
- Modify: `tests/test_acquisition_preflight.py`, `tests/test_acquisition_regression.py`, `tests/test_p0_mf4_probe.py` (use shared factory)

- [ ] **Step 1: Manifest defensive parsing**

```python
def load_manifest(path: str | Path) -> list[Mf4DatasetEntry]:
    ...
    if not isinstance(raw, dict):
        raise ValueError(f"manifest must be a JSON object, got {type(raw).__name__}")
    ...
```

- [ ] **Step 2: Signals null-alias safety**

```python
aliases_raw = raw.get("aliases") or {}
if not isinstance(aliases_raw, dict):
    raise ValueError("aliases must be a JSON object")
aliases = _coerce_aliases(aliases_raw)
```

- [ ] **Step 3: Preflight rename `expected_raw` → `effective_expected`**

For readability — `expected_raw` is misleading when no alias resolution is active.

- [ ] **Step 4: Preflight non-finite check aggregation**

```python
bad_cols = []
for col in numeric_cols:
    vals = np.asarray(df[col], dtype=float)
    if np.any(~np.isfinite(vals)):
        bad_cols.append(col)
if bad_cols:
    preview = ", ".join(bad_cols[:5])
    suffix = f" (+{len(bad_cols)-5} more)" if len(bad_cols) > 5 else ""
    problems.append(f"{len(bad_cols)} channel(s) contain non-finite values: {preview}{suffix}")
```

- [ ] **Step 5: `mf4_probe.py` type hints + ndim guard**

```python
from collections.abc import Sequence

def write_single_signal_mf4(
    output_path: str | Path,
    *,
    signal_name: str,
    unit: str,
    timestamps: Sequence[float] | np.ndarray,
    samples: Sequence[float] | np.ndarray,
) -> Path:
    ...
    if ts.ndim != 1 or vals.ndim != 1:
        raise ValueError("timestamps and samples must be 1-D")
    if ts.shape != vals.shape:
        raise ValueError("timestamps and samples must have the same length")
    ...
```

- [ ] **Step 6: `Mf4DatasetEntry` kw_only=True**

```python
@dataclass(frozen=True, kw_only=True)
class Mf4DatasetEntry:
    ...
```

Update test that constructs the entry positionally (`tests/test_acquisition_manifest.py::test_load_manifest_normalizes_entries`) to use kwargs.

- [ ] **Step 7: Smoke runner dead-code removal**

Delete the unreachable `shutil.which / Path.exists` check in `scripts/acquisition_smoke.py` (lines 79–81).

- [ ] **Step 8: CLI friendly errors**

`scripts/preflight.py` and `scripts/regression.py` — wrap `main()` body:

```python
import json
import sys


def main() -> int:
    try:
        return _run()  # extract existing body
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in input: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
```

- [ ] **Step 9: Preflight test float tolerance**

`tests/test_acquisition_preflight.py`:

```diff
-    assert abs(result.duration_s - 0.03) < 1e-12
+    assert result.duration_s == pytest.approx(0.03, abs=1e-9)
```

Add `import pytest` if not already.

- [ ] **Step 10: Shared MF4 factory**

Create `tests/_helpers/__init__.py` (empty) and `tests/_helpers/mf4_factory.py`:

```python
"""Shared MF4 builder for tests."""
from pathlib import Path
from typing import Sequence

import numpy as np
from asammdf import MDF, Signal


def write_single_channel_mf4(
    path: Path,
    *,
    name: str = "sig",
    unit: str = "V",
    timestamps: Sequence[float] = (0.0, 0.01, 0.02, 0.03),
    samples: Sequence[float] = (1.0, 2.0, 3.0, 4.0),
) -> Path:
    t = np.asarray(timestamps, dtype=float)
    y = np.asarray(samples, dtype=float)
    mdf = MDF(version="4.10")
    mdf.append([Signal(samples=y, timestamps=t, name=name, unit=unit)])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path
```

Replace `_write_mf4` in `tests/test_acquisition_preflight.py`, `tests/test_acquisition_regression.py`, and `tests/test_p0_mf4_probe.py` with imports from `_helpers.mf4_factory`. Keep call-site signatures matching what each test passes.

- [ ] **Step 11: Run full test suite**

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition_* tests/test_p0_* tests/synthetic -v
```

Expected: all GREEN.

- [ ] **Step 12: Commit**

```bash
git add mf4_analyzer/acquisition can_logger/p0 scripts tests
git commit -m "chore(acquisition): polish (typing, dead code, CLI errors, shared fixtures)"
```

---

## Final Verification (Plan Level)

Run from a clean checkout on the final Stage 3 branch:

```bash
git status --short
PYTHONPATH=. .venv/bin/python -m pytest \
    tests/test_acquisition_manifest.py \
    tests/test_acquisition_preflight.py \
    tests/test_acquisition_regression.py \
    tests/test_acquisition_signals.py \
    tests/test_acquisition_smoke.py \
    tests/test_p0_mf4_probe.py \
    tests/test_p0_a2l_probe.py \
    tests/test_p0_vector_probe.py \
    tests/test_p0_xcp_probe.py \
    tests/synthetic -v
python scripts/acquisition_smoke.py --skip-regression
python scripts/preflight.py docs/analyzer/acquisition/templates/issue_capture.md --require-exists
```

Expected:

- Only intended files modified.
- All tests GREEN; 1 SKIPPED (A2L env-gated) is acceptable.
- Smoke runner exits 0.
- Preflight CLI exits 1 and prints `ok=false` JSON with a `loader failed` problem on a non-MF4 input; it must not raise a traceback. CLI usage/config errors still exit 2 after Task 3.7.

---

## Deferred Items (Explicitly Out of Scope)

- **Module D — CI integration** (roadmap §14). Start after this plan merges; current test set will stabilize first.
- **Module E — bad-case synthetic MF4 corpus** (roadmap §L3). Needs Module A's regression to be loud-failing (Stage 1) before bad-case corpus has value.
- **Real P0 Windows run** — hardware dependency. Resume on a Windows + Vector workstation after Task 2.1's stubs are in place.
- **Loader-level standard-signal sinking** (roadmap §6 original intent) — after sidecar in Module B has stabilized for ≥ 2 vehicles.
- **Plan/spec post-merge cleanup beyond Task 3.3** — the 2026-05-14 plans/specs stay valid; only the parts contradicted by code reality get fixed in Task 3.3.

---

## Self-Review Checklist For The Implementer

- [ ] Stage 1 merged before any Stage 2 / Stage 3 work begins.
- [ ] Task 2.1 decision committed in writing — code stubs in repo OR docs downgraded to "not authored". No silent middle ground.
- [ ] Task 2.3 sha256 policy committed in writing — `data/manifest.example.json` still parses (because it is `required: false`).
- [ ] No confidential vehicle data, A2L files, MF4 files, or local mappings committed.
- [ ] `DataLoader.load_mf4` still returns raw channel names — no loader edits in this plan.
- [ ] Standard signal aliases continue to be reported as metadata/sidecar resolution, not used to hide original channels.
- [ ] At least 8 new tests land across Stages 1–3 (Fix-1 alone adds 3).
- [ ] `tests/test_acquisition_smoke.py` exists and exercises 3 paths (Task 3.1).
- [ ] `can_logger/p0/vector_probe.py` and `xcp_short_upload_probe.py` exist and import cleanly on macOS (Task 2.1).
- [ ] `Validation_Runbook.md` standard commands are copy-paste runnable in a clean checkout (Task 2.2).
- [ ] No `.py` file in this plan modifies UI, batch, FFT, signal/order_cot, or loader code.
