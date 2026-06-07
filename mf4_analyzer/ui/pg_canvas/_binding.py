"""Shared pyqtgraph Qt-binding guard.

Import this before importing pyqtgraph from any pg_canvas submodule.
"""

from __future__ import annotations

import os as _os

_os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")
