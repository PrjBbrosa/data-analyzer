# Stage 8 — Vector + XCP/DAQ Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision history:**
- v1 (2026-05-17 AM): initial 4-PR, 20-task plan.
- v2 (2026-05-17 PM): Codex adversarial-review patched 6 contract drifts
  against the live dataclasses. See spec §0.1 "Errata" for the full list.
  Plan-level changes: Task 5 now implements per-MEASUREMENT IF_DATA walk
  with a non-skipped synthetic-A2L test (E-1); Task 9 changes
  `build_daq_map` signature to take a `measurements` lookup and removes
  the bogus `sel.datatype`/`sel.size_bytes` reads (E-2); Task 12 uses the
  real 5-field `BackendStatus` and adds a `CaptureController` round-trip
  test (E-3); Task 16 splits Test Connection into hw-probe + xcp-probe
  stages with a no-A2L-loaded disabled state (E-4); new Task 11a
  implements the Seed&Key flow (E-5); Task 15 fills every `HwHealth(...)`
  with `channel_count` and `last_probe_ts` (E-6).

**Goal:** Replace the `VectorXcpRecorderBackend` stub with a production backend that, on Windows + Vector hardware + a powered ECU, records XCP DAQ samples to MF4 via the existing capture pipeline.

**Architecture:** Four-PR increment. PR-1 = foundation (deps + A2L IF_DATA parser, pure logic). PR-2 = backend core (`XcpDaqSession`, `DaqMap`, `dto_decode`, mock-transport tested). PR-3 = cockpit UI (Transport settings tab, status chip, HW probe). PR-4 = bench validation (runbook + on-vehicle bug fixes). Every PR-1/2/3 step is mock-tested on macOS; only PR-4 requires Windows + ECU.

**Tech Stack:** Python 3.10+, `python-can[vector]>=4.3.0`, `pyxcp>=0.22.0`, `pya2l` (already in repo), PyQt5, pytest, asammdf.

**Spec:** `docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md`

---

## OPEN ITEMS (re-surfaced from spec §0)

| # | Open item | Blocks PR | Status |
|---|---|---|---|
| **O-1** | Real A2L file with `IF_DATA XCP` block | PR-1 nice-to-have, PR-4 mandatory | ⏳ |
| **O-2** | Vector `app_name` on test PC | PR-3 smoke, PR-4 mandatory | ⏳ |
| **O-3** | ECU XCP auth state (and DLL if needed) | PR-4 mandatory | ⏳ |
| **O-4** | HIL/vehicle bench access | PR-3 optional smoke, PR-4 mandatory | ⏳ |
| **O-5** | Classic CAN vs CAN-FD decision | PR-4 mandatory | ⏳ |

**PR-1 can fully proceed with only synthetic IF_DATA fixtures. PR-2 same. PR-3 only needs O-2 if we want to push the "Test Connection" all the way through on the bench. PR-4 is the gating PR.**

At the top of every task below, the operator-supplied items it requires are listed under "Operator deps:". If empty, the task is fully runnable from a macOS dev machine.

---

## File Structure

### Created (new files)

| Path | Responsibility |
|---|---|
| `can_logger/p0/ifdata_xcp.py` | `IfDataXcp`, `DaqEventInfo`, `DaqProcessorInfo` dataclasses + ASAM 1.6.1 parser of `/begin IF_DATA XCP ... /end IF_DATA` blocks. |
| `mf4_analyzer/acquisition_capture/transport_config.py` | `TransportConfig` frozen dataclass + defaults. |
| `mf4_analyzer/acquisition_capture/daq_map.py` | `OdtEntry` (incl. `address`), `DaqMap` dataclasses + `build_daq_map(selected, ifdata, measurements)` builder. |
| `mf4_analyzer/acquisition_capture/dto_decode.py` | Pure byte-level DTO → `(name, ts, value)` iterator. |
| `mf4_analyzer/acquisition_capture/xcp_daq_session.py` | `XcpDaqSession` orchestrator (lifecycle, command sequencing). Lazy-imports pyxcp. |
| `mf4_analyzer/acquisition_capture/xcp_auth.py` | `unlock_resources_if_needed()` + `XcpAuthError` — seed&key flow gating `RESOURCE.DAQ` (E-5, post-Codex review). |
| `mf4_analyzer/acquisition_capture/vector_hw_probe.py` | `vector_hw_probe(transport)` + `test_xcp_connection(transport, ifdata)` — driver health + real XCP CONNECT/DISCONNECT for Settings → Test Connection (E-4, post-Codex review). |
| `tests/test_ifdata_xcp_parser.py` | Parser tests, 8-10 fixture A2L blocks. |
| `tests/test_daq_map_builder.py` | DaqMap construction tests (event grouping, MAX_DTO packing, granularity). |
| `tests/test_dto_decode.py` | Byte-stream decoding tests (signed/unsigned, big/little, timestamps). |
| `tests/test_xcp_daq_session.py` | Mock-transport lifecycle tests (CONNECT, ALLOC, START, STOP). |
| `tests/test_xcp_auth.py` | Seed&Key flow tests (locked DAQ + no-DLL / missing path / bitness mismatch / happy path / ECU rejects unlock). |
| `tests/test_vector_xcp_backend.py` | End-to-end backend tests with FakeCanBus injected. |
| `tests/test_vector_hw_probe.py` | HW probe + XCP-connection probe tests (mocked vxlapi/DLL + mocked pyxcp Master). |
| `tests/test_transport_config.py` | TransportConfig validation + defaults. |
| `tests/test_config_store_migration.py` | v1→v2 YAML migration round-trip. |
| `tests/fixtures/ifdata_xcp/` | A2L snippets: `classic_can.a2l_snippet`, `can_fd.a2l_snippet`, `multi_event.a2l_snippet`, `vector_dialect.a2l_snippet`, etc. |
| `docs/analyzer/acquisition/runbooks/2026-05-17-stage-8-bench-validation.md` | Step-by-step on-vehicle / HIL acceptance checklist (PR-4). |

### Modified

| Path | What changes |
|---|---|
| `requirements.txt` | Add `python-can[vector]>=4.3.0; sys_platform=='win32'` and `pyxcp>=0.22.0; sys_platform=='win32'`. |
| `mf4_analyzer/acquisition_capture/backends.py` (lines 405-456) | Replace `VectorXcpRecorderBackend` stub body with real implementation that delegates to `XcpDaqSession`. Remove `NotImplementedError` raises. |
| `mf4_analyzer/acquisition_capture/session.py` (lines 49-90) | Add `transport: TransportConfig` field to `SessionConfig`. |
| `mf4_analyzer/acquisition_capture/config_store.py` | Add `"transport"` to `ALLOWED_TOP_LEVEL`; add `_migrate_v1_to_v2()`; load/write transport block. |
| `mf4_analyzer/acquisition_capture/health.py` (lines 202-214) | Replace `_default_hw_probe` with `vector_hw_probe` import; keep macOS fallback. |
| `mf4_analyzer/acquisition_ui/settings_dialog.py` | Add Transport tab (app_name combo, channel, CAN-FD checkbox, bitrates, seed&key path, "Test Connection" button). |
| `mf4_analyzer/acquisition_ui/main_window.py` | Add transport status chip to toolbar; clicking it opens Settings → Transport. |
| `can_logger/p0/a2l_probe.py` (function `load_measurement_summary`) | Wire in `parse_ifdata_xcp()` to fill `event_capacity`, `measurement_events`, `a2l_has_daq_events`, `MeasurementSummary.available_events`. |
| `tests/test_acquisition_a2l_events.py` | Extend with IF_DATA-present cases. |

---

## PR-1: Foundation (Operator deps: none; macOS-only is fine)

### Task 1: Add Windows-conditional dependencies

**Files:**
- Modify: `requirements.txt`

**Operator deps:** none.

- [ ] **Step 1: Append the two Windows-only entries to requirements.txt**

Append at end of file (preserves existing entries):

```text
# Stage 8 — Vector/XCP backend (Windows-only)
python-can[vector]>=4.3.0; sys_platform == "win32"
pyxcp>=0.22.0; sys_platform == "win32"
```

- [ ] **Step 2: Verify macOS install still works**

Run: `pip install -r requirements.txt --dry-run 2>&1 | tail -20`
Expected: no errors; the two windows-only lines are skipped on macOS per PEP 508 marker.

- [ ] **Step 3: Verify Windows-side import is reachable (smoke, not full install)**

Run: `python -c "import sys; sys.platform='win32'; print('marker syntax OK')"`
(This only verifies the requirements.txt parses; full install validated in PR-4 prep.)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps(acquisition): add python-can[vector] and pyxcp as Windows-only requirements"
```

---

### Task 2: `IfDataXcp` dataclass module (no parser yet)

**Files:**
- Create: `can_logger/p0/ifdata_xcp.py`
- Create: `tests/test_ifdata_xcp_parser.py`

**Operator deps:** none.

- [ ] **Step 1: Write the failing test for dataclass shape**

Create `tests/test_ifdata_xcp_parser.py`:

```python
"""Tests for IF_DATA XCP parser and dataclasses."""
from can_logger.p0.ifdata_xcp import (
    IfDataXcp,
    DaqEventInfo,
    DaqProcessorInfo,
)


def test_dataclasses_are_frozen():
    info = DaqEventInfo(
        number=0,
        name="10ms",
        cycle_time_ms=10.0,
        max_odt_entries=8,
        properties=("DAQ",),
    )
    try:
        info.number = 1  # type: ignore[misc]
    except Exception as exc:
        assert "frozen" in str(exc).lower() or isinstance(exc, AttributeError)
    else:
        raise AssertionError("DaqEventInfo should be frozen")


