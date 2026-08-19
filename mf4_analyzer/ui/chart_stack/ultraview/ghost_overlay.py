"""Board-top overlay: ghost preview, highlight, handles, replace ring, marquee.

Transparent background: ``WA_TranslucentBackground`` disables QSS on this
widget, so ``paintEvent`` always fills (Gotchas). Mouse events pass through;
handle hit-testing lives on the card so the overlay never steals presses.
"""
from __future__ import annotations

from typing import Sequence

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui_kit.ultraview_style import titanium_color

from .free_grid import HANDLE_NAMES, handle_visual_rects, Rect

LEGAL_FILL = QColor(45, 127, 249, 40)
LEGAL_PEN = QColor("#2d7ff9")
ILLEGAL_FILL = QColor(255, 32, 56, 40)
ILLEGAL_PEN = QColor("#ff2038")
HANDLE_FILL = QColor("#ffffff")
HANDLE_EDGE = QColor("#2d7ff9")
MARQUEE_FILL = QColor(45, 127, 249, 24)
GHOST_OPACITY = 1.0
CONTINUE_BAND_PX = 72
_PREVIEW_DIRTY_MARGIN = 48
_BADGE_PAD_X = 8
_BADGE_PAD_Y = 4
_BRAND = QColor(titanium_color("brand"))
_COPPER = QColor(titanium_color("copper"))
_INK = QColor(titanium_color("ink"))


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
        "_safety_wall",
        "_continue_sides",
        "_hint_copy",
        "_viewport_rect",
        "_safety_bounds_rect",
        "_safety_sides",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewGhostOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._ghosts: tuple[tuple[QImage | QPixmap | None, QRect], ...] = ()
        self._highlights: tuple[QRect, ...] = ()
        self._legal = True
        self._badge = ""
        self._handles_rect: QRect | None = None
        self._ring_rect: QRect | None = None
        self._marquee: QRect | None = None
        self._selection_rects: tuple[QRect, ...] = ()
        self._reject_mark = False
        self._safety_wall = False
        self._continue_sides: tuple[str, ...] = ()
        self._hint_copy = ""
        self._viewport_rect: QRect | None = None
        self._safety_bounds_rect: QRect | None = None
        self._safety_sides: tuple[str, ...] = ()
        self.hide()

    @property
    def _ghost_rect(self) -> QRect | None:
        return self._ghosts[0][1] if self._ghosts else None

    @property
    def _highlight(self) -> QRect | None:
        return self._highlights[0] if self._highlights else None

    @property
    def _ghost_image(self) -> QImage | QPixmap | None:
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
            or self._continue_sides
            or self._safety_sides
            or self._hint_copy
        )

    def edge_hint_mode(self) -> str | None:
        """``safety`` wall, ``continue`` fade, or no edge hint."""
        if self._safety_wall or self._safety_sides:
            return "safety"
        if self._continue_sides:
            return "continue"
        return None

    def edge_hint_copy(self) -> str:
        return self._hint_copy

    def edge_hint_sides(self) -> tuple[str, ...]:
        return self._continue_sides

    def set_continue_hint(
        self,
        sides: Sequence[str] = (),
        copy: str = "",
        viewport: QRect | None = None,
    ) -> None:
        """Gesture-only titanium-blue fade band. Not a toast, not a wall."""
        next_sides = tuple(side for side in sides if side)
        next_copy = str(copy or "")
        next_viewport = QRect(viewport) if viewport is not None else None
        if (
            next_sides == self._continue_sides
            and next_copy == self._hint_copy
            and next_viewport == self._viewport_rect
        ):
            return
        self._continue_sides = next_sides
        self._hint_copy = next_copy
        self._viewport_rect = next_viewport
        self._present()

    def set_safety_bounds(
        self,
        rect: QRect | None = None,
        sides: Sequence[str] = (),
    ) -> None:
        """Copper-red dashed hard edge at the engineering safety bound."""
        self._safety_bounds_rect = QRect(rect) if rect is not None else None
        self._safety_sides = tuple(side for side in sides if side)
        self._present()

    def clear_edge_hint(self) -> None:
        self._continue_sides = ()
        self._hint_copy = ""
        self._viewport_rect = None
        self._safety_bounds_rect = None
        self._safety_sides = ()
        self._safety_wall = False
        self._present()

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
        self._safety_wall = False
        self._present()

    def set_move_preview(
        self,
        image: QImage | QPixmap | None,
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
        ghosts: Sequence[tuple[QImage | QPixmap | None, Rect]],
        highlights: Sequence[Rect],
        *,
        legal: bool,
        badge: str = "",
        handles: bool = False,
        safety_wall: bool = False,
        safety_bounds: QRect | None = None,
        safety_sides: Sequence[str] = (),
    ) -> None:
        old_dirty = self._preview_dirty_rect()
        old_signature = self._preview_signature()
        self._ghosts = tuple(
            (image, QRect(*ghost)) for image, ghost in ghosts if ghost is not None
        )
        self._highlights = tuple(QRect(*item) for item in highlights)
        self._legal = bool(legal)
        self._safety_wall = bool(safety_wall)
        self._reject_mark = not self._legal
        self._badge = str(badge)
        if self._safety_wall:
            self._safety_bounds_rect = (
                QRect(safety_bounds) if safety_bounds is not None else None
            )
            self._safety_sides = tuple(side for side in safety_sides if side)
        else:
            self._safety_bounds_rect = None
            self._safety_sides = ()
        self._handles_rect = (
            QRect(self._highlights[0]) if handles and self._highlights else None
        )
        if (
            self._preview_signature() == old_signature
            and self.isVisible() == bool(self._has_content())
        ):
            return
        self._present(self._united_dirty(old_dirty, self._preview_dirty_rect()))

    def clear(self) -> None:
        self._ghosts = ()
        self._highlights = ()
        self._badge = ""
        self._handles_rect = None
        self._ring_rect = None
        self._marquee = None
        self._selection_rects = ()
        self._reject_mark = False
        self._safety_wall = False
        self._continue_sides = ()
        self._hint_copy = ""
        self._viewport_rect = None
        self._safety_bounds_rect = None
        self._safety_sides = ()
        self.hide()
        self.update()

    def _preview_signature(self) -> tuple:
        ghosts = tuple(
            (
                None if image is None else id(image),
                ghost.x(),
                ghost.y(),
                ghost.width(),
                ghost.height(),
            )
            for image, ghost in self._ghosts
        )
        highlights = tuple(
            (item.x(), item.y(), item.width(), item.height())
            for item in self._highlights
        )
        handles = None
        if self._handles_rect is not None:
            handles = (
                self._handles_rect.x(),
                self._handles_rect.y(),
                self._handles_rect.width(),
                self._handles_rect.height(),
            )
        return (
            ghosts,
            highlights,
            self._legal,
            self._badge,
            handles,
            self._safety_wall,
            self._reject_mark,
        )

    def _preview_dirty_rect(self) -> QRect:
        boxes = [ghost for _image, ghost in self._ghosts]
        boxes.extend(self._highlights)
        if self._handles_rect is not None:
            boxes.append(self._handles_rect)
        if self._badge and self._highlights:
            boxes.append(self._highlights[0].adjusted(0, 0, 0, 0))
        if self._safety_bounds_rect is not None:
            boxes.append(self._safety_bounds_rect)
        if not boxes:
            return QRect()
        united = QRect(boxes[0])
        for box in boxes[1:]:
            united = united.united(box)
        margin = _PREVIEW_DIRTY_MARGIN
        return united.adjusted(-margin, -margin, margin, margin)

    @staticmethod
    def _united_dirty(old: QRect, new: QRect) -> QRect:
        if old.isNull() or not old.isValid():
            return QRect(new)
        if new.isNull() or not new.isValid():
            return QRect(old)
        return old.united(new)

    def _present(self, dirty: QRect | None = None) -> None:
        if not self._has_content():
            self.hide()
            return
        first_show = not self.isVisible()
        if first_show:
            self.show()
            self.raise_()
            dirty = None
        if dirty is None or dirty.isNull() or not dirty.isValid():
            self.update()
            return
        clipped = dirty.intersected(self.rect()) if self.rect().isValid() else dirty
        if clipped.isEmpty():
            self.update()
            return
        self.update(clipped)

    def _paint_continue_hint(self, painter: QPainter) -> None:
        if not self._continue_sides:
            return
        viewport = self._viewport_rect if self._viewport_rect is not None else self.rect()
        band = CONTINUE_BAND_PX
        for side in self._continue_sides:
            rect, start, end = _band_geometry(viewport, side, band)
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            inner = QColor(_BRAND)
            inner.setAlpha(0)
            outer = QColor(_BRAND)
            outer.setAlpha(48)
            gradient = QLinearGradient(start[0], start[1], end[0], end[1])
            gradient.setColorAt(0.0, outer)
            gradient.setColorAt(1.0, inner)
            painter.fillRect(rect, gradient)
            line = QColor(_BRAND)
            line.setAlpha(90)
            painter.setPen(QPen(line, 1, Qt.DotLine))
            painter.setBrush(Qt.NoBrush)
            if side == "left":
                painter.drawLine(rect.left() + 1, rect.top(), rect.left() + 1, rect.bottom())
            elif side == "right":
                painter.drawLine(rect.right() - 1, rect.top(), rect.right() - 1, rect.bottom())
            elif side == "top":
                painter.drawLine(rect.left(), rect.top() + 1, rect.right(), rect.top() + 1)
            else:
                painter.drawLine(rect.left(), rect.bottom() - 1, rect.right(), rect.bottom() - 1)
        if self._hint_copy:
            painter.setPen(_INK)
            box = viewport.adjusted(12, 12, -12, -12)
            painter.drawText(box, Qt.AlignTop | Qt.AlignHCenter, self._hint_copy)

    def _paint_size_badge(
        self, painter: QPainter, anchor: QRect, legal: bool
    ) -> None:
        """Opaque size chip so the span stays readable over the preview."""
        font = QFont(painter.font())
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        text = str(self._badge)
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(text)
        text_h = metrics.height()
        width = text_w + 2 * _BADGE_PAD_X
        height = text_h + 2 * _BADGE_PAD_Y
        x = anchor.left() + 6
        y = anchor.top() + 6
        chip = QRect(x, y, width, height)
        fill = QColor(ILLEGAL_PEN if not legal else LEGAL_PEN)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(chip, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            chip.adjusted(_BADGE_PAD_X, 0, -_BADGE_PAD_X, 0),
            Qt.AlignVCenter | Qt.AlignLeft,
            text,
        )

    def _paint_safety_wall(self, painter: QPainter) -> None:
        if not self._safety_sides or self._safety_bounds_rect is None:
            return
        bounds = self._safety_bounds_rect
        clip = self._viewport_rect if self._viewport_rect is not None else self.rect()
        painter.setPen(QPen(_COPPER, 2, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        if "left" in self._safety_sides:
            painter.drawLine(bounds.left(), clip.top(), bounds.left(), clip.bottom())
        if "right" in self._safety_sides:
            painter.drawLine(bounds.right(), clip.top(), bounds.right(), clip.bottom())
        if "top" in self._safety_sides:
            painter.drawLine(clip.left(), bounds.top(), clip.right(), bounds.top())
        if "bottom" in self._safety_sides:
            painter.drawLine(clip.left(), bounds.bottom(), clip.right(), bounds.bottom())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
            self._paint_continue_hint(painter)
            self._paint_safety_wall(painter)
            # Safety wall keeps a legal-looking mover; collision reject stays
            # red. Pixmaps go down first so stroke + badge stay readable.
            card_legal = self._legal or self._safety_wall
            fill = LEGAL_FILL if card_legal else ILLEGAL_FILL
            pen = LEGAL_PEN if card_legal else ILLEGAL_PEN
            style = Qt.SolidLine if card_legal else Qt.DashLine
            stroke = 2 if card_legal else 4
            for highlight in self._highlights:
                if not self._safety_wall:
                    painter.fillRect(highlight, fill)
            for image, ghost in self._ghosts:
                if image is None:
                    continue
                painter.setOpacity(0.55 if not card_legal else GHOST_OPACITY)
                painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                if isinstance(image, QPixmap):
                    painter.drawPixmap(ghost, image)
                else:
                    painter.drawImage(ghost, image)
                painter.setOpacity(1.0)
            for index, highlight in enumerate(self._highlights):
                painter.setPen(QPen(pen, stroke if index == 0 else 2, style))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(highlight.adjusted(1, 1, -1, -1))
            if self._badge and self._highlights:
                self._paint_size_badge(painter, self._highlights[0], card_legal)
            if self._reject_mark and self._highlights:
                mark = self._highlights[0]
                cx = mark.right() - 16
                cy = mark.top() + 16
                mark_pen = QPen(_COPPER if self._safety_wall else ILLEGAL_PEN, 2)
                painter.setPen(mark_pen)
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


def _band_geometry(
    viewport: QRect, side: str, band: int
) -> tuple[QRect, tuple[float, float], tuple[float, float]]:
    """Viewport-local fade band: outer edge → inner face."""
    depth = max(1, int(band))
    if side == "left":
        width = min(depth, max(1, viewport.width()))
        rect = QRect(viewport.x(), viewport.y(), width, viewport.height())
        return rect, (float(rect.left()), float(rect.center().y())), (
            float(rect.right()),
            float(rect.center().y()),
        )
    if side == "right":
        width = min(depth, max(1, viewport.width()))
        rect = QRect(viewport.right() - width + 1, viewport.y(), width, viewport.height())
        return rect, (float(rect.right()), float(rect.center().y())), (
            float(rect.left()),
            float(rect.center().y()),
        )
    if side == "top":
        height = min(depth, max(1, viewport.height()))
        rect = QRect(viewport.x(), viewport.y(), viewport.width(), height)
        return rect, (float(rect.center().x()), float(rect.top())), (
            float(rect.center().x()),
            float(rect.bottom()),
        )
    height = min(depth, max(1, viewport.height()))
    rect = QRect(viewport.x(), viewport.bottom() - height + 1, viewport.width(), height)
    return rect, (float(rect.center().x()), float(rect.bottom())), (
        float(rect.center().x()),
        float(rect.top()),
    )
