"""Lazy Qt helpers shared by the main process and the splash child.

Importing this module does not import PyQt. ``configure_high_dpi`` must run
before ``QApplication`` is created.
"""
from __future__ import annotations

import os


def configure_high_dpi() -> None:
    """Enable Qt per-monitor DPI scaling before ``QApplication`` exists."""

    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    from PyQt5.QtCore import QCoreApplication, Qt
    from PyQt5.QtGui import QGuiApplication

    for attribute_name in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
        attribute = getattr(Qt, attribute_name, None)
        if attribute is not None:
            QCoreApplication.setAttribute(attribute, True)

    policy_enum = getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None)
    if policy_enum is not None and hasattr(
        QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"
    ):
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy_enum.PassThrough)