def test_if_data_xcp_carries_all_required_fields():
    proc = DaqProcessorInfo(
        min_daq=0,
        max_event_channel=8,
        granularity_odt_entry_size_daq=1,
        overload_indication="EVENT",
    )
    ifd = IfDataXcp(
        cmd_id=0x500,
        resp_id=0x501,
        cmd_id_extended=False,
        resp_id_extended=False,
        can_fd=False,
        max_cto=8,
        max_dto=8,
        byte_order="MSB_LAST",
        address_granularity="BYTE",
        daq_timestamp_size=2,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
        available_events=(),
        daq_processor=proc,
    )
    assert ifd.cmd_id == 0x500
    assert ifd.daq_processor.min_daq == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ifdata_xcp_parser.py -v`
Expected: FAIL with "No module named 'can_logger.p0.ifdata_xcp'".

- [ ] **Step 3: Create the dataclass module**

Create `can_logger/p0/ifdata_xcp.py`:

```python
"""Structured view of an A2L IF_DATA XCP transport block.

Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md §4.1
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DaqProcessorInfo:
    min_daq: int
    max_event_channel: int
    granularity_odt_entry_size_daq: int
    overload_indication: str  # "EVENT" | "MSB" | "NONE"


@dataclass(frozen=True)
class DaqEventInfo:
    number: int
    name: str
    cycle_time_ms: float  # 0.0 means sporadic
    max_odt_entries: int
    properties: tuple[str, ...]


@dataclass(frozen=True)
class IfDataXcp:
    cmd_id: int
    resp_id: int
    cmd_id_extended: bool
    resp_id_extended: bool
    can_fd: bool
    max_cto: int
    max_dto: int
    byte_order: Literal["MSB_FIRST", "MSB_LAST"]
    address_granularity: Literal["BYTE", "WORD", "DWORD"]
    daq_timestamp_size: int  # 0, 1, 2, or 4
    daq_timestamp_unit: str  # "1NS" | "10NS" | "100NS" | "1US" | "10US" | "100US" | "1MS"
    daq_timestamp_fixed: bool
    available_events: tuple[DaqEventInfo, ...]
    daq_processor: DaqProcessorInfo
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ifdata_xcp_parser.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add can_logger/p0/ifdata_xcp.py tests/test_ifdata_xcp_parser.py
git commit -m "feat(acquisition): add IfDataXcp dataclasses for Stage 8 parser"
```

---

### Task 3: IF_DATA XCP parser — classic CAN single event

**Files:**
- Modify: `can_logger/p0/ifdata_xcp.py`
- Modify: `tests/test_ifdata_xcp_parser.py`
- Create: `tests/fixtures/ifdata_xcp/classic_can.a2l_snippet`

**Operator deps:** none (synthetic fixture).

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/ifdata_xcp/classic_can.a2l_snippet`:

```
/begin IF_DATA XCP
  /begin PROTOCOL_LAYER
    0x0100  /* XCP_PROTOCOL_VERSION */
    100     /* T1 timeout */
    100     /* T2 */
    100     /* T3 */
    100     /* T4 */
    100     /* T5 */
    100     /* T6 */
    100     /* T7 */
    8       /* MAX_CTO */
    8       /* MAX_DTO */
    BYTE_ORDER_MSB_LAST
    ADDRESS_GRANULARITY_BYTE
  /end PROTOCOL_LAYER
  /begin DAQ
    DYNAMIC                 /* DAQ_CONFIG_TYPE */
    0                       /* MAX_DAQ */
    1                       /* MAX_EVENT_CHANNEL */
    0                       /* MIN_DAQ */
    OPTIMISATION_TYPE_DEFAULT
    ADDRESS_EXTENSION_FREE
    IDENTIFICATION_FIELD_TYPE_ABSOLUTE
    GRANULARITY_ODT_ENTRY_SIZE_DAQ_BYTE
    8                       /* MAX_ODT_ENTRY_SIZE_DAQ */
    OVERLOAD_INDICATION_EVENT
    /begin TIMESTAMP_SUPPORTED
      0x0002                /* TIMESTAMP_TICKS */
      SIZE_WORD
      UNIT_1US
      TIMESTAMP_FIXED
    /end TIMESTAMP_SUPPORTED
    /begin EVENT
      "10ms"                /* long name */
      "10ms"                /* short name */
      0                     /* channel number */
      DAQ
      8                     /* max ODT entries */
      10                    /* time cycle */
      6                     /* time unit: 6 = 1ms exponent */
      0                     /* priority */
    /end EVENT
  /end DAQ
  /begin XCP_ON_CAN
    0x0100
    CAN_ID_BROADCAST 0x500
    CAN_ID_MASTER 0x500
    CAN_ID_SLAVE 0x501
    BAUDRATE 500000
  /end XCP_ON_CAN
/end IF_DATA
```

- [ ] **Step 2: Write the failing parser test**

Append to `tests/test_ifdata_xcp_parser.py`:

```python
from pathlib import Path
from can_logger.p0.ifdata_xcp import parse_ifdata_xcp

FIXTURES = Path(__file__).parent / "fixtures" / "ifdata_xcp"


def test_parse_classic_can_single_event():
    text = (FIXTURES / "classic_can.a2l_snippet").read_text()
    blocks = parse_ifdata_xcp(text)
    assert len(blocks) == 1
    ifd = blocks[0]
    assert ifd.cmd_id == 0x500
    assert ifd.resp_id == 0x501
    assert ifd.cmd_id_extended is False
    assert ifd.can_fd is False
    assert ifd.max_cto == 8
    assert ifd.max_dto == 8
    assert ifd.byte_order == "MSB_LAST"
    assert ifd.address_granularity == "BYTE"
    assert ifd.daq_timestamp_size == 2
    assert ifd.daq_timestamp_unit == "1US"
    assert ifd.daq_timestamp_fixed is True
    assert len(ifd.available_events) == 1
    ev = ifd.available_events[0]
    assert ev.number == 0
    assert ev.name == "10ms"
    assert ev.cycle_time_ms == 10.0
    assert ev.max_odt_entries == 8
    assert ev.properties == ("DAQ",)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_ifdata_xcp_parser.py::test_parse_classic_can_single_event -v`
Expected: FAIL with "cannot import name 'parse_ifdata_xcp'".

- [ ] **Step 4: Implement the parser**

Append to `can_logger/p0/ifdata_xcp.py`:

```python
import re
from typing import Iterable


_IFDATA_RE = re.compile(
    r"/begin\s+IF_DATA\s+XCP\b(.*?)/end\s+IF_DATA",
    re.DOTALL,
)

_TIME_UNIT_TOKENS = {
    "UNIT_1NS": "1NS",
    "UNIT_10NS": "10NS",
    "UNIT_100NS": "100NS",
    "UNIT_1US": "1US",
    "UNIT_10US": "10US",
    "UNIT_100US": "100US",
    "UNIT_1MS": "1MS",
}

_TIME_SIZE_TOKENS = {
    "SIZE_BYTE": 1,
    "SIZE_WORD": 2,
    "SIZE_DWORD": 4,
    "NO_TIME_STAMP": 0,
}

_BYTE_ORDER_TOKENS = {
    "BYTE_ORDER_MSB_LAST": "MSB_LAST",
    "BYTE_ORDER_MSB_FIRST": "MSB_FIRST",
}

_GRANULARITY_TOKENS = {
    "ADDRESS_GRANULARITY_BYTE": "BYTE",
    "ADDRESS_GRANULARITY_WORD": "WORD",
    "ADDRESS_GRANULARITY_DWORD": "DWORD",
}

# A2L time-cycle "unit" field is an exponent over 1ns (ASAM):
# 0=1ns, 3=1us, 6=1ms, 9=1s
_TIME_CYCLE_EXPONENT_TO_MS = {
    0: 1e-6,
    1: 1e-5,
    2: 1e-4,
    3: 1e-3,
    4: 1e-2,
    5: 1e-1,
    6: 1.0,
    7: 10.0,
    8: 100.0,
    9: 1000.0,
}


def _strip_comments(text: str) -> str:
    """Remove /* ... */ block comments while preserving line offsets."""
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)


def _tokens(block: str) -> list[str]:
    """Whitespace-split tokens, comments stripped."""
    return _strip_comments(block).split()


def _find_block(block: str, name: str) -> str | None:
    """Find the first /begin <name> ... /end <name> inside block."""
    m = re.search(
        rf"/begin\s+{name}\b(.*?)/end\s+{name}",
        block,
        re.DOTALL,
    )
    return m.group(1) if m else None


def _parse_event(event_block: str) -> DaqEventInfo:
    toks = _tokens(event_block)
    # ASAM EVENT layout (positional):
    #   "long_name" "short_name" channel daq_type max_odt cycle unit priority
    # Quoted strings appear with quotes intact; strip them.
    def _unq(s: str) -> str:
        return s.strip('"')

    long_name = _unq(toks[0])
    # short_name = _unq(toks[1])  # unused
    channel = int(toks[2], 0)
    daq_type = toks[3]
    max_odt_entries = int(toks[4], 0)
    cycle = int(toks[5], 0)
    unit_exp = int(toks[6], 0)
    cycle_time_ms = (
        cycle * _TIME_CYCLE_EXPONENT_TO_MS.get(unit_exp, 1.0)
        if cycle > 0
        else 0.0
    )
    return DaqEventInfo(
        number=channel,
        name=long_name,
        cycle_time_ms=cycle_time_ms,
        max_odt_entries=max_odt_entries,
        properties=(daq_type,),
    )


def _parse_one_block(block: str) -> IfDataXcp:
    # PROTOCOL_LAYER
    pl = _find_block(block, "PROTOCOL_LAYER") or ""
    pl_toks = _tokens(pl)
    # Positional MAX_CTO at index 8 (after the 7 timeouts and version)
    max_cto = int(pl_toks[8], 0) if len(pl_toks) > 8 else 8
    max_dto = int(pl_toks[9], 0) if len(pl_toks) > 9 else 8
    byte_order = "MSB_LAST"
    address_granularity = "BYTE"
    for tok in pl_toks:
        if tok in _BYTE_ORDER_TOKENS:
            byte_order = _BYTE_ORDER_TOKENS[tok]
        if tok in _GRANULARITY_TOKENS:
            address_granularity = _GRANULARITY_TOKENS[tok]

    # DAQ
    daq = _find_block(block, "DAQ") or ""
    daq_toks = _tokens(daq)
    max_event_channel = 0
    min_daq = 0
    granularity_odt = 1
    overload = "NONE"
    if len(daq_toks) >= 3:
        # ASAM DAQ first three positional tokens after DAQ_CONFIG_TYPE:
        # MAX_DAQ MAX_EVENT_CHANNEL MIN_DAQ
        try:
            max_event_channel = int(daq_toks[2], 0)
            min_daq = int(daq_toks[3], 0)
        except (IndexError, ValueError):
            pass
    for tok in daq_toks:
        if tok.startswith("GRANULARITY_ODT_ENTRY_SIZE_DAQ_"):
            granularity_odt = {
                "GRANULARITY_ODT_ENTRY_SIZE_DAQ_BYTE": 1,
                "GRANULARITY_ODT_ENTRY_SIZE_DAQ_WORD": 2,
                "GRANULARITY_ODT_ENTRY_SIZE_DAQ_DWORD": 4,
            }.get(tok, 1)
        if tok.startswith("OVERLOAD_INDICATION_"):
            overload = tok.replace("OVERLOAD_INDICATION_", "")

    # TIMESTAMP_SUPPORTED (inside DAQ)
    ts_block = _find_block(daq, "TIMESTAMP_SUPPORTED") or ""
    ts_size = 0
    ts_unit = "1US"
    ts_fixed = False
    for tok in _tokens(ts_block):
        if tok in _TIME_SIZE_TOKENS:
            ts_size = _TIME_SIZE_TOKENS[tok]
        if tok in _TIME_UNIT_TOKENS:
            ts_unit = _TIME_UNIT_TOKENS[tok]
        if tok == "TIMESTAMP_FIXED":
            ts_fixed = True

    # EVENTs (inside DAQ)
    events = []
    for m in re.finditer(
        r"/begin\s+EVENT\b(.*?)/end\s+EVENT", daq, re.DOTALL
    ):
        events.append(_parse_event(m.group(1)))

    # XCP_ON_CAN or XCP_ON_CAN_FD
    can_fd = _find_block(block, "XCP_ON_CAN_FD") is not None
    transport = _find_block(block, "XCP_ON_CAN_FD") or _find_block(
        block, "XCP_ON_CAN"
    ) or ""
    cmd_id = 0
    resp_id = 0
    cmd_ext = False
    resp_ext = False
    transport_toks = _tokens(transport)
    i = 0
    while i < len(transport_toks):
        t = transport_toks[i]
        if t == "CAN_ID_MASTER" and i + 1 < len(transport_toks):
            v = transport_toks[i + 1]
            cmd_id = int(v, 0)
            cmd_ext = cmd_id > 0x7FF
            i += 2
            continue
        if t == "CAN_ID_SLAVE" and i + 1 < len(transport_toks):
            v = transport_toks[i + 1]
            resp_id = int(v, 0)
            resp_ext = resp_id > 0x7FF
            i += 2
            continue
        i += 1

    return IfDataXcp(
        cmd_id=cmd_id,
        resp_id=resp_id,
        cmd_id_extended=cmd_ext,
        resp_id_extended=resp_ext,
        can_fd=can_fd,
        max_cto=max_cto,
        max_dto=max_dto,
        byte_order=byte_order,
        address_granularity=address_granularity,
        daq_timestamp_size=ts_size,
        daq_timestamp_unit=ts_unit,
        daq_timestamp_fixed=ts_fixed,
        available_events=tuple(events),
        daq_processor=DaqProcessorInfo(
            min_daq=min_daq,
            max_event_channel=max_event_channel,
            granularity_odt_entry_size_daq=granularity_odt,
            overload_indication=overload,
        ),
    )


def parse_ifdata_xcp(a2l_text: str) -> list[IfDataXcp]:
    """Parse every /begin IF_DATA XCP ... /end IF_DATA block in the text.

    Returns one IfDataXcp per block (most A2Ls have exactly one)."""
    blocks: list[IfDataXcp] = []
    for m in _IFDATA_RE.finditer(a2l_text):
        blocks.append(_parse_one_block(m.group(1)))
    return blocks
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_ifdata_xcp_parser.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add can_logger/p0/ifdata_xcp.py tests/test_ifdata_xcp_parser.py tests/fixtures/ifdata_xcp/
git commit -m "feat(acquisition): IF_DATA XCP parser for classic CAN single event"
```

---

### Task 4: IF_DATA XCP parser — CAN-FD, multi-event, dialect tolerance

**Files:**
- Create: `tests/fixtures/ifdata_xcp/can_fd.a2l_snippet`
- Create: `tests/fixtures/ifdata_xcp/multi_event.a2l_snippet`
- Create: `tests/fixtures/ifdata_xcp/no_timestamp.a2l_snippet`
- Modify: `tests/test_ifdata_xcp_parser.py`
- Modify: `can_logger/p0/ifdata_xcp.py` (only if test failures expose missing token aliases)

**Operator deps:** none.

- [ ] **Step 1: Create CAN-FD fixture**

Create `tests/fixtures/ifdata_xcp/can_fd.a2l_snippet`:

```
/begin IF_DATA XCP
  /begin PROTOCOL_LAYER
    0x0103
    100 100 100 100 100 100 100
    64      /* MAX_CTO — CAN-FD permits up to 64 */
    64      /* MAX_DTO */
    BYTE_ORDER_MSB_LAST
    ADDRESS_GRANULARITY_BYTE
  /end PROTOCOL_LAYER
  /begin DAQ
    DYNAMIC 0 2 0
    OPTIMISATION_TYPE_DEFAULT
    GRANULARITY_ODT_ENTRY_SIZE_DAQ_BYTE
    8
    OVERLOAD_INDICATION_EVENT
    /begin TIMESTAMP_SUPPORTED
      0x0002 SIZE_DWORD UNIT_1NS TIMESTAMP_FIXED
    /end TIMESTAMP_SUPPORTED
    /begin EVENT "10ms" "10ms" 0 DAQ 16 10 6 0 /end EVENT
  /end DAQ
  /begin XCP_ON_CAN_FD
    0x0103
    CAN_ID_MASTER 0x18FF0500
    CAN_ID_SLAVE  0x18FF0501
    BAUDRATE 500000
    CAN_FD_DATA_TRANSFER_BAUDRATE 2000000
    SAMPLE_POINT 75
    SAMPLE_POINT_DATA 70
  /end XCP_ON_CAN_FD
/end IF_DATA
```

- [ ] **Step 2: Create multi-event fixture**

Create `tests/fixtures/ifdata_xcp/multi_event.a2l_snippet`:

```
/begin IF_DATA XCP
  /begin PROTOCOL_LAYER
    0x0100
    100 100 100 100 100 100 100
    8 8
    BYTE_ORDER_MSB_LAST
    ADDRESS_GRANULARITY_BYTE
  /end PROTOCOL_LAYER
  /begin DAQ
    DYNAMIC 0 3 0
    GRANULARITY_ODT_ENTRY_SIZE_DAQ_BYTE
    8
    OVERLOAD_INDICATION_EVENT
    /begin TIMESTAMP_SUPPORTED
      0x0002 SIZE_WORD UNIT_1US TIMESTAMP_FIXED
    /end TIMESTAMP_SUPPORTED
    /begin EVENT "10ms"  "10ms"  0 DAQ 8 10  6 0 /end EVENT
    /begin EVENT "100ms" "100ms" 1 DAQ 8 100 6 0 /end EVENT
    /begin EVENT "1s"    "1s"    2 DAQ 4 1   9 0 /end EVENT
  /end DAQ
  /begin XCP_ON_CAN
    0x0100
    CAN_ID_MASTER 0x500
    CAN_ID_SLAVE 0x501
    BAUDRATE 500000
  /end XCP_ON_CAN
/end IF_DATA
```

- [ ] **Step 3: Create no-timestamp fixture**

Create `tests/fixtures/ifdata_xcp/no_timestamp.a2l_snippet`:

```
/begin IF_DATA XCP
  /begin PROTOCOL_LAYER
    0x0100
    100 100 100 100 100 100 100
    8 8
    BYTE_ORDER_MSB_FIRST
    ADDRESS_GRANULARITY_BYTE
  /end PROTOCOL_LAYER
  /begin DAQ
    DYNAMIC 0 1 0
    GRANULARITY_ODT_ENTRY_SIZE_DAQ_BYTE
    8
    OVERLOAD_INDICATION_NONE
    /begin TIMESTAMP_SUPPORTED
      0x0000 NO_TIME_STAMP UNIT_1US
    /end TIMESTAMP_SUPPORTED
    /begin EVENT "1ms" "1ms" 0 DAQ 8 1 6 0 /end EVENT
  /end DAQ
  /begin XCP_ON_CAN
    0x0100
    CAN_ID_MASTER 0x600
    CAN_ID_SLAVE 0x601
    BAUDRATE 1000000
  /end XCP_ON_CAN
/end IF_DATA
```

- [ ] **Step 4: Write the failing tests**

Append to `tests/test_ifdata_xcp_parser.py`:

```python
def test_parse_can_fd():
    text = (FIXTURES / "can_fd.a2l_snippet").read_text()
    ifd = parse_ifdata_xcp(text)[0]
    assert ifd.can_fd is True
    assert ifd.max_cto == 64
    assert ifd.max_dto == 64
    assert ifd.cmd_id == 0x18FF0500
    assert ifd.cmd_id_extended is True
    assert ifd.resp_id == 0x18FF0501
    assert ifd.resp_id_extended is True
    assert ifd.daq_timestamp_size == 4
    assert ifd.daq_timestamp_unit == "1NS"


def test_parse_multi_event():
    text = (FIXTURES / "multi_event.a2l_snippet").read_text()
    ifd = parse_ifdata_xcp(text)[0]
    assert len(ifd.available_events) == 3
    names = [e.name for e in ifd.available_events]
    assert names == ["10ms", "100ms", "1s"]
    cycles = [e.cycle_time_ms for e in ifd.available_events]
    assert cycles == [10.0, 100.0, 1000.0]


def test_parse_no_timestamp_big_endian():
    text = (FIXTURES / "no_timestamp.a2l_snippet").read_text()
    ifd = parse_ifdata_xcp(text)[0]
    assert ifd.daq_timestamp_size == 0
    assert ifd.byte_order == "MSB_FIRST"
    assert ifd.daq_processor.overload_indication == "NONE"
    assert ifd.available_events[0].cycle_time_ms == 1.0
```

- [ ] **Step 5: Run tests; expect mixed results**

Run: `pytest tests/test_ifdata_xcp_parser.py -v`
Expected: most pass, but watch for any FAIL — if a token alias is missing in the parser, add it to the appropriate `_*_TOKENS` dict in `ifdata_xcp.py` and re-run. **Do NOT modify the test to make it pass; modify the parser.**

- [ ] **Step 6: Once all green, commit**

```bash
git add tests/fixtures/ifdata_xcp/ tests/test_ifdata_xcp_parser.py can_logger/p0/ifdata_xcp.py
git commit -m "feat(acquisition): IF_DATA XCP parser handles CAN-FD, multi-event, no-timestamp"
```

---

### Task 5: Wire IF_DATA parser into `a2l_probe.load_measurement_summary`

**Files:**
- Modify: `can_logger/p0/a2l_probe.py`
- Modify: `tests/test_acquisition_a2l_events.py`

**Operator deps:** none (synthetic A2L test data only).

- [ ] **Step 1: Read current a2l_probe.py to see exact insertion point**

Run: `cat can_logger/p0/a2l_probe.py`
Note the function `load_measurement_summary` at line 71 — it currently sets `event_capacity={}, measurement_events={}, a2l_has_daq_events=False`.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_acquisition_a2l_events.py` (or add as new method):

```python
def test_load_measurement_summary_fills_events_when_ifdata_present(tmp_path):
    """If the A2L body contains an IF_DATA XCP DAQ block, the summary
    must expose event capacity and DAQ flag."""
    from can_logger.p0.a2l_probe import load_measurement_summary
    # Use a real A2L if available in tests/fixtures/a2l/. If absent, skip.
    import pytest
    fixture = Path(__file__).parent / "fixtures" / "a2l" / "with_daq.a2l"
    if not fixture.exists():
        pytest.skip("No A2L fixture with DAQ available; supplied via O-1")
    summary = load_measurement_summary(str(fixture), limit=5)
    assert summary.a2l_has_daq_events is True
    assert len(summary.event_capacity) >= 1
```

(This real-A2L test is conditional on O-1; the **non-skipped** synthetic
test in Step 3 below covers the E-1 contract so PR-2 can rely on the
fields being populated.)

- [ ] **Step 2b: Write the failing non-skipped test for per-MEASUREMENT IF_DATA (v2, post-E-1 fix)**

This test does NOT depend on O-1 — it builds a minimal A2L on disk with
both a top-level `IF_DATA XCP` and a per-`MEASUREMENT` `IF_DATA XCP
DAQ_EVENT FIXED_EVENT_LIST` block. It must fail before Step 4's
implementation and pass after.

Append to `tests/test_acquisition_a2l_events.py`:

```python
def test_load_measurement_summary_associates_measurements_to_events(tmp_path):
    """E-1: MeasurementSummary.available_events and
    A2LSummary.measurement_events MUST be populated when MEASUREMENT
    blocks carry IF_DATA XCP DAQ_EVENT FIXED_EVENT_LIST entries.
    Without this, LeftPane.current_selection() produces event=None and
    XcpDaqSession.start() cannot group selections."""
    from can_logger.p0.a2l_probe import load_measurement_summary
    a2l = tmp_path / "mini.a2l"
    a2l.write_text(
        "/begin PROJECT P \"\"\n"
        "  /begin MODULE M \"\"\n"
        "    /begin MEASUREMENT EngineSpeed \"\"\n"
        "      UWORD NO_COMPU_METHOD 0 0 0 65535\n"
        "      ECU_ADDRESS 0x1000\n"
        "      /begin IF_DATA XCP\n"
        "        /begin DAQ_EVENT FIXED_EVENT_LIST\n"
        "          EVENT 0\n"
        "        /end DAQ_EVENT\n"
        "      /end IF_DATA\n"
        "    /end MEASUREMENT\n"
        "    /begin IF_DATA XCP\n"
        "      /begin DAQ\n"
        "        /begin EVENT \"event_10ms\" \"ev10\" 0 DAQ 0xFF 10 1 0\n"
        "        /end EVENT\n"
        "      /end DAQ\n"
        "    /end IF_DATA\n"
        "  /end MODULE\n"
        "/end PROJECT\n",
        encoding="latin-1",
    )
    summary = load_measurement_summary(str(a2l), limit=5)
    # E-1 contract checks:
    assert summary.a2l_has_daq_events is True
    assert "event_10ms" in summary.event_capacity
    assert summary.measurement_events.get("EngineSpeed") == ("event_10ms",)
    eng = next(m for m in summary.measurements if m.name == "EngineSpeed")
    assert eng.available_events == ("event_10ms",)
```

If pya2l fails to parse the minimal stub (it sometimes requires
`/begin HEADER ... /end HEADER` or a PROJECT version line), the
implementation in Step 4 may need to fall back to a raw-text parse for
the per-MEASUREMENT IF_DATA blocks. Either path is acceptable as long
as this test passes.

- [ ] **Step 3: Add the non-conditional unit-level test (mock A2L text)**

Append:

```python
def test_a2l_probe_parses_ifdata_from_raw_text(tmp_path):
    """Even without pya2l, the IF_DATA parser pulls events from raw text."""
    snippet = (
        Path(__file__).parent / "fixtures" / "ifdata_xcp" / "multi_event.a2l_snippet"
    ).read_text()
    # Wrap snippet in minimal A2L outer scaffold
    a2l_path = tmp_path / "fake.a2l"
    a2l_path.write_text(
        "/begin PROJECT P /begin MODULE M\n"
        + snippet
        + "\n/end MODULE /end PROJECT\n"
    )

    from can_logger.p0.ifdata_xcp import parse_ifdata_xcp
    blocks = parse_ifdata_xcp(a2l_path.read_text())
    assert len(blocks) == 1
    assert len(blocks[0].available_events) == 3
```

- [ ] **Step 4: Modify `load_measurement_summary` to fill the event fields**

In `can_logger/p0/a2l_probe.py`, replace the `return A2LSummary(...)` block at the end of the function with:

```python
    finally:
        db.close()

    # Stage 8: walk IF_DATA XCP for DAQ event capacity.
    try:
        raw_text = path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        raw_text = ""
    from can_logger.p0.ifdata_xcp import parse_ifdata_xcp
    ifdata_blocks = parse_ifdata_xcp(raw_text)

    event_capacity: dict[str, int] = {}
    has_daq = False
    if ifdata_blocks:
        primary = ifdata_blocks[0]
        for ev in primary.available_events:
            event_capacity[ev.name] = ev.max_odt_entries
        has_daq = bool(primary.available_events)

    # Stage 8 v2 (E-1 fix): per-MEASUREMENT IF_DATA walk so that
    # MeasurementSummary.available_events and
    # A2LSummary.measurement_events are populated. This is the contract
    # XcpDaqSession.start() relies on for event grouping.
    from can_logger.p0.ifdata_xcp import parse_measurement_events
    measurement_events: dict[str, tuple[str, ...]] = (
        parse_measurement_events(raw_text)
    )
    # Mount the lookup onto each MeasurementSummary so the cockpit
    # LeftPane can read it directly.
    measurements = [
        replace(m, available_events=measurement_events.get(m.name, ()))
        for m in measurements
    ]

    return A2LSummary(
        path=str(path),
        total_measurements=total,
        measurements=measurements,
        event_capacity=event_capacity,
        measurement_events=measurement_events,
        a2l_has_daq_events=has_daq,
    )
```

The above uses `dataclasses.replace` to rewrite `available_events` on
each `MeasurementSummary` (the dataclass is frozen). Add
`from dataclasses import replace` at the top of `a2l_probe.py` if not
present.

`parse_measurement_events(raw_text)` is a NEW helper in
`can_logger/p0/ifdata_xcp.py`. Contract:

```python
def parse_measurement_events(a2l_text: str) -> Mapping[str, tuple[str, ...]]:
    """Walk MEASUREMENT blocks for IF_DATA XCP DAQ_EVENT
    FIXED_EVENT_LIST / AVAILABLE_EVENT_LIST and return
    measurement_name -> tuple of event names compatible with it.
    Resolves EVENT <n> references against the module-level
    IF_DATA XCP DAQ EVENT list (positional).
    Empty mapping if no MEASUREMENT carries IF_DATA XCP."""
```

Implementation uses regex over `/begin MEASUREMENT <name>` …
`/end MEASUREMENT` spans, then within each span finds
`FIXED_EVENT_LIST` and pulls every `EVENT <n>` integer, translating
each to the n-th event name from the module-level DAQ event list. A
unit test for `parse_measurement_events` belongs in
`tests/test_ifdata_xcp_parser.py` and is split from the
load_measurement_summary integration test above.

- [ ] **Step 5: Run all acquisition tests**

Run: `pytest tests/test_acquisition_a2l_events.py tests/test_ifdata_xcp_parser.py -v`
Expected: all pass (the `with_daq.a2l` test is skipped until O-1).

- [ ] **Step 6: Commit**

```bash
git add can_logger/p0/a2l_probe.py tests/test_acquisition_a2l_events.py
git commit -m "feat(acquisition): a2l_probe fills DAQ event capacity from IF_DATA"
```

---

### Task 6: `TransportConfig` dataclass + tests

**Files:**
- Create: `mf4_analyzer/acquisition_capture/transport_config.py`
- Create: `tests/test_transport_config.py`

**Operator deps:** none.

- [ ] **Step 1: Write the failing test**

Create `tests/test_transport_config.py`:

```python
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig


def test_defaults():
    tc = TransportConfig()
    assert tc.app_name == "Python"
    assert tc.channel == 0
    assert tc.can_fd is False
    assert tc.bitrate == 500_000
    assert tc.data_bitrate == 2_000_000
    assert tc.sample_point == 75.0
    assert tc.fd_sample_point == 70.0
    assert tc.timeout_s == 1.0
    assert tc.seed_and_key_dll is None


def test_frozen():
    tc = TransportConfig()
    import dataclasses
    assert dataclasses.is_dataclass(tc)
    try:
        tc.channel = 1  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("TransportConfig must be frozen")


def test_from_dict_round_trip():
    src = {
        "app_name": "CANalyzer",
        "channel": 1,
        "can_fd": True,
        "bitrate": 1_000_000,
        "data_bitrate": 4_000_000,
    }
    tc = TransportConfig.from_dict(src)
    assert tc.app_name == "CANalyzer"
    assert tc.can_fd is True
    assert tc.bitrate == 1_000_000
    d = tc.to_dict()
    for k, v in src.items():
        assert d[k] == v
```

- [ ] **Step 2: Run; expect import failure**

Run: `pytest tests/test_transport_config.py -v`
Expected: FAIL with "No module named 'mf4_analyzer.acquisition_capture.transport_config'".

- [ ] **Step 3: Implement**

Create `mf4_analyzer/acquisition_capture/transport_config.py`:

```python
"""TransportConfig: Vector/CAN transport parameters for Stage 8 backend.

Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md §4.3
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping


