"""Shared local-file drag/drop helpers for MainWindow and BatchSheet.

Keep this module in ``ui/`` (not ``ui_kit``): it only depends on pathlib and
Qt MIME/widgets, and must not create a ``ui_kit → ui`` edge.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget


def iter_local_paths(mime) -> list[str]:
    """Return local filesystem paths from mime URLs (may include dirs)."""
    if mime is None or not mime.hasUrls():
        return []
    paths: list[str] = []
    for url in mime.urls():
        path = url.toLocalFile()
        if path:
            paths.append(path)
    return paths


def filter_drop_files(paths, *, suffixes: set[str]) -> list[str]:
    """Keep existing files whose ``suffix.lower()`` is in ``suffixes``."""
    allowed = {s.lower() for s in suffixes}
    kept: list[str] = []
    for path in paths:
        parsed = Path(path)
        if parsed.is_file() and parsed.suffix.lower() in allowed:
            kept.append(path)
    return kept


def has_supported_drop_suffix(paths, *, suffixes: set[str]) -> bool:
    """True if any path's suffix is in ``suffixes`` (existence not required)."""
    allowed = {s.lower() for s in suffixes}
    return any(Path(path).suffix.lower() in allowed for path in paths)


class DropOverlay(QWidget):
    """Semi-transparent drop highlight painted without stylesheet fill."""

    _ACCENT = QColor(37, 99, 235)

    def __init__(self, parent=None, *, message: str = "松手导入文件"):
        super().__init__(parent)
        self._message = message
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()

        fill = QColor(self._ACCENT)
        fill.setAlpha(30)
        painter.fillRect(rect, fill)

        pen = QPen(self._ACCENT, 2, Qt.DashLine)
        painter.setPen(pen)
        inset = rect.adjusted(10, 10, -10, -10)
        painter.drawRoundedRect(inset, 12, 12)

        font = QFont(self.font())
        font.setPointSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self._ACCENT)
        painter.drawText(rect, Qt.AlignCenter, self._message)
        painter.end()


# Backward-compatible alias for callers that imported the private name.
_DropOverlay = DropOverlay
