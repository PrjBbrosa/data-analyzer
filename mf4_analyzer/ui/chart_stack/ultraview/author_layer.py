"""Paint-only live layer for UltraView author-created Board objects.

The persisted object renderer deliberately knows nothing about a widget tree.
This small adapter is the on-screen counterpart: it projects injected author
objects, draft guides, and static ink into a transparent sibling layer.
Card/author selection handles, move/resize targets, and other transient
chrome paint on the viewport-sized ``ViewportFeedbackSurface``.
It never handles mouse or keyboard input.  Interactive editors must instead
be direct children of :class:`FreeGridBoard`, so IME, right-button pan, and
the Page-level viewport router retain their normal Qt delivery path.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget

from .author_geometry import (
    HANDLE_HIT_PX,
    HANDLE_VISUAL_PX,
    board_box_to_pixels,
    board_point_to_pixels,
    text_corner_handle_rects,
)
from .author_render import draw_author_objects, shape_path
from .author_style import DEFAULT_THEME, pen_color
from .free_grid import GridMetrics


BoardPoint = tuple[float, float]
BoardBox = tuple[float, float, float, float]
GuideLine = tuple[BoardPoint, BoardPoint]

_LOD_FULL = "full"
_LOD_COMPACT = "compact"
_LOD_MINIMAL = "minimal"
_KNOWN_LODS = {_LOD_FULL, _LOD_COMPACT, _LOD_MINIMAL}
_SELECTION_COLOR = QColor(53, 99, 232)
_GUIDE_COLOR = QColor(53, 99, 232, 185)


@dataclass(frozen=True)
class AuthorLayerModel:
    """Injectable, UI-only projection state for :class:`AuthorPaintLayer`.

    Geometry is always in canonical Board coordinates.  The owner supplies a
    current (already zoom-scaled) ``GridMetrics`` and signed origin; this
    class carries no selection identity or persistence mutation authority.
    """

    objects: tuple[object, ...] = ()
    metrics: GridMetrics | None = None
    origin_offset: BoardPoint = (0.0, 0.0)
    theme: str = DEFAULT_THEME
    # A real Qt editor paints the active text itself.  Keep its persisted
    # counterpart out of this transparent paint layer until editing ends.
    hidden_text_object_ids: frozenset[str] = frozenset()
    selection_boxes: tuple[BoardBox, ...] = ()
    # Live drag only. ``(object id, geometry)`` where geometry is
    # ``("box", (x, y, w, h))``, ``("points", ((x, y), ...))``, or
    # ``("connector", (sx, sy), (ex, ey))``. The persisted objects stay put.
    geometry_overrides: tuple[tuple[str, tuple], ...] = ()
    # Selected text boxes, in Board units. Corner handles are drawn from these.
    text_handle_boxes: tuple[BoardBox, ...] = ()
    guide_lines: tuple[GuideLine, ...] = ()
    draft_points: tuple[BoardPoint, ...] = ()
    draft_shape: str = ""
    draft_box: BoardBox | None = None
    lod: str = _LOD_FULL


class AuthorPaintLayer(QWidget):
    """Transparent, non-interactive renderer for objects and author chrome.

    ``set_model`` accepts the typed model above and is intentionally cheap:
    callers may replace it on every Board update or zoom transaction.  The
    layer does not create persistent widgets for object content and does not
    perform hit testing; direct editor widgets are provided by
    :mod:`author_widgets`.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewAuthorPaintLayer")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.NoFocus)
        self._model = AuthorLayerModel()
        self._zoom = 1.0
        self._requested_lod = _LOD_FULL
        self._live_stroke_points: tuple[BoardPoint, ...] = ()
        self._live_stroke_tool = "pen"
        self._live_stroke_palette = "ink"
        self._live_stroke_width = 2
        self._live_stroke_role = "ink"

    def model(self) -> AuthorLayerModel:
        """Return the most recently injected immutable projection model."""
        return self._model

    def set_model(self, model: AuthorLayerModel) -> None:
        """Install one paint model without taking ownership of its objects."""
        if not isinstance(model, AuthorLayerModel):
            raise TypeError("AuthorPaintLayer requires an AuthorLayerModel")
        self._requested_lod = _normalize_lod(model.lod)
        self._model = AuthorLayerModel(
            objects=tuple(model.objects),
            metrics=model.metrics,
            origin_offset=_point_or_origin(model.origin_offset),
            theme=str(model.theme or DEFAULT_THEME),
            hidden_text_object_ids=frozenset(
                str(object_id)
                for object_id in model.hidden_text_object_ids
                if str(object_id)
            ),
            selection_boxes=tuple(model.selection_boxes),
            geometry_overrides=tuple(model.geometry_overrides),
            text_handle_boxes=tuple(model.text_handle_boxes),
            guide_lines=tuple(model.guide_lines),
            draft_points=tuple(model.draft_points),
            draft_shape=str(model.draft_shape or ""),
            draft_box=model.draft_box,
            lod=_lod_for_zoom(self._zoom, requested=self._requested_lod),
        )
        self.update()

    def set_view_geometry(
        self,
        metrics: GridMetrics | None,
        *,
        origin_offset: BoardPoint = (0.0, 0.0),
        zoom: float | None = None,
    ) -> None:
        """Refresh mapping after a zoom, extent rebase, or Board resize."""
        if zoom is not None:
            self._zoom = _positive_zoom(zoom)
        model = self._model
        self._model = AuthorLayerModel(
            objects=model.objects,
            metrics=metrics,
            origin_offset=_point_or_origin(origin_offset),
            theme=model.theme,
            hidden_text_object_ids=model.hidden_text_object_ids,
            selection_boxes=model.selection_boxes,
            geometry_overrides=model.geometry_overrides,
            text_handle_boxes=model.text_handle_boxes,
            guide_lines=model.guide_lines,
            draft_points=model.draft_points,
            draft_shape=model.draft_shape,
            draft_box=model.draft_box,
            lod=_lod_for_zoom(self._zoom, requested=self._requested_lod),
        )
        self.update()

    def set_zoom(self, zoom: float) -> None:
        """Update LOD policy; the owning Board still supplies scaled metrics."""
        self._zoom = _positive_zoom(zoom)
        model = self._model
        self._model = AuthorLayerModel(
            objects=model.objects,
            metrics=model.metrics,
            origin_offset=model.origin_offset,
            theme=model.theme,
            hidden_text_object_ids=model.hidden_text_object_ids,
            selection_boxes=model.selection_boxes,
            geometry_overrides=model.geometry_overrides,
            text_handle_boxes=model.text_handle_boxes,
            guide_lines=model.guide_lines,
            draft_points=model.draft_points,
            draft_shape=model.draft_shape,
            draft_box=model.draft_box,
            lod=_lod_for_zoom(self._zoom, requested=self._requested_lod),
        )
        self.update()

    def set_selection_boxes(self, boxes: Iterable[BoardBox]) -> None:
        model = self._model
        self._model = _replace_model(model, selection_boxes=tuple(boxes))
        self.update()

    def set_geometry_overrides(
        self, overrides: Iterable[tuple[str, tuple]]
    ) -> None:
        """Install the live id → preview geometry map. Empty clears it."""
        model = self._model
        cleaned = tuple(
            (str(object_id), geometry)
            for object_id, geometry in overrides
            if str(object_id) and isinstance(geometry, tuple)
        )
        self._model = _replace_model(model, geometry_overrides=cleaned)
        self.update()

    def set_guides(
        self,
        lines: Iterable[GuideLine] = (),
        *,
        draft_points: Iterable[BoardPoint] = (),
    ) -> None:
        """Set non-persistent snapping/drawing affordances for the next paint."""
        model = self._model
        self._model = _replace_model(
            model,
            guide_lines=tuple(lines),
            draft_points=tuple(draft_points),
        )
        self.update()

    def clear_guides(self) -> None:
        self.set_guides()

    def set_draft_shape(self, shape: str | None, box: BoardBox | None) -> None:
        """Paint an in-progress closed shape. Not a widget and not persisted."""
        model = self._model
        self._model = _replace_model(
            model,
            draft_shape=str(shape or ""),
            draft_box=box,
        )
        self.update()

    def live_stroke_points(self) -> tuple[BoardPoint, ...]:
        return self._live_stroke_points

    def set_live_stroke(
        self,
        points: Iterable[BoardPoint] = (),
        *,
        tool: str = "pen",
        palette: str = "ink",
        width_px: int = 2,
        role: str = "ink",
    ) -> None:
        self._live_stroke_points = tuple(points)
        self._live_stroke_tool = str(tool or "pen")
        self._live_stroke_palette = str(palette or "ink")
        self._live_stroke_role = "overlay" if str(role) == "overlay" else "ink"
        try:
            self._live_stroke_width = max(1, int(width_px))
        except (TypeError, ValueError):
            self._live_stroke_width = 2
        self.update()

    def append_live_stroke_point(
        self,
        point: BoardPoint,
        *,
        tool: str = "pen",
        palette: str = "ink",
        width_px: int = 2,
        role: str = "ink",
    ) -> None:
        last = self._live_stroke_points[-1] if self._live_stroke_points else None
        self._live_stroke_tool = str(tool or "pen")
        self._live_stroke_palette = str(palette or "ink")
        self._live_stroke_role = "overlay" if str(role) == "overlay" else "ink"
        try:
            self._live_stroke_width = max(1, int(width_px))
        except (TypeError, ValueError):
            self._live_stroke_width = 2
        self._live_stroke_points = self._live_stroke_points + (point,)
        dirty = self._stroke_segment_dirty_rect(last, point, self._live_stroke_width)
        if dirty is None:
            self.update()
            return
        self.update(dirty)

    def clear_live_stroke(self) -> None:
        if not self._live_stroke_points:
            self._live_stroke_role = "ink"
            return
        self._live_stroke_points = ()
        self._live_stroke_role = "ink"
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        model = self._model
        metrics = model.metrics
        if metrics is None:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            draw_author_objects(
                painter,
                _objects_with_overrides(model.objects, model.geometry_overrides),
                metrics,
                origin_offset=model.origin_offset,
                theme=model.theme,
                hidden_text_object_ids=model.hidden_text_object_ids,
            )
            if model.lod != _LOD_MINIMAL:
                self._draw_guides(painter, model, metrics)
                self._draw_draft_shape(painter, model, metrics)
                self._draw_live_stroke(painter, model, metrics)
            if model.lod != _LOD_MINIMAL:
                self._draw_selection(painter, model, metrics)
        finally:
            painter.end()

    def _draw_guides(
        self,
        painter: QPainter,
        model: AuthorLayerModel,
        metrics: GridMetrics,
    ) -> None:
        pen = QPen(_GUIDE_COLOR)
        pen.setWidthF(1.0)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for start, end in model.guide_lines:
            first = board_point_to_pixels(start, metrics, origin_offset=model.origin_offset)
            second = board_point_to_pixels(end, metrics, origin_offset=model.origin_offset)
            if first is not None and second is not None:
                painter.drawLine(QPointF(*first), QPointF(*second))
        if len(model.draft_points) < 2:
            return
        points = [
            board_point_to_pixels(point, metrics, origin_offset=model.origin_offset)
            for point in model.draft_points
        ]
        visible = [QPointF(*point) for point in points if point is not None]
        if len(visible) < 2:
            return
        draft_pen = QPen(_GUIDE_COLOR)
        draft_pen.setWidthF(2.0)
        draft_pen.setCapStyle(Qt.RoundCap)
        draft_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(draft_pen)
        path = QPainterPath(visible[0])
        for point in visible[1:]:
            path.lineTo(point)
        painter.drawPath(path)

    def _draw_draft_shape(
        self,
        painter: QPainter,
        model: AuthorLayerModel,
        metrics: GridMetrics,
    ) -> None:
        if not model.draft_shape or model.draft_box is None:
            return
        pixel = board_box_to_pixels(model.draft_box, metrics, origin_offset=model.origin_offset)
        if pixel is None:
            return
        rect = QRectF(*pixel)
        if rect.width() <= 0.0 or rect.height() <= 0.0:
            return
        path = shape_path(model.draft_shape, rect)
        if path.isEmpty():
            return
        pen = QPen(_GUIDE_COLOR)
        pen.setWidthF(1.5)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def _draw_live_stroke(
        self,
        painter: QPainter,
        model: AuthorLayerModel,
        metrics: GridMetrics,
    ) -> None:
        if len(self._live_stroke_points) < 2:
            return
        points = []
        for point in self._live_stroke_points:
            mapped = board_point_to_pixels(point, metrics, origin_offset=model.origin_offset)
            if mapped is not None:
                points.append(QPointF(*mapped))
        if len(points) < 2:
            return
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        if self._live_stroke_role == "overlay":
            pen = QPen(_GUIDE_COLOR)
            pen.setWidthF(2.0)
            pen.setStyle(Qt.DashLine)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            return
        color = QColor(*pen_color(self._live_stroke_palette, tool=self._live_stroke_tool, theme=model.theme))
        pen = QPen(color)
        pen.setWidthF(max(1.0, float(self._live_stroke_width)))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def _stroke_segment_dirty_rect(
        self, start: BoardPoint | None, end: BoardPoint, width_px: int
    ) -> QRect | None:
        metrics = self._model.metrics
        if metrics is None:
            return None
        origin = self._model.origin_offset
        mapped_end = board_point_to_pixels(end, metrics, origin_offset=origin)
        mapped_start = (
            board_point_to_pixels(start, metrics, origin_offset=origin)
            if start is not None
            else mapped_end
        )
        if mapped_end is None:
            return None
        if mapped_start is None:
            mapped_start = mapped_end
        pad = max(2.0, float(width_px) / 2.0 + 2.0)
        left = min(mapped_start[0], mapped_end[0]) - pad
        top = min(mapped_start[1], mapped_end[1]) - pad
        right = max(mapped_start[0], mapped_end[0]) + pad
        bottom = max(mapped_start[1], mapped_end[1]) + pad
        return QRect(
            int(math.floor(left)),
            int(math.floor(top)),
            max(1, int(math.ceil(right) - math.floor(left))),
            max(1, int(math.ceil(bottom) - math.floor(top))),
        )

    def _draw_selection(
        self,
        painter: QPainter,
        model: AuthorLayerModel,
        metrics: GridMetrics,
    ) -> None:
        pen = QPen(_SELECTION_COLOR)
        pen.setWidthF(1.5)
        if model.lod == _LOD_COMPACT:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        for box in model.selection_boxes:
            pixel = board_box_to_pixels(box, metrics, origin_offset=model.origin_offset)
            if pixel is None:
                continue
            rect = QRectF(*pixel)
            if rect.width() > 0.0 and rect.height() > 0.0:
                painter.drawRect(rect)
        if model.text_handle_boxes:
            painter.setBrush(_SELECTION_COLOR)
            for box in model.text_handle_boxes:
                pixel = board_box_to_pixels(box, metrics, origin_offset=model.origin_offset)
                if pixel is None:
                    continue
                rects = text_corner_handle_rects(
                    (
                        int(round(pixel[0])),
                        int(round(pixel[1])),
                        max(1, int(round(pixel[2]))),
                        max(1, int(round(pixel[3]))),
                    ),
                    hit=HANDLE_HIT_PX,
                    size=HANDLE_VISUAL_PX,
                )
                for name in ("nw", "ne", "sw", "se"):
                    painter.drawRect(QRectF(*rects[name]))


