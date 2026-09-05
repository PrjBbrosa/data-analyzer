# Vector/XCP pinned-runtime bench runbook

Status: **BLOCKED pending Windows W1/W2 and physical ECU evidence**. This
runbook is valid only with the July 11 pyxcp 0.29 readiness correction and is
not evidence that a vehicle is ready.

Before opening the Vector channel, record the application commit, Python bitness, `python-can==4.6.1`, `pyxcp==0.29.10`, `pya2ldb==1.0.332`, Vector driver/model/serial, application slot/channel/bitrate/CAN mode, A2L path/SHA-256, command/response CAN IDs, ECU side, selected event list, harness/termination, and DAQ protection/provider identity. Do not put Seed&Key secrets in JSON.

The current runtime reports `timing_source=driver_automatic` and
`sample_point_applied=False`. The disabled 75/70 percent fields exist only for
legacy config compatibility; they are not measured or applied timing facts.
Any stored non-default sample-point values are a fail-closed configuration
error. Do not construct or claim custom BitTiming without hardware clock/tseg
evidence.

The verifier and build write their machine-gate JSON to
`docs/analyzer/acquisition/evidence/vector-xcp/`. After those gates pass,
create `<date>-<run>/` there from the adjacent README template and copy the
exact runtime JSON into the retained run alongside bench facts. Missing
evidence is `UNKNOWN`, not green. Confirm CANape/CANoe or another process does
not own this channel; CANape may be an independent reference only, never this
collector.

## Ordered bench procedure

1. Verify the exact Windows package contract. Stop on any failure.

   ```powershell
   .\.venv\Scripts\python.exe scripts\verify_windows_acquisition_runtime.py --json docs\analyzer\acquisition\evidence\vector-xcp\api-contract.json
   ```

2. Build the folder executable and keep its runtime-smoke JSON.

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1
   .\dist\TraceLab8.2.2\TraceLab8.2.2.exe --acquisition-runtime-smoke --json docs\analyzer\acquisition\evidence\vector-xcp\packaged-runtime-smoke.json
   ```

   W2 must use the default `--windowed` build above, because that is the
   production artifact and intentionally has no `sys.stdout`/`sys.stderr`.
   Use `-Console` only to diagnose a failed W2; a console-build PASS does not
   substitute for windowed evidence.

   The build itself also writes `build-api-contract.json` and
   `packaged-runtime-smoke.json` to
   `docs/analyzer/acquisition/evidence/vector-xcp/`. Keep those files separate
   from the source-environment `api-contract.json`. The packaged smoke must
   report the pinned pya2ldb metadata and successful hidden-child pya2l import
   probe. Its `a2l_parse_probe` must also be green and show
   `TraceLab8.2.2.exe --a2l-probe-child`, return code zero, and the expected
   `RuntimeSmokeSignal`/`0x1000`/`UWORD` facts from the unpickled one-signal
   fixture. Then load the exact ECU A2L once in the frozen app before
   connecting the ECU.

   W1 and W2 must both be PASS before the status changes to
   `PROCEED TO PHYSICAL BENCH`.

3. Load the exact A2L, configure transport, and run **Test Connection**. Pass only with driver/device, CONNECT latency, GET_STATUS protection state, DAQ facts, and cleanup captured. CONNECT RESOURCE does not prove unlock, streaming, or MF4.

4. Select one known signal with event/datatype/conversion/unit. **Connect ECU** and require a decoded DTO before the deadline. Save staged JSON and screenshot. Unknown PID, decode error, missing mapping, timeout, or implausible value is a stop.

5. Source gate: three signals/one event, first DTO, Record 30 s, Stop, verify preview continues without reconnect, reopen MF4. Require names, units, values, monotonic time, event-based sample counts/timing, and zero queue/decode/writer/policy drops or errors. The current pyxcp path reports `bus_error_observable=False`; record application-level bus error as `UNKNOWN`, never infer PASS from `bus_error_count=0`. Retain Vector/driver bus state when an external supported source exposes it, plus transport exceptions, timeouts, and DTO continuity as separate evidence.

6. Frozen gate: repeat one-/three-signal gates from the packaged app. Package import success alone is not a pass.

7. Only after 1-6: 12 signals/two events/60 s, Record/Stop/Record in one connection, 30-minute stationary soak, and controlled non-recording recovery. CAN-FD and other VN models remain `NOT TESTED` until they repeat these gates.

## Hard NO-GO

Do not collect on a vehicle when versions differ, Test Connection has not passed against the loaded A2L/powered ECU, no selected signal decoded a first DTO, backend is FAKE/replay, DAQ protection is unknown/failed, runtime evidence is synthetic/unknown, packaged smoke is red, or an accepted run has a nonzero drop/unknown-PID/decode error.

Only the exact source+frozen Python/package/driver/Vector/ECU/A2L/classic-CAN
row may be PASS. Steps 3-6 are required for `BENCH-VALIDATED`; step 7 is
required before `vehicle-ready`.
