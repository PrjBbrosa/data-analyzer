"""Board-top overlay: ghost preview, snap highlight, later handles/marquee.

Transparent background: ``WA_TranslucentBackground`` disables QSS on this
widget, so ``paintEvent`` always fills (Gotchas). Mouse events pass through.
"""
from __future__ import annotations

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from .free_grid import Rect

LEGAL_FILL = QColor(45, 127, 249, 40)
LEGAL_PEN = QColor("#2d7ff9")
ILLEGAL_FILL = QColor(255, 32, 56, 40)
ILLEGAL_PEN = QColor("#ff2038")
GHOST_OPACITY = 0.45


class GhostOverlay(QWidget):
    """Single overlay owned by ``FreeGridBoard``."""

    _owned_names = (
        "_ghost_image",
        "_ghost_rect",
        "_highlight",
        "_legal",
        "_badge",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewGhostOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._ghost_image: QImage | None = None
        self._ghost_rect: QRect | None = None
        self._highlight: QRect | None = None
        self._legal = True
        self._badge = ""
        self.hide()

    def is_showing(self) -> bool:
        return self.isVisible() and (
            self._ghost_rect is not None or self._highlight is not None
        )

    def set_move_preview(
        self,
        image: QImage | None,
        ghost: Rect,
        highlight: Rect,
        *,
        legal: bool,
        badge: str = "",
    ) -> None:
        self._ghost_image = image
        self._ghost_rect = QRect(*ghost)
        self._highlight = QRect(*highlight)
        self._legal = bool(legal)
        self._badge = str(badge)
        if not self.isVisible():
            self.show()
        self.raise_()
        self.update()

    def clear(self) -> None:
        self._ghost_image = None
        self._ghost_rect = None
        self._highlight = None
        self._badge = ""
        self.hide()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
            if self._highlight is not None:
                fill = LEGAL_FILL if self._legal else ILLEGAL_FILL
                pen = LEGAL_PEN if self._legal else ILLEGAL_PEN
                painter.fillRect(self._highlight, fill)
                painter.setPen(QPen(pen, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(self._highlight.adjusted(1, 1, -1, -1))
            if self._ghost_image is not None and self._ghost_rect is not None:
                painter.setOpacity(GHOST_OPACITY)
                painter.drawImage(self._ghost_rect, self._ghost_image)
                painter.setOpacity(1.0)
            if self._badge and self._highlight is not None:
                painter.setPen(QColor("#0f172a"))
                painter.drawText(
                    self._highlight.adjusted(8, 4, -8, -4),
                    Qt.AlignTop | Qt.AlignLeft,
                    self._badge,
                )
        finally:
            painter.end()
