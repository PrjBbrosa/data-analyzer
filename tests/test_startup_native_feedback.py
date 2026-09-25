"""Native splash session: one pipe owner, no Qt child, no fake connection."""
from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading
import time
from pathlib import Path

from mf4_analyzer.startup_feedback import (
    StartupFeedback,
    create_startup_feedback,
    encode_frame,
    resolve_startup_backend,
)
from mf4_analyzer.startup_native_feedback import NativeStartupFeedback

ROOT = Path(__file__).resolve().parents[1]


def _pair():
    app_read, launcher_write = os.pipe()
    launcher_read, app_write = os.pipe()
    return app_read, app_write, launcher_read, launcher_write


def _install_session(monkeypatch, app_read, app_write, *, splash="1", backend="auto"):
    monkeypatch.setenv("TRACELAB_NATIVE_SPLASH_PROTOCOL", "1")
    monkeypatch.setenv("TRACELAB_NATIVE_SPLASH_SESSION", "sess-native")
    monkeypatch.setenv("TRACELAB_NATIVE_SPLASH_READ", str(app_read))
    monkeypatch.setenv("TRACELAB_NATIVE_SPLASH_WRITE", str(app_write))
    monkeypatch.setenv("TRACELAB_STARTUP_SPLASH", splash)
    monkeypatch.setenv("TRACELAB_STARTUP_BACKEND", backend)
    os.set_inheritable(app_read, True)
    os.set_inheritable(app_write, True)


def _close_many(*fds: int) -> None:
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass


