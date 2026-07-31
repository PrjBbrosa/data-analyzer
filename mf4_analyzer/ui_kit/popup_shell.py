"""Shared native-window shell for rounded Qt popup surfaces."""
from __future__ import annotations

from PyQt5.QtCore import Qt


POPUP_SHELL_FLAGS = Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint


def apply_popup_shell(window) -> bool:
    """Add the transparent, frameless popup shell without replacing flags.

    The caller keeps ownership of type-specific presentation such as frame
    shapes and stylesheets.  Returning ``True`` reports that the window's
    shell state changed; repeated calls are otherwise safe no-ops.
    """
    if window is None:
        return False

    needs_flags = (window.windowFlags() & POPUP_SHELL_FLAGS) != POPUP_SHELL_FLAGS
    needs_translucent_background = not window.testAttribute(
        Qt.WA_TranslucentBackground
    )
    if not needs_flags and not needs_translucent_background:
        return False

    if needs_flags:
        window.setWindowFlags(window.windowFlags() | POPUP_SHELL_FLAGS)
    if needs_translucent_background:
        window.setAttribute(Qt.WA_TranslucentBackground, True)
    return True
