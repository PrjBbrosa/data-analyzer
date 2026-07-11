# pyxcp 0.29 / Vector XCP 真实采集准备度 Spec

Date: 2026-07-11
Status: Approved for implementation; **hardware acceptance pending**
Plan: `docs/analyzer/acquisition/plans/2026-07-11-pyxcp-029-vector-xcp-readiness-implementation.md`
Operator action board:
`docs/analyzer/acquisition/reports/2026-07-11-vector-xcp-operator-action-board.html`
Corrects:

- `docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md`
- `docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md`
- `docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md`

This spec replaces only the real Vector/XCP runtime, DAQ-programming, DTO-ingress,
recording-lifecycle, packaging, and bench-acceptance contracts in those artifacts.
It does not supersede later Cockpit visual/layout specifications, the FAKE/replay
path, or analyzer-side MF4 behavior.

## 1. Decision

The current real backend is **NO-GO for vehicle recording** even though the
hardware-free suite is green. The reason is not merely that it has not yet been
tried on a vehicle: several calls in the production path do not match the pinned
pyxcp API, and the DTO receive path uses an XCP upload helper as if it were a DAQ
frame queue.

The release target is therefore a deliberately narrow, pinned stack:

- Windows x64;
- Vector VN16xx hardware with a locally installed Vector driver;
- `python-can==4.6.1` for the first validated release;
- `pyxcp==0.29.10` for the first validated release;
- A2L containing usable `IF_DATA XCP` for the selected ECU;
- dynamic DAQ over classic CAN first; CAN-FD is a later conditional gate;
- one pyxcp-owned CAN transport per live ECU session;
- explicit bounded DAQ frame policy; no `Master.fetch()` DTO polling;
- a persistent connected/streaming session to which MF4 recording is attached
  and detached without restarting XCP/DAQ.

`python-can` and `pyxcp` may be upgraded only in a separate compatibility change
that reruns the API contract, source-mode bench, packaged-mode bench, and soak
gates in this spec.

## 2. Evidence Baseline

### 2.1 What is already usable

- Cockpit UI, state machine, FAKE backend, replay path, writer, review modal, and
  MF4 open-back flow are implemented.
- Both supplied ERD6 A2Ls parse successfully. The A-side A2L currently yields
  323 measurements, classic-CAN XCP command/response IDs `0x6C7/0x6C6`,
  `MAX_CTO=8`, `MAX_DTO=8`, little-endian byte order, five DAQ events, and no
  ECU DAQ timestamp.
- A previous Windows action-board run established that the Vector VN1630A,
  driver, application slot `Python`, channel 0, and 500 kbit/s bus could be
  opened. That is hardware-access evidence only; it is not end-to-end DAQ or MF4
  evidence.
- The focused macOS suite at spec time was green: 124 tests covering parser,
  mapping, decode, backend lifecycle, probes, native-import boundaries, and
  Cockpit session plumbing.

### 2.2 Why that evidence is insufficient

The current production path contains the following mismatches:

