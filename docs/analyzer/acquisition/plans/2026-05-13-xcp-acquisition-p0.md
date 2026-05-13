# XCP Acquisition P0 Feasibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that this analyzer can receive one real XCP-over-CAN value, save it as MF4, and load it back through the existing analyzer loader.

**Architecture:** P0 is a command-line feasibility harness, not a production UI. It adds isolated modules under `can_logger/p0/`, uses environment variables for target-specific hardware values, and verifies MF4 output through the existing `mf4_analyzer.io.loader.DataLoader`.

**Tech Stack:** Python 3.12 target venv, `asammdf`, `python-can[vector]`, `pya2ldb`, optional `pyxcp`, optional `pyelftools`, pytest.

---

## Branch Strategy

Use a normal feature branch based on current repo history. Do not create an orphan or blank branch.

Because the current working tree may contain unrelated UI/lesson changes, prefer a clean worktree for implementation:

```bash
git worktree add ../data-analyzer-xcp-p0 -b feat/xcp-acquisition-p0 main
cd ../data-analyzer-xcp-p0
```

If the feasibility report changes are uncommitted in the original worktree, apply them to the P0 worktree before the first docs commit, or commit them separately before starting P0 implementation.

---

## File Structure

- Create: `can_logger/__init__.py`
- Create: `can_logger/p0/__init__.py`
- Create: `can_logger/p0/mf4_probe.py`
- Create: `can_logger/p0/a2l_probe.py`
- Create: `can_logger/p0/vector_probe.py`
- Create: `can_logger/p0/xcp_short_upload_probe.py`
- Create: `tests/test_p0_mf4_probe.py`
- Create: `tests/test_p0_a2l_probe.py`
- Create: `docs/analyzer/acquisition/P0_Runbook.md`

No production UI files should be modified in P0.

---

### Task 1: Create Clean Branch And Verify Environment

**Files:**
- No source files.

- [ ] **Step 1: Check current tree**

Run:

```bash
git status --short
```

Expected: note any unrelated dirty files before creating the worktree.

- [ ] **Step 2: Create the feature worktree**

Run:

```bash
git worktree add ../data-analyzer-xcp-p0 -b feat/xcp-acquisition-p0 main
cd ../data-analyzer-xcp-p0
```

Expected: clean checkout on `feat/xcp-acquisition-p0`.

- [ ] **Step 3: Create or refresh venv on macOS for hardware-free tests**

Run:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install "pya2ldb==1.0.332" "pyxcp==0.29.8" "python-can[vector]>=4.6,<5" "pyelftools==0.32"
```

Expected: install completes or fails with an exact dependency error to record in `P0_Runbook.md`.

- [ ] **Step 4: Create or refresh venv on Windows for Vector tests**

Run from `Z:\Downloads\data analyzer` or the Windows P0 checkout:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install "pya2ldb==1.0.332" "pyxcp==0.29.8" "python-can[vector]>=4.6,<5" "pyelftools==0.32"
```

Expected: install completes in the target hardware environment.

- [ ] **Step 5: Verify imports**

Run on both macOS and Windows:

```bash
.venv/bin/python - <<'PY'
import asammdf
import can
import pyxcp
import elftools
from pya2l import DB
print("imports ok")
print("asammdf", asammdf.__version__)
print("python-can", can.__version__)
PY
```

Windows equivalent:

```powershell
@"
import asammdf
import can
import pyxcp
import elftools
from pya2l import DB
print("imports ok")
print("asammdf", asammdf.__version__)
print("python-can", can.__version__)
"@ | .\.venv\Scripts\python.exe -
```

Expected: `imports ok`.

- [ ] **Step 6: Commit docs/environment notes if files were changed**

Run:

```bash
git status --short
git add "docs/analyzer/acquisition/CAN_Logger_Integration_Report.md" docs/analyzer/acquisition/plans/2026-05-13-xcp-acquisition-p0.md
git commit -m "docs: revise xcp acquisition feasibility"
```

Expected: docs-only commit. If docs are not in this worktree yet, skip this commit and record why in `P0_Runbook.md`.

---

### Task 2: Prove MF4 Output Loads In Existing Analyzer

**Files:**
- Create: `can_logger/__init__.py`
- Create: `can_logger/p0/__init__.py`
- Create: `can_logger/p0/mf4_probe.py`
- Create: `tests/test_p0_mf4_probe.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_p0_mf4_probe.py`:

