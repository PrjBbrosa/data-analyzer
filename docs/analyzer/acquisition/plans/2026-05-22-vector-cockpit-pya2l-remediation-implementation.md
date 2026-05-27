# Vector / Cockpit / pya2l Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or equivalent fresh-worker execution. Steps use checkbox (`- [ ]`) syntax for tracking. Workers are not alone in the codebase: do not revert others' edits; keep to the assigned write set.

**Goal:** Implement the remediation spec at `docs/analyzer/acquisition/specs/2026-05-22-vector-cockpit-pya2l-remediation-spec.md`.

**Architecture:** Three disjoint implementation slices. Task 1 isolates A2L parsing behind a subprocess and owns `can_logger/p0` plus A2L tests. Task 2 fixes Cockpit health/timer/precondition feedback and owns `main_window.py` plus acquisition UI tests. Task 3 adds lessons and static import/API-surface guards. A final review pass integrates and verifies all slices together.

**Tech Stack:** Python 3.10+, PyQt5, pytest, python dataclasses, subprocess + pickle IPC, existing `HealthAggregator` and `vector_hw_probe`.

---

## File Ownership

| Task | Owner | Write Set |
| --- | --- | --- |
| 1 | A2L worker | `can_logger/p0/a2l_probe.py`, `can_logger/p0/_a2l_subprocess.py`, `tests/test_p0_a2l_probe.py` |
| 2 | Cockpit UI worker | `mf4_analyzer/acquisition_ui/main_window.py`, `tests/acquisition_ui/test_record_backend_swap.py`, optional `tests/acquisition_ui/test_health_strip.py` |
| 3 | Guard/docs worker | `tests/test_native_import_boundaries.py` or existing import-boundary test file, `docs/lessons-learned/codex-windows-native-import-guard.md`, `docs/lessons-learned/codex-phantom-api-surface-guards.md`, `docs/lessons-learned/INDEX.md` |
| 4 | Controller/reviewer | Integration review, focused verification, small fixes only |

Use `.state/pytest-tmp` and `.state/pytest-cache` for local verification on
Windows if the default temp/cache paths are unavailable:

```powershell
$env:PYTHONPATH='.'
$env:QT_QPA_PLATFORM='offscreen'
$env:TMP="$PWD\.state\pytest-tmp"
$env:TEMP="$PWD\.state\pytest-tmp"
.\.venv\Scripts\python.exe -m pytest ... --basetemp .state\pytest-tmp -o cache_dir=.state\pytest-cache
```

---

## Task 1: A2L Subprocess Isolation

**Files:**

- Modify: `can_logger/p0/a2l_probe.py`
- Create: `can_logger/p0/_a2l_subprocess.py`
- Modify: `tests/test_p0_a2l_probe.py`

### Step 1: Write failing wrapper tests

Add tests like these to `tests/test_p0_a2l_probe.py`:

```python
import pickle
import subprocess
import sys

from can_logger.p0.a2l_probe import A2LSummary, MeasurementSummary


def _summary(path: str) -> A2LSummary:
    return A2LSummary(
        path=path,
        total_measurements=1,
        measurements=[
            MeasurementSummary(
                name="VehicleSpeed",
                address=0x1234,
                datatype="UWORD",
                unit="km/h",
                conversion="SpeedConv",
            )
        ],
    )


def test_load_measurement_summary_unpickles_subprocess_result(monkeypatch, tmp_path):
    a2l = tmp_path / "ok.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")
    expected = _summary(str(a2l))
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, pickle.dumps(expected), b"")

    monkeypatch.setattr(a2l_probe_module.subprocess, "run", fake_run)

    result = a2l_probe_module.load_measurement_summary(str(a2l), limit=None)

    assert result == expected
    cmd, kwargs = calls[0]
    assert cmd[:3] == [sys.executable, "-m", "can_logger.p0._a2l_subprocess"]
    assert str(a2l) in cmd
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == 30
    assert "text" not in kwargs


def test_load_measurement_summary_subprocess_crash_becomes_runtime_error(monkeypatch, tmp_path):
    a2l = tmp_path / "crash.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            -1073741819,
            b"",
            b"Windows fatal exception: access violation",
        )

    monkeypatch.setattr(a2l_probe_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="0xC0000005.*access violation"):
        a2l_probe_module.load_measurement_summary(str(a2l), limit=1)


def test_load_measurement_summary_timeout_becomes_runtime_error(monkeypatch, tmp_path):
    a2l = tmp_path / "slow.a2l"
    a2l.write_text("/begin PROJECT demo demo /end PROJECT", encoding="latin-1")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=30)

    monkeypatch.setattr(a2l_probe_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out after 30s"):
        a2l_probe_module.load_measurement_summary(str(a2l), limit=1)
```

