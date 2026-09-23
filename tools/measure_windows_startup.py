#!/usr/bin/env python3
"""Measure application startup stages for source or Windows EXE targets.

This tool owns the external monotonic clock. Process-local marks written by
``mf4_analyzer.startup_timing`` must not be subtracted from tool timestamps.

On macOS the default target is the source launcher / ``python -m mf4_analyzer.app``.
Pass ``--exe`` later for a Windows frozen binary; do not treat macOS source
timings as a Windows EXE baseline.

Outputs one run under ``.state/startup-perf/<run-id>/`` (gitignored).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERF_ROOT = ROOT / ".state" / "startup-perf"
SOURCE_LAUNCHER = ROOT / "MF4 Data Analyzer V1.py"

REQUIRED_APP_STAGES = (
    "python_entry",
    "gui_modules_imported",
    "qapplication_ready",
    "mainwindow_constructed",
    "first_frame",
)

RELATED_PATHS = (
    "MF4 Data Analyzer V1.py",
    "mf4_analyzer/app.py",
    "mf4_analyzer/startup_timing.py",
    "mf4_analyzer/startup_feedback.py",
    "tools/measure_windows_startup.py",
)

FEEDBACK_ROLE = "feedback"
FEEDBACK_ACK_ROLE = "feedback_ack"
INTERACTIVE_CMD = "interactive_probe"


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def evaluate_run_outcome(
    *,
    exit_code: int | None,
    timed_out: bool,
    marks: list[dict[str, Any]],
    interactive_received: bool,
    run_id: str,
    marks_run_id: str | None,
    splash_required: bool = False,
    splash_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if timed_out:
        return {"ok": False, "error": "startup measurement timed out"}
    if exit_code is None:
        return {"ok": False, "error": "process exit code missing"}
    if exit_code != 0:
        return {
            "ok": False,
            "error": f"process exited with non-zero code {exit_code}",
        }
    if marks_run_id is not None and marks_run_id != run_id:
        return {
            "ok": False,
            "error": (
                f"run-id mismatch: tool={run_id!r} marks={marks_run_id!r}"
            ),
        }
    if not marks:
        return {"ok": False, "error": "missing startup marks"}
    present = {str(row.get("stage")) for row in marks}
    missing = [name for name in REQUIRED_APP_STAGES if name not in present]
    if missing:
        return {
            "ok": False,
            "error": f"missing required marks: {', '.join(missing)}",
        }
    if not interactive_received:
        return {
            "ok": False,
            "error": "interactive probe response was not received",
        }
    if splash_required:
        events = list(splash_events or [])
        feedback_names = {
            str(row.get("event"))
            for row in events
            if row.get("ok") and row.get("role") == FEEDBACK_ROLE
        }
        if "splash_painted" not in feedback_names:
            return {
                "ok": False,
                "error": "splash_painted feedback was not received",
            }
    return {"ok": True, "error": None}


def send_interactive_probe(
    host: str,
    port: int,
    *,
    token: str,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Send a queued interactive probe and stamp receipt on the tool clock."""

    deadline = time.perf_counter() + timeout_s
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(min(2.0, timeout_s))
    try:
        while True:
            try:
                sock.connect((host, port))
                break
            except OSError:
                if time.perf_counter() >= deadline:
                    raise
                time.sleep(0.02)
                sock.close()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(min(2.0, max(0.05, deadline - time.perf_counter())))
        payload = json.dumps({"cmd": INTERACTIVE_CMD, "token": token}) + "\n"
        sent_ns = time.perf_counter_ns()
        sock.sendall(payload.encode("utf-8"))
        sock.settimeout(max(0.05, deadline - time.perf_counter()))
        chunks: list[bytes] = []
        while True:
            piece = sock.recv(4096)
            if not piece:
                break
            chunks.append(piece)
            if b"\n" in piece:
                break
        received_ns = time.perf_counter_ns()
        raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
        body = json.loads(raw.splitlines()[0]) if raw else {}
        ok = bool(body.get("ok")) and body.get("token") == token
        # Interactive responses must not be mistaken for feedback pushes.
        if body.get("role") == FEEDBACK_ROLE:
            ok = False
        return {
            "ok": ok,
            "role": "interactive",
            "token": token,
            "tool_mono_ns_sent": sent_ns,
            "tool_mono_ns_received": received_ns,
            "observation_overhead_ns": max(0, received_ns - sent_ns),
            "interactive_clock": "tool",
            "response": body,
        }
    finally:
        sock.close()


