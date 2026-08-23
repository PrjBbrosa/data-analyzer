"""Shared eight-way resize cursor mapping for cards and author objects."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCursor

HANDLE_CURSORS = {
    "n": Qt.SizeVerCursor,
    "s": Qt.SizeVerCursor,
    "e": Qt.SizeHorCursor,
    "w": Qt.SizeHorCursor,
    "nw": Qt.SizeFDiagCursor,
    "se": Qt.SizeFDiagCursor,
    "ne": Qt.SizeBDiagCursor,
    "sw": Qt.SizeBDiagCursor,
}


def cursor_for_handle(handle: object) -> QCursor | None:
    """Return the Qt cursor for one N/S/E/W/NE/… handle, or None."""
    shape = HANDLE_CURSORS.get(str(handle or ""))
    if shape is None:
        return None
    return QCursor(shape)


__all__ = ["HANDLE_CURSORS", "cursor_for_handle"]
