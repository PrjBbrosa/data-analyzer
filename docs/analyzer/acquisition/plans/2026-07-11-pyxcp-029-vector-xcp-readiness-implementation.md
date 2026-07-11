# pyxcp 0.29 / Vector XCP 真实采集准备度 Implementation Plan

> **Execution rule:** sequential implementation, one closed TDD slice at a
> time. Every slice starts with a failing contract/reproduction, makes the
> smallest production change, runs focused green, and records evidence. Do not
> attempt a vehicle recording until Tasks 0-10 are green. Do not claim hardware
> PASS from macOS, mocks, screenshots, or an XCP CONNECT alone.

Date: 2026-07-11

Source spec:
`docs/analyzer/acquisition/specs/2026-07-11-pyxcp-029-vector-xcp-readiness-spec.md`

Operator action board:
`docs/analyzer/acquisition/reports/2026-07-11-vector-xcp-operator-action-board.html`

Corrected predecessor artifacts:

- `docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md`
- `docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md`
- `docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md`

## Goal

Deliver one evidence-backed classic-CAN configuration in which the same pinned
runtime works from source and from the Windows folder build:

```text
A2L + transport settings
  -> Test Connection
  -> Connect ECU
  -> program DAQ
  -> receive and decode first DTO
  -> idle live preview
  -> attach MF4 recording without reconnect
  -> stop/flush/reopen MF4
  -> remain connected and previewing
```

At completion, the final report must say exactly which Python/package/driver/
Vector/ECU/A2L/CAN-mode combination passed. Anything not exercised is marked
`NOT TESTED`, not inferred.

## Required execution environment

Implementation can begin on macOS, but the real-package contract, source
runtime, frozen runtime, and ECU gates require Windows x64.

First supported dependency pair:

```text
python-can==4.6.1
pyxcp==0.29.10
```

Initial hardware configuration, to be confirmed at Task 11 rather than assumed:

```text
Vector application: Python
channel: 0
classic CAN: 500000 bit/s
known bench hardware: VN1630A serial 594136
ERD6 A-side XCP IDs: command 0x6C7, response 0x6C6
ERD6 B-side XCP IDs: command 0x6C8, response 0x6C9
```

The A/B ECU side, exact A2L, Vector device, driver, authentication state, and
termination are operator inputs. The implementation must not choose between A
and B by filename guess.

## Global constraints

- Read the source spec and this plan completely before editing.
- Before risky implementation, use `scripts/lessons/select.py` and load only
  relevant lessons. At minimum preserve the native-import and phantom-API
  protections named in the spec.
- The current main checkout contains unrelated dirty UI/test/report work. Create
  an isolated worktree/branch from the approved base before source edits. Never
  copy, stage, revert, or clean unrelated files from the source checkout.
- Keep `python-can`/`pyxcp`/`pya2l` out of module import time. Preserve the
  isolated subprocess probe.
- Do not use unrestricted `MagicMock()` to prove pyxcp compatibility. Use the
  installed real package, an autospec created from it, or a narrow structured
  fake that raises on unknown methods/keywords.
- Do not create a generic abstraction layer beyond the narrow pyxcp 0.29.10
  adapter required here.
- Keep CLI behavior working. CLI owns backend start/stop; Cockpit recording may
  attach to an already-started backend.
- Preserve FAKE/replay behavior and macOS startup.
- Use the project interpreter explicitly:
  - macOS: `.venv/bin/python`
  - Windows: `.\.venv\Scripts\python.exe`
- Hardware commands run in the foreground and write evidence. No hidden
  background process may own the Vector channel.
- Each commit stages only its task's declared files.
- If the target pyxcp surface differs from the characterization in Task 1, stop
  and revise this plan/spec before broad code changes. Do not add version-guess
  fallbacks.

## Task-to-contract matrix

| Task | Contract closed | Hardware required |
| --- | --- | --- |
| 0 | isolated baseline and evidence snapshot | no |
| 1 | exact dependency/API contract | Windows venv, no Vector |
| 2 | runtime construction and transport ownership | Windows venv; Vector optional |
| 3 | protection status and DAQ unlock | no hardware for tests; ECU later |
| 4 | correct DAQ allocation and actual PID binding | no hardware for tests; ECU later |
| 5 | bounded policy-driven DTO ingress | no hardware for deterministic tests |
| 6 | decode/conversion/value metadata | real A2L, no hardware for tests |
| 7 | persistent Connect/Preview/Record lifecycle | no hardware for UI/controller tests |
| 8 | evidence-backed health/preflight | no hardware for tests; live facts later |
| 9 | Test Connection/diagnostics/CLI integration | Windows/Vector/ECU later |
| 10 | Windows frozen runtime closure | Windows build |
| 11 | bench first DTO and source MF4 | Windows + Vector + ECU |
| 12 | packaged MF4, mixed event, soak/recovery | Windows + Vector + ECU |
| 13 | final docs/evidence/verdict | completed evidence |

