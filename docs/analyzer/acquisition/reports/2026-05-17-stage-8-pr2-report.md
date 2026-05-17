---
date: 2026-05-17
stage: 8
pr: PR-2
plan: docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md
spec: docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md
verdict: GREEN_WITH_LIMITS
author: codex
---

# Stage 8 PR-2 Report

## Verdict

**GREEN_WITH_LIMITS.** PR-2 backend core is implemented and mock-validated on
macOS. It adds the DAQ map builder, DTO decoder, Seed&Key helper,
`XcpDaqSession`, and a real `VectorXcpRecorderBackend` path that is still
lazy-import / Windows-only. It does not prove real Vector driver, pyXCP, ECU,
or bench timing behavior; those remain PR-4 hardware gates.

## Implemented

- Added `DaqMap` / `OdtEntry` plus `build_daq_map()` to group selected
  measurements by DAQ event, pack ODTs within `MAX_DTO`, and source address /
  datatype from live `SelectedMeasurement` + `MeasurementSummary`
  (`mf4_analyzer/acquisition_capture/daq_map.py:13`,
  `mf4_analyzer/acquisition_capture/daq_map.py:59`).
- Added pure DTO decode for PID lookup, timestamp conversion, endianness, and
  canonical A2L datatype tokens such as `UWORD` / `SLONG`
  (`mf4_analyzer/acquisition_capture/dto_decode.py:11`,
  `mf4_analyzer/acquisition_capture/dto_decode.py:35`).
- Added Seed&Key unlock handling for locked DAQ resources, including missing
  DLL, bitness mismatch, DLL compute failure, and ECU unlock rejection paths
  (`mf4_analyzer/acquisition_capture/xcp_auth.py:9`,
  `mf4_analyzer/acquisition_capture/xcp_auth.py:39`).
- Added `XcpDaqSession` command orchestration: CONNECT, optional unlock,
  DAQ allocation/programming, start/stop sync, and timestamp unit conversion
  (`mf4_analyzer/acquisition_capture/xcp_daq_session.py:34`,
  `mf4_analyzer/acquisition_capture/xcp_daq_session.py:60`).
- Replaced the Vector backend stub with a Windows-only implementation that
  opens `python-can`, creates a pyXCP master, starts `XcpDaqSession`, drains DTO
  frames through `decode_dto()`, and reports the live `BackendStatus` shape
  expected by `CaptureController`
  (`mf4_analyzer/acquisition_capture/backends.py:412`,
  `mf4_analyzer/acquisition_capture/backends.py:432`,
  `mf4_analyzer/acquisition_capture/backends.py:533`).

## Plan Fixes Applied

- Corrected the PR-2 DAQ-map example so three 2-byte measurements use
  `MAX_DTO=9`; with `MAX_DTO=8`, the payload budget is only five bytes and
  the third measurement must spill (`docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md:1363`).
- Updated Task 10 examples to include required `OdtEntry.address`, to exercise
  canonical A2L datatypes, and to map those datatypes in `dto_decode`
  (`docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md:1625`,
  `docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md:1744`).
- Updated Task 11 imports and Task 12 mock / expected test counts to match
  the live implementation and tests
  (`docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md:1935`,
  `docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md:2441`,
  `docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md:2702`).

## Tests Added

- `tests/test_daq_map_builder.py`: event grouping, ODT packing, missing A2L
  lookup, and missing event errors (`tests/test_daq_map_builder.py:90`).
- `tests/test_dto_decode.py`: little-endian timestamped DTOs, no-timestamp
  DTOs, big-endian signed 32-bit decode, and unknown PID drop
  (`tests/test_dto_decode.py:24`).
- `tests/test_xcp_auth.py`: unlocked skip, locked-without-DLL, missing DLL,
  bitness mismatch, happy unlock, and ECU rejection (`tests/test_xcp_auth.py:14`).
- `tests/test_xcp_daq_session.py`: start command sequence, stop/disconnect,
  and CONNECT failure mapping (`tests/test_xcp_daq_session.py:67`).
- `tests/test_vector_xcp_backend.py`: mocked lifecycle, status shape,
  CaptureController summary compatibility, DTO poll queue, and off-Windows
  unavailable behavior (`tests/test_vector_xcp_backend.py:79`).

## Validation Evidence

- Initial PR-2 red test:
  - `PYTHONPATH=. .venv/bin/python -m pytest tests/test_daq_map_builder.py tests/test_dto_decode.py tests/test_xcp_auth.py tests/test_xcp_daq_session.py tests/test_vector_xcp_backend.py -v`
  - Result: failed during collection with missing `mf4_analyzer.acquisition_capture.daq_map`, proving the new tests were not false-green.
- Focused PR-2 suite after implementation:
  - `PYTHONPATH=. .venv/bin/python -m pytest tests/test_vector_xcp_backend.py tests/test_daq_map_builder.py tests/test_dto_decode.py tests/test_xcp_auth.py tests/test_xcp_daq_session.py -v`
  - Result: **23 passed in 0.62s**
- Full PR-2 acquisition suite:
  - `PYTHONPATH=. .venv/bin/python -m pytest tests/test_acquisition* tests/test_ifdata_xcp_parser.py tests/test_transport_config.py tests/test_config_store_migration.py tests/test_daq_map_builder.py tests/test_dto_decode.py tests/test_xcp_daq_session.py tests/test_xcp_auth.py tests/test_vector_xcp_backend.py -v`
  - Result: **251 passed in 8.05s**
- CLI fake smoke:
  - `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.acquisition_capture --backend fake --duration 2 --output /tmp/cap.mf4 --signals EngSpdAvg,EngTrqAct,VehSpeedRaw`
  - Result: exit 0; wrote `/tmp/cap.mf4` and `/tmp/cap.session_summary.json`; printed `rx=558 write=558 dropped=0 warnings=0`
- Legacy-drift grep over Stage 8 plan/spec/reports:
  - Result: no stale bare command examples, stale identifiers, old UI smoke flags, memory-file references, or first-IF_DATA-block snippets.
- Analyzer doc-routing grep over Stage 8 plan/spec/reports:
  - Result: no stale top-level analyzer doc paths.
- `git diff --check`
  - Result: no whitespace errors
- `/usr/bin/python3 scripts/lessons/check.py --status`
  - Result: `lesson_required: False`, `candidate_exists: False`

## Remaining Gates

- **PR-3:** UI integration for transport settings, hardware/XCP connection
  probe, and toolbar transport status.
- **PR-4:** Windows + Vector + ECU bench validation, including pyXCP method
  signature verification against real packages and real DTO timing.
- `scripts/probe_a2l_dbc.py` remains untracked and outside the PR-1/PR-2 scope.
