"""Hidden startup-splash child process entry.

Validates the parent IPC session before creating a ``QApplication``. Does not
bootstrap extensions and must not import ``mf4_analyzer.app`` or MainWindow.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
from typing import Any, Callable

from mf4_analyzer.startup_feedback import (
    FRAME_MAX_BYTES,
    MSG_CLOSED,
    MSG_DIAGNOSTIC,
    MSG_FINISH,
    MSG_HELLO,
    MSG_PAINTED,
    MSG_STAGE,
    VALID_STAGES,
    decode_frames,
    encode_frame,
    parse_endpoint,
)

logger = logging.getLogger(__name__)

SPLASH_CHILD_FLAG = "--startup-splash-child"
SPLASH_SESSION_FLAG = "--startup-splash-session"
SPLASH_ENDPOINT_FLAG = "--startup-splash-endpoint"
SPLASH_TOKEN_FLAG = "--startup-splash-token"
SPLASH_ARGV_FLAGS = frozenset(
    {
        SPLASH_CHILD_FLAG,
        SPLASH_SESSION_FLAG,
        SPLASH_ENDPOINT_FLAG,
        SPLASH_TOKEN_FLAG,
    }
)


class _WindowedArgumentParser(argparse.ArgumentParser):
    """Match the root launcher: never depend on console streams."""

    def _print_message(self, message, file=None):
        if not message:
            return
        stream = sys.stderr if file is None else file
        writer = getattr(stream, "write", None)
        if not callable(writer):
            return
        try:
            writer(str(message))
        except (OSError, ValueError, AttributeError):
            return


def reject_abbreviated_splash_flags(argv: list[str]) -> None:
    for token in argv:
        if not token.startswith("--"):
            continue
        name = token.split("=", 1)[0]
        if name.startswith("--startup-splash") and name not in SPLASH_ARGV_FLAGS:
            raise SystemExit(2)


def _system_reduced_motion() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        # SPI_GETCLIENTAREAANIMATION — False means the user wants less motion.
        SPI_GETCLIENTAREAANIMATION = 0x1042
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION,
            0,
            ctypes.byref(enabled),
            0,
        )
        if not ok:
            return False
        return int(enabled.value) == 0
    except (AttributeError, OSError, ValueError, TypeError):
        return False


class _SplashSession:
    """Owns the child socket, inbound dispatch, and view lifetime."""

    def __init__(
        self,
        *,
        session: str,
        token: str,
        host: str,
        port: int,
    ) -> None:
        self.session = session
        self.token = token
        self.host = host
        self.port = port
        self._conn: socket.socket | None = None
        self._lock = threading.Lock()
        self._seq = 0
        self._recv_buf = bytearray()
        self._stop = threading.Event()
        self._finished = False
        self._eof = False
        self._protocol_error = False
        self._shown = False
        self._painted_sent = False
        self._stage: str | None = None
        self._slow = False
        self._reader: threading.Thread | None = None
        self._app = None
        self._splash = None
        self._paint_watcher = None
        self._on_gui: Callable[[Callable[[], None]], None] | None = None

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def eof(self) -> bool:
        return self._eof

    @property
    def protocol_error(self) -> bool:
        return self._protocol_error

    def connect(self) -> None:
        conn = socket.create_connection((self.host, self.port), timeout=5.0)
        conn.settimeout(0.2)
        try:
            conn.set_inheritable(False)
        except (AttributeError, OSError):
            pass
        self._conn = conn
        self._send(
            {
                "type": MSG_HELLO,
                "session": self.session,
                "stage": None,
                "slow": None,
                "detail": self.token,
            }
        )
        self._reader = threading.Thread(
            target=self._read_loop,
            name="startup-splash-child-ipc",
            daemon=True,
        )
        self._reader.start()

    def drain_pre_show(self, timeout_s: float = 0.15) -> None:
        """Wait briefly so an already-queued finish/EOF can suppress show()."""

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.should_suppress_show():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._stop.wait(min(0.02, remaining))

    def should_suppress_show(self) -> bool:
        return self._finished or self._eof or self._protocol_error

    def bind_gui(self, app, schedule: Callable[[Callable[[], None]], None]) -> None:
        self._app = app
        self._on_gui = schedule

    def attach_splash(self, splash) -> None:
        self._splash = splash
        self._apply_state_to_view()

    def mark_shown(self) -> None:
        self._shown = True

    def note_first_paint(self) -> None:
        if self._painted_sent:
            return
        self._painted_sent = True
        self._send(
            {
                "type": MSG_PAINTED,
                "session": self.session,
                "stage": self._stage,
                "slow": self._slow,
                "detail": None,
            }
        )

    def notify_user_closed(self) -> None:
        self._send(
            {
                "type": MSG_CLOSED,
                "session": self.session,
                "stage": self._stage,
                "slow": self._slow,
                "detail": None,
            }
        )
        splash = self._splash
        self._splash = None
        if splash is not None:
            try:
                splash.close_splash()
            except Exception:
                logger.exception("startup splash close_splash failed after user close")

    def shutdown(self) -> None:
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
        splash = self._splash
        self._splash = None
        if splash is not None:
            try:
                splash.close_splash()
            except Exception:
                logger.exception("startup splash close_splash failed on shutdown")
        app = self._app
        if app is not None:
            try:
                app.quit()
            except Exception:
                logger.exception("startup splash QApplication.quit failed")

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _send(self, payload: dict[str, Any]) -> None:
        conn = self._conn
        if conn is None:
            return
        message = dict(payload)
        with self._lock:
            message["seq"] = self._next_seq()
            try:
                frame = encode_frame(message)
            except ValueError as exc:
                logger.warning("startup splash child frame rejected: %s", exc)
                return
            try:
                conn.sendall(frame)
            except OSError as exc:
                logger.warning("startup splash child send failed: %s", exc)
                self._eof = True
                self._stop.set()

    def _read_loop(self) -> None:
        conn = self._conn
        if conn is None:
            return
        while not self._stop.is_set():
            try:
                chunk = conn.recv(1024)
            except socket.timeout:
                continue
            except OSError:
                self._eof = True
                break
            if not chunk:
                self._eof = True
                break
            self._recv_buf.extend(chunk)
            if len(self._recv_buf) > FRAME_MAX_BYTES and b"\n" not in self._recv_buf:
                self._protocol_error = True
                break
            try:
                messages = decode_frames(self._recv_buf)
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                self._protocol_error = True
                break
            for message in messages:
                self._handle_message(message)
            if self._finished or self._protocol_error:
                break
        if self._eof or self._protocol_error or self._finished:
            self._schedule_shutdown()

    def _handle_message(self, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            self._protocol_error = True
            return
        if message.get("session") != self.session:
            # Stale / cross-session traffic must not re-show or mutate state.
            return
        msg_type = message.get("type")
        if msg_type == MSG_FINISH:
            self._finished = True
            self._schedule_shutdown()
            return
        if msg_type == MSG_STAGE:
            if self._finished:
                return
            stage = message.get("stage")
            if stage is not None and stage not in VALID_STAGES:
                self._protocol_error = True
                self._schedule_shutdown()
                return
            if stage is not None:
                self._stage = str(stage)
            if "slow" in message and message.get("slow") is not None:
                self._slow = bool(message.get("slow"))
            self._schedule_view_update()
            return
        if msg_type in {MSG_HELLO, MSG_PAINTED, MSG_CLOSED, MSG_DIAGNOSTIC}:
            return
        self._protocol_error = True
        self._schedule_shutdown()

    def _schedule_view_update(self) -> None:
        schedule = self._on_gui
        if schedule is None:
            return
        schedule(self._apply_state_to_view)

    def _apply_state_to_view(self) -> None:
        splash = self._splash
        if splash is None or self._finished:
            return
        if self._stage is not None:
            splash.set_stage(self._stage)
        splash.set_slow(self._slow)

    def _schedule_shutdown(self) -> None:
        schedule = self._on_gui
        if schedule is None:
            # Pre-GUI: just mark; caller checks should_suppress_show().
            self._stop.set()
            return
        schedule(self.shutdown)


def _install_paint_watcher(splash, session: _SplashSession):
    from PyQt5.QtCore import QEvent, QObject, QTimer
    from PyQt5.QtWidgets import QApplication

    class _PaintWatcher(QObject):
        def __init__(self, owner: _SplashSession) -> None:
            # Do not parent to the view: tests may supply a non-QObject double.
            super().__init__(QApplication.instance())
            self._owner = owner
            self._armed = False

        def eventFilter(self, obj, event):  # noqa: N802 - Qt API
            if event.type() == QEvent.Paint and not self._armed:
                self._armed = True
                # Queued after the real paint returns — not construct/show/hello.
                QTimer.singleShot(0, self._owner.note_first_paint)
            return False

    watcher = _PaintWatcher(session)
    splash.installEventFilter(watcher)
    return watcher


def create_splash_application():
    """Create this process's ``QApplication`` after high-DPI setup.

    The splash child is a separate process. Attributes set later in the parent
    do not resize this window.
    """

    from mf4_analyzer.qt_app_support import configure_high_dpi
    from PyQt5.QtWidgets import QApplication

    configure_high_dpi()
    return QApplication.instance() or QApplication([])


def child_main(argv: list[str] | None = None) -> int:
    """Entry for ``--startup-splash-child``. Returns a process exit code."""

    argv_list = list(sys.argv[1:] if argv is None else argv)
    reject_abbreviated_splash_flags(argv_list)
    parser = _WindowedArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument(SPLASH_CHILD_FLAG, action="store_true", required=True)
    parser.add_argument(SPLASH_SESSION_FLAG, required=True)
    parser.add_argument(SPLASH_ENDPOINT_FLAG, required=True)
    parser.add_argument(SPLASH_TOKEN_FLAG, required=True)
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as stopped:
        code = stopped.code
        return 2 if code is None else int(code)

    try:
        host, port = parse_endpoint(args.startup_splash_endpoint)
    except ValueError:
        return 2

    session = _SplashSession(
        session=str(args.startup_splash_session),
        token=str(args.startup_splash_token),
        host=host,
        port=port,
    )
    try:
        session.connect()
    except OSError as exc:
        _bounded_diagnostic(f"connect_failed:{exc}")
        return 1

    session.drain_pre_show()
    if session.should_suppress_show():
        session.shutdown()
        return 0

    # Qt / view imports stay below the connect gate so the import-closure probe
    # can prove the child entry stays light until a validated session exists.
    # High-DPI attributes must be set before this process creates QApplication;
    # the parent configures them only for its own later QApplication.
    app = create_splash_application()
    from PyQt5.QtCore import QTimer

    from mf4_analyzer.ui.startup_splash import StartupSplash

    def schedule(callback: Callable[[], None]) -> None:
        QTimer.singleShot(0, callback)

    session.bind_gui(app, schedule)

    if session.should_suppress_show():
        session.shutdown()
        return 0

    splash = StartupSplash()
    splash.set_reduced_motion(_system_reduced_motion())
    session.attach_splash(splash)
    session._paint_watcher = _install_paint_watcher(splash, session)

    # If finish/EOF arrived while constructing the view, never show.
    if session.should_suppress_show():
        session.shutdown()
        return 0

    splash.show()
    session.mark_shown()
    # User closing the panel only closes the panel; do not kill the parent.
    _install_close_watcher(splash, session)

    code = app.exec_()
    session.shutdown()
    return int(code or 0)


def _install_close_watcher(splash, session: _SplashSession) -> None:
    from PyQt5.QtCore import QEvent, QObject
    from PyQt5.QtWidgets import QApplication

    class _CloseWatcher(QObject):
        def __init__(self) -> None:
            super().__init__(QApplication.instance())
            self._notified = False

        def eventFilter(self, obj, event):  # noqa: N802 - Qt API
            if self._notified:
                return False
            if event.type() in (QEvent.Close, QEvent.Hide):
                if session.finished:
                    return False
                self._notified = True
                session.notify_user_closed()
            return False

    watcher = _CloseWatcher()
    splash.installEventFilter(watcher)


def _bounded_diagnostic(detail: str) -> None:
    """Pre-connect failures cannot block on stdout; keep a short log line."""

    logger.warning("startup splash child: %s", detail)
    # Best-effort stderr for source runs; windowed EXE may have no streams.
    stream = getattr(sys, "stderr", None)
    writer = getattr(stream, "write", None)
    if callable(writer):
        try:
            writer(f"startup splash child: {detail}\n")
        except (OSError, ValueError, AttributeError):
            return


if __name__ == "__main__":
    raise SystemExit(child_main())