| Area | Current implementation | Required correction |
| --- | --- | --- |
| Master construction | `backends.py:545-547` and `vector_hw_probe.py:186-190` pass a plain `{"bus": bus}` dictionary and do not bind the A2L command/response IDs | Construct the pinned pyxcp configuration object with CAN layer, Vector parameters, timeout, command ID, response ID, CAN/CAN-FD mode, and ownership defined by this spec |
| Authentication | `xcp_auth.py:39-77` treats CONNECT `resource` availability as protection state and calls `getSeed` / `unlock` with unsupported keywords | Read protection through GET_STATUS/current protection status; unlock only DAQ with the pinned API or a verified `cond_unlock("DAQ")` adapter |
| DAQ allocation | `xcp_daq_session.py:75-100` calls `allocDaq` per list, uses unsupported keywords, hard-codes timestamp mode, and starts lists without selecting them | Follow the complete dynamic-DAQ sequence in §6 and capture each list's ECU-assigned `firstPid` |
| PID map | `daq_map.py:91-109` invents PIDs beginning at zero | Bind decode map only after `startStopDaqList(SELECT)` returns `firstPid` |
| DTO receive | `backends.py:642-656` calls `Master.fetch(timeout=...)` or a hypothetical transport `fetch` | Supply an explicit bounded `FrameAcquisitionPolicy`; DAQ frames enter through the policy's callback/queue |
| Concurrency | `backends.py:518,565-568,632` shares an unbounded list between threads and drains it by copy-then-clear | Use bounded thread-safe queues with atomic drain and separate frame/sample overflow counters |
| Record lifecycle | `_capture_session_mixin.py:72-85` stops the live backend and starts it again at Record | Keep the already-proven live session running; Record attaches writer/controller consumption to that session |
| Health/preflight | `_connection_mixin.py:271-288` returns synthetic CAN/XCP/DAQ facts; `window.py:939-957` fabricates capacity 32 | Display evidence from the actual runtime and A2L/ECU query; unknown stays unknown |
| Physical values | `daq_map.py:20-21,125-133` leaves every scale at `1/0` | Carry supported A2L conversion and unit into the mapping; unsupported conversion is explicitly raw, never silently physical |
| Frozen build | `tools/build_windows_folder.ps1` vendors only the `pyxcp` package directory while excluding it from PyInstaller analysis | Pin, vendor, and smoke-test the complete runtime dependency closure in the built folder |

The existing green tests are not compatibility proof because key tests inject
unrestricted mocks that accept arbitrary methods and keywords. A mock that can
invent an API on attribute access is forbidden for the external pyxcp boundary.

## 3. Scope

### 3.1 In scope

- Pin and characterize the supported python-can/pyxcp versions.
- Correct pyxcp construction, XCP connection/status/authentication, DAQ
  programming, PID binding, DTO ingestion, decode, and cleanup.
- Preserve macOS/Linux import safety and FAKE/replay behavior.
- Correct the Cockpit connection/recording lifecycle so the same live session
  supplies preview and MF4 recording.
- Replace synthetic production health and preflight values with evidence-backed
  values or explicit unknown state.
- Carry LINEAR and the already-supported linearizable RAT_FUNC conversions plus
  unit metadata into live values and MF4; mark other conversions raw.
- Make source and frozen Windows builds prove the same runtime imports.
- Produce reproducible Windows + Vector + ECU evidence from Test Connection
  through first decoded DTO, MF4 close, reopen, and soak.
- Rewrite the bench runbook so it follows the real state machine and records
  version/config/evidence metadata.

### 3.2 Non-goals

- Connecting to or automating CANape. CANape is not part of the data path.
- Supporting Vector on macOS/Linux.
- Broad A2L dialect expansion such as XCPplus-only files unless the target ECU
  requires it and a real sample is supplied.
- Full COMPU_METHOD coverage. Unsupported nonlinear/table conversions remain
  raw with explicit metadata and warning.
- Calibration, flashing, STIM, PGM, or CAL/PAG access.
- ECU-specific Seed&Key algorithm design. The app only integrates a supplied,
  validated DLL/plugin.
- Declaring CAN-FD production-ready from classic-CAN evidence.
- Treating public-road driving as part of software acceptance. Initial evidence
  is stationary bench/HIL/vehicle-in-workshop only.

## 4. Supported Runtime Contract

### 4.1 Version lock

The first validated runtime shall install exactly:

```text
python-can==4.6.1
pyxcp==0.29.10
```

The Windows build must fail before packaging if installed versions differ. The
application diagnostic/evidence bundle must report Python bitness, application
version/commit, python-can version, pyxcp version, Vector driver version, device
model/serial where available, application slot, channel, bitrates, CAN mode,
A2L SHA-256, XCP command/response IDs, and selected event list.

### 4.2 Native import boundary

- No `mf4_analyzer` module may statically import `pyxcp` or `pya2l`.
- A subprocess import probe runs before the main process dynamically imports
  either native-risk package.
- The real import is permitted only after the probe exits successfully.
- Source and frozen builds exercise the same adapter entrypoint.
- A build-analysis workaround is not acceptance: the packaged executable must
  actually import the vendored modules and construct the runtime adapter.

