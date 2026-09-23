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
    MSG_FINISH,
    MSG_HELLO,
    MSG_PAINTED,
    MSG_STAGE,
    decode_frames,
    encode_frame,
)
from mf4_analyzer.startup_splash_child import (
    _SplashSession,
    child_main,
    reject_abbreviated_splash_flags,
)

ROOT = Path(__file__).resolve().parents[1]


class _FakeSplash:
    def __init__(self):
        self.stages: list[str] = []
        self.slow_values: list[bool] = []
        self.reduced_motion: list[bool] = []
        self.shown = False
        self.closed = False
        self._filters: list = []

    def set_stage(self, stage: str) -> None:
        self.stages.append(stage)

    def set_slow(self, slow: bool) -> None:
        self.slow_values.append(bool(slow))

    def set_reduced_motion(self, enabled: bool) -> None:
        self.reduced_motion.append(bool(enabled))

    def show(self) -> None:
        self.shown = True
        # Simulate a real paint arriving after show returns.
        from PyQt5.QtCore import QEvent, QTimer
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        event = QEvent(QEvent.Paint)
        for watcher in list(self._filters):
            watcher.eventFilter(self, event)
        if app is not None:
            # Escape hatch so a missed finish/painted path cannot hang pytest.
            QTimer.singleShot(0, app.quit)
            QTimer.singleShot(2000, app.quit)

    def close_splash(self) -> None:
        self.closed = True

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
            time.sleep(0.3)
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

    def parent():
        conn, _ = listen.accept()
        buf = bytearray()
        conn.settimeout(3.0)
        try:
            while not seen_painted.is_set():
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
            time.sleep(0.2)
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
    assert code == 0
    widget = holder["widget"]
    assert widget.shown is True
    assert "loading_components" in widget.stages
    assert widget.closed is True


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
    # Hold the connection open; child will drain_pre_show then import Qt/view.
    # We close immediately after hello so child suppresses show before view... 
    # Actually we need to inspect modules AFTER connect and BEFORE view.
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
# Also reject MainWindow symbol path commonly loaded via ui package.
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