## Agent handoff map

Use one sequential implementation agent for Tasks 0-10. Tasks 2-9 share the
same runtime, backend, controller, and test seams; parallel agents would create
competing ownership/lifecycle designs. A separate review agent may inspect the
completed Tasks 0-10 branch read-only before the bench, but must not rewrite the
contract to match an incomplete implementation.

| Execution block | Owner | Environment | Exit handed to next block |
| --- | --- | --- | --- |
| A — baseline and real API contract | implementation agent | macOS + Windows venv | Tasks 0-1 green; exact package/API JSON |
| B — runtime, auth, DAQ, DTO, conversion | same implementation agent | hardware-free tests | Tasks 2-6 green; deterministic 1000-DTO proof |
| C — Cockpit lifecycle, health, diagnostic | same implementation agent | macOS/Windows source | Tasks 7-9 green; one-connect Record contract |
| D — frozen runtime and pre-bench pack | same implementation agent | Windows build host | Task 10 green; executable smoke + runbook |
| E — source bench gates | operator physically, agent assists | Windows + Vector + ECU | Task 11 evidence |
| F — packaged/mixed/soak/recovery | operator physically, agent assists | same bench | Task 12 evidence and final verdict |

### Copy-paste prompt for the implementation agent

```text
在 /Users/donghang/Downloads/data analyzer 仓库执行 Vector/XCP 真实采集准备度工作。

先完整阅读：
1. docs/analyzer/acquisition/specs/2026-07-11-pyxcp-029-vector-xcp-readiness-spec.md
2. docs/analyzer/acquisition/plans/2026-07-11-pyxcp-029-vector-xcp-readiness-implementation.md
3. 上述 plan Task 0 列出的 lessons。

只执行 Tasks 0-10，严格顺序 TDD：先捕获红测试，再做最小实现，再跑 focused green。
当前 main checkout 有无关脏改动，必须建立独立 worktree/branch，不得清理、复制或回退用户改动。
pyxcp 首版只支持 0.29.10，python-can 只支持 4.6.1；不得添加版本猜测 fallback。
不得用 unrestricted MagicMock 证明外部 API；不得静态 import pyxcp/pya2l；不得用
Master.fetch/transport.fetch 接收 DTO；不得把 CONNECT resource availability 当锁状态。

Tasks 0-10 完成后停止，不执行或声称 Tasks 11-12 的硬件 PASS。按 spec §14.4 返回完整
handoff，并给出明确的 PROCEED TO BENCH 或 DO NOT PROCEED。不要 commit/push 到 main；只在任务
branch 提交每个闭环 task，等待用户 review。
```

### Operator availability needed before Task 11

The implementation agent may finish Tasks 0-10 without a powered ECU. Before
Task 11, the operator must fill the HTML action board with the exact ECU side,
A2L, Vector/driver/channel/bitrate, protection/provider, harness/termination,
and chosen first signal. Unknown fields are a bench-entry blocker, not values
for the agent to guess.

---

## Task 0: Isolate work and freeze the baseline

**Purpose:** protect the user's dirty checkout and make the pre-fix failures
reproducible.

**Read in full:**

```text
docs/analyzer/acquisition/specs/2026-07-11-pyxcp-029-vector-xcp-readiness-spec.md
docs/analyzer/acquisition/plans/2026-07-11-pyxcp-029-vector-xcp-readiness-implementation.md
docs/lessons-learned/codex-plan-spec-literal-evidence.md
docs/lessons-learned/codex-analyzer-doc-routing.md
docs/lessons-learned/codex-acquisition-validation-evidence-gates.md
docs/lessons-learned/codex-phantom-api-surface-guards.md
docs/lessons-learned/codex-windows-native-import-guard.md
```

- [ ] Record source checkout status and base commit:

  ```bash
  git status --short --branch
  git rev-parse HEAD
  git rev-parse origin/main
  ```

- [ ] Create a clean sibling worktree and task branch without deleting or
  resetting any existing worktree:

  ```bash
  git worktree add ../data-analyzer-vector-xcp-readiness \
    -b codex/vector-xcp-readiness HEAD
  cd ../data-analyzer-vector-xcp-readiness
  if [ ! -e .venv ]; then
    ln -s "/Users/donghang/Downloads/data analyzer/.venv" .venv
  fi
  test -x .venv/bin/python
  git status --short --branch
  ```

- [ ] Run and save the current focused baseline:

  ```bash
  TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
    .venv/bin/python -m pytest \
    tests/test_vector_xcp_backend.py \
    tests/test_xcp_daq_session.py \
    tests/test_xcp_auth.py \
    tests/test_vector_hw_probe.py \
    tests/test_vector_probe_stages.py \
    tests/test_native_import_boundaries.py \
    tests/test_daq_map_builder.py \
    tests/test_dto_decode.py \
    tests/test_ifdata_xcp_parser.py \
    tests/acquisition_ui/test_record_backend_swap.py \
    tests/acquisition_ui/test_settings_transport_tab.py \
    tests/acquisition_ui/test_state_machine.py \
    tests/acquisition_ui/test_capture_session.py -q
  ```

  Plan-time reference: `124 passed`. A changed count is acceptable only if all
  listed tests pass and the delta is explained.

