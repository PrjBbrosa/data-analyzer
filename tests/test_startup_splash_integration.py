"""Integration coverage for ordinary-GUI StartupFeedback wiring (Task 3).

Uses fakes/mocks only — never spawns a long-lived real splash child or GUI.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "MF4 Data Analyzer V1.py"


class _RecordingFeedback:
    """Stand-in for StartupFeedback that records calls without spawning."""

    instances: list["_RecordingFeedback"] = []

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.start_kwargs: dict[str, Any] | None = None
        self.finished = False
        self.closed = False
        type(self).instances.append(self)

    def start(self, **kwargs) -> None:
        self.start_kwargs = dict(kwargs)
        self.calls.append(("start", dict(kwargs)))

    def publish(self, stage: str) -> None:
        self.calls.append(("publish", stage))

    def set_slow(self, slow: bool) -> None:
        self.calls.append(("set_slow", bool(slow)))

    def finish(self) -> None:
        self.finished = True
        self.calls.append(("finish", None))

    def close(self) -> None:
        self.closed = True
        self.calls.append(("close", None))


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

    def _arm(app, window, feedback=None):
        calls.append("arm")
        arm_args.append((app, window, feedback))

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
        # Prove ordinary path would start feedback inside main, not launcher.
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
        # Publish order must already include loading_components before we arrive.
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


def test_paint_finish_queued_after_paint_not_on_show(qtbot, monkeypatch):
    """Finish only after a real Paint returns; show alone is not enough."""
    from PyQt5.QtCore import QEvent
    from PyQt5.QtWidgets import QApplication, QWidget

    import mf4_analyzer.app as app_mod

    monkeypatch.setenv("TRACELAB_STARTUP_TIMING", "0")
    # Force timing module to see disabled without leftover state.
    from mf4_analyzer import startup_timing as st

    monkeypatch.setattr(st, "enabled", lambda: False)

    fb = _RecordingFeedback()
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    qtbot.addWidget(window)

    app_mod._arm_startup_observation(app, window, fb)
    window.show()
    # show() alone must not finish.
    assert not fb.finished

    # Deliver a Paint through the event filter path.
    QApplication.sendEvent(window, QEvent(QEvent.Paint))
    assert not fb.finished  # still waiting for the queued singleShot(0)
    qtbot.waitUntil(lambda: fb.finished, timeout=2000)
    assert fb.finished


def test_observation_armed_when_timing_disabled(qtbot, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QWidget

    import mf4_analyzer.app as app_mod
    from mf4_analyzer import startup_timing as st

    monkeypatch.setattr(st, "enabled", lambda: False)
    fb = _RecordingFeedback()
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    qtbot.addWidget(window)
    app_mod._arm_startup_observation(app, window, fb)
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