Run:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\test_p0_a2l_probe.py -q --basetemp .state\pytest-tmp -o cache_dir=.state\pytest-cache
```

Expected: new tests fail because the wrapper still parses in-process.

### Step 2: Move fake-DB tests to the in-process helper

Change the existing fake-DB tests so they call:

```python
summary = a2l_probe_module._load_measurement_summary_inprocess(str(a2l), limit=1)
```

Expected red before implementation: helper does not exist.

### Step 3: Implement the parent wrapper

In `can_logger/p0/a2l_probe.py`:

- Add imports:

```python
import pickle
import subprocess
import sys
```

- Add helpers:

```python
DEFAULT_A2L_PARSE_TIMEOUT_S = 30


def _format_exit_code(returncode: int) -> str:
    unsigned = returncode & 0xFFFFFFFF
    if returncode < 0 or unsigned > 0x7FFFFFFF:
        return f"{returncode} (0x{unsigned:08X})"
    return str(returncode)


def _compact_process_output(stdout: bytes, stderr: bytes) -> str:
    raw = stderr or stdout or b""
    text = raw.decode("utf-8", errors="replace").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    detail = lines[0] if lines else "no output"
    return detail[:297] + "..." if len(detail) > 300 else detail
```

- Rename the current public parse body to:

```python
def _load_measurement_summary_inprocess(
    a2l_path: str, *, limit: int | None = None
) -> A2LSummary:
    ...
