"""Entrypoint probes for startup timing without disturbing hidden children."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "MF4 Data Analyzer V1.py"


def test_launcher_marks_python_entry_before_importing_app(monkeypatch):
    calls: list[str] = []

    fake_timing = ModuleType("mf4_analyzer.startup_timing")

    def mark(stage, **_detail):
        calls.append(f"mark:{stage}")

    fake_timing.mark = mark
    fake_timing.enabled = lambda: True
    fake_timing.STAGE_PYTHON_ENTRY = "python_entry"

    fake_app = ModuleType("mf4_analyzer.app")

    def main():
        calls.append("gui")

    fake_app.main = main
    fake_app.bootstrap_extension_runtime = lambda **_k: calls.append("boot")

    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_timing", fake_timing)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setattr(sys, "argv", ["TraceLab.exe"])

    runpy.run_path(str(LAUNCHER), run_name="__main__")

    assert calls[0] == "mark:python_entry"
    assert "gui" in calls
    assert calls.index("mark:python_entry") < calls.index("gui")
    # Ordinary GUI no longer bootstraps in the launcher; app.main owns that.
    assert "boot" not in calls


def test_launcher_child_modes_exit_before_mainwindow(monkeypatch):
    """Every hidden child/smoke path must not construct the GUI main window."""
    calls: list[str] = []

    fake_timing = ModuleType("mf4_analyzer.startup_timing")
    fake_timing.mark = lambda *_a, **_k: calls.append("mark")
    fake_timing.enabled = lambda: False
    fake_timing.STAGE_PYTHON_ENTRY = "python_entry"

    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.main = lambda: calls.append("gui")
    fake_app.bootstrap_extension_runtime = lambda **_k: calls.append("boot")
    fake_app.MainWindow = lambda: calls.append("MainWindow") or object()

    acquisition = ModuleType("mf4_analyzer.acquisition_capture.runtime_smoke")
    acquisition.run_import_probe_child = lambda: calls.append("pyxcp") or 0
    acquisition.run_pya2l_import_probe_child = lambda: calls.append("pya2l") or 0
    acquisition.run = lambda *_a, **_k: calls.append("acq-smoke") or 0

    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_timing", fake_timing)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setitem(
        sys.modules, "mf4_analyzer.acquisition_capture.runtime_smoke", acquisition
    )

    cases = [
        ["TraceLab.exe", "--pyxcp-import-probe-child"],
        ["TraceLab.exe", "--pya2l-import-probe-child"],
        ["TraceLab.exe", "--acquisition-runtime-smoke", "--json", "out.json"],
    ]
    for argv in cases:
        calls.clear()
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as stopped:
            runpy.run_path(str(LAUNCHER), run_name="__main__")
        assert stopped.value.code == 0
        assert "gui" not in calls
        assert "MainWindow" not in calls


def test_launcher_importer_smoke_still_exits_before_main(tmp_path, monkeypatch):
    calls: list[str] = []

    fake_timing = ModuleType("mf4_analyzer.startup_timing")
    fake_timing.mark = lambda stage, **_k: calls.append(f"mark:{stage}")
    fake_timing.enabled = lambda: True
    fake_timing.STAGE_PYTHON_ENTRY = "python_entry"

    importer = ModuleType("mf4_analyzer.io.importer_runtime_smoke")
    importer.run = lambda *_a, **_k: calls.append("importer") or 0

    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.main = lambda: calls.append("gui")
    fake_app.bootstrap_extension_runtime = lambda **_k: calls.append("boot")

    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_timing", fake_timing)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.io.importer_runtime_smoke", importer)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            "--importer-runtime-smoke",
            "--import-path",
            str(tmp_path / "a.mat"),
            "--json",
            str(tmp_path / "out.json"),
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 0
    assert calls[0] == "mark:python_entry"
    assert calls == ["mark:python_entry", "boot", "importer"]
    assert "gui" not in calls


def test_app_module_main_marks_python_entry_when_launched_directly(monkeypatch):
    """``python -m mf4_analyzer.app`` must mark before GUI construction."""
    import mf4_analyzer.app as app_mod

    calls: list[str] = []
    monkeypatch.setenv("TRACELAB_STARTUP_SPLASH", "0")
    monkeypatch.setattr(
        app_mod,
        "bootstrap_extension_runtime",
        lambda **_k: calls.append("boot"),
    )
    monkeypatch.setattr(app_mod, "setup_logging", lambda: calls.append("log"))
    monkeypatch.setattr(app_mod, "_configure_high_dpi", lambda: None)

    fake_timing = ModuleType("mf4_analyzer.startup_timing")

    def mark(stage, **_detail):
        calls.append(f"mark:{stage}")

    fake_timing.mark = mark
    fake_timing.enabled = lambda: True
    fake_timing.STAGE_PYTHON_ENTRY = "python_entry"
    fake_timing.STAGE_GUI_MODULES_IMPORTED = "gui_modules_imported"
    fake_timing.STAGE_QAPPLICATION_READY = "qapplication_ready"
    fake_timing.STAGE_MAINWINDOW_CONSTRUCTED = "mainwindow_constructed"
    fake_timing.STAGE_FIRST_FRAME = "first_frame"
    fake_timing.STAGE_INTERACTIVE_PROBE_HANDLED = "interactive_probe_handled"
    fake_timing.StartupTimingError = RuntimeError
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_timing", fake_timing)

    feedback_calls: list[str] = []

    class _FakeFeedback:
        def start(self, **kwargs):
            feedback_calls.append(("start", dict(kwargs)))
            calls.append("feedback:start")

        def publish(self, stage):
            feedback_calls.append(("publish", stage))
            calls.append(f"feedback:publish:{stage}")

        def finish(self):
            feedback_calls.append(("finish", None))
            calls.append("feedback:finish")

        def close(self):
            feedback_calls.append(("close", None))
            calls.append("feedback:close")

    monkeypatch.setattr(
        "mf4_analyzer.startup_feedback.StartupFeedback",
        _FakeFeedback,
    )

    armed: list[tuple] = []

    def _capture_arm(_app, _window, feedback=None):
        calls.append("arm")
        armed.append(("arm", feedback))

    monkeypatch.setattr(app_mod, "_arm_startup_observation", _capture_arm)

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

    monkeypatch.setitem(
        sys.modules,
        "PyQt5.QtWidgets",
        ModuleType("PyQt5.QtWidgets"),
    )
    sys.modules["PyQt5.QtWidgets"].QApplication = _FakeApp

    monkeypatch.setattr(
        app_mod,
        "_import_symbol",
        lambda module, name: {
            ("ui", "MainWindow"): _FakeWindow,
            ("ui_kit", "setup_chinese_font"): lambda: None,
            ("ui_kit", "load_stylesheet"): lambda _app: None,
            ("ui_kit", "install_glass_tooltips"): lambda _app: None,
        }[(module, name)],
    )
    monkeypatch.setattr(app_mod, "_load_app_icon", lambda: None)
    monkeypatch.setattr(app_mod, "install_qt_message_handler", lambda: None)
    monkeypatch.setattr(app_mod, "install_excepthooks", lambda **_k: None)

    fonts = ModuleType("mf4_analyzer.ui.pg_canvas.fonts")
    fonts.apply_global_chart_font = lambda _app: None
    monkeypatch.setitem(sys.modules, "mf4_analyzer.ui.pg_canvas.fonts", fonts)

    monkeypatch.delenv("TRACELAB_LAYOUT_PROBE", raising=False)
    monkeypatch.setattr(sys, "exit", lambda code: calls.append(f"exit:{code}"))

    app_mod.main()

    assert calls[0] == "mark:python_entry"
    assert "feedback:start" in calls
    assert "feedback:publish:loading_components" in calls
    assert "boot" in calls
    assert calls.index("feedback:start") < calls.index(
        "feedback:publish:loading_components"
    )
    assert calls.index("feedback:publish:loading_components") < calls.index("boot")
    assert "feedback:publish:preparing_workspace" in calls
    assert calls.index("feedback:publish:preparing_workspace") < calls.index(
        "MainWindow"
    )
    assert "mark:gui_modules_imported" in calls
    assert "mark:qapplication_ready" in calls
    assert "mark:mainwindow_constructed" in calls
    assert "MainWindow" in calls
    assert calls.index("mark:python_entry") < calls.index("MainWindow")
    assert calls.index("mark:mainwindow_constructed") < calls.index("show")
    assert calls.index("arm") < calls.index("show")
    assert len(armed) == 1
    assert armed[0][0] == "arm"
    assert armed[0][1] is not None
    assert "feedback:close" in calls
    # Task 0 must not pretend preload/pages are done on the startup path.
    assert "mark:preload_complete" not in calls
    assert not any(item.startswith("mark:page_ready") for item in calls)
def test_launcher_text_keeps_hidden_children_before_app_import():
    text = LAUNCHER.read_text(encoding="utf-8")
    gui_import = "from mf4_analyzer.app import main"
    assert gui_import in text
    assert "startup_timing" in text
    assert text.index("if args.pyxcp_import_probe_child") < text.index(gui_import)
    assert text.index("if args.a2l_probe_child") < text.index(gui_import)
    assert text.index("startup_timing") < text.index(gui_import)
    # Splash child must return before timing marks and the GUI import.
    assert "startup_splash_child" in text
    assert text.index("startup_splash_child") < text.index("startup_timing")
    assert text.index("startup_splash_child") < text.index(gui_import)
    # No timing CLI; splash uses an exact hidden child flag instead.
    assert "--startup-timing" not in text
    assert 'add_argument("--startup-timing"' not in text
    assert 'add_argument("--startup-splash-child"' in text


def test_launcher_routes_startup_splash_child_before_timing(monkeypatch):
    calls: list[str] = []

    fake_timing = ModuleType("mf4_analyzer.startup_timing")
    fake_timing.mark = lambda *_a, **_k: calls.append("mark")
    fake_timing.enabled = lambda: False
    fake_timing.STAGE_PYTHON_ENTRY = "python_entry"

    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.main = lambda: calls.append("gui")
    fake_app.bootstrap_extension_runtime = lambda **_k: calls.append("boot")

    splash = ModuleType("mf4_analyzer.startup_splash_child")

    def child_main(argv=None):
        calls.append("splash:" + " ".join(argv or []))
        return 0

    splash.child_main = child_main

    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_timing", fake_timing)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_splash_child", splash)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            "--startup-splash-child",
            "--startup-splash-session",
            "sess-1",
            "--startup-splash-endpoint",
            "127.0.0.1:54321",
            "--startup-splash-token",
            "tok-1",
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 0
    assert calls == [
        "splash:--startup-splash-child --startup-splash-session sess-1 "
        "--startup-splash-endpoint 127.0.0.1:54321 --startup-splash-token tok-1"
    ]
    assert "mark" not in calls
    assert "gui" not in calls
    assert "boot" not in calls


@pytest.mark.parametrize(
    "argv",
    [
        [
            "TraceLab.exe",
            "--startup-splash-child",
            "--startup-splash-session",
            "sess",
            "--startup-splash-endpoint",
            "127.0.0.1:9",
            "--startup-splash-token",
            "tok",
            "--pyxcp-import-probe-child",
        ],
        [
            "TraceLab.exe",
            "--importer-runtime-smoke",
            "--startup-splash-child",
            "--json",
            "out.json",
            "--import-path",
            "a.mat",
        ],
    ],
)
def test_launcher_rejects_splash_child_with_other_hidden_modes(
    argv, monkeypatch
):
    calls: list[str] = []
    splash = ModuleType("mf4_analyzer.startup_splash_child")
    splash.child_main = lambda *_a, **_k: calls.append("splash") or 0
    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.main = lambda: calls.append("gui")
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_splash_child", splash)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 2
    assert calls == []


def test_launcher_rejects_abbreviated_splash_child_flag(monkeypatch):
    calls: list[str] = []
    splash = ModuleType("mf4_analyzer.startup_splash_child")
    splash.child_main = lambda *_a, **_k: calls.append("splash") or 0
    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.main = lambda: calls.append("gui")
    fake_app.bootstrap_extension_runtime = lambda **_k: None
    fake_timing = ModuleType("mf4_analyzer.startup_timing")
    fake_timing.mark = lambda *_a, **_k: None
    fake_timing.STAGE_PYTHON_ENTRY = "python_entry"
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_splash_child", splash)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_timing", fake_timing)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            "--startup-splash-ch",
            "--startup-splash-session",
            "sess",
            "--startup-splash-endpoint",
            "127.0.0.1:9",
            "--startup-splash-token",
            "tok",
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 2
    assert calls == []


@pytest.mark.parametrize(
    "argv",
    [
        # Mode without payload
        ["TraceLab.exe", "--startup-splash-child"],
        # Payload without mode
        [
            "TraceLab.exe",
            "--startup-splash-session",
            "sess",
            "--startup-splash-endpoint",
            "127.0.0.1:9",
            "--startup-splash-token",
            "tok",
        ],
        # Illegal endpoint host
        [
            "TraceLab.exe",
            "--startup-splash-child",
            "--startup-splash-session",
            "sess",
            "--startup-splash-endpoint",
            "0.0.0.0:9",
            "--startup-splash-token",
            "tok",
        ],
        # Illegal endpoint shape
        [
            "TraceLab.exe",
            "--startup-splash-child",
            "--startup-splash-session",
            "sess",
            "--startup-splash-endpoint",
            "127.0.0.1",
            "--startup-splash-token",
            "tok",
        ],
        # Missing token
        [
            "TraceLab.exe",
            "--startup-splash-child",
            "--startup-splash-session",
            "sess",
            "--startup-splash-endpoint",
            "127.0.0.1:9",
        ],
    ],
)
def test_launcher_rejects_missing_or_illegal_splash_payload(argv, monkeypatch):
    calls: list[str] = []
    splash = ModuleType("mf4_analyzer.startup_splash_child")
    splash.child_main = lambda *_a, **_k: calls.append("splash") or 0
    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.main = lambda: calls.append("gui")
    fake_app.bootstrap_extension_runtime = lambda **_k: None
    fake_timing = ModuleType("mf4_analyzer.startup_timing")
    fake_timing.mark = lambda *_a, **_k: None
    fake_timing.STAGE_PYTHON_ENTRY = "python_entry"
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_splash_child", splash)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_timing", fake_timing)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 2
    assert "splash" not in calls
    assert "gui" not in calls


def test_launcher_splash_child_dispatch_without_console_streams(monkeypatch):
    calls: list[str] = []
    splash = ModuleType("mf4_analyzer.startup_splash_child")
    splash.child_main = lambda argv=None: calls.append("splash") or 0
    monkeypatch.setitem(sys.modules, "mf4_analyzer.startup_splash_child", splash)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            "--startup-splash-child",
            "--startup-splash-session",
            "sess",
            "--startup-splash-endpoint",
            "127.0.0.1:4242",
            "--startup-splash-token",
            "tok",
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 0
    assert calls == ["splash"]
