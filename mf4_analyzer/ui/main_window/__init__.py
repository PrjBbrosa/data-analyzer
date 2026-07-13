"""main_window package: re-exports MainWindow from window.py.

This __init__.py is the monkeypatch anchor for all names that tests patch
via ``patch('mf4_analyzer.ui.main_window.<Symbol>', ...)``.  The list is:

  - QFileDialog  (getOpenFileNames patched in smoke tests)
  - QMessageBox  (static-warning anchor)
  - FFTAnalyzer  (compute_averaged_fft / compute_peak_hold_fft patched)
  - importlib    (import_module patched in cockpit test)
  - np           (numpy module; tests patch mw.np.min/max/... as tripwires)

All names must remain importable from this namespace so existing
``patch('mf4_analyzer.ui.main_window.<Symbol>', ...)`` calls in the test
suite continue to work after the module-to-package split.

Methods in window.py that call QFileDialog at execution time use a
``sys.modules.get('mf4_analyzer.ui.main_window')`` runtime lookup so patches
applied here are visible at call time (not captured at import time).
``AnalysisJobService`` is the sole owner of QThread lifecycle. FFTAnalyzer is
only patched on the class itself (monkeypatch.setattr of a method), so the
re-export here is sufficient — no runtime lookup needed.
"""

import importlib  # monkeypatch anchor (test_analyzer_opens_cockpit)

import numpy as np  # monkeypatch anchor (mw.np.min/max/... tripwires)

from PyQt5.QtWidgets import QFileDialog, QMessageBox  # monkeypatch anchors
from ...signal import FFTAnalyzer  # monkeypatch anchor (compute_averaged_fft etc.)

from .window import MainWindow

__all__ = ["MainWindow"]
