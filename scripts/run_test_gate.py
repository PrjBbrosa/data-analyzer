#!/usr/bin/env python3
"""Run bounded pytest gates with durable, phase-level diagnostics.

This is deliberately an *outer* watchdog.  It starts one fresh process group
per phase, records its own evidence under ``.state/test-runs/``, and never
attaches to or terminates a process it did not create.  A timeout, signal,
interruption, or source snapshot change is ``UNVERIFIED``; a normal pytest
assertion failure remains ``FAIL``.

Parent-process exit is not the same as “the owned tree has exited”.  Cleanup
always targets this invocation’s process group (POSIX) or job/process tree
(Windows).  The output reader has an independent EOF/join deadline so a
descendant holding stdout cannot pin the coordinator.  If cleanup cannot
finish, the runner still exits boundedly, marks ``UNVERIFIED``, and keeps
leftover evidence.  It never kills by process name.

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
_PYTEST_PLUGIN_NAME = "gate_pytest_plugin"
_NODEID_PATTERN = re.compile(r"(?P<node>[^\s]+::[^\s]+)")

PREFLIGHT_LIMITS = {
    "unknown_cwd": (
        "ps/lsof may not expose cwd (especially macOS); unknown cwd is skipped "
        "and never guessed to be this checkout"
    ),
    "subdirectory": (
        "only an exact resolved cwd match to repo_root counts; pytest whose cwd "
        "is a subdirectory of the checkout is not treated as same-checkout overlap"
    ),
    "raced_start": (
        "preflight is a point-in-time snapshot before phases start; a pytest "
        "launched after this check is not detected. No checkout mutex this round."
    ),
}


_PYTEST_PLUGIN_SOURCE = r'''"""Ephemeral event writer injected by scripts.run_test_gate."""
from __future__ import annotations

import faulthandler
import json
import os
import threading
import time


_EVENT_PATH = os.environ.get("TEST_GATE_EVENT_FILE")
_DUMP_REQUEST = os.environ.get("TEST_GATE_STACK_DUMP_REQUEST")
_DUMP_OUTPUT = os.environ.get("TEST_GATE_STACK_DUMP_FILE")
_MAX_TEXT = 65536
_collection_started = False
_dump_thread_started = False


def _clip(text):
    if text is None:
        return None
    text = str(text)
    if len(text) <= _MAX_TEXT:
        return text
    return text[:_MAX_TEXT] + "\n... [truncated %s chars]" % (len(text) - _MAX_TEXT)


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


def _report_extra(report):
    extra = {
        "outcome": getattr(report, "outcome", None),
        "duration_seconds": getattr(report, "duration", None),
    }
    outcome = extra["outcome"]
    if outcome in {"failed", "skipped"}:
        longrepr = getattr(report, "longreprtext", None)
        if not longrepr and getattr(report, "longrepr", None) is not None:
            longrepr = str(report.longrepr)
        extra["longrepr"] = _clip(longrepr)
        extra["capstdout"] = _clip(getattr(report, "capstdout", None))
        extra["capstderr"] = _clip(getattr(report, "capstderr", None))
    return extra


def _stack_dump_watcher():
    request = _DUMP_REQUEST
    output = _DUMP_OUTPUT
    if not request or not output:
        return
    while True:
        try:
            if os.path.exists(request):
                directory = os.path.dirname(output)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                with open(output, "ab") as stream:
                    header = ("----- python stack dump pid=%s t=%s -----\n" % (
                        os.getpid(),
                        time.time(),
                    )).encode("utf-8", errors="replace")
                    stream.write(header)
                    faulthandler.dump_traceback(file=stream, all_threads=True)
                    stream.flush()
                try:
                    os.remove(request)
                except OSError:
                    pass
        except OSError:
            pass
        time.sleep(0.05)


def pytest_configure(config):
    global _dump_thread_started
    if _dump_thread_started or not _DUMP_REQUEST or not _DUMP_OUTPUT:
        return
    _dump_thread_started = True
    thread = threading.Thread(
        target=_stack_dump_watcher,
        name="test-gate-stack-dump",
        daemon=True,
    )
    thread.start()


def pytest_collectstart(collector):
    global _collection_started
    if _collection_started:
        return
    _collection_started = True
    _emit(phase="collection", state="start", nodeid=getattr(collector, "nodeid", None) or "")


def pytest_collectreport(report):
    extra = _report_extra(report)
    nodeid = getattr(report, "nodeid", None) or ""
    _emit(nodeid=nodeid, phase="collection", state="item", **extra)


def pytest_collection_finish(session):
    items = getattr(session, "items", None) or []
    _emit(phase="collection", state="finish", item_count=len(items))


def pytest_sessionstart(session):
    _emit(phase="session", state="start")


def pytest_runtest_logstart(nodeid, location):
    _emit(nodeid=nodeid, phase="setup", state="start")


def pytest_runtest_logreport(report):
    extra = _report_extra(report)
    _emit(nodeid=report.nodeid, phase=report.when, state="complete", **extra)
    if report.when == "setup" and report.outcome == "passed":
        _emit(nodeid=report.nodeid, phase="call", state="start")
    elif report.when == "setup" and report.outcome in {"failed", "skipped"}:
        _emit(nodeid=report.nodeid, phase="teardown", state="start")
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


@dataclass
class OwnedProcessTree:
    """Identity of the process group/tree created by this runner invocation."""

    kind: str
    root_pid: int
    process_group: int | None
    job: Any = None

    def as_record(self) -> dict[str, Any]:
        job_error = None
        job_attached = False
        if self.job is not None:
            job_attached = getattr(self.job, "handle", None) is not None
            job_error = getattr(self.job, "error", None)
        return {
            "kind": self.kind,
            "root_pid": self.root_pid,
            "process_group": self.process_group,
            "windows_job_attached": job_attached,
            "windows_job_error": job_error,
        }

    def close(self) -> None:
        job = self.job
        if job is None:
            return
        closer = getattr(job, "close", None)
        if callable(closer):
            closer()


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


def _snapshot_ignored_roots(repo_root: Path, run_root: Path) -> tuple[Path, ...]:
    """Evidence and pytest scratch must not look like source edits."""
    return (run_root, repo_root / ".tmp-pytest")


def capture_repo_snapshot(
    repo_root: Path,
    *,
    ignored_roots: Iterable[Path] = (),
) -> dict[str, Any]:
    """Capture HEAD plus a content-sensitive dirty fingerprint.

    ``run_root`` and ``<repo>/.tmp-pytest`` are excluded: evidence and local
    pytest scratch must not make a successful process appear to have changed
    sources.
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


