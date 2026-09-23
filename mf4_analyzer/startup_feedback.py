"""Parent-side startup splash feedback controller.

Import has no process, thread, or socket side effects and must not import Qt
or ``mf4_analyzer.ui``. Spawn/IPC failures degrade the panel only; they never
block or abort the main GUI path. A second panel is never retried.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENV_SPLASH = "TRACELAB_STARTUP_SPLASH"

STAGE_PREPARING = "preparing"
STAGE_LOADING_COMPONENTS = "loading_components"
STAGE_PREPARING_WORKSPACE = "preparing_workspace"
VALID_STAGES = frozenset(
    {
        STAGE_PREPARING,
        STAGE_LOADING_COMPONENTS,
        STAGE_PREPARING_WORKSPACE,
    }
)

MSG_HELLO = "hello"
MSG_STAGE = "stage"
MSG_PAINTED = "painted"
MSG_FINISH = "finish"
MSG_CLOSED = "closed"
MSG_DIAGNOSTIC = "diagnostic"
VALID_TYPES = frozenset(
    {
        MSG_HELLO,
        MSG_STAGE,
        MSG_PAINTED,
        MSG_FINISH,
        MSG_CLOSED,
        MSG_DIAGNOSTIC,
    }
)

FRAME_MAX_BYTES = 4096
HANDSHAKE_TIMEOUT_S = 5.0
FINISH_REAP_TIMEOUT_S = 1.0

CHILD_ENV_STRIP = (
    "TRACELAB_STARTUP_TIMING",
    "TRACELAB_STARTUP_RUN_ID",
    "TRACELAB_STARTUP_PERF_DIR",
    "TRACELAB_STARTUP_PROBE_HOST",
    "TRACELAB_STARTUP_PROBE_PORT",
    "TRACELAB_STARTUP_EXIT_AFTER_PROBE",
)

_FALSEY = frozenset({"0", "false", "off", "no"})
_LAUNCHER_NAME = "MF4 Data Analyzer V1.py"


def splash_enabled(
    *,
    hidden: bool,
    layout_probe: bool,
    platform: str | None = None,
    allow_offscreen: bool = False,
) -> bool:
    """Return whether the parent should spawn a splash child for this launch."""

    if hidden or layout_probe:
        return False
    qpa = str(os.environ.get("QT_QPA_PLATFORM") or "").strip().lower()
    if qpa == "offscreen" and not allow_offscreen:
        return False
    raw = os.environ.get(ENV_SPLASH)
    mode = "auto" if raw is None else str(raw).strip().lower()
    if mode in _FALSEY:
        return False
    if mode == "1":
        return True
    if mode in {"", "auto"}:
        host = sys.platform if platform is None else platform
        return host == "win32"
    return False


def _launcher_path() -> Path:
    return Path(__file__).resolve().parent.parent / _LAUNCHER_NAME


def build_child_command(
    *,
    session: str,
    endpoint: str,
    token: str,
    frozen: bool | None = None,
    executable: str | None = None,
    launcher: Path | None = None,
) -> list[str]:
    """Construct the splash-child argv. Does not consult cwd, BAT, or PATH."""

    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    exe = sys.executable if executable is None else executable
    args = [
        "--startup-splash-child",
        "--startup-splash-session",
        session,
        "--startup-splash-endpoint",
        endpoint,
        "--startup-splash-token",
        token,
    ]
    if is_frozen:
        return [exe, *args]
    path = _launcher_path() if launcher is None else Path(launcher)
    return [exe, str(path.resolve()), *args]


def child_environment(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for name in CHILD_ENV_STRIP:
        env.pop(name, None)
    # Prevent recursive splash if the child somehow entered a normal GUI path.
    env[ENV_SPLASH] = "0"
    return env


def encode_frame(payload: dict[str, Any]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    if len(raw) > FRAME_MAX_BYTES:
        raise ValueError(f"startup splash frame exceeds {FRAME_MAX_BYTES} bytes")
    return raw + b"\n"


def decode_frames(buffer: bytearray) -> list[dict[str, Any]]:
    """Pull complete JSON lines from *buffer*; leave a partial trailing frame."""

    messages: list[dict[str, Any]] = []
    while True:
        newline = buffer.find(b"\n")
        if newline < 0:
            if len(buffer) > FRAME_MAX_BYTES:
                raise ValueError("startup splash frame exceeded limit before newline")
            return messages
        line = bytes(buffer[:newline])
        del buffer[: newline + 1]
        if not line.strip():
            continue
        if len(line) > FRAME_MAX_BYTES:
            raise ValueError("startup splash frame exceeds limit")
        messages.append(json.loads(line.decode("utf-8")))


def parse_endpoint(endpoint: str) -> tuple[str, int]:
    text = str(endpoint).strip()
    if text.count(":") != 1:
        raise ValueError("endpoint must be 127.0.0.1:port")
    host, _, port_text = text.partition(":")
    if host != "127.0.0.1":
        raise ValueError("endpoint host must be 127.0.0.1")
    port = int(port_text)
    if not (1 <= port <= 65535):
        raise ValueError("endpoint port out of range")
    return host, port


class StartupFeedback:
    """Owns the splash listen socket, I/O worker, and child ``Popen`` handle."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._started = False
        self._finished = False
        self._closed = False
        self._degraded = False
        self._connected = False
        self._hello_ok = False
        self._session = secrets.token_urlsafe(16)
        self._token = secrets.token_urlsafe(24)
        self._seq = 0
        self._pending: list[dict[str, Any]] = []
        self._listen: socket.socket | None = None
        self._conn: socket.socket | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._worker: threading.Thread | None = None
        self._reaper: threading.Thread | None = None
        self._stop = threading.Event()
        self._recv_buf = bytearray()
        self._stage: str | None = None
        self._slow = False
        self._painted = False
        self._child_closed = False
        self._fail_reason: str | None = None
        self._endpoint: str | None = None

    @property
    def session(self) -> str:
        return self._session

    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def painted(self) -> bool:
        return self._painted

    @property
    def child_closed(self) -> bool:
        return self._child_closed

    @property
    def fail_reason(self) -> str | None:
        return self._fail_reason

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return self._proc

    def start(
        self,
        *,
        hidden: bool = False,
        layout_probe: bool = False,
        allow_offscreen: bool = False,
        platform: str | None = None,
    ) -> None:
        """Bind, spawn, and arm the I/O worker. Never waits for child paint."""

        with self._lock:
            if self._started or self._closed or self._finished:
                return
            self._started = True
            if not splash_enabled(
                hidden=hidden,
                layout_probe=layout_probe,
                platform=platform,
                allow_offscreen=allow_offscreen,
            ):
                self._degraded = True
                self._fail_reason = "disabled"
                return
            try:
                self._bind_listener()
                self._spawn_child()
            except (OSError, ValueError, TypeError) as exc:
                logger.warning("startup splash start failed: %s", exc)
                self._mark_failed(f"start:{exc}")
                self._cleanup_locked(kill_child=True)
                return
            self._worker = threading.Thread(
                target=self._worker_main,
                name="startup-splash-ipc",
                daemon=True,
            )
            self._worker.start()

    def publish(self, stage: str) -> None:
        stage_id = str(stage)
        if stage_id not in VALID_STAGES:
            raise ValueError(f"unknown startup splash stage: {stage_id!r}")
        with self._lock:
            if self._closed or self._degraded or not self._started:
                return
            if self._finished:
                return
            self._stage = stage_id
            self._enqueue_locked(
                {
                    "type": MSG_STAGE,
                    "session": self._session,
                    "stage": stage_id,
                    "slow": self._slow,
                }
            )

    def set_slow(self, slow: bool) -> None:
        with self._lock:
            if self._closed or self._degraded or not self._started:
                return
            if self._finished:
                return
            self._slow = bool(slow)
            self._enqueue_locked(
                {
                    "type": MSG_STAGE,
                    "session": self._session,
                    "stage": self._stage,
                    "slow": self._slow,
                }
            )

    def finish(self) -> None:
        """Terminal state: prefer over queued stages; never wait/join here."""

        with self._lock:
            if self._closed:
                return
            if self._finished:
                self._ensure_reaper_locked()
                return
            self._finished = True
            if self._degraded or not self._started or self._fail_reason == "disabled":
                self._cleanup_locked(kill_child=True)
                return
            # Finish outranks pending ordinary stage traffic.
            self._pending = [
                item for item in self._pending if item.get("type") == MSG_FINISH
            ]
            self._enqueue_locked(
                {
                    "type": MSG_FINISH,
                    "session": self._session,
                    "stage": self._stage,
                    "slow": self._slow,
                }
            )
            self._ensure_reaper_locked()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._finished = True
            self._stop.set()
            self._cleanup_locked(kill_child=True)

    def _bind_listener(self) -> None:
        listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen.bind(("127.0.0.1", 0))
        listen.listen(1)
        listen.settimeout(0.2)
        try:
            listen.set_inheritable(False)
        except (AttributeError, OSError):
            pass
        host, port = listen.getsockname()[:2]
        self._listen = listen
        self._endpoint = f"{host}:{port}"

    def _spawn_child(self) -> None:
        assert self._endpoint is not None
        command = build_child_command(
            session=self._session,
            endpoint=self._endpoint,
            token=self._token,
        )
        env = child_environment()
        kwargs: dict[str, Any] = {
            "args": command,
            "env": env,
            "shell": False,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True
        self._proc = subprocess.Popen(**kwargs)

    def _next_seq_locked(self) -> int:
        self._seq += 1
        return self._seq

    def _enqueue_locked(self, payload: dict[str, Any]) -> None:
        message = dict(payload)
        message["seq"] = self._next_seq_locked()
        if "detail" not in message:
            message["detail"] = None
        if self._hello_ok and self._conn is not None:
            conn = self._conn
            try:
                frame = encode_frame(message)
            except ValueError as exc:
                logger.warning("startup splash frame rejected: %s", exc)
                self._mark_failed(f"frame:{exc}")
                self._stop.set()
                return
            # Send without relying on the peer reading promptly; IO errors degrade.
            try:
                conn.sendall(frame)
            except OSError as exc:
                logger.warning("startup splash send failed: %s", exc)
                self._mark_failed(f"send:{exc}")
                self._stop.set()
        else:
            self._pending.append(message)

    def _flush_pending_locked(self) -> None:
        if self._conn is None or not self._hello_ok:
            return
        pending, self._pending = self._pending, []
        # Finish messages first if any were queued during the race.
        pending.sort(key=lambda item: 0 if item.get("type") == MSG_FINISH else 1)
        conn = self._conn
        for message in pending:
            try:
                frame = encode_frame(message)
            except ValueError as exc:
                logger.warning("startup splash flush frame rejected: %s", exc)
                self._mark_failed(f"flush_frame:{exc}")
                self._stop.set()
                return
            try:
                conn.sendall(frame)
            except OSError as exc:
                logger.warning("startup splash flush failed: %s", exc)
                self._mark_failed(f"flush:{exc}")
                self._stop.set()
                return

    def _mark_failed(self, reason: str) -> None:
        self._degraded = True
        if self._fail_reason is None:
            self._fail_reason = reason

    def _ensure_reaper_locked(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return
        if self._proc is None:
            self._cleanup_locked(kill_child=False)
            return
        self._reaper = threading.Thread(
            target=self._reap_after_finish,
            name="startup-splash-reaper",
            daemon=True,
        )
        self._reaper.start()

    def _reap_after_finish(self) -> None:
        deadline = time.monotonic() + FINISH_REAP_TIMEOUT_S
        proc = self._proc
        while proc is not None and proc.poll() is None:
            if time.monotonic() >= deadline:
                break
            if self._stop.wait(0.05):
                break
            proc = self._proc
        with self._lock:
            proc = self._proc
            if proc is not None and proc.poll() is None:
                logger.warning(
                    "startup splash child still alive after finish; terminating"
                )
                self._terminate_proc_locked(proc)
            self._cleanup_locked(kill_child=False)

    def _terminate_proc_locked(self, proc: subprocess.Popen[bytes]) -> None:
        try:
            proc.terminate()
        except OSError as exc:
            logger.warning("startup splash terminate failed: %s", exc)
            return
        try:
            proc.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError as exc:
                logger.warning("startup splash kill failed: %s", exc)
            try:
                proc.wait(timeout=0.4)
            except (subprocess.TimeoutExpired, OSError) as exc:
                logger.warning("startup splash reap failed: %s", exc)

    def _cleanup_locked(self, *, kill_child: bool) -> None:
        self._stop.set()
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        listen = self._listen
        self._listen = None
        if listen is not None:
            try:
                listen.close()
            except OSError:
                pass
        proc = self._proc
        if kill_child and proc is not None and proc.poll() is None:
            self._terminate_proc_locked(proc)
        # Drop the handle after an attempt to reap; do not join workers here.
        if proc is not None and proc.poll() is not None:
            self._proc = None
        self._pending.clear()

    def _worker_main(self) -> None:
        try:
            self._accept_and_serve()
        except Exception:
            logger.exception("startup splash worker crashed")
            with self._lock:
                self._mark_failed("worker_crash")
                self._cleanup_locked(kill_child=True)

    def _accept_and_serve(self) -> None:
        deadline = time.monotonic() + HANDSHAKE_TIMEOUT_S
        listen = self._listen
        if listen is None:
            return
        conn: socket.socket | None = None
        while not self._stop.is_set():
            if time.monotonic() >= deadline and not self._hello_ok:
                with self._lock:
                    self._mark_failed("handshake_timeout")
                    self._cleanup_locked(kill_child=True)
                return
            try:
                conn, _addr = listen.accept()
                break
            except socket.timeout:
                continue
            except OSError:
                return
        if conn is None:
            return
        try:
            conn.settimeout(0.2)
            try:
                conn.set_inheritable(False)
            except (AttributeError, OSError):
                pass
            with self._lock:
                self._conn = conn
                self._connected = True
            self._serve_connection(conn, deadline)
        finally:
            with self._lock:
                if self._conn is conn:
                    self._conn = None
            try:
                conn.close()
            except OSError:
                pass

    def _serve_connection(self, conn: socket.socket, handshake_deadline: float) -> None:
        while not self._stop.is_set():
            if not self._hello_ok and time.monotonic() >= handshake_deadline:
                with self._lock:
                    self._mark_failed("handshake_timeout")
                    self._cleanup_locked(kill_child=True)
                return
            try:
                chunk = conn.recv(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            self._recv_buf.extend(chunk)
            try:
                messages = decode_frames(self._recv_buf)
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning("startup splash protocol error: %s", exc)
                with self._lock:
                    self._mark_failed(f"protocol:{exc}")
                    self._cleanup_locked(kill_child=True)
                return
            for message in messages:
                self._handle_message(message)
        with self._lock:
            if not self._finished and not self._closed:
                self._mark_failed("child_eof")
            # EOF path: stop listening; leave reaper/finish to shared cleanup.
            if self._finished or self._closed:
                self._cleanup_locked(kill_child=False)
            else:
                self._cleanup_locked(kill_child=True)

    def _handle_message(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        msg_type = message.get("type")
        session = message.get("session")
        emit_event: str | None = None
        emit_detail: Any = None
        with self._lock:
            if session != self._session:
                logger.warning("startup splash ignored cross-session message")
                return
            if msg_type not in VALID_TYPES:
                self._mark_failed(f"bad_type:{msg_type!r}")
                self._stop.set()
                return
            if msg_type == MSG_HELLO:
                detail = message.get("detail")
                token = detail if isinstance(detail, str) else None
                if token != self._token:
                    self._mark_failed("bad_token")
                    self._stop.set()
                    return
                self._hello_ok = True
                self._flush_pending_locked()
                return
            if not self._hello_ok:
                return
            if msg_type == MSG_PAINTED:
                if not self._painted:
                    self._painted = True
                    emit_event = "splash_painted"
                    emit_detail = message.get("detail")
            elif msg_type == MSG_CLOSED:
                if not self._child_closed:
                    self._child_closed = True
                    emit_event = "splash_closed"
                    emit_detail = message.get("detail")
            elif msg_type == MSG_DIAGNOSTIC:
                logger.info(
                    "startup splash diagnostic: %s",
                    message.get("detail"),
                )
                return
            else:
                # Child must not drive stage/finish; ignore stale copies.
                return
        if emit_event is not None:
            # Forward on the I/O thread immediately — do not wait for main-window
            # first_frame / interactive probe connection.
            self._emit_splash_diagnostic(emit_event, emit_detail)

    def _emit_splash_diagnostic(self, event: str, detail: Any) -> None:
        """Record parent-side splash diagnostics without blocking the GUI path."""

        try:
            from mf4_analyzer.startup_timing import record_splash_event

            record_splash_event(
                event,
                session=self._session,
                detail=detail,
            )
        except Exception:
            # Diagnostic only: never fail the splash session for timing/probe I/O.
            logger.exception("startup splash diagnostic forward failed for %s", event)