def _objects_with_overrides(objects, overrides) -> tuple[object, ...]:
    """Return paint copies whose geometry follows the live drag preview."""
    if not overrides:
        return tuple(objects)
    by_id = {str(object_id): geometry for object_id, geometry in overrides}
    painted = []
    for item in objects:
        object_id = str(getattr(item, "object_id", "") or "")
        geometry = by_id.get(object_id)
        painted.append(item if geometry is None else _apply_geometry_override(item, geometry))
    return tuple(painted)


def _apply_geometry_override(item, geometry):
    """Copy ``item`` with one preview geometry. Malformed input keeps ``item``."""
    from dataclasses import replace

    from mf4_analyzer.ui.ultraview_state import BoardBox, BoardPoint

    if not isinstance(geometry, tuple) or not geometry:
        return item
    kind = geometry[0]
    if kind == "box" and getattr(item, "box", None) is not None:
        raw = _finite_tuple(geometry[1] if len(geometry) > 1 else (), 4)
        if raw is None:
            return item
        return replace(item, box=BoardBox(*raw))
    if kind == "points" and hasattr(item, "points"):
        raw_points = geometry[1] if len(geometry) > 1 else ()
        points = []
        for point in raw_points:
            parsed = _finite_tuple(point, 2)
            if parsed is not None:
                points.append(BoardPoint(*parsed))
        if len(points) < 2:
            return item
        return replace(item, points=tuple(points))
    if kind == "connector" and hasattr(item, "start") and hasattr(item, "end"):
        start = _finite_tuple(geometry[1] if len(geometry) > 1 else (), 2)
        end = _finite_tuple(geometry[2] if len(geometry) > 2 else (), 2)
        if start is None or end is None:
            return item
        return replace(
            item,
            start=type(item.start)(BoardPoint(*start), item.start.target),
            end=type(item.end)(BoardPoint(*end), item.end.target),
        )
    return item