@dataclass(frozen=True)
class TransportConfig:
    app_name: str = "Python"
    channel: int = 0
    can_fd: bool = False
    bitrate: int = 500_000
    data_bitrate: int = 2_000_000
    sample_point: float = 75.0
    fd_sample_point: float = 70.0
    timeout_s: float = 1.0
    seed_and_key_dll: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransportConfig":
        known = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_transport_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_capture/transport_config.py tests/test_transport_config.py
git commit -m "feat(acquisition): add TransportConfig dataclass for Stage 8"
```

---

### Task 7: Wire TransportConfig into SessionConfig + config_store migration v1→v2

**Files:**
- Modify: `mf4_analyzer/acquisition_capture/session.py`
- Modify: `mf4_analyzer/acquisition_capture/config_store.py`
- Create: `tests/test_config_store_migration.py`

**Operator deps:** none.

- [ ] **Step 1: Add `transport` field to SessionConfig**

In `mf4_analyzer/acquisition_capture/session.py`, add to the imports:

```python
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
```

In the `SessionConfig` class definition, add a field (preserve alphabetical or end-of-list placement to match existing style):

```python
    transport: TransportConfig = field(default_factory=TransportConfig)
```

- [ ] **Step 2: Write the failing migration test**

Create `tests/test_config_store_migration.py`:

```python
from pathlib import Path

from mf4_analyzer.acquisition_capture.config_store import (
    ConfigStore,
    CONFIG_VERSION,
)


def test_v1_config_loads_with_default_transport(tmp_path):
    """A v1 acquisition_config.yaml on disk should load cleanly under v2
    by injecting default transport values."""
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        "version: 1\n"
        'a2l_path: "fake.a2l"\n'
        "favorites: []\n"
        "selection: []\n"
    )
    store = ConfigStore.load(cfg)
    assert store.transport.app_name == "Python"
    assert store.transport.bitrate == 500_000
    assert store.version == CONFIG_VERSION  # now 2


def test_v2_config_round_trip(tmp_path):
    cfg = tmp_path / "acquisition_config.yaml"
    cfg.write_text(
        "version: 2\n"
        'a2l_path: "fake.a2l"\n'
        "favorites: []\n"
        "selection: []\n"
        "transport:\n"
        '  app_name: "CANalyzer"\n'
        "  channel: 1\n"
        "  can_fd: true\n"
        "  bitrate: 1000000\n"
    )
    store = ConfigStore.load(cfg)
    assert store.transport.app_name == "CANalyzer"
    assert store.transport.can_fd is True
    assert store.transport.bitrate == 1_000_000


def test_save_then_load_preserves_transport(tmp_path):
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    cfg = tmp_path / "acquisition_config.yaml"
    store = ConfigStore(
        path=cfg,
        a2l_path="x.a2l",
        favorites=[],
        selection=[],
        transport=TransportConfig(app_name="CANoe", channel=2, can_fd=True),
    )
    store.save()
    reloaded = ConfigStore.load(cfg)
    assert reloaded.transport.app_name == "CANoe"
    assert reloaded.transport.channel == 2
    assert reloaded.transport.can_fd is True
```

- [ ] **Step 3: Run; expect failures**

Run: `pytest tests/test_config_store_migration.py -v`
Expected: 3 failures (transport field doesn't exist, migration not present).

- [ ] **Step 4: Implement migration in config_store.py**

In `mf4_analyzer/acquisition_capture/config_store.py`:

1. Add to imports:
   ```python
   from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
   ```
2. Bump `CONFIG_VERSION` from `1` to `2`.
3. Add `"transport"` to the `ALLOWED_TOP_LEVEL` frozenset.
4. Add a `transport: TransportConfig` field to the `ConfigStore` dataclass with `field(default_factory=TransportConfig)`.
5. In `_load_config_file()` (or wherever parsed dict → `ConfigStore` mapping happens), add migration:
   ```python
   parsed_version = int(parsed.get("version", 1))
   if parsed_version < 2:
       parsed["version"] = 2
       parsed.setdefault("transport", TransportConfig().to_dict())
   transport_dict = parsed.get("transport") or {}
   transport = TransportConfig.from_dict(transport_dict)
   ```
6. Pass `transport=transport` to the `ConfigStore(...)` constructor call.
7. In `_write_config_file()` / `save()`, serialize `self.transport.to_dict()` under the `"transport:"` YAML key. Honor existing hand-rolled YAML format (whitelist allowed keys).

(Exact line numbers depend on current config_store.py; the engineer reads the file first and adapts.)

- [ ] **Step 5: Run all config tests**

Run: `pytest tests/test_acquisition_config_store.py tests/test_config_store_migration.py -v`
Expected: all pass, including existing v1 tests (migration is non-destructive).

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/acquisition_capture/session.py mf4_analyzer/acquisition_capture/config_store.py tests/test_config_store_migration.py
git commit -m "feat(acquisition): config_store v1→v2 migration adds transport block"
```

---

### Task 8: PR-1 wrap-up

- [ ] **Step 1: Run the full acquisition test suite**

Run: `pytest tests/test_acquisition* tests/test_ifdata_xcp_parser.py tests/test_transport_config.py tests/test_config_store_migration.py -v`
Expected: all green, no skips except `with_daq.a2l` fixture-dependent test (O-1).

- [ ] **Step 2: Verify no regressions in cockpit smoke**

Run: `python -m mf4_analyzer.acquisition_ui --demo --backend fake --headless`
(Exit cleanly after 2 s with the existing smoke script.)
Expected: no crashes; transport field is auto-defaulted.

- [ ] **Step 3: Open PR**

```bash
git push -u origin HEAD
gh pr create --title "Stage 8a: foundation — IF_DATA XCP parser + transport config" \
  --body "$(cat <<'EOF'
## Summary
- Parses A2L IF_DATA XCP transport blocks into structured dataclasses
- Adds TransportConfig with persistence v1→v2 migration
- Fills a2l_probe DAQ event capacity from real IF_DATA

## Open items (operator)
- O-1 real A2L fixture: PR-1 ships without; future PRs benefit
- Subsequent PRs (8b/c/d) are unblocked

## Test plan
- [x] pytest tests/test_ifdata_xcp_parser.py
- [x] pytest tests/test_transport_config.py
- [x] pytest tests/test_config_store_migration.py
- [x] no regression in tests/test_acquisition_*
EOF
)"
```

---

## PR-2: Backend Core (Operator deps: O-1 helpful but not required)

### Task 9: `DaqMap` dataclasses + `build_daq_map` builder

**Files:**
- Create: `mf4_analyzer/acquisition_capture/daq_map.py`
- Create: `tests/test_daq_map_builder.py`

**Operator deps:** none (synthetic `SelectedMeasurement` + `IfDataXcp` only).

- [ ] **Step 1: Write the failing test**

Create `tests/test_daq_map_builder.py`:

```python
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.daq_map import (
    OdtEntry,
    DaqMap,
    build_daq_map,
)
from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import (
    IfDataXcp,
    DaqEventInfo,
    DaqProcessorInfo,
)


def _ifdata(max_dto=8, ts_size=2, events=(("10ms", 8),)):
    return IfDataXcp(
        cmd_id=0x500, resp_id=0x501,
        cmd_id_extended=False, resp_id_extended=False,
        can_fd=False, max_cto=8, max_dto=max_dto,
        byte_order="MSB_LAST", address_granularity="BYTE",
        daq_timestamp_size=ts_size, daq_timestamp_unit="1US",
        daq_timestamp_fixed=True,
        available_events=tuple(
            DaqEventInfo(
                number=i, name=name, cycle_time_ms=10.0,
                max_odt_entries=cap, properties=("DAQ",),
            )
            for i, (name, cap) in enumerate(events)
        ),
        daq_processor=DaqProcessorInfo(
            min_daq=0, max_event_channel=len(events),
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )


# E-2 fix (v2): SelectedMeasurement at session.py:24-45 has neither
# `datatype` nor `size_bytes`. Tests construct it with only the live
# fields, and feed the A2L per-measurement lookup as a separate arg.
def _sel(name, addr, event, *, event_rate_hz=100.0, payload_bytes=2):
    return SelectedMeasurement(
        name=name,
        address_hex=f"0x{addr:08X}",
        event=event,
        event_rate_hz=event_rate_hz,
        payload_bytes=payload_bytes,
    )


def _meas(name, addr, datatype="UWORD"):
    return MeasurementSummary(
        name=name, address=addr, datatype=datatype,
        unit="", conversion="",
    )


def _measurements(*items):
    """items: iterable of (name, addr [, datatype]) tuples."""
    out = {}
    for it in items:
        if len(it) == 2:
            name, addr = it
            datatype = "UWORD"
        else:
            name, addr, datatype = it
        out[name] = _meas(name, addr, datatype)
    return out


def test_single_event_three_measurements_pack_one_odt():
    selected = (
        _sel("a", 0x1000, "10ms"),
        _sel("b", 0x1002, "10ms"),
        _sel("c", 0x1004, "10ms"),
    )
    meas = _measurements(("a", 0x1000), ("b", 0x1002), ("c", 0x1004))
    m = build_daq_map(selected, _ifdata(), meas)
    # 1 daq list, 1 odt, 3 entries; offsets: 1(pid)+2(ts)=3, 5, 7
    assert set(m.pid_to_odt.keys()) == {0}
    daq_list_count = len({d for d, _ in m.entries.keys()})
    assert daq_list_count == 1
    entries = m.entries[(0, 0)]
    assert [e.measurement_name for e in entries] == ["a", "b", "c"]
    assert entries[0].offset == 3  # after pid(1) + ts(2)
    assert entries[1].offset == 5
    assert entries[2].offset == 7
    # E-2: address sourced from sel.address_hex, datatype from meas.
    assert entries[0].address == 0x1000
    assert entries[0].datatype == "UWORD"


def test_multi_event_groups_into_separate_daq_lists():
    selected = (
        _sel("a", 0x1000, "10ms"),
        _sel("b", 0x2000, "100ms"),
    )
    meas = _measurements(("a", 0x1000), ("b", 0x2000))
    ifd = _ifdata(events=(("10ms", 8), ("100ms", 8)))
    m = build_daq_map(selected, ifd, meas)
    assert len(m.event_for_daq) == 2
    # Two distinct daq lists, one per event
    daq_lists = sorted({d for d, _ in m.entries.keys()})
    assert daq_lists == [0, 1]


def test_too_many_measurements_for_one_odt_spills_to_second_odt():
    # MAX_DTO=8 → payload after pid(1)+ts(2)=5 bytes; 4 measurements at 2 bytes
    # = 8 bytes needed → spill the 4th to ODT 1.
    selected = tuple(
        _sel(chr(ord('a') + i), 0x1000 + i * 2, "10ms")
        for i in range(4)
    )
    meas = _measurements(*((chr(ord('a') + i), 0x1000 + i * 2) for i in range(4)))
    m = build_daq_map(selected, _ifdata(max_dto=8), meas)
    # ODT0 holds first 2 measurements (4 bytes), ODT1 holds the rest
    odt0 = m.entries[(0, 0)]
    odt1 = m.entries[(0, 1)]
    assert len(odt0) + len(odt1) == 4
    # Each ODT's used payload ≤ MAX_DTO - PID - timestamp
    payload_budget = 8 - 1 - 2
    assert sum(e.size for e in odt0) <= payload_budget
    assert sum(e.size for e in odt1) <= payload_budget


def test_build_daq_map_raises_when_measurement_lookup_missing():
    """E-2: builder must not silently fall back to payload_bytes for
    datatype — DTO decoding would emit garbage. Raise clearly."""
    import pytest
    selected = (_sel("ghost", 0x1000, "10ms"),)
    with pytest.raises(ValueError, match="not in A2L summary"):
        build_daq_map(selected, _ifdata(), {})
```

