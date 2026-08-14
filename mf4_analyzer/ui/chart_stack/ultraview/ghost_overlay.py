"""Board-top overlay: ghost preview, snap highlight, handles, later marquee.

Transparent background: ``WA_TranslucentBackground`` disables QSS on this
widget, so ``paintEvent`` always fills (Gotchas). Mouse events pass through;
handle hit-testing lives on the card so the overlay never steals presses.
"""
from __future__ import annotations

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from .free_grid import HANDLE_NAMES, handle_visual_rects, Rect

LEGAL_FILL = QColor(45, 127, 249, 40)
LEGAL_PEN = QColor("#2d7ff9")
ILLEGAL_FILL = QColor(255, 32, 56, 40)
ILLEGAL_PEN = QColor("#ff2038")
HANDLE_FILL = QColor("#ffffff")
HANDLE_EDGE = QColor("#2d7ff9")
GHOST_OPACITY = 0.45


class GhostOverlay(QWidget):
    """Single overlay owned by ``FreeGridBoard``."""

    _owned_names = (
        "_ghost_image",
        "_ghost_rect",
        "_highlight",
        "_legal",
        "_badge",
        "_handles_rect",
        "_ring_rect",
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
        self._handles_rect: QRect | None = None
        self._ring_rect: QRect | None = None
        self.hide()

    def is_showing(self) -> bool:
        return self.isVisible() and (
            self._ghost_rect is not None
            or self._highlight is not None
            or self._handles_rect is not None
            or self._ring_rect is not None
        )

    def set_replace_ring(self, card: Rect | None) -> None:
        self._ring_rect = QRect(*card) if card is not None else None
        if self._ring_rect is None and self._handles_rect is None and self._ghost_rect is None:
            self.hide()
        self._present()

    def set_selection_handles(self, card: Rect | None) -> None:
        self._handles_rect = QRect(*card) if card is not None else None
        self._ghost_image = None
        self._ghost_rect = None
        self._highlight = None
        self._badge = ""
        self._present()

    def set_move_preview(
        self,
        image: QImage | None,
        ghost: Rect,
        highlight: Rect,
        *,
        legal: bool,
        badge: str = "",
        handles: bool = False,
    ) -> None:
        self._ghost_image = image
        self._ghost_rect = QRect(*ghost)
        self._highlight = QRect(*highlight)
        self._legal = bool(legal)
        self._badge = str(badge)
        self._handles_rect = QRect(*highlight) if handles else None
        self._present()

    def clear(self) -> None:
        self._ghost_image = None
        self._ghost_rect = None
        self._highlight = None
        self._badge = ""
        self._handles_rect = None
        self._ring_rect = None
        self.hide()
        self.update()

    def _present(self) -> None:
        if (
            self._ghost_rect is None
            and self._highlight is None
            and self._handles_rect is None
            and self._ring_rect is None
        ):
            self.hide()
        elif not self.isVisible():
            self.show()
        self.raise_()
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
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.drawImage(self._ghost_rect, self._ghost_image)
                painter.setOpacity(1.0)
            if self._badge and self._highlight is not None:
                painter.setPen(QColor("#0f172a"))
                painter.drawText(
                    self._highlight.adjusted(8, 4, -8, -4),
                    Qt.AlignTop | Qt.AlignLeft,
                    self._badge,
                )
            if self._ring_rect is not None:
                painter.setPen(QPen(LEGAL_PEN, 3))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(self._ring_rect.adjusted(-6, -6, 6, 6), 10, 10)
            if self._handles_rect is not None:
                painter.setBrush(HANDLE_FILL)
                painter.setPen(QPen(HANDLE_EDGE, 1))
                box = (
                    self._handles_rect.x(),
                    self._handles_rect.y(),
                    self._handles_rect.width(),
                    self._handles_rect.height(),
                )
                for name in HANDLE_NAMES:
                    hx, hy, hw, hh = handle_visual_rects(box)[name]
                    painter.drawRect(hx, hy, hw, hh)
        finally:
            painter.end()