```python
from pathlib import Path

import pytest

from can_logger.p0.mf4_probe import write_single_signal_mf4
from mf4_analyzer.io.loader import DataLoader


def test_p0_written_mf4_loads_through_existing_loader(tmp_path):
    out = tmp_path / "p0_single_signal.mf4"

    written = write_single_signal_mf4(
        out,
        signal_name="EngineSpeed",
        unit="rpm",
        timestamps=[0.0, 0.01, 0.02],
        samples=[1000.0, 1010.0, 1020.0],
    )

    assert written == out
    assert out.exists()

    df, channels, units = DataLoader.load_mf4(str(out))

    assert "EngineSpeed" in channels
    assert units["EngineSpeed"] == "rpm"
    assert list(df["EngineSpeed"]) == pytest.approx([1000.0, 1010.0, 1020.0])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_mf4_probe.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'can_logger'`.

- [ ] **Step 3: Add minimal package files**

Create `can_logger/__init__.py`:

```python
"""CAN/XCP acquisition experiments for MF4 Data Analyzer."""
```

Create `can_logger/p0/__init__.py`:

```python
"""P0 feasibility probes for acquisition integration."""
```

- [ ] **Step 4: Implement MF4 probe**

Create `can_logger/p0/mf4_probe.py`:

```python
from pathlib import Path

import numpy as np
from asammdf import MDF, Signal


def write_single_signal_mf4(
    output_path: str | Path,
    *,
    signal_name: str,
    unit: str,
    timestamps: list[float],
    samples: list[float],
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ts = np.asarray(timestamps, dtype=float)
    vals = np.asarray(samples, dtype=float)
    if ts.shape != vals.shape:
        raise ValueError("timestamps and samples must have the same length")
    if ts.size == 0:
        raise ValueError("at least one sample is required")

    mdf = MDF(version="4.10")
    signal = Signal(samples=vals, timestamps=ts, name=signal_name, unit=unit)
    mdf.append([signal], comment="P0 acquisition probe")
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_mf4_probe.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add can_logger tests/test_p0_mf4_probe.py
git commit -m "test: prove p0 mf4 output opens in analyzer"
```

---

### Task 3: Parse A2L Measurement Summary

**Files:**
- Create: `can_logger/p0/a2l_probe.py`
- Create: `tests/test_p0_a2l_probe.py`

- [ ] **Step 1: Write the environment-gated test**

Create `tests/test_p0_a2l_probe.py`:

```python
import os

import pytest

from can_logger.p0.a2l_probe import load_measurement_summary


@pytest.mark.skipif(
    not os.environ.get("P0_A2L_PATH"),
    reason="set P0_A2L_PATH to a real ECU A2L file for this probe",
)
def test_p0_real_a2l_has_measurements():
    summary = load_measurement_summary(os.environ["P0_A2L_PATH"], limit=5)

    assert summary.total_measurements > 0
    assert summary.measurements
    first = summary.measurements[0]
    assert first.name
    assert first.datatype
    assert isinstance(first.address, int)
```

- [ ] **Step 2: Run test without A2L**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_a2l_probe.py -v
```

Expected: SKIPPED with reason `set P0_A2L_PATH...`.

- [ ] **Step 3: Implement A2L summary adapter**

Create `can_logger/p0/a2l_probe.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from pya2l import DB
import pya2l.model as model


@dataclass(frozen=True)
class MeasurementSummary:
    name: str
    address: int
    datatype: str
    unit: str
    conversion: str


@dataclass(frozen=True)
class A2LSummary:
    path: str
    total_measurements: int
    measurements: list[MeasurementSummary]


def _address_of(measurement) -> int:
    ecu_address = getattr(measurement, "ecu_address", None)
    address = getattr(ecu_address, "address", ecu_address)
    if address is None:
        return 0
    return int(address)