- [ ] Add failing regression/contract tests that expose, before fixes:
  - Master cannot be constructed from the current dictionary;
  - current Seed&Key keywords are invalid;
  - current DAQ sequence/keywords are invalid;
  - PIDs must not be invented at zero;
  - `Master.fetch(timeout=...)` is not a DTO receive API;
  - Record currently causes a second backend start.

No production change and no commit until the red assertions are captured.

---

## Task 1: Pin and characterize the real pyxcp surface

**Files:**

- Add: `requirements-windows-acquisition.txt`
- Add: `scripts/verify_windows_acquisition_runtime.py`
- Add: `tests/test_pyxcp_029_contract.py`
- Modify: `requirements.txt`
- Modify: `tests/test_native_import_boundaries.py` only if the new adapter path
  requires the whitelist to remain explicit

**Purpose:** replace remembered/fork-dependent APIs with an executable contract
against the installed package.

- [ ] Add a Windows acquisition constraint file with exact versions. Make
  `requirements.txt` point to or match that exact supported pair; do not leave a
  broad `pyxcp>=0.22.0` production range.
- [ ] Write `verify_windows_acquisition_runtime.py` so it:
  - rejects non-Windows with a clear diagnostic and nonzero code for the live
    checks;
  - reports Python/bitness and installed package versions;
  - fails on version mismatch;
  - runs the existing isolated import probe before dynamic import;
  - verifies `Master.__init__`, `getSeed`, `unlock`, `allocDaq`, `allocOdt`,
    `allocOdtEntry`, `writeDaq`, `setDaqListMode`, `startStopDaqList`, and
    `startStopSynch` signatures;
  - verifies the acquisition-policy base class/callback surface and the
    `NoOpPolicy` default behavior;
  - verifies the supported configuration object's CAN/Vector trait paths;
  - emits JSON with `ok`, versions, checked surfaces, and exact failure.
- [ ] Make the contract test import the real installed package on Windows. Do
  not monkeypatch an unrestricted module object. Mark the test skip on hosts
  where the Windows-only dependency is intentionally absent; make it mandatory
  in the Windows gate script.
- [ ] Characterize standard and extended CAN ID representation and document it
  in a test vector.
- [ ] Characterize whether `sample_point` and `fd_sample_point` reach the Vector
  bus. If unsupported, write a failing settings expectation for Task 2 to stop
  claiming they are active.

**Windows command:**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-windows-acquisition.txt
.\.venv\Scripts\python.exe scripts\verify_windows_acquisition_runtime.py `
  --json evidence\vector-xcp\api-contract.json
.\.venv\Scripts\python.exe -m pytest tests\test_pyxcp_029_contract.py -q
```

**Exit:** exact versions and every required real surface are green. Any mismatch
blocks Task 2 and triggers a spec/plan revision, not a compatibility fallback.

**Commit:** `test(acq): pin and characterize pyxcp 0.29 runtime`

---

## Task 2: Add the narrow runtime adapter and single transport owner

**Files:**

- Add: `mf4_analyzer/acquisition_capture/pyxcp_runtime.py`
- Modify: `mf4_analyzer/acquisition_capture/backends.py`
- Modify: `mf4_analyzer/acquisition_capture/vector_hw_probe.py`
- Modify: `mf4_analyzer/acquisition_capture/transport_config.py`
- Test: `tests/test_pyxcp_runtime.py`
- Test: `tests/test_vector_xcp_backend.py`
- Test: `tests/test_vector_hw_probe.py`
- Test: `tests/test_native_import_boundaries.py`

**Required interface:**

```text
PyXcpRuntime.open(transport, ifdata, policy) -> runtime
runtime.master
runtime.connect()
runtime.disconnect()
runtime.close()
runtime.diagnostics()
```

Names may adjust to repository style, but there must be one construction and
cleanup seam shared by Test Connection and the production backend.

- [ ] Write a structured fake config tree that rejects unknown trait paths and
  prove the adapter sets layer/interface/app/channel/bitrates/timeout/CAN IDs.
- [ ] Make the adapter dynamically import only after the subprocess probe.
- [ ] Let pyxcp create/own the Vector CAN transport. Remove the backend's
  independent `can.Bus(...)` + undocumented `{"bus": bus}` handoff.
- [ ] Ensure close is idempotent after construction failure, CONNECT failure,
  partial DAQ start, normal disconnect, and repeated stop.
- [ ] Route `test_xcp_connection` through the same adapter; it must not maintain
  a second Master construction path.
- [ ] Apply `sample_point` fields only if Task 1 proved support. Otherwise make
  the settings/UI say `not applied by Vector XCP backend` or remove them from
  the real-backend payload while preserving config migration.