### 4.3 Single transport owner

For a live session, pyxcp owns and closes the CAN transport. The backend must
not independently open a second `python-can` Vector bus and then attempt to pass
it through an undocumented dictionary.

`Test Connection` constructs a short-lived runtime through the same adapter and
closes it in `finally`. The live `Connect ECU` path constructs the long-lived
runtime. Hardware enumeration may use python-can separately only while no live
runtime owns that channel.

### 4.4 Configuration mapping

The adapter must map and verify all of the following against pyxcp 0.29.10:

- transport layer `CAN`;
- interface `vector`;
- `app_name`, channel, arbitration bitrate;
- CAN-FD flag and data bitrate when enabled;
- timeout;
- A2L `CAN_ID_MASTER` as command ID and `CAN_ID_SLAVE` as response ID;
- standard versus extended CAN-ID semantics;
- any sample-point field that the actual Vector/pyxcp surface supports.

If pyxcp/python-can cannot honor `sample_point` or `fd_sample_point`, the UI must
not pretend they were applied. The implementation either passes verified
parameters or labels/removes them as unsupported for this backend.

No production path may construct pyxcp from an unvalidated dictionary shape.

## 5. Connection And Authentication Contract

### 5.1 Test Connection

`Test Connection` is enabled only after a valid A2L `IF_DATA XCP` block and
transport settings are loaded. It performs, in order:

1. platform, installed-package, bitness, driver, application-slot, channel, and
   bitrate/config validation;
2. pinned runtime construction through the production adapter;
3. XCP CONNECT using the A2L command/response IDs;
4. GET_STATUS/current protection-state read;
5. optional DAQ unlock verification if DAQ is protected and a Seed&Key provider
   is configured;
6. `getDaqProcessorInfo()` and, when supported, DAQ resolution/list information;
7. DISCONNECT and complete cleanup.

A green result means only: hardware opened, XCP responded, protection state was
understood, and the ECU exposed compatible DAQ capabilities. It does **not**
mean DTO streaming or MF4 recording has passed.

The result shows structured facts rather than a misleading raw RESOURCE byte:
driver/device, XCP latency, DAQ available, DAQ locked/unlocked, max DAQ/ODT
facts when known, and a cleanup result.

### 5.2 Authentication

CONNECT resource information answers which resource classes exist. It does not
answer whether they are locked. The adapter shall inspect GET_STATUS/current
protection status and unlock only if DAQ is protected.

The preferred compatibility seam is a narrow adapter around the pinned pyxcp
API. Direct Seed&Key calls are accepted only after signature tests prove their
positional arguments, multi-part seed handling, key length semantics, and
response interpretation. Missing provider, bitness mismatch, symbol mismatch,
provider failure, and ECU rejection must be separate operator-facing errors.

## 6. DAQ Programming Contract

### 6.1 Preconditions

Before issuing allocation commands:

- every selected measurement exists in the loaded A2L snapshot;
- every selection has a resolved event, address, address extension, datatype,
  byte order, and payload size;
- ODT packing respects `MAX_DTO`, identification field, timestamp presence,
  granularity, and ECU/A2L DAQ limits;
- event numbers and prescalers are valid;
- unsupported static-DAQ-only ECUs fail with an explicit message rather than
  attempting dynamic allocation.

### 6.2 Dynamic DAQ sequence

For N DAQ lists, the production adapter issues this sequence:

1. `freeDaq()`;
2. `allocDaq(N)` exactly once;
3. `allocOdt(daq_list_number, odt_count)` for every list;
4. `allocOdtEntry(daq_list_number, odt_number, entry_count)` for every ODT;
5. for every entry, `setDaqPtr(...)` then `writeDaq(...)` with verified bit
   offset, element size, address extension, and address;
6. `setDaqListMode(mode, daq_list_number, event_channel_number, prescaler,
   priority)` with timestamp mode derived from capability/A2L, never hard-coded;
7. `startStopDaqList(0x02, daq_list_number)` for each list; record its returned
   `firstPid` and bind the list's ODTs to the actual PID range;
8. `startStopSynch(0x01)` to start selected lists.

