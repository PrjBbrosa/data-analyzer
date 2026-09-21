"""Focused self-tests for the outer pytest gate watchdog.

These tests deliberately exercise a throwaway pytest project.  They never run
the repository suite through the watchdog.

Hang-sensitive cases use an outer deadline that is independent of the runner
under test.  The runner's own soft/hard timers are not the only bound.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_test_gate import (
    PREFLIGHT_LIMITS,
    OwnedProcessTree,
    PhaseCommand,
    _find_pytest_in_same_checkout,
    _list_owned_processes,
    _terminate_owned_process_group,
    _windows_process_tree_pids,
    compose_gate_status,
    capture_repo_snapshot,
    run_test_gate,
    windows_taskkill_command,
    _write_json,
)


GATE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_test_gate.py"


def _git(project: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(project), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _project(tmp_path: Path, source: str) -> Path:
    project = tmp_path / "tiny-pytest-project"
    project.mkdir()
    (project / "test_tiny.py").write_text(source, encoding="utf-8")
    (project / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "test@example.invalid")
    _git(project, "config", "user.name", "Test Gate")
    _git(project, "add", "test_tiny.py", ".gitignore")
    _git(project, "commit", "-qm", "initial")
    return project


def _run_tiny_gate(
    project: Path,
    *,
    soft_seconds: float = 2.0,
    hard_seconds: float = 4.0,
    output_reader_join_seconds: float = 0.5,
    phases: list[PhaseCommand] | None = None,
    continue_after_unverified: bool = False,
):
    return run_test_gate(
        phases
        or [
            PhaseCommand(
                name="tiny",
                command=(sys.executable, "-m", "pytest", "-q"),
            )
        ],
        cwd=project,
        repo_root=project,
        run_root=project / "gate-artifacts",
        soft_timeout_seconds=soft_seconds,
        hard_timeout_seconds=hard_seconds,
        heartbeat_seconds=0.05,
        terminate_grace_seconds=0.25,
        output_reader_join_seconds=output_reader_join_seconds,
        continue_after_unverified=continue_after_unverified,
    )


def _record(result) -> dict:
    return json.loads(result.record_path.read_text(encoding="utf-8"))


def _run_with_outer_deadline(func, outer_seconds: float):
    """Bound the test itself; do not rely on the runner's watchdog alone."""

    box: dict = {}
    done = threading.Event()

    def worker() -> None:
        try:
            box["value"] = func()
        except BaseException as exc:  # noqa: BLE001 — surface any runner error
            box["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=worker, name="test-gate-outer-deadline", daemon=True)
    thread.start()
    if not done.wait(outer_seconds):
        pytest.fail(
            f"runner under test did not return within outer deadline {outer_seconds}s"
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


def _latest_record(run_root: Path) -> dict:
    records = sorted(run_root.glob("*/run.json"))
    assert records, f"no run.json under {run_root}"
    return json.loads(records[-1].read_text(encoding="utf-8"))


def _phase_events(phase: dict) -> list[dict]:
    path = Path(phase["artifacts"]["events"])
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


_STILL_ACTIVE = 259


def _process_is_live(pid: int) -> bool:
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        process_query_limited_information = 0x1000
        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return int(exit_code.value) == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    completed = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    state = completed.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _read_pid_file(path: Path, timeout: float = 3.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return int(text)
        time.sleep(0.02)
    raise AssertionError(f"missing pid file {path}")


def _wait_until_dead(pid: int, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while _process_is_live(pid) and time.monotonic() < deadline:
        time.sleep(0.05)


def _reap_if_live(pid: int) -> None:
    if not _process_is_live(pid):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def test_gate_records_clean_snapshot_and_pytest_phase_events(tmp_path):
    project = _project(tmp_path, "def test_ok():\n    assert True\n")

    result = _run_tiny_gate(project)

    assert result.status == "PASS"
    record = _record(result)
    assert record["status"] == "PASS"
    assert record["pytest_status"] == "PASS"
    assert record["snapshot_before"]["head"]
    assert record["snapshot_before"]["dirty_fingerprint"] == record["snapshot_after"][
        "dirty_fingerprint"
    ]
    phase = record["phases"][0]
    assert phase["status"] == "PASS"
    assert phase["pid"] == phase["owned_process_group"]
    assert phase["current_node"].endswith("test_tiny.py::test_ok")
    assert phase["current_phase"] == "teardown"
    events = _phase_events(phase)
    assert any(event["phase"] == "collection" and event["state"] == "start" for event in events)
    assert any(event["phase"] == "collection" and event["state"] == "finish" for event in events)
    assert any(event["phase"] == "setup" and event["state"] == "start" for event in events)
    assert any(event["phase"] == "call" and event["state"] == "start" for event in events)
    assert any(event["phase"] == "call" and event["state"] == "complete" for event in events)
    assert any(event["phase"] == "teardown" and event["state"] == "start" for event in events)
    assert any(
        event["phase"] == "teardown" and event["state"] == "complete"
        for event in events
    )
    assert Path(phase["artifacts"]["output"]).exists()


def test_gate_preserves_assertion_failure_as_fail_not_unverified(tmp_path):
    project = _project(tmp_path, "def test_failure():\n    assert False, 'expected failure'\n")

    result = _run_tiny_gate(project)

    assert result.status == "FAIL"
    record = _record(result)
    assert record["pytest_status"] == "FAIL"
    phase = record["phases"][0]
    assert phase["status"] == "FAIL"
    assert phase["exit_code"] == 1
    assert phase["hard_deadline_exceeded"] is False
    assert "expected failure" in Path(phase["artifacts"]["output"]).read_text(
        encoding="utf-8"
    )


def test_gate_hard_timeout_is_unverified_and_keeps_diagnostics(tmp_path):
    project = _project(
        tmp_path,
        "import time\n\ndef test_sleep_forever():\n    time.sleep(60)\n",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(project, soft_seconds=0.15, hard_seconds=0.75),
        8.0,
    )

    assert result.status == "UNVERIFIED"
    phase = _record(result)["phases"][0]
    assert phase["status"] == "UNVERIFIED"
    assert phase["soft_deadline_exceeded"] is True
    assert phase["hard_deadline_exceeded"] is True
    assert Path(phase["artifacts"]["hard_diagnostic"]).exists()
    assert phase["exit_code"] is not None


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group assertion")
def test_gate_timeout_kills_only_its_own_child_process_group(tmp_path):
    project = _project(
        tmp_path,
        """import pathlib
import subprocess
import sys
import time


def test_spawns_child_then_blocks():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    pathlib.Path("child.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(60)
""",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(project, soft_seconds=0.15, hard_seconds=1.0),
        8.0,
    )

    assert result.status == "UNVERIFIED"
    child_pid = _read_pid_file(project / "child.pid")
    _wait_until_dead(child_pid)
    try:
        assert not _process_is_live(child_pid), "watchdog left its test child alive"
    finally:
        _reap_if_live(child_pid)


def test_parent_exit_does_not_leave_owned_child_running(tmp_path):
    project = _project(
        tmp_path,
        """import pathlib
import subprocess
import sys


def test_parent_exits_child_keeps_running():
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGHUP, signal.SIG_IGN); time.sleep(60)"
            if __import__("os").name != "nt"
            else "import time; time.sleep(60)",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pathlib.Path("child.pid").write_text(str(child.pid), encoding="utf-8")
""",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(project, soft_seconds=2.0, hard_seconds=4.0),
        8.0,
    )
    child_pid = _read_pid_file(project / "child.pid")
    try:
        record = _record(result)
        phase = record["phases"][0]
        assert result.status == "UNVERIFIED"
        assert phase["status"] == "UNVERIFIED"
        assert record["pytest_status"] == "UNVERIFIED"
        _wait_until_dead(child_pid)
        assert not _process_is_live(child_pid)
        leftovers = phase.get("leftover_processes") or []
        assert leftovers == [] or not any(int(item["pid"]) == child_pid for item in leftovers)
    finally:
        _reap_if_live(child_pid)


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGTERM ignore assertion")
def test_parent_term_child_ignores_term_is_still_reaped(tmp_path):
    project = _project(
        tmp_path,
        """import pathlib
import subprocess
import sys
import time


def test_parent_handles_term_child_ignores():
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGHUP, signal.SIG_IGN); signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pathlib.Path("child.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(60)
""",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(project, soft_seconds=0.2, hard_seconds=1.0),
        8.0,
    )
    child_pid = _read_pid_file(project / "child.pid")
    try:
        assert result.status == "UNVERIFIED"
        _wait_until_dead(child_pid)
        assert not _process_is_live(child_pid)
        actions = " ".join(_record(result)["phases"][0].get("termination_actions") or [])
        assert "SIGKILL" in actions
    finally:
        _reap_if_live(child_pid)


def test_descendant_holding_stdout_does_not_block_runner_exit(tmp_path):
    project = _project(
        tmp_path,
        """import pathlib
import subprocess
import sys


def test_descendant_holds_stdout():
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, sys, time; signal.signal(signal.SIGHUP, signal.SIG_IGN) if hasattr(signal, 'SIGHUP') else None; sys.stdout.write('held\\\\n'); sys.stdout.flush(); time.sleep(60)",
        ]
    )
    pathlib.Path("child.pid").write_text(str(child.pid), encoding="utf-8")
""",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(
            project,
            soft_seconds=2.0,
            hard_seconds=4.0,
            output_reader_join_seconds=0.4,
        ),
        8.0,
    )
    child_pid = _read_pid_file(project / "child.pid")
    try:
        record = _record(result)
        phase = record["phases"][0]
        assert result.status == "UNVERIFIED"
        assert phase["status"] == "UNVERIFIED"
        _wait_until_dead(child_pid)
        assert not _process_is_live(child_pid)
    finally:
        _reap_if_live(child_pid)


def test_cpu_loop_is_unverified_and_bounded(tmp_path):
    project = _project(
        tmp_path,
        "def test_cpu_loop():\n    while True:\n        pass\n",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(project, soft_seconds=0.15, hard_seconds=0.75),
        8.0,
    )

    assert result.status == "UNVERIFIED"
    phase = _record(result)["phases"][0]
    assert phase["hard_deadline_exceeded"] is True
    assert phase["termination_actions"]


def test_teardown_hang_is_unverified_and_records_teardown_start(tmp_path):
    project = _project(
        tmp_path,
        """import time

import pytest


@pytest.fixture
def hang_teardown():
    yield
    time.sleep(60)


def test_body_passes(hang_teardown):
    assert True
""",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(project, soft_seconds=0.2, hard_seconds=1.0),
        8.0,
    )
    record = _record(result)
    phase = record["phases"][0]
    events = _phase_events(phase)
    assert result.status == "UNVERIFIED"
    assert any(
        event["phase"] == "call" and event["state"] == "complete" and event.get("outcome") == "passed"
        for event in events
    )
    assert any(event["phase"] == "teardown" and event["state"] == "start" for event in events)
    assert phase["current_phase"] == "teardown"


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGINT to the gate coordinator")
def test_user_interrupt_stops_owned_tree_and_is_unverified(tmp_path):
    project = _project(
        tmp_path,
        """import pathlib
import subprocess
import sys
import time


def test_sleep_and_child():
    child = subprocess.Popen(
        [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGHUP, signal.SIG_IGN); time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pathlib.Path("child.pid").write_text(str(child.pid), encoding="utf-8")
    time.sleep(60)
""",
    )
    artifacts = project / "gate-artifacts"
    cmd = [
        sys.executable,
        str(GATE_SCRIPT),
        "--cwd",
        str(project),
        "--repo-root",
        str(project),
        "--run-root",
        str(artifacts),
        "--soft-timeout-seconds",
        "8",
        "--hard-timeout-seconds",
        "12",
        "--heartbeat-seconds",
        "0.05",
        "--terminate-grace-seconds",
        "0.25",
        "--output-reader-join-seconds",
        "0.4",
        "--phase",
        f"tiny={shlex.quote(sys.executable)} -m pytest -q",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    child_pid = None
    try:
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and not (project / "child.pid").exists():
            if proc.poll() is not None:
                stdout, _ = proc.communicate(timeout=1)
                pytest.fail(
                    "runner exited before the owned child started: "
                    f"code={proc.returncode}\n{stdout}"
                )
            time.sleep(0.05)
        child_pid = _read_pid_file(project / "child.pid")
        proc.send_signal(signal.SIGINT)
        try:
            proc.communicate(timeout=8.0)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            pytest.fail("runner did not exit after SIGINT within outer deadline 8.0s")
        record = _latest_record(artifacts)
        assert record["status"] == "UNVERIFIED"
        assert record["phases"][0]["interrupted"] is True
        _wait_until_dead(child_pid)
        assert not _process_is_live(child_pid)
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if child_pid is not None:
            _reap_if_live(child_pid)


@pytest.mark.skipif(os.name == "nt", reason="POSIX unrelated session sentinel")
def test_timeout_does_not_kill_unrelated_session(tmp_path):
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    project = _project(
        tmp_path,
        "import time\n\ndef test_sleep_forever():\n    time.sleep(60)\n",
    )
    try:
        result = _run_with_outer_deadline(
            lambda: _run_tiny_gate(project, soft_seconds=0.15, hard_seconds=0.75),
            8.0,
        )
        assert result.status == "UNVERIFIED"
        assert _process_is_live(sentinel.pid)
    finally:
        _reap_if_live(sentinel.pid)


@pytest.mark.skipif(os.name == "nt", reason="POSIX pgid membership after parent exit")
def test_terminate_reaps_group_after_parent_exits():
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess, sys\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],"
            " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
            "print(child.pid, flush=True)\n",
        ],
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert parent.stdout is not None
    child_pid = int(parent.stdout.readline())
    parent.wait(timeout=5)
    assert parent.returncode == 0
    assert _process_is_live(child_pid)

    class _Handle:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def poll(self) -> int:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    try:
        actions, leftover = _terminate_owned_process_group(
            _Handle(parent.pid),
            process_group=parent.pid,
            grace_seconds=0.4,
        )
        _wait_until_dead(child_pid)
        assert not _process_is_live(child_pid)
        assert leftover == []
        assert actions
    finally:
        _reap_if_live(child_pid)


def test_windows_cleanup_commands_use_pid_tree_not_image_name():
    command = windows_taskkill_command(4242, force=True)
    assert command[0] == "taskkill"
    assert command[1:3] == ["/PID", "4242"]
    assert "/T" in command
    assert "/F" in command
    assert "/IM" not in command
    joined = " ".join(command).lower()
    assert "pytest" not in joined
    assert "python.exe" not in joined


class _FakeToolhelpKernel32:
    """Deterministic CreateToolhelp32Snapshot stand-in. Not a native Windows gate."""

    def __init__(
        self,
        rows: list[tuple[int, int]] | None = None,
        *,
        snapshot_failed: bool = False,
    ) -> None:
        self.rows = list(rows or [])
        self.snapshot_failed = snapshot_failed
        self._index = 0
        self.create_calls = 0

    def CreateToolhelp32Snapshot(self, flags, pid):
        self.create_calls += 1
        if self.snapshot_failed:
            return wintypes.HANDLE(-1).value
        return 1

    def Process32First(self, snapshot, entry_ref):
        self._index = 0
        return self._write_current(entry_ref)

    def Process32Next(self, snapshot, entry_ref):
        return self._write_current(entry_ref)

    def CloseHandle(self, handle):
        return True

    def _write_current(self, entry_ref) -> int:
        if self._index >= len(self.rows):
            return 0
        pid, ppid = self.rows[self._index]
        self._index += 1
        entry = getattr(entry_ref, "_obj", None)
        if entry is None:
            entry = getattr(entry_ref, "contents", None)
        if entry is not None:
            entry.th32ProcessID = pid
            entry.th32ParentProcessID = ppid
        return 1


class _FakeWindowsJob:
    def __init__(
        self,
        pids: list[int] | None = None,
        *,
        handle: object | None = object(),
        query_error: str | None = None,
    ) -> None:
        self._pids = list(pids or [])
        self.handle = handle
        self.error = query_error
        self._query_error = query_error

    def pids(self) -> list[int]:
        if self._query_error:
            raise OSError(self._query_error)
        return list(self._pids)


def _install_windows_toolhelp(
    monkeypatch,
    rows: list[tuple[int, int]] | None = None,
    *,
    snapshot_failed: bool = False,
) -> _FakeToolhelpKernel32:
    monkeypatch.setattr(os, "name", "nt")
    fake = _FakeToolhelpKernel32(rows=rows, snapshot_failed=snapshot_failed)

    def _kernel32_windll(name, *args, **kwargs):
        if name != "kernel32":
            raise OSError(f"unexpected WinDLL({name!r})")
        return fake

    # macOS ctypes has no WinDLL. raising=False injects the missing
    # attribute and lets monkeypatch delete it on teardown.
    monkeypatch.setattr(ctypes, "WinDLL", _kernel32_windll, raising=False)
    return fake


def _exited_handle(pid: int):
    return SimpleNamespace(
        pid=pid,
        poll=lambda: 0,
        wait=lambda timeout=None: 0,
        kill=lambda: None,
    )


def test_windows_terminate_path_uses_owned_pid_after_parent_exit(monkeypatch):
    monkeypatch.setattr(os, "name", "nt")
    _install_windows_toolhelp(monkeypatch, rows=[])
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr("scripts.run_test_gate.subprocess.run", fake_run)

    class _Handle:
        pid = 4242

        def poll(self) -> int:
            return 0

        def wait(self, timeout=None) -> int:
            return 0

        def kill(self) -> None:
            return None

    actions, leftover = _terminate_owned_process_group(
        _Handle(),
        process_group=None,
        grace_seconds=0.05,
    )
    assert leftover == []
    assert any(cmd[:3] == ["taskkill", "/PID", "4242"] and "/T" in cmd for cmd in calls)
    assert not any("/IM" in cmd for cmd in calls)
    assert "taskkill" in " ".join(actions).lower() or calls


def test_windows_api_standin_empty_job_and_empty_snapshot_are_not_live(monkeypatch):
    _install_windows_toolhelp(monkeypatch, rows=[])
    owned = OwnedProcessTree(
        kind="windows-job",
        root_pid=4242,
        process_group=None,
        job=_FakeWindowsJob([], handle=object()),
    )
    assert _windows_process_tree_pids(4242) == []
    assert _list_owned_processes(owned, _exited_handle(4242)) == []


def test_windows_api_standin_root_gone_still_finds_owned_children(monkeypatch):
    _install_windows_toolhelp(
        monkeypatch,
        rows=[(5101, 5000), (5102, 5101), (5999, 1)],
    )
    owned = OwnedProcessTree(
        kind="windows-process-tree",
        root_pid=5000,
        process_group=None,
        job=_FakeWindowsJob([], handle=object()),
    )
    assert _windows_process_tree_pids(5000) == [5101, 5102]
    live = _list_owned_processes(owned, _exited_handle(5000))
    assert [item["pid"] for item in live] == [5101, 5102]
    assert 5000 not in [item["pid"] for item in live]


def test_windows_api_standin_live_root_is_listed(monkeypatch):
    _install_windows_toolhelp(monkeypatch, rows=[(7001, 1), (7002, 7001)])
    owned = OwnedProcessTree(
        kind="windows-process-tree",
        root_pid=7001,
        process_group=None,
        job=_FakeWindowsJob([], handle=None),
    )
    assert _windows_process_tree_pids(7001) == [7001, 7002]
    live = _list_owned_processes(owned, SimpleNamespace(pid=7001, poll=lambda: None))
    assert [item["pid"] for item in live] == [7001, 7002]


def test_windows_api_standin_job_members_win_over_empty_tree(monkeypatch):
    _install_windows_toolhelp(monkeypatch, rows=[])
    owned = OwnedProcessTree(
        kind="windows-job",
        root_pid=8001,
        process_group=None,
        job=_FakeWindowsJob([8001, 8002], handle=object()),
    )
    live = _list_owned_processes(owned, SimpleNamespace(pid=8001, poll=lambda: None))
    assert [item["pid"] for item in live] == [8001, 8002]


def test_windows_api_standin_job_unavailable_falls_back_to_tree(monkeypatch):
    _install_windows_toolhelp(monkeypatch, rows=[(9102, 9101)])
    owned = OwnedProcessTree(
        kind="windows-process-tree",
        root_pid=9101,
        process_group=None,
        job=_FakeWindowsJob([], handle=None),
    )
    live = _list_owned_processes(owned, _exited_handle(9101))
    assert [item["pid"] for item in live] == [9102]


def test_windows_api_standin_snapshot_failure_is_observable(monkeypatch):
    fake = _install_windows_toolhelp(monkeypatch, snapshot_failed=True)
    owned = OwnedProcessTree(
        kind="windows-process-tree",
        root_pid=4242,
        process_group=None,
        job=_FakeWindowsJob([], handle=None),
    )
    with pytest.raises(OSError, match="CreateToolhelp32Snapshot"):
        _windows_process_tree_pids(4242)
    live = _list_owned_processes(owned, _exited_handle(4242))
    assert live, "snapshot failure must not look like a clean empty tree"
    assert any(item.get("error") for item in live)
    assert fake.create_calls >= 1


def test_windows_api_standin_job_query_failure_is_observable(monkeypatch):
    _install_windows_toolhelp(monkeypatch, snapshot_failed=True)
    owned = OwnedProcessTree(
        kind="windows-job",
        root_pid=4242,
        process_group=None,
        job=_FakeWindowsJob(handle=object(), query_error="QueryInformationJobObject failed"),
    )
    live = _list_owned_processes(owned, _exited_handle(4242))
    assert live, "job query failure must not be converted into no leftovers"
    assert any("QueryInformationJobObject" in str(item.get("error") or "") for item in live)


@pytest.mark.skipif(os.name != "nt", reason="Windows live process-tree probe pending on this host")
def test_windows_live_parent_exit_reaps_owned_tree(tmp_path):
    project = _project(
        tmp_path,
        """import pathlib
import subprocess
import sys


def test_parent_exits_child_keeps_running():
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pathlib.Path("child.pid").write_text(str(child.pid), encoding="utf-8")
""",
    )
    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(project, soft_seconds=2.0, hard_seconds=4.0),
        8.0,
    )
    child_pid = _read_pid_file(project / "child.pid")
    try:
        assert result.status == "UNVERIFIED"
        _wait_until_dead(child_pid)
        assert not _process_is_live(child_pid)
    finally:
        _reap_if_live(child_pid)


def test_runner_source_never_kills_by_process_name():
    source = GATE_SCRIPT.read_text(encoding="utf-8")
    assert "pkill" not in source
    assert "killall" not in source
    assert "/IM" not in source


def test_failure_longrepr_and_captured_output_are_persisted(tmp_path):
    project = _project(
        tmp_path,
        "def test_failure():\n    print('visible output')\n    assert False, 'expected failure'\n",
    )

    result = _run_tiny_gate(project)
    phase = _record(result)["phases"][0]
    first = phase["first_failure"]
    assert first["nodeid"].endswith("test_tiny.py::test_failure")
    assert first["phase"] == "call"
    assert "expected failure" in (first.get("longrepr") or "")
    assert "visible output" in (first.get("capstdout") or "")
    failures_path = Path(phase["artifacts"]["failures"])
    assert failures_path.exists()
    assert "expected failure" in failures_path.read_text(encoding="utf-8")


def test_first_failure_preserved_when_later_item_hangs(tmp_path):
    project = _project(
        tmp_path,
        """import time


def test_fail_first():
    print('captured first')
    assert False, 'first boom'


def test_hang_second():
    time.sleep(60)
""",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(project, soft_seconds=0.3, hard_seconds=1.2),
        8.0,
    )
    record = _record(result)
    phase = record["phases"][0]
    first = phase["first_failure"]
    assert result.status == "UNVERIFIED"
    assert first["nodeid"].endswith("test_fail_first")
    assert first["phase"] == "call"
    assert "first boom" in (first.get("longrepr") or "")
    assert "captured first" in (first.get("capstdout") or "")
    assert str(phase.get("current_node") or "").endswith("test_hang_second")


def test_setup_fail_records_teardown_phase(tmp_path):
    project = _project(
        tmp_path,
        """import pytest


@pytest.fixture
def boom():
    raise RuntimeError("setup boom")
    yield


def test_depends(boom):
    assert True
""",
    )

    result = _run_tiny_gate(project)
    events = _phase_events(_record(result)["phases"][0])
    assert any(
        event["phase"] == "setup"
        and event["state"] == "complete"
        and event.get("outcome") == "failed"
        for event in events
    )
    assert any("setup boom" in (event.get("longrepr") or "") for event in events)
    assert any(event["phase"] == "teardown" and event["state"] == "start" for event in events)
    assert any(event["phase"] == "teardown" and event["state"] == "complete" for event in events)


def test_setup_skip_records_teardown_phase(tmp_path):
    project = _project(
        tmp_path,
        """import pytest


@pytest.fixture
def skipfix():
    pytest.skip("skip setup")
    yield


def test_depends(skipfix):
    assert True
""",
    )

    result = _run_tiny_gate(project)
    events = _phase_events(_record(result)["phases"][0])
    assert any(
        event["phase"] == "setup"
        and event["state"] == "complete"
        and event.get("outcome") == "skipped"
        for event in events
    )
    assert any(event["phase"] == "teardown" and event["state"] == "start" for event in events)
    assert any(event["phase"] == "teardown" and event["state"] == "complete" for event in events)


def test_collection_events_and_collection_failure_are_recorded(tmp_path):
    project = _project(
        tmp_path,
        "import definitely_missing_module_for_gate\n\ndef test_ok():\n    assert True\n",
    )

    result = _run_tiny_gate(project)
    record = _record(result)
    phase = record["phases"][0]
    events = _phase_events(phase)
    assert any(event["phase"] == "collection" and event["state"] == "start" for event in events)
    assert any(
        event["phase"] == "collection" and event.get("outcome") == "failed"
        for event in events
    )
    blob = Path(phase["artifacts"]["events"]).read_text(encoding="utf-8")
    assert "definitely_missing_module_for_gate" in blob
    assert phase["first_failure"]["phase"] == "collection"
    assert "definitely_missing_module_for_gate" in (phase["first_failure"].get("longrepr") or "")


def test_stack_dump_is_separate_from_termination(tmp_path):
    project = _project(
        tmp_path,
        "import time\n\ndef test_sleep_forever():\n    time.sleep(60)\n",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(project, soft_seconds=0.15, hard_seconds=0.8),
        8.0,
    )
    phase = _record(result)["phases"][0]
    soft = json.loads(Path(phase["artifacts"]["soft_diagnostic"]).read_text(encoding="utf-8"))
    hard = json.loads(Path(phase["artifacts"]["hard_diagnostic"]).read_text(encoding="utf-8"))
    stack_path = Path(phase["artifacts"]["stack_dump"])
    assert stack_path.exists()
    stack_text = stack_path.read_text(encoding="utf-8", errors="replace")
    assert "python stack dump" in stack_text.lower() or "Thread" in stack_text
    assert "python_stack_dump" in soft
    assert "python_stack_dump" in hard
    assert phase["termination_actions"]
    assert "termination_actions" not in soft.get("reason", "")


def test_unavailable_snapshot_does_not_report_stable_pass(tmp_path, monkeypatch):
    project = _project(tmp_path, "def test_ok():\n    assert True\n")
    monkeypatch.setattr(
        "scripts.run_test_gate.capture_repo_snapshot",
        lambda *args, **kwargs: {"available": False, "error": "git snapshot failed"},
    )

    result = _run_tiny_gate(project)
    record = _record(result)
    assert record["phases"][0]["status"] == "PASS"
    assert record["pytest_status"] == "PASS"
    assert record["source_snapshot_matches"] is None
    assert result.status == "UNVERIFIED"
    assert record["status"] == "UNVERIFIED"
    assert any("snapshot unavailable" in reason for reason in record["unverified_reasons"])


def test_source_change_marks_overall_unverified(tmp_path, monkeypatch):
    project = _project(tmp_path, "def test_ok():\n    assert True\n")
    snapshots = iter(
        [
            {"available": True, "head": "aaa", "dirty_fingerprint": "one"},
            {"available": True, "head": "aaa", "dirty_fingerprint": "two"},
        ]
    )
    monkeypatch.setattr(
        "scripts.run_test_gate.capture_repo_snapshot",
        lambda *args, **kwargs: dict(next(snapshots)),
    )

    result = _run_tiny_gate(project)
    record = _record(result)
    assert record["phases"][0]["status"] == "PASS"
    assert record["pytest_status"] == "PASS"
    assert record["source_snapshot_matches"] is False
    assert result.status == "UNVERIFIED"
    assert any("fingerprint changed" in reason for reason in record["unverified_reasons"])


def test_git_failure_marks_overall_unverified(tmp_path, monkeypatch):
    project = _project(tmp_path, "def test_ok():\n    assert True\n")

    def boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr("scripts.run_test_gate._run_git", boom)

    result = _run_tiny_gate(project)
    record = _record(result)
    assert record["snapshot_before"]["available"] is False
    assert record["phases"][0]["status"] == "PASS"
    assert record["pytest_status"] == "PASS"
    assert record["source_snapshot_matches"] is None
    assert result.status == "UNVERIFIED"


def test_two_phase_fail_then_pass_is_fail(tmp_path):
    project = _project(tmp_path, "def test_failure():\n    assert False, 'phase one fail'\n")
    (project / "test_ok2.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    result = _run_tiny_gate(
        project,
        phases=[
            PhaseCommand("fail", (sys.executable, "-m", "pytest", "test_tiny.py", "-q")),
            PhaseCommand("pass", (sys.executable, "-m", "pytest", "test_ok2.py", "-q")),
        ],
    )
    record = _record(result)
    assert record["phases"][0]["status"] == "FAIL"
    assert record["phases"][1]["status"] == "PASS"
    assert record["pytest_status"] == "FAIL"
    assert result.status == "FAIL"


def test_two_phase_clean_exit_continues_to_second_phase(tmp_path):
    project = _project(tmp_path, "def test_ok():\n    assert True\n")
    (project / "test_ok2.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    result = _run_tiny_gate(
        project,
        phases=[
            PhaseCommand("one", (sys.executable, "-m", "pytest", "test_tiny.py", "-q")),
            PhaseCommand("two", (sys.executable, "-m", "pytest", "test_ok2.py", "-q")),
        ],
    )
    record = _record(result)
    assert record["phases"][0]["status"] == "PASS"
    assert record["phases"][1]["status"] == "PASS"
    assert record["phases"][0].get("leftover_processes") in ([], None)
    assert record["pytest_status"] == "PASS"
    assert result.status == "PASS"


def test_two_phase_owned_child_triggers_cleanup_and_skips_later_phase(tmp_path):
    project = _project(
        tmp_path,
        """import pathlib
import subprocess
import sys


def test_parent_exits_child_keeps_running():
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGHUP, signal.SIG_IGN); time.sleep(60)"
            if __import__("os").name != "nt"
            else "import time; time.sleep(60)",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pathlib.Path("child.pid").write_text(str(child.pid), encoding="utf-8")
""",
    )
    (project / "test_ok2.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(
            project,
            soft_seconds=2.0,
            hard_seconds=4.0,
            phases=[
                PhaseCommand("child", (sys.executable, "-m", "pytest", "test_tiny.py", "-q")),
                PhaseCommand("two", (sys.executable, "-m", "pytest", "test_ok2.py", "-q")),
            ],
        ),
        8.0,
    )
    child_pid = _read_pid_file(project / "child.pid")
    try:
        record = _record(result)
        assert result.status == "UNVERIFIED"
        assert record["phases"][0]["status"] == "UNVERIFIED"
        assert len(record["phases"]) == 1
        assert any(
            "later phases were not started" in reason
            for reason in record.get("unverified_reasons") or []
        )
        _wait_until_dead(child_pid)
        assert not _process_is_live(child_pid)
        leftovers = record["phases"][0].get("leftover_processes") or []
        assert leftovers == [] or not any(
            item.get("pid") is not None and int(item["pid"]) == child_pid
            for item in leftovers
        )
        actions = record["phases"][0].get("termination_actions") or []
        assert actions
        assert not any("/IM" in str(action) for action in actions)
    finally:
        _reap_if_live(child_pid)


def test_two_phase_pass_then_unverified_is_unverified(tmp_path):
    project = _project(tmp_path, "def test_ok():\n    assert True\n")
    (project / "test_hang.py").write_text(
        "import time\n\ndef test_sleep_forever():\n    time.sleep(60)\n",
        encoding="utf-8",
    )

    result = _run_with_outer_deadline(
        lambda: _run_tiny_gate(
            project,
            soft_seconds=0.2,
            hard_seconds=0.8,
            phases=[
                PhaseCommand("pass", (sys.executable, "-m", "pytest", "test_tiny.py", "-q")),
                PhaseCommand("hang", (sys.executable, "-m", "pytest", "test_hang.py", "-q")),
            ],
        ),
        12.0,
    )
    record = _record(result)
    assert record["phases"][0]["status"] == "PASS"
    assert record["phases"][1]["status"] == "UNVERIFIED"
    assert record["pytest_status"] == "UNVERIFIED"
    assert result.status == "UNVERIFIED"


def test_compose_snapshot_none_keeps_pytest_pass_but_overall_unverified():
    overall, pytest_status, reasons = compose_gate_status(
        ["PASS"],
        snapshot_matches=None,
    )
    assert pytest_status == "PASS"
    assert overall == "UNVERIFIED"
    assert any("snapshot unavailable" in reason for reason in reasons)


def test_compose_fail_then_unverified_is_unverified():
    overall, pytest_status, reasons = compose_gate_status(
        ["FAIL", "UNVERIFIED"],
        snapshot_matches=True,
    )
    assert pytest_status == "UNVERIFIED"
    assert overall == "UNVERIFIED"
    assert reasons == []


def test_preflight_skips_unknown_cwd(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("scripts.run_test_gate.shutil.which", lambda name: "/usr/bin/lsof" if name == "lsof" else None)

    def fake_run(cmd, **kwargs):
        if cmd[:1] == ["ps"] or (cmd and cmd[0] == "ps"):
            return subprocess.CompletedProcess(cmd, 0, "91 1 91 pytest other\n", "")
        return subprocess.CompletedProcess(cmd, 1, "", "no cwd")

    monkeypatch.setattr("scripts.run_test_gate.subprocess.run", fake_run)
    assert _find_pytest_in_same_checkout(repo) == []


def test_preflight_ignores_subdirectory_cwd(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    nested = repo / "tests"
    nested.mkdir()
    monkeypatch.setattr("scripts.run_test_gate.shutil.which", lambda name: "/usr/bin/lsof" if name == "lsof" else None)

    def fake_run(cmd, **kwargs):
        if cmd[:1] == ["ps"] or (cmd and cmd[0] == "ps"):
            return subprocess.CompletedProcess(cmd, 0, "92 1 92 pytest nested\n", "")
        return subprocess.CompletedProcess(cmd, 0, f"p92\nn{nested}\n", "")

    monkeypatch.setattr("scripts.run_test_gate.subprocess.run", fake_run)
    assert _find_pytest_in_same_checkout(repo) == []


def test_preflight_limits_document_unknown_cwd_subdirectory_and_raced_start(tmp_path):
    project = _project(tmp_path, "def test_ok():\n    assert True\n")
    record = _record(_run_tiny_gate(project))
    limits = record["preflight"]["limits"]
    assert limits["unknown_cwd"] == PREFLIGHT_LIMITS["unknown_cwd"]
    assert limits["subdirectory"] == PREFLIGHT_LIMITS["subdirectory"]
    assert limits["raced_start"] == PREFLIGHT_LIMITS["raced_start"]
    assert "mutex" in limits["raced_start"].lower() or "no checkout mutex" in limits["raced_start"].lower()


def test_write_json_retries_replace_permission_error(tmp_path, monkeypatch):
    path = tmp_path / "run.json"
    calls = {"n": 0}
    original = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "Access is denied")
        return original(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    _write_json(path, {"ok": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}
    assert calls["n"] == 3


def test_snapshot_ignores_tmp_pytest_scratch(tmp_path):
    repo = _project(tmp_path, "def test_ok():\n    assert True\n")
    scratch = repo / ".tmp-pytest"
    scratch.mkdir()
    (scratch / "a.txt").write_text("one", encoding="utf-8")
    run_root = repo / "gate-artifacts"
    run_root.mkdir()
    (run_root / "ev.txt").write_text("ev", encoding="utf-8")
    ignored = (run_root, repo / ".tmp-pytest")
    first = capture_repo_snapshot(repo, ignored_roots=ignored)
    (scratch / "b.txt").write_text("two", encoding="utf-8")
    (run_root / "ev2.txt").write_text("ev2", encoding="utf-8")
    second = capture_repo_snapshot(repo, ignored_roots=ignored)
    assert first["available"] and second["available"]
    assert first["dirty_fingerprint"] == second["dirty_fingerprint"]
    (repo / "src.py").write_text("changed", encoding="utf-8")
    third = capture_repo_snapshot(repo, ignored_roots=ignored)
    assert third["dirty_fingerprint"] != first["dirty_fingerprint"]
