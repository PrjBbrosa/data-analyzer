"""Owner tests for the parent startup-splash feedback controller."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from mf4_analyzer.startup_feedback import (
    ENV_SPLASH,
    FINISH_REAP_TIMEOUT_S,
    MSG_PAINTED,
    StartupFeedback,
    build_child_command,
    child_environment,
    splash_enabled,
)

ROOT = Path(__file__).resolve().parents[1]


def _wait_until(predicate, timeout_s: float = 5.0, interval_s: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def _peer_script() -> str:
    """Minimal splash peer: speak the protocol without Qt."""

    return r"""
import json
import os
import socket
import sys
import time

argv = sys.argv[1:]
flags = {}
i = 0
standalone = {"--startup-splash-child"}
while i < len(argv):
    key = argv[i]
    if key in standalone:
        flags[key] = True
        i += 1
        continue
    if key.startswith("--") and i + 1 < len(argv):
        flags[key] = argv[i + 1]
        i += 2
    else:
        i += 1
session = flags["--startup-splash-session"]
token = flags["--startup-splash-token"]
endpoint = flags["--startup-splash-endpoint"]
host, port_text = endpoint.split(":", 1)
port = int(port_text)
mode = os.environ.get("SPLASH_PEER_MODE", "normal")
delay = float(os.environ.get("SPLASH_PEER_DELAY", "0"))
if delay:
    time.sleep(delay)
conn = socket.create_connection((host, port), timeout=5.0)
conn.settimeout(0.2)

def send(payload):
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
    conn.sendall(raw)

send({"type": "hello", "session": session, "seq": 1, "stage": None, "slow": None, "detail": token})
if mode == "hang_after_hello":
    while True:
        time.sleep(0.2)
seq = 1
buf = bytearray()
painted = False
while True:
    try:
        chunk = conn.recv(1024)
    except socket.timeout:
        chunk = b""
        if mode == "idle":
            continue
    if not chunk:
        # Parent EOF / hard close
        sys.exit(0)
    buf.extend(chunk)
    while True:
        nl = buf.find(b"\n")
        if nl < 0:
            break
        line = bytes(buf[:nl])
        del buf[: nl + 1]
        if not line.strip():
            continue
        msg = json.loads(line.decode("utf-8"))
        if msg.get("session") != session:
            continue
        if msg.get("type") == "finish":
            sys.exit(0)
        if msg.get("type") == "stage" and not painted:
            painted = True
            seq += 1
            send({"type": "painted", "session": session, "seq": seq, "stage": msg.get("stage"), "slow": msg.get("slow"), "detail": None})
"""


@pytest.fixture
def force_splash_env(monkeypatch):
    monkeypatch.setenv(ENV_SPLASH, "1")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("TRACELAB_LAYOUT_PROBE", raising=False)


def test_splash_enabled_matrix(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv(ENV_SPLASH, "auto")
    assert splash_enabled(hidden=False, layout_probe=False, platform="win32") is True
    assert splash_enabled(hidden=False, layout_probe=False, platform="darwin") is False
    assert splash_enabled(hidden=True, layout_probe=False, platform="win32") is False
    assert splash_enabled(hidden=False, layout_probe=True, platform="win32") is False

    monkeypatch.setenv(ENV_SPLASH, "0")
    assert splash_enabled(hidden=False, layout_probe=False, platform="win32") is False
    monkeypatch.setenv(ENV_SPLASH, "false")
    assert splash_enabled(hidden=False, layout_probe=False, platform="win32") is False

    monkeypatch.setenv(ENV_SPLASH, "1")
    assert splash_enabled(hidden=False, layout_probe=False, platform="darwin") is True
    assert splash_enabled(hidden=True, layout_probe=False, platform="darwin") is False
    assert splash_enabled(hidden=False, layout_probe=True, platform="darwin") is False

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert splash_enabled(hidden=False, layout_probe=False, platform="win32") is False
    assert (
        splash_enabled(
            hidden=False,
            layout_probe=False,
            platform="win32",
            allow_offscreen=True,
        )
        is True
    )


def test_import_startup_feedback_has_no_qt_side_effects():
    script = r"""