Stop uses `startStopSynch(0x00)` before DISCONNECT. Partial-start failure runs a
best-effort stop/disconnect/transport-close sequence and leaves the backend
restartable.

### 6.3 PID and DTO mapping

The pre-allocation map contains list/ODT layout but no invented PID. The final
decode map is created only after all `firstPid` values are known. It rejects:

- overlapping PID ranges;
- PIDs outside the supported identification-field range;
- a DTO shorter than its mapped entries;
- unknown PID, malformed timestamp, or datatype-size mismatch.

Malformed DTOs increment a decode-drop counter, not a queue-overflow counter.
All counters preserve their distinct causes in diagnostics and the session
sidecar.

## 7. DTO Ingress And Backpressure

pyxcp 0.29.10 defaults to `NoOpPolicy`, which discards received frames. The
application must install an explicit `FrameAcquisitionPolicy` compatible with
that version before CONNECT.

The policy contract is:

- accept DAQ frames through the documented policy callback;
- copy the payload plus host monotonic arrival time into a bounded,
  thread-safe frame queue;
- never block the pyxcp transport worker on UI, decode, writer, or disk I/O;
- use a declared overflow policy (drop oldest is preferred for live preview,
  while any drop makes recording evidence fail);
- expose queue depth/high-water mark/overflow count/last-frame time;
- wake shutdown promptly without polling sleeps;
- bound both raw-frame and decoded-sample queues by capacity and memory;
- perform atomic batch drain; no shared-list copy-then-clear race.

`Master.fetch()` is reserved for its upload-helper meaning and must not appear in
the DTO ingress path. A missing/incompatible acquisition-policy API is a startup
error, never a silent loop returning no frames.

## 8. Decode And Measurement Correctness

- If ECU DAQ timestamps are present, decode and unwrap them according to A2L/
  ECU capability and rebase them to session time.
- If timestamps are absent, use the host monotonic arrival timestamp stored by
  the policy. All measurements from one DTO share that frame time.
- Decode signedness, width, float format, byte order, and address extension from
  the resolved A2L snapshot.
- Apply supported LINEAR and linearizable RAT_FUNC conversions and carry the A2L
  unit into live cards and MF4.
- Unsupported conversion methods produce an explicitly named raw channel or raw
  metadata flag and warning. They must not silently use scale `1/0` while
  displaying a physical unit.
- Sample counts and inter-arrival timing are validated by event, not only by
  total row count.

For the known ERD6 battery-voltage signal, a bench fixture must prove the A2L
factor `0.015625 V/bit` is applied and agrees with an independent reference
within the tolerance declared in the evidence worksheet.

## 9. Cockpit Lifecycle Contract

### 9.1 State model

```text
DISCONNECTED
    | Test Connection (short-lived; returns to DISCONNECTED)
    | Connect ECU
    v
CONNECTING -> STREAM_WAIT_FIRST_DTO -> CONNECTED_IDLE
                                      | Record: attach writer
                                      v
                                  RECORDING
                                      | Stop: flush/detach writer
                                      v
                                CONNECTED_IDLE
                                      | Disconnect
                                      v
                                DISCONNECTED
```

`Connect ECU` is successful only after at least one selected measurement is
decoded from a DTO. CONNECT/DAQ-start without a decoded first sample remains
`STREAM_WAIT_FIRST_DTO` and times out with a stage-specific diagnostic.

### 9.2 First-frame gate

The Record action is disabled until the current live session has produced a
decoded sample for at least one selected channel. The UI distinguishes:

- XCP CONNECT timeout;
- DAQ allocation/programming rejection;
- DAQ started but no DTO received;
- DTO received but unknown PID/malformed payload;
- DTO decoded but selected measurement absent.

For the first stationary bench smoke, the default first-frame deadline is 3 s
or `max(3 s, 5 × slowest selected event period)`, whichever is larger.

### 9.3 Record attachment

Pressing Record must not close and reopen Vector, reconnect XCP, reallocate DAQ,
or reset the live timestamp base. It attaches the ring/writer/controller to the
already-running sample stream. Pressing Stop flushes and closes MF4 but leaves
the live session and preview running. Disconnect owns DAQ stop and transport
close.

