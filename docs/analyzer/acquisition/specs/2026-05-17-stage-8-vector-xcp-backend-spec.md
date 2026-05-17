# Stage 8 — Production Vector + XCP/DAQ Backend (Spec)

**Author:** main Claude
**Date:** 2026-05-17 (v2 — Codex adversarial-review errata)
**Status:** Draft, pending user review
**Revision history:**
- v1 (2026-05-17, morning): initial spec.
- v2 (2026-05-17, afternoon): Codex adversarial-review surfaced 6 contract drifts
  between this spec and the live dataclasses
  (`SelectedMeasurement`, `BackendStatus`, `HwHealth`,
  `MeasurementSummary.available_events`). All six are addressed in §0
  "Errata" and the bodies of §4.2, §5, §7, §8.1, §10 below.

**Supersedes:** the `VectorXcpRecorderBackend` placeholder in
[`mf4_analyzer/acquisition_capture/backends.py:418-456`](../../../../mf4_analyzer/acquisition_capture/backends.py) and the
"Stage 8 deferred" notes at
[`docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md:502, 676`](2026-05-15-acquisition-cockpit-ui-spec.md).

---

## 0. OPEN ITEMS — REQUIRES OPERATOR INPUT BEFORE WORK CAN PROCEED

These items block forward motion. They are tracked here and re-surfaced at
the start of every plan stage so they don't get forgotten in PRs.

| # | Open item | Why it blocks | Status |
|---|---|---|---|
| **O-1** | **Real A2L file (with `IF_DATA XCP` block)** from the target ECU | Without it I cannot anchor field-name dialects, MAX_CTO/MAX_DTO actual values, DAQ event names/rates, or BYTE_ORDER. spec field names below are written to the ASAM 1.6.1 standard; real ECUs deviate. | ⏳ Operator to supply (any A2L from a recent program is fine for first pass) |
| **O-2** | **Vector Hardware Configurator `app_name`** currently used on the test bench | python-can vector backend selects the device via `(app_name, channel)` tuple, not by part number. We have to know which application slot is bound. | ⏳ Operator to read off Vector Hardware Config dialog on the Windows test PC |
| **O-3** | **Target ECU XCP slave authentication state** (seed&key on/off) | If seed&key is on, we need the vendor's `XCP_SeedAndKey.dll` (Windows) and which `GET_SEED` resource it gates (CAL/PAG, DAQ, PGM, STIM). If off (open-XCP, typical on dev ECUs), we skip the UNLOCK flow entirely. | ⏳ Operator to check with ECU vendor or attempt CONNECT and inspect `RESOURCE` byte |
| **O-4** | **Bench access for end-to-end validation** | Mock unit tests can verify ~90% of code correctness. The last 10% (real ECU accepts our DAQ config, ODT byte layout matches, no PHY-layer dropouts at sustained rate) only validates on hardware. | ⏳ Operator schedules HIL/vehicle session for PR-3 and PR-4 acceptance |
| **O-5** | **Decision on CAN-FD usage for first vehicle test** | Architecture supports both; default choice (classic CAN 500k) is conservative. If the ECU's XCP slave is CAN-FD-capable we get 8× per-DTO capacity. | ⏳ Operator picks "classic CAN first" (recommended) or "go CAN-FD from start" |

**Re-surfacing rule:** every plan stage's "Pre-flight" section will list the
subset of O-1..O-5 it actually depends on, and the stage cannot start until
those rows are ✅. Stages with no O- dependency (e.g. pure unit-tested
parsing work) proceed in parallel.

### 0.1 Errata fixed in v2 (Codex adversarial-review, 2026-05-17)