import json
import sys
assert "PyQt5" not in sys.modules
import mf4_analyzer.startup_feedback as mod
present = sorted(name for name in sys.modules if name == "PyQt5" or name.startswith("PyQt5."))
print(json.dumps({"present": present, "has_start": hasattr(mod, "StartupFeedback")}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "TMPDIR": "/tmp",
            "MPLCONFIGDIR": "/tmp",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["present"] == []
    assert payload["has_start"] is True


def test_child_environment_strips_timing_probe_vars(monkeypatch):
    monkeypatch.setenv("TRACELAB_STARTUP_TIMING", "1")
    monkeypatch.setenv("TRACELAB_STARTUP_RUN_ID", "run")
    monkeypatch.setenv("TRACELAB_STARTUP_PERF_DIR", "/tmp/x")
    monkeypatch.setenv("TRACELAB_STARTUP_PROBE_HOST", "127.0.0.1")
    monkeypatch.setenv("TRACELAB_STARTUP_PROBE_PORT", "9")
    monkeypatch.setenv("TRACELAB_STARTUP_EXIT_AFTER_PROBE", "1")
    monkeypatch.setenv("PYINSTALLER_RESET_ENVIRONMENT", "keep-me")
    env = child_environment()
    for name in (
        "TRACELAB_STARTUP_TIMING",
        "TRACELAB_STARTUP_RUN_ID",
        "TRACELAB_STARTUP_PERF_DIR",
        "TRACELAB_STARTUP_PROBE_HOST",
        "TRACELAB_STARTUP_PROBE_PORT",
        "TRACELAB_STARTUP_EXIT_AFTER_PROBE",
    ):
        assert name not in env
    assert env.get("PYINSTALLER_RESET_ENVIRONMENT") == "keep-me"
    assert env[ENV_SPLASH] == "0"


def test_build_child_command_source_and_frozen():
    source = build_child_command(
        session="s",
        endpoint="127.0.0.1:1",
        token="t",
        frozen=False,
        executable="/bin/python",
        launcher=ROOT / "MF4 Data Analyzer V1.py",
    )
    assert source[0] == "/bin/python"
    assert source[1].endswith("MF4 Data Analyzer V1.py")
    assert "--startup-splash-child" in source
    frozen = build_child_command(
        session="s",
        endpoint="127.0.0.1:1",
        token="t",
        frozen=True,
        executable="/apps/TraceLab.exe",
    )
    assert frozen == [
        "/apps/TraceLab.exe",
        "--startup-splash-child",
        "--startup-splash-session",
        "s",
        "--startup-splash-endpoint",
        "127.0.0.1:1",
        "--startup-splash-token",
        "t",
    ]


def _start_with_peer(monkeypatch, force_splash_env, peer_env: dict[str, str] | None = None):
    feedback = StartupFeedback()
    peer_path_holder: dict[str, list[str]] = {}

    def fake_spawn(self):
        assert self._endpoint is not None
        command = [
            sys.executable,
            "-c",
            _peer_script(),
            "--startup-splash-child",
            "--startup-splash-session",
            self._session,
            "--startup-splash-endpoint",
            self._endpoint,
            "--startup-splash-token",
            self._token,
        ]
        env = child_environment()
        if peer_env:
            env.update(peer_env)
        peer_path_holder["command"] = command
        self._proc = subprocess.Popen(
            command,
            env=env,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    monkeypatch.setattr(StartupFeedback, "_spawn_child", fake_spawn)
    feedback.start(allow_offscreen=True)
    return feedback


def test_publish_out_of_order_and_finish_is_terminal(monkeypatch, force_splash_env):
    feedback = _start_with_peer(monkeypatch, force_splash_env)
    try:
        assert _wait_until(lambda: feedback.painted or feedback._hello_ok)
        feedback.publish("preparing_workspace")
        feedback.publish("preparing")
        feedback.set_slow(True)
        feedback.finish()
        feedback.publish("loading_components")  # ignored after finish
        feedback.finish()  # idempotent
        assert _wait_until(
            lambda: feedback.process is None or feedback.process.poll() is not None
        )
        assert feedback._finished
    finally:
        feedback.close()
        _reap(feedback)


def test_finish_before_child_connect_suppresses_late_show(monkeypatch, force_splash_env):
    """Parent finishes while the peer is still delayed; child must exit on finish."""

    feedback = _start_with_peer(
        monkeypatch,
        force_splash_env,
        peer_env={"SPLASH_PEER_DELAY": "0.4"},
    )
    try:
        feedback.finish()
        assert _wait_until(
            lambda: feedback.process is None or feedback.process.poll() is not None,
            timeout_s=5.0,
        )
    finally:
        feedback.close()
        _reap(feedback)


def test_spawn_failure_degrades_without_raising(monkeypatch, force_splash_env):
    def boom(self):
        raise OSError("spawn denied")

    monkeypatch.setattr(StartupFeedback, "_spawn_child", boom)
    feedback = StartupFeedback()
    feedback.start(allow_offscreen=True)
    assert feedback.degraded
    feedback.publish("preparing")
    feedback.finish()
    feedback.close()


def test_parent_eof_lets_peer_exit(monkeypatch, force_splash_env):
    feedback = _start_with_peer(monkeypatch, force_splash_env)
    try:
        assert _wait_until(lambda: feedback._hello_ok)
        proc = feedback.process
        assert proc is not None
        with feedback._lock:
            if feedback._conn is not None:
                feedback._conn.shutdown(socket.SHUT_RDWR)
                feedback._conn.close()
                feedback._conn = None
        assert _wait_until(lambda: proc.poll() is not None, timeout_s=5.0)
    finally:
        feedback.close()
        _reap(feedback)


def test_parent_hard_kill_closes_child_socket(monkeypatch, force_splash_env, tmp_path):
    """Simulate abrupt parent death: drop the listen/conn without graceful finish."""

    feedback = _start_with_peer(monkeypatch, force_splash_env)
    try:
        assert _wait_until(lambda: feedback._hello_ok)
        proc = feedback.process
        assert proc is not None
        # Hard-kill style: tear sockets down from another thread without finish().
        with feedback._lock:
            listen = feedback._listen
            conn = feedback._conn
            feedback._listen = None
            feedback._conn = None
            feedback._stop.set()
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        if listen is not None:
            try:
                listen.close()
            except OSError:
                pass
        assert _wait_until(lambda: proc.poll() is not None, timeout_s=5.0)
    finally:
        try:
            feedback.close()
        finally:
            _reap(feedback)


def test_unresponsive_child_is_reaped_after_finish(monkeypatch, force_splash_env):
    feedback = _start_with_peer(
        monkeypatch,
        force_splash_env,
        peer_env={"SPLASH_PEER_MODE": "hang_after_hello"},
    )
    try:
        assert _wait_until(lambda: feedback._hello_ok)
        proc = feedback.process
        assert proc is not None
        feedback.finish()
        assert _wait_until(
            lambda: proc.poll() is not None,
            timeout_s=FINISH_REAP_TIMEOUT_S + 3.0,
        )
    finally:
        feedback.close()
        _reap(feedback)


def test_two_sessions_do_not_cross_talk(monkeypatch, force_splash_env):
    first = _start_with_peer(monkeypatch, force_splash_env)
    second = _start_with_peer(monkeypatch, force_splash_env)
    try:
        assert _wait_until(lambda: first._hello_ok and second._hello_ok)
        assert first.session != second.session
        # Cross-session painted must be ignored (do not hold the controller lock:
        # _handle_message acquires it itself).
        first._handle_message(
            {
                "type": MSG_PAINTED,
                "session": second.session,
                "seq": 99,
                "stage": None,
                "slow": None,
                "detail": None,
            }
        )
        assert first.painted is False
        first.publish("preparing")
        assert _wait_until(lambda: first.painted)
        second.finish()
        first.finish()
    finally:
        first.close()
        second.close()
        _reap(first)
        _reap(second)


def test_close_and_finish_are_idempotent(monkeypatch, force_splash_env):
    feedback = _start_with_peer(monkeypatch, force_splash_env)
    try:
        assert _wait_until(lambda: feedback._hello_ok)
        feedback.finish()
        feedback.finish()
        feedback.close()
        feedback.close()
    finally:
        _reap(feedback)


def test_disabled_start_creates_no_socket(monkeypatch):
    monkeypatch.setenv(ENV_SPLASH, "0")
    feedback = StartupFeedback()
    feedback.start(allow_offscreen=True)
    assert feedback.degraded
    assert feedback._listen is None
    assert feedback.process is None
    feedback.finish()
    feedback.close()


def test_painted_and_closed_forward_diagnostics_on_io_path(
    monkeypatch, force_splash_env
):
    """Controller must forward on the I/O path when painted/closed arrive.

    Must not wait for main-window first_frame / interactive probe connect.
    """

    calls: list[tuple[str, dict]] = []

    def fake_record(event, *, session=None, detail=None):
        calls.append((str(event), {"session": session, "detail": detail}))

    monkeypatch.setattr(
        "mf4_analyzer.startup_timing.record_splash_event",
        fake_record,
    )
    feedback = StartupFeedback()
    # Drive the message handler directly: this is the I/O-thread entry.
    feedback._hello_ok = True
    feedback._handle_message(
        {
            "type": MSG_PAINTED,
            "session": feedback.session,
            "seq": 2,
            "stage": "preparing",
            "slow": False,
            "detail": {"frames": 1, "child_mono_ns": 10**15},
        }
    )
    assert feedback.painted is True
    assert calls and calls[0][0] == "splash_painted"
    assert calls[0][1]["session"] == feedback.session
    assert calls[0][1]["detail"]["child_mono_ns"] == 10**15

    feedback._handle_message(
        {
            "type": "closed",
            "session": feedback.session,
            "seq": 3,
            "stage": None,
            "slow": None,
            "detail": None,
        }
    )
    assert feedback.child_closed is True
    assert [name for name, _ in calls] == ["splash_painted", "splash_closed"]

    # Idempotent: duplicate painted/closed must not re-forward.
    feedback._handle_message(
        {
            "type": MSG_PAINTED,
            "session": feedback.session,
            "seq": 4,
            "stage": None,
            "slow": None,
            "detail": None,
        }
    )
    assert [name for name, _ in calls] == ["splash_painted", "splash_closed"]


def _reap(feedback: StartupFeedback) -> None:
    proc = feedback.process
    if proc is None:
        return
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
