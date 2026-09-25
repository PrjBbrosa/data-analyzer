"""Parent-side startup splash feedback controller.

Import has no process, thread, or socket side effects and must not import Qt
or ``mf4_analyzer.ui``. Spawn/IPC failures degrade the panel only; they never
block or abort the main GUI path. A second panel is never retried.

Outbound frames are queued under the lock and flushed only from the I/O
worker — callers (including the GUI thread) must never block on ``sendall``,
``wait``/``join``, or process reaping.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from mf4_analyzer.qt_app_support import parse_screen_rect

logger = logging.getLogger(__name__)

ENV_SPLASH = "TRACELAB_STARTUP_SPLASH"
ENV_BACKEND = "TRACELAB_STARTUP_BACKEND"

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
MSG_HIDDEN = "hidden"
MSG_CLOSED = "closed"  # legacy; not a visibility confirmation
MSG_DIAGNOSTIC = "diagnostic"
VALID_TYPES = frozenset(
    {
        MSG_HELLO,
        MSG_STAGE,
        MSG_PAINTED,
        MSG_FINISH,
        MSG_HIDDEN,
        MSG_CLOSED,
        MSG_DIAGNOSTIC,
    }
)

HIDDEN_FINISH_CLOSE = "finish_close"
HIDDEN_USER_CLOSE = "user_close"
HIDDEN_NEVER_SHOWN = "never_shown"
VALID_HIDDEN_REASONS = frozenset(
    {
        HIDDEN_FINISH_CLOSE,
        HIDDEN_USER_CLOSE,
        HIDDEN_NEVER_SHOWN,
    }
)

FRAME_MAX_BYTES = 4096
HANDSHAKE_TIMEOUT_S = 5.0
# Forced kill of the held Popen if no hidden ACK arrives after finish.
HIDDEN_ACK_TIMEOUT_S = 0.25
# Absolute handover ceiling from finish request; then degrade-show is allowed.
HANDOVER_FALLBACK_TIMEOUT_S = 1.5
# Historical alias used by older tests; maps to the forced-kill window.
FINISH_REAP_TIMEOUT_S = HIDDEN_ACK_TIMEOUT_S

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

NotifyCallback = Callable[[dict[str, Any]], None]


def resolve_startup_backend(env: dict[str, str] | None = None) -> str:
    """Return ``native``, ``qt``, ``none``, or ``native_unverified``.

    ``TRACELAB_STARTUP_SPLASH=0`` wins. ``native`` is returned only when the
    launcher left a verified inherited session. An explicit native request
    without that session does not fall through to a Qt child.
    """

    source = os.environ if env is None else env
    raw_splash = source.get(ENV_SPLASH)
    if raw_splash is not None and str(raw_splash).strip().lower() in _FALSEY:
        return "none"
    backend = str(source.get(ENV_BACKEND, "auto")).strip().lower() or "auto"
    from mf4_analyzer.startup_native_feedback import native_session_verified

    verified = native_session_verified(source)
    if backend == "none":
        return "none"
    if backend == "qt":
        return "qt"
    if backend == "native":
        return "native" if verified else "native_unverified"
    if backend != "auto":
        return "qt"
    return "native" if verified else "qt"


def create_startup_feedback():
    """Pick the splash controller for this process. Does not spawn anything."""

    from mf4_analyzer.startup_native_feedback import (
        NativeStartupFeedback,
        scrub_native_bootstrap,
    )

    kind = resolve_startup_backend()
    if kind == "native":
        return NativeStartupFeedback()
    scrub_native_bootstrap(close_handles=True)
    feedback = StartupFeedback()
    if kind in {"none", "native_unverified"}:
        suppress = getattr(feedback, "suppress", None)
        if callable(suppress):
            suppress("disabled" if kind == "none" else "native_unverified")
    return feedback


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
        self._watchdog: threading.Thread | None = None
        self._stop = threading.Event()
        self._recv_buf = bytearray()
        self._stage: str | None = None
        self._slow = False
        self._painted = False
        self._child_closed = False  # legacy closed message
        self._fail_reason: str | None = None
        self._endpoint: str | None = None
        self._wake_r: socket.socket | None = None
        self._wake_w: socket.socket | None = None
        self._listeners: list[NotifyCallback] = []
        # Handover observability (parent mono clock only; never subtract child).
        self._finish_requested = False
        self._finish_mono: float | None = None
        self._hidden = False
        self._hidden_reason: str | None = None
        self._hidden_seq: int | None = None
        self._handover_failed = False
        self._force_terminated = False
        self._child_exit_code: int | None = None
        self._child_exited = False
        self._reveal_notified = False
        # Finished can_reveal for this session. Late listeners replay this
        # payload only; raw stage history is not retained.
        self._reveal_payload: dict[str, Any] | None = None
        self._cancel_spawn = False
        self._suppress_reason: str | None = None
        # Screen the splash actually used, so the main window can open there.
        self._launch_screen: tuple[int, int, int, int] | None = None

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
    def launch_screen(self) -> tuple[int, int, int, int] | None:
        """Splash work area in virtual-desktop coordinates, if the child reported it."""

        with self._lock:
            return self._launch_screen

    @property
    def child_closed(self) -> bool:
        return self._child_closed

    @property
    def hidden(self) -> bool:
        return self._hidden

    @property
    def hidden_reason(self) -> str | None:
        return self._hidden_reason

    @property
    def handover_failed(self) -> bool:
        return self._handover_failed

    @property
    def finish_requested(self) -> bool:
        return self._finish_requested

    @property
    def child_exited(self) -> bool:
        return self._child_exited

    @property
    def child_exit_code(self) -> int | None:
        return self._child_exit_code

    @property
    def force_terminated(self) -> bool:
        return self._force_terminated

    @property
    def fail_reason(self) -> str | None:
        return self._fail_reason

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return self._proc

    def add_listener(self, callback: NotifyCallback) -> None:
        """Register a notify callback. Invoked from the I/O / watchdog threads.

        A finished ``can_reveal`` is replayed to a new listener. Registering
        the same callback again is a no-op. Callbacks run outside the lock.
        """

        replay: dict[str, Any] | None = None
        with self._lock:
            if self._closed:
                return
            if callback in self._listeners:
                return
            self._listeners.append(callback)
            cached = self._reveal_payload
            if cached is not None:
                replay = dict(cached)
        if replay is None:
            return
        try:
            callback(replay)
        except Exception:
            logger.exception("startup splash reveal listener failed")

    def remove_listener(self, callback: NotifyCallback) -> None:
        with self._lock:
            try:
                self._listeners.remove(callback)
            except ValueError:
                return

    def snapshot(self) -> dict[str, Any]:
        """Queryable handover state for diagnostics / tests."""

        with self._lock:
            return {
                "session": self._session,
                "hidden": self._hidden,
                "hidden_reason": self._hidden_reason,
                "handover_failed": self._handover_failed,
                "finish_requested": self._finish_requested,
                "child_exited": self._child_exited,
                "child_exit_code": self._child_exit_code,
                "force_terminated": self._force_terminated,
                "painted": self._painted,
                "degraded": self._degraded,
                "fail_reason": self._fail_reason,
                "closed": self._closed,
            }

    def suppress(self, reason: str) -> None:
        """Force the next start() to skip the Qt child without pretending it ran."""

        with self._lock:
            self._suppress_reason = str(reason)

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
            if self._suppress_reason:
                self._degraded = True
                self._fail_reason = (
                    "disabled"
                    if self._suppress_reason == "disabled"
                    else self._suppress_reason
                )
                return
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
                self._open_wake_pair()
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

        notify_reveal = False
        with self._lock:
            if self._closed:
                return
            if self._finished:
                self._ensure_watchdog_locked()
                return
            self._finished = True
            self._finish_requested = True
            self._finish_mono = time.monotonic()
            self._cancel_spawn = True
            self._emit_diagnostic_locked("finish_requested", None)
            if self._degraded or not self._started or self._fail_reason == "disabled":
                notify_reveal = True
                self._ensure_watchdog_locked()
            else:
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
                # Already dead / never spawned → reveal without waiting for hidden.
                proc = self._proc
                if proc is None or proc.poll() is not None:
                    if proc is not None and proc.poll() is not None:
                        self._note_child_exit_locked(int(proc.returncode or 0))
                    notify_reveal = True
                self._ensure_watchdog_locked()
        if notify_reveal:
            self._notify_reveal(reason="immediate")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._finished = True
            self._cancel_spawn = True
            self._listeners.clear()
            self._reveal_payload = None
            self._stop.set()
            self._cleanup_locked(kill_child=True)
        self._wake()

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

    def _open_wake_pair(self) -> None:
        try:
            wake_r, wake_w = socket.socketpair()
        except (AttributeError, OSError):
            self._wake_r = None
            self._wake_w = None
            return
        for sock in (wake_r, wake_w):
            sock.setblocking(False)
            try:
                sock.set_inheritable(False)
            except (AttributeError, OSError):
                pass
        self._wake_r = wake_r
        self._wake_w = wake_w

    def _wake(self) -> None:
        wake_w = self._wake_w
        if wake_w is None:
            return
        try:
            wake_w.send(b"\0")
        except OSError:
            pass

    def _drain_wake(self) -> None:
        wake_r = self._wake_r
        if wake_r is None:
            return
        while True:
            try:
                if not wake_r.recv(64):
                    break
            except BlockingIOError:
                break
            except OSError:
                break

    def _spawn_child(self) -> None:
        assert self._endpoint is not None
        with self._lock:
            if self._cancel_spawn or self._finished or self._closed:
                # Finish won the race before spawn completed.
                self._mark_failed("cancelled_before_spawn")
                return
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
        proc = subprocess.Popen(**kwargs)
        discard = False
        with self._lock:
            if self._cancel_spawn or self._finished or self._closed:
                # Late spawn after cancel: do not publish this handle.
                discard = True
            else:
                self._proc = proc
        if not discard:
            return
        # Wait outside the lock so a GUI finish() cannot block on reap.
        self._terminate_proc(proc)
        with self._lock:
            self._mark_failed("cancelled_before_spawn")

    def _next_seq_locked(self) -> int:
        self._seq += 1
        return self._seq

    def _enqueue_locked(self, payload: dict[str, Any]) -> None:
        """Queue an outbound frame. Never ``sendall`` under the caller lock."""

        message = dict(payload)
        message["seq"] = self._next_seq_locked()
        if "detail" not in message:
            message["detail"] = None
        self._pending.append(message)
        self._wake()

    def _take_pending_locked(self) -> list[dict[str, Any]]:
        if not self._pending:
            return []
        pending, self._pending = self._pending, []
        pending.sort(key=lambda item: 0 if item.get("type") == MSG_FINISH else 1)
        return pending

    def _flush_pending(self, conn: socket.socket) -> None:
        with self._lock:
            if not self._hello_ok:
                return
            pending = self._take_pending_locked()
        for message in pending:
            try:
                frame = encode_frame(message)
            except ValueError as exc:
                logger.warning("startup splash flush frame rejected: %s", exc)
                with self._lock:
                    self._mark_failed(f"flush_frame:{exc}")
                    self._stop.set()
                return
            try:
                conn.sendall(frame)
            except OSError as exc:
                logger.warning("startup splash flush failed: %s", exc)
                with self._lock:
                    self._mark_failed(f"flush:{exc}")
                    self._stop.set()
                return

    def _mark_failed(self, reason: str) -> None:
        self._degraded = True
        if self._fail_reason is None:
            self._fail_reason = reason

    def _ensure_watchdog_locked(self) -> None:
        if self._watchdog is not None and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(
            target=self._handover_watchdog,
            name="startup-splash-handover",
            daemon=True,
        )
        self._watchdog.start()

    def _handover_watchdog(self) -> None:
        """Background-only: wait for hidden, force-kill held Popen, or fallback."""

        finish_mono = self._finish_mono
        if finish_mono is None:
            finish_mono = time.monotonic()
        hidden_deadline = finish_mono + HIDDEN_ACK_TIMEOUT_S
        fallback_deadline = finish_mono + HANDOVER_FALLBACK_TIMEOUT_S
        held_proc: subprocess.Popen[bytes] | None = None
        with self._lock:
            held_proc = self._proc

        # Path A: already revealable (disabled / dead / hidden).
        if self._should_reveal_now():
            self._notify_reveal(reason="watchdog_ready")
            self._background_reap_remainder(held_proc, fallback_deadline)
            return

        # Wait for hidden ACK up to 250 ms.
        while time.monotonic() < hidden_deadline and not self._stop.is_set():
            if self._hidden or self._closed:
                break
            if held_proc is not None and held_proc.poll() is not None:
                with self._lock:
                    self._note_child_exit_locked(int(held_proc.returncode or 0))
                break
            time.sleep(0.01)

        if self._should_reveal_now():
            self._notify_reveal(reason="hidden_or_exit")
            self._background_reap_remainder(held_proc, fallback_deadline)
            return

        # No hidden within 250 ms: terminate only the held handle (never by name).
        with self._lock:
            proc = self._proc if self._proc is held_proc else held_proc
            already_hidden = self._hidden
            closed = self._closed
        if already_hidden or closed:
            self._notify_reveal(reason="hidden_late")
            self._background_reap_remainder(held_proc, fallback_deadline)
            return
        if proc is not None and proc.poll() is None:
            logger.warning(
                "startup splash child still alive after finish; terminating"
            )
            with self._lock:
                self._force_terminated = True
            self._terminate_proc(proc)
        # After forced kill (or natural exit), wait for the handle to exit then reveal.
        while time.monotonic() < fallback_deadline and not self._stop.is_set():
            if self._hidden:
                self._notify_reveal(reason="hidden_after_kill")
                return
            if proc is not None and proc.poll() is not None:
                with self._lock:
                    self._note_child_exit_locked(int(proc.returncode or 0))
                self._notify_reveal(reason="child_exited")
                self._background_cleanup_sockets()
                return
            time.sleep(0.02)

        # Absolute ceiling: degrade-show so the main app is not stuck forever.
        with self._lock:
            if not self._hidden and not self._reveal_notified:
                self._handover_failed = True
                self._emit_diagnostic_locked(
                    "handover_failed",
                    {
                        "force_terminated": self._force_terminated,
                        "child_exited": self._child_exited,
                    },
                )
        self._notify_reveal(reason="handover_failed")
        self._background_cleanup_sockets()

    def _background_reap_remainder(
        self,
        proc: subprocess.Popen[bytes] | None,
        fallback_deadline: float,
    ) -> None:
        """After reveal, reap sockets/process without blocking the GUI."""

        while time.monotonic() < fallback_deadline and not self._stop.is_set():
            if proc is None:
                break
            if proc.poll() is not None:
                with self._lock:
                    self._note_child_exit_locked(int(proc.returncode or 0))
                break
            time.sleep(0.05)
        # Normal success must not depend on terminate. Only kill if still alive
        # long after hidden and past a generous grace (fallback window).
        if (
            proc is not None
            and proc.poll() is None
            and not self._stop.is_set()
            and self._hidden
            and not self._force_terminated
        ):
            # Child acknowledged hide but hung on exit — log and terminate.
            logger.warning(
                "startup splash child still alive after hidden ack; terminating"
            )
            with self._lock:
                self._force_terminated = True
            self._terminate_proc(proc)
        self._background_cleanup_sockets()

    def _background_cleanup_sockets(self) -> None:
        with self._lock:
            self._cleanup_locked(kill_child=False)

    def _should_reveal_now(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            if self._hidden:
                return True
            if self._degraded and self._finish_requested:
                return True
            if self._fail_reason == "disabled" and self._finish_requested:
                return True
            if self._child_exited and self._finish_requested:
                return True
            return False

    def _notify_reveal(self, *, reason: str) -> None:
        with self._lock:
            if self._closed or self._reveal_notified:
                return
            self._reveal_notified = True
            payload = {
                "event": "can_reveal",
                "session": self._session,
                "reason": reason,
                "hidden": self._hidden,
                "hidden_reason": self._hidden_reason,
                "handover_failed": self._handover_failed,
                "child_exit_code": self._child_exit_code,
                "force_terminated": self._force_terminated,
            }
            self._reveal_payload = payload
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(dict(payload))
            except Exception:
                logger.exception("startup splash reveal listener failed")

    def _notify_raw(self, payload: dict[str, Any]) -> None:
        with self._lock:
            if self._closed:
                return
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(payload)
            except Exception:
                logger.exception("startup splash listener failed")

    def _note_child_exit_locked(self, code: int) -> None:
        if self._child_exited:
            return
        self._child_exited = True
        self._child_exit_code = int(code)
        self._emit_diagnostic_locked(
            "child_exited",
            {"returncode": self._child_exit_code},
        )

    def _emit_diagnostic_locked(self, event: str, detail: Any) -> None:
        # Called while holding the lock; forward outside via a tiny deferral.
        session = self._session

        def _forward() -> None:
            self._emit_splash_diagnostic(event, detail)

        # Prefer not to hold the lock during timing I/O.
        threading.Thread(
            target=_forward,
            name=f"startup-splash-diag-{event}",
            daemon=True,
        ).start()
        # Also push a structured listener event for the Qt bridge.
        # Use a copy so callers cannot mutate our state.
        payload = {
            "event": event,
            "session": session,
            "detail": detail,
        }
        # Schedule listener notify without nested lock issues: callers of
        # _emit_diagnostic_locked already hold the lock, so notify after release
        # via the same daemon thread.
        def _notify() -> None:
            self._notify_raw(payload)

        threading.Thread(
            target=_notify,
            name=f"startup-splash-notify-{event}",
            daemon=True,
        ).start()

    def _terminate_proc(self, proc: subprocess.Popen[bytes]) -> None:
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
        for attr in ("_wake_r", "_wake_w"):
            sock = getattr(self, attr)
            setattr(self, attr, None)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        proc = self._proc
        if kill_child and proc is not None and proc.poll() is None:
            # Must not block the GUI: terminate without wait under a GUI caller's
            # stack. Wait happens on the watchdog/daemon path only.
            try:
                proc.terminate()
            except OSError as exc:
                logger.warning("startup splash terminate failed: %s", exc)
            self._force_terminated = True
        if proc is not None and proc.poll() is not None:
            self._note_child_exit_locked(int(proc.returncode or 0))
            self._proc = None
        self._pending.clear()
        self._wake()

    def _worker_main(self) -> None:
        try:
            self._accept_and_serve()
        except Exception:
            logger.exception("startup splash worker crashed")
            with self._lock:
                self._mark_failed("worker_crash")
                self._cleanup_locked(kill_child=True)
            self._notify_reveal(reason="worker_crash")

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
                self._notify_reveal(reason="handshake_timeout")
                return
            # Late finish before accept: do not keep waiting for a panel.
            with self._lock:
                finished_early = self._finished and not self._hello_ok
            if finished_early and time.monotonic() >= deadline:
                with self._lock:
                    self._cleanup_locked(kill_child=True)
                return
            readable: list[socket.socket] = [listen]
            if self._wake_r is not None:
                readable.append(self._wake_r)
            try:
                ready, _, _ = select.select(readable, [], [], 0.05)
            except (OSError, ValueError):
                return
            if self._wake_r is not None and self._wake_r in ready:
                self._drain_wake()
            if listen not in ready:
                # Still flush if we somehow connected elsewhere — no-op here.
                continue
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
            conn.settimeout(0.05)
            try:
                conn.set_inheritable(False)
            except (AttributeError, OSError):
                pass
            with self._lock:
                # Reject a late handshake after the session was cancelled/finished
                # without ever intending to show the panel after main.
                if self._closed:
                    try:
                        conn.close()
                    except OSError:
                        pass
                    return
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
                self._notify_reveal(reason="handshake_timeout")
                return
            self._flush_pending(conn)
            readable = [conn]
            if self._wake_r is not None:
                readable.append(self._wake_r)
            try:
                ready, _, _ = select.select(readable, [], [], 0.05)
            except (OSError, ValueError):
                break
            if self._wake_r is not None and self._wake_r in ready:
                self._drain_wake()
            if conn not in ready:
                continue
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
                self._notify_reveal(reason="protocol_error")
                return
            for message in messages:
                self._handle_message(message)
            self._flush_pending(conn)
        with self._lock:
            if not self._finished and not self._closed:
                self._mark_failed("child_eof")
            if self._finished or self._closed:
                self._cleanup_locked(kill_child=False)
            else:
                self._cleanup_locked(kill_child=True)
        # EOF after finish without hidden still allows reveal via watchdog/exit.
        if self._finished and not self._hidden:
            proc = self._proc
            if proc is not None and proc.poll() is not None:
                with self._lock:
                    self._note_child_exit_locked(int(proc.returncode or 0))
                self._notify_reveal(reason="child_eof")
            elif self._degraded:
                self._notify_reveal(reason="child_eof")

    def _handle_message(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        msg_type = message.get("type")
        session = message.get("session")
        emit_event: str | None = None
        emit_detail: Any = None
        reveal = False
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
                # Late hello after close must not keep a panel alive for show.
                if self._closed:
                    self._stop.set()
                    return
                self._hello_ok = True
                # Pending (including finish) flushed by the worker after return.
                self._wake()
                return
            if not self._hello_ok:
                return
            if msg_type == MSG_PAINTED:
                if not self._painted:
                    self._painted = True
                    emit_detail = message.get("detail")
                    screen = parse_screen_rect(emit_detail)
                    if screen is not None:
                        self._launch_screen = screen
                    emit_event = "splash_painted"
            elif msg_type == MSG_HIDDEN:
                if not self._hidden:
                    reason = message.get("detail")
                    if reason not in VALID_HIDDEN_REASONS:
                        reason = str(reason) if reason is not None else None
                    self._hidden = True
                    self._hidden_reason = reason
                    seq = message.get("seq")
                    self._hidden_seq = int(seq) if isinstance(seq, int) else None
                    emit_event = "splash_hidden"
                    emit_detail = {
                        "reason": reason,
                        "seq": self._hidden_seq,
                    }
                    reveal = True
            elif msg_type == MSG_CLOSED:
                # Legacy: record but do not treat as visibility confirmation.
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
            self._emit_splash_diagnostic(emit_event, emit_detail)
            self._notify_raw(
                {
                    "event": emit_event,
                    "session": self._session,
                    "detail": emit_detail,
                }
            )
        if reveal:
            self._notify_reveal(reason="hidden")

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