| # | Issue | Where | Fix landing in |
|---|---|---|---|
| **E-1** (critical) | `MeasurementSummary.available_events` and `A2LSummary.measurement_events` were left empty by the planned `load_measurement_summary` even though `LeftPane.current_selection()` derives `SelectedMeasurement.event` from `available_events[0]`. Real cockpit selections would carry `event=None`, and the planned `build_daq_map` would then raise on the empty event name. | spec §4.1/§2 diagram; plan Task 5 | spec §4.1 + plan Task 5 now mandates per-measurement IF_DATA walk + a non-skipped synthetic-A2L test |
| **E-2** (critical) | Planned `build_daq_map` read `sel.size_bytes` and `sel.datatype`, but the live `SelectedMeasurement` dataclass at `mf4_analyzer/acquisition_capture/session.py:24-45` has neither. | spec §4.2; plan Task 9 | spec §4.2 rewritten to take a `measurements: Mapping[str, MeasurementSummary]` lookup; `OdtEntry.size`/`datatype`/`address` source from `MeasurementSummary.datatype` + `SelectedMeasurement.address_hex` |
| **E-3** (high) | Planned Vector `BackendStatus(...)` used `dropped_count=...` but the live dataclass at `backends.py:41-46` is `BackendStatus(started, rx_count, bus_error_count, queue_overflow_count, last_error)`, and `CaptureController._build_summary` reads `queue_overflow_count` and `bus_error_count` for the sidecar. | spec §5.4/§5.5; plan Task 12 | Both now spell the 5-field shape; "dropped DTOs" map to `queue_overflow_count`, bus errors increment `bus_error_count` |
| **E-4** (high) | Spec §8.1 already says Test Connection must do XCP CONNECT/DISCONNECT, but plan Task 16 wired the button only to `vector_hw_probe()`, so the button could go green while XCP would fail immediately. | plan Task 16 | spec §8.1 expanded; plan Task 16 split into hw-probe + `test_xcp_connection` stages with a no-A2L-loaded disabled state |
| **E-5** (high) | Spec §5.2 step 4 mentions Seed&Key but the plan had no implementation task — `XcpAuthError` was declared but never raised. | plan PR-2 | spec §5.2 step 4 expanded; new plan Task 11a "Seed&Key auth flow" with locked-resource mock tests |
| **E-6** (medium) | Planned `vector_hw_probe()` returned `HwHealth(ok=False, error=...)` without the required `channel_count` and `last_probe_ts` fields. Spec §7 ¶2 also said macOS chip is "yellow", but `level_hw` returns red for any non-null error and existing `probe_hw_macos_stub` tests pin macOS to red. | spec §7; plan Task 15 | spec §7 ¶2 changed to "red on non-Windows, matching current `level_hw` semantics"; plan Task 15 fills every `HwHealth(...)` with `channel_count` and `last_probe_ts` |

---

## 1. Goal & Non-Goals

**Goal.** Replace the `VectorXcpRecorderBackend` stub with a production
backend that, on Windows with a Vector CAN interface and a powered ECU,
records XCP DAQ samples to an MF4 file via the existing capture pipeline.

**In scope:**

- Structured parsing of `IF_DATA XCP` in A2L, replacing the
  `re.findall` grep at [`scripts/probe_a2l_dbc.py:51`](../../../../scripts/probe_a2l_dbc.py).
- DAQ list construction and configuration (`ALLOC_DAQ`, `WRITE_DAQ`,
  `SET_DAQ_LIST_MODE`, `START_STOP_SYNCH`) using `pyxcp` as the protocol layer.
- DAQ DTO frame parsing (PID → ODT → measurement values), feeding the
  existing `RecorderBackend.poll()` channel.
- Hardware health probe replacing `_default_hw_probe` at
  [`mf4_analyzer/acquisition_capture/health.py:202-214`](../../../../mf4_analyzer/acquisition_capture/health.py).
- Cockpit Settings dialog extension for transport configuration (Vector
  `app_name`/channel/bitrate/CAN-FD toggle) with persistence into
  `acquisition_config.yaml`.
- Cockpit toolbar "transport status" angle chip showing connected hardware.
- Stage 8 acceptance criteria: end-to-end record on a real ECU produces
  an MF4 whose channel set equals `selected_measurements` and whose
  per-channel sample timestamps fall within the DAQ event's specified
  rate ± 5%.

**Out of scope:**

- DBC / raw-CAN-frame capture path (covered in a separate spec, est.
  Stage 9 if pursued).
- Calibration (write to ECU memory). This is XCP master *read-only* DAQ.
- STIM (master-to-ECU stimulus). DAQ-only.
- XCP-on-Ethernet / XCP-on-FlexRay. CAN/CAN-FD only.
- pyxcp's seed&key sample plugins — we either use the customer's DLL
  verbatim or assume no auth. We do NOT roll our own crypto.
- Replacement of `FakeRecorderBackend` and `ReplayRecorderBackend` —
  both stay as-is, used by macOS dev and CI.

---

## 2. Architectural Overview

```
┌─────────────────────────────────────────────────────────────┐
│ Cockpit (PyQt) — no change to state machine or modals       │
│   Settings dialog + transport status chip (NEW)             │
└─────────────────────────────────────────────────────────────┘
                          │ SessionConfig (extended)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ CaptureController — no change                                │
└─────────────────────────────────────────────────────────────┘
                          │ start(selected) / poll() / stop()
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ VectorXcpRecorderBackend  (NEW, replaces stub)               │
│   ┌──────────────────────────────────────────────────────┐  │
│   │  XcpDaqSession (NEW)                                  │  │
│   │   ├── connect() / disconnect()                        │  │
│   │   ├── allocate_daq_lists(selected, ifdata) → DaqMap   │  │
│   │   ├── start_synch()                                   │  │
│   │   └── poll_dtos() → list[(name, ts, value)]           │  │
│   └──────────────────────────────────────────────────────┘  │
│   ┌──────────────────────────────────────────────────────┐  │
│   │  pyxcp.Master + python-can.VectorBus (transport)      │  │
│   └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          │ uses
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ IfDataXcpParser (NEW)                                        │
│   parse(a2l_path) → IfDataXcp{cmd_id, resp_id, max_cto,      │
│                  max_dto, byte_order, timestamp_unit, ...}   │
│   + a2l_events.daq_events(a2l_path) extended to walk         │
│     IF_DATA DAQ_LIST_CAN_ID / DAQ_EVENT / ODT entries        │
└─────────────────────────────────────────────────────────────┘
                          │ feeds
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ a2l_probe (EXTENDED)                                         │
│   load_measurement_summary() fills in:                       │
│     • A2LSummary.event_capacity (Stage 2 stub → real)        │
│     • A2LSummary.measurement_events                          │
│     • A2LSummary.a2l_has_daq_events                          │
│     • MeasurementSummary.available_events                    │
└─────────────────────────────────────────────────────────────┘
```

