#!/usr/bin/env python3
"""Run bounded pytest gates with durable, phase-level diagnostics.

This is deliberately an *outer* watchdog.  It starts one fresh process group
per phase, records its own evidence under ``.state/test-runs/``, and never
attaches to or terminates a process it did not create.  A timeout, signal,
interruption, or source snapshot change is ``UNVERIFIED``; a normal pytest
assertion failure remains ``FAIL``.

Examples::

    # An explicit focused gate (the command is parsed without a shell):
    .venv/bin/python scripts/run_test_gate.py \\
      --phase 'focused=.venv/bin/python -m pytest tests/test_example.py -q'

    # The two full-suite phases, strictly sequentially:
    .venv/bin/python scripts/run_test_gate.py --full-suite \\
      --soft-timeout-seconds 900 --hard-timeout-seconds 1500

The ``--full-suite`` form is intentionally explicit so invoking this script
without arguments cannot accidentally begin a long repository gate.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import queue
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
_PYTEST_PLUGIN_NAME = "test_gate_pytest_plugin"
_NODEID_PATTERN = re.compile(r"(?P<node>[^\s]+::[^\s]+)")


_PYTEST_PLUGIN_SOURCE = r'''"""Ephemeral event writer injected by scripts.run_test_gate."""
from __future__ import annotations

import json
import os
import time


_EVENT_PATH = os.environ.get("TEST_GATE_EVENT_FILE")


def _emit(*, nodeid=None, phase=None, state=None, **extra):
    if not _EVENT_PATH:
        return
    payload = {
        "timestamp": time.time(),
        "nodeid": nodeid,
        "phase": phase,
        "state": state,
        **extra,
    }
    try:
        with open(_EVENT_PATH, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
    except OSError:
        # Diagnostics must never alter the test process's outcome.
        return


def pytest_sessionstart(session):
    _emit(phase="session", state="start")


def pytest_runtest_logstart(nodeid, location):
    _emit(nodeid=nodeid, phase="setup", state="start")


def pytest_runtest_logreport(report):
    _emit(
        nodeid=report.nodeid,
        phase=report.when,
        state="complete",
        outcome=report.outcome,
        duration_seconds=report.duration,
    )
    if report.when == "setup" and report.outcome == "passed":
        _emit(nodeid=report.nodeid, phase="call", state="start")
    elif report.when == "call":
        _emit(nodeid=report.nodeid, phase="teardown", state="start")


def pytest_sessionfinish(session, exitstatus):
    _emit(phase="session", state="complete", exitstatus=exitstatus)
'''


@dataclass(frozen=True)
class PhaseCommand:
    """One command that the gate owns and runs in a fresh process group."""

    name: str
    command: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("phase name must not be empty")
        if not self.command:
            raise ValueError(f"phase {self.name!r} has no command")


@dataclass(frozen=True)
class GateResult:
    """Stable result returned to tests and the CLI wrapper."""

    status: str
    record_path: Path
    exit_code: int


class _EventReader:
    """Incrementally consume newline-delimited JSON without rereading the file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offset = 0
        self._partial = ""

    def read(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as stream:
            stream.seek(self._offset)
            chunk = stream.read()
            self._offset = stream.tell()
        if not chunk:
            return []

        lines = (self._partial + chunk).split("\n")
        self._partial = lines.pop()
        events: list[dict[str, Any]] = []
        for line in lines:
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # A plugin diagnostic must not disrupt the outer watchdog.
                continue
            if isinstance(event, dict):
                events.append(event)
        return events


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    if path.is_symlink():
        return _sha256_bytes(("symlink:\0" + os.readlink(path)).encode("utf-8"))
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        timeout=10,
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def capture_repo_snapshot(
    repo_root: Path,
    *,
    ignored_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    """Capture HEAD plus a content-sensitive dirty fingerprint.

    ``run_root`` is intentionally excluded: evidence generated by this script
    must not make its own successful process appear to have changed sources.
    """

    repo_root = repo_root.resolve()
    try:
        head_result = _run_git(repo_root, "rev-parse", "HEAD")
        status_result = _run_git(
            repo_root,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=no",
        )
        diff_result = _run_git(repo_root, "diff", "--no-ext-diff", "--binary", "HEAD")
        untracked_result = _run_git(
            repo_root,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return {"available": False, "error": f"git snapshot failed: {exc}"}

    results = (head_result, status_result, diff_result, untracked_result)
    if any(result.returncode != 0 for result in results):
        stderr = b"\n".join(result.stderr for result in results if result.stderr)
        return {
            "available": False,
            "error": stderr.decode("utf-8", errors="replace").strip()
            or "git snapshot command failed",
        }

    ignored = tuple(root.resolve() for root in ignored_roots)
    untracked: list[dict[str, str]] = []
    for raw_path in untracked_result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(os.fsdecode(raw_path))
        absolute = repo_root / relative
        if any(_is_within(absolute, root) for root in ignored):
            continue
        try:
            digest = _sha256_path(absolute)
        except OSError as exc:
            digest = f"UNREADABLE:{type(exc).__name__}:{exc}"
        untracked.append({"path": relative.as_posix(), "sha256": digest})
    untracked.sort(key=lambda entry: entry["path"])

    dirty_payload = {
        "tracked_status_sha256": _sha256_bytes(status_result.stdout),
        "tracked_diff_sha256": _sha256_bytes(diff_result.stdout),
        "untracked": untracked,
    }
    return {
        "available": True,
        "repo_root": str(repo_root),
        "head": head_result.stdout.decode("ascii", errors="replace").strip(),
        "dirty_fingerprint": _sha256_bytes(
            json.dumps(
                dirty_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ),
        **dirty_payload,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        stream.flush()


def _dependency_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {
        "python": sys.version.replace("\n", " "),
        "executable": sys.executable,
        "platform": sys.platform,
    }
    for package in ("pytest", "pytest-qt"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def _find_pytest_in_same_checkout(repo_root: Path) -> list[dict[str, Any]]:
    """Return only externally owned pytest processes whose cwd is known.

    macOS does not expose every process cwd through ``ps``.  ``lsof`` is used
    when available; an unknown cwd is recorded but never guessed to be this
    checkout, avoiding false positives against unrelated developers' runs.
    """

    try:
        listing = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pgid=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if listing.returncode != 0:
        return []

    lsof = shutil.which("lsof")
    current_pid = os.getpid()
    matches: list[dict[str, Any]] = []
    for line in listing.stdout.splitlines():
        fields = line.strip().split(None, 3)
        if len(fields) != 4:
            continue
        pid_text, parent_text, pgid_text, command = fields
        if "pytest" not in command.lower():
            continue
        try:
            pid = int(pid_text)
            parent_pid = int(parent_text)
            pgid = int(pgid_text)
        except ValueError:
            continue
        if pid == current_pid:
            continue

        cwd: str | None = None
        if lsof:
            try:
                cwd_result = subprocess.run(
                    [lsof, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                cwd_result = None
            if cwd_result and cwd_result.returncode == 0:
                for cwd_line in cwd_result.stdout.splitlines():
                    if cwd_line.startswith("n"):
                        cwd = cwd_line[1:]
                        break
        if cwd is None:
            continue
        try:
            same_checkout = Path(cwd).resolve() == repo_root.resolve()
        except OSError:
            same_checkout = False
        if same_checkout:
            matches.append(
                {
                    "pid": pid,
                    "ppid": parent_pid,
                    "pgid": pgid,
                    "cwd": cwd,
                    "command": command,
                }
            )
    return matches


def _pytest_command_with_event_plugin(
    command: Sequence[str],
    *,
    plugin_dir: Path,
    event_path: Path,
    env: dict[str, str],
) -> tuple[list[str], bool]:
    """Inject a narrow plugin only for a recognisable pytest command."""

    command_list = list(command)
    insertion_index: int | None = None
    for index in range(len(command_list) - 1):
        if command_list[index] == "-m" and command_list[index + 1] == "pytest":
            insertion_index = index + 2
            break
    if insertion_index is None and command_list:
        executable = Path(command_list[0]).name.lower()
        if executable in {"pytest", "pytest.exe"}:
            insertion_index = 1
    if insertion_index is None:
        return command_list, False

    plugin_path = plugin_dir / f"{_PYTEST_PLUGIN_NAME}.py"
    plugin_path.write_text(_PYTEST_PLUGIN_SOURCE, encoding="utf-8")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(plugin_dir)
        if not existing_pythonpath
        else str(plugin_dir) + os.pathsep + existing_pythonpath
    )
    env["TEST_GATE_EVENT_FILE"] = str(event_path)
    command_list[insertion_index:insertion_index] = ["-p", _PYTEST_PLUGIN_NAME]
    return command_list, True


def _start_output_reader(process: subprocess.Popen[str]) -> tuple[queue.Queue[str | None], threading.Thread]:
    lines: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    lines.put(line)
        finally:
            lines.put(None)

    thread = threading.Thread(target=reader, name="test-gate-output-reader", daemon=True)
    thread.start()
    return lines, thread


def _drain_output(
    lines: queue.Queue[str | None],
    output: Any,
    tail: deque[str],
    phase_record: dict[str, Any],
) -> bool:
    reader_closed = False
    while True:
        try:
            line = lines.get_nowait()
        except queue.Empty:
            break
        if line is None:
            reader_closed = True
            continue
        output.write(line)
        output.flush()
        tail.append(line.rstrip("\n"))
        match = _NODEID_PATTERN.search(line)
        if match:
            phase_record["current_node"] = match.group("node")
            phase_record["last_progress_at"] = _utc_now()
    return reader_closed


def _apply_events(
    events: Sequence[dict[str, Any]], phase_record: dict[str, Any]) -> bool:
    if not events:
        return False
    for event in events:
        nodeid = event.get("nodeid")
        phase = event.get("phase")
        if isinstance(nodeid, str) and nodeid:
            phase_record["current_node"] = nodeid
        if phase in {"setup", "call", "teardown"}:
            phase_record["current_phase"] = phase
        phase_record["last_progress_at"] = _utc_now()
        phase_record["event_count"] += 1
    return True


def _diagnostic_payload(
    *,
    process: subprocess.Popen[str],
    process_group: int | None,
    reason: str,
    elapsed_seconds: float,
    phase_record: dict[str, Any],
    output_tail: Sequence[str],
) -> dict[str, Any]:
    ps_output = ""
    try:
        ps_result = subprocess.run(
            [
                "ps",
                "-o",
                "pid=,ppid=,pgid=,etime=,state=,rss=,command=",
                "-p",
                str(process.pid),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        ps_output = (ps_result.stdout + ps_result.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        ps_output = f"ps unavailable: {exc}"
    return {
        "timestamp": _utc_now(),
        "reason": reason,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "pid": process.pid,
        "owned_process_group": process_group,
        "returncode": process.poll(),
        "current_node": phase_record.get("current_node"),
        "current_phase": phase_record.get("current_phase"),
        "last_progress_at": phase_record.get("last_progress_at"),
        "process_snapshot": ps_output,
        "output_tail": list(output_tail),
    }


def _terminate_owned_process_group(
    process: subprocess.Popen[str],
    *,
    process_group: int | None,
    grace_seconds: float,
) -> list[str]:
    """Stop only the process group/tree created by this runner invocation."""

    actions: list[str] = []
    if process.poll() is not None:
        return actions
    if os.name == "posix":
        if process_group is None:
            raise RuntimeError("POSIX watchdog missing its owned process group")
        try:
            os.killpg(process_group, signal.SIGTERM)
            actions.append(f"SIGTERM process group {process_group}")
        except ProcessLookupError:
            return actions
    else:
        # ``/T`` limits taskkill to the tree rooted at our own child PID.
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                text=True,
                timeout=max(2.0, grace_seconds + 1.0),
            )
            actions.append(f"taskkill owned process tree {process.pid}")
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            actions.append(f"taskkill unavailable: {exc}")
            process.kill()
            actions.append(f"kill owned process {process.pid}")

    deadline = time.monotonic() + grace_seconds
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)

    if process.poll() is None and os.name == "posix":
        assert process_group is not None
        try:
            os.killpg(process_group, signal.SIGKILL)
            actions.append(f"SIGKILL process group {process_group}")
        except ProcessLookupError:
            pass
    if process.poll() is None:
        try:
            process.wait(timeout=max(1.0, grace_seconds))
        except subprocess.TimeoutExpired:
            actions.append("owned process still running after termination budget")
    return actions


def _phase_status(*, returncode: int | None, hard_timeout: bool, interrupted: bool) -> str:
    if hard_timeout or interrupted:
        return "UNVERIFIED"
    if returncode == 0:
        return "PASS"
    if returncode == 1:
        return "FAIL"
    return "UNVERIFIED"


def _run_phase(
    phase: PhaseCommand,
    *,
    cwd: Path,
    phase_dir: Path,
    soft_timeout_seconds: float,
    hard_timeout_seconds: float,
    heartbeat_seconds: float,
    terminate_grace_seconds: float,
    register_phase: Callable[[dict[str, Any]], None],
    persist: Callable[[], None],
) -> dict[str, Any]:
    phase_dir.mkdir(parents=True, exist_ok=False)
    output_path = phase_dir / "pytest-output.log"
    event_path = phase_dir / "pytest-events.jsonl"
    heartbeat_path = phase_dir / "heartbeats.jsonl"
    soft_diagnostic_path = phase_dir / "soft-deadline.json"
    hard_diagnostic_path = phase_dir / "hard-deadline.json"
    interrupt_diagnostic_path = phase_dir / "interrupted.json"

    env = os.environ.copy()
    effective_command, has_pytest_events = _pytest_command_with_event_plugin(
        phase.command,
        plugin_dir=phase_dir,
        event_path=event_path,
        env=env,
    )
    phase_record: dict[str, Any] = {
        "name": phase.name,
        "command": list(phase.command),
        "effective_command": effective_command,
        "cwd": str(cwd),
        "started_at": _utc_now(),
        "ended_at": None,
        "elapsed_seconds": None,
        "pid": None,
        "owned_process_group": None,
        "pytest_event_plugin": has_pytest_events,
        "current_node": None,
        "current_phase": None,
        "last_progress_at": None,
        "event_count": 0,
        "soft_deadline_exceeded": False,
        "hard_deadline_exceeded": False,
        "interrupted": False,
        "termination_actions": [],
        "exit_code": None,
        "status": "RUNNING",
        "artifacts": {
            "output": str(output_path),
            "events": str(event_path),
            "heartbeats": str(heartbeat_path),
            "soft_diagnostic": str(soft_diagnostic_path),
            "hard_diagnostic": str(hard_diagnostic_path),
            "interrupt_diagnostic": str(interrupt_diagnostic_path),
        },
    }
    register_phase(phase_record)
    persist()

    popen_kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    else:
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        process = subprocess.Popen(effective_command, **popen_kwargs)
    except OSError as exc:
        phase_record["ended_at"] = _utc_now()
        phase_record["elapsed_seconds"] = 0.0
        phase_record["status"] = "UNVERIFIED"
        phase_record["launch_error"] = f"{type(exc).__name__}: {exc}"
        return phase_record

    process_group = process.pid if os.name == "posix" else None
    phase_record["pid"] = process.pid
    phase_record["owned_process_group"] = process_group if process_group is not None else process.pid
    persist()

    lines, reader_thread = _start_output_reader(process)
    event_reader = _EventReader(event_path)
    output_tail: deque[str] = deque(maxlen=120)
    started_monotonic = time.monotonic()
    next_heartbeat = started_monotonic
    reader_closed = False
    soft_recorded = False
    hard_recorded = False
    interrupted = False

    def stop_for_interrupt(elapsed_seconds: float) -> None:
        nonlocal interrupted
        if interrupted:
            return
        interrupted = True
        phase_record["interrupted"] = True
        _write_json(
            interrupt_diagnostic_path,
            _diagnostic_payload(
                process=process,
                process_group=process_group,
                reason="gate coordinator interrupted; stopping owned process group",
                elapsed_seconds=elapsed_seconds,
                phase_record=phase_record,
                output_tail=output_tail,
            ),
        )
        phase_record["termination_actions"] = _terminate_owned_process_group(
            process,
            process_group=process_group,
            grace_seconds=terminate_grace_seconds,
        )
        persist()

    with output_path.open("w", encoding="utf-8", buffering=1) as output:
        while True:
            reader_closed = _drain_output(lines, output, output_tail, phase_record) or reader_closed
            progress_changed = _apply_events(event_reader.read(), phase_record)
            now = time.monotonic()
            elapsed = now - started_monotonic

            if progress_changed:
                persist()
            if now >= next_heartbeat:
                heartbeat = {
                    "timestamp": _utc_now(),
                    "elapsed_seconds": round(elapsed, 3),
                    "current_node": phase_record["current_node"],
                    "current_phase": phase_record["current_phase"],
                    "last_progress_at": phase_record["last_progress_at"],
                    "returncode": process.poll(),
                }
                _append_jsonl(heartbeat_path, heartbeat)
                phase_record["last_heartbeat"] = heartbeat
                persist()
                next_heartbeat = now + heartbeat_seconds

            try:
                if not soft_recorded and elapsed >= soft_timeout_seconds:
                    phase_record["soft_deadline_exceeded"] = True
                    _write_json(
                        soft_diagnostic_path,
                        _diagnostic_payload(
                            process=process,
                            process_group=process_group,
                            reason="soft deadline exceeded; process left running",
                            elapsed_seconds=elapsed,
                            phase_record=phase_record,
                            output_tail=output_tail,
                        ),
                    )
                    soft_recorded = True
                    persist()

                if not hard_recorded and elapsed >= hard_timeout_seconds:
                    phase_record["hard_deadline_exceeded"] = True
                    _write_json(
                        hard_diagnostic_path,
                        _diagnostic_payload(
                            process=process,
                            process_group=process_group,
                            reason="hard deadline exceeded; stopping owned process group",
                            elapsed_seconds=elapsed,
                            phase_record=phase_record,
                            output_tail=output_tail,
                        ),
                    )
                    phase_record["termination_actions"] = _terminate_owned_process_group(
                        process,
                        process_group=process_group,
                        grace_seconds=terminate_grace_seconds,
                    )
                    hard_recorded = True
                    persist()
            except KeyboardInterrupt:
                stop_for_interrupt(elapsed)

            if process.poll() is not None and reader_closed:
                # One final flush picks up plugin events written immediately
                # before pytest exits.
                _apply_events(event_reader.read(), phase_record)
                break
            try:
                time.sleep(0.02)
            except KeyboardInterrupt:
                stop_for_interrupt(time.monotonic() - started_monotonic)

    reader_thread.join(timeout=1.0)
    phase_record["exit_code"] = process.poll()
    phase_record["ended_at"] = _utc_now()
    phase_record["elapsed_seconds"] = round(time.monotonic() - started_monotonic, 3)
    phase_record["status"] = _phase_status(
        returncode=phase_record["exit_code"],
        hard_timeout=hard_recorded,
        interrupted=interrupted,
    )
    persist()
    return phase_record


def _new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"-pid{os.getpid()}"


def run_test_gate(
    phases: Sequence[PhaseCommand],
    *,
    cwd: Path,
    repo_root: Path = REPO_ROOT,
    run_root: Path | None = None,
    soft_timeout_seconds: float = 900.0,
    hard_timeout_seconds: float = 1500.0,
    heartbeat_seconds: float = 30.0,
    terminate_grace_seconds: float = 5.0,
    continue_after_unverified: bool = False,
) -> GateResult:
    """Run phases serially and return a durable PASS/FAIL/UNVERIFIED result."""

    if not phases:
        raise ValueError("at least one phase is required")
    if soft_timeout_seconds < 0:
        raise ValueError("soft_timeout_seconds must be non-negative")
    if hard_timeout_seconds <= soft_timeout_seconds:
        raise ValueError("hard_timeout_seconds must be greater than soft_timeout_seconds")
    if heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be positive")
    if terminate_grace_seconds <= 0:
        raise ValueError("terminate_grace_seconds must be positive")

    cwd = cwd.resolve()
    repo_root = repo_root.resolve()
    if run_root is None:
        run_root = repo_root / ".state" / "test-runs"
    run_root = run_root.resolve()
    run_dir = run_root / _new_run_id()
    run_dir.mkdir(parents=True, exist_ok=False)
    record_path = run_dir / "run.json"
    record: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "status": "RUNNING",
        "coordinator": {
            "pid": os.getpid(),
            "cwd": str(Path.cwd()),
            "requested_cwd": str(cwd),
        },
        "started_at": _utc_now(),
        "ended_at": None,
        "dependencies": _dependency_versions(),
        "timeouts": {
            "soft_seconds": soft_timeout_seconds,
            "hard_seconds": hard_timeout_seconds,
            "heartbeat_seconds": heartbeat_seconds,
            "terminate_grace_seconds": terminate_grace_seconds,
        },
        "commands": [
            {"name": phase.name, "command": list(phase.command)} for phase in phases
        ],
        "snapshot_before": capture_repo_snapshot(repo_root, ignored_roots=(run_root,)),
        "snapshot_after": None,
        "preflight": {},
        "phases": [],
        "unverified_reasons": [],
    }

    def persist() -> None:
        _write_json(record_path, record)

    same_checkout = _find_pytest_in_same_checkout(repo_root)
    record["preflight"] = {
        "same_checkout_pytest_processes": same_checkout,
        "proceeded": not same_checkout,
    }
    persist()
    if same_checkout:
        record["status"] = "UNVERIFIED"
        record["unverified_reasons"].append(
            "refused to overlap an existing pytest process in this checkout"
        )
        record["snapshot_after"] = capture_repo_snapshot(repo_root, ignored_roots=(run_root,))
        record["ended_at"] = _utc_now()
        persist()
        return GateResult("UNVERIFIED", record_path, 2)

    for index, phase in enumerate(phases, start=1):
        phase_dir = run_dir / f"{index:02d}-{_safe_phase_name(phase.name)}"
        phase_record = _run_phase(
            phase,
            cwd=cwd,
            phase_dir=phase_dir,
            soft_timeout_seconds=soft_timeout_seconds,
            hard_timeout_seconds=hard_timeout_seconds,
            heartbeat_seconds=heartbeat_seconds,
            terminate_grace_seconds=terminate_grace_seconds,
            register_phase=record["phases"].append,
            persist=persist,
        )
        persist()
        if phase_record["status"] == "UNVERIFIED" and not continue_after_unverified:
            record["unverified_reasons"].append(
                f"phase {phase.name!r} was unverified; later phases were not started"
            )
            break

    record["snapshot_after"] = capture_repo_snapshot(repo_root, ignored_roots=(run_root,))
    before = record["snapshot_before"]
    after = record["snapshot_after"]
    if before.get("available") and after.get("available"):
        snapshot_matches = (
            before.get("head") == after.get("head")
            and before.get("dirty_fingerprint") == after.get("dirty_fingerprint")
        )
    else:
        snapshot_matches = None
    record["source_snapshot_matches"] = snapshot_matches
    if snapshot_matches is False:
        record["unverified_reasons"].append(
            "HEAD or dirty content fingerprint changed while the gate ran"
        )

    phase_statuses = [phase["status"] for phase in record["phases"]]
    if snapshot_matches is False or "UNVERIFIED" in phase_statuses:
        status = "UNVERIFIED"
    elif "FAIL" in phase_statuses:
        status = "FAIL"
    else:
        status = "PASS"
    record["status"] = status
    record["ended_at"] = _utc_now()
    persist()
    exit_code = 0 if status == "PASS" else 1 if status == "FAIL" else 2
    return GateResult(status, record_path, exit_code)


def _safe_phase_name(name: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip()).strip(".-")
    return compact or "phase"


def _parse_phase(value: str) -> PhaseCommand:
    name, separator, command_text = value.partition("=")
    if not separator or not name.strip() or not command_text.strip():
        raise argparse.ArgumentTypeError("phase must use NAME=COMMAND")
    try:
        command = tuple(shlex.split(command_text))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid phase command: {exc}") from exc
    if not command:
        raise argparse.ArgumentTypeError("phase command must not be empty")
    return PhaseCommand(name=name.strip(), command=command)


def _default_python(repo_root: Path) -> str:
    candidate = repo_root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    return str(candidate) if candidate.exists() else sys.executable


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a bounded, recorded pytest gate.")
    parser.add_argument(
        "--phase",
        action="append",
        type=_parse_phase,
        metavar="NAME=COMMAND",
        help="Repeatable phase. COMMAND is parsed with shlex, never through a shell.",
    )
    parser.add_argument(
        "--full-suite",
        action="store_true",
        help="Run main (--ignore=tests/acquisition_ui) then acquisition in fresh processes.",
    )
    parser.add_argument("--cwd", type=Path, default=REPO_ROOT, help="Working directory for phases.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Git root used for HEAD/dirty fingerprints.",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=None,
        help="Directory for evidence (default: REPO_ROOT/.state/test-runs).",
    )
    parser.add_argument("--soft-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--hard-timeout-seconds", type=float, default=1500.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--terminate-grace-seconds", type=float, default=5.0)
    parser.add_argument(
        "--continue-after-unverified",
        action="store_true",
        help="Run later requested phases after a timeout/crash only when explicitly requested.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.full_suite and args.phase:
        parser.error("--full-suite cannot be combined with --phase")
    if not args.full_suite and not args.phase:
        parser.error("provide at least one --phase or use --full-suite")
    if args.hard_timeout_seconds <= args.soft_timeout_seconds:
        parser.error("--hard-timeout-seconds must be greater than --soft-timeout-seconds")

    repo_root = args.repo_root.resolve()
    if args.full_suite:
        python = _default_python(repo_root)
        phases = [
            PhaseCommand(
                "main",
                (python, "-m", "pytest", "--ignore=tests/acquisition_ui"),
            ),
            PhaseCommand("acquisition", (python, "-m", "pytest", "tests/acquisition_ui")),
        ]
    else:
        phases = args.phase
    run_root = args.run_root
    if run_root is not None and not run_root.is_absolute():
        run_root = repo_root / run_root

    try:
        result = run_test_gate(
            phases,
            cwd=args.cwd,
            repo_root=repo_root,
            run_root=run_root,
            soft_timeout_seconds=args.soft_timeout_seconds,
            hard_timeout_seconds=args.hard_timeout_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
            terminate_grace_seconds=args.terminate_grace_seconds,
            continue_after_unverified=args.continue_after_unverified,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(f"{result.status}: {result.record_path}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