def _finite_tuple(value, count: int) -> tuple[float, ...] | None:
    if not isinstance(value, tuple) or len(value) != count:
        return None
    numbers = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        numbers.append(number)
    return tuple(numbers)


def _replace_model(model: AuthorLayerModel, **changes) -> AuthorLayerModel:
    values = {
        "objects": model.objects,
        "metrics": model.metrics,
        "origin_offset": model.origin_offset,
        "theme": model.theme,
        "hidden_text_object_ids": model.hidden_text_object_ids,
        "selection_boxes": model.selection_boxes,
        "geometry_overrides": model.geometry_overrides,
        "text_handle_boxes": model.text_handle_boxes,
        "guide_lines": model.guide_lines,
        "draft_points": model.draft_points,
        "draft_shape": model.draft_shape,
        "draft_box": model.draft_box,
        "lod": model.lod,
    }
    values.update(changes)
    return AuthorLayerModel(**values)


def _point_or_origin(value: object) -> BoardPoint:
    try:
        x, y = value  # type: ignore[misc]
        return float(x), float(y)
    except (TypeError, ValueError):
        return 0.0, 0.0


def _positive_zoom(value: object) -> float:
    try:
        zoom = float(value)
    except (TypeError, ValueError):
        return 1.0
    return zoom if zoom > 0.0 else 1.0


def _normalize_lod(value: object) -> str:
    return value if isinstance(value, str) and value in _KNOWN_LODS else _LOD_FULL


def _lod_for_zoom(zoom: float, *, requested: object) -> str:
    # The owner may force a lower detail tier, but no zoom can force a higher
    # tier than the screen-space budget permits.
    requested_lod = _normalize_lod(requested)
    automatic = _LOD_FULL if zoom >= 0.55 else _LOD_COMPACT if zoom >= 0.24 else _LOD_MINIMAL
    return max((requested_lod, automatic), key=(_LOD_FULL, _LOD_COMPACT, _LOD_MINIMAL).index)


__all__ = [
    "AuthorLayerModel",
    "AuthorPaintLayer",
    "BoardBox",
    "BoardPoint",
    "GuideLine",
]
