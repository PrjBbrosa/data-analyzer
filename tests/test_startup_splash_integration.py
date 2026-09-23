"""Integration coverage for ordinary-GUI StartupFeedback wiring (Task 3).

Includes handover ordering (hidden before main show) and a real-child natural
exit path. Does not claim Windows compositor visibility.
"""
from __future__ import annotations

import logging
import os
import runpy
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "MF4 Data Analyzer V1.py"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


class _RecordingFeedback:
    """Stand-in for StartupFeedback that records calls without spawning."""

    instances: list["_RecordingFeedback"] = []

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.start_kwargs: dict[str, Any] | None = None
        self.finished = False
        self.closed = False
        self.session = "recording-session"
        self._listeners: list = []
        type(self).instances.append(self)

    def start(self, **kwargs) -> None:
        self.start_kwargs = dict(kwargs)
        self.calls.append(("start", dict(kwargs)))

    def publish(self, stage: str) -> None:
        self.calls.append(("publish", stage))

    def set_slow(self, slow: bool) -> None:
        self.calls.append(("set_slow", bool(slow)))

    def add_listener(self, callback) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            return

    def snapshot(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "degraded": False,
            "fail_reason": None,
            "hidden": False,
        }

    def finish(self) -> None:
        self.finished = True
        self.calls.append(("finish", None))

    def close(self) -> None:
        self.closed = True
        self.calls.append(("close", None))

    def emit_reveal(self, **extra: Any) -> None:
        payload = {
            "event": "can_reveal",
            "session": self.session,
            "reason": "hidden",
            "hidden": True,
            "hidden_reason": "finish_close",
            "handover_failed": False,
            "child_exit_code": 0,
            "force_terminated": False,
        }
        payload.update(extra)
        for callback in list(self._listeners):
            callback(payload)


def _install_fake_feedback(monkeypatch) -> type[_RecordingFeedback]:
    _RecordingFeedback.instances = []
    monkeypatch.setattr(
        "mf4_analyzer.startup_feedback.StartupFeedback",
        _RecordingFeedback,
    )
    return _RecordingFeedback


def _stub_app_gui(monkeypatch, app_mod, *, calls: list[str], window_factory=None):
    """Shared fakes for QApplication / MainWindow / ui_kit imports."""

    monkeypatch.setattr(app_mod, "setup_logging", lambda: calls.append("log"))
    monkeypatch.setattr(app_mod, "_configure_high_dpi", lambda: None)
    monkeypatch.setattr(app_mod, "_load_app_icon", lambda: None)
    monkeypatch.setattr(app_mod, "install_qt_message_handler", lambda: None)
    monkeypatch.setattr(app_mod, "install_excepthooks", lambda **_k: None)

    fake_timing = ModuleType("mf4_analyzer.startup_timing")

    def mark(stage, **_detail):
        calls.append(f"mark:{stage}")

    fake_timing.mark = mark
    fake_timing.enabled = lambda: False
    fake_timing.STAGE_PYTHON_ENTRY = "python_entry"
    fake_timing.STAGE_GUI_MODULES_IMPORTED = "gui_modules_imported"
    fake_timing.STAGE_QAPPLICATION_READY = "qapplication_ready"
    fake_timing.STAGE_MAINWINDOW_CONSTRUCTED = "mainwindow_constructed"
    fake_timing.STAGE_FIRST_FRAME = "first_frame"
    fake_timing.STAGE_INTERACTIVE_PROBE_HANDLED = "interactive_probe_handled"
    fake_timing.StartupTimingError = RuntimeError
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_timing", fake_timing)

    class _FakeApp:
        def __init__(self, _argv):
            calls.append("QApplication")

        def setStyle(self, *_a):
            return None

        def setWindowIcon(self, *_a):
            return None

        def exec_(self):
            calls.append("exec")
            return 0

    class _FakeWindow:
        def __init__(self):
            calls.append("MainWindow")

        def show(self):
            calls.append("show")

        def toast(self, *_a, **_k):
            return None

        def isVisible(self):
            return True

        def installEventFilter(self, _obj):
            return None

    Window = window_factory or _FakeWindow

    monkeypatch.setitem(sys.modules, "PyQt5.QtWidgets", ModuleType("PyQt5.QtWidgets"))
    sys.modules["PyQt5.QtWidgets"].QApplication = _FakeApp
    monkeypatch.setattr(
        app_mod,
        "_import_symbol",
        lambda module, name: {
            ("ui", "MainWindow"): Window,
            ("ui_kit", "setup_chinese_font"): lambda: None,
            ("ui_kit", "load_stylesheet"): lambda _app: None,
            ("ui_kit", "install_glass_tooltips"): lambda _app: None,
        }[(module, name)],
    )
    fonts = ModuleType("mf4_analyzer.ui.pg_canvas.fonts")
    fonts.apply_global_chart_font = lambda _app: None
    monkeypatch.setitem(sys.modules, "mf4_analyzer.ui.pg_canvas.fonts", fonts)
    monkeypatch.delenv("TRACELAB_LAYOUT_PROBE", raising=False)

    # Handover: begin() finishes + reveal path for disabled/recording feedback.
    class _FakeHandover:
        def __init__(self, app, window, feedback, **_k):
            self.app = app
            self.window = window
            self.feedback = feedback
            self.show_called = False
            calls.append("handover_init")

        def begin(self):
            calls.append("handover_begin")
            self.feedback.finish()
            # Recording feedback does not auto-reveal; simulate disabled path.
            self.window.show()
            self.show_called = True

        def close(self):
            calls.append("handover_close")

        def mark_first_frame(self):
            calls.append("first_frame")

    monkeypatch.setitem(
        sys.modules,
        "mf4_analyzer.startup_handover",
        ModuleType("mf4_analyzer.startup_handover"),
    )
    sys.modules["mf4_analyzer.startup_handover"].StartupHandover = _FakeHandover