- [ ] Preserve non-Windows backend refusal before any native import.

**Focused tests:**

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_pyxcp_runtime.py \
  tests/test_vector_xcp_backend.py \
  tests/test_vector_hw_probe.py \
  tests/test_native_import_boundaries.py -q
```

**Exit:** one adapter owns construction/transport/cleanup; current dictionary
Master construction no longer exists.

**Commit:** `fix(acq): construct pinned pyxcp Vector runtime correctly`

---

## Task 3: Correct protection status and Seed&Key handling

**Files:**

- Modify: `mf4_analyzer/acquisition_capture/xcp_auth.py`
- Modify: `mf4_analyzer/acquisition_capture/pyxcp_runtime.py`
- Test: `tests/test_xcp_auth.py`
- Test: `tests/test_pyxcp_029_contract.py`

- [ ] Replace CONNECT-resource bit interpretation with a protection-status
  query. Tests must separately cover:
  - DAQ unavailable;
  - DAQ available and unlocked;
  - DAQ available and locked with no provider;
  - locked with provider success;
  - multi-part seed if pyxcp exposes it;
  - provider file missing, wrong bitness/symbol, nonzero provider return;
  - ECU rejects key;
  - cleanup after every error.
- [ ] Prefer the pinned library's verified conditional-unlock helper where it
  can call the supplied key provider correctly. Otherwise implement the exact
  verified positional `getSeed(first, resource)` / `unlock(length, key)` flow
  behind this adapter.
- [ ] Ensure only DAQ is requested. Do not unlock CAL/PAG, STIM, or PGM.
- [ ] Replace tests that assert `resource_id=` or other unsupported keywords.

**Exit:** tests fail if CONNECT availability is mistaken for a lock, and fail
if unsupported auth keywords return.

**Commit:** `fix(acq): use XCP protection status for DAQ unlock`

---

## Task 4: Correct dynamic DAQ programming and actual PID binding

**Files:**

- Modify: `mf4_analyzer/acquisition_capture/xcp_daq_session.py`
- Modify: `mf4_analyzer/acquisition_capture/daq_map.py`
- Modify: `mf4_analyzer/acquisition_capture/dto_decode.py`
- Test: `tests/test_xcp_daq_session.py`
- Test: `tests/test_daq_map_builder.py`
- Test: `tests/test_dto_decode.py`

**Structured master fake:** create an explicit class with real 0.29.10 method
signatures. It records commands and raises `TypeError` for unknown keywords.

- [ ] Split layout into:
  1. pre-programming DAQ/ODT/entry layout with no PID map;
  2. post-selection final map bound from ECU-returned `firstPid` values.
- [ ] Assert exact command order:

  ```text
  CONNECT / status / DAQ info
  FREE_DAQ
  ALLOC_DAQ(N) once
  ALLOC_ODT for every list
  ALLOC_ODT_ENTRY for every ODT
  SET_DAQ_PTR + WRITE_DAQ for every entry
  SET_DAQ_LIST_MODE for every list
  START_STOP_DAQ_LIST(SELECT) for every list -> firstPid
  START_STOP_SYNCH(START_SELECTED)
  ```

- [ ] Derive timestamp mode from A2L/ECU capability. For known ERD6
  `daq_timestamp_size=0`, assert timestamp mode is not enabled.
- [ ] Carry address extension instead of hard-coding zero.
- [ ] Validate granularity and DTO overhead before any command is sent.
- [ ] Reject overlapping PID ranges and unknown PID deterministically.
- [ ] On any programming error, issue best-effort STOP/DISCONNECT and keep the
  backend restartable.

**Focused tests:**

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_xcp_daq_session.py \
  tests/test_daq_map_builder.py \
  tests/test_dto_decode.py -q
```

**Exit:** no per-list `allocDaq`, no unsupported DAQ keywords, no hard-coded
timestamp mode, and no PID map before ECU `firstPid` responses.

**Commit:** `fix(acq): program dynamic DAQ and bind ECU PIDs`

---

## Task 5: Replace DTO polling with a bounded acquisition policy

**Files:**

- Add or include in runtime module:
  `mf4_analyzer/acquisition_capture/pyxcp_daq_policy.py`
- Modify: `mf4_analyzer/acquisition_capture/backends.py`
- Modify: `mf4_analyzer/acquisition_capture/session.py` if counters/sidecar need
  explicit fields
- Test: `tests/test_pyxcp_daq_policy.py`
- Test: `tests/test_vector_xcp_backend.py`
- Test: `tests/test_capture_pipeline_concurrency.py`

**Required behavior:**

- policy callback receives the pinned pyxcp DAQ frame shape;
- it captures `time.monotonic()` at ingress;
- it performs bounded nonblocking enqueue;
- a decoder worker blocks on queue/event rather than sleeping in a 1 ms loop;
- decoded samples enter a second bounded thread-safe queue;
- `poll()` atomically drains a batch;
- frame overflow, sample overflow, decode drop, unknown PID, bus error, and
  successfully decoded sample count remain separate;
