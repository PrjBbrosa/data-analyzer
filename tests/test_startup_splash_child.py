"""Owner tests for the hidden startup-splash child entry."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest

from mf4_analyzer.startup_feedback import (
    HIDDEN_FINISH_CLOSE,
    HIDDEN_NEVER_SHOWN,
    HIDDEN_USER_CLOSE,
    MSG_FINISH,
    MSG_HELLO,
    MSG_HIDDEN,
    MSG_PAINTED,
    MSG_STAGE,
    decode_frames,
    encode_frame,
)
from mf4_analyzer.startup_splash_child import (
    _SplashSession,
    child_main,
    create_gui_dispatcher,
    create_splash_application,
    reject_abbreviated_splash_flags,
)

ROOT = Path(__file__).resolve().parents[1]


def test_first_paint_reports_the_splash_screen():
    session = _SplashSession(
        session="screen",
        token="tok",
        host="127.0.0.1",
        port=1,
    )
    sent: list[dict] = []
    session._send = sent.append  # type: ignore[method-assign]

    class _Splash:
        def launch_screen_rect(self):
            return (-1920, 0, 1920, 1080)

    session._splash = _Splash()
    session.note_first_paint()
    assert sent[-1]["type"] == MSG_PAINTED
    assert sent[-1]["detail"] == {"screen": [-1920, 0, 1920, 1080]}


def test_splash_application_configures_high_dpi_before_qapplication():
    import inspect

    source = inspect.getsource(create_splash_application)
    assert source.index("configure_high_dpi()") < source.index("QApplication(")


class _FakeSplash:
    def __init__(self):
        self.stages: list[str] = []
        self.slow_values: list[bool] = []
        self.reduced_motion: list[bool] = []
        self.shown = False
        self.closed = False
        self._filters: list = []
        self._visible = False

    def set_stage(self, stage: str) -> None:
        self.stages.append(stage)

    def set_slow(self, slow: bool) -> None:
        self.slow_values.append(bool(slow))

    def set_reduced_motion(self, enabled: bool) -> None:
        self.reduced_motion.append(bool(enabled))

    def show(self) -> None:
        self.shown = True
        self._visible = True
        # Simulate a real paint arriving after show returns.
        from PyQt5.QtCore import QEvent

        event = QEvent(QEvent.Paint)
        for watcher in list(self._filters):
            watcher.eventFilter(self, event)
        # Do NOT quit the host QApplication from show — that would fake finish
        # success and poison later qtbot tests that share the process app.

    def isVisible(self) -> bool:  # noqa: N802 - Qt API
        return bool(self._visible) and not self.closed

    def close_splash(self) -> None:
        self.closed = True
        self._visible = False

    def installEventFilter(self, watcher) -> None:  # noqa: N802 - Qt API
        self._filters.append(watcher)


def _install_fake_splash(monkeypatch):
    splash_mod = ModuleType("mf4_analyzer.ui.startup_splash")
    holder: dict[str, _FakeSplash] = {}

    def factory():
        widget = _FakeSplash()
        holder["widget"] = widget
        return widget

    splash_mod.StartupSplash = factory
    monkeypatch.setitem(sys.modules, "mf4_analyzer.ui.startup_splash", splash_mod)
    return holder


def test_reject_abbreviated_splash_flags():
    with pytest.raises(SystemExit) as stopped:
        reject_abbreviated_splash_flags(["--startup-splash-ch", "x"])
    assert stopped.value.code == 2


def test_child_main_rejects_illegal_endpoint_without_gui(monkeypatch):
    holder = _install_fake_splash(monkeypatch)
    code = child_main(
        [
            "--startup-splash-child",
            "--startup-splash-session",
            "s",
            "--startup-splash-endpoint",
            "0.0.0.0:9",
            "--startup-splash-token",
            "t",
        ]
    )
    assert code == 0 or code == 2
    assert code == 2
    assert "widget" not in holder


def test_finish_before_show_never_shows_end_to_end(monkeypatch):
    holder = _install_fake_splash(monkeypatch)
    listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen.bind(("127.0.0.1", 0))
    listen.listen(1)
    host, port = listen.getsockname()[:2]
    session = "sess-early"
    token = "tok-early"
    done = threading.Event()
    hidden_reason: list[str] = []

    def parent():
        conn, _ = listen.accept()
        try:
            buf = bytearray()
            conn.settimeout(3.0)
            while b"\n" not in buf:
                buf.extend(conn.recv(1024))
            decode_frames(buf)
            conn.sendall(
                encode_frame(
                    {
                        "type": MSG_FINISH,
                        "session": session,
                        "seq": 1,
                        "stage": None,
                        "slow": None,
                        "detail": None,
                    }
                )
            )
            # Child may ACK never_shown before exiting.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                try:
                    chunk = conn.recv(1024)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf.extend(chunk)
                for message in decode_frames(buf):
                    if message.get("type") == MSG_HIDDEN:
                        hidden_reason.append(str(message.get("detail")))
            time.sleep(0.1)
        finally:
            conn.close()
            listen.close()
            done.set()

    threading.Thread(target=parent, daemon=True).start()
    code = child_main(
        [
            "--startup-splash-child",
            "--startup-splash-session",
            session,
            "--startup-splash-endpoint",
            f"{host}:{port}",
            "--startup-splash-token",
            token,
        ]
    )
    assert done.wait(5)
    assert code == 0
    widget = holder.get("widget")
    if widget is not None:
        assert widget.shown is False
    if hidden_reason:
        assert hidden_reason[0] == HIDDEN_NEVER_SHOWN


def test_child_receives_stages_then_finish(monkeypatch):
    holder = _install_fake_splash(monkeypatch)
    listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen.bind(("127.0.0.1", 0))
    listen.listen(1)
    host, port = listen.getsockname()[:2]
    session = "sess-flow"
    token = "tok-flow"
    seen_painted = threading.Event()
    seen_hidden = threading.Event()
    hidden_detail: list[str] = []

    def parent():
        conn, _ = listen.accept()
        buf = bytearray()
        conn.settimeout(3.0)
        try:
            while not seen_hidden.is_set():
                try:
                    chunk = conn.recv(1024)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf.extend(chunk)
                for message in decode_frames(buf):
                    if message.get("type") == MSG_HELLO:
                        conn.sendall(
                            encode_frame(
                                {
                                    "type": MSG_STAGE,
                                    "session": session,
                                    "seq": 1,
                                    "stage": "loading_components",
                                    "slow": False,
                                    "detail": None,
                                }
                            )
                        )
                    if message.get("type") == MSG_PAINTED:
                        seen_painted.set()
                        conn.sendall(
                            encode_frame(
                                {
                                    "type": MSG_FINISH,
                                    "session": session,
                                    "seq": 2,
                                    "stage": "loading_components",
                                    "slow": False,
                                    "detail": None,
                                }
                            )
                        )
                    if message.get("type") == MSG_HIDDEN:
                        hidden_detail.append(str(message.get("detail")))
                        seen_hidden.set()
            time.sleep(0.1)
        finally:
            conn.close()
            listen.close()

    threading.Thread(target=parent, daemon=True).start()
    code = child_main(
        [
            "--startup-splash-child",
            "--startup-splash-session",
            session,
            "--startup-splash-endpoint",
            f"{host}:{port}",
            "--startup-splash-token",
            token,
        ]
    )
    assert seen_painted.wait(5)
    assert seen_hidden.wait(5)
    assert code == 0
    widget = holder["widget"]
    assert widget.shown is True
    assert "loading_components" in widget.stages
    assert widget.closed is True
    assert hidden_detail == [HIDDEN_FINISH_CLOSE]
    # Hide happened before the ACK (closed flag set by close_splash).
    assert widget.isVisible() is False


def test_user_close_sends_hidden_after_hide(monkeypatch):
    holder = _install_fake_splash(monkeypatch)
    listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen.bind(("127.0.0.1", 0))
    listen.listen(1)
    host, port = listen.getsockname()[:2]
    session = "sess-user"
    token = "tok-user"
    seen_painted = threading.Event()
    seen_hidden = threading.Event()
    order: list[str] = []

    def parent():
        conn, _ = listen.accept()
        buf = bytearray()
        conn.settimeout(5.0)
        try:
            while not seen_hidden.is_set():
                try:
                    chunk = conn.recv(1024)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf.extend(chunk)
                for message in decode_frames(buf):
                    if message.get("type") == MSG_PAINTED:
                        seen_painted.set()
                        order.append("painted")
                        # Ask the child view to close as a user would.
                        # Delivered via Hide on the fake by calling close_splash
                        # from the child process once painted — parent just waits.
                    if message.get("type") == MSG_HIDDEN:
                        order.append(f"hidden:{message.get('detail')}")
                        seen_hidden.set()
        finally:
            conn.close()
            listen.close()

    threading.Thread(target=parent, daemon=True).start()

    # Patch close watcher path: after show+paint, simulate user close on GUI.

    def factory_with_user_close():
        widget = _FakeSplash()
        holder["widget"] = widget
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication

        def _user_close():
            from PyQt5.QtCore import QEvent

            event = QEvent(QEvent.Close)
            for watcher in list(widget._filters):
                watcher.eventFilter(widget, event)

        def show_and_schedule_close():
            _FakeSplash.show(widget)
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(50, _user_close)

        widget.show = show_and_schedule_close  # type: ignore[method-assign]
        return widget

    splash_mod = ModuleType("mf4_analyzer.ui.startup_splash")
    splash_mod.StartupSplash = factory_with_user_close
    monkeypatch.setitem(sys.modules, "mf4_analyzer.ui.startup_splash", splash_mod)

    code = child_main(
        [
            "--startup-splash-child",
            "--startup-splash-session",
            session,
            "--startup-splash-endpoint",
            f"{host}:{port}",
            "--startup-splash-token",
            token,
        ]
    )
    assert seen_hidden.wait(5)
    assert code == 0
    assert any(item.startswith("hidden:") for item in order)
    assert HIDDEN_USER_CLOSE in order[-1]
    widget = holder["widget"]
    assert widget.closed is True
    assert widget.isVisible() is False


def test_parent_eof_exits_child_without_atexit(monkeypatch):
    holder = _install_fake_splash(monkeypatch)
    listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen.bind(("127.0.0.1", 0))
    listen.listen(1)
    host, port = listen.getsockname()[:2]
    session = "sess-eof"
    token = "tok-eof"

    def parent():
        conn, _ = listen.accept()
        buf = bytearray()
        conn.settimeout(3.0)
        while b"\n" not in buf:
            buf.extend(conn.recv(1024))
        decode_frames(buf)
        # Abrupt EOF without finish.
        conn.close()
        listen.close()

    threading.Thread(target=parent, daemon=True).start()
    code = child_main(
        [
            "--startup-splash-child",
            "--startup-splash-session",
            session,
            "--startup-splash-endpoint",
            f"{host}:{port}",
            "--startup-splash-token",
            token,
        ]
    )
    assert code == 0
    widget = holder.get("widget")
    # May or may not construct depending on timing; must not hang.
    if widget is not None and widget.shown:
        assert widget.closed is True


def test_cross_session_message_does_not_mutate(monkeypatch):
    session = _SplashSession(
        session="alpha",
        token="tok",
        host="127.0.0.1",
        port=1,
    )
    session._handle_message(
        {
            "type": MSG_STAGE,
            "session": "beta",
            "seq": 1,
            "stage": "preparing",
            "slow": True,
            "detail": None,
        }
    )
    assert session._stage is None
    assert session._slow is False
    session._handle_message(
        {
            "type": MSG_FINISH,
            "session": "beta",
            "seq": 2,
            "stage": None,
            "slow": None,
            "detail": None,
        }
    )
    assert session.finished is False


def test_reader_dispatches_stage_finish_eof_on_gui_thread(qtbot):
    """Real Python reader → GUI dispatcher: callbacks run on the GUI thread."""
    from PyQt5.QtCore import QThread
    from PyQt5.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    qtbot.addWidget(parent)
    gui_thread = app.thread()

    session = _SplashSession(
        session="disp",
        token="tok",
        host="127.0.0.1",
        port=1,
    )
    dispatcher = create_gui_dispatcher(session, parent=parent)

    class _NoQuitApp:
        """Avoid app.quit() tearing down the shared pytest QApplication."""

        def quit(self) -> None:
            return None

    session.bind_gui(_NoQuitApp(), dispatcher)

    seen: dict[str, object] = {"ops": []}

    original = session.handle_gui_command

    def wrapped(command):
        seen["thread"] = QThread.currentThread()
        seen["op"] = command.get("op")
        seen["ops"].append(command.get("op"))  # type: ignore[union-attr]
        original(command)

    session.handle_gui_command = wrapped  # type: ignore[method-assign]

    def reader_stage():
        session._handle_message(
            {
                "type": MSG_STAGE,
                "session": "disp",
                "seq": 1,
                "stage": "preparing",
                "slow": False,
                "detail": None,
            }
        )

    threading.Thread(target=reader_stage, daemon=True).start()
    qtbot.waitUntil(lambda: "stage" in seen["ops"], timeout=2000)  # type: ignore[arg-type]
    assert seen["thread"] is gui_thread

    def reader_finish():
        session._handle_message(
            {
                "type": MSG_FINISH,
                "session": "disp",
                "seq": 2,
                "stage": None,
                "slow": None,
                "detail": None,
            }
        )

    threading.Thread(target=reader_finish, daemon=True).start()
    qtbot.waitUntil(lambda: "finish" in seen["ops"], timeout=2000)  # type: ignore[arg-type]
    assert seen["thread"] is gui_thread

    session2 = _SplashSession(session="disp2", token="t", host="127.0.0.1", port=1)
    dispatcher2 = create_gui_dispatcher(session2, parent=parent)
    session2.bind_gui(_NoQuitApp(), dispatcher2)
    real_handle = session2.handle_gui_command

    def wrap_eof(command):
        assert QThread.currentThread() is gui_thread
        real_handle(command)

    session2.handle_gui_command = wrap_eof  # type: ignore[method-assign]
    eof_ops: list[str] = []

    def wrap_eof_track(command):
        assert QThread.currentThread() is gui_thread
        eof_ops.append(str(command.get("op")))
        real_handle(command)

    session2.handle_gui_command = wrap_eof_track  # type: ignore[method-assign]

    def reader_eof():
        session2._eof = True
        session2._post_gui({"op": "shutdown", "reason": HIDDEN_NEVER_SHOWN})

    threading.Thread(target=reader_eof, daemon=True).start()
    qtbot.waitUntil(lambda: "shutdown" in eof_ops, timeout=2000)

    dispatcher.deleteLater()
    dispatcher2.deleteLater()
    qtbot.wait(20)


def test_child_entry_import_closure_stays_light_before_view():
    script = r"""