def test_app_main_starts_feedback_before_bootstrap(monkeypatch):
    import mf4_analyzer.app as app_mod

    calls: list[str] = []
    Feedback = _install_fake_feedback(monkeypatch)
    monkeypatch.setattr(
        app_mod,
        "bootstrap_extension_runtime",
        lambda **_k: calls.append("boot"),
    )
    arm_args: list[Any] = []

    def _arm(app, window, feedback=None, handover=None):
        calls.append("arm")
        arm_args.append((app, window, feedback, handover))

    monkeypatch.setattr(app_mod, "_arm_startup_observation", _arm)
    _stub_app_gui(monkeypatch, app_mod, calls=calls)
    monkeypatch.setattr(sys, "exit", lambda code: calls.append(f"exit:{code}"))

    app_mod.main()

    assert Feedback.instances, "StartupFeedback was not constructed"
    fb = Feedback.instances[-1]
    assert fb.start_kwargs == {"layout_probe": False}
    assert fb.calls[0][0] == "start"
    assert fb.calls[1] == ("publish", "loading_components")
    assert ("publish", "preparing_workspace") in fb.calls
    assert calls.index("arm") < calls.index("show")
    assert calls.index("handover_begin") < calls.index("show")
    assert arm_args and arm_args[0][2] is fb
    assert fb.closed


def test_root_launcher_ordinary_gui_enters_main_with_feedback(monkeypatch):
    """Root launcher marks, then calls app.main (which owns feedback start)."""
    calls: list[str] = []

    fake_timing = ModuleType("mf4_analyzer.startup_timing")
    fake_timing.mark = lambda stage, **_k: calls.append(f"mark:{stage}")
    fake_timing.enabled = lambda: False
    fake_timing.STAGE_PYTHON_ENTRY = "python_entry"

    fake_app = ModuleType("mf4_analyzer.app")

    def main():
        calls.append("gui")
        from mf4_analyzer.startup_feedback import StartupFeedback

        fb = StartupFeedback()
        fb.start(layout_probe=False)
        calls.append("feedback:start")
        fb.close()

    fake_app.main = main
    fake_app.bootstrap_extension_runtime = lambda **_k: calls.append("boot")

    Feedback = _install_fake_feedback(monkeypatch)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_timing", fake_timing)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setattr(sys, "argv", ["TraceLab.exe"])

    runpy.run_path(str(LAUNCHER), run_name="__main__")

    assert calls[0] == "mark:python_entry"
    assert "gui" in calls
    assert "boot" not in calls
    assert "feedback:start" in calls
    assert Feedback.instances
    assert Feedback.instances[-1].start_kwargs is not None


def test_layout_probe_and_hidden_do_not_spawn_child(monkeypatch):
    from mf4_analyzer.startup_feedback import StartupFeedback, splash_enabled

    monkeypatch.setenv("TRACELAB_STARTUP_SPLASH", "1")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert splash_enabled(hidden=True, layout_probe=False, allow_offscreen=True) is False
    assert splash_enabled(hidden=False, layout_probe=True, allow_offscreen=True) is False

    spawned: list[Any] = []
    monkeypatch.setattr(
        StartupFeedback,
        "_spawn_child",
        lambda self: spawned.append("spawn"),
    )
    fb = StartupFeedback()
    fb.start(layout_probe=True, allow_offscreen=True)
    assert spawned == []
    assert fb.degraded
    fb.close()

    fb2 = StartupFeedback()
    fb2.start(hidden=True, allow_offscreen=True)
    assert spawned == []
    assert fb2.degraded
    fb2.close()