- [ ] **Step 2: Run; expect import failure**

Run: `pytest tests/test_daq_map_builder.py -v`
Expected: FAIL with "No module named '...daq_map'".

- [ ] **Step 3: Implement the builder**

Create `mf4_analyzer/acquisition_capture/daq_map.py`:

```python
"""DaqMap: runtime mapping of selected measurements to DAQ list / ODT slots.

Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md §4.2
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import IfDataXcp
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement


@dataclass(frozen=True)
class OdtEntry:
    measurement_name: str
    offset: int
    size: int
    datatype: str
    address: int          # E-2 fix: address comes from sel.address_hex
    scale_a: float = 1.0
    scale_b: float = 0.0


@dataclass(frozen=True)
class DaqMap:
    pid_to_odt: Mapping[int, tuple[int, int]]
    entries: Mapping[tuple[int, int], tuple[OdtEntry, ...]]
    event_for_daq: Mapping[int, int]


# Canonical A2L datatype tokens → bytes. ASAM AML 1.6.1 §3.5 spells
# `UBYTE/SBYTE/UWORD/SWORD/ULONG/SLONG/A_UINT64/A_INT64/FLOAT32_IEEE/FLOAT64_IEEE`.
# Lowercase aliases (`u8`..`f64`) are kept for the IfDataXcp parser side.
_DATATYPE_SIZE: dict[str, int] = {
    "UBYTE": 1, "SBYTE": 1,
    "UWORD": 2, "SWORD": 2,
    "ULONG": 4, "SLONG": 4,
    "A_UINT64": 8, "A_INT64": 8,
    "FLOAT32_IEEE": 4, "FLOAT64_IEEE": 8,
    "u8": 1, "s8": 1,
    "u16": 2, "s16": 2,
    "u32": 4, "s32": 4, "f32": 4,
    "u64": 8, "s64": 8, "f64": 8,
}


def _size_from_datatype(datatype: str, payload_bytes_fallback: int) -> int:
    return _DATATYPE_SIZE.get(datatype, payload_bytes_fallback)


def build_daq_map(
    selected: Sequence[SelectedMeasurement],
    ifdata: IfDataXcp,
    measurements: Mapping[str, MeasurementSummary],
) -> DaqMap:
    """Group selected measurements by event; pack each event's
    measurements into ODTs honoring MAX_DTO.

    E-2 (v2): `measurements` is the A2L per-name lookup so we can
    resolve datatype/size without adding fields to SelectedMeasurement
    (a load-bearing public dataclass with serialization contracts).
    """
    # Header overhead: 1 byte PID + timestamp bytes
    overhead = 1 + ifdata.daq_timestamp_size
    odt_payload_budget = ifdata.max_dto - overhead
    if odt_payload_budget <= 0:
        raise ValueError(
            f"MAX_DTO={ifdata.max_dto} too small for PID + timestamp "
            f"({overhead} bytes overhead)"
        )

    # E-2: surface missing-lookup early — DTO decode would be garbage.
    for sel in selected:
        if sel.name not in measurements:
            raise ValueError(
                f"measurement {sel.name!r} not in A2L summary; "
                "cannot build DAQ map"
            )

    # Group by event name. E-1: `sel.event` is sourced from
    # MeasurementSummary.available_events[0] by LeftPane; if that field
    # is empty, the planner will land here with event=None — we surface
    # it as a clear error rather than collapsing to "" silently.
    by_event: dict[str, list[SelectedMeasurement]] = {}
    for sel in selected:
        if not sel.event:
            raise ValueError(
                f"measurement {sel.name!r} has no event assigned; "
                "A2L per-MEASUREMENT IF_DATA likely missing"
            )
        by_event.setdefault(sel.event, []).append(sel)

    # Look up event channel number from ifdata
    event_number_by_name = {
        e.name: e.number for e in ifdata.available_events
    }

    pid_to_odt: dict[int, tuple[int, int]] = {}
    entries: dict[tuple[int, int], tuple[OdtEntry, ...]] = {}
    event_for_daq: dict[int, int] = {}

    next_pid = 0
    next_daq = 0

    for ev_name, sels in by_event.items():
        if ev_name not in event_number_by_name:
            raise ValueError(f"Selected event {ev_name!r} not in A2L IF_DATA")
        daq_list = next_daq
        next_daq += 1
        event_for_daq[daq_list] = event_number_by_name[ev_name]

        # Pack measurements into ODTs greedily within budget
        odt_index = 0
        cur_offset = overhead
        cur_entries: list[OdtEntry] = []

        def _flush() -> None:
            nonlocal odt_index, cur_offset, cur_entries, next_pid
            if cur_entries:
                entries[(daq_list, odt_index)] = tuple(cur_entries)
                pid_to_odt[next_pid] = (daq_list, odt_index)
                next_pid += 1
                odt_index += 1
                cur_offset = overhead
                cur_entries = []

        for sel in sels:
            meas = measurements[sel.name]
            datatype = meas.datatype or ""
            size = _size_from_datatype(datatype, sel.payload_bytes)
            address = (
                int(sel.address_hex, 16) if sel.address_hex else meas.address
            )
            if cur_offset + size - overhead > odt_payload_budget:
                _flush()
            cur_entries.append(OdtEntry(
                measurement_name=sel.name,
                offset=cur_offset,
                size=size,
                datatype=datatype,
                address=address,
                scale_a=1.0,
                scale_b=0.0,
            ))
            cur_offset += size
        _flush()

    return DaqMap(
        pid_to_odt=pid_to_odt,
        entries=entries,
        event_for_daq=event_for_daq,
    )
```

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/test_daq_map_builder.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_capture/daq_map.py tests/test_daq_map_builder.py
git commit -m "feat(acquisition): build_daq_map groups measurements by event and packs ODTs"
```

---

### Task 10: `dto_decode` — pure byte-level DTO parser

**Files:**
- Create: `mf4_analyzer/acquisition_capture/dto_decode.py`
- Create: `tests/test_dto_decode.py`

**Operator deps:** none.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dto_decode.py`:

```python
import struct

from mf4_analyzer.acquisition_capture.dto_decode import decode_dto
from mf4_analyzer.acquisition_capture.daq_map import OdtEntry, DaqMap


def _map_single():
    return DaqMap(
        pid_to_odt={0: (0, 0)},
        entries={
            (0, 0): (
                OdtEntry("a", offset=3, size=2, datatype="u16"),
                OdtEntry("b", offset=5, size=2, datatype="s16"),
            ),
        },
        event_for_daq={0: 0},
    )


def test_decode_two_measurements_little_endian():
    pid = bytes([0])
    ts = struct.pack("<H", 1000)  # 1000 us → 1.0 ms
    a = struct.pack("<H", 0x1234)
    b = struct.pack("<h", -42)
    frame = pid + ts + a + b

    samples = list(decode_dto(
        frame=frame,
        daq_map=_map_single(),
        timestamp_size=2,
        timestamp_unit_ns=1000,  # 1us
        byte_order="MSB_LAST",
        base_monotonic_s=100.0,
    ))
    assert len(samples) == 2
    n0, t0, v0 = samples[0]
    assert n0 == "a"
    # ts = base + 1000 us → 100.0 + 0.001 = 100.001 s
    assert abs(t0 - 100.001) < 1e-9
    assert v0 == float(0x1234)
    n1, t1, v1 = samples[1]
    assert n1 == "b"
    assert v1 == -42.0


def test_decode_no_timestamp_uses_base():
    daq_map = _map_single()
    pid = bytes([0])
    a = struct.pack("<H", 7)
    b = struct.pack("<h", -1)
    # No timestamp; entries offset must therefore use offset=1, 3 — but
    # _map_single uses offset=3, 5 assuming 2-byte timestamp. So we use
    # a different map for the no-ts case.
    no_ts_map = DaqMap(
        pid_to_odt={0: (0, 0)},
        entries={
            (0, 0): (
                OdtEntry("a", offset=1, size=2, datatype="u16"),
                OdtEntry("b", offset=3, size=2, datatype="s16"),
            ),
        },
        event_for_daq={0: 0},
    )
    frame = pid + a + b
    samples = list(decode_dto(
        frame=frame,
        daq_map=no_ts_map,
        timestamp_size=0,
        timestamp_unit_ns=1000,
        byte_order="MSB_LAST",
        base_monotonic_s=50.0,
    ))
    assert samples[0] == ("a", 50.0, 7.0)
    assert samples[1] == ("b", 50.0, -1.0)


def test_decode_big_endian_signed_32():
    daq_map = DaqMap(
        pid_to_odt={0: (0, 0)},
        entries={
            (0, 0): (
                OdtEntry("x", offset=1, size=4, datatype="s32"),
            ),
        },
        event_for_daq={0: 0},
    )
    pid = bytes([0])
    x = struct.pack(">i", -123456789)
    frame = pid + x
    samples = list(decode_dto(
        frame=frame, daq_map=daq_map, timestamp_size=0,
        timestamp_unit_ns=1000, byte_order="MSB_FIRST",
        base_monotonic_s=0.0,
    ))
    assert samples[0][2] == -123456789.0


def test_unknown_pid_yields_nothing():
    daq_map = _map_single()
    frame = bytes([99]) + bytes(7)  # PID not in map
    samples = list(decode_dto(
        frame=frame, daq_map=daq_map, timestamp_size=2,
        timestamp_unit_ns=1000, byte_order="MSB_LAST",
        base_monotonic_s=0.0,
    ))
    assert samples == []
```

- [ ] **Step 2: Run; expect failure**

Run: `pytest tests/test_dto_decode.py -v`
Expected: FAIL with "No module named '...dto_decode'".

- [ ] **Step 3: Implement**

Create `mf4_analyzer/acquisition_capture/dto_decode.py`:

```python
"""Pure byte-level DTO decoder.

Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md §6
"""
from __future__ import annotations

import struct
from typing import Iterator

from mf4_analyzer.acquisition_capture.daq_map import DaqMap


_FMT_BY_DATATYPE = {
    "u8": "B", "s8": "b",
    "u16": "H", "s16": "h",
    "u32": "I", "s32": "i",
    "u64": "Q", "s64": "q",
    "f32": "f", "f64": "d",
}


def decode_dto(
    *,
    frame: bytes,
    daq_map: DaqMap,
    timestamp_size: int,
    timestamp_unit_ns: int,
    byte_order: str,  # "MSB_LAST" | "MSB_FIRST"
    base_monotonic_s: float,
) -> Iterator[tuple[str, float, float]]:
    """Yield (measurement_name, timestamp_s, value) for each entry in
    the DTO, looking up which ODT this PID belongs to."""
    if not frame:
        return
    pid = frame[0]
    key = daq_map.pid_to_odt.get(pid)
    if key is None:
        return  # unknown PID — silently drop (see §10 DtoDecodeError counter)

    endian = "<" if byte_order == "MSB_LAST" else ">"

    ts_s = base_monotonic_s
    if timestamp_size > 0:
        ts_bytes = frame[1 : 1 + timestamp_size]
        ts_fmt = endian + {1: "B", 2: "H", 4: "I"}[timestamp_size]
        ts_raw = struct.unpack(ts_fmt, ts_bytes)[0]
        ts_s = base_monotonic_s + (ts_raw * timestamp_unit_ns) / 1e9

    for entry in daq_map.entries[key]:
        fmt_char = _FMT_BY_DATATYPE.get(entry.datatype.lower())
        if fmt_char is None:
            continue
        slc = frame[entry.offset : entry.offset + entry.size]
        if len(slc) < entry.size:
            continue
        raw = struct.unpack(endian + fmt_char, slc)[0]
        value = float(raw) * entry.scale_a + entry.scale_b
        yield (entry.measurement_name, ts_s, value)
```

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/test_dto_decode.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_capture/dto_decode.py tests/test_dto_decode.py
git commit -m "feat(acquisition): pure dto_decode handles endian/signed/timestamps"
```

---

### Task 11: `XcpDaqSession` orchestrator (mock pyxcp master)

**Files:**
- Create: `mf4_analyzer/acquisition_capture/xcp_daq_session.py`
- Create: `tests/test_xcp_daq_session.py`

**Operator deps:** none (mock pyxcp master).

- [ ] **Step 1: Write the failing test**

Create `tests/test_xcp_daq_session.py`:

```python
"""XcpDaqSession orchestration tests with mocked pyxcp.master.Master."""
from unittest.mock import MagicMock

import pytest

from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.daq_map import build_daq_map
from can_logger.p0.ifdata_xcp import (
    IfDataXcp, DaqEventInfo, DaqProcessorInfo,
)