import json
import socket
import sys
import threading
import time

FORBIDDEN = (
    "mf4_analyzer.ui.main_window",
    "mf4_analyzer.ui.MainWindow",
    "pyqtgraph",
    "numpy",
    "pandas",
    "scipy",
    "asammdf",
    "mf4_analyzer.io.loader",
    "mf4_analyzer.acquisition",
    "mf4_analyzer.ui.widgets",
    "mf4_analyzer.ui_kit",
)

listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listen.bind(("127.0.0.1", 0))
listen.listen(1)
host, port = listen.getsockname()[:2]
session = "sess-light"
token = "tok-light"
ready = {"conn": None}

def parent():
    conn, _ = listen.accept()
    ready["conn"] = conn
    buf = bytearray()
    conn.settimeout(3.0)
    while b"\n" not in buf:
        buf.extend(conn.recv(1024))
    time.sleep(0.5)
    conn.close()
    listen.close()

threading.Thread(target=parent, daemon=True).start()

from mf4_analyzer.startup_splash_child import _SplashSession
sess = _SplashSession(session=session, token=token, host=host, port=port)
sess.connect()
sess.drain_pre_show(0.05)
present = sorted(
    name for name in FORBIDDEN
    if name in sys.modules or any(m == name or m.startswith(name + ".") for m in sys.modules)
)
ui_main = [m for m in sys.modules if "main_window" in m or m.endswith(".MainWindow")]
print(json.dumps({"present": present, "main_window_modules": ui_main, "eof": sess.eof or sess.finished}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "TMPDIR": "/tmp",
            "MPLCONFIGDIR": "/tmp",
            "QT_QPA_PLATFORM": "offscreen",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["present"] == [], payload
    assert payload["main_window_modules"] == [], payload


def test_child_main_without_console_streams(monkeypatch):
    holder = _install_fake_splash(monkeypatch)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    code = child_main(
        [
            "--startup-splash-child",
            "--startup-splash-session",
            "s",
            "--startup-splash-endpoint",
            "not-an-endpoint",
            "--startup-splash-token",
            "t",
        ]
    )
    assert code == 2
    assert "widget" not in holder


def test_protocol_error_exits(monkeypatch):
    holder = _install_fake_splash(monkeypatch)
    listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen.bind(("127.0.0.1", 0))
    listen.listen(1)
    host, port = listen.getsockname()[:2]
    session = "sess-proto"
    token = "tok-proto"

    def parent():
        conn, _ = listen.accept()
        buf = bytearray()
        conn.settimeout(3.0)
        while b"\n" not in buf:
            buf.extend(conn.recv(1024))
        decode_frames(buf)
        conn.sendall(b"{not-json\n")
        time.sleep(0.2)
        conn.close()
        listen.close()

    threading.Thread(target=parent, daemon=True).start()
    code = child_main(
        [
            "--startup-splash-child",
            "--startup-splash-session",
            session,
            "--startup-splash-endpoint",
            f"{host}:{port}",
            "--startup-splash-token",
            token,
        ]
    )
    assert code == 0
    widget = holder.get("widget")
    if widget is not None:
        assert widget.shown is False or widget.closed is True
