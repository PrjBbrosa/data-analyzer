# Vector/XCP Readiness Review Remediation Plan

**Date:** 2026-07-11  
**Branch:** `codex/vector-xcp-readiness`  
**Starting commit:** `04591e57`  
**Status:** Code remediation complete; Windows W1/W2 and physical gates BLOCKED  
**Supersedes for readiness closure:** the implementation-complete assumption in
the July 11 Terra handoff. The historical Stage 8 spec remains architectural
background; this document owns the review corrections and acceptance gates.

## 1. Goal

Make the Vector + pyxcp 0.29.10 acquisition path truthful and testable from
Test Connection through DTO decode and MF4 persistence. Completion means:

1. real pyxcp response shapes are handled without permissive mocks;
2. DAQ protection, conversion, queue and decoder health are explicit facts;
3. connected configuration cannot drift from the active DAQ layout;
4. the exact Windows source environment and frozen application pass their
   no-ECU runtime gates; and
5. physical ECU validation has a bounded operator checklist with retained
   evidence.

macOS unit tests cannot satisfy items 4 or 5. Missing Windows or ECU evidence
must remain `UNKNOWN` or `BLOCKED`.

## 2. Non-goals

- Adding a PEAK/PCAN backend to this Python application.
- Running CANape and this collector as simultaneous XCP masters.
- Calibration writes, STIM, XCP-on-Ethernet, or unrelated Cockpit UI redesign.
- Claiming CAN-FD or additional Vector hardware support without repeating the
  same evidence gates.

## 3. Workstream A — pyxcp protocol and authentication contracts

### Task A1 — CONNECT resource facts

**Owned files:**

- `mf4_analyzer/acquisition_capture/vector_hw_probe.py`
- `tests/test_vector_hw_probe.py`
- `tests/test_pyxcp_029_contract.py`

**Steps:**

- Add a failing test whose CONNECT response uses the real pyxcp 0.29.10
  structured resource shape (`resource.daq`, `resource.calpag`, and peers).
- Remove integer coercion of `response.resource`.
- Return named resource/protection facts rather than an opaque resource byte.
- Keep Test Connection cleanup deterministic on every failure path.

**Acceptance:** a structured resource fake and the real Windows package
contract both pass; no unrestricted `MagicMock()` defines the external surface.

### Task A2 — GET_STATUS and DAQ protection

**Owned files:**

- `mf4_analyzer/acquisition_capture/vector_hw_probe.py`
- `mf4_analyzer/acquisition_capture/xcp_auth.py`
- `mf4_analyzer/acquisition_ui/settings_dialog.py`
- `tests/test_vector_hw_probe.py`
- `tests/test_xcp_auth.py`

**Steps:**

- Execute GET_STATUS after every successful CONNECT, whether or not a provider
  DLL is configured.
- Report DAQ as `unprotected`, `locked`, `unlocked`, or `unknown`.
- Make locked DAQ without a configured provider a red Test Connection result.
- Change the DAQ Seed&Key resource/category from `0x02` to `0x04` and pin it
  with a real-contract test.
- Delegate provider ABI, multi-part seed/key and privilege handling to pinned
  pyxcp 0.29.10 `Master.cond_unlock("DAQ")`; do not maintain a guessed custom
  ctypes signature for a vendor DLL.
- Ensure UI copy says only what was actually probed.

**Acceptance:** locked/unlocked/no-provider/rejected-unlock cases have distinct
results; a green result always includes a successful GET_STATUS fact.

### Task A3 — isolated runtime verification

**Owned files:**

- `scripts/verify_windows_acquisition_runtime.py`
- `mf4_analyzer/acquisition_capture/pyxcp_runtime.py`
- `tests/test_pyxcp_runtime.py`
- `tests/test_windows_build_script.py`

**Steps:**

- Make the verifier exercise the same isolated import probe used by the UI,
  including the PyQt-loaded context that previously produced access violations.
- Emit explicit probe command, return code, package versions, bitness, and API
  facts to JSON.
- Fail closed if the isolated probe or metadata lookup is incomplete.
- Normalize an absent Seed&Key path to pyxcp's real non-null Unicode default
  `""`; never assign Python `None` to `General.seed_n_key_dll`.
- Do not claim bare sample-point percentages are applied: Vector timing needs
  clock-specific BitTiming/tseg facts. Keep this release driver-automatic and
  fail closed on unsupported legacy overrides.

**Acceptance:** the verifier cannot report PASS after a simulated subprocess
crash, missing metadata, or incompatible API shape.

## 4. Workstream B — real DTO and backend health facts

### Task B1 — move diagnostics to the real backend

**Owned files:**

- `mf4_analyzer/acquisition_capture/backends.py`
- `mf4_analyzer/acquisition_capture/pyxcp_daq_policy.py`
- `mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py`
- `tests/test_vector_xcp_backend.py`
- `tests/test_pyxcp_daq_policy.py`