The Mf4 writer, ring buffer, controller, ReviewModal, history tab — none
change. Stage 8 is a tightly-bounded "fill in the bottom of the stack"
project.

---

## 3. Dependency Additions

Add to `requirements.txt` under a `[windows-only]` extras section (or
similar; pip extras syntax TBD in plan):

```
python-can[vector]>=4.3.0
pyxcp>=0.22.0
```

**Both libraries lazy-import** inside the backend module — macOS dev and
CI workflows MUST continue passing without these installed. The cockpit
spec's lazy-import rule at
[`spec line 676`](2026-05-15-acquisition-cockpit-ui-spec.md) is preserved.

**No new C extensions.** Both libraries are pure Python over Vector's
`vxlapi` (DLL) which the Vector Hardware Configurator installer provides.

---

## 4. Data Model

### 4.1 `IfDataXcp` (NEW dataclass)

Structured view of the A2L's `IF_DATA XCP` transport block. Defined in
a new module `can_logger/p0/ifdata_xcp.py` and consumed by the backend.

```python
@dataclass(frozen=True)
class IfDataXcp:
    cmd_id: int                    # 11-bit or 29-bit CAN ID
    resp_id: int
    cmd_id_extended: bool
    resp_id_extended: bool
    can_fd: bool                   # IF_DATA CAN_FD block present?
    max_cto: int                   # Master->Slave max payload bytes
    max_dto: int                   # Slave->Master max payload bytes (DTO)
    byte_order: Literal["MSB_FIRST", "MSB_LAST"]
    address_granularity: Literal["BYTE", "WORD", "DWORD"]
    daq_timestamp_size: int        # 0, 1, 2, or 4 bytes
    daq_timestamp_unit: str        # "1NS", "10NS", "100NS", "1US", ...
    daq_timestamp_fixed: bool      # Fixed event vs per-DTO timestamp
    available_events: tuple[DaqEventInfo, ...]
    daq_processor: DaqProcessorInfo

@dataclass(frozen=True)
class DaqEventInfo:
    number: int                    # DAQ event channel number
    name: str                      # Long name (e.g. "10ms")
    cycle_time_ms: float           # Rate in milliseconds (0 = sporadic)
    max_odt_entries: int           # ODT_ENTRIES_COUNT
    properties: tuple[str, ...]    # e.g. ("DAQ",) or ("DAQ", "STIM")

@dataclass(frozen=True)
class DaqProcessorInfo:
    min_daq: int                   # DAQ_LIST_COUNT supported
    max_event_channel: int
    granularity_odt_entry_size_daq: int  # bytes per ODT entry slot
    overload_indication: str       # "EVENT", "MSB", "NONE"
```

Field names align with ASAM AML 1.6.1. **Operator-side dialect risk:** if
the real A2L from O-1 uses non-standard tokens (e.g. some Vector tooling
emits `DAQ_TIMESTAMP_FIXED_LENGTH` instead of plain `DAQ_TIMESTAMP_FIXED`),
the parser must tolerate them — we add token aliases as discovered, with
a regression test per alias.

**Per-measurement IF_DATA contract (v2, post-E-1 fix).** The Stage 8
parser MUST also walk each `MEASUREMENT` block's nested
`IF_DATA XCP DAQ_EVENT FIXED_EVENT_LIST EVENT <n>` entries (or
`AVAILABLE_EVENT_LIST` for non-fixed) and populate:

- `MeasurementSummary.available_events: tuple[str, ...]` — names of
  the DAQ events declared as compatible with that measurement (default
  empty tuple when the A2L does not associate this measurement with any
  event).
- `A2LSummary.measurement_events: Mapping[str, tuple[str, ...]]` —
  same data indexed by measurement name (for global lookups).

These fields are already defined on the dataclasses at
`can_logger/p0/a2l_probe.py:27-59` with `field(default_factory=...)`
empty defaults. Stage 3 wired the dataclass; Stage 8 fills them.

**Why this matters:** `LeftPane.current_selection()` at
`mf4_analyzer/acquisition_ui/widgets/left_pane.py:264-275` derives
`SelectedMeasurement.event` from `m.available_events[0]`. If
`available_events` stays empty, real cockpit selections carry
`event=None`, and §5.2 step 6's "Group `selected` by `event`"
collapses to a single empty-string bucket — `build_daq_map` then
raises `ValueError("Selected event '' not in A2L IF_DATA")` and
recording cannot start. A non-skipped synthetic-A2L test is mandated
in the plan (Task 5) to lock this contract before §5.2 is written.