def probe_wait_for_input_idle(pid: int, timeout_ms: int = 5000) -> dict[str, Any]:
    """Auxiliary Windows-only signal. Never pretend success on macOS."""

    if not sys.platform.startswith("win"):
        return {
            "available": False,
            "ok": False,
            "reason": "WaitForInputIdle unavailable outside Windows",
            "pid": pid,
        }
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x00100000
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not handle:
            return {
                "available": True,
                "ok": False,
                "reason": "OpenProcess failed",
                "pid": pid,
            }
        try:
            # WaitForInputIdle wants a process handle opened with SYNCHRONIZE|
            # PROCESS_QUERY_INFORMATION typically; treat failure as auxiliary miss.
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32.CloseHandle(handle)
            handle = kernel32.OpenProcess(
                SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
            )
            if not handle:
                return {
                    "available": True,
                    "ok": False,
                    "reason": "OpenProcess(query) failed",
                    "pid": pid,
                }
            result = int(user32.WaitForInputIdle(handle, int(timeout_ms)))
            return {
                "available": True,
                "ok": result == 0,
                "result": result,
                "pid": pid,
                "reason": None if result == 0 else f"WaitForInputIdle returned {result}",
            }
        finally:
            if handle:
                kernel32.CloseHandle(handle)
    except Exception as exc:  # auxiliary only
        return {
            "available": True,
            "ok": False,
            "reason": f"WaitForInputIdle probe failed: {exc}",
            "pid": pid,
        }


def _git_head() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dirty_hashes() -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in RELATED_PATHS:
        digest = _file_sha256(ROOT / rel)
        if digest is not None:
            out[rel] = digest
    return out


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {"python": sys.version.split()[0]}
    for name in ("PyQt5", "pyqtgraph", "numpy", "pandas"):
        try:
            mod = __import__(name)
        except Exception:
            versions[name] = "unavailable"
            continue
        versions[name] = str(getattr(mod, "__version__", "unknown"))
    return versions


def _machine_info() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
    }