def _ifdata():
    return IfDataXcp(
        cmd_id=0x500, resp_id=0x501,
        cmd_id_extended=False, resp_id_extended=False,
        can_fd=False, max_cto=8, max_dto=8,
        byte_order="MSB_LAST", address_granularity="BYTE",
        daq_timestamp_size=2, daq_timestamp_unit="1US",
        daq_timestamp_fixed=True,
        available_events=(
            DaqEventInfo(number=0, name="10ms", cycle_time_ms=10.0,
                         max_odt_entries=8, properties=("DAQ",)),
        ),
        daq_processor=DaqProcessorInfo(
            min_daq=0, max_event_channel=1,
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )


# E-2 (v2): SelectedMeasurement carries no datatype/size_bytes fields.
def _selected():
    return (
        SelectedMeasurement(
            name="a", address_hex="0x1000",
            event="10ms", event_rate_hz=100.0,
            payload_bytes=2,
        ),
    )


def _measurements():
    from can_logger.p0.a2l_probe import MeasurementSummary
    return {
        "a": MeasurementSummary(
            name="a", address=0x1000, datatype="UWORD",
            unit="", conversion="",
            available_events=("10ms",),
        ),
    }


def test_start_issues_expected_command_sequence():
    from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession
    master = MagicMock()
    # RESOURCE byte with DAQ bit (0x04) cleared → no seed&key needed.
    master.connect.return_value = MagicMock(resource=0x00)
    sess = XcpDaqSession(
        master=master, ifdata=_ifdata(), measurements=_measurements(),
    )
    sess.start(_selected())

    assert master.connect.called
    assert master.allocDaq.called
    assert master.allocOdt.called
    assert master.allocOdtEntry.called
    assert master.writeDaq.called
    assert master.setDaqListMode.called
    # startStopSynch called with START_SELECTED (0x01)
    master.startStopSynch.assert_called_with(0x01)


def test_stop_disconnects():
    from mf4_analyzer.acquisition_capture.xcp_daq_session import XcpDaqSession
    master = MagicMock()
    master.connect.return_value = MagicMock(resource=0x00)
    sess = XcpDaqSession(
        master=master, ifdata=_ifdata(), measurements=_measurements(),
    )
    sess.start(_selected())
    sess.stop()
    master.startStopSynch.assert_called_with(0x00)  # STOP_SELECTED
    assert master.disconnect.called


def test_start_raises_on_master_connect_failure():
    from mf4_analyzer.acquisition_capture.xcp_daq_session import (
        XcpDaqSession, XcpConnectError,
    )
    master = MagicMock()
    master.connect.side_effect = RuntimeError("no slave response")
    sess = XcpDaqSession(
        master=master, ifdata=_ifdata(), measurements=_measurements(),
    )
    with pytest.raises(XcpConnectError):
        sess.start(_selected())
```

- [ ] **Step 2: Run; expect import failure**

Run: `pytest tests/test_xcp_daq_session.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `mf4_analyzer/acquisition_capture/xcp_daq_session.py`:

```python
"""XcpDaqSession orchestrates the XCP master through the DAQ lifecycle.

Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md §5
"""
from __future__ import annotations

from typing import Any, Sequence

from can_logger.p0.ifdata_xcp import IfDataXcp
from mf4_analyzer.acquisition_capture.daq_map import DaqMap, build_daq_map
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement


class XcpConnectError(RuntimeError):
    pass


class XcpAuthError(RuntimeError):
    pass


class DaqAllocError(RuntimeError):
    pass


_TS_UNIT_TO_NS = {
    "1NS": 1, "10NS": 10, "100NS": 100,
    "1US": 1_000, "10US": 10_000, "100US": 100_000,
    "1MS": 1_000_000,
}


class XcpDaqSession:
    def __init__(
        self,
        *,
        master: Any,
        ifdata: IfDataXcp,
        measurements: Mapping[str, MeasurementSummary],
    ) -> None:
        self._master = master
        self._ifdata = ifdata
        self._measurements = measurements
        self._daq_map: DaqMap | None = None
        self._started = False

    @property
    def daq_map(self) -> DaqMap | None:
        return self._daq_map

    @property
    def timestamp_unit_ns(self) -> int:
        return _TS_UNIT_TO_NS.get(self._ifdata.daq_timestamp_unit, 1_000)

    def is_running(self) -> bool:
        return self._started

    def start(self, selected: Sequence[SelectedMeasurement]) -> None:
        try:
            connect_resp = self._master.connect()
        except Exception as exc:
            raise XcpConnectError(f"XCP CONNECT failed: {exc}") from exc

        # E-5 (v2): inspect RESOURCE and run seed&key if DAQ is locked.
        # Implemented in the new Task 11a; reference it here so the
        # implementer sees the dependency.
        from mf4_analyzer.acquisition_capture.xcp_auth import (
            unlock_resources_if_needed,
        )
        unlock_resources_if_needed(
            master=self._master,
            connect_response=connect_resp,
            seed_and_key_dll=getattr(self, "_seed_and_key_dll", None),
        )

        self._daq_map = build_daq_map(
            selected, self._ifdata, self._measurements,
        )
        try:
            for daq_list in sorted({d for d, _ in self._daq_map.entries.keys()}):
                odts_in_list = sorted(
                    {o for d, o in self._daq_map.entries.keys() if d == daq_list}
                )
                self._master.allocDaq(daq_list)
                self._master.allocOdt(daq_list, len(odts_in_list))
                for odt in odts_in_list:
                    entries = self._daq_map.entries[(daq_list, odt)]
                    self._master.allocOdtEntry(daq_list, odt, len(entries))
                    for entry_idx, entry in enumerate(entries):
                        self._master.setDaqPtr(daq_list, odt, entry_idx)
                        # bit_offset=0xFF means "no bit offset", size in bytes,
                        # address_extension=0
                        self._master.writeDaq(
                            0xFF, entry.size, 0, entry.address,
                        )
                self._master.setDaqListMode(
                    mode=0x10,  # timestamp enabled
                    daq=daq_list,
                    event=self._daq_map.event_for_daq[daq_list],
                    prescaler=1,
                    priority=0,
                )
        except Exception as exc:
            raise DaqAllocError(f"DAQ allocation failed: {exc}") from exc

        self._master.startStopSynch(0x01)  # START_SELECTED
        self._started = True

    def stop(self) -> None:
        if self._started:
            try:
                self._master.startStopSynch(0x00)
            finally:
                self._master.disconnect()
                self._started = False
```

Note: `writeDaq(0xFF, entry.size, 0, entry.address)` uses `entry.address`
which is already populated by `build_daq_map` (E-2 fix, Task 9 v2).
No follow-up `OdtEntry.address` migration is needed — the field is part
of the initial dataclass definition.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_daq_map_builder.py tests/test_dto_decode.py tests/test_xcp_daq_session.py -v`
Expected: all pass. (If daq_map tests fail due to the new field, add `address=...` to expected OdtEntry constructions in those tests.)

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/acquisition_capture/xcp_daq_session.py mf4_analyzer/acquisition_capture/daq_map.py tests/test_xcp_daq_session.py
git commit -m "feat(acquisition): XcpDaqSession orchestrates XCP master through DAQ lifecycle"
```

---

### Task 11a: Seed&Key authentication flow (E-5 fix, v2)

**Why:** spec §5.2 step 4 requires inspecting the `RESOURCE` byte from
CONNECT and, when DAQ is locked, running `getSeed` → vendor DLL →
`unlock`. v1 of this plan declared `XcpAuthError` but never raised it,
so a locked ECU would fail later as an opaque `DaqAllocError`. The new
helper module isolates the protocol from `XcpDaqSession` so locked-
resource paths are unit-testable with no hardware.

**Files:**
- Create: `mf4_analyzer/acquisition_capture/xcp_auth.py`
- Create: `tests/test_xcp_auth.py`
- Modify: `mf4_analyzer/acquisition_capture/xcp_daq_session.py` (import
  the helper; the call site is already wired in Task 11 v2).

**Operator deps:** none (DLL access is fully mocked via `ctypes.WinDLL`
patching). On-bench validation lands in PR-4 once O-3 is supplied.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_xcp_auth.py`:

```python
"""Seed&Key auth flow (E-5, post-Codex review).

Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md §5.2 step 4
"""
import ctypes
from unittest.mock import MagicMock, patch

import pytest


def _connect_resp(resource_byte: int):
    return MagicMock(resource=resource_byte)


def test_unlocked_daq_skips_auth():
    """RESOURCE byte 0x00 (DAQ bit clear) → nothing happens."""
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        unlock_resources_if_needed,
    )
    master = MagicMock()
    unlock_resources_if_needed(
        master=master,
        connect_response=_connect_resp(0x00),
        seed_and_key_dll=None,
    )
    master.getSeed.assert_not_called()
    master.unlock.assert_not_called()


def test_locked_daq_without_dll_raises_xcp_auth_error():
    """RESOURCE byte 0x04 (DAQ locked) + no DLL configured → clear error."""
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        unlock_resources_if_needed,
        XcpAuthError,
    )
    master = MagicMock()
    with pytest.raises(XcpAuthError, match="no seed&key DLL configured"):
        unlock_resources_if_needed(
            master=master,
            connect_response=_connect_resp(0x04),
            seed_and_key_dll=None,
        )


def test_locked_daq_with_missing_dll_path_raises():
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        unlock_resources_if_needed,
        XcpAuthError,
    )
    master = MagicMock()
    with pytest.raises(XcpAuthError, match="DLL not found"):
        unlock_resources_if_needed(
            master=master,
            connect_response=_connect_resp(0x04),
            seed_and_key_dll="C:/does/not/exist/seed.dll",
        )


def test_locked_daq_with_bitness_mismatch_raises(tmp_path):
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        unlock_resources_if_needed,
        XcpAuthError,
    )
    fake = tmp_path / "seed32.dll"
    fake.write_bytes(b"\x00" * 16)  # not a real DLL; loader will fail
    master = MagicMock()
    # Force WinDLL to raise OSError matching the bitness-mismatch pattern.
    with patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._load_seed_key_dll",
        side_effect=OSError("[WinError 193] is not a valid Win32 application"),
    ):
        with pytest.raises(XcpAuthError, match="bitness mismatch|not a valid"):
            unlock_resources_if_needed(
                master=master,
                connect_response=_connect_resp(0x04),
                seed_and_key_dll=str(fake),
            )


def test_locked_daq_happy_path_unlocks(tmp_path):
    """RESOURCE locked + DLL returns key + master.unlock accepts."""
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        unlock_resources_if_needed,
    )
    fake = tmp_path / "seed64.dll"
    fake.write_bytes(b"\x00" * 16)

    fake_dll = MagicMock()
    fake_dll.ASAP1A_XCP_ComputeKeyFromSeed = MagicMock(return_value=0)

    def _fake_compute(seed_bytes, dll):
        return b"\xDE\xAD\xBE\xEF"

    master = MagicMock()
    with patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._load_seed_key_dll",
        return_value=fake_dll,
    ), patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._compute_key_from_seed",
        side_effect=_fake_compute,
    ):
        master.getSeed.return_value = b"\x01\x02\x03\x04"
        unlock_resources_if_needed(
            master=master,
            connect_response=_connect_resp(0x04),
            seed_and_key_dll=str(fake),
        )
        master.getSeed.assert_called_with(resource_id=0x02)
        master.unlock.assert_called_with(
            resource_id=0x02, key=b"\xDE\xAD\xBE\xEF",
        )


def test_locked_daq_ecu_rejects_unlock_raises():
    from mf4_analyzer.acquisition_capture.xcp_auth import (
        unlock_resources_if_needed,
        XcpAuthError,
    )
    fake_dll = MagicMock()
    master = MagicMock()
    master.unlock.side_effect = RuntimeError("ERR_ACCESS_DENIED")
    with patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._load_seed_key_dll",
        return_value=fake_dll,
    ), patch(
        "mf4_analyzer.acquisition_capture.xcp_auth._compute_key_from_seed",
        return_value=b"\x00\x00\x00\x00",
    ), patch("os.path.exists", return_value=True):
        master.getSeed.return_value = b"\x00\x00"
        with pytest.raises(XcpAuthError, match="ECU rejected unlock"):
            unlock_resources_if_needed(
                master=master,
                connect_response=_connect_resp(0x04),
                seed_and_key_dll="/any/path.dll",
            )
```

- [ ] **Step 2: Run; expect import failure**

Run: `pytest tests/test_xcp_auth.py -v`
Expected: FAIL with "No module named '...xcp_auth'".

- [ ] **Step 3: Implement the helper module**

Create `mf4_analyzer/acquisition_capture/xcp_auth.py`:

```python
"""Seed&Key auth flow for XCP masters (E-5, post-Codex review).

Isolated from XcpDaqSession so locked-resource paths can be unit-tested
without a real DLL or hardware.

Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md §5.2 step 4
"""
from __future__ import annotations

import ctypes
import os
from typing import Any

# ASAM XCP 1.1.0 §3.1.1.2 RESOURCE byte bits:
RESOURCE_BIT_DAQ = 0x04
RESOURCE_ID_DAQ = 0x02  # ASAM XCP resource_id for DAQ in getSeed/unlock


class XcpAuthError(RuntimeError):
    pass


def _load_seed_key_dll(path: str) -> Any:
    """Seam for tests: WinDLL load may raise OSError on bitness mismatch
    or missing-symbol DLLs. Tests patch this directly."""
    return ctypes.WinDLL(path)  # type: ignore[attr-defined]


def _compute_key_from_seed(seed: bytes, dll: Any) -> bytes:
    """Call the standard ASAP1B symbol ASAP1A_XCP_ComputeKeyFromSeed.

    Signature per ASAM AE MCD-1 XCP Part 2:
      int32 fn(uint8 seed_len, uint8* seed, uint8* key_len_inout, uint8* key);

    Caller supplies a 256-byte key buffer; the DLL writes the key and
    updates key_len_inout. Returns the key bytes truncated to the
    actual length.
    """
    fn = dll.ASAP1A_XCP_ComputeKeyFromSeed
    fn.restype = ctypes.c_int32
    fn.argtypes = [
        ctypes.c_uint8,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.POINTER(ctypes.c_uint8),
    ]
    seed_buf = (ctypes.c_uint8 * len(seed))(*seed)
    key_buf = (ctypes.c_uint8 * 256)()
    key_len = ctypes.c_uint8(256)
    rc = fn(len(seed), seed_buf, ctypes.byref(key_len), key_buf)
    if rc != 0:
        raise XcpAuthError(
            f"seed&key DLL rejected seed: code={rc}"
        )
    return bytes(key_buf[: int(key_len.value)])


def unlock_resources_if_needed(
    *,
    master: Any,
    connect_response: Any,
    seed_and_key_dll: str | None,
) -> None:
    """Inspect RESOURCE; if DAQ is locked, run the seed&key flow.

    Stage 8 only needs DAQ unlock (CAL/PAG/PGM/STIM out of scope).
    """
    resource = getattr(connect_response, "resource", 0) or 0
    if not (resource & RESOURCE_BIT_DAQ):
        return

    if seed_and_key_dll is None:
        raise XcpAuthError(
            "RESOURCE.DAQ locked but no seed&key DLL configured "
            "(set TransportConfig.seed_and_key_dll)"
        )

    if not os.path.exists(seed_and_key_dll):
        raise XcpAuthError(
            f"seed&key DLL not found: {seed_and_key_dll}"
        )

    # Validate bitness — Python 64-bit needs a 64-bit DLL, etc. The
    # actual mismatch surface is OSError [WinError 193] from WinDLL.
    try:
        dll = _load_seed_key_dll(seed_and_key_dll)
    except OSError as exc:
        msg = str(exc)
        if "193" in msg or "not a valid" in msg.lower():
            raise XcpAuthError(
                f"seed&key DLL bitness mismatch (Python is "
                f"{ctypes.sizeof(ctypes.c_void_p) * 8}-bit): {msg}"
            ) from exc
        raise XcpAuthError(f"seed&key DLL load failed: {msg}") from exc

    try:
        seed = master.getSeed(resource_id=RESOURCE_ID_DAQ)
    except Exception as exc:
        raise XcpAuthError(f"getSeed failed: {exc}") from exc

    key = _compute_key_from_seed(seed, dll)

    try:
        master.unlock(resource_id=RESOURCE_ID_DAQ, key=key)
    except Exception as exc:
        raise XcpAuthError(f"ECU rejected unlock: {exc}") from exc
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_xcp_auth.py tests/test_xcp_daq_session.py -v`
Expected: all pass. (The Task 11 session tests already use
`resource=0x00` to skip the auth path; the new auth tests cover the
locked path independently.)

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_capture/xcp_auth.py tests/test_xcp_auth.py
git commit -m "feat(acquisition): seed&key unlock flow for locked DAQ resource"
```

---

### Task 12: `VectorXcpRecorderBackend` real implementation

**Files:**
- Modify: `mf4_analyzer/acquisition_capture/backends.py` (lines 405-456 — replace stub)
- Create: `tests/test_vector_xcp_backend.py`

**Operator deps:** none (mocked transport).

- [ ] **Step 1: Write the failing end-to-end backend test**

Create `tests/test_vector_xcp_backend.py`:

```python
"""End-to-end VectorXcpRecorderBackend test with mocked transport stack.

Bypasses sys.platform check by directly patching the platform guard.
"""
import struct
import sys
from unittest.mock import MagicMock, patch

import pytest

from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from can_logger.p0.a2l_probe import MeasurementSummary
from can_logger.p0.ifdata_xcp import (
    IfDataXcp, DaqEventInfo, DaqProcessorInfo,
)


def _ifdata():
    return IfDataXcp(
        cmd_id=0x500, resp_id=0x501,
        cmd_id_extended=False, resp_id_extended=False,
        can_fd=False, max_cto=8, max_dto=8,
        byte_order="MSB_LAST", address_granularity="BYTE",
        daq_timestamp_size=0,
        daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
        available_events=(
            DaqEventInfo(number=0, name="10ms", cycle_time_ms=10.0,
                         max_odt_entries=8, properties=("DAQ",)),
        ),
        daq_processor=DaqProcessorInfo(
            min_daq=0, max_event_channel=1,
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )


def _measurements():
    return {
        "a": MeasurementSummary(
            name="a", address=0x1000, datatype="UWORD",
            unit="", conversion="",
            available_events=("10ms",),
        ),
    }


def _selected():
    # E-2 (v2): SelectedMeasurement has no datatype/size_bytes fields.
    return (
        SelectedMeasurement(
            name="a", address_hex="0x1000",
            event="10ms", event_rate_hz=100.0, payload_bytes=2,
        ),
    )


def test_lifecycle_on_mock_transport():
    from mf4_analyzer.acquisition_capture.backends import (
        VectorXcpRecorderBackend,
    )

    with patch.object(sys, "platform", "win32"), \
         patch("mf4_analyzer.acquisition_capture.backends._import_can") as ic, \
         patch("mf4_analyzer.acquisition_capture.backends._import_xcp_master") as ix:
        # Build the mock bus + master
        mock_bus = MagicMock()
        ic.return_value = MagicMock(
            interfaces=MagicMock(vector=MagicMock(VectorBus=lambda **kw: mock_bus))
        )
        mock_master = MagicMock()
        # E-5: RESOURCE=0x00 → DAQ unlocked → seed&key skipped.
        mock_master.connect.return_value = MagicMock(resource=0x00)
        ix.return_value = lambda *a, **kw: mock_master

        backend = VectorXcpRecorderBackend(
            transport=TransportConfig(),
            ifdata=_ifdata(),
            measurements=_measurements(),
        )
        backend.start(_selected())
        assert mock_master.connect.called
        assert mock_master.startStopSynch.called

        final_status = backend.stop()
        mock_master.disconnect.assert_called()
        # E-3 (v2): BackendStatus must be the live 5-field shape.
        assert final_status.rx_count == 0
        assert final_status.bus_error_count == 0
        assert final_status.queue_overflow_count == 0
        assert final_status.last_error is None
        # started reads False after stop().
        assert final_status.started is False


def test_status_shape_matches_capture_controller_summary_contract():
    """E-3 (v2): CaptureController._build_summary reads
    status.queue_overflow_count and status.bus_error_count. Verify
    those fields exist and are ints, and that a fresh status() before
    start() does not raise."""
    from mf4_analyzer.acquisition_capture.backends import (
        VectorXcpRecorderBackend,
        BackendStatus,
    )

    with patch.object(sys, "platform", "win32"), \
         patch("mf4_analyzer.acquisition_capture.backends._import_can"), \
         patch("mf4_analyzer.acquisition_capture.backends._import_xcp_master"):
        backend = VectorXcpRecorderBackend(
            transport=TransportConfig(),
            ifdata=_ifdata(),
            measurements=_measurements(),
        )
        snap = backend.status()
        assert isinstance(snap, BackendStatus)
        assert isinstance(snap.queue_overflow_count, int)
        assert isinstance(snap.bus_error_count, int)
        assert snap.started is False


def test_capture_controller_round_trips_vector_backend_status(tmp_path):
    """E-3 (v2): drive CaptureController.start → stop on the Vector
    backend and assert _build_summary completes without AttributeError
    on the new BackendStatus fields."""
    from mf4_analyzer.acquisition_capture.backends import (
        VectorXcpRecorderBackend,
    )
    from mf4_analyzer.acquisition_capture.controller import CaptureController
    from mf4_analyzer.acquisition_capture.session import SessionConfig

    with patch.object(sys, "platform", "win32"), \
         patch("mf4_analyzer.acquisition_capture.backends._import_can") as ic, \
         patch("mf4_analyzer.acquisition_capture.backends._import_xcp_master") as ix:
        ic.return_value = MagicMock(Bus=lambda **kw: MagicMock())
        mock_master = MagicMock()
        mock_master.connect.return_value = MagicMock(resource=0x00)
        ix.return_value = lambda *a, **kw: mock_master

        backend = VectorXcpRecorderBackend(
            transport=TransportConfig(),
            ifdata=_ifdata(),
            measurements=_measurements(),
        )
        cfg = SessionConfig(
            output_mf4=tmp_path / "out.mf4",
            selected=_selected(),
            backend="vector",
        )
        ctrl = CaptureController(config=cfg, backend=backend)
        ctrl.start()
        summary = ctrl.stop()
        # The summary read queue_overflow_count and bus_error_count
        # off our BackendStatus without raising.
        assert summary is not None


def test_non_windows_raises_unavailable():
    from mf4_analyzer.acquisition_capture.backends import (
        VectorXcpRecorderBackend,
        RecorderBackendUnavailableError,
    )

    with patch.object(sys, "platform", "darwin"):
        with pytest.raises(RecorderBackendUnavailableError):
            VectorXcpRecorderBackend(
                transport=TransportConfig(),
                ifdata=_ifdata(),
                measurements=_measurements(),
            )
```

