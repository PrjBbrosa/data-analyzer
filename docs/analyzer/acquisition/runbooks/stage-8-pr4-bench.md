# Vector/XCP pinned-runtime bench runbook

Status: pre-bench draft. This runbook is valid only with the July 11 pyxcp 0.29 readiness correction and is not evidence that a vehicle is ready.

Before opening the Vector channel, record the application commit, Python bitness, `python-can==4.6.1`, `pyxcp==0.29.10`, Vector driver/model/serial, application slot/channel/bitrate/CAN mode, A2L path/SHA-256, command/response CAN IDs, ECU side, selected event list, harness/termination, and DAQ protection/provider identity. Do not put Seed&Key secrets in JSON.

Create `docs/analyzer/acquisition/evidence/vector-xcp/<date>-<run>/` from the adjacent README template. Missing evidence is `UNKNOWN`, not green. Confirm CANape/CANoe or another process does not own this channel; CANape may be an independent reference only, never this collector.

## Ordered bench procedure

1. Verify the exact Windows package contract. Stop on any failure.

   ```powershell
   .\.venv\Scripts\python.exe scripts\verify_windows_acquisition_runtime.py --json evidence\vector-xcp\api-contract.json
   ```

2. Build the folder executable and keep its runtime-smoke JSON.

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\build_windows_folder.ps1 -Console
   .\dist\MF4DataAnalyzer\MF4DataAnalyzer.exe --acquisition-runtime-smoke --json evidence\vector-xcp\packaged-runtime-smoke.json
   ```

3. Load the exact A2L, configure transport, and run **Test Connection**. Pass only with driver/device, CONNECT latency, GET_STATUS protection state, DAQ facts, and cleanup captured. CONNECT RESOURCE does not prove unlock, streaming, or MF4.

4. Select one known signal with event/datatype/conversion/unit. **Connect ECU** and require a decoded DTO before the deadline. Save staged JSON and screenshot. Unknown PID, decode error, missing mapping, timeout, or implausible value is a stop.

5. Source gate: three signals/one event, first DTO, Record 30 s, Stop, verify preview continues without reconnect, reopen MF4. Require names, units, values, monotonic time, event-based sample counts/timing, and zero queue/decode/writer/bus drops.

6. Frozen gate: repeat one-/three-signal gates from the packaged app. Package import success alone is not a pass.

7. Only after 1-6: 12 signals/two events/60 s, Record/Stop/Record in one connection, 30-minute stationary soak, and controlled non-recording recovery. CAN-FD and other VN models remain `NOT TESTED` until they repeat these gates.

## Hard NO-GO

Do not collect on a vehicle when versions differ, Test Connection has not passed against the loaded A2L/powered ECU, no selected signal decoded a first DTO, backend is FAKE/replay, DAQ protection is unknown/failed, runtime evidence is synthetic/unknown, packaged smoke is red, or an accepted run has a nonzero drop/unknown-PID/decode error.

Only the exact source+frozen Python/package/driver/Vector/ECU/A2L/classic-CAN row may be PASS; no `bench-validated` or `vehicle-ready` tag exists before its MF4 and soak evidence is stored.