### 4.2 `DaqMap` (NEW dataclass, runtime-built)

Produced by §5.2 step 7 and consumed by both `poll()` and `dto_decode`.
Pure data; no protocol calls.

```python
@dataclass(frozen=True)
class OdtEntry:
    measurement_name: str
    offset: int                    # byte offset within DTO payload (after PID + optional timestamp)
    size: int                      # bytes
    datatype: str                  # "u8" | "s8" | ... | "f64"
    address: int                   # ECU memory address from MEASUREMENT.ECU_ADDRESS
    scale_a: float = 1.0           # COMPU_METHOD linear: y = scale_a * x + scale_b
    scale_b: float = 0.0

@dataclass(frozen=True)
class DaqMap:
    pid_to_odt: Mapping[int, tuple[int, int]]   # pid → (daq_list_number, odt_index)
    entries: Mapping[tuple[int, int], tuple[OdtEntry, ...]]  # (daq, odt) → entries
    event_for_daq: Mapping[int, int]            # daq_list_number → event channel
```

**Source-of-truth contract (v2, post-E-2 fix):**
`build_daq_map` MUST NOT add fields to `SelectedMeasurement` —
`session.py:24-45` is a load-bearing public dataclass with serialization
contracts (Mf4Writer, sidecar JSON, replay round-trips). The builder
signature instead takes a per-name lookup into the A2L summary:

```python
def build_daq_map(
    selected: Sequence[SelectedMeasurement],
    ifdata: IfDataXcp,
    measurements: Mapping[str, MeasurementSummary],   # name → A2L record
) -> DaqMap: ...
```

Per `OdtEntry`:

| OdtEntry field | Source |
|---|---|
| `measurement_name` | `sel.name` |
| `datatype` | `measurements[sel.name].datatype` (already populated by Stage 3) |
| `size` | derived from `datatype` via `_size_from_datatype()` (canonical: u8/s8=1, u16/s16=2, u32/s32/f32=4, u64/s64/f64=8); unknown → fall back to `sel.payload_bytes` and emit a warning. |
| `address` | `int(sel.address_hex, 16)` (already on `SelectedMeasurement`) |
| `scale_a`, `scale_b` | linear `COMPU_METHOD` if present; default `(1.0, 0.0)` |
| `offset` | computed by the packer, after PID + optional timestamp |

If `measurements` is missing an entry for `sel.name`, raise
`ValueError(f"measurement {sel.name!r} not in A2L summary; cannot build DAQ map")`
— do NOT silently fall back to `payload_bytes` for the datatype, because
DTO decoding would produce garbage values.

Linear-only `scale_a/scale_b` is by design (see §6); non-linear
`COMPU_METHOD` becomes `(1.0, 0.0)` with a warning log entry.

### 4.3 `SessionConfig` additions

[`session.py:49-90`](../../../../mf4_analyzer/acquisition_capture/session.py) extends:

```python
@dataclass(frozen=True)
class SessionConfig:
    ...existing fields...
    transport: TransportConfig = field(default_factory=TransportConfig)

@dataclass(frozen=True)
class TransportConfig:
    app_name: str = "Python"           # Vector Hardware Configurator slot
    channel: int = 0
    can_fd: bool = False
    bitrate: int = 500_000
    data_bitrate: int = 2_000_000      # only used when can_fd=True
    sample_point: float = 75.0
    fd_sample_point: float = 70.0
    timeout_s: float = 1.0             # XCP command timeout
    seed_and_key_dll: str | None = None  # Windows path, None = no auth
```

`backend: str` whitelist (currently `{"fake", "replay", "vector"}`)
stays — we're filling in `"vector"` not adding a new enum value.

### 4.4 `acquisition_config.yaml` schema v2

```yaml
version: 2                        # bumped from 1
a2l_path: "..."
favorites: [...]
selection: [...]
transport:                        # NEW block
  app_name: "Python"
  channel: 0
  can_fd: false
  bitrate: 500000
  data_bitrate: 2000000
  sample_point: 75.0
  fd_sample_point: 70.0
  timeout_s: 1.0
  seed_and_key_dll: null
```

[`config_store.py`](../../../../mf4_analyzer/acquisition_capture/config_store.py)
adds `"transport"` to `ALLOWED_TOP_LEVEL` and a migration path
v1 → v2 that injects defaults.

---

## 5. Backend Lifecycle

`VectorXcpRecorderBackend` implements the `RecorderBackend` ABC at
[`backends.py:64-94`](../../../../mf4_analyzer/acquisition_capture/backends.py).
Every method MUST be safe to call from the controller thread; pyxcp's
master is held behind a `threading.Lock`.

### 5.1 `__init__(transport: TransportConfig, ifdata: IfDataXcp)`

- Validates Windows platform (`sys.platform == "win32"`); on other
  platforms raises `RecorderBackendUnavailableError` matching the
  current stub's behaviour.
- Lazy-imports `can` and `pyxcp.master.Master`.
- Stores config; does NOT open hardware yet.