def _read_marks(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            rows.append(json.loads(text))
        except json.JSONDecodeError:
            rows.append({"stage": "_invalid_json", "raw": text})
    return rows


def _marks_run_id(marks: list[dict[str, Any]]) -> str | None:
    for row in marks:
        value = row.get("run_id")
        if value:
            return str(value)
    return None


class _ProbeServer:
    """Accept feedback pushes and one interactive app connection.

    Feedback clients push a JSON line with ``role=feedback`` immediately.
    The main-window interactive client connects and waits for the tool to send
    ``interactive_probe``. The two roles are never mixed on one socket.
    """

    def __init__(self, *, expected_run_id: str) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(8)
        self._server.settimeout(0.05)
        self.host, self.port = self._server.getsockname()
        self.expected_run_id = str(expected_run_id)
        self.conn: socket.socket | None = None
        self.feedback_events: list[dict[str, Any]] = []

    def poll(self) -> None:
        """Accept pending connections; classify feedback vs interactive."""

        while True:
            try:
                conn, _addr = self._server.accept()
            except socket.timeout:
                return
            except OSError:
                return
            accepted_ns = time.perf_counter_ns()
            conn.settimeout(0.15)
            try:
                # Feedback peers send first; interactive peers stay silent.
                data = conn.recv(4096)
            except socket.timeout:
                data = b""
            except OSError:
                try:
                    conn.close()
                except OSError:
                    pass
                continue
            if data:
                self._ingest_feedback_push(conn, data, accepted_ns=accepted_ns)
                continue
            if self.conn is None:
                try:
                    conn.settimeout(None)
                except OSError:
                    pass
                self.conn = conn
            else:
                try:
                    conn.close()
                except OSError:
                    pass

    def accept_ready(self) -> bool:
        """Compatibility shim: poll once; True when interactive conn is held."""

        self.poll()
        return self.conn is not None

    def _ingest_feedback_push(
        self,
        conn: socket.socket,
        data: bytes,
        *,
        accepted_ns: int,
    ) -> None:
        received_ns = time.perf_counter_ns()
        transport_overhead_ns = max(0, received_ns - accepted_ns)
        raw = data.decode("utf-8", errors="replace").strip()
        body: dict[str, Any] = {}
        try:
            body = json.loads(raw.splitlines()[0]) if raw else {}
        except json.JSONDecodeError:
            body = {}
        ok = (
            isinstance(body, dict)
            and body.get("role") == FEEDBACK_ROLE
            and str(body.get("run_id") or "") == self.expected_run_id
            and str(body.get("event") or "")
            in {"splash_painted", "splash_closed"}
        )
        # Never derive launch-to-splash from parent_mono_ns vs tool clocks.
        parent_mono = body.get("parent_mono_ns") if isinstance(body, dict) else None
        event_row = {
            "ok": ok,
            "role": FEEDBACK_ROLE,
            "event": body.get("event") if isinstance(body, dict) else None,
            "run_id": body.get("run_id") if isinstance(body, dict) else None,
            "session": body.get("session") if isinstance(body, dict) else None,
            "tool_mono_ns_accepted": accepted_ns,
            "tool_mono_ns_received": received_ns,
            "transport_overhead_ns": transport_overhead_ns,
            "feedback_clock": "tool",
            "parent_mono_ns_reported": parent_mono,
            "payload": body if isinstance(body, dict) else {"raw": raw},
        }
        self.feedback_events.append(event_row)
        try:
            ack = {
                "role": FEEDBACK_ACK_ROLE,
                "ok": ok,
                "event": event_row["event"],
                "run_id": self.expected_run_id,
            }
            conn.sendall(
                (json.dumps(ack, ensure_ascii=False) + "\n").encode("utf-8")
            )
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass

    def drain_feedback(self) -> list[dict[str, Any]]:
        events, self.feedback_events = self.feedback_events, []
        return events

    def send_probe(self, token: str, timeout_s: float) -> dict[str, Any]:
        deadline = time.perf_counter() + timeout_s
        while self.conn is None:
            if time.perf_counter() >= deadline:
                return {
                    "ok": False,
                    "role": "interactive",
                    "error": "timed out waiting for app probe connection",
                    "interactive_clock": "tool",
                }
            self.poll()
            time.sleep(0.01)
        assert self.conn is not None
        payload = json.dumps({"cmd": INTERACTIVE_CMD, "token": token}) + "\n"
        sent_ns = time.perf_counter_ns()
        self.conn.settimeout(max(0.05, deadline - time.perf_counter()))
        self.conn.sendall(payload.encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            piece = self.conn.recv(4096)
            if not piece:
                break
            chunks.append(piece)
            if b"\n" in piece:
                break
        received_ns = time.perf_counter_ns()
        raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
        body = json.loads(raw.splitlines()[0]) if raw else {}
        ok = bool(body.get("ok")) and body.get("token") == token
        if body.get("role") == FEEDBACK_ROLE:
            ok = False
        return {
            "ok": ok,
            "role": "interactive",
            "token": token,
            "tool_mono_ns_sent": sent_ns,
            "tool_mono_ns_received": received_ns,
            "observation_overhead_ns": max(0, received_ns - sent_ns),
            "interactive_clock": "tool",
            "response": body,
        }

    def close(self) -> None:
        try:
            if self.conn is not None:
                self.conn.close()
        finally:
            self._server.close()


def stamp_feedback_message(
    body: dict[str, Any],
    *,
    expected_run_id: str,
    accepted_ns: int | None = None,
    received_ns: int | None = None,
) -> dict[str, Any]:
    """Pure helper for unit tests: validate feedback and stamp tool clocks."""

    accepted = int(accepted_ns if accepted_ns is not None else time.perf_counter_ns())
    received = int(received_ns if received_ns is not None else time.perf_counter_ns())
    ok = (
        isinstance(body, dict)
        and body.get("role") == FEEDBACK_ROLE
        and str(body.get("run_id") or "") == str(expected_run_id)
        and str(body.get("event") or "") in {"splash_painted", "splash_closed"}
    )
    return {
        "ok": ok,
        "role": FEEDBACK_ROLE,
        "event": body.get("event"),
        "run_id": body.get("run_id"),
        "session": body.get("session"),
        "tool_mono_ns_accepted": accepted,
        "tool_mono_ns_received": received,
        "transport_overhead_ns": max(0, received - accepted),
        "feedback_clock": "tool",
        "parent_mono_ns_reported": body.get("parent_mono_ns"),
        "payload": body,
    }


def build_command(
    *,
    package_type: str,
    exe: Path | None,
    python_exe: Path,
) -> list[str]:
    if package_type == "exe":
        if exe is None:
            raise SystemExit("--exe is required when --package-type exe")
        return [str(exe)]
    # Source: prefer the Windows-oriented launcher path so timing matches packaging.
    return [str(python_exe), str(SOURCE_LAUNCHER)]


def run_once(
    *,
    run_id: str,
    perf_root: Path,
    package_type: str,
    exe: Path | None,
    python_exe: Path,
    timeout_s: float,
    qt_platform: str | None,
    splash_mode: str = "auto",
) -> dict[str, Any]:
    run_dir = perf_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    marks_path = run_dir / "marks.jsonl"
    tool_timeline_path = run_dir / "tool_timeline.jsonl"
    summary_path = run_dir / "summary.json"
    meta_path = run_dir / "meta.json"

    probe_server = _ProbeServer(expected_run_id=run_id)
    token = uuid.uuid4().hex
    timeline: list[dict[str, Any]] = []
    splash_events: list[dict[str, Any]] = []

    def note(event: str, **extra: Any) -> None:
        row = {"event": event, "tool_mono_ns": time.perf_counter_ns(), **extra}
        timeline.append(row)
        with tool_timeline_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    meta = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "head": _git_head(),
        "dirty_file_sha256": _dirty_hashes(),
        "dependency_versions": _dependency_versions(),
        "package_type": package_type,
        "exe": str(exe) if exe is not None else None,
        "machine": _machine_info(),
        "params": {
            "timeout_s": timeout_s,
            "qt_platform": qt_platform,
            "python_exe": str(python_exe),
            "probe_host": probe_server.host,
            "probe_port": probe_server.port,
            "splash_mode": splash_mode,
        },
        "notes": (
            "macOS source/offscreen runs are not a Windows EXE baseline. "
            "Splash first-visible times require tool-clock receipt of feedback "
            "events (or screen capture); never parent_mono_ns − child_mono_ns."
            if package_type == "source"
            else "Windows EXE measurement."
        ),
        "windows_frozen_status": "UNKNOWN",
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    env = os.environ.copy()
    env["TRACELAB_STARTUP_TIMING"] = "1"
    env["TRACELAB_STARTUP_RUN_ID"] = run_id
    env["TRACELAB_STARTUP_PERF_DIR"] = str(perf_root)
    env["TRACELAB_STARTUP_PROBE_HOST"] = probe_server.host
    env["TRACELAB_STARTUP_PROBE_PORT"] = str(probe_server.port)
    env["TRACELAB_STARTUP_EXIT_AFTER_PROBE"] = "1"
    env["TRACELAB_STARTUP_SPLASH"] = str(splash_mode)
    env.setdefault("PYTHONPATH", str(ROOT))
    if qt_platform:
        env["QT_QPA_PLATFORM"] = qt_platform
    env.setdefault("TMPDIR", "/tmp")
    env.setdefault("MPLCONFIGDIR", "/tmp")

    command = build_command(
        package_type=package_type, exe=exe, python_exe=python_exe
    )
    note("launcher_spawn_requested", command=command)
    spawn_ns = time.perf_counter_ns()
    timed_out = False
    exit_code: int | None = None
    proc: subprocess.Popen[str] | None = None
    interactive: dict[str, Any] | None = None
    wait_idle: dict[str, Any] | None = None
    stdout = ""
    stderr = ""
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        note("launcher_spawned", pid=proc.pid, tool_mono_ns_spawn=spawn_ns)
        wait_idle = probe_wait_for_input_idle(proc.pid)
        note("wait_for_input_idle", **wait_idle)

        deadline = time.perf_counter() + timeout_s
        saw_first_frame = False
        while time.perf_counter() < deadline:
            # Poll feedback pushes early — do not wait for first_frame.
            probe_server.poll()
            for feedback in probe_server.drain_feedback():
                splash_events.append(feedback)
                note("splash_feedback_received", **feedback)
            marks = _read_marks(marks_path)
            stages = {str(row.get("stage")) for row in marks}
            if "first_frame" in stages and not saw_first_frame:
                saw_first_frame = True
                note("first_frame_observed")
                interactive = probe_server.send_probe(
                    token, timeout_s=max(0.5, deadline - time.perf_counter())
                )
                note("interactive_probe_finished", **interactive)
            if proc.poll() is not None:
                break
            time.sleep(0.02)
        else:
            timed_out = True
            if proc.poll() is None:
                proc.kill()
        stdout, stderr = proc.communicate(timeout=max(1.0, timeout_s))
        exit_code = proc.returncode
    except Exception as exc:
        note("measurement_exception", error=str(exc))
        if proc is not None and proc.poll() is None:
            proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except Exception:
                stdout, stderr = "", str(exc)
            exit_code = proc.returncode
        else:
            stderr = str(exc)
            if exit_code is None:
                exit_code = -1
    finally:
        probe_server.poll()
        for feedback in probe_server.drain_feedback():
            splash_events.append(feedback)
            note("splash_feedback_received", **feedback)
        probe_server.close()

    marks = _read_marks(marks_path)
    marks_id = _marks_run_id(marks)
    interactive_ok = bool(interactive and interactive.get("ok"))
    splash_required = str(splash_mode).strip() in {"1", "true", "yes", "on"}
    outcome = evaluate_run_outcome(
        exit_code=exit_code if exit_code is not None else -1,
        timed_out=timed_out,
        marks=marks,
        interactive_received=interactive_ok,
        run_id=run_id,
        marks_run_id=marks_id,
        splash_required=splash_required,
        splash_events=splash_events,
    )

    def _delta_from_spawn(tool_ns: Any) -> int | None:
        try:
            return max(0, int(tool_ns) - int(spawn_ns))
        except (TypeError, ValueError):
            return None

    painted = next(
        (
            row
            for row in splash_events
            if row.get("ok") and row.get("event") == "splash_painted"
        ),
        None,
    )
    closed = next(
        (
            row
            for row in splash_events
            if row.get("ok") and row.get("event") == "splash_closed"
        ),
        None,
    )

    summary = {
        "ok": outcome["ok"],
        "error": outcome["error"],
        "run_id": run_id,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "marks": marks,
        "interactive": interactive,
        "splash_mode": splash_mode,
        "splash_events": splash_events,
        "splash_painted_ns_from_spawn": (
            _delta_from_spawn(painted.get("tool_mono_ns_received"))
            if painted
            else None
        ),
        "splash_closed_ns_from_spawn": (
            _delta_from_spawn(closed.get("tool_mono_ns_received"))
            if closed
            else None
        ),
        "interactive_ns_from_spawn": (
            _delta_from_spawn(interactive.get("tool_mono_ns_received"))
            if interactive
            else None
        ),
        "wait_for_input_idle": wait_idle,
        "stdout_tail": (stdout or "")[-4000:],
        "stderr_tail": (stderr or "")[-4000:],
        "package_type": package_type,
        "platform": platform.system(),
        "windows_frozen_status": "UNKNOWN",
    }
    try:
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return {
            "ok": False,
            "error": f"failed writing summary for run_id={run_id}: {exc}",
            "run_dir": str(run_dir),
        }
    summary["run_dir"] = str(run_dir)
    return summary

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure TraceLab startup stages. macOS source/offscreen is supported "
            "for tooling checks; Windows EXE baselines require --exe on Windows."
        )
    )
    parser.add_argument(
        "--package-type",
        choices=("source", "exe"),
        default="source",
        help="source (default on macOS) or frozen exe",
    )
    parser.add_argument(
        "--exe",
        type=Path,
        help="Windows TraceLab EXE path (required for --package-type exe)",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python used for source launches",
    )
    parser.add_argument(
        "--perf-root",
        type=Path,
        default=DEFAULT_PERF_ROOT,
        help="Parent directory for run-id folders",
    )
    parser.add_argument("--run-id", help="Optional fixed run id")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--qt-platform",
        default=os.environ.get("QT_QPA_PLATFORM") or "offscreen",
        help="Qt platform plugin for source runs (default: offscreen)",
    )
    parser.add_argument(
        "--splash",
        choices=("auto", "0", "1"),
        default="auto",
        help=(
            "TRACELAB_STARTUP_SPLASH for the measured process. "
            "Use 0/1 for matched splash-disabled/enabled comparisons."
        ),
    )
    args = parser.parse_args(argv)

    if args.package_type == "exe" and args.exe is None:
        parser.error("--exe is required for package-type exe")
    if args.package_type == "exe" and not sys.platform.startswith("win"):
        print(
            "WARNING: measuring an EXE path from a non-Windows host is unsupported; "
            "result must not be treated as a Windows baseline.",
            file=sys.stderr,
        )

    run_id = args.run_id or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    summary = run_once(
        run_id=run_id,
        perf_root=args.perf_root,
        package_type=args.package_type,
        exe=args.exe,
        python_exe=args.python,
        timeout_s=float(args.timeout),
        qt_platform=None if args.package_type == "exe" else args.qt_platform,
        splash_mode=str(args.splash),
    )
    print(json.dumps({"ok": summary.get("ok"), "run_dir": summary.get("run_dir"), "error": summary.get("error"), "windows_frozen_status": summary.get("windows_frozen_status", "UNKNOWN")}, ensure_ascii=False))
    return 0 if summary.get("ok") else 1

if __name__ == "__main__":
    raise SystemExit(main())