- stop wakes and joins workers, then stops DAQ/disconnects/closes in order.

- [ ] Write a deterministic race test in which a producer enqueues while
  `poll()` drains. Prove no sample disappears through copy-then-clear.
- [ ] Fill each queue past capacity. Assert declared drop policy, exact counter,
  high-water mark, bounded memory, and recording acceptance failure.
- [ ] Feed policy callbacks for multiple DAQ lists/PIDs and assert ordering and
  shared per-frame timestamps.
- [ ] Remove `_read_dto_frame()` and all `master.fetch` / `transport.fetch`
  fallbacks from the production DTO path.
- [ ] Make missing policy compatibility a startup error that names installed
  pyxcp version.

**Static guard:**

```bash
rg -n "master\.fetch|transport_fetch|transport\.fetch" \
  mf4_analyzer/acquisition_capture tests
```

Expected: no production DTO receive call; a negative regression assertion may
mention the forbidden names.

**Exit:** 1000 deterministic DTOs produce the expected sample sequence with
zero loss; overflow is bounded, counted, and visible.

**Commit:** `fix(acq): receive DTOs through bounded pyxcp policy`

---

## Task 6: Make decoded values and units trustworthy

**Files:**

- Modify: `can_logger/p0/a2l_probe.py`
- Modify: `can_logger/p0/ifdata_xcp.py` if address extension is not preserved
- Modify: `mf4_analyzer/acquisition_capture/daq_map.py`
- Modify: `mf4_analyzer/acquisition_capture/dto_decode.py`
- Modify: `mf4_analyzer/acquisition_capture/writer.py` only as required to carry
  unit/raw metadata
- Test: `tests/test_acquisition_a2l_events.py`
- Test: `tests/test_daq_map_builder.py`
- Test: `tests/test_dto_decode.py`
- Test: `tests/test_mf4_writer.py`
- Add fixture: the smallest copyright-safe A2L excerpt needed for conversion
  and address-extension cases

- [ ] Extend the immutable measurement snapshot with the minimum runtime facts:
  address extension, conversion kind/coefficients, unit, and an explicit
  `conversion_supported` or equivalent state.
- [ ] Parse LINEAR and the existing supported linearizable RAT_FUNC shape.
- [ ] Apply conversion once, in the DTO decode path. Do not double-convert in
  UI or writer.
- [ ] For unsupported conversion, preserve raw numeric data and explicit raw
  metadata; never attach a physical unit to an unconverted raw number.
- [ ] Add the ERD6 battery-voltage fixture assertion for factor `0.015625` and
  unit `V`.
- [ ] Reopen the generated MF4 and assert names, units, values, monotonic time,
  and sample counts.

**Exit:** a known raw DTO value produces the expected physical value in both
live sample output and reopened MF4; unsupported conversion is visibly raw.

**Commit:** `fix(acq): preserve A2L conversion and unit metadata`

---

## Task 7: Attach recording to the persistent live stream

**Files:**

- Modify: `mf4_analyzer/acquisition_capture/controller.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_capture_session_mixin.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py`
- Modify: `mf4_analyzer/acquisition_ui/state.py` only if an explicit
  first-frame-wait state is required by the existing model
- Test: `tests/test_capture_controller.py`
- Test: `tests/acquisition_ui/test_capture_session.py`
- Test: `tests/acquisition_ui/test_record_backend_swap.py`
- Test: `tests/acquisition_ui/test_state_machine.py`

**Minimal controller seam:**

- retain `CaptureController.start()` as the CLI-owned path that calls
  `backend.start()` and owns `backend.stop()`;
- add an explicit attached-start path (for example `start_attached()`) that
  requires `backend.status().started`, does not call `backend.start()`, and does
  not stop the backend when recording finalizes;
- record ownership inside the controller rather than passing ambiguous booleans
  at every stop call.

- [ ] First write a test proving the current Record action invokes a second
  backend start.
- [ ] On `Connect ECU`, start backend once and let idle `_poll_live` consume it.
- [ ] Transition to connected-idle only after a decoded first selected sample.
- [ ] On Record, switch the sole polling consumer to an attached controller;
  there must never be two concurrent consumers of `backend.poll()`.
- [ ] On Stop, finalize writer/sidecar, detach controller, and return polling
  ownership to idle preview without backend restart or timestamp reset.
- [ ] On Disconnect/window close, the connection owner stops backend exactly
  once.
- [ ] While connected, selection changes require a visible reconnect/apply
  action or a controlled reconfiguration. Remove the silent debounce restart
  for the real backend; preserve FAKE behavior if useful.
- [ ] Assert Record/Stop/Record creates two valid MF4 files in one XCP session,
  with a continuous live timestamp base and exactly one backend start.

**Exit:** source-level fake/structured backend proves one connect, zero reconnect
at Record, writer flush at Stop, preview continues, and disconnect closes once.

