"""Runtime side of a native launcher splash session.

The launcher already owns the panel. This adapter speaks the inherited pipe
protocol and presents the same start/publish/finish/listener surface as
``StartupFeedback``. It never starts a Qt splash child and never invents a
child pid for the launcher process.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, BinaryIO

from mf4_analyzer.qt_app_support import parse_screen_rect
from mf4_analyzer.startup_feedback import (
    FRAME_MAX_BYTES,
    HANDOVER_FALLBACK_TIMEOUT_S,
    HIDDEN_ACK_TIMEOUT_S,
    STAGE_PREPARING,
    VALID_HIDDEN_REASONS,
    VALID_STAGES,
    NotifyCallback,
    decode_frames,
    encode_frame,
)

logger = logging.getLogger(__name__)

ENV_PROTOCOL = "TRACELAB_NATIVE_SPLASH_PROTOCOL"
ENV_SESSION = "TRACELAB_NATIVE_SPLASH_SESSION"
ENV_READ = "TRACELAB_NATIVE_SPLASH_READ"
ENV_WRITE = "TRACELAB_NATIVE_SPLASH_WRITE"
NATIVE_ENV_KEYS = (ENV_PROTOCOL, ENV_SESSION, ENV_READ, ENV_WRITE)
PROTOCOL_VERSION = "1"


def native_session_verified(env: dict[str, str] | None = None) -> bool:
    source = os.environ if env is None else env
    if str(source.get(ENV_PROTOCOL, "")).strip() != PROTOCOL_VERSION:
        return False
    session = str(source.get(ENV_SESSION, "")).strip()
    if not session:
        return False
    for name in (ENV_READ, ENV_WRITE):
        raw = str(source.get(name, "")).strip()
        if not raw or raw[0] == "-":
            return False
        if not raw.isdigit():
            return False
    return True


def scrub_native_bootstrap(*, close_handles: bool) -> None:
    """Drop launcher bootstrap facts so later children cannot inherit them."""

    read_raw = str(os.environ.get(ENV_READ, "")).strip()
    write_raw = str(os.environ.get(ENV_WRITE, "")).strip()
    verified = native_session_verified()
    for key in NATIVE_ENV_KEYS:
        os.environ.pop(key, None)
    if not close_handles or not verified:
        return
    _close_inherited_handle(read_raw)
    _close_inherited_handle(write_raw)


def _close_inherited_handle(raw: str) -> None:
    try:
        value = int(raw)
    except ValueError:
        return
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(value))  # type: ignore[attr-defined]
        return
    try:
        os.close(value)
    except OSError:
        return


def _open_inherited(raw: str, mode: str) -> BinaryIO:
    value = int(raw)
    if os.name == "nt":
        import msvcrt

        flag = os.O_RDONLY if "r" in mode else os.O_WRONLY
        fd = msvcrt.open_osfhandle(value, flag)
    else:
        fd = value
    os.set_inheritable(fd, False)
    return os.fdopen(fd, mode, buffering=0)


class NativeStartupFeedback:
    """Pipe-backed splash controller. ``process`` stays None on purpose."""

    def __init__(
        self,
        *,
        hidden_ack_timeout_s: float = HIDDEN_ACK_TIMEOUT_S,
        handover_timeout_s: float = HANDOVER_FALLBACK_TIMEOUT_S,
    ) -> None:
        self._lock = threading.RLock()
        self._session = str(os.environ.get(ENV_SESSION, "")).strip()
        self._read_raw = str(os.environ.get(ENV_READ, "")).strip()
        self._write_raw = str(os.environ.get(ENV_WRITE, "")).strip()
        self._verified = native_session_verified()
        for key in NATIVE_ENV_KEYS:
            os.environ.pop(key, None)
        self._hidden_ack_timeout_s = float(hidden_ack_timeout_s)
        self._handover_timeout_s = float(handover_timeout_s)
        self._started = False
        self._finished = False
        self._closed = False
        self._degraded = False
        self._fail_reason: str | None = None
        self._hidden = False
        self._hidden_reason: str | None = None
        self._handover_failed = False
        self._finish_requested = False
        self._painted = False
        self._reveal_notified = False
        # Same late-subscriber contract as StartupFeedback: one cached can_reveal.
        self._reveal_payload: dict[str, Any] | None = None
        self._pipe_eof = False
        self._launch_screen: tuple[int, int, int, int] | None = None
        self._listeners: list[NotifyCallback] = []
        self._stage = STAGE_PREPARING
        self._slow = False
        self._seq = 0
        self._reader: BinaryIO | None = None
        self._writer: BinaryIO | None = None
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None
        self._write_queue: list[dict[str, Any]] = []

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
        with self._lock:
            return self._launch_screen

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
    def fail_reason(self) -> str | None:
        return self._fail_reason

    @property
    def process(self) -> None:
        return None

    @property
    def child_exit_code(self) -> None:
        return None

    @property
    def force_terminated(self) -> bool:
        return False

    def add_listener(self, callback: NotifyCallback) -> None:
        """Register a notify callback.

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
            logger.exception("native startup reveal listener failed")

    def remove_listener(self, callback: NotifyCallback) -> None:
        with self._lock:
            try:
                self._listeners.remove(callback)
            except ValueError:
                return

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "session": self._session,
                "hidden": self._hidden,
                "hidden_reason": self._hidden_reason,
                "handover_failed": self._handover_failed,
                "finish_requested": self._finish_requested,
                "child_exited": False,
                "child_exit_code": None,
                "force_terminated": False,
                "painted": self._painted,
                "degraded": self._degraded,
                "fail_reason": self._fail_reason,
                "closed": self._closed,
                "native": True,
            }

    def start(
        self,
        *,
        hidden: bool = False,
        layout_probe: bool = False,
        allow_offscreen: bool = False,
        platform: str | None = None,
    ) -> None:
        del allow_offscreen, platform
        with self._lock:
            if self._started or self._closed or self._finished:
                return
            self._started = True
            if hidden or layout_probe or not self._verified:
                self._degraded = True
                self._fail_reason = "disabled" if hidden or layout_probe else "native_unverified"
                return
            try:
                self._reader = _open_inherited(self._read_raw, "rb")
                self._writer = _open_inherited(self._write_raw, "wb")
            except (OSError, ValueError) as exc:
                logger.warning("native startup channel was not usable: %s", exc)
                self._degraded = True
                self._fail_reason = f"start:{exc}"
                self._close_pipes_locked()
                return
        worker = threading.Thread(target=self._reader_main, name="native-startup-splash", daemon=True)
        self._worker = worker
        worker.start()

    def publish(self, stage: str) -> None:
        stage_id = str(stage)
        if stage_id not in VALID_STAGES:
            raise ValueError(f"unknown startup splash stage: {stage_id!r}")
        with self._lock:
            if self._closed or self._degraded or not self._started or self._finished:
                return
            self._stage = stage_id
            self._enqueue_locked(self._message("stage", stage=stage_id, slow=self._slow))
        self._flush_writes()

    def finish(self) -> None:
        notify = False
        with self._lock:
            if self._closed:
                return
            if self._finished:
                return
            self._finished = True
            self._finish_requested = True
            if self._degraded or not self._started or self._pipe_eof or self._hidden:
                if self._pipe_eof and not self._hidden:
                    self._handover_failed = True
                notify = True
            else:
                self._enqueue_locked(self._message("finish"))
                self._arm_watchdog_locked()
        if not notify:
            self._flush_writes()
        else:
            reason = "hidden" if self._hidden else "immediate"
            self._notify_reveal(reason=reason)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._finished = True
            self._stop.set()
            self._listeners.clear()
            self._reveal_payload = None
            self._close_pipes_locked()

    def _message(self, kind: str, **extra: Any) -> dict[str, Any]:
        self._seq += 1
        payload: dict[str, Any] = {
            "v": 1,
            "session": self._session,
            "seq": self._seq,
            "type": kind,
        }
        payload.update(extra)
        return payload

    def _enqueue_locked(self, payload: dict[str, Any]) -> None:
        self._write_queue.append(payload)

    def _flush_writes(self) -> None:
        with self._lock:
            pending = list(self._write_queue)
            self._write_queue.clear()
            writer = self._writer
        if writer is None or not pending:
            return
        try:
            for payload in pending:
                writer.write(encode_frame(payload))
            writer.flush()
        except (OSError, ValueError) as exc:
            logger.warning("native startup write failed: %s", exc)
            with self._lock:
                self._pipe_eof = True

    def _reader_main(self) -> None:
        reader = self._reader
        if reader is None:
            return
        buffer = bytearray()
        while not self._stop.is_set():
            try:
                chunk = reader.read(FRAME_MAX_BYTES)
            except OSError as exc:
                logger.warning("native startup read failed: %s", exc)
                chunk = b""
            if not chunk:
                with self._lock:
                    self._pipe_eof = True
                    finished = self._finish_requested
                    hidden = self._hidden
                if finished and not hidden:
                    with self._lock:
                        self._handover_failed = True
                    self._notify_reveal(reason="pipe_eof")
                return
            buffer.extend(chunk)
            try:
                messages = decode_frames(buffer)
            except ValueError as exc:
                logger.warning("native startup protocol error: %s", exc)
                with self._lock:
                    self._degraded = True
                    self._fail_reason = f"protocol:{exc}"
                    self._handover_failed = True
                self._notify_reveal(reason="protocol_error")
                return
            for message in messages:
                self._handle_message(message)

    def _handle_message(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        if message.get("session") != self._session:
            logger.warning("native startup ignored a cross-session message")
            return
        if int(message.get("v") or 0) != 1:
            return
        kind = message.get("type")
        reveal = False
        with self._lock:
            if self._closed or self._hidden:
                return
            if kind == "presented":
                if not self._painted:
                    self._painted = True
                    screen = parse_screen_rect(message)
                    if screen is not None:
                        self._launch_screen = screen
            elif kind == "hidden":
                reason = message.get("reason")
                if reason not in VALID_HIDDEN_REASONS:
                    reason = str(reason) if reason else None
                self._hidden = True
                self._hidden_reason = reason
                reveal = True
            elif kind == "diagnostic":
                logger.info("native startup diagnostic: %s", message.get("detail"))
                return
            else:
                return
        if reveal:
            self._notify_reveal(reason="hidden")

    def _arm_watchdog_locked(self) -> None:
        if self._watchdog is not None:
            return
        watchdog = threading.Thread(target=self._watchdog_main, name="native-startup-watchdog", daemon=True)
        self._watchdog = watchdog
        watchdog.start()

    def _watchdog_main(self) -> None:
        deadline = time.monotonic() + self._handover_timeout_s
        ack_deadline = time.monotonic() + self._hidden_ack_timeout_s
        reason = "handover_failed"
        while time.monotonic() < deadline and not self._stop.is_set():
            with self._lock:
                if self._hidden or self._reveal_notified:
                    return
                if self._pipe_eof:
                    self._handover_failed = True
                    reason = "pipe_eof"
                    break
            now = time.monotonic()
            if now >= ack_deadline:
                # 0.25 s used to kill a Qt splash child. This path has no child
                # process; the handover ceiling below is the failure window.
                ack_deadline = deadline
            time.sleep(min(0.02, max(0.0, deadline - now)))
        else:
            with self._lock:
                if self._hidden or self._reveal_notified:
                    return
                self._handover_failed = True
        self._notify_reveal(reason=reason)

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
                "child_exit_code": None,
                "force_terminated": False,
            }
            self._reveal_payload = payload
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(dict(payload))
            except Exception:
                logger.exception("native startup reveal listener failed")

    def _close_pipes_locked(self) -> None:
        for attr in ("_reader", "_writer"):
            handle = getattr(self, attr)
            setattr(self, attr, None)
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
