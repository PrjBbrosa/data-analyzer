"""Shared pytest fixtures for UI tests."""
import gc
import os
# Force offscreen Qt platform for headless CI *before* QApplication exists
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication


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
