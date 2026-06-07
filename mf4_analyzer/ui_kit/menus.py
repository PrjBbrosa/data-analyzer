"""Shared menu chrome helpers."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMenu


def apply_rounded_menu_chrome(menu: QMenu) -> QMenu:
    """Suppress native square popup backing behind rounded QSS menus."""
    menu.setWindowFlags(
        menu.windowFlags()
        | Qt.FramelessWindowHint
        | Qt.NoDropShadowWindowHint
    )
    menu.setAttribute(Qt.WA_TranslucentBackground, True)
    return menu
