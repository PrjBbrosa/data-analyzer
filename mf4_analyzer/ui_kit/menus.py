"""Shared menu chrome helpers."""
from __future__ import annotations

from PyQt5.QtWidgets import QMenu

from .popup_shell import apply_popup_shell


def apply_rounded_menu_chrome(menu: QMenu) -> QMenu:
    """Suppress native square popup backing behind rounded QSS menus."""
    apply_popup_shell(menu)
    return menu
