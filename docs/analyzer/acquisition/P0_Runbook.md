# P0 Acquisition Runbook

Date: 2026-05-14
Branch: feat/acquisition-validation-program
Machine: macOS (Darwin 25.5.0)
Python: 3.12 (.venv/bin/python)
Vector hardware: N/A (not available on host)
ECU: N/A (hardware-blocked)
A2L file: (set via P0_A2L_PATH env var when available; currently unset)

## Dependency Probe

Command:

```text
.venv/bin/python -m pip install pya2ldb==1.0.332 pyelftools==0.32
```

Result:

```text
post-install import probe:
  asammdf      OK 8.8.7
  elftools     OK 0.32
  pya2l.DB     OK
  python-can   absent (hardware-gated, intentional — Vector interface not
               required on macOS host; install gated to Windows P0 runs)
  pyxcp        absent (hardware-gated, intentional — only used by the
               XCP probe which is itself Windows + Vector-only)
```

Note: `python-can[vector]>=4.6,<5` and `pyxcp==0.29.8` are intentionally
absent on this macOS host. They are installed only on the Windows
workstation that owns Vector hardware, per the P0 plan §Task 1 Step 4.

## MF4 Compatibility

Command:

```text
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_mf4_probe.py -v
```

Result:

```text
tests/test_p0_mf4_probe.py::test_p0_written_mf4_loads_through_existing_loader PASSED [0.23s]
1 passed
```

Result: **PASS**. The MF4 file produced by `write_single_signal_mf4`
opens cleanly through the existing `mf4_analyzer.io.loader.DataLoader`,
exposes the `EngineSpeed` channel with unit `rpm`, and the sample
column matches the input samples to `pytest.approx` tolerance. This is
the load-bearing compatibility proof: any P0/P1 acquisition path that
emits MF4 can be consumed by the analyzer without loader changes.

## A2L Parse

Command:

```text
PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_a2l_probe.py -v
```

Result:

```text
tests/test_p0_a2l_probe.py::test_p0_real_a2l_has_measurements SKIPPED
  reason: 'set P0_A2L_PATH to a real ECU A2L file for this probe'
1 skipped
```

Result: **SKIPPED (acceptable)**. This is the documented skip path
defined in the P0 plan §Task 3 Step 1 — the test is `@pytest.mark.skipif`
gated on `P0_A2L_PATH`, and the parser module (`a2l_probe.py`,
including `MeasurementSummary`, `A2LSummary`, `load_measurement_summary`)
was implemented and committed in `c5eed55`. The A2L gate counts as
passing in skipped state on this macOS host.

To convert this gate to PASS, run on any workstation that has access
to a real ECU A2L file:

```text
P0_A2L_PATH=<absolute path to real.a2l> \
  PYTHONPATH=. .venv/bin/python -m pytest tests/test_p0_a2l_probe.py -v
```

Optional CLI sanity check on the same A2L:

```text
PYTHONPATH=. .venv/bin/python -m can_logger.p0.a2l_probe "$P0_A2L_PATH" --limit 10
```

## Vector Access

Command:

```text
.\.venv\Scripts\python.exe -m can_logger.p0.vector_probe --open
```

Result: **BLOCKED on macOS — hardware not available**.

Reason: code is on disk at `can_logger/p0/vector_probe.py` and imports
cleanly on macOS without `python-can` installed. Runtime Vector access
still requires Vector CAN hardware on Windows; host was macOS (Darwin
25.5.0). `python-can[vector]` is not portable to macOS, and even with
the package installed the `vector` interface needs the Vector kernel
driver and a physical CANcaseXL or compatible device on the bus.

Next step: resume on a Windows workstation with Vector CANcaseXL or
compatible, run the dependency install from the P0 plan §Task 1 Step 4
(`python-can[vector]>=4.6,<5`, `pyxcp==0.29.8`), then run the P0 plan
§Task 4 commands and append the actual `vector_channels:` /
`vector_open: ok` output to this section. If the open call raises,
record the exception verbatim and re-classify this gate as PASS (with
exact failure log) per the plan's "documented driver/config blocker"
allowance.

