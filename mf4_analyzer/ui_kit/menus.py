"""Shared menu chrome helpers."""
from __future__ import annotations

from PyQt5.QtWidgets import QMenu

from .popup_shell import apply_popup_shell


def apply_rounded_menu_chrome(
    menu: QMenu, *, gutter: str | None = None,
) -> QMenu:
    """Suppress native square popup backing behind rounded QSS menus.

    ``gutter="check"`` opts into the slightly wider item right-pad used for
    checkable rows and submenu arrows (see ``style.qss`` ``QMenu[gutter=…]``).
    Plain single-action menus keep the compact default pad.
    """
    apply_popup_shell(menu)
    if gutter:
        menu.setProperty("gutter", str(gutter))
        style = menu.style()
        if style is not None:
            style.unpolish(menu)
            style.polish(menu)
    return menu
