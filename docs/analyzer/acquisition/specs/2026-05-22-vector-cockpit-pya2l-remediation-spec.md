# Vector / Cockpit / pya2l Remediation Spec

Date: 2026-05-22
Status: Execution-ready
Source report: `docs/analyzer/acquisition/reports/2026-05-22-vector-cockpit-pya2l-incident-report.md`
Plan: `docs/analyzer/acquisition/plans/2026-05-22-vector-cockpit-pya2l-remediation-implementation.md`

## Goal

Close the two remaining production blockers from the 2026-05-22 incident:

1. Selecting an A2L from Cockpit must never terminate the PyQt process, even
   when `pya2l` crashes with a native access violation.
2. The Cockpit health strip must leave its initial grey state, report real
   Vector hardware health when transport is configured, and surface missing
   connection preconditions as operator-visible warnings instead of status-bar
   text only.

The already-fixed Vector phantom API bug remains a regression source, so this
work also adds durable import/API-surface guards.

## Non-Goals

- Do not redesign the Cockpit state machine.
- Do not implement full CAN/XCP/DAQ/REC live production health from backend
  status. This spec only replaces the HW stub with the real `vector_hw_probe`
  path and keeps the existing CAN/XCP/DAQ/REC probes.
- Do not change `MeasurementSummary` or `A2LSummary` public field names.
- Do not introduce a new IPC protocol beyond local subprocess stdout/stderr.
- Do not edit `CLAUDE.md` or `.claude/`.

## Current Failure Model

### pya2l Access Violation

`can_logger.p0.a2l_probe.load_measurement_summary()` currently imports
`pya2l` in the same process that called it. Lazy import delayed the crash until
the operator selected an A2L, but did not isolate it. In a PyQt-loaded process,
`from pya2l import DB` can terminate the process with `0xC0000005`, which
`try/except` cannot catch.

### Cockpit Grey Health Chips

`CockpitMainWindow._health_timer` is constructed in `__init__` but only starts
after `_maybe_swap_to_vector_backend()` succeeds inside
`_begin_connection_attempt()`. Missing transport, IF_DATA, or measurement pool
returns before `timer.start()`, leaving all chips in initial grey state.

`_begin_connection_attempt()` currently writes `_connection_attempt_started`
before preconditions are checked. If the timer is simply moved earlier, the
existing `_probe_hw()` stub can turn a failed vehicle connection attempt into
`demo-fake` green. Therefore timer startup, connection-attempt state, and HW
probe replacement must land together.

### Operator Feedback

When vehicle preconditions are missing and `allow_fake_backend=False`,
`_maybe_swap_to_vector_backend()` writes a status-bar message and returns
`False`. This is too quiet for the vehicle/operator workflow. Missing
transport, A2L IF_DATA, measurement pool, or unavailable Vector backend must
also show a non-blocking window-modal warning.

## Required Design

### A2L Parse Isolation

Public API stays:

```python
def load_measurement_summary(a2l_path: str, *, limit: int | None = None) -> A2LSummary:
    ...
```

Implementation changes:

- Move the current in-process parser body to
  `_load_measurement_summary_inprocess(a2l_path, *, limit=None)`.
- Keep `MeasurementSummary`, `A2LSummary`, `_address_of()`,
  `_fill_ifdata_events()`, and `_dispose_db()` pure and import-safe.
- Public `load_measurement_summary()` runs:

```text
sys.executable -m can_logger.p0._a2l_subprocess <path> [--limit N]
```

- Parent captures binary stdout, never uses `text=True`, unpickles an
  `A2LSummary`, and returns it.
- Child process imports `pya2l` only inside the in-process parse function,
  pickles the summary to stdout, and writes diagnostics to stderr on failure.
- Native crash return codes must be formatted as unsigned Windows hex; both
  `-1073741819` and `3221225477` render with `0xC0000005`.
- Timeout defaults to 30 seconds and raises a `RuntimeError` in the parent.

Only these paths may contain static `pya2l` imports:

- `can_logger/p0/a2l_probe.py`, inside `_load_measurement_summary_inprocess`
- `can_logger/p0/_a2l_subprocess.py`, only if needed for the child entrypoint

No `mf4_analyzer` module may statically import `pya2l` or `pyxcp`.