- [ ] **Step 2: Run; expect failure**

Run: `pytest tests/test_vector_xcp_backend.py -v`
Expected: FAIL (`RecorderBackendUnavailableError` not defined; `_import_can` not present; backend still raises `NotImplementedError`).

- [ ] **Step 3: Implement the new backend**

Replace lines 405-456 of `mf4_analyzer/acquisition_capture/backends.py` with:

```python
class RecorderBackendUnavailableError(RuntimeError):
    pass


class RecorderStartError(RuntimeError):
    pass


def _import_can():  # seam for tests to patch
    import can  # type: ignore[import-not-found]
    return can


def _import_xcp_master():  # seam for tests to patch
    from pyxcp.master import Master  # type: ignore[import-not-found]
    return Master


class VectorXcpRecorderBackend(RecorderBackend):
    """Production Vector + XCP/DAQ recorder backend (Windows-only).

    Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md §5
    """

    def __init__(
        self,
        *,
        transport: "TransportConfig",
        ifdata: "IfDataXcp",
        measurements: "Mapping[str, MeasurementSummary]",
        **_legacy_kwargs: Any,
    ) -> None:
        if not sys.platform.startswith("win"):
            raise RecorderBackendUnavailableError(
                "Vector/XCP backend is Windows-only. "
                "Use --backend fake or --backend replay on macOS / Linux."
            )
        # Lazy-imported via seams so tests can patch them on macOS.
        self._can = _import_can()
        self._MasterCls = _import_xcp_master()

        self._transport = transport
        self._ifdata = ifdata
        self._measurements = measurements
        self._bus = None
        self._master = None
        self._session = None
        self._poll_queue: list[tuple[str, float, float]] = []
        self._rx_count = 0
        self._bus_error_count = 0       # E-3 (v2): real BackendStatus field
        self._dropped_count = 0         # mapped to queue_overflow_count below
        self._last_error: str | None = None
        self._last_frame_t: float | None = None
        self._base_t = 0.0

    def start(self, selected: Sequence[SelectedMeasurement]) -> None:
        from mf4_analyzer.acquisition_capture.xcp_daq_session import (
            XcpDaqSession,
        )

        bus_kwargs = {
            "interface": "vector",
            "app_name": self._transport.app_name,
            "channel": self._transport.channel,
            "bitrate": self._transport.bitrate,
            "fd": self._transport.can_fd,
        }
        if self._transport.can_fd:
            bus_kwargs["data_bitrate"] = self._transport.data_bitrate
        try:
            self._bus = self._can.Bus(**bus_kwargs)
        except Exception as exc:
            raise RecorderStartError(f"Vector bus open failed: {exc}") from exc

        try:
            self._master = self._MasterCls("can", config={"bus": self._bus})
        except Exception as exc:
            try:
                self._bus.shutdown()
            except Exception:
                pass
            raise RecorderStartError(f"pyxcp Master init failed: {exc}") from exc

        self._session = XcpDaqSession(
            master=self._master,
            ifdata=self._ifdata,
            measurements=self._measurements,
        )
        # Seed&Key DLL (E-5) plumbed via the session for the unlock step
        # in Task 11a:
        self._session._seed_and_key_dll = self._transport.seed_and_key_dll
        self._base_t = time.monotonic()
        self._session.start(selected)

    def poll(self) -> list[tuple[str, float, float]]:
        # Drain whatever the capture thread (Stage 8b TODO: real thread)
        # has queued. For now, the master.fetch() / iter_dto() loop runs
        # inline on poll().
        if self._session is None or self._master is None:
            return []
        result = self._poll_queue
        self._poll_queue = []
        return result

    def _make_status(self) -> "BackendStatus":
        """E-3 (v2): the live BackendStatus dataclass at backends.py:41-46
        is (started, rx_count, bus_error_count, queue_overflow_count,
        last_error). CaptureController._build_summary reads
        queue_overflow_count and bus_error_count for the sidecar; we
        map our 'dropped DTOs' counter onto queue_overflow_count."""
        return BackendStatus(
            started=self._session is not None and self._session.is_running(),
            rx_count=self._rx_count,
            bus_error_count=self._bus_error_count,
            queue_overflow_count=self._dropped_count,
            last_error=self._last_error,
        )

    def stop(self) -> "BackendStatus":
        try:
            if self._session is not None:
                self._session.stop()
        finally:
            try:
                if self._bus is not None:
                    self._bus.shutdown()
            except Exception:
                pass
        return self._make_status()

    def status(self) -> "BackendStatus":
        return self._make_status()

    def last_frame_monotonic(self) -> float | None:
        return self._last_frame_t
```

Note: the actual DTO capture loop (`master.fetch()` driving `dto_decode` driving `_poll_queue`) is left as a Stage 8b refinement; the lifecycle test only verifies start/stop, not poll-with-data. A separate task adds the capture thread.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_vector_xcp_backend.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_capture/backends.py tests/test_vector_xcp_backend.py
git commit -m "feat(acquisition): VectorXcpRecorderBackend lifecycle on mocked transport"
```

---

### Task 13: Capture thread + DTO-driven poll queue

**Files:**
- Modify: `mf4_analyzer/acquisition_capture/backends.py` (VectorXcpRecorderBackend)
- Modify: `tests/test_vector_xcp_backend.py`

**Operator deps:** none.

- [ ] **Step 1: Write the failing test — feed canned DTO frames, expect poll() to return them**

Append to `tests/test_vector_xcp_backend.py`:

```python
def test_poll_returns_decoded_samples_from_dto_frames():
    """Feed canned DTO frames into the mock master.fetch(), verify
    poll() returns the decoded (name, ts, value) tuples."""
    from mf4_analyzer.acquisition_capture.backends import (
        VectorXcpRecorderBackend,
    )
    import struct

    pid = bytes([0])
    payload_a = struct.pack("<H", 0x1234)  # OdtEntry size=2, offset=1
    dto_frame = pid + payload_a

    with patch.object(sys, "platform", "win32"), \
         patch("mf4_analyzer.acquisition_capture.backends._import_can") as ic, \
         patch("mf4_analyzer.acquisition_capture.backends._import_xcp_master") as ix:
        ic.return_value = MagicMock(
            interfaces=MagicMock(vector=MagicMock(VectorBus=lambda **kw: MagicMock())),
            Bus=lambda **kw: MagicMock(),
        )
        mock_master = MagicMock()
        # E-5 (v2): RESOURCE=0x00 → DAQ unlocked → seed&key skipped.
        mock_master.connect.return_value = MagicMock(resource=0x00)
        # fetch() yields one DTO then EOF
        mock_master.fetch.side_effect = [dto_frame, None]
        ix.return_value = lambda *a, **kw: mock_master

        backend = VectorXcpRecorderBackend(
            transport=TransportConfig(),
            ifdata=_ifdata(),
            measurements=_measurements(),
        )
        backend.start(_selected())
        # Allow the capture thread one tick
        import time as _t
        _t.sleep(0.05)

        samples = backend.poll()
        backend.stop()

        names = [s[0] for s in samples]
        assert "a" in names
        a_value = next(v for n, _, v in samples if n == "a")
        assert a_value == float(0x1234)
```

- [ ] **Step 2: Run; expect failure**

Run: `pytest tests/test_vector_xcp_backend.py::test_poll_returns_decoded_samples_from_dto_frames -v`
Expected: FAIL (capture thread doesn't exist yet).

- [ ] **Step 3: Add the capture thread**

In `VectorXcpRecorderBackend.__init__`, add:

```python
        self._stop_event: threading.Event | None = None
        self._capture_thread: threading.Thread | None = None
```

(import `threading` at top of file if not already.)

In `start()`, after `self._session.start(selected)`, add:

```python
        from mf4_analyzer.acquisition_capture.dto_decode import decode_dto
        self._stop_event = threading.Event()

        def _capture_loop():
            ts_unit_ns = self._session.timestamp_unit_ns
            ts_size = self._ifdata.daq_timestamp_size
            byte_order = self._ifdata.byte_order
            daq_map = self._session.daq_map
            base_t = self._base_t
            while not self._stop_event.is_set():
                try:
                    frame = self._master.fetch(timeout=0.05)
                except Exception:
                    self._dropped_count += 1
                    continue
                if frame is None or not frame:
                    continue
                self._last_frame_t = time.monotonic()
                for tup in decode_dto(
                    frame=bytes(frame),
                    daq_map=daq_map,
                    timestamp_size=ts_size,
                    timestamp_unit_ns=ts_unit_ns,
                    byte_order=byte_order,
                    base_monotonic_s=base_t,
                ):
                    self._poll_queue.append(tup)
                    self._rx_count += 1

        self._capture_thread = threading.Thread(
            target=_capture_loop, name="xcp-capture", daemon=True,
        )
        self._capture_thread.start()
```

In `stop()`, before disconnecting, signal the thread to stop:

```python
        if self._stop_event is not None:
            self._stop_event.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=1.0)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_vector_xcp_backend.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_capture/backends.py tests/test_vector_xcp_backend.py
git commit -m "feat(acquisition): capture thread feeds dto_decode into poll() queue"
```

---

### Task 14: PR-2 wrap-up

- [ ] **Step 1: Run full acquisition suite**

Run: `pytest tests/test_acquisition* tests/test_ifdata_xcp_parser.py tests/test_transport_config.py tests/test_config_store_migration.py tests/test_daq_map_builder.py tests/test_dto_decode.py tests/test_xcp_daq_session.py tests/test_xcp_auth.py tests/test_vector_xcp_backend.py -v`
Expected: all green. (`tests/test_xcp_auth.py` was added by Task 11a
for the Seed&Key flow — E-5 fix.)

- [ ] **Step 2: Verify CLI smoke still works with fake backend**

Run: `python -m mf4_analyzer.acquisition_capture --backend fake --duration 2 --output /tmp/cap.mf4 --signals EngSpdAvg,EngTrqAct,VehSpeedRaw`
Expected: exits 0, creates `/tmp/cap.mf4`.

- [ ] **Step 3: Open PR**

```bash
git push -u origin HEAD
gh pr create --title "Stage 8b: backend core — XcpDaqSession + VectorXcpRecorderBackend" \
  --body "$(cat <<'EOF'
## Summary
- XcpDaqSession orchestrates pyxcp Master through DAQ lifecycle
- VectorXcpRecorderBackend wires bus → master → session → dto_decode → poll
- Capture thread feeds decoded samples into poll queue
- Seed&Key auth flow (E-5) gates locked DAQ resources before allocation

## Open items (operator)
- O-1 real A2L for cross-checking IF_DATA dialect: nice-to-have, mocks cover correctness
- O-2 / O-3 / O-4 / O-5: gated to PR-3 / PR-4

## Test plan
- [x] pytest tests/test_daq_map_builder.py
- [x] pytest tests/test_dto_decode.py
- [x] pytest tests/test_xcp_daq_session.py
- [x] pytest tests/test_xcp_auth.py
- [x] pytest tests/test_vector_xcp_backend.py (incl. CaptureController round-trip)
- [x] CLI smoke with fake backend exits 0 and writes MF4
EOF
)"
```

---

## PR-3: UI Integration (Operator deps: O-1 + O-2 for end-to-end smoke; otherwise none)

### Task 15: `vector_hw_probe` — HW health detection

**Files:**
- Create: `mf4_analyzer/acquisition_capture/vector_hw_probe.py`
- Create: `tests/test_vector_hw_probe.py`
- Modify: `mf4_analyzer/acquisition_capture/health.py` (lines 202-214)

**Operator deps:** PR-3 task body none; O-2 needed to verify on real Windows PC.

- [ ] **Step 1: Write the failing test**

Create `tests/test_vector_hw_probe.py`:

```python
import sys
import time
from unittest.mock import MagicMock, patch

from mf4_analyzer.acquisition_capture.transport_config import TransportConfig


def test_probe_returns_red_on_non_windows():
    """E-6 (v2): existing level_hw returns red when error is non-null,
    and test_acquisition_capture_health.py pins the macOS stub red.
    Spec §7 v2 explicitly accepts red (not yellow) for non-Windows."""
    from mf4_analyzer.acquisition_capture.vector_hw_probe import (
        vector_hw_probe,
    )
    from mf4_analyzer.acquisition_capture.health import level_hw
    with patch.object(sys, "platform", "darwin"):
        result = vector_hw_probe(TransportConfig())
        assert result.ok is False
        assert "Windows" in (result.error or "")
        # E-6: HwHealth required fields must be populated on every
        # return path, including the non-Windows early-return.
        assert isinstance(result.channel_count, int)
        assert isinstance(result.last_probe_ts, float)
        assert level_hw(result) == "red"


def test_probe_returns_green_on_windows_when_app_known():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import (
        vector_hw_probe,
    )
    fake_canlib = MagicMock()
    fake_canlib.get_application_config.return_value = MagicMock(
        hw_type="VN1640", channel=0, driver_version="22.0",
    )
    fake_canlib.get_channel_count.return_value = 4

    with patch.object(sys, "platform", "win32"), \
         patch(
            "mf4_analyzer.acquisition_capture.vector_hw_probe._load_vector_canlib",
            return_value=fake_canlib,
         ):
        result = vector_hw_probe(TransportConfig(app_name="Python", channel=0))
        assert result.ok is True
        assert result.error is None
        assert result.channel_count == 4
        assert result.driver_version == "22.0"


def test_probe_reports_missing_app():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import (
        vector_hw_probe,
    )
    fake_canlib = MagicMock()
    fake_canlib.get_application_config.side_effect = LookupError(
        "application 'Python' not found"
    )

    with patch.object(sys, "platform", "win32"), \
         patch(
            "mf4_analyzer.acquisition_capture.vector_hw_probe._load_vector_canlib",
            return_value=fake_canlib,
         ):
        result = vector_hw_probe(TransportConfig(app_name="Python", channel=0))
        assert result.ok is False
        assert "Python" in (result.error or "")
        # Every HwHealth(...) construction MUST set channel_count and
        # last_probe_ts — error returns are no exception.
        assert isinstance(result.channel_count, int)
        assert isinstance(result.last_probe_ts, float)