### 5.2 `start(selected: tuple[SelectedMeasurement, ...]) -> None`

Sequence (each step on failure raises `RecorderStartError` with a
human-readable cause):

1. Open `can.interfaces.vector.VectorBus(app_name, channel, fd, bitrate, ...)`.
2. Instantiate `pyxcp.master.Master("can", config=...)`, pass the bus.
3. `master.connect()` → store `RESOURCE` byte for health reporting.
4. **Seed&Key authentication (v2, post-E-5 fix).** Inspect the
   `RESOURCE` byte returned by CONNECT. Bits per ASAM XCP 1.1.0
   §3.1.1.2: bit0=CAL/PAG, bit2=DAQ, bit4=STIM, bit5=PGM. For
   each bit that is set AND that we need for DAQ (the DAQ bit, and
   CAL/PAG only if we plan calibration — out of scope at Stage 8, so
   DAQ only):
   - If `transport.seed_and_key_dll is None`: raise
     `XcpAuthError("RESOURCE.DAQ locked but no seed&key DLL configured")`.
   - Else:
     - Validate the DLL path exists and matches Python's bitness
       (`ctypes.sizeof(ctypes.c_void_p) == 8` → 64-bit DLL required).
       On mismatch, raise `XcpAuthError("seed&key DLL bitness mismatch: ...")`.
     - `seed = master.getSeed(resource_id=0x02)` (DAQ resource).
     - Load DLL via `ctypes.WinDLL(path)`, look up the standard ASAP1B
       symbol `ASAP1A_XCP_ComputeKeyFromSeed` (signature per ASAM
       AE MCD-1 XCP Part 2: `(seed_len, seed_ptr, key_len_inout_ptr,
       key_ptr) -> int32`). On non-zero return raise
       `XcpAuthError("seed&key DLL rejected seed: code=...")`.
     - `master.unlock(resource_id=0x02, key=key_bytes)`. On negative
       XCP response raise `XcpAuthError("ECU rejected unlock: 0x...")`.
   If `RESOURCE.DAQ` bit is clear, skip the entire seed&key flow.
5. `master.getDaqProcessorInfo()` → cross-check `min_daq` and granularity
   match `ifdata`.
6. Group `selected` by `event` (from `MeasurementSummary.available_events`,
   which §4.1 v2 mandates is populated from per-MEASUREMENT IF_DATA).
7. For each event group:
   - `master.allocDaq(daq_list_number)`,
   - `master.allocOdt(daq, odt_count_for_event)`,
   - `master.allocOdtEntry(daq, odt, entry_count)`,
   - `master.setDaqPtr(daq, odt, entry)` and
     `master.writeDaq(bit_offset, size, address_extension, address)`
     for every measurement.
   - `master.setDaqListMode(mode=0x10, daq, event, prescaler, priority)`.
8. `master.startStopSynch(0x01)` — START_SELECTED.
9. Start an internal capture thread that reads DTOs off the bus and
   queues `(name, monotonic_ts, value)` tuples for `poll()` to drain.

The DAQ→measurement mapping built in step 7 is preserved as
`self._daq_map: DaqMap` so DTO parsing can look up which measurement
each ODT slot belongs to.

### 5.3 `poll() -> list[tuple[str, float, float]]`

Drains the internal queue. Returns the same `(channel_name, ts_s, value)`
shape as `FakeRecorderBackend` and `ReplayRecorderBackend` — no schema
change at the controller boundary.

Timestamps:
- If `ifdata.daq_timestamp_size > 0`: use the per-DTO ECU timestamp,
  scaled by `ifdata.daq_timestamp_unit`, rebased to capture session t=0.
- Else: synthesize from `time.monotonic()` at DTO RX time.

### 5.4 `stop() -> None`

1. `master.startStopSynch(0x00)` — STOP_SELECTED.
2. Join capture thread (1 s timeout, then mark daemon and abandon).
3. `master.disconnect()`.
4. `bus.shutdown()`.
5. Returns even on partial failure; final exception (if any) is logged
   to capture session log and surfaced via `status()`.

### 5.5 `status() -> BackendStatus` and `stop() -> BackendStatus`

**v2, post-E-3 fix:** both methods MUST return the existing 5-field
`BackendStatus` dataclass defined at `backends.py:41-46`:

```python
@dataclass
class BackendStatus:
    started: bool
    rx_count: int
    bus_error_count: int
    queue_overflow_count: int
    last_error: str | None = None
```

Field mapping for the Vector backend:

| BackendStatus field | Vector source |
|---|---|
| `started` | `self._session is not None and self._session.is_running()` |
| `rx_count` | total DTOs successfully decoded and queued for `poll()` |
| `bus_error_count` | `python-can` bus-error frames observed in the capture thread |
| `queue_overflow_count` | DTOs dropped because the poll queue exceeded `MAX_POLL_QUEUE` or the capture thread missed a DTO (was `dropped_count` in v1 spec) |
| `last_error` | most-recent exception string from CONNECT/DAQ/RX, or `None` |

