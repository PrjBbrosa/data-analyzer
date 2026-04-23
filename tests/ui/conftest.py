"""Shared pytest fixtures for UI tests."""
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