def compose_gate_status(
    phase_statuses: Sequence[str],
    *,
    snapshot_matches: bool | None,
) -> tuple[str, str, list[str]]:
    """Compose overall evidence vs the actual pytest/command outcome.

    A missing snapshot must not become overall PASS (“stable source accepted”).
    The pytest outcome is retained separately even when overall evidence is
    UNVERIFIED.
    """

    reasons: list[str] = []
    if not phase_statuses:
        pytest_status = "UNVERIFIED"
        reasons.append("no phase completed")
    elif "UNVERIFIED" in phase_statuses:
        pytest_status = "UNVERIFIED"
    elif "FAIL" in phase_statuses:
        pytest_status = "FAIL"
    elif all(status == "PASS" for status in phase_statuses):
        pytest_status = "PASS"
    else:
        pytest_status = "UNVERIFIED"
        reasons.append(f"unrecognized phase statuses: {list(phase_statuses)}")

    if snapshot_matches is True:
        overall = pytest_status
    else:
        overall = "UNVERIFIED"
        if snapshot_matches is False:
            reasons.append(
                "HEAD or dirty content fingerprint changed while the gate ran"
            )
        else:
            reasons.append(
                "source snapshot unavailable; pytest outcome retained but overall evidence is UNVERIFIED"
            )
    return overall, pytest_status, reasons


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    delay = 0.05
    last_error: PermissionError | None = None
    for attempt in range(8):
        try:
            os.replace(temporary, path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt == 7:
                break
            time.sleep(delay)
            delay = min(delay * 2, 0.8)
    raise last_error


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

    Limits (also recorded on each run as ``preflight.limits``):

    * unknown cwd — macOS often hides cwd from ``ps``; ``lsof`` is best-effort.
      An unknown cwd is recorded by skipping the process, never guessed to be
      this checkout.
    * subdirectory — only an exact resolved cwd match to ``repo_root`` counts.
    * raced start — this is a point-in-time snapshot.  A pytest launched after
      the check is not detected.  This round does not implement a checkout mutex.
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
        except (ValueError, OSError):
            # Coordinator closed the pipe to bound EOF wait.
            pass
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
    events: Sequence[dict[str, Any]],
    phase_record: dict[str, Any],
    *,
    persist: Callable[[], None],
    failures_path: Path,
) -> bool:
    if not events:
        return False
    for event in events:
        nodeid = event.get("nodeid")
        phase = event.get("phase")
        if isinstance(nodeid, str) and nodeid:
            if phase in {"setup", "call", "teardown"} or "::" in nodeid:
                phase_record["current_node"] = nodeid
        if phase in {"setup", "call", "teardown", "collection"}:
            phase_record["current_phase"] = phase
        phase_record["last_progress_at"] = _utc_now()
        phase_record["event_count"] += 1
        if event.get("outcome") == "failed":
            failure = {
                "nodeid": event.get("nodeid"),
                "phase": event.get("phase"),
                "longrepr": event.get("longrepr"),
                "capstdout": event.get("capstdout"),
                "capstderr": event.get("capstderr"),
                "timestamp": event.get("timestamp"),
            }
            _append_jsonl(failures_path, failure)
            if phase_record.get("first_failure") is None:
                phase_record["first_failure"] = failure
            persist()
    return True


