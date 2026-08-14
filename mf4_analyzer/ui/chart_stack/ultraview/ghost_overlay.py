"""Board-top overlay: ghost preview, highlight, handles, replace ring, marquee.

Transparent background: ``WA_TranslucentBackground`` disables QSS on this
widget, so ``paintEvent`` always fills (Gotchas). Mouse events pass through;
handle hit-testing lives on the card so the overlay never steals presses.
"""
from __future__ import annotations

from typing import Sequence

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
MARQUEE_FILL = QColor(45, 127, 249, 24)
GHOST_OPACITY = 0.45


class GhostOverlay(QWidget):
    """Single overlay owned by ``FreeGridBoard``."""

    _owned_names = (
        "_ghosts",
        "_highlights",
        "_legal",
        "_badge",
        "_handles_rect",
        "_ring_rect",
        "_marquee",
        "_selection_rects",
        "_reject_mark",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewGhostOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._ghosts: tuple[tuple[QImage | None, QRect], ...] = ()
        self._highlights: tuple[QRect, ...] = ()
        self._legal = True
        self._badge = ""
        self._handles_rect: QRect | None = None
        self._ring_rect: QRect | None = None
        self._marquee: QRect | None = None
        self._selection_rects: tuple[QRect, ...] = ()
        self._reject_mark = False
        self.hide()

    @property
    def _ghost_rect(self) -> QRect | None:
        return self._ghosts[0][1] if self._ghosts else None

    @property
    def _highlight(self) -> QRect | None:
        return self._highlights[0] if self._highlights else None

    @property
    def _ghost_image(self) -> QImage | None:
        return self._ghosts[0][0] if self._ghosts else None

    def is_showing(self) -> bool:
        return self.isVisible() and self._has_content()

    def _has_content(self) -> bool:
        return bool(
            self._ghosts
            or self._highlights
            or self._handles_rect is not None
            or self._ring_rect is not None
            or self._marquee is not None
            or self._selection_rects
        )

    def set_replace_ring(self, card: Rect | None) -> None:
        self._ring_rect = QRect(*card) if card is not None else None
        self._present()

    def set_marquee(self, rect: Rect | None) -> None:
        self._marquee = QRect(*rect) if rect is not None else None
        self._present()

    def set_selection_handles(self, card: Rect | None) -> None:
        if card is None:
            self.set_selection_rects((), handles=False)
            return
        self.set_selection_rects((card,), handles=True)

    def set_selection_rects(
        self, rects: Sequence[Rect], *, handles: bool
    ) -> None:
        self._selection_rects = tuple(QRect(*item) for item in rects)
        self._handles_rect = (
            QRect(self._selection_rects[0])
            if handles and len(self._selection_rects) == 1
            else None
        )
        self._ghosts = ()
        self._highlights = ()
        self._badge = ""
        self._reject_mark = False
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
        self.set_move_previews(
            ((image, ghost),),
            (highlight,),
            legal=legal,
            badge=badge,
            handles=handles,
        )

    def set_move_previews(
        self,
        ghosts: Sequence[tuple[QImage | None, Rect]],
        highlights: Sequence[Rect],
        *,
        legal: bool,
        badge: str = "",
        handles: bool = False,
    ) -> None:
        self._ghosts = tuple(
            (image, QRect(*ghost)) for image, ghost in ghosts if ghost is not None
        )
        self._highlights = tuple(QRect(*item) for item in highlights)
        self._legal = bool(legal)
        self._reject_mark = not self._legal
        self._badge = str(badge)
        self._handles_rect = (
            QRect(self._highlights[0]) if handles and self._highlights else None
        )
        self._present()

    def clear(self) -> None:
        self._ghosts = ()
        self._highlights = ()
        self._badge = ""
        self._handles_rect = None
        self._ring_rect = None
        self._marquee = None
        self._selection_rects = ()
        self._reject_mark = False
        self.hide()
        self.update()

    def _present(self) -> None:
        if not self._has_content():
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
            fill = LEGAL_FILL if self._legal else ILLEGAL_FILL
            pen = LEGAL_PEN if self._legal else ILLEGAL_PEN
            style = Qt.SolidLine if self._legal else Qt.DashLine
            for highlight in self._highlights:
                painter.fillRect(highlight, fill)
                painter.setPen(QPen(pen, 2 if self._legal else 3, style))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(highlight.adjusted(1, 1, -1, -1))
            for image, ghost in self._ghosts:
                if image is None:
                    continue
                painter.setOpacity(GHOST_OPACITY)
                painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
                painter.drawImage(ghost, image)
                painter.setOpacity(1.0)
            if self._badge and self._highlights:
                painter.setPen(QColor("#0f172a"))
                painter.drawText(
                    self._highlights[0].adjusted(8, 4, -8, -4),
                    Qt.AlignTop | Qt.AlignLeft,
                    self._badge,
                )
            if self._reject_mark and self._highlights:
                mark = self._highlights[0]
                cx = mark.right() - 16
                cy = mark.top() + 16
                painter.setPen(QPen(ILLEGAL_PEN, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(cx - 7, cy - 7, 14, 14)
                painter.drawLine(cx - 4, cy - 4, cx + 4, cy + 4)
                painter.drawLine(cx + 4, cy - 4, cx - 4, cy + 4)
            if self._ring_rect is not None:
                painter.setPen(QPen(LEGAL_PEN, 3))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(self._ring_rect.adjusted(-6, -6, 6, 6), 10, 10)
            if self._marquee is not None:
                painter.setPen(QPen(LEGAL_PEN, 1, Qt.DashLine))
                painter.setBrush(MARQUEE_FILL)
                painter.drawRect(self._marquee)
            if not self._highlights:
                painter.setPen(QPen(LEGAL_PEN, 1))
                painter.setBrush(Qt.NoBrush)
                for rect in self._selection_rects:
                    painter.drawRect(rect.adjusted(1, 1, -1, -1))
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