**Commit:** `fix(cockpit): attach recording to connected XCP stream`

---

## Task 8: Replace synthetic production health and preflight

**Files:**

- Modify: `mf4_analyzer/acquisition_capture/health.py`
- Modify: `mf4_analyzer/acquisition_capture/backends.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py`
- Modify: `mf4_analyzer/acquisition_capture/preflight_estimates.py`
- Test: `tests/test_health.py`
- Test: `tests/acquisition_ui/test_health_strip.py`
- Test: `tests/acquisition_ui/test_pinned_monitoring.py`
- Test: `tests/acquisition_ui/test_state_machine.py`

- [ ] Add a read-only runtime diagnostic snapshot containing connection, DAQ,
  queue, decode, and last-frame facts without expanding `BackendStatus` into a
  catch-all UI model.
- [ ] Feed real backend health from that snapshot. Retain clearly labeled fake
  facts only in demo mode.
- [ ] Report CAN load only when the Vector/python-can surface provides it;
  otherwise use unknown.
- [ ] Compute DAQ event/list/ODT usage from actual packing and ECU capability.
  Remove real-backend capacity `32` fabrication.
- [ ] Keep missing evidence grey/off. Do not turn an absent counter or unknown
  capacity green.
- [ ] Make first-DTO wait show last protocol stage and elapsed time.

**Exit:** structured tests show that live facts move chips/preflight and missing
facts remain unknown; FAKE demos stay functional.

**Commit:** `fix(cockpit): drive XCP health from runtime evidence`

---

## Task 9: Unify Test Connection, Connect ECU, CLI, and diagnostics

**Files:**

- Modify: `mf4_analyzer/acquisition_capture/vector_hw_probe.py`
- Modify: `mf4_analyzer/acquisition_capture/__main__.py`
- Modify: `mf4_analyzer/acquisition_ui/settings_dialog.py`
- Modify: relevant main-window connection/status mixins
- Add: `scripts/vector_xcp_diagnostic.py` if the existing CLI cannot emit the
  required staged JSON cleanly
- Test: `tests/test_vector_hw_probe.py`
- Test: `tests/test_vector_probe_stages.py`
- Test: `tests/test_capture_cli.py`
- Test: `tests/acquisition_ui/test_settings_transport_tab.py`

- [ ] Make Test Connection use Task 2's production adapter and Task 3's
  protection logic.
- [ ] Return structured stages: runtime, Vector, CONNECT, protection, DAQ info,
  cleanup. UI text is rendered from these fields, not parsed back from prose.
- [ ] Ensure A2L loads before Test Connection, since CAN IDs and DAQ facts come
  from it.
- [ ] Add a diagnostic mode that can stop after:
  - package/import check;
  - Vector open;
  - XCP CONNECT/status;
  - one-signal DAQ first DTO;
  - timed MF4 capture.
- [ ] Make every mode save exact configuration/version/A2L hash and counters to
  JSON without leaking Seed&Key material.
- [ ] Ensure `--backend vector` uses the same runtime/DAQ/policy code and exact
  version gate as Cockpit.

**Exit:** there is one implementation for runtime construction and one for DAQ;
UI, diagnostic, and CLI are orchestration shells only.

**Commit:** `feat(acq): add staged Vector XCP diagnostics`

---

## Task 10: Make the Windows folder build prove its runtime closure

**Files:**

- Modify: `tools/build_windows_folder.ps1`
- Modify: `tools/pyinstaller_rthook_pyxcp_vendor.py`
- Modify: `tests/test_windows_build_script.py`
- Modify: `tests/test_packaging_imports.py`
- Add: packaged runtime smoke support to the main entrypoint or diagnostic

- [ ] Build script installs/validates the exact acquisition constraints before
  vendoring.
- [ ] Determine the full pyxcp runtime dependency closure from the installed
  distribution metadata and imports. Vendor/copy the required packages,
  metadata, native modules, resources, and entrypoint support without letting
  PyInstaller analysis import the known crash-class modules.
- [ ] Keep the existing isolated import protection. Do not solve the build by
  globally importing pyxcp in the spec/analysis process.
- [ ] After build, launch the executable with a non-GUI diagnostic flag that:
  - reports source/frozen mode;
  - imports the vendored runtime through the real adapter;
  - verifies exact versions and required policy/config surfaces;
  - exits nonzero on failure.
- [ ] Save the smoke JSON next to the build artifact.
- [ ] Test that the build script contains both the version guard and the
  post-build executable smoke; source-venv import alone is insufficient.

**Windows commands:**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_windows_build_script.py `
  tests\test_packaging_imports.py -q
powershell -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1 -Console
.\dist\MF4DataAnalyzer\MF4DataAnalyzer.exe `
  --acquisition-runtime-smoke `
  --json evidence\vector-xcp\packaged-runtime-smoke.json
```

**Exit:** the built executable—not merely the build venv—imports and validates
the pinned runtime successfully.