def test_test_xcp_connection_returns_resource_byte_on_success():
    """E-4 (v2): real XCP CONNECT/DISCONNECT helper that the Settings
    dialog wires the Test Connection button to."""
    from mf4_analyzer.acquisition_capture.vector_hw_probe import (
        test_xcp_connection,
    )
    from can_logger.p0.ifdata_xcp import IfDataXcp, DaqEventInfo, DaqProcessorInfo

    ifdata = IfDataXcp(
        cmd_id=0x500, resp_id=0x501,
        cmd_id_extended=False, resp_id_extended=False,
        can_fd=False, max_cto=8, max_dto=8,
        byte_order="MSB_LAST", address_granularity="BYTE",
        daq_timestamp_size=0, daq_timestamp_unit="1US",
        daq_timestamp_fixed=False,
        available_events=(),
        daq_processor=DaqProcessorInfo(
            min_daq=0, max_event_channel=0,
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )

    mock_master = MagicMock()
    mock_master.connect.return_value = MagicMock(resource=0x05)
    mock_bus = MagicMock()
    with patch.object(sys, "platform", "win32"), \
         patch(
            "mf4_analyzer.acquisition_capture.vector_hw_probe._open_vector_bus",
            return_value=mock_bus,
         ), \
         patch(
            "mf4_analyzer.acquisition_capture.vector_hw_probe._make_pyxcp_master",
            return_value=mock_master,
         ):
        result = test_xcp_connection(TransportConfig(), ifdata)
        assert result.ok is True
        assert result.resource_byte == 0x05
        assert result.latency_ms is not None
        mock_master.connect.assert_called_once()
        mock_master.disconnect.assert_called_once()
        mock_bus.shutdown.assert_called_once()


def test_test_xcp_connection_reports_no_response_on_timeout():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import (
        test_xcp_connection,
    )
    from can_logger.p0.ifdata_xcp import IfDataXcp, DaqProcessorInfo

    ifdata = IfDataXcp(
        cmd_id=0x500, resp_id=0x501,
        cmd_id_extended=False, resp_id_extended=False,
        can_fd=False, max_cto=8, max_dto=8,
        byte_order="MSB_LAST", address_granularity="BYTE",
        daq_timestamp_size=0, daq_timestamp_unit="1US",
        daq_timestamp_fixed=False, available_events=(),
        daq_processor=DaqProcessorInfo(
            min_daq=0, max_event_channel=0,
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )

    mock_master = MagicMock()
    mock_master.connect.side_effect = TimeoutError("no response")
    mock_bus = MagicMock()
    with patch.object(sys, "platform", "win32"), \
         patch(
            "mf4_analyzer.acquisition_capture.vector_hw_probe._open_vector_bus",
            return_value=mock_bus,
         ), \
         patch(
            "mf4_analyzer.acquisition_capture.vector_hw_probe._make_pyxcp_master",
            return_value=mock_master,
         ):
        result = test_xcp_connection(TransportConfig(), ifdata)
        assert result.ok is False
        assert "0x500" in (result.error or "")
        # Bus must be shut down even on failure.
        mock_bus.shutdown.assert_called_once()


def test_test_xcp_connection_bus_open_failure_reports_red():
    from mf4_analyzer.acquisition_capture.vector_hw_probe import (
        test_xcp_connection,
    )
    from can_logger.p0.ifdata_xcp import IfDataXcp, DaqProcessorInfo

    ifdata = IfDataXcp(
        cmd_id=0x500, resp_id=0x501,
        cmd_id_extended=False, resp_id_extended=False,
        can_fd=False, max_cto=8, max_dto=8,
        byte_order="MSB_LAST", address_granularity="BYTE",
        daq_timestamp_size=0, daq_timestamp_unit="1US",
        daq_timestamp_fixed=False, available_events=(),
        daq_processor=DaqProcessorInfo(
            min_daq=0, max_event_channel=0,
            granularity_odt_entry_size_daq=1,
            overload_indication="EVENT",
        ),
    )

    with patch.object(sys, "platform", "win32"), \
         patch(
            "mf4_analyzer.acquisition_capture.vector_hw_probe._open_vector_bus",
            side_effect=RuntimeError("vxlapi: channel busy"),
         ):
        result = test_xcp_connection(TransportConfig(), ifdata)
        assert result.ok is False
        assert "总线" in (result.error or "") or "bus" in (result.error or "").lower()
```

- [ ] **Step 2: Run; expect failure**

Run: `pytest tests/test_vector_hw_probe.py -v`
Expected: FAIL with "No module named '...vector_hw_probe'".

- [ ] **Step 3: Implement vector_hw_probe**

Create `mf4_analyzer/acquisition_capture/vector_hw_probe.py`:

```python
"""Vector hardware health probe + XCP connection probe.

Spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md §7, §8.1
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from mf4_analyzer.acquisition_capture.health import HwHealth
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from can_logger.p0.ifdata_xcp import IfDataXcp


def _load_vector_canlib():
    from can.interfaces.vector import canlib  # type: ignore[import-not-found]
    return canlib


def _hw(*, ok: bool, error: str | None, driver_version: str | None,
        channel_count: int) -> HwHealth:
    """E-6 (v2): HwHealth requires channel_count and last_probe_ts on
    every return path. Centralizing construction so we cannot forget."""
    return HwHealth(
        ok=ok,
        driver_version=driver_version,
        channel_count=channel_count,
        last_probe_ts=time.monotonic(),
        error=error,
    )


def vector_hw_probe(transport: TransportConfig) -> HwHealth:
    if not sys.platform.startswith("win"):
        # E-6: non-Windows returns red (current level_hw semantics).
        # Spec §7 v2 documents the choice; introducing yellow would
        # require an `expected_unavailable` field on HwHealth and a
        # level_hw revision, both out of Stage 8 scope.
        return _hw(
            ok=False, error="Vector backend requires Windows",
            driver_version=None, channel_count=0,
        )
    try:
        canlib = _load_vector_canlib()
    except Exception as exc:
        return _hw(
            ok=False, error=f"vxlapi DLL not loadable: {exc}",
            driver_version=None, channel_count=0,
        )

    try:
        cfg = canlib.get_application_config(transport.app_name)
    except LookupError as exc:
        return _hw(
            ok=False,
            error=f"Vector application {transport.app_name!r} not configured ({exc})",
            driver_version=None, channel_count=0,
        )
    except Exception as exc:
        return _hw(
            ok=False, error=f"get_application_config failed: {exc}",
            driver_version=None, channel_count=0,
        )

    try:
        count = canlib.get_channel_count()
    except Exception:
        count = 0
    if transport.channel >= count:
        return _hw(
            ok=False,
            error=f"channel {transport.channel} not present (count={count})",
            driver_version=getattr(cfg, "driver_version", None),
            channel_count=count,
        )

    return _hw(
        ok=True, error=None,
        driver_version=getattr(cfg, "driver_version", None),
        channel_count=count,
    )


# ---------------------------------------------------------------------------
# E-4 (v2, post-Codex review): real XCP CONNECT/DISCONNECT probe for the
# Settings → Test Connection button. This is the operator's primary
# debug tool when on-vehicle things go sideways — it MUST exercise the
# real protocol, not only the driver/app health probe.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TestXcpConnectionResult:
    ok: bool
    resource_byte: int | None
    latency_ms: int | None
    error: str | None


def _open_vector_bus(transport: TransportConfig):
    import can  # type: ignore[import-not-found]
    return can.Bus(
        interface="vector",
        app_name=transport.app_name,
        channel=transport.channel,
        bitrate=transport.bitrate,
        fd=transport.can_fd,
        **({"data_bitrate": transport.data_bitrate} if transport.can_fd else {}),
    )


def _make_pyxcp_master(bus, transport: TransportConfig):
    from pyxcp.master import Master  # type: ignore[import-not-found]
    return Master("can", config={
        "bus": bus,
        "timeout": transport.timeout_s,
    })


def test_xcp_connection(
    transport: TransportConfig,
    ifdata: IfDataXcp,
) -> TestXcpConnectionResult:
    """Open Vector bus, CONNECT, capture RESOURCE, DISCONNECT, close.

    Surfaces three failure modes the Codex review flagged:
    - CAN bus open failure (driver / channel busy)
    - XCP CONNECT no-response (wrong cmd_id, powered-off ECU)
    - Seed&Key auth failure (when transport.seed_and_key_dll is set)
    """
    bus = None
    try:
        try:
            bus = _open_vector_bus(transport)
        except Exception as exc:
            return TestXcpConnectionResult(
                ok=False, resource_byte=None, latency_ms=None,
                error=f"CAN 总线打开失败：{exc}",
            )

        master = _make_pyxcp_master(bus, transport)
        t0 = time.monotonic()
        try:
            resp = master.connect()
        except TimeoutError as exc:
            return TestXcpConnectionResult(
                ok=False, resource_byte=None, latency_ms=None,
                error=(
                    f"ECU 未在 {int(transport.timeout_s * 1000)} ms "
                    f"内响应 (cmd_id=0x{ifdata.cmd_id:03X}): {exc}"
                ),
            )
        except Exception as exc:
            return TestXcpConnectionResult(
                ok=False, resource_byte=None, latency_ms=None,
                error=f"XCP CONNECT 失败：{exc}",
            )
        latency_ms = int((time.monotonic() - t0) * 1000)
        resource = int(getattr(resp, "resource", 0) or 0)

        # Optional seed&key sanity check — surfaces auth errors here so
        # the operator sees them at Test Connection time, not Record.
        if transport.seed_and_key_dll:
            from mf4_analyzer.acquisition_capture.xcp_auth import (
                unlock_resources_if_needed,
                XcpAuthError,
            )
            try:
                unlock_resources_if_needed(
                    master=master,
                    connect_response=resp,
                    seed_and_key_dll=transport.seed_and_key_dll,
                )
            except XcpAuthError as exc:
                try:
                    master.disconnect()
                except Exception:
                    pass
                return TestXcpConnectionResult(
                    ok=False, resource_byte=resource, latency_ms=latency_ms,
                    error=f"Seed&Key 失败：{exc}",
                )

        try:
            master.disconnect()
        except Exception:
            pass
        return TestXcpConnectionResult(
            ok=True, resource_byte=resource, latency_ms=latency_ms,
            error=None,
        )
    finally:
        if bus is not None:
            try:
                bus.shutdown()
            except Exception:
                pass
```

- [ ] **Step 4: Verify HwHealth field coverage**

Run: `grep -n "HwHealth(" mf4_analyzer/acquisition_capture/vector_hw_probe.py`
Every match must funnel through `_hw(...)` (no direct `HwHealth(...)`
calls anywhere else in this module) — that's the E-6 guarantee that
`channel_count` and `last_probe_ts` are always set.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_vector_hw_probe.py tests/test_acquisition_capture_health.py -v`
Expected: all pass.

- [ ] **Step 6: Wire vector_hw_probe into HealthAggregator**

In `health.py`, replace `_default_hw_probe()` (lines 202-214) with:

```python
def _default_hw_probe(transport=None) -> HwHealth:
    """Default HW probe. On Windows with Vector, delegates to
    vector_hw_probe; elsewhere returns red (E-6, post-Codex review)."""
    import time as _time
    if transport is None:
        return HwHealth(
            ok=False, driver_version=None, channel_count=0,
            last_probe_ts=_time.monotonic(),
            error="transport not configured",
        )
    from mf4_analyzer.acquisition_capture.vector_hw_probe import (
        vector_hw_probe,
    )
    return vector_hw_probe(transport)
```

In whatever code constructs `HealthAggregator(_hw_probe=...)`, ensure the probe is bound with the current `TransportConfig` (this is a small refactor; the engineer reads the construction site and adds `transport` parameter or uses `functools.partial`).

- [ ] **Step 7: Run all health tests**

Run: `pytest tests/test_acquisition_capture_health.py tests/test_vector_hw_probe.py -v`
Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/acquisition_capture/vector_hw_probe.py mf4_analyzer/acquisition_capture/health.py tests/test_vector_hw_probe.py
git commit -m "feat(acquisition): vector_hw_probe replaces hardcoded HW chip stub"
```

---

### Task 16: Settings Dialog — Transport tab

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/settings_dialog.py`
- Create: `tests/ui/test_settings_transport_tab.py`

**Operator deps:** none; O-2 helpful for visual verification.

- [ ] **Step 1: Write the failing widget test**

Create `tests/ui/test_settings_transport_tab.py`:

```python
"""SettingsDialog Transport tab — field round-trip and Test Connection button.

E-4 (v2, post-Codex review): Test Connection MUST do real XCP
CONNECT/DISCONNECT, not only a driver/app health probe. The button
disables when no A2L (and thus no IfDataXcp) is loaded, because we
need CAN IDs and MAX_DTO to even attempt the protocol exchange.
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.usefixtures("qtbot")


def test_transport_tab_round_trips_values(qtbot, tmp_path):
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig

    initial = TransportConfig(
        app_name="CANalyzer", channel=1, can_fd=True,
        bitrate=1_000_000, data_bitrate=4_000_000,
    )
    dlg = SettingsDialog(transport=initial)
    qtbot.addWidget(dlg)

    # Toggle a value and read back
    dlg.transport_widget.channel_spin.setValue(2)
    out = dlg.current_transport()
    assert out.channel == 2
    assert out.app_name == "CANalyzer"
    assert out.can_fd is True


def test_test_connection_button_disabled_on_non_windows(qtbot):
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig

    with patch.object(sys, "platform", "darwin"):
        dlg = SettingsDialog(transport=TransportConfig())
        qtbot.addWidget(dlg)
        assert dlg.transport_widget.test_btn.isEnabled() is False
        # Tooltip explains why.
        assert "Windows" in dlg.transport_widget.test_btn.toolTip()


def test_test_connection_button_disabled_without_ifdata_on_windows(qtbot):
    """E-4: without an A2L loaded we have no cmd_id/MAX_DTO, so the
    protocol probe cannot run. Button must be visibly disabled."""
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig

    with patch.object(sys, "platform", "win32"):
        dlg = SettingsDialog(transport=TransportConfig(), ifdata=None)
        qtbot.addWidget(dlg)
        assert dlg.transport_widget.test_btn.isEnabled() is False
        assert "A2L" in dlg.transport_widget.test_btn.toolTip()


def test_test_connection_runs_hw_then_xcp_probe_and_reports_resource(qtbot):
    """E-4: on click, run vector_hw_probe first; if green, run
    test_xcp_connection; toast must include the RESOURCE byte."""
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_capture.health import HwHealth
    import time

    with patch.object(sys, "platform", "win32"), \
         patch(
            "mf4_analyzer.acquisition_ui.settings_dialog.vector_hw_probe",
            return_value=HwHealth(
                ok=True, driver_version="22.0", channel_count=4,
                last_probe_ts=time.monotonic(),
            ),
         ), \
         patch(
            "mf4_analyzer.acquisition_ui.settings_dialog.test_xcp_connection",
            return_value=MagicMock(
                ok=True, resource_byte=0x05, latency_ms=12,
                error=None,
            ),
         ) as xcp_mock:
        ifdata = MagicMock()
        dlg = SettingsDialog(transport=TransportConfig(), ifdata=ifdata)
        qtbot.addWidget(dlg)
        assert dlg.transport_widget.test_btn.isEnabled() is True

        result = dlg._run_test_connection_for_test()  # test seam
        xcp_mock.assert_called_once()
        assert "RESOURCE=0x05" in result.message
        assert "12" in result.message  # latency


def test_test_connection_reports_xcp_no_response_in_red(qtbot):
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_capture.health import HwHealth
    import time

    with patch.object(sys, "platform", "win32"), \
         patch(
            "mf4_analyzer.acquisition_ui.settings_dialog.vector_hw_probe",
            return_value=HwHealth(
                ok=True, driver_version="22.0", channel_count=4,
                last_probe_ts=time.monotonic(),
            ),
         ), \
         patch(
            "mf4_analyzer.acquisition_ui.settings_dialog.test_xcp_connection",
            return_value=MagicMock(
                ok=False, resource_byte=None, latency_ms=None,
                error="ECU 未在 1000 ms 内响应 (cmd_id=0x500)",
            ),
         ):
        ifdata = MagicMock()
        dlg = SettingsDialog(transport=TransportConfig(), ifdata=ifdata)
        qtbot.addWidget(dlg)
        result = dlg._run_test_connection_for_test()
        assert "未在" in result.message and "响应" in result.message
        assert result.level == "red"


def test_test_connection_hw_failure_skips_xcp_probe(qtbot):
    """E-4: if hw probe is red, don't open the bus / try CONNECT.
    The XCP probe is gated on hw probe success."""
    from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    from mf4_analyzer.acquisition_capture.health import HwHealth
    import time

    with patch.object(sys, "platform", "win32"), \
         patch(
            "mf4_analyzer.acquisition_ui.settings_dialog.vector_hw_probe",
            return_value=HwHealth(
                ok=False, driver_version=None, channel_count=0,
                last_probe_ts=time.monotonic(),
                error="vxlapi DLL not loadable",
            ),
         ), \
         patch(
            "mf4_analyzer.acquisition_ui.settings_dialog.test_xcp_connection",
         ) as xcp_mock:
        ifdata = MagicMock()
        dlg = SettingsDialog(transport=TransportConfig(), ifdata=ifdata)
        qtbot.addWidget(dlg)
        dlg._run_test_connection_for_test()
        xcp_mock.assert_not_called()
```

- [ ] **Step 2: Run; expect failure**

Run: `pytest tests/ui/test_settings_transport_tab.py -v`
Expected: FAIL (Transport tab doesn't exist).

- [ ] **Step 3: Implement the Transport tab widget**

Add a new tab to `SettingsDialog` in `mf4_analyzer/acquisition_ui/settings_dialog.py`. The exact insertion depends on existing dialog structure — engineer reads the file, then adds:

A new `TransportTabWidget(QWidget)` class with:
- `app_combo: QComboBox` (editable, populated with known apps if accessible: "Python", "CANalyzer", "CANoe", custom)
- `channel_spin: QSpinBox` (0..15)
- `can_fd_check: QCheckBox`
- `bitrate_combo: QComboBox` ({125000, 250000, 500000, 1000000})
- `data_bitrate_combo: QComboBox` ({2000000, 4000000, 5000000, 8000000}) — disabled unless `can_fd_check`
- `sample_point_spin: QDoubleSpinBox` (50.0..90.0)
- `fd_sample_point_spin: QDoubleSpinBox`
- `timeout_spin: QSpinBox` (100..10000 ms)
- `seed_key_line: QLineEdit` + `seed_key_browse: QPushButton`
- `test_btn: QPushButton("Test Connection")` — disabled states per E-4:
  - macOS / Linux: disabled, tooltip "Vector 仅在 Windows 可用"
  - No `IfDataXcp` loaded: disabled, tooltip "请先选择 A2L 文件 — XCP 连接测试需要 CAN ID / MAX_DTO 信息"

`current_transport(self) -> TransportConfig` returns a fresh dataclass from widget values.

`SettingsDialog.__init__` accepts both `transport: TransportConfig | None = None`
AND `ifdata: IfDataXcp | None = None`; stores them, adds the tab, and
sets `test_btn.setEnabled(sys.platform.startswith("win") and ifdata is not None)`.

`test_btn.clicked` runs the two-stage probe (E-4, post-Codex review):

```python
# Imports at module top so tests can patch them.
from mf4_analyzer.acquisition_capture.vector_hw_probe import (
    vector_hw_probe,
    test_xcp_connection,
)


@dataclass(frozen=True)
class _TestConnectionResult:
    ok: bool
    level: Literal["green", "red"]
    message: str


def _on_test_connection(self) -> None:
    result = self._run_test_connection_for_test()
    box = QMessageBox.information if result.ok else QMessageBox.warning
    box(self, "Test Connection", result.message)


def _run_test_connection_for_test(self) -> _TestConnectionResult:
    """Test seam so unit tests don't need to drive the QMessageBox.
    Returns the structured result; _on_test_connection just renders it."""
    transport = self.current_transport()
    # Stage A: driver / DLL / app / channel.
    hw = vector_hw_probe(transport)
    if not hw.ok:
        return _TestConnectionResult(
            ok=False, level="red",
            message=f"硬件检查失败：{hw.error}",
        )
    # Stage B: real XCP CONNECT → DISCONNECT (E-4).
    xcp = test_xcp_connection(transport, self._ifdata)
    if not xcp.ok:
        return _TestConnectionResult(
            ok=False, level="red",
            message=f"XCP 连接失败：{xcp.error}",
        )
    return _TestConnectionResult(
        ok=True, level="green",
        message=(
            f"OK · driver {hw.driver_version} · "
            f"RESOURCE=0x{xcp.resource_byte:02X} · {xcp.latency_ms} ms"
        ),
    )
```

The `test_xcp_connection(transport, ifdata)` helper is implemented in
Task 15 v2 alongside `vector_hw_probe`. Its return shape:

```python
@dataclass(frozen=True)
class TestXcpConnectionResult:
    ok: bool
    resource_byte: int | None
    latency_ms: int | None
    error: str | None
```

If the dialog needs to stay responsive on slow buses, wrap the call
in a `QThread` + signal — but the function itself MUST run real
CONNECT/DISCONNECT, never just the hw probe.

(Engineer adapts to existing dialog look-and-feel. Use Chinese labels
matching the cockpit's existing language style.)

- [ ] **Step 4: Run UI tests**

Run: `pytest tests/ui/test_settings_transport_tab.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/settings_dialog.py tests/ui/test_settings_transport_tab.py
git commit -m "feat(cockpit): Settings dialog adds Transport tab with Test Connection"
```

---

### Task 17: Transport status chip in cockpit toolbar

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window.py`
- Create: `tests/ui/test_main_window_transport_chip.py`

**Operator deps:** none.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_main_window_transport_chip.py`:

```python
import pytest


pytestmark = pytest.mark.usefixtures("qtbot")


def test_transport_chip_shows_disconnected_when_no_config(qtbot):
    from mf4_analyzer.acquisition_ui.main_window import MainWindow
    win = MainWindow(demo=True)
    qtbot.addWidget(win)
    chip = win.findChild(object, "transport_status_chip")
    assert chip is not None
    assert "未配置" in chip.text() or "传输" in chip.text()


def test_transport_chip_updates_when_transport_changes(qtbot):
    from mf4_analyzer.acquisition_ui.main_window import MainWindow
    from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
    win = MainWindow(demo=True)
    qtbot.addWidget(win)
    win.set_transport(TransportConfig(app_name="CANalyzer", channel=1))
    chip = win.findChild(object, "transport_status_chip")
    assert "CANalyzer" in chip.text()
    assert "Ch=1" in chip.text() or "1" in chip.text()
```

- [ ] **Step 2: Run; expect failure**

Run: `pytest tests/ui/test_main_window_transport_chip.py -v`
Expected: FAIL.

- [ ] **Step 3: Add the chip to MainWindow**

In `mf4_analyzer/acquisition_ui/main_window.py`:

1. Add a `QLabel` near the existing toolbar widgets:
   ```python
   self._transport_chip = QLabel("传输未配置", self)
   self._transport_chip.setObjectName("transport_status_chip")
   self._transport_chip.setStyleSheet(
       "QLabel { padding: 2px 8px; border-radius: 8px; "
       "background: #f0c040; color: #333; }"
   )
   # Add to existing toolbar layout (engineer reads current layout)
   ```
2. Add the method:
   ```python
   def set_transport(self, transport: "TransportConfig | None") -> None:
       if transport is None:
           self._transport_chip.setText("传输未配置")
           self._transport_chip.setStyleSheet(
               "QLabel { padding: 2px 8px; border-radius: 8px; "
               "background: #f0c040; color: #333; }"
           )
           return
       fd_label = "CAN-FD" if transport.can_fd else "CAN"
       rate = transport.bitrate // 1000
       text = (
           f"传输 · App={transport.app_name} · Ch={transport.channel} · "
           f"{fd_label} {rate}k"
       )
       self._transport_chip.setText(text)
       self._transport_chip.setStyleSheet(
           "QLabel { padding: 2px 8px; border-radius: 8px; "
           "background: #c8e6c9; color: #1b5e20; }"
       )
   ```
3. Wire the chip click to open Settings → Transport tab:
   ```python
   self._transport_chip.mousePressEvent = lambda _ev: self._open_settings(tab="transport")
   ```
   (Adapt to existing `_open_settings` signature.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/ui/test_main_window_transport_chip.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window.py tests/ui/test_main_window_transport_chip.py
git commit -m "feat(cockpit): toolbar transport status chip"
```

---

### Task 18: PR-3 wrap-up

- [ ] **Step 1: Run full suite + UI**

Run: `pytest tests/ -v --ignore=tests/integration`
Expected: green; allow `qtbot` skip on headless CI if not configured.

- [ ] **Step 2: Cockpit smoke (manual visual)**

Run: `python -m mf4_analyzer.acquisition_ui --demo --backend fake`
Visual checks:
- Toolbar shows "传输未配置" yellow chip on first launch (no config).
- Open Settings → Transport tab present with all fields.
- "Test Connection" button is grey on macOS, active on Windows (if O-2 supplied).

- [ ] **Step 3: Open PR**

```bash
git push -u origin HEAD
gh pr create --title "Stage 8c: cockpit UI — Transport settings + HW probe + status chip" \
  --body "$(cat <<'EOF'
## Summary
- vector_hw_probe replaces the hardcoded _default_hw_probe stub
- SettingsDialog gains a Transport tab with Test Connection
- Toolbar carries a live transport status chip

## Open items (operator)
- O-2 Vector app_name on real Windows test PC: blocks PR-4 (bench validation)
- O-1, O-3, O-4, O-5: all needed for PR-4

## Test plan
- [x] pytest tests/test_vector_hw_probe.py
- [x] pytest tests/ui/test_settings_transport_tab.py
- [x] pytest tests/ui/test_main_window_transport_chip.py
- [x] cockpit --demo on macOS shows yellow chip and Settings tab
EOF
)"
```

---

## PR-4: Bench Validation (Operator deps: O-1, O-2, O-3, O-4, O-5 ALL required)

### Task 19: Bench validation runbook

**Files:**
- Create: `docs/analyzer/acquisition/runbooks/2026-05-17-stage-8-bench-validation.md`

**Operator deps:** none for writing the runbook; ALL for executing it.

- [ ] **Step 1: Write the runbook**

Create `docs/analyzer/acquisition/runbooks/2026-05-17-stage-8-bench-validation.md`:

```markdown
# Stage 8 Bench Validation Runbook

**Purpose.** Verify that `VectorXcpRecorderBackend` records valid MF4
from a real ECU before declaring Stage 8 done. Run on Windows + Vector
hardware + powered ECU.

## Pre-flight

- [ ] **O-1**: A2L on local disk; note path. `IF_DATA XCP` block visible.
- [ ] **O-2**: Vector Hardware Configurator opens; note `app_name` and
  channel for the bench. Hardware (VN1610 / VN1630 / VN1640) connected
  and recognized.
- [ ] **O-3**: Confirm XCP slave authentication state. If seed&key on,
  place the DLL at a path you'll enter in Settings → Transport →
  Seed&Key DLL.
- [ ] **O-4**: Bench / ECU powered, CAN harness terminated, vehicle key
  in run position (if applicable).
- [ ] **O-5**: Decided whether first session is classic CAN or CAN-FD.
  Recommended: classic CAN 500k first.
- [ ] `pip install python-can[vector] pyxcp` succeeded on this PC.

## Test sequence

### Step 1 — Cold connection
1. Launch cockpit: `python -m mf4_analyzer.acquisition_ui`.
2. Open Settings → Transport. Enter app_name, channel, bitrate from O-2.
3. Click **Test Connection**.
4. **Expected**: green toast "OK · driver vX.Y.Z".
5. **If red**: copy the error verbatim; consult the §Common errors
   section below; fix and retry.

### Step 2 — Load A2L
1. Cockpit toolbar "选择 A2L" → pick the file from O-1.
2. Left pane populates with measurement tree.
3. "有 DAQ" chip should be **enabled** (greyed = IF_DATA missing — file a
   bug if you expected events).

### Step 3 — Three-measurement smoke (10 ms event)
1. Pick 3 measurements all on the "10ms" event (or whatever the ECU's
   fastest DAQ event is).
2. Click Record. Wait 30 s. Click Stop.
3. Review Modal opens. Click "在 Analyzer 打开".
4. Analyzer must show 3 channels. Each channel: ~3000 samples
   (30 s × 100 Hz, ±5%).
5. **Pass**: tick this step.

### Step 4 — Twelve-measurement two-event
1. Pick 8 measurements on "10ms" + 4 on "100ms".
2. Record 60 s.
3. Analyzer: 12 channels. The 8 "10ms" channels ≈ 6000 samples each;
   the 4 "100ms" channels ≈ 600 samples each.

### Step 5 — Cross-hardware
Repeat Step 3 once on each VN model available (VN1610, VN1630, VN1640).
Reuse the same app_name; physically swap the hardware in Vector
Hardware Configurator between runs.

### Step 6 — CAN-FD (if O-5 = CAN-FD)
1. Settings → Transport → check "CAN-FD". Set data_bitrate from O-5.
2. Test Connection → green.
3. Repeat Step 4 but with 24 measurements (CAN-FD's larger MAX_DTO
   permits this in a single ODT per event).

## Common errors

| Toast text | Cause | Fix |
|---|---|---|
| "vxlapi DLL not loadable" | Vector driver not installed | Install Vector Hardware Configurator |
| "Vector application 'Python' not configured" | app_name doesn't exist in Vector Hardware Config | Open Vector Hardware Configurator, create the application slot |
| "channel N not present" | Channel number exceeds installed channel count | Decrement channel until match |
| "XCP CONNECT failed: no response" | ECU not powered, wrong CAN ID, wrong bitrate | Re-check power, A2L `CAN_ID_MASTER`, bitrate matches ECU |
| "negative XCP response: pid=0xFE, code=0x35" | DAQ list exhausted | Reduce selection count |
| "Seed&Key 失败" | DLL path wrong or bitness mismatch | Verify path, confirm 64-bit DLL for 64-bit Python |

## Acceptance gate

All of Step 3, Step 4, Step 5 (at least one HW model), and Step 6 (if
O-5 = CAN-FD) green at least once. File the captured MF4s under
`docs/analyzer/acquisition/evidence/stage-8/<YYYY-MM-DD>/`.

## After acceptance

- [ ] Tag the merge commit `stage-8-bench-validated`
- [ ] Update `MEMORY.md` with a note linking to this runbook
- [ ] Close all open O-* items in the parent spec
```

- [ ] **Step 2: Commit**

```bash
git add docs/analyzer/acquisition/runbooks/
git commit -m "docs(acquisition): Stage 8 bench validation runbook"
```

---

### Task 20: Hardware acceptance execution + bug fixes

**Files:** (will be discovered on-site)

**Operator deps:** ALL of O-1, O-2, O-3, O-4, O-5.

- [ ] **Step 1: Operator executes the runbook**

Operator runs through `docs/analyzer/acquisition/runbooks/2026-05-17-stage-8-bench-validation.md`.

For each FAIL, operator captures:
- Toast / dialog text verbatim
- Cockpit console / Python stdout
- The relevant A2L excerpt
- Vector Hardware Configurator screenshot

- [ ] **Step 2: Triage each failure**

For every failure, classify:
- **A2L dialect** → extend `_*_TOKENS` in `ifdata_xcp.py`; add fixture; new test.
- **DAQ alloc rejection** → inspect ECU response code; adjust `XcpDaqSession.start` or `DaqMap` packing.
- **Decoding mismatch** → debug `dto_decode` against captured raw frames.
- **Vector driver issue** → not our code; resolve in Vector Hardware Configurator.

- [ ] **Step 3: TDD each fix**

For each code-side fix:
1. Add a failing test that reproduces (using captured bytes as fixture).
2. Apply the fix.
3. Verify green.
4. Commit each as: `fix(acquisition): <one-line description from bench>`.

- [ ] **Step 4: Update runbook with new common-errors rows**

Append to the runbook's "Common errors" table any new failure modes
encountered during validation, so the next operator finds them.

- [ ] **Step 5: Run final acceptance**

Re-run the full runbook end-to-end. All steps green.

- [ ] **Step 6: Tag the release**

```bash
git tag stage-8-bench-validated
git push --tags
```

- [ ] **Step 7: Update MEMORY.md**

Add an entry pointing to the runbook and the merged PRs.

- [ ] **Step 8: Open final PR**

```bash
gh pr create --title "Stage 8d: bench validation runbook + on-vehicle fixes" \
  --body "$(cat <<'EOF'
## Summary
- Runbook for Stage 8 acceptance on Windows + Vector + ECU
- Bug fixes discovered during on-bench execution (per commits)

## Open items
- All resolved.

## Evidence
- See docs/analyzer/acquisition/evidence/stage-8/<date>/

## Test plan
- [x] All four steps of the runbook green on at least one VN model
- [x] CAN-FD path verified (if O-5 selected CAN-FD)
- [x] Cross-hardware verification on VN1610 / VN1630 / VN1640
EOF
)"
```

---

## Self-Review Checklist (run after the plan is written, before handoff)

**Spec coverage:**
- §0 Open items → re-surfaced atop every PR section ✅
- §1 Goals (Vector backend replacing stub) → PR-2 Task 12 ✅
- §2 Architecture (IfDataXcpParser, XcpDaqSession, DaqMap, dto_decode, vector_hw_probe) → Tasks 3, 11, 9, 10, 15 ✅
- §3 Dependencies → Task 1 ✅
- §4 Data model (IfDataXcp, DaqMap, TransportConfig, schema v2) → Tasks 2, 9, 6, 7 ✅
- §5 Backend lifecycle (start/poll/stop) → Tasks 12, 13 ✅
- §6 DTO parsing → Task 10 ✅
- §7 Health probe → Task 15 ✅
- §8 UI (Settings tab + status chip) → Tasks 16, 17 ✅
- §9 Test strategy (pure logic, mock transport, hardware acceptance) → Tasks 2-13, 15, 19, 20 ✅
- §10 Error handling (RecorderBackendUnavailableError, RecorderStartError, XcpConnectError, XcpAuthError, DaqAllocError) → defined in Tasks 11, 12 ✅
- §11 Migration v1→v2 → Task 7 ✅
- §12 Risks → covered in runbook common errors (Task 19) ✅
- §13 Acceptance criteria → Task 20 ✅

**Placeholder scan:** no "TODO" / "TBD" inside task steps. (Two references to "Stage 8b TODO" inside Task 12's code comment are intentional — they get resolved within the same PR by Task 13.)

**Type consistency:**
- `IfDataXcp` field names: identical across Task 2, 3, 4, 9, 11, 12 ✅
- `OdtEntry` adds `address` field in Task 11 Step 4; downstream Tasks 10, 12, 13 reference `entry.address` — consistent ✅
- `TransportConfig` field names: identical Task 6, 7, 15, 16, 17 ✅
- `vector_hw_probe(transport)` signature: same Task 15, 16 ✅