```

- Replace public `load_measurement_summary()` with the subprocess wrapper:

```python
def load_measurement_summary(
    a2l_path: str, *, limit: int | None = None
) -> A2LSummary:
    path = Path(a2l_path)
    if not path.exists():
        raise FileNotFoundError(path)

    cmd = [
        sys.executable,
        "-m",
        "can_logger.p0._a2l_subprocess",
        str(path),
    ]
    if limit is not None:
        cmd.extend(["--limit", str(limit)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=DEFAULT_A2L_PARSE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"A2L parse subprocess timed out after {exc.timeout:g}s: {path}"
        ) from exc

    if result.returncode != 0:
        detail = _compact_process_output(result.stdout, result.stderr)
        raise RuntimeError(
            "A2L parse subprocess failed "
            f"(exit={_format_exit_code(result.returncode)}): {detail}"
        )

    try:
        return pickle.loads(result.stdout)
    except Exception as exc:  # noqa: BLE001
        detail = _compact_process_output(result.stdout, result.stderr)
        raise RuntimeError(f"A2L parse subprocess returned invalid data: {detail}") from exc
```

### Step 4: Add the child entrypoint

Create `can_logger/p0/_a2l_subprocess.py`:

```python
"""Subprocess entrypoint for crash-isolated pya2l parsing."""

from __future__ import annotations

import argparse
import pickle
import sys

from can_logger.p0.a2l_probe import _load_measurement_summary_inprocess


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse A2L in an isolated subprocess.")
    parser.add_argument("a2l_path")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    try:
        summary = _load_measurement_summary_inprocess(args.a2l_path, limit=args.limit)
    except Exception as exc:  # noqa: BLE001
        print(f"A2L parse failed: {exc}", file=sys.stderr)
        return 1

    sys.stdout.buffer.write(pickle.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Step 5: Verify Task 1

Run:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\test_p0_a2l_probe.py -q --basetemp .state\pytest-tmp -o cache_dir=.state\pytest-cache
```

Expected: pass, with the real-A2L test skipped unless `P0_A2L_PATH` is set.

---

## Task 2: Cockpit Health Timer, Real HW Probe, And Warnings

**Files:**

- Modify: `mf4_analyzer/acquisition_ui/main_window.py`
- Modify: `tests/acquisition_ui/test_record_backend_swap.py`
- Optional modify: `tests/acquisition_ui/test_health_strip.py`

### Step 1: Write failing timer and failed-precondition tests

Add tests to `tests/acquisition_ui/test_record_backend_swap.py`:

```python
def test_health_timer_starts_on_window_init(qapp):
    window = CockpitMainWindow()
    try:
        assert window._health_timer.isActive()
    finally:
        window.deleteLater()


def test_failed_vehicle_preconditions_do_not_mark_connection_started(qapp):
    class _SpyFake(FakeRecorderBackend):
        def __init__(self) -> None:
            super().__init__()
            self.start_called = 0

        def start(self, selected):  # type: ignore[override]
            self.start_called += 1
            return super().start(selected)

    backend = _SpyFake()
    window = CockpitMainWindow(backend=backend)
    try:
        warnings = []
        window._warn_connection_preconditions = lambda problems: warnings.extend(problems)  # type: ignore[method-assign]
        window._ifdata_xcp = _stub_ifdata()
        window._left_pane.set_pool(_stub_pool(), a2l_has_daq_events=True)

        window._begin_connection_attempt()

        assert backend.start_called == 0
        assert window._connection_attempt_started is None
        assert window._stream_start_ts is None
        assert window._fake_xcp_connected is False
        assert window._fake_can_load_pct is None
        assert any("Transport" in item for item in warnings)
    finally:
        window.deleteLater()
```

Expected: fail because timer does not start in `__init__`, connection state is
written before preconditions, and warning wrapper does not exist.

### Step 2: Write failing real HW probe test

Add:

```python
def test_probe_hw_uses_vector_hw_probe_when_transport_configured(qapp, monkeypatch):
    from mf4_analyzer.acquisition_capture.health import HwHealth

    calls = []

    def fake_probe(transport):
        calls.append(transport)
        return HwHealth(
            ok=True,
            driver_version="26.10.2",
            channel_count=7,
            last_probe_ts=123.0,
            error=None,
        )

    monkeypatch.setattr(
        "mf4_analyzer.acquisition_capture.vector_hw_probe.vector_hw_probe",
        fake_probe,
    )

    window = CockpitMainWindow()
    try:
        transport = TransportConfig(app_name="Python", channel=0)
        window.set_transport(transport)

        result = window._probe_hw()

        assert result.ok is True
        assert result.driver_version == "26.10.2"
        assert calls == [transport]
    finally:
        window.deleteLater()
```

Expected: fail because `_probe_hw()` still returns `demo-fake`/non-Windows
stub instead of calling `vector_hw_probe`.

### Step 3: Implement connection-state reset helper

In `CockpitMainWindow`, add:

```python
def _reset_connection_attempt_state(self) -> None:
    self._connection_attempt_started = None
    self._stream_start_ts = None
    self._first_frame_ts = None
    self._fake_xcp_connected = False
    self._fake_rec_state = "off"
    self._fake_can_load_pct = None
```

Use it on precondition failure and backend-start failure.

### Step 4: Start health timer in `__init__`

After `_hydrate_from_config_path()` in `__init__`, start and poll once:

```python
if not self._health_timer.isActive():
    self._health_timer.start()
self._poll_health()
```

If a test-injected aggregator cannot poll during construction, prefer starting
the timer without the immediate poll. The acceptance requirement is that the
timer is active and the first timeout updates the strip.

### Step 5: Move connection attempt state after successful gate

In `_begin_connection_attempt()`:

- Keep selection logic at the top.
- Call `_maybe_swap_to_vector_backend()` before writing fake connection fields.
- On `False`, call `_reset_connection_attempt_state()` and return.
- Call `_backend.start(selection)`.
- Only after start succeeds set `_connection_attempt_started`,
  `_stream_start_ts`, `_first_frame_ts`, `_fake_xcp_connected`,
  `_fake_rec_state`, and `_fake_can_load_pct`.
- Keep live timer and center-card seeding after successful start.

### Step 6: Replace `_probe_hw()`

Implement:

```python
def _probe_hw(self) -> HwHealth:
    if self._allow_fake_backend and (
        self._connection_attempt_started is not None or self._fake_xcp_connected
    ):
        return HwHealth(
            ok=True,
            driver_version="demo-fake",
            channel_count=1,
            last_probe_ts=time.monotonic(),
            error=None,
        )
    if self._transport_config is None:
        return HwHealth(
            ok=False,
            driver_version=None,
            channel_count=0,
            last_probe_ts=time.monotonic(),
            error="transport not configured",
        )
    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

    return vector_hw_probe(self._transport_config)
```

### Step 7: Add warning wrapper and call it from vehicle failures

Add:

```python
def _warn_connection_preconditions(self, problems: list[str]) -> None:
    box = QMessageBox(self)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("连接 ECU 前置条件")
    box.setText("无法开始真实 ECU 连接：\n\n" + "\n".join(f"• {p}" for p in problems))
    box.setWindowModality(Qt.WindowModal)
    self._connection_warning_box = box
    box.open()
```

In `_maybe_swap_to_vector_backend()`:

- For missing preconditions in production mode, call
  `_warn_connection_preconditions(missing)`.
- For Vector unavailable/construction failure in production mode, call it with
  the same user-visible reason shown in the status bar.

Do not call this wrapper in demo mode.

### Step 8: Verify Task 2

Run:

```powershell
$env:PYTHONPATH='.'
$env:QT_QPA_PLATFORM='offscreen'
$env:TMP="$PWD\.state\pytest-tmp"
$env:TEMP="$PWD\.state\pytest-tmp"
.\.venv\Scripts\python.exe -m pytest tests\acquisition_ui\test_record_backend_swap.py tests\acquisition_ui\test_pick_a2l_warnings.py -q --basetemp .state\pytest-tmp -o cache_dir=.state\pytest-cache
```

Expected: pass. No test should hang on a static `QMessageBox.warning`.

---

## Task 3: Lessons And Native/API Boundary Guards

**Files:**

- Create: `tests/test_native_import_boundaries.py`
- Modify: `docs/lessons-learned/codex-windows-native-import-guard.md`
- Create: `docs/lessons-learned/codex-phantom-api-surface-guards.md`
- Modify: `docs/lessons-learned/INDEX.md`

### Step 1: Add static import-boundary test

Create `tests/test_native_import_boundaries.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (ROOT / "can_logger", ROOT / "mf4_analyzer")
FORBIDDEN = {"pya2l", "pyxcp"}
PYA2L_ALLOWED = {
    (Path("can_logger/p0/a2l_probe.py"), "_load_measurement_summary_inprocess"),
}


def _function_stack(tree: ast.AST) -> dict[ast.AST, tuple[str, ...]]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    stacks: dict[ast.AST, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        names = []
        cur = parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(cur.name)
            cur = parents.get(cur)
        stacks[node] = tuple(reversed(names))
    return stacks


def test_native_dependencies_have_no_unapproved_static_imports():
    violations = []
    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            rel = path.relative_to(ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
            stacks = _function_stack(tree)
            for node in ast.walk(tree):
                module = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name.split(".")[0]
                        if module in FORBIDDEN:
                            func = stacks[node][-1] if stacks[node] else None
                            if (rel, func) not in PYA2L_ALLOWED:
                                violations.append(f"{rel}:{node.lineno} import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module.split(".")[0]
                    if module in FORBIDDEN:
                        func = stacks[node][-1] if stacks[node] else None
                        if (rel, func) not in PYA2L_ALLOWED:
                            violations.append(f"{rel}:{node.lineno} from {node.module}")

    assert not violations, "\n".join(violations)
```

Run:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\test_native_import_boundaries.py -q --basetemp .state\pytest-tmp -o cache_dir=.state\pytest-cache
```

Expected before Task 1 implementation: fail on current `a2l_probe.py` static
imports if they are not yet moved into the whitelisted helper.

### Step 2: Update native-import lesson

Append a short note to `docs/lessons-learned/codex-windows-native-import-guard.md`:

```markdown
2026-05-22 update: `pya2l` is in the same crash class as `pyxcp` when imported
inside an already-initialized PyQt process. Lazy import is not enough; public
Cockpit/UI paths must call a subprocess wrapper, and only the child/in-process
parse helper may import `pya2l`.
```

Add `tests/test_native_import_boundaries.py` to the lesson checks/tests list.

### Step 3: Add phantom API lesson

Create `docs/lessons-learned/codex-phantom-api-surface-guards.md`:

```markdown
---
id: codex-phantom-api-surface-guards
status: active
owners: [codex]
keywords: [phantom-api, MagicMock, vector, python-can, api-surface, acquisition]
paths:
  - can_logger/p0/
  - mf4_analyzer/acquisition_capture/vector_hw_probe.py
  - tests/test_vector_hw_probe.py
  - tests/test_vector_probe_stages.py
checks:
  - rg -n "MagicMock\\(\\)" tests/test_vector_hw_probe.py tests/test_vector_probe_stages.py
tests:
  - PYTHONPATH=. .venv/Scripts/python.exe -m pytest tests/test_vector_probe_stages.py tests/test_vector_hw_probe.py -q
---

# Phantom API Surface Guards

Trigger: Mocking external library surfaces for acquisition probes, especially
Vector/python-can, `pyxcp`, or other optional native dependencies.

Past failure: Tests used unrestricted `MagicMock` module surfaces and patched
entire probe bodies, so production code called nonexistent python-can APIs
(`canlib.get_application_config`, `canlib.get_channel_count`) while CI stayed
green.

Rule: Do not fake an external module with unrestricted `MagicMock` when the
production code is proving API compatibility. Use structured fakes,
`create_autospec()` from the real module when available, or explicit
regression assertions that the production code calls the documented API.

Verification: Run the Vector probe tests and grep for unrestricted module-level
`MagicMock()` fakes in those tests before claiming the probe surface is guarded.
```

### Step 4: Update lesson index

Add a row to `docs/lessons-learned/INDEX.md`:

```markdown
| [Phantom API Surface Guards](codex-phantom-api-surface-guards.md) | Mocking external library surfaces for acquisition probes or optional native dependencies. | Structured fakes/autospec; focused Vector probe tests |
```

### Step 5: Verify Task 3

Run:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\test_native_import_boundaries.py tests\test_vector_probe_stages.py tests\test_vector_hw_probe.py -q --basetemp .state\pytest-tmp -o cache_dir=.state\pytest-cache
```

Expected: pass after Task 1 moves `pya2l` import into the whitelisted helper.

---

## Task 4: Integration Verification And Code Review

**Files:** no planned ownership; small fixes only after review findings.

### Step 1: Run focused integration suite

```powershell
$env:PYTHONPATH='.'
$env:QT_QPA_PLATFORM='offscreen'
$env:TMP="$PWD\.state\pytest-tmp"
$env:TEMP="$PWD\.state\pytest-tmp"
.\.venv\Scripts\python.exe -m pytest tests\test_p0_a2l_probe.py tests\test_native_import_boundaries.py tests\acquisition_ui\test_record_backend_swap.py tests\acquisition_ui\test_pick_a2l_warnings.py tests\test_vector_probe_stages.py tests\test_vector_hw_probe.py tests\test_vector_xcp_backend.py -q --basetemp .state\pytest-tmp -o cache_dir=.state\pytest-cache
```

Expected: all selected tests pass, except env-gated real A2L tests remain
skipped when `P0_A2L_PATH` is unset.

### Step 2: Run static grep acceptance

```powershell
rg -n "from pya2l|import pya2l|from pyxcp|import pyxcp" can_logger mf4_analyzer
```

Expected: only whitelisted child/in-process `pya2l` references and dynamic
string/import-wrapper `pyxcp` references.

### Step 3: Systematic code review checklist

Review the final diff for:

- Public A2L API unchanged.
- Child process never calls public `load_measurement_summary()`.
- Parent subprocess wrapper never uses `text=True`.
- Timeout/nonzero/native-crash details are readable.
- Cockpit timer starts without causing modal hangs in tests.
- Failed vehicle preconditions cannot leave `_connection_attempt_started`.
- Demo fake green is only possible when `allow_fake_backend=True`.
- `_warn_connection_preconditions()` uses `.open()` and stores a reference.
- Lessons index points to the new phantom API lesson.

Fix Critical and Important findings before final verification.