**Steps:**

- Remove the invalid Vector-specific diagnostics method from
  `FakeRecorderBackend`.
- Add a thread-safe diagnostics snapshot to `VectorXcpRecorderBackend`.
- Include at minimum DTO received, samples emitted, policy/bus errors, frame and
  sample queue current size/high-water/overflow, unknown PID, decode error, and
  last error.
- Preserve the existing five-field `BackendStatus` public contract unless a
  schema change is explicitly tested across all consumers.

**Acceptance:** UI receives non-empty live Vector diagnostics; fake/replay
backends remain callable; counters reset at the documented session boundary.

### Task B2 — explicit decoder outcomes

**Owned files:**

- `mf4_analyzer/acquisition_capture/dto_decode.py`
- `mf4_analyzer/acquisition_capture/backends.py`
- `tests/test_dto_decode.py`
- `tests/test_vector_xcp_backend.py`

**Steps:**

- Distinguish unknown PID, short payload, unsupported datatype/timestamp, and
  successful decode without silently collapsing them to an empty iterator.
- Feed these outcomes into the real backend counters without blocking the
  receive callback.
- Keep malformed frames from killing subsequent valid DTO processing.

**Acceptance:** each failure class increments only its own counter; a later
valid frame still yields a sample; accepted source/bench runs require all drop
and decode counters to remain zero.

The current pyxcp CAN wrapper consumes `python-can CanError` before the policy
can observe it. Until a documented bus-error source is added, diagnostics must
state `bus_error_observable=False`; a numeric zero is not a PASS fact.

## 5. Workstream C — value correctness and configuration ownership

### Task C1 — A2L address extension and conversion propagation

**Owned files:**

- `can_logger/p0/a2l_probe.py`
- `mf4_analyzer/acquisition_capture/daq_map.py`
- `mf4_analyzer/acquisition_capture/dto_decode.py`
- `tests/test_p0_a2l_probe.py`
- `tests/test_daq_map_builder.py`
- `tests/test_dto_decode.py`

**Steps:**

- Parse ECU address extension and supported linear conversion facts into
  `MeasurementSummary` without importing `pya2l` at module load.
- Propagate extension, scale and offset into ODT writes and DTO decode.
- Treat unsupported/nonlinear conversion explicitly instead of silently using
  identity conversion.
- Add an end-to-end fixture for a known `0.015625 V/bit` signal and assert raw,
  physical value, and unit separately.

**Acceptance:** the fixture proves address extension reaches `writeDaq` and a
known raw value decodes to the expected physical value; unsupported conversion
cannot masquerade as converted data.

### Task C2 — connected selection invalidation

**Owned files:**

- `mf4_analyzer/acquisition_ui/main_window/_capture_session_mixin.py`
- `mf4_analyzer/acquisition_ui/main_window/window.py`
- `tests/acquisition_ui/test_capture_session.py`
- `tests/acquisition_ui/test_record_backend_swap.py`
- `tests/acquisition_ui/test_state_machine.py`

**Steps:**

- Detect changes to selected measurements/events while a Cockpit-owned Vector
  backend is attached.
- Immediately invalidate and best-effort stop the owned backend, or revert the
  UI selection. Do not leave a warning-only state.
- Disable Record until Test Connection/Connect ECU has rebuilt DAQ from the new
  selection.
- Preserve caller-injected fake/replay test backends where their contract
  intentionally allows live selection changes.

**Acceptance:** a test proves the active DAQ selection and writer schema cannot
diverge; reconnecting with the new selection restores Record eligibility.

### Task C3 — transport/A2L mutation and DAQ error gates

- Reject transport or A2L mutation while RECORDING or REVIEW owns a live
  capture; never stop/swap the controller's backend behind its state.
- In CONNECTED_IDLE, a transport/A2L change must stop the owned Vector backend,
  clear connection/first-frame facts, request disconnect, and require a new
  Test Connection/Connect ECU cycle.
- Never permit a real acquisition configuration change to silently turn the
  next Record into Fake data.
- Propagate unknown PID, decode error and policy error diagnostics into DAQ
  health. Any nonzero value remains red/NO-GO for the session even if a later
  DTO decodes successfully.

## 6. Integration and packaging

### Task D1 — source regression gate

Run from this worktree using the available repository venv:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  '/Users/donghang/Downloads/data analyzer/.venv/bin/python' -m pytest \
  tests/test_pyxcp_029_contract.py \
  tests/test_pyxcp_runtime.py \
  tests/test_pyxcp_daq_policy.py \
  tests/test_vector_hw_probe.py \
  tests/test_vector_probe_stages.py \
  tests/test_xcp_auth.py \
  tests/test_vector_xcp_backend.py \
  tests/test_daq_map_builder.py \
  tests/test_dto_decode.py \
  tests/test_p0_a2l_probe.py \
  tests/test_p0_a2l_probe_import_safety.py \
  tests/test_native_import_boundaries.py \
  tests/test_acquisition_capture_controller.py \
  tests/acquisition_ui/test_capture_session.py \
  tests/acquisition_ui/test_record_backend_swap.py \
  tests/acquisition_ui/test_state_machine.py \
  tests/test_windows_build_script.py -q
