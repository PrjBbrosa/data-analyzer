"""Shared fixtures for Cockpit UI tests.

Mirrors ``tests/ui/conftest.py``: force offscreen Qt before
``QApplication`` is constructed, expose a session-wide ``qapp``
fixture, and force a GC sweep between tests so matplotlib /
``FigureCanvasQTAgg`` cycles don't crash a subsequent paintEvent.
"""

from __future__ import annotations

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """Session-wide QApplication so each test reuses the instance."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _gc_between_tests():
    yield
    gc.collect()
