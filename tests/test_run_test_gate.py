"""Focused self-tests for the outer pytest gate watchdog.

These tests deliberately exercise a throwaway pytest project.  They never run
the repository suite through the watchdog.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.run_test_gate import PhaseCommand, run_test_gate


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
):
    return run_test_gate(
        [
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
    )


def _record(result) -> dict:
    return json.loads(result.record_path.read_text(encoding="utf-8"))


def _process_is_live(pid: int) -> bool:
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


def test_gate_records_clean_snapshot_and_pytest_phase_events(tmp_path):
    project = _project(tmp_path, "def test_ok():\n    assert True\n")

    result = _run_tiny_gate(project)

    assert result.status == "PASS"
    record = _record(result)
    assert record["status"] == "PASS"
    assert record["snapshot_before"]["head"]
    assert record["snapshot_before"]["dirty_fingerprint"] == record["snapshot_after"][
        "dirty_fingerprint"
    ]
    phase = record["phases"][0]
    assert phase["status"] == "PASS"
    assert phase["pid"] == phase["owned_process_group"]
    assert phase["current_node"].endswith("test_tiny.py::test_ok")
    assert phase["current_phase"] == "teardown"
    events = [
        json.loads(line)
        for line in Path(phase["artifacts"]["events"]).read_text(encoding="utf-8").splitlines()
    ]
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
    phase = _record(result)["phases"][0]
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

    result = _run_tiny_gate(project, soft_seconds=0.15, hard_seconds=0.75)

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

    result = _run_tiny_gate(project, soft_seconds=0.15, hard_seconds=1.0)

    assert result.status == "UNVERIFIED"
    child_pid = int((project / "child.pid").read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2.0
    while _process_is_live(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        assert not _process_is_live(child_pid), "watchdog left its test child alive"
    finally:
        if _process_is_live(child_pid):
            os.kill(child_pid, signal.SIGKILL)
