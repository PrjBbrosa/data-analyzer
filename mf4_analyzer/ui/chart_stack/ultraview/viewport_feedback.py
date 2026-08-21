"""Viewport-bounded FreeGrid gesture feedback surface.

FreeGrid transient chrome (move/resize, selection, marquee, insert, replace,
author handles) paints here. The widget is always the visible viewport size,
never the elastic Board extent. ``GhostOverlay`` remains the template
``BoardGrid`` overlay and must not be reattached to FreeGrid.

Geometry in a ``GestureFeedbackFrame`` is Board-widget local. Paint maps
through ``BoardToViewportTransform`` once per frame. Expose/resize/show may
repaint a cached frame; they must not call the planner.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRegion,
)
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui_kit.ultraview_style import titanium_color

from .free_grid import HANDLE_NAMES, handle_visual_rects, Rect
from .ghost_overlay import (
    CONTINUE_BAND_PX,
    GHOST_OPACITY,
    HANDLE_EDGE,
    HANDLE_FILL,
    ILLEGAL_PEN,
    LEGAL_PEN,
    MARQUEE_FILL,
    ORIGIN_MASK_FILL,
    ORIGIN_MASK_PEN,
    PREVIEW_COLLISION_REJECT,
    PREVIEW_DISPLACED_WARNING,
    PREVIEW_MOVER_VALID,
    PREVIEW_SAFETY_WALL,
    _band_geometry,
    _coerce_preview_item,
    _style_for_role,
)

_BADGE_PAD_X = 8
_BADGE_PAD_Y = 4
_BRAND = QColor(titanium_color("brand"))
_COPPER = QColor(titanium_color("copper"))
_INK = QColor(titanium_color("ink"))
_SCREEN_CHANGE_INTERNAL = 175

_GhostItem = tuple[QImage | QPixmap | None, QRect, str]


@dataclass(frozen=True)
class FeedbackItem:
    key: str
    rect: tuple[int, int, int, int]
    role: str
    image_key: str | None = None


@dataclass(frozen=True)
class BoardToViewportTransform:
    """Map Board-widget local pixels onto the viewport-sized surface."""

    revision: int = 0
    viewport_in_board: tuple[int, int] = (0, 0)
    origin_px: tuple[int, int] = (0, 0)
    zoom: float = 1.0

    def to_surface(self, rect: QRect) -> QRect:
        dx, dy = self.viewport_in_board
        return QRect(rect.x() - dx, rect.y() - dy, rect.width(), rect.height())

    def tuple_to_surface(self, box: tuple[int, int, int, int]) -> QRect:
        return self.to_surface(QRect(*box))


@dataclass(frozen=True)
class GestureFeedbackFrame:
    """Immutable FreeGrid presentation frame. No QWidget or planner state."""

    gesture_id: int
    generation: int
    layout_revision: int
    operation: str
    candidate_fingerprint: tuple
    items: tuple[FeedbackItem, ...] = ()
    selection_rects: tuple[tuple[int, int, int, int], ...] = ()
    handles_rect: tuple[int, int, int, int] | None = None
    marquee: tuple[int, int, int, int] | None = None
    ring_rect: tuple[int, int, int, int] | None = None
    origin_masks: tuple[tuple[int, int, int, int], ...] = ()
    badge: str = ""
    displace_copy: str = ""
    continue_sides: tuple[str, ...] = ()
    hint_copy: str = ""
    safety_wall: bool = False
    safety_bounds: tuple[int, int, int, int] | None = None
    safety_sides: tuple[str, ...] = ()
    legal: bool = True
    editor_exclusion: tuple[int, int, int, int] | None = None


class ViewportFeedbackSurface(QWidget):
    """Mouse-transparent paint-only surface sized to the visible viewport."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewViewportFeedback")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.NoFocus)
        self._ghosts: tuple[_GhostItem, ...] = ()
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
        self._origin_masks: tuple[QRect, ...] = ()
        self._displace_copy = ""
        self._editor_exclusion: QRect | None = None
        self._gesture_id = 0
        self._generation = 0
        self._layout_revision = 0
        self._operation = ""
        self._candidate_fingerprint: tuple = ()
        self._frame: GestureFeedbackFrame | None = None
        self._transform = BoardToViewportTransform()
        self._paint_transform = self._transform
        self._transform_board: QWidget | None = None
        self._transform_viewport: QWidget | None = None
        self.present_count = 0
        self.paint_count = 0
        self.hide()

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def _ghost_rect(self) -> QRect | None:
        return self._ghosts[0][1] if self._ghosts else None

    @property
    def _highlight(self) -> QRect | None:
        return self._highlights[0] if self._highlights else None

    @property
    def _ghost_image(self) -> QImage | QPixmap | None:
        return self._ghosts[0][0] if self._ghosts else None

    def current_frame(self) -> GestureFeedbackFrame | None:
        return self._frame

    def is_showing(self) -> bool:
        return self.isVisible() and self._has_content()

    def has_content(self) -> bool:
        return self._has_content()

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
            or self._origin_masks
            or self._displace_copy
        )

    def preview_roles(self) -> tuple[str, ...]:
        return tuple(role for _image, _rect, role in self._ghosts)

    def ghost_images(self) -> tuple[QImage | QPixmap | None, ...]:
        return tuple(image for image, _rect, _role in self._ghosts)

    def edge_hint_mode(self) -> str | None:
        if self._safety_wall or self._safety_sides:
            return "safety"
        if self._continue_sides:
            return "continue"
        return None

    def edge_hint_copy(self) -> str:
        return self._hint_copy

    def edge_hint_sides(self) -> tuple[str, ...]:
        return self._continue_sides

    def bind_transform_host(self, board: QWidget, viewport: QWidget) -> None:
        """Parent to the scroll viewport and map Board-local rects on paint."""
        if self.parentWidget() is not viewport:
            self.setParent(viewport)
        self._transform_board = board
        self._transform_viewport = viewport
        self.sync_host_geometry()
        self._raise_for_stack()

    def sync_host_geometry(self) -> None:
        host = self.parentWidget()
        if host is None:
            return
        target = host.rect()
        if self.geometry() != target:
            self.setGeometry(target)

    def set_editor_exclusion(self, rect: QRect | None) -> None:
        next_rect = QRect(rect) if rect is not None else None
        if next_rect == self._editor_exclusion:
            return
        self._editor_exclusion = next_rect
        if self._has_content():
            self.update()

    def present(
        self,
        frame: GestureFeedbackFrame,
        transform: BoardToViewportTransform | None = None,
    ) -> None:
        if frame.generation < self._generation:
            return
        if (
            self._frame is not None
            and frame.generation == self._generation
            and frame.candidate_fingerprint == self._candidate_fingerprint
            and (
                transform is None
                or transform.revision == self._transform.revision
            )
            and self.isVisible()
            and self._has_content()
        ):
            return
        self._install_frame(frame)
        if transform is not None:
            self._transform = transform
        self._present()

    def apply_transform(self, transform: BoardToViewportTransform) -> None:
        if transform.revision == self._transform.revision and (
            transform.viewport_in_board == self._transform.viewport_in_board
        ):
            return
        self._transform = transform
        if self._has_content():
            self.sync_host_geometry()
            self.update()

    def set_continue_hint(
        self,
        sides: Sequence[str] = (),
        copy: str = "",
        viewport: QRect | None = None,
    ) -> None:
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
        self._origin_masks = ()
        self._displace_copy = ""
        self._operation = "selection"
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
        ghosts: Sequence[tuple],
        highlights: Sequence[Rect],
        *,
        legal: bool,
        badge: str = "",
        handles: bool = False,
        safety_wall: bool = False,
        safety_bounds: QRect | None = None,
        safety_sides: Sequence[str] = (),
        origin_masks: Sequence[Rect] = (),
        displace_copy: str = "",
        gesture_id: int = 0,
        generation: int | None = None,
        layout_revision: int = 0,
        operation: str = "",
        candidate_fingerprint: tuple | None = None,
    ) -> None:
        parsed: list[_GhostItem] = []
        for index, item in enumerate(ghosts):
            if not item or item[1] is None:
                continue
            parsed.append(
                _coerce_preview_item(
                    item, index=index, legal=legal, safety_wall=safety_wall
                )
            )
        next_highlights = tuple(QRect(*item) for item in highlights)
        next_origins = tuple(QRect(*item) for item in origin_masks)
        next_handles = (
            QRect(next_highlights[0]) if handles and next_highlights else None
        )
        next_safety_bounds = (
            QRect(safety_bounds) if safety_wall and safety_bounds is not None else None
        )
        next_safety_sides = (
            tuple(side for side in safety_sides if side) if safety_wall else ()
        )
        fingerprint = candidate_fingerprint
        if fingerprint is None:
            fingerprint = _preview_fingerprint(
                parsed,
                next_highlights,
                next_origins,
                bool(legal),
                str(badge),
                str(displace_copy or ""),
                next_handles,
                bool(safety_wall),
                (not bool(legal)) and (not bool(safety_wall)),
                operation or ("resize" if handles else "move"),
                int(layout_revision),
            )
        if (
            fingerprint == self._candidate_fingerprint
            and self.isVisible()
            and self._has_content()
        ):
            return
        self._ghosts = tuple(parsed)
        self._highlights = next_highlights
        self._origin_masks = next_origins
        self._displace_copy = str(displace_copy or "")
        self._legal = bool(legal)
        self._safety_wall = bool(safety_wall)
        self._reject_mark = (not self._legal) and (not self._safety_wall)
        self._badge = str(badge)
        self._safety_bounds_rect = next_safety_bounds
        self._safety_sides = next_safety_sides
        self._handles_rect = next_handles
        self._gesture_id = int(gesture_id)
        self._layout_revision = int(layout_revision)
        self._operation = operation or ("resize" if handles else "move")
        self._candidate_fingerprint = fingerprint
        if generation is not None:
            if int(generation) < self._generation:
                return
            self._generation = int(generation)
        else:
            self._generation += 1
        self._present()

    def clear(self, gesture_id: int | None = None) -> None:
        if (
            gesture_id is not None
            and self._gesture_id
            and int(gesture_id) != int(self._gesture_id)
        ):
            return
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
        self._origin_masks = ()
        self._displace_copy = ""
        self._editor_exclusion = None
        self._gesture_id = 0
        self._candidate_fingerprint = ()
        self._frame = None
        self._operation = ""
        self.hide()
        self.update()

    def event(self, event) -> bool:  # noqa: N802
        etype = event.type()
        if etype in (
            QEvent.Show,
            QEvent.Resize,
            QEvent.Expose,
        ) or int(etype) == _SCREEN_CHANGE_INTERNAL:
            self.sync_host_geometry()
            if self._has_content():
                self.update()
        return super().event(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._raise_for_stack()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._has_content():
            self.update()

    def _raise_for_stack(self) -> None:
        if self.parentWidget() is None:
            return
        self.raise_()

    def _install_frame(self, frame: GestureFeedbackFrame) -> None:
        self._frame = frame
        self._gesture_id = int(frame.gesture_id)
        self._generation = int(frame.generation)
        self._layout_revision = int(frame.layout_revision)
        self._operation = str(frame.operation)
        self._candidate_fingerprint = tuple(frame.candidate_fingerprint)
        self._ghosts = tuple(
            (None, QRect(*item.rect), item.role) for item in frame.items
        )
        self._highlights = tuple(QRect(*item.rect) for item in frame.items)
        self._origin_masks = tuple(QRect(*item) for item in frame.origin_masks)
        self._selection_rects = tuple(QRect(*item) for item in frame.selection_rects)
        self._handles_rect = (
            QRect(*frame.handles_rect) if frame.handles_rect is not None else None
        )
        self._marquee = QRect(*frame.marquee) if frame.marquee is not None else None
        self._ring_rect = (
            QRect(*frame.ring_rect) if frame.ring_rect is not None else None
        )
        self._badge = str(frame.badge)
        self._displace_copy = str(frame.displace_copy)
        self._continue_sides = tuple(frame.continue_sides)
        self._hint_copy = str(frame.hint_copy)
        self._legal = bool(frame.legal)
        self._safety_wall = bool(frame.safety_wall)
        self._reject_mark = (not self._legal) and (not self._safety_wall)
        self._safety_bounds_rect = (
            QRect(*frame.safety_bounds) if frame.safety_bounds is not None else None
        )
        self._safety_sides = tuple(frame.safety_sides)
        self._editor_exclusion = (
            QRect(*frame.editor_exclusion) if frame.editor_exclusion is not None else None
        )

    def _snapshot_frame(self) -> GestureFeedbackFrame:
        items = tuple(
            FeedbackItem(
                key=str(index),
                rect=(ghost.x(), ghost.y(), ghost.width(), ghost.height()),
                role=role,
            )
            for index, (_image, ghost, role) in enumerate(self._ghosts)
        )
        return GestureFeedbackFrame(
            gesture_id=self._gesture_id,
            generation=self._generation,
            layout_revision=self._layout_revision,
            operation=self._operation,
            candidate_fingerprint=self._candidate_fingerprint,
            items=items,
            selection_rects=tuple(
                (item.x(), item.y(), item.width(), item.height())
                for item in self._selection_rects
            ),
            handles_rect=(
                (
                    self._handles_rect.x(),
                    self._handles_rect.y(),
                    self._handles_rect.width(),
                    self._handles_rect.height(),
                )
                if self._handles_rect is not None
                else None
            ),
            marquee=(
                (
                    self._marquee.x(),
                    self._marquee.y(),
                    self._marquee.width(),
                    self._marquee.height(),
                )
                if self._marquee is not None
                else None
            ),
            ring_rect=(
                (
                    self._ring_rect.x(),
                    self._ring_rect.y(),
                    self._ring_rect.width(),
                    self._ring_rect.height(),
                )
                if self._ring_rect is not None
                else None
            ),
            origin_masks=tuple(
                (item.x(), item.y(), item.width(), item.height())
                for item in self._origin_masks
            ),
            badge=self._badge,
            displace_copy=self._displace_copy,
            continue_sides=self._continue_sides,
            hint_copy=self._hint_copy,
            safety_wall=self._safety_wall,
            safety_bounds=(
                (
                    self._safety_bounds_rect.x(),
                    self._safety_bounds_rect.y(),
                    self._safety_bounds_rect.width(),
                    self._safety_bounds_rect.height(),
                )
                if self._safety_bounds_rect is not None
                else None
            ),
            safety_sides=self._safety_sides,
            legal=self._legal,
            editor_exclusion=(
                (
                    self._editor_exclusion.x(),
                    self._editor_exclusion.y(),
                    self._editor_exclusion.width(),
                    self._editor_exclusion.height(),
                )
                if self._editor_exclusion is not None
                else None
            ),
        )

    def _present(self, dirty: QRect | None = None) -> None:
        del dirty
        if not self._has_content():
            self.hide()
            return
        self._generation = max(1, self._generation)
        self._frame = self._snapshot_frame()
        self.present_count += 1
        self.sync_host_geometry()
        if not self.isVisible():
            self.show()
            self._raise_for_stack()
        self.update()

    def _resolve_transform(self) -> BoardToViewportTransform:
        board = self._transform_board
        viewport = self._transform_viewport or self.parentWidget()
        if board is None or viewport is None or viewport is board:
            return BoardToViewportTransform(revision=self._transform.revision)
        origin = board.mapFrom(viewport, QPoint(0, 0))
        return BoardToViewportTransform(
            revision=self._transform.revision,
            viewport_in_board=(int(origin.x()), int(origin.y())),
        )

    def _map_rect(self, rect: QRect | None) -> QRect | None:
        if rect is None:
            return None
        return self._paint_transform.to_surface(rect)

    def _paint_continue_hint(self, painter: QPainter) -> None:
        if not self._continue_sides:
            return
        source = self._viewport_rect if self._viewport_rect is not None else self.rect()
        viewport = self._map_rect(source) or self.rect()
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

    def _paint_origin_masks(self, painter: QPainter) -> None:
        if not self._origin_masks:
            return
        painter.setPen(QPen(ORIGIN_MASK_PEN, 1))
        painter.setBrush(ORIGIN_MASK_FILL)
        for rect in self._origin_masks:
            mapped = self._map_rect(rect)
            if mapped is not None:
                painter.drawRect(mapped)

    def _paint_displace_badge(self, painter: QPainter) -> None:
        anchor = None
        for index, (_image, ghost, role) in enumerate(self._ghosts):
            if role == PREVIEW_DISPLACED_WARNING:
                if index < len(self._highlights):
                    anchor = self._highlights[index]
                else:
                    anchor = ghost
                break
        if anchor is None:
            return
        mapped = self._map_rect(anchor)
        if mapped is None:
            return
        font = QFont(painter.font())
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        text = str(self._displace_copy)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 2 * _BADGE_PAD_X
        height = metrics.height() + 2 * _BADGE_PAD_Y
        chip = QRect(mapped.left() + 6, mapped.top() + 6, width, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(ILLEGAL_PEN))
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
        bounds = self._map_rect(self._safety_bounds_rect)
        clip_source = self._viewport_rect if self._viewport_rect is not None else self.rect()
        clip = self._map_rect(clip_source) if self._viewport_rect is not None else self.rect()
        if bounds is None or clip is None:
            return
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
        del event
        self.paint_count += 1
        self._paint_transform = self._resolve_transform()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
            exclusion = self._map_rect(self._editor_exclusion)
            if exclusion is not None and exclusion.isValid():
                region = QRegion(self.rect()).subtracted(QRegion(exclusion))
                painter.setClipRegion(region)
            self._paint_continue_hint(painter)
            self._paint_safety_wall(painter)
            self._paint_origin_masks(painter)
            roles = self.preview_roles()
            for index, highlight in enumerate(self._highlights):
                mapped = self._map_rect(highlight)
                if mapped is None:
                    continue
                role = roles[index] if index < len(roles) else (
                    PREVIEW_MOVER_VALID if (self._legal or self._safety_wall)
                    else PREVIEW_COLLISION_REJECT
                )
                fill, _pen, _style, _stroke = _style_for_role(role)
                if role != PREVIEW_SAFETY_WALL:
                    painter.fillRect(mapped, fill)
            for image, ghost, role in self._ghosts:
                if image is None:
                    continue
                mapped = self._map_rect(ghost)
                if mapped is None:
                    continue
                painter.setOpacity(
                    0.55 if role == PREVIEW_COLLISION_REJECT else GHOST_OPACITY
                )
                painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
                if isinstance(image, QPixmap):
                    painter.drawPixmap(mapped, image)
                else:
                    painter.drawImage(mapped, image)
                painter.setOpacity(1.0)
            for index, highlight in enumerate(self._highlights):
                mapped = self._map_rect(highlight)
                if mapped is None:
                    continue
                role = roles[index] if index < len(roles) else (
                    PREVIEW_MOVER_VALID if (self._legal or self._safety_wall)
                    else PREVIEW_COLLISION_REJECT
                )
                _fill, pen, style, stroke = _style_for_role(role)
                painter.setPen(QPen(pen, stroke, style))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(mapped.adjusted(1, 1, -1, -1))
            if self._badge and self._highlights:
                mover_legal = self._legal or self._safety_wall
                mapped = self._map_rect(self._highlights[0])
                if mapped is not None:
                    self._paint_size_badge(painter, mapped, mover_legal)
            if self._displace_copy:
                self._paint_displace_badge(painter)
            if self._reject_mark and self._highlights:
                mark = self._map_rect(self._highlights[0])
                if mark is not None:
                    cx = mark.right() - 16
                    cy = mark.top() + 16
                    mark_pen = QPen(ILLEGAL_PEN, 2)
                    painter.setPen(mark_pen)
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(cx - 7, cy - 7, 14, 14)
                    painter.drawLine(cx - 4, cy - 4, cx + 4, cy + 4)
                    painter.drawLine(cx + 4, cy - 4, cx - 4, cy + 4)
            if self._ring_rect is not None:
                mapped = self._map_rect(self._ring_rect)
                if mapped is not None:
                    painter.setPen(QPen(LEGAL_PEN, 3))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRoundedRect(mapped.adjusted(-6, -6, 6, 6), 10, 10)
            if self._marquee is not None:
                mapped = self._map_rect(self._marquee)
                if mapped is not None:
                    painter.setPen(QPen(LEGAL_PEN, 1, Qt.DashLine))
                    painter.setBrush(MARQUEE_FILL)
                    painter.drawRect(mapped)
            if not self._highlights:
                painter.setPen(QPen(LEGAL_PEN, 1))
                painter.setBrush(Qt.NoBrush)
                for rect in self._selection_rects:
                    mapped = self._map_rect(rect)
                    if mapped is not None:
                        painter.drawRect(mapped.adjusted(1, 1, -1, -1))
            if self._handles_rect is not None:
                painter.setBrush(HANDLE_FILL)
                painter.setPen(QPen(HANDLE_EDGE, 1))
                mapped = self._map_rect(self._handles_rect)
                if mapped is not None:
                    box = (
                        mapped.x(),
                        mapped.y(),
                        mapped.width(),
                        mapped.height(),
                    )
                    for name in HANDLE_NAMES:
                        hx, hy, hw, hh = handle_visual_rects(box)[name]
                        painter.drawRect(hx, hy, hw, hh)
        finally:
            painter.end()


def _preview_fingerprint(
    ghosts: Sequence[_GhostItem],
    highlights: Sequence[QRect],
    origins: Sequence[QRect],
    legal: bool,
    badge: str,
    displace_copy: str,
    handles: QRect | None,
    safety_wall: bool,
    reject_mark: bool,
    operation: str,
    layout_revision: int,
) -> tuple:
    ghost_key = tuple(
        (
            ghost.x(),
            ghost.y(),
            ghost.width(),
            ghost.height(),
            role,
        )
        for _image, ghost, role in ghosts
    )
    highlight_key = tuple(
        (item.x(), item.y(), item.width(), item.height()) for item in highlights
    )
    origin_key = tuple(
        (item.x(), item.y(), item.width(), item.height()) for item in origins
    )
    handle_key = None
    if handles is not None:
        handle_key = (handles.x(), handles.y(), handles.width(), handles.height())
    return (
        int(layout_revision),
        str(operation),
        ghost_key,
        highlight_key,
        origin_key,
        bool(legal),
        str(badge),
        str(displace_copy),
        handle_key,
        bool(safety_wall),
        bool(reject_mark),
    )
