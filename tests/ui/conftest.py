"""Shared pytest fixtures for UI tests."""
import gc
import os
# Force offscreen Qt platform for headless CI *before* QApplication exists
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _isolate_qsettings(tmp_path, monkeypatch):
    """Keep UI tests from polluting the real MF4Analyzer/DataAnalyzer store.

    Constructing a persistent UI widget (Inspector param sections,
    PersistentTop, PresetBar) and toggling it calls ``set_expanded`` /
    ``setValue`` on the ``QSettings`` returned by ``_preset_settings()``. On
    Windows the native backend is the registry, so a UI test that expands a
    section writes ``inspector/{fft,order,fft_time}/params_expanded=true`` into
    the live store; the next real app launch then opens that section expanded,
    appearing to violate the default-collapsed spec even though the code
    default is correct (lesson ``codex-qt-render-probes-isolate-qsettings``).

    ``QSettings(org, app)`` ignores ``setDefaultFormat`` — it hard-binds the
    native backend — so redirecting it requires monkeypatching the
    ``_preset_settings`` factory itself, in every module that imported it by
    name *and* the package re-export the tests pull from. Each test gets its
    own throwaway INI. ``setDefaultFormat`` + ``setPath`` additionally divert
    any bare ``QSettings()`` (hint bars) away from the registry.
    """
    from PyQt5.QtCore import QSettings
    import mf4_analyzer.ui.inspector_sections as _pkg
    import mf4_analyzer.ui.inspector_sections._helpers as _helpers_mod
    import mf4_analyzer.ui.inspector_sections.collapsible as _collapsible_mod
    import mf4_analyzer.ui.inspector_sections.presets as _presets_mod
    import mf4_analyzer.ui.inspector_sections.persistent_top as _persistent_top_mod

    ini = str(tmp_path / "qsettings.ini")

    def _temp_settings(*_args, **_kwargs):
        return QSettings(ini, QSettings.IniFormat)

    for mod in (_pkg, _helpers_mod, _collapsible_mod, _presets_mod,
                _persistent_top_mod):
        if hasattr(mod, "_preset_settings"):
            monkeypatch.setattr(mod, "_preset_settings", _temp_settings)

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(tmp_path))
    yield


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication so each test reuses the instance."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _own_chartstacks(qapp, monkeypatch):
    """Keep unowned ChartStack widgets alive until queued layout callbacks drain."""
    from mf4_analyzer.ui.chart_stack import ChartStack

    created = []
    orig_init = ChartStack.__init__

    def _tracking_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(ChartStack, "__init__", _tracking_init)
    yield
    qapp.processEvents()
    for cs in created:
        try:
            cs.deleteLater()
        except Exception:
            pass
    created.clear()
    qapp.processEvents()


@pytest.fixture(autouse=True)
def _collect_mpl_cycles_between_tests():
    # matplotlib Figure/FigureCanvasQTAgg hold strong reference cycles
    # (figure.canvas <-> canvas.figure plus mpl_connect lambdas capturing
    # self). Tests that don't register widgets with qtbot leave zombies
    # behind; once enough accumulate, a subsequent paintEvent allocation
    # trips Python's cyclic GC mid-QPainter.drawImage and segfaults on
    # Windows. Forcing a collection between tests keeps the heap clean so
    # no collection fires inside a live paint path.
    yield
    gc.collect()


@pytest.fixture
def loaded_csv(tmp_path):
    """Create a small CSV for file-load tests."""
    import pandas as pd
    import numpy as np
    t = np.linspace(0, 1.0, 1000)
    df = pd.DataFrame({"time": t, "speed": 1000 * np.sin(2 * np.pi * 5 * t), "torque": 50 + 5 * np.cos(2 * np.pi * 3 * t)})
    p = tmp_path / "sample.csv"
    df.to_csv(p, index=False)
    return str(p)
