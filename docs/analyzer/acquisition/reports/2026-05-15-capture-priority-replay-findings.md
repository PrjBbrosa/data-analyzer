# Capture Priority And MF4 Replay Findings

- Date: 2026-05-15
- Branch inspected: `fix/acquisition-docs-and-polish`
- Purpose: record the replay findings, clarify that the product goal is **data acquisition / recording first**, and set the next implementation priorities.

## One-line Decision

Current isolation boundaries are right, but the product goal must shift from "validate historical MF4" back to **recording first**. Replay, preflight, and quality checks stay as post-record diagnostics; they must not become hard gates for successful acquisition.

## User Clarification

The actual target is **采集数据**:

- The first useful outcome is "can record and save data".
- Frame drops, timestamp jumps, bus congestion, and uneven timing are expected real-world acquisition conditions.
- These conditions matter for later analysis quality, but they should not block recording or saving the raw capture.

## Replay Evidence From `testdoc`

Command family used:

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/acquisition_smoke.py --skip-regression
TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python - <<'PY'
# summarized local replay/preflight probe over testdoc/*.mf4
PY
```

Observed results:

| Check | Result |
| --- | --- |
| Acquisition smoke without local regression dataset | `45 passed` |
| `testdoc` MF4 files found | 9 |
| `analyze_mf4()` preflight OK | 8 / 9 |
| Snapshot build + immediate compare replay | 9 / 9 PASS |
| Main preflight red case | `testdoc/tiaodamping.MF4` |
| `tiaodamping.MF4` issue | `Time column is not strictly increasing` |
| `tiaodamping.MF4` measured timestamp issue | 2 non-increasing steps, min `dt=-2.288928216`, median positive `dt=0.010000081`, max `dt=2.754978240` |

Important interpretation:

- The loader can open all 9 files.
- Snapshot replay is stable for all 9 files.
- `tiaodamping.MF4` is a data-quality warning, not a recording failure.
- For acquisition, a timestamp jump should be recorded and reported, not used as a reason to discard the capture.

## Signal Alias Finding

Current checked-in example:

- `configs/signals/vehicles/X04C.example.json`
- `steering_angle_speed` currently maps only to `calculation_vSteeringAngleSpeed_xds16`.

The `testdoc` samples use another observed raw channel:

- `Rte_RotationSpeedCalculation_vSteeringAngleSpeed_xds16`

If this raw channel is added as a second alias candidate, 8 / 9 `testdoc` files can resolve all three seed standard signals (`vehicle_speed`, `torsion_bar_torque`, `steering_angle_speed`). The remaining file, `X04C_Ripple.mf4`, lacks `vehicle_speed`.

Impact:

- This is useful for diagnostics and later analysis.
- It is not a blocker for recording.

## Architecture Assessment

What is reasonable now:

- Hardware-related feasibility code is isolated under `can_logger/p0/`.
- `can_logger/p0/mf4_probe.py` proves that an MF4 emitted by the acquisition side can be loaded by the existing analyzer.
- Vector and XCP probes are platform-gated and do not pollute normal analyzer startup.
- `mf4_analyzer/acquisition/` is a useful offline validation and diagnostic package.

What is missing for the real goal:

- There is no production recorder backend yet.
- There is no receive loop, bounded queue, writer loop, segmenting policy, stop/flush contract, or session summary.
- There is no capture health accounting: received frames, written samples, queue overflow, bus errors, max queue depth, segment count.
- Current docs over-emphasize validation gates compared with the immediate user goal: recording data first.

## Consequence For Data Quality Problems

Timestamp jumps, dropped frames, and bus congestion should be treated as:

- **Capture health metadata** during recording.
- **Warnings** in post-record preflight.
- **Analysis caveats** for FFT/order/regression workflows.

They should not be treated as:

- A reason to stop recording.
- A reason to reject saving an MF4.
- A reason to block the recorder MVP.

## Recommended Target Architecture

```text
Capture hot path
Vector/CAN/XCP -> reader thread -> bounded queue -> MF4 writer -> session_summary.json

Post-record diagnostic path
saved MF4 -> preflight / replay / alias resolution / quality report
```

Design rule:

- The capture hot path prioritizes **durable recording**.
- The diagnostic path prioritizes **truthful quality reporting**.
- These two paths must not be coupled such that a diagnostic warning prevents saving raw data.

## Next Priority Queue

### P0 — Reframe The Acquisition Plan

Update acquisition planning/runbook language so future work does not confuse replay quality with capture success.

Concrete decisions to record:

- Recording MVP success means "data is received and saved with health metadata".
- Preflight/replay is post-record evidence, not a capture prerequisite.
- A capture can be successful while its quality report is warning/red.
- The current P0 runbook says production DAQ UI should wait for full Vector/XCP PASS; the master program plan allows PASS or documented narrow PARTIAL. This tension should be resolved explicitly before implementation planning continues.

### P1 — Implement A Minimal Recorder Backend

Build a CLI-first recorder MVP before any UI:

- `SessionConfig`: bus/interface/channel/bitrate/output path/duration/segment policy.
- Reader loop: receives CAN/XCP samples and timestamps them.
- Bounded queue: never lets UI or writer stalls crash the process silently.
- Writer loop: writes MF4 segments through `asammdf`.
- Stop/flush contract: Ctrl-C or timeout closes the MF4 cleanly.
- `session_summary.json`: `duration_s`, `rx_count`, `write_count`, `queue_overflow_count`, `bus_error_count`, `max_queue_depth`, `segments`, `output_mf4`.

Testing rule:

- Use fake bus/fake messages first so tests run on macOS without Vector.
- Keep `python-can[vector]` imports lazy and Windows-gated.

### P2 — Run Windows + Vector Hardware Proof

Use the existing `can_logger/p0/vector_probe.py` and `can_logger/p0/xcp_short_upload_probe.py` on the Windows + Vector + powered ECU workstation.

Required evidence:

- Vector channel list and open result.
- XCP `CONNECT` result.
- One read value from `SHORT_UPLOAD`.
- One MF4 file generated from that read path and loaded back by `DataLoader`.

### P3 — Add Post-record Diagnostics

After a recording is saved:

- Run preflight optionally.
- Report timestamp jumps, missing aliases, non-finite values, and estimated sampling rate.
- Do not mark the recording itself as failed unless file writing failed.

### P4 — UI Comes After CLI Recording Is Boring

Only after CLI recording is stable:

- Add an acquisition panel or separate cockpit UI.
- Display live status: recording duration, file size, rx rate, queue depth, warnings.
- Keep analysis/preflight warnings visually separate from "recording is alive".

## Files To Revisit Next

- `docs/analyzer/acquisition/plans/2026-05-14-data-acquisition-validation-program.md`
- `docs/analyzer/acquisition/P0_Runbook.md`
- `docs/analyzer/acquisition/reports/2026-05-14-p0-report.md`
- `can_logger/p0/mf4_probe.py`
- `can_logger/p0/vector_probe.py`
- `can_logger/p0/xcp_short_upload_probe.py`
- `configs/signals/vehicles/X04C.example.json`
- `mf4_analyzer/acquisition/preflight.py`

## Suggested Next Starting Prompt

Start from `docs/analyzer/acquisition/reports/2026-05-15-capture-priority-replay-findings.md`.

Goal: revise the acquisition plan from validation-first to capture-first, then design the minimal CLI recorder backend. Keep replay/preflight as post-record diagnostics and do not let data-quality warnings block saving captured data.

