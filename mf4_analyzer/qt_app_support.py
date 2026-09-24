"""Lazy Qt helpers shared by the main process and the splash child.

Importing this module does not import PyQt. ``configure_high_dpi`` must run
before ``QApplication`` is created.
"""
from __future__ import annotations

import os
from typing import Any


# Same inset the main window has always used from the top-left of its screen.
_WINDOW_SCREEN_MARGIN = 100


def parse_screen_rect(detail: Any) -> tuple[int, int, int, int] | None:
    """Read ``{"screen": [x, y, w, h]}`` from a splash IPC detail."""

    if not isinstance(detail, dict):
        return None
    raw = detail.get("screen")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x, y, width, height = (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (x, y, width, height)


def window_origin_on_screen(
    avail: tuple[int, int, int, int],
    window_width: int,
    window_height: int,
    *,
    margin: int = _WINDOW_SCREEN_MARGIN,
) -> tuple[int, int]:
    """Place a window on one screen's work area, inset from that screen's origin.

    ``avail`` is ``QScreen.availableGeometry()`` in virtual-desktop coordinates,
    so a monitor left of the primary screen has a negative x. The historical
    ``setGeometry(100, 100, ...)`` inset is kept, but measured from this screen
    rather than from the primary origin.
    """

    ax, ay, aw, ah = avail
    width = max(1, int(window_width))
    height = max(1, int(window_height))
    inset = max(0, int(margin))
    if width >= aw:
        x = ax
    else:
        x = min(max(ax, ax + inset), ax + aw - width)
    if height >= ah:
        y = ay
    else:
        y = min(max(ay, ay + inset), ay + ah - height)
    return (int(x), int(y))


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