def load_measurement_summary(a2l_path: str, *, limit: int = 20) -> A2LSummary:
    path = Path(a2l_path)
    if not path.exists():
        raise FileNotFoundError(path)

    db = DB()
    session = db.import_a2l(str(path), progress_bar=False, loglevel="ERROR")
    try:
        query = session.query(model.Measurement).order_by(model.Measurement.name)
        total = query.count()
        rows = query.limit(limit).all()
        measurements = [
            MeasurementSummary(
                name=str(m.name),
                address=_address_of(m),
                datatype=str(getattr(m, "datatype", "")),
                unit=str(getattr(m, "phys_unit", "") or ""),
                conversion=str(getattr(m, "conversion", "") or ""),
            )
            for m in rows
        ]
        return A2LSummary(
            path=str(path),
            total_measurements=total,
            measurements=measurements,
        )
    finally:
        db.close()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Summarize measurements from a real A2L file.")
    parser.add_argument("a2l_path")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    summary = load_measurement_summary(args.a2l_path, limit=args.limit)
    print(f"A2L: {summary.path}")
    print(f"measurements: {summary.total_measurements}")
    for item in summary.measurements:
        print(
            f"{item.name}\t0x{item.address:08X}\t{item.datatype}\t"
            f"{item.unit}\t{item.conversion}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run with real A2L**

Run:

```bash
test -f "$P0_A2L_PATH"
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_a2l_probe.py -v
PYTHONPATH=. .venv/bin/python -m can_logger.p0.a2l_probe "$P0_A2L_PATH" --limit 10
```

Expected: test PASS and CLI prints non-empty measurement rows.

- [ ] **Step 5: Commit**

Run:

```bash
git add can_logger/p0/a2l_probe.py tests/test_p0_a2l_probe.py
git commit -m "feat: add p0 a2l summary probe"
```

---

### Task 4: Verify Vector Hardware Access On Windows

**Files:**
- Create: `can_logger/p0/vector_probe.py`

- [ ] **Step 1: Implement Vector channel probe**

Create `can_logger/p0/vector_probe.py`:

```python
import argparse
import sys


def list_vector_channels() -> list:
    from can.interfaces import vector

    return list(vector.get_channel_configs())


def open_vector_bus(*, channel: int, bitrate: int, app_name: str):
    import can

    return can.Bus(interface="vector", channel=channel, bitrate=bitrate, app_name=app_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe python-can Vector access.")
    parser.add_argument("--channel", type=int, default=0)
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--app-name", default="CANalyzer")
    parser.add_argument("--open", action="store_true", help="also open and close the bus")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("Vector interface is expected to run on Windows; current platform:", sys.platform)
        return 2

    channels = list_vector_channels()
    print(f"vector_channels: {len(channels)}")
    for ch in channels:
        print(ch)

    if args.open:
        bus = open_vector_bus(
            channel=args.channel,
            bitrate=args.bitrate,
            app_name=args.app_name,
        )
        try:
            print("vector_open: ok")
        finally:
            bus.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run on macOS to confirm graceful non-Windows exit**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m can_logger.p0.vector_probe
```

Expected: exit code 2 and message that Vector is expected on Windows.

- [ ] **Step 3: Run on Windows with Vector driver installed**

Run:

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m can_logger.p0.vector_probe --channel 0 --bitrate 500000 --app-name CANalyzer --open
```

Expected: `vector_open: ok`. If it fails, record the exact exception in `P0_Runbook.md`.

- [ ] **Step 4: Commit**

Run:

```bash
git add can_logger/p0/vector_probe.py
git commit -m "feat: add p0 vector access probe"
```

---

### Task 5: Verify XCP CONNECT And SHORT_UPLOAD

**Files:**
- Create: `can_logger/p0/xcp_short_upload_probe.py`

- [ ] **Step 1: Implement raw XCP probe**

Create `can_logger/p0/xcp_short_upload_probe.py`:

```python
import argparse
import struct
import time

import can


CMD_CONNECT = 0xFF
CMD_DISCONNECT = 0xFE
CMD_SHORT_UPLOAD = 0xF4
RESP_OK = 0xFF


def parse_int(text: str) -> int:
    return int(text, 0)


class RawXcpCanProbe:
    def __init__(self, bus, *, cmd_id: int, resp_id: int, timeout: float = 0.5):
        self.bus = bus
        self.cmd_id = cmd_id
        self.resp_id = resp_id
        self.timeout = timeout

    def send(self, payload: bytes) -> None:
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
            raise RuntimeError(f"negative XCP response: pid=0x{response[0]:02X}, code=0x{code:02X}")
        return response

    def connect(self) -> bytes:
        return self.command(bytes([CMD_CONNECT, 0x00]))

    def disconnect(self) -> None:
        self.send(bytes([CMD_DISCONNECT]))

    def short_upload(self, *, address: int, size: int, address_extension: int = 0) -> bytes:
        payload = struct.pack("<BBBBI", CMD_SHORT_UPLOAD, size, 0x00, address_extension, address)
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
    if len(raw) < struct.calcsize(endian_prefix + fmt):
        raise ValueError(f"not enough data for {dtype}: {raw.hex()}")
    return struct.unpack(endian_prefix + fmt, raw[: struct.calcsize(endian_prefix + fmt)])[0]


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
    parser.add_argument("--dtype", choices=["u8", "s8", "u16", "s16", "u32", "s32", "f32", "f64"], default="f32")
    parser.add_argument("--endian", choices=["little", "big"], default="little")
    args = parser.parse_args()

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

- [ ] **Step 2: Run against powered ECU on Windows**

Run with real IDs/address from the A2L or calibration owner:

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m can_logger.p0.xcp_short_upload_probe `
  --interface vector `
  --channel 0 `
  --bitrate 500000 `
  --app-name CANalyzer `
  --cmd-id 0x7E1 `
  --resp-id 0x7E9 `
  --address 0x20003A4C `
  --size 4 `
  --dtype f32 `
  --endian little
```

Expected: `connect_response: ...`, `raw: ...`, and a plausible decoded value. Replace IDs/address/type with real target values before accepting the result.

- [ ] **Step 3: Commit**

Run:

```bash
git add can_logger/p0/xcp_short_upload_probe.py
git commit -m "feat: add p0 xcp short-upload probe"
```

---

### Task 6: Capture One Read Value As MF4

**Files:**
- Modify: `can_logger/p0/xcp_short_upload_probe.py`
- Modify: `tests/test_p0_mf4_probe.py`

- [ ] **Step 1: Add output arguments to the XCP probe**

Modify `can_logger/p0/xcp_short_upload_probe.py`:

```python
# Add near other imports
from .mf4_probe import write_single_signal_mf4

# Add parser arguments inside main()
parser.add_argument("--signal-name", default="P0Signal")
parser.add_argument("--unit", default="")
parser.add_argument("--mf4-out", default="")

# After decoded value is computed
value = decode_raw(raw, args.dtype, args.endian)
print("decoded:", value)
if args.mf4_out:
    path = write_single_signal_mf4(
        args.mf4_out,
        signal_name=args.signal_name,
        unit=args.unit,
        timestamps=[0.0],
        samples=[float(value)],
    )
    print("mf4:", path)
```

Keep only one `print("decoded:", value)` line after the edit.

- [ ] **Step 2: Run hardware command with MF4 output**

Run:

```powershell
$env:PYTHONPATH="."
.\.venv\Scripts\python.exe -m can_logger.p0.xcp_short_upload_probe `
  --interface vector `
  --channel 0 `
  --bitrate 500000 `
  --app-name CANalyzer `
  --cmd-id 0x7E1 `
  --resp-id 0x7E9 `
  --address 0x20003A4C `
  --size 4 `
  --dtype f32 `
  --endian little `
  --signal-name EngineSpeed `
  --unit rpm `
  --mf4-out .\recordings\p0_short_upload.mf4
```

Expected: command prints `mf4: recordings\p0_short_upload.mf4`.

- [ ] **Step 3: Verify generated MF4 with existing loader**

Run:

```powershell
$env:PYTHONPATH="."
@"
from mf4_analyzer.io.loader import DataLoader
df, channels, units = DataLoader.load_mf4(r".\recordings\p0_short_upload.mf4")
print(channels)
print(df.head().to_string(index=False))
print(units)
"@ | .\.venv\Scripts\python.exe -
```

Expected: printed channels include `EngineSpeed` or the selected `--signal-name`.

- [ ] **Step 4: Commit**

Run:

```bash
git add can_logger/p0/xcp_short_upload_probe.py tests/test_p0_mf4_probe.py
git commit -m "feat: save p0 xcp read as mf4"
```

---

### Task 7: Write P0 Runbook Results

**Files:**
- Create: `docs/analyzer/acquisition/P0_Runbook.md`

- [ ] **Step 1: Create runbook**

Create `docs/analyzer/acquisition/P0_Runbook.md`:

````markdown
# P0 Acquisition Runbook

Date:
Branch:
Machine:
Python:
Vector hardware:
ECU:
A2L file:

## Dependency Probe

Command:

```text

```

Result:

```text

```

## MF4 Compatibility

Command:

```text

```

Result:

```text

```

## A2L Parse

Command:

```text

```

Result:

```text

```

## Vector Access

Command:

```text

```

Result:

```text

```

## XCP CONNECT And SHORT_UPLOAD

Command:

```text

```

Result:

```text

```

## Final Verdict

Verdict: UNKNOWN

Reasons:
- 
````

- [ ] **Step 2: Fill the runbook with actual commands and outputs**

Replace every empty fenced block with the exact command/output snippets from Tasks 1-6. Set verdict to one of:

```text
PASS
PARTIAL
BLOCKED
FAIL
```

- [ ] **Step 3: Run verification subset**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_mf4_probe.py tests/test_p0_a2l_probe.py -v
```

Expected: MF4 test PASS; A2L test PASS when `P0_A2L_PATH` is set or SKIPPED when not set.

- [ ] **Step 4: Commit**

Run:

```bash
git add "docs/analyzer/acquisition/P0_Runbook.md"
git commit -m "docs: record p0 acquisition runbook"
```

---

## P0 Completion Gate

P0 is complete only when:

- MF4 compatibility test passes.
- Real A2L parse either passes or has a documented parser blocker.
- Windows Vector open either passes or has a documented driver/config blocker.
- XCP `CONNECT` and `SHORT_UPLOAD` either pass or have a documented ECU/protocol blocker.
- `docs/analyzer/acquisition/P0_Runbook.md` contains the actual command/output evidence.

If all pass, proceed to P1: a small acquisition sidecar window or dialog. If any are blocked, do not start DAQ streaming or full UI integration yet.