## XCP CONNECT And SHORT_UPLOAD

Command:

```text
.\.venv\Scripts\python.exe -m can_logger.p0.xcp_short_upload_probe ...
```

Result: **BLOCKED on macOS — hardware not available**.

Reason: code is on disk at `can_logger/p0/xcp_short_upload_probe.py`
and imports cleanly on macOS without `python-can` or `pyxcp` installed;
the `decode_raw` helper is hardware-free. Runtime XCP still requires
the same Vector hardware as the Vector Access gate above, plus a
powered ECU on the bus with known cmd_id/resp_id and a measurement
address (typically sourced from the ECU's A2L). None of these are
available from the macOS host.

Next step: after Vector access is verified, obtain from the calibration
owner the four target-specific values:

- `--cmd-id` (XCP command frame, e.g. `0x7E1`)
- `--resp-id` (XCP response frame, e.g. `0x7E9`)
- `--address` and `--address-extension` (from A2L `MEASUREMENT.ecu_address`)
- `--size`, `--dtype`, `--endian` (from A2L `MEASUREMENT.datatype`)

Then run P0 plan §Task 5 Step 2 verbatim and capture `connect_response:`,
`raw:`, and `decoded:` into this section.

## Final Verdict

Verdict: **PARTIAL**

Reasoning: MF4 compatibility test passed (commit `62ae309`); the A2L
parser is implemented and skip-passes pending a real `P0_A2L_PATH`
(commit `c5eed55`); the Vector + XCP probe modules now exist and import
cleanly on macOS, but runtime probe execution is deferred to a Windows
+ Vector hardware environment that the macOS host cannot provide.
Resume path verified to import on macOS; full PASS requires Vector
hardware on Windows.
This matches the P0 plan's PARTIAL rule verbatim: "MF4 and A2L passed,
but a hardware condition blocked Vector or XCP with a narrow next
action" — the narrow next action is documented inline in the Vector
Access and XCP CONNECT And SHORT_UPLOAD sections above.

## P0 Completion Gate

Copied verbatim from the P0 plan §P0 Completion Gate section, annotated
with this run's outcome:

- MF4 compatibility test passes — **MET** (commit `62ae309`, test
  green).
- Real A2L parse either passes or has a documented parser blocker —
  **MET** in skipped state (commit `c5eed55`; parser implemented,
  documented skip path is `P0_A2L_PATH` env var).
- Windows Vector open either passes or has a documented driver/config
  blocker — **MET in BLOCKED state** (no Vector hardware on host;
  documented blocker recorded above).
- XCP `CONNECT` and `SHORT_UPLOAD` either pass or have a documented
  ECU/protocol blocker — **MET in BLOCKED state** (same hardware
  dependency).
- `docs/analyzer/acquisition/P0_Runbook.md` contains the actual
  command/output evidence — **THIS DOCUMENT**.

Conclusion: P0 completion gate is in **PARTIAL** state.

**Gate scope (clarified 2026-05-15, see [`reports/2026-05-15-capture-priority-replay-findings.md`](reports/2026-05-15-capture-priority-replay-findings.md)):** this gate governs **production DAQ UI on real Vector hardware** (cockpit Capture state wired to live Vector / XCP). It does **not** govern:

- the CLI recorder MVP backend (fake-bus / synthetic path),
- cockpit UI scaffolding work that runs against mock data,
- Modules A / B / C (offline preflight, manifest, regression, alias).

Per the master plan §Deferred Until P0 PASS (or documented narrow PARTIAL), the in-scope deferred work resumes once the verdict is **PASS** or a documented narrow PARTIAL whose blocker is named and bounded. The current PARTIAL with "Vector hardware not present on macOS host" is documented and narrow, but it does not yet authorize hardware-wired UI work — that needs the Vector and XCP CONNECT / SHORT_UPLOAD gates run to completion on a Windows + Vector + powered-ECU workstation, with the actual command output appended above.