def windows_taskkill_command(root_pid: int, *, force: bool) -> list[str]:
    """Build a taskkill command for this invocation's root pid tree.

    The tree is identified by PID (``/PID`` + ``/T``), never by image name.
    """

    if not isinstance(root_pid, int) or root_pid <= 0:
        raise ValueError("windows cleanup requires this invocation's root pid")
    command = ["taskkill", "/PID", str(root_pid), "/T"]
    if force:
        command.append("/F")
    return command


class _WindowsJob:
    """Job object wrapping one owned Windows process tree."""

    def __init__(self, root_pid: int) -> None:
        self.root_pid = root_pid
        self.handle = None
        self.error: str | None = None
        if os.name != "nt":
            self.error = "windows job is not available on this platform"
            return
        try:
            self.handle = _windows_create_job_and_assign(root_pid)
        except OSError as exc:
            self.error = str(exc)
            self.handle = None

    def pids(self) -> list[int]:
        if self.handle is None:
            return []
        return _windows_job_pids(self.handle)

    def terminate(self) -> bool:
        if os.name != "nt" or self.handle is None:
            return False
        try:
            import ctypes

            return bool(ctypes.windll.kernel32.TerminateJobObject(self.handle, 1))
        except (OSError, AttributeError):
            return False

    def close(self) -> None:
        if os.name != "nt" or self.handle is None:
            self.handle = None
            return
        try:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self.handle)
        except (OSError, AttributeError):
            pass
        self.handle = None


def _windows_create_job_and_assign(root_pid: int) -> Any:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise OSError("CreateJobObjectW failed")

    job_object_extended_limit_information = 9
    job_object_limit_kill_on_job_close = 0x2000

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
    kernel32.SetInformationJobObject(
        handle,
        job_object_extended_limit_information,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )

    process_set_quota = 0x0100
    process_terminate = 0x0001
    process_query_information = 0x0400
    access = process_set_quota | process_terminate | process_query_information
    kernel32.OpenProcess.restype = wintypes.HANDLE
    process_handle = kernel32.OpenProcess(access, False, root_pid)
    if not process_handle:
        kernel32.CloseHandle(handle)
        raise OSError("OpenProcess failed for owned root pid")
    try:
        if not kernel32.AssignProcessToJobObject(handle, process_handle):
            kernel32.CloseHandle(handle)
            raise OSError("AssignProcessToJobObject failed")
    finally:
        kernel32.CloseHandle(process_handle)
    return handle


def _windows_job_pids(handle: Any) -> list[int]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    job_object_basic_process_id_list = 3
    count = 256
    header = 2 * ctypes.sizeof(wintypes.DWORD)
    length = header + count * ctypes.sizeof(ctypes.c_void_p)
    buf = ctypes.create_string_buffer(length)
    returned = wintypes.DWORD()
    ok = kernel32.QueryInformationJobObject(
        handle,
        job_object_basic_process_id_list,
        buf,
        length,
        ctypes.byref(returned),
    )
    if not ok:
        raise OSError("QueryInformationJobObject failed")
    in_list = int.from_bytes(buf.raw[4:8], sys.byteorder)
    pids: list[int] = []
    ptr_size = ctypes.sizeof(ctypes.c_void_p)
    for index in range(min(in_list, count)):
        start = 8 + index * ptr_size
        pids.append(int.from_bytes(buf.raw[start:start + ptr_size], sys.byteorder))
    return [pid for pid in pids if pid]