Selection changes while connected are explicit: either the UI requires
Disconnect/Reconnect or it performs a visible controlled DAQ reconfiguration.
It may not silently restart the backend on a debounce timer during a recording.

## 10. Health And Preflight Evidence

- HW health comes from driver/device/application/channel probes.
- CAN health reports real bus/driver errors and bus load only if a supported
  source exists; otherwise load is unknown, not a fixed percentage.
- XCP health comes from live connection state, responses/timeouts, and last
  response age.
- DAQ health reports configured/selected/running list counts, event mapping,
  first DTO time, last DTO age, frame queue watermarks, decode drops, and queue
  overflows.
- Recording health reports writer/ring/disk facts separately from transport.
- Preflight capacity comes from A2L plus ECU DAQ capability and actual packing.
  No fixed capacity such as 32 may be fabricated for the real backend.
- `off`/unknown evidence remains grey/unknown; the UI must not convert missing
  evidence into green.

## 11. Verification Ladder

Evidence classes remain separate. Passing a lower gate does not imply a higher
gate.

| Gate | Environment | Required proof |
| --- | --- | --- |
| G0 static/import | macOS + Windows source | Native imports remain lazy; adapter modules import without pyxcp on macOS |
| G1 pinned API | Windows venv with exact packages | Real signatures/config/policy callbacks are exercised; no unrestricted mocks |
| G2 pure protocol | Hardware-free | Exact DAQ command order, PID binding, DTO decode, conversion, overflow, cleanup |
| G3 deterministic transport | Windows, virtual/simulated XCP slave if feasible | CONNECT → DAQ → policy callback → decoded samples without Vector hardware |
| G4 Vector open | Windows + Vector, ECU optional | Driver/app/channel/bus open and close; version/device evidence |
| G5 ECU connection | Windows + Vector + powered ECU | Test Connection green with protection and DAQ capability facts |
| G6 first DTO | Same | 1 known signal; decoded first sample before deadline; plausible value/raster |
| G7 source MF4 | Same, source launch | 3 signals/one event/30 s; zero drops; MF4 closes/reopens and matches selection |
| G8 mixed events | Same | 12 signals/two events/60 s; per-event counts and timing within tolerance |
| G9 packaged MF4 | Same, built executable | Repeat G6/G7 from frozen build; runtime dependency evidence captured |
| G10 soak/recovery | Same | 30 min stationary soak, stop/start recording without reconnect, ECU power-cycle/error recovery |

Classic CAN can be released after G0-G10 pass on the declared VN model and ECU
configuration. CAN-FD requires its own G4-G10 run. Cross-VN-model support is a
separate evidence claim per model; it is not inferred from one device.

## 12. Acceptance And NO-GO Rules

### 12.1 Software implementation acceptance

All of the following are required before going to the bench:

- pinned real-package contract test passes on Windows;
- no production DTO path contains `Master.fetch` or a hypothetical transport
  fetch fallback;
- DAQ sequence and auth tests use a structured fake/spec or the real package,
  and reject unsupported keywords;
- native-import boundary tests remain green;
- existing FAKE/replay/Cockpit tests remain green;
- build script enforces versions and the packaged runtime smoke passes;
- the rewritten runbook and evidence template are complete.

### 12.2 Vehicle/bench release acceptance

The backend is called **bench validated** only when G5-G10 evidence is stored
with exact versions/config/A2L hash and MF4 files. It is called **vehicle-ready
for the validated configuration** only when:

- source and packaged paths both pass;
- zero frame-queue overflow, sample-queue overflow, decode drop, writer drop,
  and bus error occurs in accepted G7-G10 runs;
- channel names, units, value plausibility, sample counts, and timing are
  independently checked after reopening MF4;
- Record/Stop does not cause a second CONNECT or timestamp discontinuity;
- cleanup leaves the Vector channel reusable without restarting the app;
- operator failure messages identify the failed stage and actionable config.

### 12.3 Hard NO-GO conditions

Do not record on a vehicle when any of these is true:

- installed versions differ from the validated pair;
- Test Connection has not passed against the loaded A2L and powered ECU;
- current connection has not produced a decoded first DTO;
- the status bar/backend badge says FAKE or replay;
- any selected signal lacks an event/address/datatype mapping;
- DAQ protection is unknown or unlock failed;
- runtime health evidence is synthetic/unknown where the acceptance sheet
  requires a measured value;
- packaged runtime smoke or source MF4 gate is red;
- drops/unknown PID/decode errors are nonzero;
- operator cannot identify the actual Vector application, channel, bitrate,
  CAN IDs, ECU/A2L variant, and output location.

## 13. Deliverables

- pinned Windows acquisition requirements/constraints;
- a narrow pyxcp runtime adapter and bounded acquisition policy;
- corrected auth, DAQ session, PID map, DTO ingress, conversion, lifecycle,
  health, and build behavior;
- real-package contract and structured protocol tests;
- updated Windows build checks and runtime diagnostic;
- rewritten bench runbook and evidence manifest/template;
- source and packaged MF4 evidence for the validated hardware/ECU combination;
- final verdict stating exactly which combinations are PASS, PARTIAL, BLOCKED,
  or NOT TESTED.

## 14. Agent / Operator Handoff Contract

This work has two ownership boundaries. They must not be blurred merely to keep
an implementation session moving.

### 14.1 Other agent owns before bench time is booked

An implementation agent owns all hardware-independent and Windows-runtime work
through implementation-plan Task 10:

- reproduce the current API/lifecycle failures with red tests;
- implement and review Tasks 1-9 in a clean worktree;
- run the macOS hardware-free gates;
- run the exact-package contract on Windows;
- build and smoke-test the Windows folder executable;
- prepare the corrected runbook and empty evidence template;
- return a clean handoff containing branch, commits, changed-file list, exact
  commands/results, known limitations, and remaining hardware gates.

The agent may ask the operator for the target A2L and configuration facts, but
must not require a powered ECU to make ordinary unit tests green. It must not
label code `vehicle-ready`, `bench-validated`, or equivalent at this boundary.

### 14.2 Operator supplies or physically performs

The operator owns facts/actions that software cannot safely infer:

- choose A-side versus B-side ECU and provide the matching A2L;
- confirm the real Vector model/serial, driver, application slot, channel,
  arbitration/data bitrate, termination, and harness;
- confirm ECU power/ignition state and whether DAQ is protected;
- provide the matching Seed&Key DLL/provider when protection is enabled;
- ensure CANape/CANoe/another process does not own the same channel;
- physically connect/power/cycle equipment and authorize controlled recovery;
- run or supervise implementation-plan Tasks 11-12 and preserve evidence.

The printable/interactable operator checklist is the action-board HTML linked
at the top of this spec.

### 14.3 Bench-entry acceptance packet

Do not spend operator/vehicle time until the implementation agent supplies all
of the following:

1. a clean task branch/worktree and reviewable commits for Tasks 0-10;
2. a Windows runtime JSON proving the exact package versions and pyxcp surface;
3. focused macOS and Windows test commands with live pass results;
4. a successful frozen-executable runtime-smoke JSON;
5. the pre-bench runbook revision/commit and empty evidence directory template;
6. a zero-item list for unresolved P0 software blockers, or an explicit
   `BLOCKED` handoff that names each blocker;
7. no unsupported API fallback, unrestricted external-module mock, synthetic
   production health value, or broad pyxcp version range remaining.

### 14.4 Required agent return format

Every implementation handoff must contain this exact information:

```text
Branch / worktree:
Base commit:
Task(s) completed:
Commits:
Changed files:
Red tests captured before fix:
Focused green commands and live results:
Windows real-package contract result:
Frozen runtime-smoke result:
Known limitations / NOT TESTED:
Hardware gates still requiring operator:
Recommendation: PROCEED TO BENCH | DO NOT PROCEED
```

`PROCEED TO BENCH` means only that Tasks 0-10 meet their software exit gates.
It is not a substitute for Tasks 11-12 or the final combination-specific
verdict.