```

Also run `git diff --check` and the lesson-prescribed import/mocking greps.

### Task D2 — frozen application closure

**Owned files:**

- `tools/build_windows_folder.ps1`
- `mf4_analyzer/acquisition_capture/runtime_smoke.py`
- `tests/test_windows_build_script.py`
- `docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md`

**Steps:**

- Use one authoritative application/exe name in build and runbook.
- Ensure the frozen folder contains pyxcp metadata and its required import/data
  closure; do not infer this from copying the top-level package directory.
- Route crash-isolated A2L parsing through a dedicated frozen child flag;
  `sys.executable -m ...` is valid only when `sys.executable` is CPython.
- Vendor the exact installed pya2ldb metadata and parser dependency closure;
  copying only `pya2l/` is not a packaged A2L contract.
- Make packaged runtime smoke prove `importlib.metadata.version("pyxcp")`,
  pyxcp and pya2l isolated import safety, real application-config construction,
  and policy construction without opening a Vector channel.
- Retain source and packaged JSON separately.

**Acceptance:** a clean Windows build runs its smoke command from outside the
source tree and emits a PASS JSON with exact versions/bitness; missing metadata
or dependency changes the process exit code to nonzero.

## 7. Windows and operator gates

### Gate W1 — exact Windows source environment

- Install the pinned requirements into a clean Windows venv.
- Run the focused test command from this plan.
- Generate `api-contract.json`; result must be PASS with no skipped real-package
  contract.

### Gate W2 — exact frozen folder

- Build from the reviewed commit.
- Run packaged runtime smoke outside the checkout.
- Generate `build-api-contract.json` and `packaged-runtime-smoke.json`.

### Gate H1 — one-signal first DTO

- Power ECU and preserve exact Vector/driver/A2L/bitrate/ID facts.
- Test Connection must prove CONNECT, GET_STATUS and cleanup.
- Connect one known converted signal and require a decoded first DTO before the
  deadline.
- Unknown PID, decode error, queue overflow, protection uncertainty, or
  implausible value is NO-GO.

### Gate H2 — MF4 source and packaged runs

- Three signals/one event/30 seconds from source, then from frozen app.
- Reopen MF4 and verify names, units, physical values, monotonic timestamps,
  event-based counts, and zero drop/error counters.
- Exercise Record/Stop/Record without reconnecting and confirm preview remains
  attached.

### Gate H3 — scale and recovery

- Twelve signals/two events/60 seconds.
- Thirty-minute stationary soak.
- Controlled bus/ECU interruption and recovery without a silent stale backend.

Status vocabulary is sequential:

- W1 + W2 PASS: `PROCEED TO PHYSICAL BENCH` for the exact built configuration.
- H1 + H2 PASS: `BENCH-VALIDATED` for the exact ECU/A2L/Vector/CAN row.
- H3 PASS: eligible for a broader `vehicle-ready` claim, still limited to the
  tested CAN mode and Vector model.

## 8. Execution result

Completed on the macOS review host:

- Workstreams A, B, C and frozen-build preparation implemented by isolated
  agents and integration-reviewed.
- Focused integration: `204 passed, 4 skipped in 19.27s`.
- Broad Acquisition/Cockpit regression: 700 tests, exit 0
  (`699 passed, 1 skipped`).
- Full repository collection: `3211/3214 tests collected (3 deselected)`.
- Two local CANape A2Ls passed isolated parsing; the 323-measurement B-side
  profile produced the known battery conversion `0.015625 V/bit`, offset 0,
  unit V.
- Diff, lazy-import, retired-ABI and stale-identifier checks passed.
- Independent adversarial closure review marked every discovered P0/P1 group
  code-level `RESOLVED` and found no new P0/P1.

Not completed on this host:

- W1 clean Windows source contract JSON.
- W2 real onedir build and packaged runtime smoke JSON.
- H1/H2/H3 Vector + powered ECU DTO/MF4/soak evidence.
- CAN bus errors are not observable through the pyxcp policy path;
  diagnostics explicitly reports `bus_error_observable=False` and the runbook
  records the numeric counter as `UNKNOWN`, not PASS.

## 9. PCAN-driven bench boundary

This application remains Vector-only. A supported bench topology is:

```text
PSU -> ECU power/IGN
PCAN -> shared CAN bus for wake/NM/stimulus frames
Vector VN -> shared CAN bus -> this collector or CANape as the sole XCP master
```

PCAN must not transmit the XCP command/response IDs. CANape and this Python
collector must run sequentially against the same ECU/XCP connection, not as
simultaneous masters.