def test_app_main_layout_probe_passes_flag_and_skips_mainwindow(monkeypatch):
    import mf4_analyzer.app as app_mod

    calls: list[str] = []
    Feedback = _install_fake_feedback(monkeypatch)
    monkeypatch.setattr(
        app_mod,
        "bootstrap_extension_runtime",
        lambda **_k: calls.append("boot"),
    )
    monkeypatch.setattr(app_mod, "_arm_startup_observation", lambda *_a, **_k: None)
    _stub_app_gui(monkeypatch, app_mod, calls=calls)
    monkeypatch.setenv("TRACELAB_LAYOUT_PROBE", "1")

    probe = ModuleType("mf4_analyzer.ui.layout_probe")
    probe.run_layout_probe = lambda _app: calls.append("layout_probe") or 0
    monkeypatch.setitem(sys.modules, "mf4_analyzer.ui.layout_probe", probe)

    def _exit(code):
        calls.append(f"exit:{code}")
        raise SystemExit(code)

    monkeypatch.setattr(sys, "exit", _exit)

    with pytest.raises(SystemExit) as stopped:
        app_mod.main()

    assert stopped.value.code == 0
    fb = Feedback.instances[-1]
    assert fb.start_kwargs == {"layout_probe": True}
    assert "MainWindow" not in calls
    assert "layout_probe" in calls
    assert fb.closed


def test_slow_bootstrap_keeps_publish_order(monkeypatch):
    import mf4_analyzer.app as app_mod

    calls: list[str] = []
    Feedback = _install_fake_feedback(monkeypatch)

    def slow_boot(**_k):
        calls.append("boot")
        fb = Feedback.instances[-1]
        assert ("publish", "loading_components") in fb.calls
        assert ("publish", "preparing_workspace") not in fb.calls

    monkeypatch.setattr(app_mod, "bootstrap_extension_runtime", slow_boot)
    monkeypatch.setattr(app_mod, "_arm_startup_observation", lambda *_a, **_k: None)
    _stub_app_gui(monkeypatch, app_mod, calls=calls)
    monkeypatch.setattr(sys, "exit", lambda code: calls.append(f"exit:{code}"))

    app_mod.main()

    fb = Feedback.instances[-1]
    assert [c for c in fb.calls if c[0] in {"start", "publish"}] == [
        ("start", fb.start_kwargs),
        ("publish", "loading_components"),
        ("publish", "preparing_workspace"),
    ]


def test_mainwindow_construct_error_closes_feedback_nonzero(monkeypatch):
    import mf4_analyzer.app as app_mod

    calls: list[str] = []
    Feedback = _install_fake_feedback(monkeypatch)
    monkeypatch.setattr(
        app_mod,
        "bootstrap_extension_runtime",
        lambda **_k: calls.append("boot"),
    )
    monkeypatch.setattr(app_mod, "_report_startup_failure", lambda *_a, **_k: None)

    class _BoomWindow:
        def __init__(self):
            raise RuntimeError("mw-boom")

    monkeypatch.setattr(app_mod, "_arm_startup_observation", lambda *_a, **_k: None)
    _stub_app_gui(monkeypatch, app_mod, calls=calls, window_factory=_BoomWindow)
    exit_codes: list[int] = []
    monkeypatch.setattr(sys, "exit", lambda code: exit_codes.append(code))

    app_mod.main()

    fb = Feedback.instances[-1]
    assert fb.closed
    assert exit_codes == [1]


def test_handover_shows_once_after_hidden_not_on_construct(qtbot, monkeypatch):
    """Main window is constructed without show; reveal only after hidden ACK."""
    from PyQt5.QtCore import QEvent
    from PyQt5.QtWidgets import QApplication, QWidget

    from mf4_analyzer.startup_handover import StartupHandover
    from mf4_analyzer import startup_timing as st

    monkeypatch.setattr(st, "enabled", lambda: False)
    monkeypatch.setattr(st, "record_splash_event", lambda *a, **k: None)

    fb = _RecordingFeedback()
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    qtbot.addWidget(window)
    shows = {"n": 0}
    original_show = window.show

    def counting_show():
        shows["n"] += 1
        original_show()

    window.show = counting_show  # type: ignore[method-assign]

    handover = StartupHandover(app, window, fb)
    # begin issues finish; recording feedback does not auto-reveal.
    handover.begin()
    assert shows["n"] == 0
    assert not window.isVisible()

    fb.emit_reveal()
    qtbot.waitUntil(lambda: shows["n"] == 1, timeout=2000)
    assert shows["n"] == 1
    assert handover.show_called

    # Duplicate ACK must not show again.
    fb.emit_reveal()
    qtbot.wait(50)
    assert shows["n"] == 1

    # First-frame timing is independent and must not finish again.
    import mf4_analyzer.app as app_mod

    app_mod._arm_startup_observation(app, window, fb, handover)
    QApplication.sendEvent(window, QEvent(QEvent.Paint))
    qtbot.wait(50)
    finish_calls = [c for c in fb.calls if c[0] == "finish"]
    # begin() called finish once; paint must not add another.
    assert len(finish_calls) == 1

    handover.close()
    # Late reveal after close must not revive show.
    fb.emit_reveal()
    qtbot.wait(50)
    assert shows["n"] == 1


