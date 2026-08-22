"""Canvas content host with non-layout-participating sibling overlays.

``set_canvas_widget`` fills the complete host. Registered overlays are
direct children of this host and never enter a layout, so opening a library
or a popover cannot reflow or resize the board viewport. The page remains
responsible for deciding which panel is active and where it should sit.
"""
from __future__ import annotations

from collections.abc import Sequence

from PyQt5.QtCore import QEvent, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt5.QtWidgets import QFrame, QWidget

from .chrome_common import (
    UV_BRAND,
    UV_BRAND_DEEP,
    UV_CANVAS,
    UV_CANVAS_DEEP,
    UV_DOT,
    UV_GLOW_MIST,
    UV_GLOW_SELECTED,
    UV_GLOW_TEAL,
    UV_GRID,
    UV_SELECTED,
    _set_flag,
)


_DOT_PITCH_PX = 22
_DPR_CHANGE_EVENT_TYPES = frozenset(
    value
    for value in (
        getattr(QEvent, "ScreenChangeInternal", None),
        getattr(QEvent, "DevicePixelRatioChange", None),
    )
    if value is not None
)

class CanvasHost(QFrame):
    """A canvas content host with non-layout-participating sibling overlays.

    ``set_canvas_widget`` fills the complete host.  Registered overlays are
    direct children of this host and never enter a layout, so opening a library
    or a popover cannot reflow or resize the board viewport.  The page remains
    responsible for deciding which panel is active and where it should sit.
    """

    overlay_opened = pyqtSignal(str)
    overlay_closed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCanvasHost")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("surface", "canvas")
        self._canvas: QWidget | None = None
        self._overlays: dict[str, QWidget] = {}
        self._overlay_triggers: dict[str, QWidget | None] = {}
        self._overlay_close_on_canvas: dict[str, bool] = {}
        self._active_overlay: str | None = None
        self._dot_tile: QPixmap | None = None
        self._dot_tile_key: tuple[str, int, float] | None = None
        self._background: QPixmap | None = None
        self._background_size = QSize()
        self._background_dpr = 0.0

    def canvas_widget(self) -> QWidget | None:
        return self._canvas

    def set_canvas_widget(self, widget: QWidget) -> None:
        """Install the one board content widget below every overlay."""
        if widget is self._canvas:
            return
        if self._canvas is not None:
            self._canvas.removeEventFilter(self)
            self._canvas.hide()
        widget.setParent(self)
        widget.installEventFilter(self)
        widget.show()
        self._canvas = widget
        widget.setGeometry(self.contentsRect())
        widget.lower()

    def _canvas_dpr(self) -> float:
        return max(1.0, float(self.devicePixelRatioF()))

    def _invalidate_canvas_background(self) -> None:
        self._background = None
        self._dot_tile = None
        self.update()

    def event(self, event) -> bool:  # noqa: N802
        if event.type() in _DPR_CHANGE_EVENT_TYPES:
            self._invalidate_canvas_background()
        return super().event(event)

    def register_overlay(
        self,
        overlay_id: str,
        widget: QWidget,
        *,
        trigger: QWidget | None = None,
        close_on_canvas_click: bool = True,
    ) -> None:
        """Register a stable overlay widget without taking ownership of state."""
        key = str(overlay_id)
        if not key:
            raise ValueError("overlay_id must not be empty")
        existing = self._overlays.get(key)
        if existing is not None and existing is not widget:
            raise ValueError(f"overlay already registered: {key}")
        widget.setParent(self)
        widget.setProperty("floatingOverlay", "true")
        widget.setProperty("overlayId", key)
        widget.hide()
        self._overlays[key] = widget
        self._overlay_triggers[key] = trigger
        self._overlay_close_on_canvas[key] = bool(close_on_canvas_click)

    def overlay_closes_on_canvas(self, overlay_id: str) -> bool:
        return bool(self._overlay_close_on_canvas.get(str(overlay_id), True))

    def set_overlay_close_on_canvas(self, overlay_id: str, close: bool) -> None:
        key = str(overlay_id)
        if key not in self._overlays:
            raise KeyError(key)
        self._overlay_close_on_canvas[key] = bool(close)

    def overlay(self, overlay_id: str) -> QWidget | None:
        return self._overlays.get(str(overlay_id))

    def active_overlay(self) -> str | None:
        return self._active_overlay

    def open_overlay(
        self,
        overlay_id: str,
        rect: QRect | None = None,
        *,
        focus: bool = False,
    ) -> bool:
        """Show one registered overlay, closing any currently active sibling."""
        key = str(overlay_id)
        widget = self._overlays.get(key)
        if widget is None:
            return False
        if self._active_overlay is not None and self._active_overlay != key:
            self.close_active_overlay(restore_focus=False)
        if rect is not None:
            self.set_overlay_geometry(key, rect)
        elif widget.width() <= 0 or widget.height() <= 0:
            hint = widget.sizeHint()
            self.set_overlay_geometry(key, QRect(12, 12, hint.width(), hint.height()))
        self._active_overlay = key
        widget.show()
        _set_flag(widget, "active", True)
        self.reassert_stacking()
        if focus:
            self._focus_first_control(widget)
        self.overlay_opened.emit(key)
        return True

    def close_overlay(self, overlay_id: str, *, restore_focus: bool = True) -> bool:
        key = str(overlay_id)
        widget = self._overlays.get(key)
        if widget is None or self._active_overlay != key:
            return False
        widget.hide()
        _set_flag(widget, "active", False)
        self._active_overlay = None
        self.overlay_closed.emit(key)
        if restore_focus:
            trigger = self._overlay_triggers.get(key)
            if trigger is not None and trigger.isVisible() and trigger.isEnabled():
                trigger.setFocus(Qt.OtherFocusReason)
        return True

    def close_active_overlay(self, *, restore_focus: bool = True) -> bool:
        key = self._active_overlay
        return self.close_overlay(key, restore_focus=restore_focus) if key is not None else False

    def set_overlay_geometry(self, overlay_id: str, rect: QRect) -> QRect:
        """Clamp an externally calculated overlay rectangle into this host."""
        widget = self._overlays.get(str(overlay_id))
        if widget is None:
            raise KeyError(str(overlay_id))
        bounds = self.contentsRect()
        width = max(0, min(int(rect.width()), bounds.width()))
        height = max(0, min(int(rect.height()), bounds.height()))
        max_x = bounds.x() + max(0, bounds.width() - width)
        max_y = bounds.y() + max(0, bounds.height() - height)
        x = min(max(int(rect.x()), bounds.x()), max_x)
        y = min(max(int(rect.y()), bounds.y()), max_y)
        clamped = QRect(x, y, width, height)
        widget.setGeometry(clamped)
        return clamped

    def reassert_stacking(self, extra: Sequence[QWidget] = ()) -> None:
        """Restore the host z-order. The active overlay always finishes on top.

        Board canvas stays at the bottom. Persistent chrome (rail, islands,
        selection toolbar) sits above it. The one transient overlay is last
        so cards, ghost paint, and selection chrome cannot cover a flyout.
        """
        if self._canvas is not None:
            self._canvas.lower()
        for widget in extra:
            if widget is not None and widget.isVisible():
                widget.raise_()
        key = self._active_overlay
        if key is None:
            return
        overlay = self._overlays.get(key)
        if overlay is not None and overlay.isVisible():
            overlay.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._canvas is not None:
            self._canvas.setGeometry(self.contentsRect())
        for key, overlay in self._overlays.items():
            if overlay.isVisible():
                self.set_overlay_geometry(key, overlay.geometry())
        self.reassert_stacking()

    def paintEvent(self, event) -> None:  # noqa: N802
        """Paint the cached UltraView canvas beneath all Qt children."""
        painter = QPainter(self)
        size = self.size()
        dpr = self._canvas_dpr()
        if (
            self._background is None
            or self._background_size != size
            or self._background_dpr != dpr
        ):
            self._background = self._build_canvas_background(size)
            self._background_size = QSize(size)
            self._background_dpr = dpr
        painter.drawPixmap(self.rect(), self._background)

    def _build_canvas_background(self, size: QSize) -> QPixmap:
        """Create a static multi-layer backdrop once per resize, never per pan."""
        dpr = self._canvas_dpr()
        width, height = max(1, size.width()), max(1, size.height())
        background = QPixmap(
            max(1, int(round(width * dpr))),
            max(1, int(round(height * dpr))),
        )
        background.setDevicePixelRatio(dpr)
        background.fill(UV_CANVAS)
        painter = QPainter(background)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(0.0, 0.0, float(width), float(height))

        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        base.setColorAt(0.0, UV_CANVAS)
        base.setColorAt(1.0, UV_CANVAS_DEEP)
        painter.fillRect(rect, base)
        for center, radius, color in (
            (QPointF(width * 0.16, height * 0.04), max(width, height) * 0.46, UV_GLOW_TEAL),
            (QPointF(width * 0.88, height * 0.09), max(width, height) * 0.42, UV_GLOW_SELECTED),
            (QPointF(width * 0.64, height * 1.04), max(width, height) * 0.48, UV_GLOW_MIST),
        ):
            glow = QRadialGradient(center, radius)
            glow.setColorAt(0.0, color)
            edge = QColor(color)
            edge.setAlpha(0)
            glow.setColorAt(1.0, edge)
            painter.fillRect(rect, glow)

        key = (UV_CANVAS.name(), UV_DOT.rgba(), dpr)
        if self._dot_tile is None or self._dot_tile_key != key:
            pitch = max(1, int(round(_DOT_PITCH_PX * dpr)))
            tile = QPixmap(pitch, pitch)
            tile.setDevicePixelRatio(dpr)
            tile.fill(Qt.transparent)
            dots = QPainter(tile)
            dots.setPen(Qt.NoPen)
            dots.setBrush(UV_DOT)
            dots.drawRect(10, 10, 2, 2)
            dots.end()
            self._dot_tile = tile
            self._dot_tile_key = key
        painter.drawTiledPixmap(QRectF(rect), self._dot_tile)

        grid_pen = QPen(UV_GRID)
        grid_pen.setWidthF(1.0)
        painter.setPen(grid_pen)
        coarse_pitch = _DOT_PITCH_PX * 5
        for x in range(0, width + 1, coarse_pitch):
            painter.drawLine(x, 0, x, height)
        for y in range(0, height + 1, coarse_pitch):
            painter.drawLine(0, y, width, y)

        horizon = QPainterPath(QPointF(0.0, height * 0.15))
        horizon.cubicTo(
            width * 0.18, height * 0.10, width * 0.25, height * 0.20, width * 0.42, height * 0.14
        )
        horizon.cubicTo(
            width * 0.58, height * 0.08, width * 0.73, height * 0.20, float(width), height * 0.12
        )
        horizon_gradient = QLinearGradient(0.0, 0.0, float(width), 0.0)
        for stop, color in ((0.0, UV_BRAND), (0.55, UV_SELECTED), (1.0, UV_BRAND_DEEP)):
            faint = QColor(color)
            faint.setAlpha(36)
            horizon_gradient.setColorAt(stop, faint)
        horizon_pen = QPen(horizon_gradient, 1.0, Qt.DashLine)
        horizon_pen.setDashPattern((2.0, 6.0))
        painter.setPen(horizon_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(horizon)
        painter.end()
        return background

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape and self.close_active_overlay():
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.close_from_canvas_click()
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            watched is self._canvas
            and event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
        ):
            self.close_from_canvas_click()
        return super().eventFilter(watched, event)

    def close_from_canvas_click(self) -> None:
        key = self._active_overlay
        if key is not None and self._overlay_close_on_canvas.get(key, True):
            # Mouse close leaves focus on the canvas, not the trigger. Esc
            # still uses restore_focus=True so keyboard users return to the
            # button that opened the panel.
            self.close_active_overlay(restore_focus=False)

    _close_from_canvas_click = close_from_canvas_click

    @staticmethod
    def _focus_first_control(widget: QWidget) -> None:
        for child in widget.findChildren(QWidget):
            if child.focusPolicy() != Qt.NoFocus and child.isVisible() and child.isEnabled():
                child.setFocus(Qt.OtherFocusReason)
                return
        if widget.focusPolicy() != Qt.NoFocus:
            widget.setFocus(Qt.OtherFocusReason)