def test_import_native_feedback_does_not_pull_qt():
    script = r"""
import json, sys
assert "PyQt5" not in sys.modules
import mf4_analyzer.startup_native_feedback as mod
import mf4_analyzer.startup_visual_contract as contract
present = sorted(name for name in sys.modules if name == "PyQt5" or name.startswith("PyQt5.") or name.startswith("mf4_analyzer.ui"))
print(json.dumps({"present": present, "native": hasattr(mod, "NativeStartupFeedback"), "tips": len(contract.TIPS)}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "TMPDIR": "/tmp", "MPLCONFIGDIR": "/tmp"},
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["present"] == []
    assert payload["native"] is True
    assert payload["tips"] == 26


def test_verified_session_adopts_pipes_and_does_not_spawn_a_child(monkeypatch):
    app_read, app_write, launcher_read, launcher_write = _pair()
    try:
        _install_session(monkeypatch, app_read, app_write)
        feedback = create_startup_feedback()
        assert isinstance(feedback, NativeStartupFeedback)
        assert feedback.process is None
        assert "TRACELAB_NATIVE_SPLASH_SESSION" not in os.environ
        feedback.start()
        assert os.get_inheritable(app_read) is False
        assert os.get_inheritable(app_write) is False
        feedback.publish("loading_components")
        readable, _, _ = select.select([launcher_read], [], [], 1.0)
        assert readable
        raw = os.read(launcher_read, 4096)
        message = json.loads(raw.splitlines()[0])
        assert message["type"] == "stage"
        assert message["stage"] == "loading_components"
        assert message["session"] == "sess-native"
        os.write(
            launcher_write,
            encode_frame(
                {
                    "v": 1,
                    "session": "sess-native",
                    "seq": 1,
                    "type": "presented",
                    "screen": [10, 20, 800, 600],
                }
            ),
        )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and feedback.launch_screen is None:
            time.sleep(0.01)
        assert feedback.launch_screen == (10, 20, 800, 600)
        assert feedback.snapshot()["child_exit_code"] is None
    finally:
        feedback.close()
        _close_many(launcher_read, launcher_write)


def test_hidden_ack_is_once_and_a_late_copy_does_not_reveal_again(monkeypatch):
    app_read, app_write, launcher_read, launcher_write = _pair()
    feedback = None
    try:
        _install_session(monkeypatch, app_read, app_write)
        feedback = NativeStartupFeedback(hidden_ack_timeout_s=0.2, handover_timeout_s=0.5)
        reveals = []
        feedback.add_listener(reveals.append)
        feedback.start()
        feedback.finish()
        os.write(
            launcher_write,
            encode_frame(
                {
                    "v": 1,
                    "session": feedback.session,
                    "seq": 2,
                    "type": "hidden",
                    "reason": "finish_close",
                }
            ),
        )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not reveals:
            time.sleep(0.01)
        assert len(reveals) == 1
        assert reveals[0]["event"] == "can_reveal"
        assert reveals[0]["hidden"] is True
        assert reveals[0]["handover_failed"] is False
        assert reveals[0]["child_exit_code"] is None
        os.write(
            launcher_write,
            encode_frame(
                {
                    "v": 1,
                    "session": feedback.session,
                    "seq": 3,
                    "type": "hidden",
                    "reason": "user_close",
                }
            ),
        )
        time.sleep(0.05)
        assert len(reveals) == 1
        assert feedback.hidden_reason == "finish_close"
    finally:
        if feedback is not None:
            feedback.close()
        _close_many(launcher_read, launcher_write)


def test_silent_launcher_records_handover_failure_without_a_second_panel(monkeypatch):
    app_read, app_write, launcher_read, launcher_write = _pair()
    feedback = None
    try:
        _install_session(monkeypatch, app_read, app_write)
        feedback = NativeStartupFeedback(hidden_ack_timeout_s=0.05, handover_timeout_s=0.15)
        reveals = []
        feedback.add_listener(reveals.append)
        feedback.start()
        feedback.finish()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not reveals:
            time.sleep(0.01)
        assert len(reveals) == 1
        assert reveals[0]["handover_failed"] is True
        assert feedback.process is None
    finally:
        if feedback is not None:
            feedback.close()
        _close_many(launcher_read, launcher_write)


def test_pipe_eof_before_hide_reveals_without_a_qt_child(monkeypatch):
    app_read, app_write, launcher_read, launcher_write = _pair()
    feedback = None
    try:
        _install_session(monkeypatch, app_read, app_write)
        feedback = NativeStartupFeedback()
        reveals = []
        feedback.add_listener(reveals.append)
        feedback.start()
        os.close(launcher_write)
        launcher_write = -1
        feedback.finish()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not reveals:
            time.sleep(0.01)
        assert len(reveals) == 1
        assert reveals[0]["handover_failed"] is True
        assert feedback.process is None
    finally:
        if feedback is not None:
            feedback.close()
        _close_many(launcher_read, launcher_write)


def test_splash_zero_closes_the_native_channel_and_skips_qt(monkeypatch):
    app_read, app_write, launcher_read, launcher_write = _pair()
    try:
        _install_session(monkeypatch, app_read, app_write, splash="0", backend="native")
        assert resolve_startup_backend() == "none"
        feedback = create_startup_feedback()
        assert isinstance(feedback, StartupFeedback)
        assert not isinstance(feedback, NativeStartupFeedback)
        try:
            os.fstat(app_read)
            closed = False
        except OSError:
            closed = True
        assert closed
        assert "TRACELAB_NATIVE_SPLASH_READ" not in os.environ
        feedback.start()
        assert feedback.snapshot()["fail_reason"] == "disabled"
        assert feedback.degraded is True
    finally:
        feedback.close()
        _close_many(launcher_read, launcher_write)


def test_unverified_native_request_does_not_invent_a_session(monkeypatch):
    monkeypatch.setenv("TRACELAB_STARTUP_BACKEND", "native")
    monkeypatch.delenv("TRACELAB_NATIVE_SPLASH_PROTOCOL", raising=False)
    monkeypatch.setenv("TRACELAB_STARTUP_SPLASH", "1")
    feedback = create_startup_feedback()
    assert isinstance(feedback, StartupFeedback)
    assert not isinstance(feedback, NativeStartupFeedback)
    feedback.start(platform="win32", allow_offscreen=True)
    snap = feedback.snapshot()
    assert snap["fail_reason"] == "native_unverified"
    assert snap["degraded"] is True
    assert feedback.process is None
    feedback.close()


def test_explicit_qt_backend_drops_a_verified_native_session(monkeypatch):
    app_read, app_write, launcher_read, launcher_write = _pair()
    try:
        _install_session(monkeypatch, app_read, app_write, backend="qt")
        feedback = create_startup_feedback()
        assert type(feedback) is StartupFeedback
        try:
            os.fstat(app_write)
            closed = False
        except OSError:
            closed = True
        assert closed
    finally:
        _close_many(launcher_read, launcher_write)


def _native_feedback(monkeypatch):
    app_read, app_write, launcher_read, launcher_write = _pair()
    _install_session(monkeypatch, app_read, app_write)
    return NativeStartupFeedback(), (app_read, app_write, launcher_read, launcher_write)


def _native_hidden(feedback: NativeStartupFeedback, *, session: str | None = None) -> dict:
    return {
        "v": 1,
        "session": feedback.session if session is None else session,
        "seq": 2,
        "type": "hidden",
        "reason": "finish_close",
    }


def _native_reveals(bucket: list[dict]):
    def _callback(payload):
        if isinstance(payload, dict) and payload.get("event") == "can_reveal":
            bucket.append(dict(payload))

    return _callback


def test_native_late_listener_replays_can_reveal_once(monkeypatch):
    feedback, fds = _native_feedback(monkeypatch)
    try:
        feedback._handle_message(
            {
                "v": 1,
                "session": "other-session",
                "seq": 1,
                "type": "hidden",
                "reason": "finish_close",
            }
        )
        assert feedback.hidden is False
        missed: list[dict] = []
        feedback.add_listener(_native_reveals(missed))
        assert missed == []
        feedback._handle_message(_native_hidden(feedback))
        assert len(missed) == 1
        late: list[dict] = []
        callback = _native_reveals(late)
        feedback.add_listener(callback)
        feedback.add_listener(callback)
        assert len(late) == 1
        assert late[0]["event"] == "can_reveal"
        assert late[0]["hidden"] is True
        assert late[0]["session"] == feedback.session
        feedback.remove_listener(callback)
        feedback._handle_message(_native_hidden(feedback))
        assert len(late) == 1
        feedback.add_listener(callback)
        assert len(late) == 2
    finally:
        feedback.close()
        _close_many(*fds)


def test_native_register_during_reveal_and_after_close(monkeypatch):
    feedback, fds = _native_feedback(monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    first: list[dict] = []
    late: list[dict] = []

    def first_listener(payload):
        if not isinstance(payload, dict) or payload.get("event") != "can_reveal":
            return
        first.append(dict(payload))
        entered.set()
        assert release.wait(2.0)

    try:
        feedback.add_listener(first_listener)
        worker = threading.Thread(
            target=lambda: feedback._handle_message(_native_hidden(feedback)),
            name="native-hidden-overlap",
        )
        worker.start()
        assert entered.wait(2.0)
        late_thread = threading.Thread(
            target=lambda: feedback.add_listener(_native_reveals(late)),
            name="native-late-listener",
        )
        late_thread.start()
        late_thread.join(2.0)
        assert not late_thread.is_alive()
        assert len(late) == 1
        release.set()
        worker.join(2.0)
        assert not worker.is_alive()
        assert len(first) == 1
        feedback.close()
        after: list[dict] = []
        feedback.add_listener(_native_reveals(after))
        feedback._handle_message(_native_hidden(feedback))
        feedback._notify_reveal(reason="pipe_eof")
        assert after == []
        assert feedback._reveal_payload is None
    finally:
        release.set()
        feedback.close()
        _close_many(*fds)


def test_native_hidden_before_listener_on_the_pipe_replays_once(monkeypatch):
    app_read, app_write, launcher_read, launcher_write = _pair()
    feedback = None
    try:
        _install_session(monkeypatch, app_read, app_write)
        feedback = NativeStartupFeedback(hidden_ack_timeout_s=0.2, handover_timeout_s=0.4)
        feedback.start()
        os.write(
            launcher_write,
            encode_frame(
                {
                    "v": 1,
                    "session": feedback.session,
                    "seq": 1,
                    "type": "hidden",
                    "reason": "finish_close",
                }
            ),
        )
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not feedback.hidden:
            time.sleep(0.01)
        assert feedback.hidden is True
        reveals: list[dict] = []
        feedback.add_listener(reveals.append)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not reveals:
            time.sleep(0.01)
        assert len(reveals) == 1
        assert reveals[0]["event"] == "can_reveal"
        assert reveals[0]["hidden"] is True
        assert reveals[0]["handover_failed"] is False
        os.close(launcher_write)
        launcher_write = -1
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and not feedback._pipe_eof:
            time.sleep(0.01)
        assert feedback._pipe_eof is True
        assert len(reveals) == 1
        assert feedback.handover_failed is False
        feedback.finish()
        assert len(reveals) == 1
        feedback.close()
        late: list[dict] = []
        feedback.add_listener(late.append)
        assert late == []
    finally:
        if feedback is not None:
            feedback.close()
        _close_many(launcher_read, launcher_write)


def test_native_disabled_finish_replays_to_a_late_listener(monkeypatch):
    feedback, fds = _native_feedback(monkeypatch)
    try:
        feedback.start(hidden=True)
        assert feedback.fail_reason == "disabled"
        assert feedback.degraded is True
        feedback.finish()
        reveals: list[dict] = []
        feedback.add_listener(_native_reveals(reveals))
        assert len(reveals) == 1
        assert reveals[0]["reason"] == "immediate"
        assert feedback.fail_reason == "disabled"
        assert feedback.process is None
    finally:
        feedback.close()
        _close_many(*fds)
