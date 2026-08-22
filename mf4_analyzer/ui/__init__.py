"""UI subpackage: PyQt5 widgets, canvases, dialogs, and main window.

``MainWindow`` is loaded lazily so Qt-free modules under this package
(``ultraview_state``) can be imported without pulling Qt. Wave 5 Task 5.2
closed the ``ultraview_core`` → ``ui.ultraview_state`` seam, but this
lazy load remains required for ``from mf4_analyzer.ui.ultraview_state
import ...`` and ``from mf4_analyzer.ui import MainWindow``. Do not restore
a module-level ``from .main_window import MainWindow``.
"""

from __future__ import annotations

from typing import Any

__all__ = ["MainWindow"]


def __getattr__(name: str) -> Any:
    if name == "MainWindow":
        from .main_window import MainWindow as _MainWindow

        globals()["MainWindow"] = _MainWindow
        return _MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