Additional cockpit-only fields (`bus_open`, `xcp_connected`,
`daq_running`) are NOT on `BackendStatus`. They live on the cockpit's
transport chip via `vector_hw_probe()` + the live backend's last RX
timestamp, not on the controller-boundary status object. Adding them
to `BackendStatus` would break `CaptureController._build_summary` which
reads `queue_overflow_count` and `bus_error_count` for the sidecar.

`last_frame_monotonic()` stays a separate ABC method returning a `float | None`.

---

## 6. DTO Parsing

A separate pure-data module `mf4_analyzer/acquisition_capture/dto_decode.py`
holds the byte-level decoding, so it is unit-testable without hardware.

```python
def decode_dto(
    frame: bytes,
    daq_map: DaqMap,
    timestamp_size: int,
    timestamp_unit_ns: int,
    byte_order: ByteOrder,
    base_monotonic_s: float,
) -> Iterator[tuple[str, float, float]]: ...
```

Algorithm:

1. `pid = frame[0]` → look up `(daq_list, odt_index)` via
   `daq_map.pid_to_odt[pid]`.
2. Optional timestamp: next `timestamp_size` bytes, decoded per
   `byte_order`. `ts_s = base + (ts_raw * timestamp_unit_ns) / 1e9`.
3. For each `OdtEntry` in `daq_map.entries[(daq_list, odt_index)]`:
   slice `frame[entry.offset : entry.offset + entry.size]`, decode
   per `entry.datatype` + `byte_order`, apply A2L `COMPU_METHOD` linear
   scaling if present, yield `(entry.measurement_name, ts_s, value)`.

`COMPU_METHOD` evaluation is intentionally minimal at Stage 8 — only
`LINEAR` (`y = ax + b`) and `RAT_FUNC` with rational coefficients
`[0, a, b, 0, 0, c]` (also linear). Non-linear conversions surface as a
raw integer and a warning log entry; full conversion is deferred to a
later stage with no MVP impact (downstream analyzer can re-apply).

---

## 7. Health Probe

Replace `_default_hw_probe` at
[`health.py:202-214`](../../../../mf4_analyzer/acquisition_capture/health.py) with
`vector_hw_probe(transport_config) -> HwHealth`. The probe MUST construct
`HwHealth` with every field the live dataclass at `health.py:42-47`
requires (v2, post-E-6 fix):

```python
@dataclass(frozen=True)
class HwHealth:
    ok: bool
    driver_version: str | None
    channel_count: int        # REQUIRED — must be set on every return path
    last_probe_ts: float      # REQUIRED — monotonic seconds at probe time
    error: str | None = None
```

| Subcheck | Source | Effect on HwHealth |
|---|---|---|
| Vector driver DLL loadable | `ctypes.WinDLL("vxlapi64.dll")` returns object | `ok` requires this; `error` if missing |
| Application slot exists | `can.interfaces.vector.canlib.get_application_config(app_name)` | `error` if `LookupError` |
| Channel index in range | iterate `get_channel_count()` results | populates `channel_count`; `error` if `transport.channel >= channel_count` |
| Driver version | parse from DLL info struct | populates `driver_version` |
| Probe timestamp | `time.monotonic()` at the start of the probe | populates `last_probe_ts` |

The probe runs once at cockpit launch and on every "Reconnect" action.

**Non-Windows behavior (v2, post-E-6 fix):** on macOS / Linux the probe
returns
```python
HwHealth(
    ok=False,
    driver_version=None,
    channel_count=0,
    last_probe_ts=time.monotonic(),
    error="Vector backend requires Windows",
)
```
and the chip is **red** (not yellow). This matches the existing
`level_hw()` semantics at `health.py:87-101` — any non-null `error`
returns red — and the existing `probe_hw_macos_stub` red expectation
locked in by `tests/test_acquisition_capture_health.py::test_hw_macos_stub_levels_to_red`.
Introducing an "expected unavailability" yellow state would require
adding `expected_unavailable: bool` to `HwHealth` and revising
`level_hw`; that is deliberately out of Stage 8 scope (operators
running the Vector path are on Windows, so yellow vs red on macOS
is cosmetic).

XCP / DAQ chips: `_xcp_probe` and `_daq_probe` get fed by the live
backend's `status()` once recording is in progress; until then they
show "off" (gray), which is correct per spec §Health Snapshot Model.

---

## 8. UI Changes

### 8.1 Settings Dialog (extends [`settings_dialog.py`](../../../../mf4_analyzer/acquisition_ui/settings_dialog.py))

New tab "传输 / Transport":

```
┌─ Transport ──────────────────────────────────────┐
│ Vector Application: [ Python      ▼ ]            │
│ Channel:            [ 0  ▼ ]                     │
│ ☐ CAN-FD                                          │
│ Bitrate (kbps):     [ 500   ▼ ]                  │
│   Data bitrate:     [ 2000  ▼ ]  (CAN-FD only)   │
│ Seed&Key DLL:       [ (none)        ] [Browse]   │
│ Timeout (ms):       [ 1000 ]                     │
│                                                  │
│  [ Test Connection ]      [ OK ]  [ Cancel ]     │
└──────────────────────────────────────────────────┘
```

