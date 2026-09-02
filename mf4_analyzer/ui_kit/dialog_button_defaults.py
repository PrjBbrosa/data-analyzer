"""Explicit QDialog default-button flags.

Qt gives every ``QPushButton`` ``autoDefault=True`` inside a ``QDialog``, so
the first created button silently becomes the Enter target. Callers must
name the unique confirm button; this helper does not guess by creation
order and does not install a key filter.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QPushButton, QWidget


def set_unique_default_button(
    confirm: QPushButton,
    host: QWidget | None = None,
) -> None:
    """Make ``confirm`` the unique default; disable autoDefault on siblings.

    ``host`` is the dialog whose ``QPushButton`` children should be updated.
    Nested dialogs must pass themselves so parent-dialog buttons are left
    alone. Defaults to ``confirm.window()``.
    """
    root = host if host is not None else confirm.window()
    for button in root.findChildren(QPushButton):
        is_confirm = button is confirm
        button.setAutoDefault(is_confirm)
        button.setDefault(is_confirm)