### Cockpit Health Timer

`CockpitMainWindow.__init__()` starts `_health_timer` after the UI is built and
after the health strip exists. This causes the first poll to update chips from
grey to explicit evidence states.

The initial production state should be evidence-bearing, not optimistic:

- No transport configured: HW red with error `transport not configured`
- Transport configured but Vector unavailable/off-Windows: HW red with the
  real `vector_hw_probe()` error
- Demo mode may still produce `demo-fake` HW only when
  `allow_fake_backend=True`

### Connection Attempt State

`_connection_attempt_started`, `_stream_start_ts`, `_fake_xcp_connected`,
`_fake_can_load_pct`, and related demo stream fields are written only after
the connection path is allowed to start:

- In demo mode, after fake backend is allowed.
- In vehicle mode, after Vector backend preconditions pass and backend start
  succeeds.

If `_maybe_swap_to_vector_backend()` returns `False` or `_backend.start()`
raises, connection-attempt fields are reset:

```python
self._connection_attempt_started = None
self._stream_start_ts = None
self._first_frame_ts = None
self._fake_xcp_connected = False
self._fake_rec_state = "off"
self._fake_can_load_pct = None
```

This prevents failed connection attempts from feeding fake green health.

### HW Probe Wiring

`CockpitMainWindow._probe_hw()` becomes:

- If `allow_fake_backend=True` and demo connection has started, return the
  existing `demo-fake` success snapshot.
- If no transport is configured, return `HwHealth(ok=False, error="transport not configured", ...)`.
- If transport exists, call
  `mf4_analyzer.acquisition_capture.vector_hw_probe.vector_hw_probe(self._transport_config)`.

The real probe is synchronous and may be called by the timer. The initial fix
keeps the existing polling interval. A later stage may add throttling if real
hardware evidence shows the Vector call is expensive.

### Operator-Visible Connection Warning

Add `_warn_connection_preconditions(problems: list[str])`.

Rules:

- Use `QMessageBox(self)`, `setWindowModality(Qt.WindowModal)`, store the
  object on `self._connection_warning_box`, then call `.open()`.
- Never use static `QMessageBox.warning/information/critical` for this path.
- Tests stub the wrapper instead of rendering a dialog.
- `_maybe_swap_to_vector_backend()` keeps the status-bar message and also calls
  the warning wrapper when `allow_fake_backend=False`.
- Do not spam warnings on every health timer tick. Warnings are only emitted
  from explicit connection attempts.

### Regression Guards

Add or extend tests so CI protects the incident lessons:

- Public `load_measurement_summary()` converts subprocess success, nonzero
  native-crash exit, and timeout into normal Python results/errors.
- `_load_measurement_summary_inprocess()` preserves current fake-DB behavior:
  `remove_existing=True`, repeated parse of same path, and IF_DATA enrichment.
- Importing `can_logger.p0.a2l_probe` does not import `pya2l`.
- Static import guard fails on `import pya2l`, `from pya2l`, `import pyxcp`,
  or `from pyxcp` outside the whitelist.
- Cockpit construction starts the health timer.
- Failed vehicle preconditions do not call backend start and leave
  `_connection_attempt_started is None`.
- `_probe_hw()` calls `vector_hw_probe()` when transport exists.
- Missing vehicle preconditions call the warning wrapper and do not use static
  `QMessageBox.warning`.

## Documentation And Lessons

- Update `docs/lessons-learned/codex-windows-native-import-guard.md` with the
  specific pya2l subprocess requirement.
- Add a new lesson for phantom API surface guards, because it is a mock/API
  contract issue, not a native-import issue.
- Update `docs/lessons-learned/INDEX.md` with the new phantom API lesson.

## Acceptance Criteria

- Focused A2L tests pass.
- Focused Cockpit connection/health tests pass under `QT_QPA_PLATFORM=offscreen`.
- Static native import guard passes.
- Existing Vector probe tests still pass.
- `rg -n "from pya2l|import pya2l|from pyxcp|import pyxcp" can_logger mf4_analyzer`
  returns only whitelisted subprocess/dynamic-wrapper references.
- Selecting a bad A2L produces a handled warning/error path in the parent
  process rather than a process crash.
