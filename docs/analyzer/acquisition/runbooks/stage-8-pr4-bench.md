# Stage 8 PR-4 — Bench Validation Runbook

**Status:** Pending operator execution. All Mac-side prerequisites
landed 2026-05-19 in the Phase-A commit batch (see
`runbooks/2026-05-19-stage-8-vn1630-vehicle-test-action-board.html`).

**Purpose.** Verify that `VectorXcpRecorderBackend` records valid MF4
from a real ECU before declaring Stage 8 done. Run on Windows + Vector
hardware + powered ECU.

**Source.** This file is the operator-facing extract of
`plans/2026-05-17-stage-8-vector-xcp-backend.md` §PR-4 Task 19 (3770+).
The plan stays the authoritative design doc; this runbook is what you
print and bring to the bench.

---

## 0. What changed on Mac side before this runbook
Refer to the action board for the full punch-list. The five things the
operator most needs to know:

1. **Cockpit Record path now swaps to `VectorXcpRecorderBackend` automatically**
   when Transport is configured, A2L IF_DATA is loaded, and the
   measurement pool is non-empty. Otherwise the status bar shows a
   loud `[FAKE backend] 不录真实 ECU: <reason>` warning — **never
   ignore this on the bench**.
2. **Picking an A2L now populates the left pane** (T1-1) and shows
   all 323 ERD6 measurements (T1-2, no more `limit=20` truncation).
3. **`daq_timestamp_size = 0` is fixed** (T1-5): per-frame
   `time.monotonic()` arrival is converted to seconds from capture
   start before it becomes the sample timestamp. Two consecutive DTOs
   now yield strictly increasing, session-relative timestamps in the
   MF4. The §"Acceptance gate" check for ts_size=0 ECUs below now bites
   if drift exceeds ±25 ms.
4. **CLI `--backend vector` works** (T1-4). The pre-built cockpit is
   the primary path, but this CLI is the back-up for headless bench
   testing or when the cockpit can't open. It binds `--signals` through
   the A2L measurement summary and IF_DATA event table before opening
   Vector, so bad names / missing events fail early. Usage:
   ```powershell
   .\.venv\Scripts\python.exe -m mf4_analyzer.acquisition_capture `
       --backend vector --a2l <path>.a2l --duration 30 `
       --output evidence\stage-8\<date>-<round>\smoke.mf4 `
       --signals EngineSpeed,Throttle,Steering `
       --app-name Python --channel 0 --bitrate 500000
   ```
5. **Config persists** (T1-6): once you configure Transport in
   Settings, it survives cockpit restart via
   `<project>/acquisition_config.yaml`. If the operator changes
   machines between rounds, copy that file along too.

---

## Pre-flight

- [ ] **O-1** A2L on local disk; note path. `IF_DATA XCP` block visible
  in the cockpit's Settings → Test Connection diagnostic.
- [ ] **O-2** Vector Hardware Configurator opens; note `app_name` and
  channel for the bench. Hardware (VN1610 / VN1630 / VN1640) connected
  and recognized.
- [ ] **O-3** Confirm XCP slave authentication state. If seed&key on,
  place the DLL at a path you'll enter in Settings → Transport →
  Seed&Key DLL.
- [ ] **O-4** Bench / ECU powered, CAN harness terminated, vehicle key
  in run position (if applicable).
- [ ] **O-5** Decided whether first session is classic CAN or CAN-FD.
  **Recommended: classic CAN 500k first** (ERD6 ships classic CAN).
- [ ] `.\.venv\Scripts\python.exe -m pip install "python-can[vector]"
  pyxcp` succeeded on this PC.
- [ ] `.\.venv\Scripts\python.exe -m can_logger.p0.vector_probe --open --app-name Python
  --channel 0 --bitrate 500000` returns clean output (driver loadable,
  application configured, channel present, bus opens).

---

## Test sequence

### Step 1 — Cold connection
1. Launch cockpit: `.\.venv\Scripts\python.exe -m mf4_analyzer.acquisition_ui`.
2. Open Settings → Transport. Enter app_name, channel, bitrate from O-2.
3. Click **Test Connection**.
4. **Expected**: green toast "OK · driver vX.Y.Z · RESOURCE=0xXX · NN ms".
5. **If red**: copy the error verbatim; consult §Common errors below;
   fix and retry. Save the toast text in
   `evidence/stage-8/<date>-<round>/step1-failure.txt` before fixing
   so the next round has a paper trail.

### Step 2 — Load A2L
1. Cockpit toolbar **选择 A2L** → pick the file from O-1.
2. Left pane populates with measurement tree (status bar:
   "A2L 已加载：N measurement"; ERD6 should show **323**).
3. "有 DAQ" chip should be **enabled** (greyed = IF_DATA missing — file
   a bug if you expected events).
4. If a QMessageBox warning pops up (T2-2), **stop** and capture its
   exact text into `evidence/stage-8/<date>-<round>/step2-a2l-warning.txt`.
   Do not proceed — IF_DATA or measurement parse failures clear both
   the cached IF_DATA and measurement pool, so everything downstream is
   intentionally blocked until the A2L loads atomically.

### Step 3 — Three-measurement smoke (10 ms event)
1. Pick 3 measurements all on the "10ms" event (or whatever the ECU's
   fastest DAQ event is). For ERD6, `Rte_OsTask_BSW_10ms` is the
   common pick.
