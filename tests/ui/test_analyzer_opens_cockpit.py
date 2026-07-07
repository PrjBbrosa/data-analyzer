from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMainWindow


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_importing_analyzer_main_window_does_not_import_cockpit_main_window():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONPATH"] = str(REPO_ROOT)
    code = (
        "import sys\n"
        "import mf4_analyzer.ui.main_window\n"
        "raise SystemExit("
        "'mf4_analyzer.acquisition_ui.main_window' in sys.modules"
        ")\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        "mf4_analyzer.ui.main_window imported Cockpit at module load\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_importing_cockpit_main_window_does_not_import_pya2l():
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONPATH"] = str(REPO_ROOT)
    code = (
        "import builtins\n"
        "real_import = builtins.__import__\n"
        "def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):\n"
        "    if name == 'pya2l' or name.startswith('pya2l.'):\n"
        "        raise AssertionError(f'eager pya2l import: {name}')\n"
        "    return real_import(name, globals, locals, fromlist, level)\n"
        "builtins.__import__ = guarded_import\n"
        "import mf4_analyzer.acquisition_ui.main_window\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, (
        "Cockpit startup imported pya2l before an A2L file was selected\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def _triple_click_logo(qtbot, window):
    """Fire the hidden Cockpit gesture: three rapid clicks on the brand logo."""
    logo = window.toolbar._logo_label
    for _ in range(3):
        qtbot.mouseClick(logo, Qt.LeftButton)


def _patch_cockpit_import(monkeypatch, cockpit_cls):
    import mf4_analyzer.ui.main_window as main_window_module

    real_import = importlib.import_module

    def fake_import_module(name, package=None):
        if name == "mf4_analyzer.acquisition_ui.main_window":
            return SimpleNamespace(CockpitMainWindow=cockpit_cls)
        return real_import(name, package)

    monkeypatch.setattr(main_window_module.importlib, "import_module", fake_import_module)


def test_analyzer_toolbar_opens_cockpit_when_none_open(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    class FakeCockpit(QMainWindow):
        instances: list["FakeCockpit"] = []

        def __init__(self, **kwargs):
            super().__init__()
            self.kwargs = kwargs
            self.shown = False
            FakeCockpit.instances.append(self)

        def show(self):
            self.shown = True
            super().show()

    _patch_cockpit_import(monkeypatch, FakeCockpit)

    window = MainWindow()
    qtbot.addWidget(window)
    # Hidden entry: the logo keeps the company tooltip, no Cockpit button.
    assert window.toolbar._logo_label.toolTip() == "博世华域转向系统有限公司"
    assert not hasattr(window.toolbar, "btn_acquisition_cockpit")

    _triple_click_logo(qtbot, window)
    qapp.processEvents()

    assert len(FakeCockpit.instances) == 1
    assert FakeCockpit.instances[0].shown
    config_path = FakeCockpit.instances[0].kwargs.get("config_path")
    assert config_path is not None
    assert config_path.name == "acquisition_config.yaml"
    assert config_path.parent.name == ".acquisition-cockpit"
    FakeCockpit.instances[0].close()


def test_analyzer_toolbar_raises_existing_cockpit(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    class FakeCockpit(QMainWindow):
        instances: list["FakeCockpit"] = []

        def __init__(self):
            super().__init__()
            self.raised = False
            self.activated = False
            FakeCockpit.instances.append(self)

        def raise_(self):
            self.raised = True
            super().raise_()

        def activateWindow(self):
            self.activated = True
            super().activateWindow()

    _patch_cockpit_import(monkeypatch, FakeCockpit)
    existing = FakeCockpit()
    qtbot.addWidget(existing)
    existing.show()
    qapp.processEvents()

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_acquisition_cockpit()
    qapp.processEvents()

    assert FakeCockpit.instances == [existing]
    assert existing.raised
    assert existing.activated


def test_analyzer_toolbar_reopens_cockpit_after_close(qapp, qtbot, monkeypatch):
    """Regression: closing the Cockpit then clicking the button again
    must re-show the window. Qt's default close hides — it does not
    destroy — so ``topLevelWidgets()`` still surfaces the hidden
    instance. ``raise_()`` / ``activateWindow()`` are no-ops on hidden
    widgets, so without ``show()`` the second click silently does
    nothing."""
    from mf4_analyzer.ui.main_window import MainWindow

    class FakeCockpit(QMainWindow):
        instances: list["FakeCockpit"] = []

        def __init__(self, **_kwargs):
            super().__init__()
            self.show_calls = 0
            FakeCockpit.instances.append(self)

        def show(self):
            self.show_calls += 1
            super().show()

    _patch_cockpit_import(monkeypatch, FakeCockpit)

    window = MainWindow()
    qtbot.addWidget(window)

    _triple_click_logo(qtbot, window)
    qapp.processEvents()
    assert len(FakeCockpit.instances) == 1
    first = FakeCockpit.instances[0]
    assert first.show_calls == 1
    assert first.isVisible()

    first.close()
    qapp.processEvents()
    assert not first.isVisible()

    _triple_click_logo(qtbot, window)
    qapp.processEvents()

    visible = [c for c in FakeCockpit.instances if c.isVisible()]
    assert visible, "after close + re-click, cockpit must be visible again"

    for c in FakeCockpit.instances:
        c.close()


def test_cockpit_creation_does_not_load_a2l_eagerly(qapp, qtbot, monkeypatch):
    from PyQt5.QtWidgets import QFileDialog

    from mf4_analyzer.ui.main_window import MainWindow

    def fail_if_a2l_picker_opens(*args, **kwargs):
        raise AssertionError("Cockpit creation must not open the A2L picker")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", fail_if_a2l_picker_opens)

    window = MainWindow()
    qtbot.addWidget(window)
    window.open_acquisition_cockpit()
    qapp.processEvents()

    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow

    cockpits = [
        top_level for top_level in QApplication.topLevelWidgets()
        if isinstance(top_level, CockpitMainWindow)
    ]
    assert cockpits
    for cockpit in cockpits:
        cockpit.close()