**Commit:** `build(win): verify frozen Vector XCP runtime`

### Pre-bench documentation gate

Before Task 11, rewrite `docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md`
as a pre-bench draft and add
`docs/analyzer/acquisition/evidence/vector-xcp/README.md` as the evidence
template. The draft must already contain the corrected order, exact version
gate, stage-specific JSON capture, source/frozen split, first-decoded-DTO gate,
counter worksheet, and NO-GO rules from the source spec. Commit this separately
as `docs(acq): prepare pinned Vector XCP bench runbook` and print/use that exact
revision at the bench. Task 13 finalizes its results and verdict after execution.

---

## Task 11: Execute first-DTO and source MF4 bench gates

**Environment:** Windows x64 + Vector + powered ECU, stationary bench/HIL or
vehicle in workshop. Start with classic CAN 500 kbit/s unless the actual target
configuration says otherwise.

**Before touching hardware:**

- [ ] Print the pre-bench runbook committed after Task 10 and record its commit.
- [ ] Confirm ECU side (A/B), exact A2L path/hash, command/response IDs, Vector
  model/serial, application/channel, termination, bitrates, and Seed&Key state.
- [ ] Confirm no CANape/CANoe/other process owns the same Vector application
  channel.
- [ ] Run Task 1's source runtime verifier and Task 10's packaged smoke.
- [ ] Create a new evidence directory; never overwrite a prior round.

### Gate 11A — Vector and Test Connection

```powershell
.\.venv\Scripts\python.exe scripts\vector_xcp_diagnostic.py `
  --stage connect `
  --a2l "<exact path>" `
  --app-name Python --channel 0 --bitrate 500000 `
  --evidence "evidence\vector-xcp\<date>-<round>\connect.json"
```

Pass requires runtime/Vector/CONNECT/protection/DAQ-info/cleanup all green. Save
the literal error and full JSON before changing settings on a failed attempt.

### Gate 11B — one known signal, first decoded DTO

- [ ] Select one signal with known event, datatype, conversion, unit, and
  plausible stationary value.
- [ ] Run Connect ECU, not Record.
- [ ] Pass only when the current session receives and decodes the selected
  signal before the calculated deadline.
- [ ] Compare the raw bytes/decoded value/conversion against an independent
  reference (CANape may be used as a separate reference session, not as the
  collector and not concurrently on the same channel).
- [ ] Save diagnostic JSON and a screenshot showing real backend, channel,
  selected signal, first-frame state, and plausible value.

### Gate 11C — source-mode 3-signal/30-second MF4

- [ ] Select three signals from one known event.
- [ ] Connect and wait for first decoded DTO.
- [ ] Press Record for 30 s, then Stop.
- [ ] Confirm the backend did not reconnect at Record or Stop.
- [ ] Confirm idle preview continues after Stop.
- [ ] Reopen MF4 and independently check:
  - exactly the selected channel names;
  - units and value plausibility;
  - monotonic time;
  - per-channel sample count within the declared event tolerance;
  - median interval within ±10% of raster for the no-timestamp ERD6 case;
  - worst interval deviation within the runbook threshold;
  - all bus/queue/decode/writer drop counters are zero.

On any nonzero drop, unknown PID, decode error, implausible value, or cleanup
failure, stop and return to the corresponding implementation task. Do not
continue to larger selections.

---

## Task 12: Packaged, mixed-event, soak, and recovery acceptance

Proceed only after Task 11 passes from source.

### Gate 12A — packaged one-signal and 3-signal captures

Repeat Gate 11B and Gate 11C from the folder-style executable. Pass criteria are
identical. Package/import success without an MF4 is not enough.

### Gate 12B — 12 signals across two events

- [ ] Choose a documented split, initially 8 signals on 10 ms and 4 on 100 ms
  if those events exist on the target.
- [ ] Record 60 s.
- [ ] Verify every channel independently and by event group.
- [ ] Prove actual PIDs are non-overlapping and match diagnostic mapping.
- [ ] Require zero drops/errors and successful MF4 reopen.

### Gate 12C — Record/Stop/Record in one connection

- [ ] Connect once.
- [ ] Record 30 s, stop, remain previewing, then record another 30 s.
- [ ] Prove one XCP CONNECT/DAQ allocation, two writer lifecycles, two valid
  MF4s, and continuous preview/session timestamps.

### Gate 12D — 30-minute stationary soak

- [ ] Run representative selected signals for 30 minutes; record for the full
  interval if disk/memory estimates are safe.
- [ ] Capture queue high-water marks, process memory, CPU, last-frame age,
  sample/write rate, bus/decode/drop counters, and final cleanup.
- [ ] Pass only with zero accepted-path drops/errors and a reopenable MF4.

### Gate 12E — controlled recovery

On a bench where safe and authorized:

- [ ] disconnect/reconnect Vector cable or cycle ECU power while not recording;
- [ ] verify the app reports the actual failed stage and returns to a clean
  reconnectable state;