"Test Connection" button (v2, post-E-4 fix — two-stage probe):

- **Stage A — `vector_hw_probe(transport)`** (driver/DLL/channel exists)
  always runs first. If it returns `ok=False`, the toast is red and
  shows `error`; stage B is skipped.
- **Stage B — `test_xcp_connection(transport, ifdata)`** (real XCP
  CONNECT/DISCONNECT on the bus). Must:
  1. Open `VectorBus(...)`, abort with `"CAN 总线打开失败 (bus open)"`
     on failure.
  2. Instantiate `pyxcp.master.Master`, call `connect()` with a
     `transport.timeout_s` deadline.
  3. Capture the `RESOURCE` byte from the CONNECT response.
  4. If `transport.seed_and_key_dll` is configured, run the same
     seed&key flow as §5.2 step 4 to surface auth failures here too.
  5. `disconnect()` and `bus.shutdown()` in a `finally` block so
     bench state is left clean.
- Disabled states:
  - macOS / Linux: button disabled, tooltip "Vector 仅在 Windows 可用".
  - No A2L loaded (no `IfDataXcp` available): button disabled, tooltip
    "请先选择 A2L 文件 — XCP 连接测试需要 CAN ID / MAX_DTO 信息".
- Result toast text:
  - Green: `"OK · driver {version} · RESOURCE=0x{byte:02X} · {latency_ms} ms"`.
  - Red on auth: `"Seed&Key 失败：{reason}"`.
  - Red on no response: `"ECU 未在 {timeout_ms} ms 内响应 (cmd_id=0x{id:03X})"`.
  - Red on bus error: the underlying `VectorError.message`.
- The button is the operator's primary debug tool when on-vehicle
  things go sideways before hitting Record.

### 8.2 Transport Status Chip (extends [`main_window.py` toolbar](../../../../mf4_analyzer/acquisition_ui/main_window.py))