2. **Status bar must NOT say `[FAKE backend]`** — if it does, abort.
   That means transport / IF_DATA / pool wiring is incomplete; capture
   the warning text and the cockpit screenshot, then go back to Step 1.
3. Click Record. Wait 30 s. Click Stop.
4. Review Modal opens. Click "在 Analyzer 打开".
5. Analyzer must show 3 channels. Each channel: ~3000 samples
   (30 s × 100 Hz, ±5%).
6. **Pass**: tick this step. Save the MF4 to
   `evidence/stage-8/<date>-<round>/step3-3sig-30s.mf4`.

### Step 4 — Twelve-measurement two-event
1. Pick 8 measurements on "10ms" + 4 on "100ms".
2. Record 60 s.
3. Analyzer: 12 channels. The 8 "10ms" channels ≈ 6000 samples each;
   the 4 "100ms" channels ≈ 600 samples each.
4. Save as `step4-12sig-60s.mf4`.

### Step 5 — Cross-hardware
Repeat Step 3 once on each VN model available (VN1610, VN1630, VN1640).
Reuse the same app_name; physically swap the hardware in Vector
Hardware Configurator between runs. Save each as
`step5-<vnmodel>-3sig-30s.mf4`.

### Step 6 — CAN-FD (if O-5 = CAN-FD)
1. Settings → Transport → check "CAN-FD". Set data_bitrate from O-5.
2. Test Connection → green.
3. Repeat Step 4 but with 24 measurements (CAN-FD's larger MAX_DTO
   permits this in a single ODT per event). Save as
   `step6-canfd-24sig-60s.mf4`.

---

## Acceptance gate

All of Step 3, Step 4, Step 5 (at least one HW model), and Step 6 (if
O-5 = CAN-FD) green at least once. File the captured MF4s under
`docs/analyzer/acquisition/evidence/stage-8/<YYYY-MM-DD>-<round>/`.

### T1-5 cross-check (`daq_timestamp_size = 0` ECUs, including ERD6)

The MF4 sample timestamps come from host `time.monotonic()` arrival
time converted to seconds from capture start, not the ECU. Open one MF4
from Step 3 in Analyzer, pick a single channel, compute the diff of
consecutive sample timestamps for the same event, and confirm:

| Metric | Tolerance |
|---|---|
| Median consecutive diff | within ±10 % of the event's `cycle_time_ms` |
| Worst sample-to-sample deviation | within ±25 ms |

Anything larger is host / driver buffering masquerading as sample
timing and must be filed against backend Task 13's capture thread, not
accepted as ECU clock.

Skip this check when `daq_timestamp_size > 0` (the ECU clock is
authoritative).

---

## Common errors

| Toast / status text | Cause | Fix |
|---|---|---|
| `vxlapi DLL not loadable` | Vector driver not installed | Install Vector Hardware Configurator |
| `Vector application 'Python' not configured` | app_name doesn't exist in Vector Hardware Config | Open Vector Hardware Configurator, create the application slot |
| `channel N not present` | Channel number exceeds installed channel count | Decrement channel until match |
| `XCP CONNECT failed: no response` | ECU not powered, wrong CAN ID, wrong bitrate | Re-check power, A2L `CAN_ID_MASTER`, bitrate matches ECU |
| `negative XCP response: pid=0xFE, code=0x35` | DAQ list exhausted | Reduce selection count |
| `Seed&Key 失败` | DLL path wrong or bitness mismatch | Verify path, confirm 64-bit DLL for 64-bit Python |
| `[FAKE backend] 不录真实 ECU: ...` | Cockpit can't construct VectorXcpRecorderBackend | This now blocks the connection attempt in vehicle mode. Check the reason: Transport 未配置 / A2L IF_DATA 未加载 / measurement pool 为空 — go back to the corresponding step. If you see "Vector 不可用：Windows" you're running on Mac/Linux and shouldn't be at this runbook yet. |
| `A2L measurement 解析失败: ...a2ldb already exists` | Stale pya2l sidecar from a previous import | Fixed in Phase A: `load_measurement_summary` now imports with `remove_existing=True`. If it recurs, save the warning text and A2L path; do not delete random files on the bench. |
| `A2L 不含可用 IF_DATA XCP block (XCPplus-only ECU 或 transport 段缺失)` | Parser regex skips `XCPplus`-prefixed blocks. ERD6 is plain XCP so this should not fire; if it does, the A2L either uses XCPplus only (file a parser-extension task) or has lost its transport block. | Confirm A2L source; if XCPplus-only, escalate to extend `ifdata_xcp.py` regex |

---

## After acceptance

- [ ] Tag the merge commit `stage-8-bench-validated`
- [ ] File a short note in `evidence/stage-8/<date>-<round>/README.md`
  listing the MF4 names, pass/fail per step, and operator observations.
- [ ] Close all open O-* items in `plans/2026-05-17-stage-8-vector-xcp-backend.md` §0
- [ ] Flip step 9 of the action board (Phase B → Phase C) to ✅ once
  Step 3 + Step 4 are green on at least one VN model.

---

## When you go back to Phase A (Mac side)

If the bench surfaces a code-side bug:

1. Triage per the plan's §Task 20 Step 2 classification (A2L dialect /
   DAQ alloc / DTO decode / Vector driver).
2. Write a failing test on Mac using the captured bytes as a fixture
   (drop them in `tests/fixtures/`).
3. Apply the fix, prove green on Mac, then come back to this runbook
   for a re-run.
4. Append the new failure mode + fix as a row to the "Common errors"
   table above so the next operator finds it.