def _windows_toolhelp_snapshot_entries() -> list[tuple[int, int]]:
    """Return ``(pid, parent_pid)`` rows from CreateToolhelp32Snapshot.

    An unusable snapshot is an error, not an empty live set.
    """

    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    th32cs_snapprocess = 0x2

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (OSError, AttributeError, ImportError) as exc:
        raise OSError("kernel32 unavailable") from exc

    snapshot = kernel32.CreateToolhelp32Snapshot(th32cs_snapprocess, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise OSError("CreateToolhelp32Snapshot failed")
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    rows: list[tuple[int, int]] = []
    try:
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            pid = int(entry.th32ProcessID)
            if pid:
                rows.append((pid, int(entry.th32ParentProcessID)))
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    except (OSError, AttributeError, ValueError) as exc:
        raise OSError(f"CreateToolhelp32Snapshot walk failed: {exc}") from exc
    finally:
        kernel32.CloseHandle(snapshot)
    return rows


def _windows_process_tree_pids(root_pid: int) -> list[int]:
    """Best-effort parent-tree walk. Reparented children are lost without a job."""

    if os.name != "nt":
        return []
    children: dict[int, list[int]] = {}
    live: set[int] = set()
    for pid, ppid in _windows_toolhelp_snapshot_entries():
        live.add(pid)
        children.setdefault(ppid, []).append(pid)
    found: list[int] = []
    if root_pid in live:
        found.append(root_pid)
    stack = [root_pid]
    seen = {root_pid}
    while stack:
        current = stack.pop()
        for child in children.get(current, []):
            if child not in seen:
                seen.add(child)
                if child in live:
                    found.append(child)
                stack.append(child)
    return found


def _posix_owned_live_records(pgid: int) -> list[dict[str, Any]]:
    try:
        listing = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,pgid=,stat=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if listing.returncode != 0:
        return []
    records: list[dict[str, Any]] = []
    for line in listing.stdout.splitlines():
        fields = line.strip().split(None, 4)
        if len(fields) < 4:
            continue
        pid_text, ppid_text, pgid_text, stat = fields[:4]
        command = fields[4] if len(fields) > 4 else ""
        try:
            pid = int(pid_text)
            ppid = int(ppid_text)
            group = int(pgid_text)
        except ValueError:
            continue
        if group != pgid or str(stat).startswith("Z"):
            continue
        records.append(
            {
                "pid": pid,
                "ppid": ppid,
                "pgid": group,
                "stat": stat,
                "command": command,
            }
        )
    return records


def _list_owned_processes(
    owned_tree: OwnedProcessTree | None,
    process: subprocess.Popen[str] | Any | None,
) -> list[dict[str, Any]]:
    if owned_tree is None and process is None:
        return []
    root_pid = owned_tree.root_pid if owned_tree is not None else int(process.pid)
    process_group = owned_tree.process_group if owned_tree is not None else None
    if os.name == "posix":
        pgid = process_group if process_group is not None else root_pid
        return _posix_owned_live_records(pgid)

    pids: list[int] = []
    job = owned_tree.job if owned_tree is not None else None
    job_query_failed: OSError | None = None
    job_attached = job is not None and getattr(job, "handle", None) is not None
    if job_attached:
        try:
            pids = [pid for pid in job.pids() if pid]
        except OSError as exc:
            job_query_failed = exc
    if pids:
        return [{"pid": pid, "root_pid": root_pid, "command": ""} for pid in pids]
    try:
        pids = _windows_process_tree_pids(root_pid)
    except OSError as exc:
        detail = job_query_failed if job_query_failed is not None else exc
        prefix = (
            "windows job query failed"
            if job_query_failed is not None
            else "windows process snapshot failed"
        )
        return [{"root_pid": root_pid, "command": "", "error": f"{prefix}: {detail}"}]
    if pids:
        return [{"pid": pid, "root_pid": root_pid, "command": ""} for pid in pids]
    if job_query_failed is not None:
        return [
            {
                "root_pid": root_pid,
                "command": "",
                "error": f"windows job query failed: {job_query_failed}",
            }
        ]
    return []


def _build_owned_tree(process: subprocess.Popen[str]) -> OwnedProcessTree:
    if os.name == "posix":
        try:
            process_group = os.getpgid(process.pid)
        except OSError:
            process_group = process.pid
        return OwnedProcessTree(
            kind="posix-process-group",
            root_pid=process.pid,
            process_group=process_group,
            job=None,
        )
    job = _WindowsJob(process.pid)
    kind = "windows-job" if job.handle is not None else "windows-process-tree"
    return OwnedProcessTree(
        kind=kind,
        root_pid=process.pid,
        process_group=None,
        job=job,
    )


def _wait_for_owned_exit(
    owned_tree: OwnedProcessTree,
    process: subprocess.Popen[str] | Any,
    deadline: float,
) -> None:
    while time.monotonic() < deadline:
        live = _list_owned_processes(owned_tree, process)
        if not live and process.poll() is not None:
            return
        time.sleep(0.02)


def _terminate_owned_process_group(
    process: subprocess.Popen[str] | Any,
    *,
    process_group: int | None,
    grace_seconds: float,
    owned_tree: OwnedProcessTree | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Stop only the process group/tree created by this runner invocation.

    The parent Popen handle exiting is not sufficient: descendants in the
    owned group/tree are reaped too.  Never terminates by process name.
    """

    actions: list[str] = []
    if owned_tree is None:
        if os.name == "posix":
            if process_group is None:
                raise RuntimeError("POSIX watchdog missing its owned process group")
            owned_tree = OwnedProcessTree(
                kind="posix-process-group",
                root_pid=int(process.pid),
                process_group=process_group,
                job=None,
            )
        else:
            owned_tree = OwnedProcessTree(
                kind="windows-process-tree",
                root_pid=int(process.pid),
                process_group=None,
                job=None,
            )

    if os.name == "posix":
        pgid = owned_tree.process_group
        if pgid is None:
            raise RuntimeError("POSIX watchdog missing its owned process group")
        live = _posix_owned_live_records(pgid)
        if not live and process.poll() is not None:
            return actions, []
        try:
            os.killpg(pgid, signal.SIGTERM)
            actions.append(f"SIGTERM process group {pgid}")
        except ProcessLookupError:
            pass
        _wait_for_owned_exit(owned_tree, process, time.monotonic() + grace_seconds)
        live = _posix_owned_live_records(pgid)
        if live:
            try:
                os.killpg(pgid, signal.SIGKILL)
                actions.append(f"SIGKILL process group {pgid}")
            except ProcessLookupError:
                pass
            for record in live:
                try:
                    os.kill(int(record["pid"]), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    continue
            _wait_for_owned_exit(
                owned_tree,
                process,
                time.monotonic() + max(0.2, min(1.0, grace_seconds)),
            )
        leftover = _posix_owned_live_records(pgid)
        if leftover:
            actions.append("owned processes still running after termination budget")
        if process.poll() is None:
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                actions.append("owned process still running after termination budget")
        return actions, leftover

    root_pid = owned_tree.root_pid
    live = _list_owned_processes(owned_tree, process)
    graceful = windows_taskkill_command(root_pid, force=False)
    try:
        completed = subprocess.run(
            graceful,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(2.0, grace_seconds + 1.0),
        )
        actions.append(" ".join(graceful) + f" exit={completed.returncode}")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        actions.append(f"taskkill unavailable: {exc}")
    _wait_for_owned_exit(owned_tree, process, time.monotonic() + grace_seconds)
    live = _list_owned_processes(owned_tree, process)
    if live or process.poll() is None:
        forced = windows_taskkill_command(root_pid, force=True)
        try:
            completed = subprocess.run(
                forced,
                check=False,
                capture_output=True,
                text=True,
                timeout=max(2.0, grace_seconds + 1.0),
            )
            actions.append(" ".join(forced) + f" exit={completed.returncode}")
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            actions.append(f"taskkill unavailable: {exc}")
            try:
                process.kill()
                actions.append(f"kill owned process {root_pid}")
            except OSError:
                pass
        job = owned_tree.job
        if job is not None and job.terminate():
            actions.append(f"TerminateJobObject owned job for pid {root_pid}")
        _wait_for_owned_exit(
            owned_tree,
            process,
            time.monotonic() + max(0.2, min(1.0, grace_seconds)),
        )
    leftover = _list_owned_processes(owned_tree, process)
    if leftover:
        actions.append("owned processes still running after termination budget")
    if process.poll() is None:
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            actions.append("owned process still running after termination budget")
    return actions, leftover


def _request_stack_dump(
    request_path: Path,
    output_path: Path,
    *,
    wait_seconds: float = 0.25,
) -> str:
    """Ask the owned pytest process to dump stacks. Does not terminate anyone."""

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as stream:
            stream.write(f"----- python stack dump requested t={time.time()} -----\n")
        request_path.write_text("dump\n", encoding="utf-8")
        previous_size = output_path.stat().st_size
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if output_path.exists() and output_path.stat().st_size > previous_size:
                break
            time.sleep(0.02)
        return output_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"stack dump unavailable: {exc}"


def _process_snapshot_text(pids: Sequence[int]) -> str:
    if not pids:
        return ""
    try:
        ps_result = subprocess.run(
            [
                "ps",
                "-o",
                "pid=,ppid=,pgid=,etime=,state=,rss=,command=",
                "-p",
                ",".join(str(pid) for pid in pids),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (ps_result.stdout + ps_result.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return f"ps unavailable: {exc}"


def _diagnostic_payload(
    *,
    process: subprocess.Popen[str],
    process_group: int | None,
    reason: str,
    elapsed_seconds: float,
    phase_record: dict[str, Any],
    output_tail: Sequence[str],
    owned_live_processes: Sequence[dict[str, Any]] | None = None,
    python_stack_dump: str | None = None,
) -> dict[str, Any]:
    live = list(owned_live_processes or [])
    pids = [int(item["pid"]) for item in live if item.get("pid") is not None]
    if not pids:
        pids = [process.pid]
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
        "first_failure": phase_record.get("first_failure"),
        "owned_live_processes": live,
        "python_stack_dump": python_stack_dump or "",
        "process_snapshot": _process_snapshot_text(pids),
        "output_tail": list(output_tail),
    }


def _phase_status(
    *,
    returncode: int | None,
    hard_timeout: bool,
    interrupted: bool,
    leftover_processes: Sequence[dict[str, Any]] | None = None,
    parent_exited_with_descendants: bool = False,
    output_reader_join_timed_out: bool = False,
) -> str:
    if (
        hard_timeout
        or interrupted
        or leftover_processes
        or parent_exited_with_descendants
        or output_reader_join_timed_out
    ):
        return "UNVERIFIED"
    if returncode == 0:
        return "PASS"
    if returncode == 1:
        return "FAIL"
    return "UNVERIFIED"


def _close_stdout(process: subprocess.Popen[str]) -> None:
    stdout = process.stdout
    if stdout is None:
        return
    try:
        stdout.close()
    except OSError:
        return


def _run_phase(
    phase: PhaseCommand,
    *,
    cwd: Path,
    phase_dir: Path,
    soft_timeout_seconds: float,
    hard_timeout_seconds: float,
    heartbeat_seconds: float,
    terminate_grace_seconds: float,
    output_reader_join_seconds: float,
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
    descendant_diagnostic_path = phase_dir / "descendants-after-parent-exit.json"
    failures_path = phase_dir / "failures.jsonl"
    stack_request_path = phase_dir / "stack-dump.request"
    stack_dump_path = phase_dir / "stack-dump.txt"

    env = os.environ.copy()
    env["TEST_GATE_STACK_DUMP_REQUEST"] = str(stack_request_path)
    env["TEST_GATE_STACK_DUMP_FILE"] = str(stack_dump_path)
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
        "owned_tree": None,
        "pytest_event_plugin": has_pytest_events,
        "current_node": None,
        "current_phase": None,
        "last_progress_at": None,
        "event_count": 0,
        "first_failure": None,
        "soft_deadline_exceeded": False,
        "hard_deadline_exceeded": False,
        "interrupted": False,
        "parent_exited_with_descendants": False,
        "output_reader_join_timed_out": False,
        "termination_actions": [],
        "leftover_processes": [],
        "exit_code": None,
        "status": "RUNNING",
        "artifacts": {
            "output": str(output_path),
            "events": str(event_path),
            "heartbeats": str(heartbeat_path),
            "failures": str(failures_path),
            "stack_dump": str(stack_dump_path),
            "soft_diagnostic": str(soft_diagnostic_path),
            "hard_diagnostic": str(hard_diagnostic_path),
            "interrupt_diagnostic": str(interrupt_diagnostic_path),
            "descendant_leak_diagnostic": str(descendant_diagnostic_path),
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

    owned_tree = _build_owned_tree(process)
    process_group = owned_tree.process_group
    phase_record["pid"] = process.pid
    phase_record["owned_process_group"] = (
        process_group if process_group is not None else process.pid
    )
    phase_record["owned_tree"] = owned_tree.as_record()
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
    cleanup_started = False
    parent_exit_checked = False
    reader_deadline: float | None = None

    def write_diagnostic(path: Path, reason: str, elapsed_seconds: float, *, dump_stacks: bool) -> None:
        stacks = ""
        if dump_stacks:
            stacks = _request_stack_dump(stack_request_path, stack_dump_path)
        payload = _diagnostic_payload(
            process=process,
            process_group=process_group,
            reason=reason,
            elapsed_seconds=elapsed_seconds,
            phase_record=phase_record,
            output_tail=output_tail,
            owned_live_processes=_list_owned_processes(owned_tree, process),
            python_stack_dump=stacks,
        )
        _write_json(path, payload)

    def begin_cleanup(reason: str, diagnostic_path: Path, elapsed_seconds: float, *, dump_stacks: bool) -> None:
        nonlocal cleanup_started, reader_deadline
        write_diagnostic(diagnostic_path, reason, elapsed_seconds, dump_stacks=dump_stacks)
        if not cleanup_started:
            cleanup_started = True
            actions, leftover = _terminate_owned_process_group(
                process,
                process_group=process_group,
                grace_seconds=terminate_grace_seconds,
                owned_tree=owned_tree,
            )
            phase_record["termination_actions"] = list(actions)
            phase_record["leftover_processes"] = leftover
        if reader_deadline is None:
            reader_deadline = time.monotonic() + output_reader_join_seconds
        persist()

    def stop_for_interrupt(elapsed_seconds: float) -> None:
        nonlocal interrupted
        if interrupted:
            return
        interrupted = True
        phase_record["interrupted"] = True
        begin_cleanup(
            "gate coordinator interrupted; stopping owned process group",
            interrupt_diagnostic_path,
            elapsed_seconds,
            dump_stacks=True,
        )

    try:
        with output_path.open("w", encoding="utf-8", buffering=1) as output:
            while True:
              try:
                reader_closed = _drain_output(lines, output, output_tail, phase_record) or reader_closed
                progress_changed = _apply_events(
                    event_reader.read(),
                    phase_record,
                    persist=persist,
                    failures_path=failures_path,
                )
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
                        write_diagnostic(
                            soft_diagnostic_path,
                            "soft deadline exceeded; process left running",
                            elapsed,
                            dump_stacks=True,
                        )
                        soft_recorded = True
                        persist()

                    if not hard_recorded and elapsed >= hard_timeout_seconds:
                        phase_record["hard_deadline_exceeded"] = True
                        hard_recorded = True
                        begin_cleanup(
                            "hard deadline exceeded; stopping owned process group",
                            hard_diagnostic_path,
                            elapsed,
                            dump_stacks=True,
                        )
                except KeyboardInterrupt:
                    stop_for_interrupt(elapsed)

                parent_exited = process.poll() is not None
                if parent_exited and not parent_exit_checked:
                    parent_exit_checked = True
                    live = _list_owned_processes(owned_tree, process)
                    if live:
                        phase_record["parent_exited_with_descendants"] = True
                        begin_cleanup(
                            "parent exited with owned descendants still running",
                            descendant_diagnostic_path,
                            elapsed,
                            dump_stacks=True,
                        )
                    if reader_deadline is None:
                        reader_deadline = time.monotonic() + output_reader_join_seconds

                if reader_deadline is not None and time.monotonic() >= reader_deadline:
                    if not reader_closed:
                        phase_record["output_reader_join_timed_out"] = True
                        _close_stdout(process)
                        reader_closed = (
                            _drain_output(lines, output, output_tail, phase_record)
                            or reader_closed
                        )
                        persist()

                bounded_exit = bool(
                    parent_exited or cleanup_started
                ) and (
                    reader_closed or phase_record.get("output_reader_join_timed_out")
                )
                if bounded_exit:
                    live = _list_owned_processes(owned_tree, process)
                    if live and not cleanup_started:
                        phase_record["parent_exited_with_descendants"] = True
                        begin_cleanup(
                            "parent exited with owned descendants still running",
                            descendant_diagnostic_path,
                            elapsed,
                            dump_stacks=True,
                        )
                        live = _list_owned_processes(owned_tree, process)
                    if live:
                        phase_record["leftover_processes"] = live
                    _apply_events(
                        event_reader.read(),
                        phase_record,
                        persist=persist,
                        failures_path=failures_path,
                    )
                    break
                try:
                    time.sleep(0.02)
                except KeyboardInterrupt:
                    stop_for_interrupt(time.monotonic() - started_monotonic)
              except KeyboardInterrupt:
                stop_for_interrupt(time.monotonic() - started_monotonic)
    finally:
        reader_thread.join(timeout=output_reader_join_seconds)
        if reader_thread.is_alive():
            phase_record["output_reader_join_timed_out"] = True
            _close_stdout(process)
            reader_thread.join(timeout=0.2)
        leftover = _list_owned_processes(owned_tree, process)
        if leftover:
            phase_record["leftover_processes"] = leftover
            if not cleanup_started:
                actions, leftover = _terminate_owned_process_group(
                    process,
                    process_group=process_group,
                    grace_seconds=min(terminate_grace_seconds, 0.5),
                    owned_tree=owned_tree,
                )
                phase_record["termination_actions"] = list(actions)
                phase_record["leftover_processes"] = leftover
                phase_record["parent_exited_with_descendants"] = True
        owned_tree.close()

    phase_record["exit_code"] = process.poll()
    phase_record["ended_at"] = _utc_now()
    phase_record["elapsed_seconds"] = round(time.monotonic() - started_monotonic, 3)
    phase_record["status"] = _phase_status(
        returncode=phase_record["exit_code"],
        hard_timeout=hard_recorded,
        interrupted=interrupted,
        leftover_processes=phase_record.get("leftover_processes"),
        parent_exited_with_descendants=bool(
            phase_record.get("parent_exited_with_descendants")
        ),
        output_reader_join_timed_out=bool(
            phase_record.get("output_reader_join_timed_out")
        ),
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
    output_reader_join_seconds: float = 2.0,
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
    if output_reader_join_seconds <= 0:
        raise ValueError("output_reader_join_seconds must be positive")

    cwd = cwd.resolve()
    repo_root = repo_root.resolve()
    if run_root is None:
        run_root = repo_root / ".state" / "test-runs"
    run_root = run_root.resolve()
    run_dir = run_root / _new_run_id()
    run_dir.mkdir(parents=True, exist_ok=False)
    record_path = run_dir / "run.json"
    record: dict[str, Any] = {
        "schema_version": 2,
        "run_id": run_dir.name,
        "status": "RUNNING",
        "pytest_status": None,
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
            "output_reader_join_seconds": output_reader_join_seconds,
        },
        "commands": [
            {"name": phase.name, "command": list(phase.command)} for phase in phases
        ],
        "snapshot_before": capture_repo_snapshot(
            repo_root, ignored_roots=_snapshot_ignored_roots(repo_root, run_root)
        ),
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
        "limits": dict(PREFLIGHT_LIMITS),
    }
    persist()
    if same_checkout:
        record["status"] = "UNVERIFIED"
        record["pytest_status"] = "UNVERIFIED"
        record["unverified_reasons"].append(
            "refused to overlap an existing pytest process in this checkout"
        )
        record["snapshot_after"] = capture_repo_snapshot(
            repo_root, ignored_roots=_snapshot_ignored_roots(repo_root, run_root)
        )
        record["ended_at"] = _utc_now()
        persist()
        return GateResult("UNVERIFIED", record_path, 2)

    try:
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
                output_reader_join_seconds=output_reader_join_seconds,
                register_phase=record["phases"].append,
                persist=persist,
            )
            persist()
            if phase_record["status"] == "UNVERIFIED" and not continue_after_unverified:
                record["unverified_reasons"].append(
                    f"phase {phase.name!r} was unverified; later phases were not started"
                )
                break
    except KeyboardInterrupt:
        record["unverified_reasons"].append("gate coordinator interrupted")
        for phase_record in record["phases"]:
            if phase_record.get("status") == "RUNNING":
                phase_record["status"] = "UNVERIFIED"
                phase_record["interrupted"] = True

    record["snapshot_after"] = capture_repo_snapshot(
        repo_root, ignored_roots=_snapshot_ignored_roots(repo_root, run_root)
    )
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

    phase_statuses = [phase["status"] for phase in record["phases"]]
    overall, pytest_status, snapshot_reasons = compose_gate_status(
        phase_statuses,
        snapshot_matches=snapshot_matches,
    )
    record["pytest_status"] = pytest_status
    for reason in snapshot_reasons:
        if reason not in record["unverified_reasons"]:
            record["unverified_reasons"].append(reason)
    record["status"] = overall
    record["ended_at"] = _utc_now()
    persist()
    exit_code = 0 if overall == "PASS" else 1 if overall == "FAIL" else 2
    return GateResult(overall, record_path, exit_code)


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
    parser.add_argument("--output-reader-join-seconds", type=float, default=2.0)
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
            output_reader_join_seconds=args.output_reader_join_seconds,
            continue_after_unverified=args.continue_after_unverified,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(f"{result.status}: {result.record_path}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
