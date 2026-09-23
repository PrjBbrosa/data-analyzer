"""Opt-in process-local startup stage timing (stdlib only).

Enable with ``TRACELAB_STARTUP_TIMING=1``. When disabled this module must not
create directories, scan the filesystem, or import heavy dependencies; ``mark``
calls are no-ops.

Environment:

* ``TRACELAB_STARTUP_TIMING`` – truthy enables recording
* ``TRACELAB_STARTUP_RUN_ID`` – run folder name under the perf directory
* ``TRACELAB_STARTUP_PERF_DIR`` – parent directory for run folders
* ``TRACELAB_STARTUP_PROBE_HOST`` / ``TRACELAB_STARTUP_PROBE_PORT`` – optional
  TCP endpoint owned by ``tools/measure_windows_startup.py`` for the queued
  interactive probe after first frame
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any

ENV_ENABLED = "TRACELAB_STARTUP_TIMING"
ENV_RUN_ID = "TRACELAB_STARTUP_RUN_ID"
ENV_PERF_DIR = "TRACELAB_STARTUP_PERF_DIR"
ENV_PROBE_HOST = "TRACELAB_STARTUP_PROBE_HOST"
ENV_PROBE_PORT = "TRACELAB_STARTUP_PROBE_PORT"
ENV_EXIT_AFTER_PROBE = "TRACELAB_STARTUP_EXIT_AFTER_PROBE"

STAGE_PYTHON_ENTRY = "python_entry"
STAGE_GUI_MODULES_IMPORTED = "gui_modules_imported"
STAGE_QAPPLICATION_READY = "qapplication_ready"
STAGE_MAINWINDOW_CONSTRUCTED = "mainwindow_constructed"
STAGE_FIRST_FRAME = "first_frame"
STAGE_INTERACTIVE_PROBE_HANDLED = "interactive_probe_handled"
STAGE_PRELOAD_COMPLETE = "preload_complete"
STAGE_PAGE_READY = "page_ready"
# Parent-side splash diagnostics (marks.jsonl). Never written by the splash child.
STAGE_SPLASH_PAINTED = "splash_painted"
STAGE_SPLASH_CLOSED = "splash_closed"  # legacy closed message
STAGE_SPLASH_HIDDEN = "splash_hidden"
STAGE_FINISH_REQUESTED = "finish_requested"
STAGE_MAIN_SHOW_CALLED = "main_show_called"
STAGE_MAIN_FIRST_FRAME = "main_first_frame"
STAGE_CHILD_EXITED = "child_exited"
STAGE_HANDOVER_FAILED = "handover_failed"

# Probe message roles: feedback is a parent push; interactive is tool→app request.
PROBE_ROLE_FEEDBACK = "feedback"
PROBE_ROLE_FEEDBACK_ACK = "feedback_ack"
PROBE_CMD_INTERACTIVE = "interactive_probe"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

_enabled = False
_run_id: str | None = None
_perf_dir: Path | None = None
_origin_mono_ns: int | None = None
_stages: list[str] = []
_write_error: str | None = None
_marks_path: Path | None = None
_seen_stages: set[str] = set()


class StartupTimingError(RuntimeError):
    """Raised when an enabled timing write cannot be completed."""


def _env_truthy(name: str) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return False
    return str(raw).strip().lower() in _TRUTHY


def _bootstrap_from_env() -> None:
    global _enabled, _run_id, _perf_dir, _origin_mono_ns
    _enabled = _env_truthy(ENV_ENABLED)
    if not _enabled:
        _run_id = None
        _perf_dir = None
        return
    raw_id = os.environ.get(ENV_RUN_ID)
    _run_id = str(raw_id).strip() if raw_id and str(raw_id).strip() else None
    raw_dir = os.environ.get(ENV_PERF_DIR)
    if raw_dir and str(raw_dir).strip():
        _perf_dir = Path(str(raw_dir).strip()).expanduser()
    else:
        _perf_dir = Path(".state") / "startup-perf"
    if _origin_mono_ns is None:
        _origin_mono_ns = time.perf_counter_ns()


_bootstrap_from_env()


def reset_for_tests() -> None:
    """Clear process state so focused tests can reconfigure the env."""

    global _enabled, _run_id, _perf_dir, _origin_mono_ns
    global _stages, _write_error, _marks_path, _seen_stages
    _stages = []
    _write_error = None
    _marks_path = None
    _seen_stages = set()
    _origin_mono_ns = None
    _bootstrap_from_env()


def enabled() -> bool:
    return bool(_enabled)


def last_write_error() -> str | None:
    return _write_error


def recorded_stages() -> tuple[str, ...]:
    return tuple(_stages)


def run_id() -> str | None:
    return _run_id


def marks_path() -> Path | None:
    return _marks_path


def _ensure_marks_file() -> Path:
    global _marks_path, _write_error
    if not _enabled:
        raise StartupTimingError("startup timing is disabled")
    if _run_id is None:
        raise StartupTimingError(
            f"{ENV_RUN_ID} is required when {ENV_ENABLED} is enabled"
        )
    assert _perf_dir is not None
    run_dir = _perf_dir / _run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "marks.jsonl"
        if not path.exists():
            path.write_text("", encoding="utf-8")
        _marks_path = path
        return path
    except OSError as exc:
        _write_error = (
            f"cannot create timing run dir for run_id={_run_id!r} "
            f"under {_perf_dir}: {exc}"
        )
        raise StartupTimingError(_write_error) from exc


def mark(stage: str, **detail: Any) -> None:
    """Record one process-local stage. No-op when timing is disabled."""

    global _write_error
    if not _enabled:
        return
    stage_name = str(stage)
    # python_entry may be emitted from both the launcher and app.main; keep once.
    if stage_name == STAGE_PYTHON_ENTRY and stage_name in _seen_stages:
        return
    if _origin_mono_ns is None:
        _bootstrap_from_env()
    assert _origin_mono_ns is not None
    mono_ns = time.perf_counter_ns() - _origin_mono_ns
    payload: dict[str, Any] = {
        "stage": stage_name,
        "mono_ns": int(mono_ns),
        "run_id": _run_id,
    }
    if detail:
        payload["detail"] = detail
    try:
        path = _ensure_marks_file()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except StartupTimingError:
        raise
    except OSError as exc:
        _write_error = (
            f"failed writing startup mark {stage_name!r} for run_id={_run_id!r}: {exc}"
        )
        raise StartupTimingError(_write_error) from exc
    _stages.append(stage_name)
    _seen_stages.add(stage_name)


def mark_page_ready(page_id: str, **detail: Any) -> None:
    """Task 3 hook: record one analysis page becoming ready. Not auto-called."""

    extra = {"page_id": str(page_id)}
    extra.update(detail)
    mark(STAGE_PAGE_READY, **extra)


def mark_preload_complete(**detail: Any) -> None:
    """Task 3 hook: record idle preload finished. Never means 'app available'."""

    mark(STAGE_PRELOAD_COMPLETE, **detail)


def record_splash_event(
    event: str,
    *,
    session: str | None = None,
    detail: Any = None,
) -> None:
    """Parent I/O-thread splash diagnostic: marks.jsonl + optional probe push.

    Uses this process's mono clock for marks only. Child mono timestamps in
    *detail* are recorded as opaque payload and must never be subtracted from
    parent or tool clocks. When timing is disabled this is a full no-op.
    """

    if not _enabled:
        return
    stage_name = str(event)
    extra: dict[str, Any] = {}
    if session is not None:
        extra["session"] = str(session)
    if detail is not None:
        # Opaque child diagnostics (e.g. frame stats); not a parent clock.
        extra["child_detail"] = detail
    mark(stage_name, **extra)
    forward_feedback_event(stage_name, session=session)


def forward_feedback_event(
    event: str,
    *,
    session: str | None = None,
    timeout_s: float = 0.5,
) -> dict[str, Any] | None:
    """One-shot TCP push of a feedback event to the measurement tool.

    Safe to call from the splash controller I/O thread. Does not wait for the
    main-window interactive probe path. Returns the tool ack payload when
    present; returns None when timing/probe is disabled or the push fails.
    """

    if not _enabled:
        return None
    endpoint = probe_endpoint()
    if endpoint is None:
        return None
    host, port = endpoint
    parent_mono_ns: int | None = None
    if _origin_mono_ns is not None:
        parent_mono_ns = int(time.perf_counter_ns() - _origin_mono_ns)
    payload = {
        "role": PROBE_ROLE_FEEDBACK,
        "event": str(event),
        "run_id": _run_id,
        "session": session,
        # Informational only — the tool must stamp receipt on its own clock.
        "parent_mono_ns": parent_mono_ns,
    }
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect((host, port))
        raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        sock.sendall(raw)
        try:
            reply = sock.recv(4096)
        except OSError:
            return None
        if not reply:
            return None
        text = reply.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        try:
            body = json.loads(text.splitlines()[0])
        except json.JSONDecodeError:
            return None
        if not isinstance(body, dict):
            return None
        if body.get("role") != PROBE_ROLE_FEEDBACK_ACK:
            return None
        return body
    except OSError:
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass


def exit_after_probe() -> bool:
    return _env_truthy(ENV_EXIT_AFTER_PROBE)


def probe_endpoint() -> tuple[str, int] | None:
    if not _enabled:
        return None
    host = os.environ.get(ENV_PROBE_HOST)
    port_raw = os.environ.get(ENV_PROBE_PORT)
    if not host or not port_raw:
        return None
    try:
        port = int(str(port_raw).strip())
    except ValueError:
        return None
    if port <= 0:
        return None
    return str(host).strip(), port


def connect_probe_socket(timeout_s: float = 2.0) -> socket.socket | None:
    """Non-blocking-capable client socket to the measurement tool, or None."""

    endpoint = probe_endpoint()
    if endpoint is None:
        return None
    host, port = endpoint
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect((host, port))
    except OSError:
        sock.close()
        return None
    sock.settimeout(None)
    sock.setblocking(False)
    return sock


def read_probe_request(sock: socket.socket) -> dict[str, Any] | None:
    try:
        data = sock.recv(4096)
    except BlockingIOError:
        return None
    except OSError:
        return None
    if not data:
        return None
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        payload = json.loads(text.splitlines()[0])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def write_probe_response(
    sock: socket.socket, *, token: str, ok: bool = True, **extra: Any
) -> None:
    payload = {
        "ok": bool(ok),
        "token": token,
        "child_mono_ns": time.perf_counter_ns()
        if _origin_mono_ns is None
        else time.perf_counter_ns() - _origin_mono_ns,
        "run_id": _run_id,
    }
    payload.update(extra)
    raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    sock.setblocking(True)
    try:
        sock.sendall(raw)
    finally:
        try:
            sock.setblocking(False)
        except OSError:
            pass