def test_parent_close_blocks_late_reveal_show(qtbot, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QWidget

    from mf4_analyzer.startup_handover import StartupHandover
    from mf4_analyzer import startup_timing as st

    monkeypatch.setattr(st, "record_splash_event", lambda *a, **k: None)
    fb = _RecordingFeedback()
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    qtbot.addWidget(window)
    handover = StartupHandover(app, window, fb)
    handover.begin()
    handover.close()
    fb.emit_reveal()
    qtbot.wait(80)
    assert handover.show_called is False
    assert not window.isVisible()


def test_observation_armed_when_timing_disabled(qtbot, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QWidget

    import mf4_analyzer.app as app_mod
    from mf4_analyzer import startup_timing as st

    monkeypatch.setattr(st, "enabled", lambda: False)
    fb = _RecordingFeedback()
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    qtbot.addWidget(window)
    app_mod._arm_startup_observation(app, window, fb, handover=None)
    assert getattr(window, "_tracelab_startup_observer", None) is not None


def test_offscreen_default_does_not_spawn_real_child(monkeypatch):
    from mf4_analyzer.startup_feedback import StartupFeedback

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("TRACELAB_STARTUP_SPLASH", raising=False)
    monkeypatch.setenv("TRACELAB_STARTUP_SPLASH", "1")  # even forced
    spawned: list[str] = []
    monkeypatch.setattr(
        StartupFeedback,
        "_spawn_child",
        lambda self: spawned.append("spawn"),
    )
    # Production path: allow_offscreen defaults False → disabled on offscreen.
    fb = StartupFeedback()
    fb.start(layout_probe=False)
    assert spawned == []
    assert fb.degraded
    assert fb.fail_reason == "disabled"
    fb.close()


def test_real_child_finish_hidden_natural_exit_zero(monkeypatch, caplog):
    """Real source child: painted → finish → hidden → exit 0, no force-kill."""
    if not VENV_PYTHON.is_file():
        pytest.skip("project .venv python missing")

    from mf4_analyzer.startup_feedback import (
        ENV_SPLASH,
        HIDDEN_FINISH_CLOSE,
        StartupFeedback,
    )

    monkeypatch.setenv(ENV_SPLASH, "1")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.setenv("TMPDIR", "/tmp")
    monkeypatch.setenv("MPLCONFIGDIR", "/tmp")

    # Force child to use the project venv interpreter.
    monkeypatch.setattr(
        "mf4_analyzer.startup_feedback.sys.executable",
        str(VENV_PYTHON),
    )

    feedback = StartupFeedback()
    try:
        with caplog.at_level(logging.WARNING):
            feedback.start(allow_offscreen=True)
            assert feedback.process is not None
            assert _wait(lambda: feedback.painted, timeout_s=8.0), "child never painted"
            feedback.finish()
            assert _wait(lambda: feedback.hidden, timeout_s=5.0), "hidden ACK missing"
            assert feedback.hidden_reason == HIDDEN_FINISH_CLOSE
            assert _wait(
                lambda: feedback.child_exited
                or (
                    feedback.process is not None and feedback.process.poll() is not None
                ),
                timeout_s=5.0,
            )
        code = feedback.child_exit_code
        if code is None and feedback.process is not None:
            code = feedback.process.poll()
        assert code == 0
        assert feedback.force_terminated is False
        assert "still alive after finish; terminating" not in caplog.text
    finally:
        feedback.close()
        proc = feedback.process
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


def test_cross_session_reveal_ignored_by_handover(qtbot, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QWidget

    from mf4_analyzer.startup_handover import StartupHandover
    from mf4_analyzer import startup_timing as st

    monkeypatch.setattr(st, "record_splash_event", lambda *a, **k: None)
    fb = _RecordingFeedback()
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    qtbot.addWidget(window)
    handover = StartupHandover(app, window, fb)
    handover.begin()
    fb.emit_reveal(session="other-session")
    qtbot.wait(80)
    assert handover.show_called is False
    fb.emit_reveal(session=fb.session)
    qtbot.waitUntil(lambda: handover.show_called, timeout=2000)
    handover.close()


def _wait(predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False