- [ ] reconnect and repeat one-signal first DTO without restarting the app;
- [ ] do not inject faults during public-road operation.

CAN-FD and other VN models remain `NOT TESTED` until their own Gate 11/12 set is
run. A classic-CAN VN1630A pass cannot be relabeled as a generic Vector pass.

---

## Task 13: Finalize operator docs and issue the final verdict

**Files:**

- Modify: `docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md`
- Modify: `docs/analyzer/acquisition/evidence/vector-xcp/README.md`
- Add per run: evidence manifest/README plus generated JSON/MF4 artifacts or
  repository-approved references when binaries are too large
- Update predecessor spec/plan headers with a short pointer to the new
  correction artifacts; do not rewrite their history

- [ ] Confirm the committed pre-bench runbook used this order and annotate each
  step with its actual evidence/result:

  ```text
  verify exact runtime/build
  -> load A2L
  -> configure transport
  -> Test Connection
  -> select known measurement
  -> Connect ECU and wait for decoded first DTO
  -> Record
  -> Stop/reopen/validate
  ```

- [ ] Remove instructions to install unpinned latest packages.
- [ ] Remove raw CONNECT RESOURCE lock interpretation.
- [ ] Add stage-specific failure capture, exact version/config/A2L hash fields,
  backend identity, counters, MF4 validation worksheet, and source/frozen split.
- [ ] Make the runbook state that CANape may be an independent reference only;
  it is not part of this program's acquisition chain.
- [ ] Run the full hardware-free regression on macOS and the complete Windows
  acquisition suite.
- [ ] Run `git diff --check`, stale-identifier grep, and changed-file review.
- [ ] Complete the project lesson gate. Promote a lesson only if the work found
  a new recurring failure not already covered by the native-import,
  phantom-API, or acquisition-evidence lessons.

**Required final verdict table:**

| Combination | Source | Packaged | First DTO | MF4 | Soak | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| exact Python/packages/driver/Vector/ECU/A2L/classic-CAN config | evidence link | evidence link | evidence link | evidence link | evidence link | PASS/PARTIAL/BLOCKED |
| CAN-FD | evidence or NOT TESTED | ... | ... | ... | ... | ... |
| each additional VN model | evidence or NOT TESTED | ... | ... | ... | ... | ... |

No tag named `bench-validated`, `vehicle-ready`, or equivalent is created until
the exact row is PASS.

---

## Final verification commands

### macOS / hardware-free

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_pyxcp_runtime.py \
  tests/test_pyxcp_daq_policy.py \
  tests/test_vector_xcp_backend.py \
  tests/test_xcp_daq_session.py \
  tests/test_xcp_auth.py \
  tests/test_daq_map_builder.py \
  tests/test_dto_decode.py \
  tests/test_vector_hw_probe.py \
  tests/test_vector_probe_stages.py \
  tests/test_native_import_boundaries.py \
  tests/test_capture_controller.py \
  tests/acquisition_ui/test_capture_session.py \
  tests/acquisition_ui/test_record_backend_swap.py \
  tests/acquisition_ui/test_settings_transport_tab.py \
  tests/acquisition_ui/test_state_machine.py -q
```

Also run the repository's broader acquisition/Cockpit suite selected from the
actual changed-file scope. Do not freeze an expected test count in perpetuity;
record the live count and command in the final evidence.

### Windows / source and build

```powershell
.\.venv\Scripts\python.exe scripts\verify_windows_acquisition_runtime.py `
  --json evidence\vector-xcp\final-api-contract.json
.\.venv\Scripts\python.exe -m pytest `
  tests\test_pyxcp_029_contract.py `
  tests\test_pyxcp_runtime.py `
  tests\test_pyxcp_daq_policy.py `
  tests\test_vector_xcp_backend.py `
  tests\test_xcp_daq_session.py `
  tests\test_xcp_auth.py `
  tests\test_windows_build_script.py -q
powershell -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1 -Console
.\dist\MF4DataAnalyzer\MF4DataAnalyzer.exe `
  --acquisition-runtime-smoke `
  --json evidence\vector-xcp\final-packaged-runtime.json
```

Hardware commands and MF4 verification follow Tasks 11-12 and the rewritten
runbook; they cannot be replaced by the commands above.

## Stale-contract guard

Before implementation handoff, inspect every match and ensure old behavior is
present only in historical/correction context, not active code/runbook:

```bash
rg -n "master\.fetch|transport\.fetch|resource_id=|allocDaq\(daq_list|mode=0x10|pyxcp>=0\.22|RESOURCE=0x" \
  mf4_analyzer tests requirements.txt requirements-windows-acquisition.txt \
  docs/analyzer/acquisition/runbooks/stage-8-pr4-bench.md
```

Expected production result: no DTO fetch fallback, no obsolete auth keywords,
no per-list allocation, no unconditionally hard-coded timestamp mode, no broad
production pyxcp range, and no runbook claim that a RESOURCE byte proves unlock.