A compact read-only chip showing
`VN1640 · App=Python · Ch=0 · CAN 500k` (the device model is read from
the Vector driver, NOT user-typed — operator can visually confirm
which physical box they're talking to). Click opens the Settings →
Transport tab.

When disconnected: chip text reads `传输未配置` and is yellow.

---

## 9. Test Strategy

Three tiers:

### 9.1 Pure-logic unit tests (no hardware, run on macOS/CI)

- `test_ifdata_xcp_parser.py`: 8-10 sample A2L blocks covering
  classic CAN, CAN-FD, signed/unsigned timestamp unit tokens, single
  vs multi-event ECUs. Asserts every `IfDataXcp` field.
- `test_dto_decode.py`: hand-crafted DTO byte streams → expected
  `(name, ts, value)` tuples. Includes timestamp wraparound, big/little
  endian, multi-ODT frames.
- `test_daq_map_builder.py`: given a list of `SelectedMeasurement` and
  an `IfDataXcp`, assert the produced `DaqMap` has correct ODT
  packing (no entry crosses MAX_DTO, all events grouped, ODT entries
  obey `granularity_odt_entry_size_daq`).
- `test_a2l_probe_events.py`: extend existing
  `tests/test_acquisition_a2l_events.py` to verify
  `available_events` / `event_capacity` / `measurement_events` /
  `a2l_has_daq_events` are populated when IF_DATA is present.

### 9.2 Mock-transport backend tests (no hardware, run on macOS/CI)

- Inject a `FakeCanBus` that records `send()` calls and yields canned
  `recv()` results.
- `test_vector_xcp_backend_lifecycle.py`: `start()` issues the expected
  CONNECT → ALLOC_DAQ × N → WRITE_DAQ × M → START_STOP_SYNCH command
  sequence. Verify byte-for-byte against the pyxcp protocol-level mock.
- `test_vector_xcp_backend_poll.py`: pre-load the fake bus with 1000
  DTO frames; `poll()` must yield 1000 `(name, ts, value)` tuples in
  order, with no drops and correct values.
- `test_vector_xcp_backend_stop.py`: clean shutdown after error path
  (CAN send timeout, negative XCP response, ECU mid-recording reset).

### 9.3 Hardware acceptance test (manual, on Windows + real ECU)

A checklist document `docs/analyzer/acquisition/runbooks/2026-05-17-stage-8-bench-validation.md`
created in PR-3, executed by operator:

1. Connect VN16xx + ECU, power up.
2. Launch cockpit, open Settings → Transport → "Test Connection". Expect
   green toast with RESOURCE byte.
3. Pick A2L, select 3 measurements on the 10 ms event.
4. Hit Record for 30 s.
5. Verify MF4 written, sidecar JSON populated.
6. Open MF4 in analyzer. Channel count == 3. Each channel has ~3000
   samples (30 s × 100 Hz, ±5% tolerance).
7. Repeat with 12 measurements across two events (10 ms + 100 ms).
8. Repeat with CAN-FD if O-5 = "CAN-FD".

Acceptance gate: all 8 steps green at least once on each VN model
operator has (1610, 1630, 1640) for CAN; CAN-FD validated on at least
one model.

---

## 10. Error Handling

A taxonomy spec'd here to keep error paths consistent:

| Exception | Where raised | UI surface |
|---|---|---|
| `RecorderBackendUnavailableError` | `__init__` on non-Windows | Cockpit disables "vector" backend in Settings, falls back to fake |
| `VectorBusOpenError` | `start()` step 1 | "Test Connection" toast red; cockpit Health HW chip red |
| `XcpConnectError` | `start()` step 3 | Health XCP chip red, status bar "ECU 未响应" |
| `XcpAuthError` | `start()` step 4 | Modal dialog "Seed&Key 失败：<reason>" — likely needs O-3 |
| `DaqAllocError` | `start()` step 7 | Modal "ECU 拒绝 DAQ 配置 (code 0x..)", show suggested fix |
| `RecorderStartError` | wraps any of above | Cockpit stays in ConnectedIdle, button label resets |
| `DtoDecodeError` | DTO parsing | Logged to session log; sample dropped; `dropped_count++` |

All raise paths increment the appropriate `RecHealth` counter so the
operator sees status degrade visibly rather than getting silent zeros.

---

## 11. Persistence Migration

`acquisition_config.yaml` v1 (no `transport` block) on disk → v2 (with
defaults injected):

[`config_store.py`](../../../../mf4_analyzer/acquisition_capture/config_store.py)
gains a migration step:

```python
def _migrate_v1_to_v2(parsed: dict) -> dict:
    if parsed.get("version") == 2:
        return parsed
    parsed["version"] = 2
    parsed.setdefault("transport", asdict(TransportConfig()))
    return parsed
```

Migration is **non-destructive** — old v1 files keep working with
default transport values. No backwards-incompatible removals.

---

## 12. Risks & Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| A2L IF_DATA dialect mismatch | High | Tolerant parser + per-dialect regression tests; expect 2-3 iterations on first real A2L (O-1) |
| ECU rejects DAQ config (overload, slot exhaustion) | Medium | Preflight estimate `daq_slot_usage()` already exists; surface red before Record. Error code from `DaqAllocError` mapped to actionable message |
| Seed&Key DLL ABI mismatch (32-bit vs 64-bit) | Medium | Detect Python interpreter bitness, require matching DLL; error message names the mismatch |
| Vector driver version skew | Low-Medium | Pin minimum `python-can[vector]` version; HW probe surfaces driver version in chip tooltip |
| CAN-FD timing parameters wrong | Medium | Default to widely-known values (Bosch sample point 75%/70%); make all 4 timing fields editable in Settings; mitigation O-5 = start with classic CAN |
| Long-session memory growth (existing issue not new in Stage 8) | Medium | Out of scope; existing writer concern. Document in runbook to cap test duration at 30 min until incremental flush ships |

---

## 13. Acceptance Criteria

Stage 8 is **DONE** when:

1. All §9.1 and §9.2 tests pass green on macOS CI.
2. `requirements.txt` extras install cleanly on a Windows machine
   without manual DLL fiddling beyond Vector Hardware Configurator
   being pre-installed.
3. §9.3 hardware acceptance checklist green on at least one VN model
   for classic CAN.
4. `VectorXcpRecorderBackend.__init__` no longer raises
   `NotImplementedError`.
5. `_default_hw_probe` is removed; `vector_hw_probe` is wired into
   `HealthAggregator` on Windows.
6. Cockpit Settings → Transport tab present and functional.
7. Transport status chip present in cockpit toolbar.
8. `acquisition_config.yaml` migration v1→v2 lossless (round-trip test).
9. `MF4 Data Analyzer V1.py` opens a Stage-8-recorded MF4 with no error
   and shows all selected channels in the inspector tree.

---

## 14. Cross-References

- Cockpit UI spec: [`2026-05-15-acquisition-cockpit-ui-spec.md`](2026-05-15-acquisition-cockpit-ui-spec.md)
- P0 hardware evidence baseline: [`2026-05-14-p0-spec.md`](2026-05-14-p0-spec.md)
- Existing P0 raw probe (stays in repo as diagnostic):
  [`can_logger/p0/xcp_short_upload_probe.py`](../../../../can_logger/p0/xcp_short_upload_probe.py)
- Backend ABC: [`mf4_analyzer/acquisition_capture/backends.py:64-94`](../../../../mf4_analyzer/acquisition_capture/backends.py)

---

## 15. Re-Surfacing OPEN ITEMS

(See §0 for full table. Listing here so the spec's last words remind
the reader:)

- **O-1** Real A2L file with `IF_DATA XCP` block — operator
- **O-2** Vector `app_name` on test PC — operator
- **O-3** ECU XCP authentication state (and DLL if needed) — operator
- **O-4** HIL/vehicle bench access for PR-3, PR-4 — operator
- **O-5** Classic CAN vs CAN-FD for first vehicle test — operator decision

No PR can merge with any of its declared O- dependencies still ⏳.
