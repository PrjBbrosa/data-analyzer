"""Shared menu chrome helpers."""
from __future__ import annotations

from PyQt5.QtWidgets import QMenu

from .popup_shell import apply_popup_shell

_SUBMENU_SHELL_HOOK = "roundedSubmenuShellHook"


def apply_rounded_menu_chrome(
    menu: QMenu, *, gutter: str | None = None,
) -> QMenu:
    """Suppress native square popup backing behind rounded QSS menus.

    ``gutter="check"`` opts into the slightly wider item right-pad used for
    checkable rows and submenu arrows (see ``style.qss`` ``QMenu[gutter=…]``).
    Plain single-action menus keep the compact default pad.

    Nested ``QMenu.addMenu()`` windows are separate top-level popups. The
    parent's shell does not inherit, so this helper applies the same
    translucent/frameless flags to current children and again on
    ``aboutToShow`` (covers submenus added after the first call).
    """
    apply_popup_shell(menu)
    if gutter:
        menu.setProperty("gutter", str(gutter))
        style = menu.style()
        if style is not None:
            style.unpolish(menu)
            style.polish(menu)
    _install_submenu_shell_hook(menu)
    _apply_shell_to_submenus(menu)
    return menu


def add_rounded_submenu(menu: QMenu, title: str) -> QMenu:
    """Create a nested ``QMenu`` with the same rounded popup shell as ``menu``.

    Also gives the parent the check/arrow gutter so the submenu indicator
    is not clipped by the compact default item pad.
    """
    submenu = menu.addMenu(title)
    apply_rounded_menu_chrome(submenu)
    apply_rounded_menu_chrome(menu, gutter="check")
    return submenu


def _apply_shell_to_submenus(menu: QMenu) -> None:
    for action in menu.actions():
        submenu = action.menu()
        if submenu is None:
            continue
        apply_popup_shell(submenu)
        _install_submenu_shell_hook(submenu)
        _apply_shell_to_submenus(submenu)


def _install_submenu_shell_hook(menu: QMenu) -> None:
    if bool(menu.property(_SUBMENU_SHELL_HOOK)):
        return
    menu.setProperty(_SUBMENU_SHELL_HOOK, True)

    def _on_about_to_show() -> None:
        _apply_shell_to_submenus(menu)

    menu.aboutToShow.connect(_on_about_to_show)
