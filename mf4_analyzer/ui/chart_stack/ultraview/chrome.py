"""Lightweight floating presentation widgets for the UltraView canvas.

The widgets in this module deliberately project only local visual state.  They
never receive an ``UltraViewBoardState`` and never mutate the workspace: the
page owns the active panel and translates these typed Qt signals into its
existing coordinator intents.

The module also intentionally does not position the islands relative to cards
or the minimap.  ``floating_layout.py`` / ``UltraViewPage`` own that geometry;
``CanvasHost`` merely provides a stable sibling-overlay host.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import qtawesome as qta
from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from mf4_analyzer.ui_kit.icons import Icons, icon_device_pixel_ratio
from mf4_analyzer.ui_kit.menus import add_rounded_submenu, apply_rounded_menu_chrome
from mf4_analyzer.ui_kit.ultraview_style import titanium_color
from mf4_analyzer.ui.ultraview_state import LAYOUT_SLOTS, ULTRAVIEW_REF_MIME, parse_ref_payload

from .author_style import DEFAULT_THEME, STICKY_PALETTE_TOKENS, sticky_colors
from .floating_layout import (
    BOARD_ISLAND_MAX_WIDTH,
    DEFAULT_NAVIGATION_ISLAND_SIZE,
    GLOBAL_ISLAND_WIDTH,
    ISLAND_HEIGHT,
    RAIL_CONTENT_HEIGHT,
    RAIL_WIDTH,
    STATUS_ISLAND_WIDTH,
)


PANEL_LIBRARY = "library"
PANEL_LAYOUT = "layout"
PANEL_FILTER = "filter"
PANEL_UNPLACED = "unplaced"
PANEL_BOARDS = "boards"
AUTHOR_TOOL_SELECT = "select"
AUTHOR_TOOL_STICKY = "sticky"
AUTHOR_TOOL_TEXT = "text"
AUTHOR_TOOL_SHAPES = "shapes"
AUTHOR_TOOL_DRAW = "draw"
AUTHOR_TOOLS = (
    AUTHOR_TOOL_SELECT,
    AUTHOR_TOOL_STICKY,
    AUTHOR_TOOL_TEXT,
    AUTHOR_TOOL_SHAPES,
    AUTHOR_TOOL_DRAW,
)
RAIL_BUTTON_SIZE = 36
RAIL_ICON_SIZE = 20
BOARD_POPOVER_WIDTH = 260
BOARD_ROW_HEIGHT = 36
_BOARD_CURRENT_ROLE = Qt.UserRole + 1
_BOARD_ACTION_WIDTH = 24
_BOARD_POPOVER_MARGIN = 8
_BOARD_POPOVER_GAP = 6
_BOARD_CREATE_HEIGHT = 28
_BOARD_LIST_BOTTOM_PAD = 6


def _author_tool_icon(tool: str, *, active: bool) -> QIcon:
    """Return one compact, stable line icon for an authoring rail tool."""
    names = {
        AUTHOR_TOOL_SELECT: "fa5s.mouse-pointer",
        AUTHOR_TOOL_STICKY: "fa5s.sticky-note",
        AUTHOR_TOOL_TEXT: "fa5s.font",
        AUTHOR_TOOL_SHAPES: "fa5s.shapes",
        AUTHOR_TOOL_DRAW: "fa5s.pen",
    }
    return qta.icon(names[str(tool)], color=UV_PRESENTATION_ICON if active else UV_MUTED)


class _AuthorToolButton(QToolButton):
    """A rail button that distinguishes a click from the pin gesture."""

    pin_requested = pyqtSignal(str)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.pin_requested.emit(str(self.property("authorTool") or ""))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


def board_popover_height(rows: int) -> int:
    """Exact popover height for ``rows`` Board lines plus the create row."""
    count = max(1, int(rows))
    list_h = count * BOARD_ROW_HEIGHT + max(0, count - 1) + _BOARD_LIST_BOTTOM_PAD
    return _BOARD_POPOVER_MARGIN * 2 + list_h + _BOARD_POPOVER_GAP + _BOARD_CREATE_HEIGHT

# UltraView-local Titanium Amber palette.  Keep this role mapping isolated
# from CONTROL_COLORS: the rest of the Analyzer must not inherit this canvas.
UV_CANVAS = QColor(titanium_color("canvas"))
UV_CANVAS_DEEP = QColor(titanium_color("canvas_deep"))
UV_DOT = QColor(44, 82, 93, 43)
UV_GRID = QColor(38, 74, 86, 26)
UV_GLOW_TEAL = QColor(31, 104, 128, 41)
UV_GLOW_AMBER = QColor(238, 151, 58, 33)
UV_GLOW_COPPER = QColor(197, 76, 64, 20)
UV_PAPER = QColor(titanium_color("surface_solid"))
UV_BRAND = QColor(titanium_color("brand"))
UV_BRAND_DEEP = QColor(titanium_color("brand_deep"))
UV_AMBER = QColor(titanium_color("amber"))
UV_DANGER = QColor(titanium_color("danger"))
UV_WASH = QColor(titanium_color("surface_tint"))
UV_LINE = QColor(50, 86, 97, 59)
UV_INK = QColor(titanium_color("ink"))
UV_MUTED = QColor(titanium_color("muted"))
UV_PRESENTATION_ICON = QColor("#FFFFFF")
# Compatibility seam for the card module.  Keep only this import alias while
# widgets moves to the role palette; all paint decisions above use ``UV_*``.
ULTRAVIEW_MUTED = UV_MUTED
_LAYOUT_THUMB_SIZE = QSize(88, 54)
_LAYOUT_THUMB_CELL = QSize(168, 118)
_HERO_LAYOUT_IDS = frozenset({"hero_left_4", "hero_top_4"})
_DOT_PITCH_PX = 22
_DPR_CHANGE_EVENT_TYPES = frozenset(
    value
    for value in (
        getattr(QEvent, "ScreenChangeInternal", None),
        getattr(QEvent, "DevicePixelRatioChange", None),
    )
    if value is not None
)
_LAYOUT_THUMB_SCHEMES: dict[str, tuple[tuple[float, float, float, float], ...]] = {
    "split_horizontal": ((0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 0.5, 1.0)),
    "split_vertical": ((0.0, 0.0, 1.0, 0.5), (0.0, 0.5, 1.0, 0.5)),
    "grid_2x2": (
        (0.0, 0.0, 0.5, 0.5),
        (0.5, 0.0, 0.5, 0.5),
        (0.0, 0.5, 0.5, 0.5),
        (0.5, 0.5, 0.5, 0.5),
    ),
    "hero_left_4": (
        (0.0, 0.0, 0.62, 1.0),
        (0.62, 0.0, 0.38, 0.33),
        (0.62, 0.33, 0.38, 0.33),
        (0.62, 0.66, 0.38, 0.34),
    ),
    "hero_top_4": (
        (0.0, 0.0, 1.0, 0.58),
        (0.0, 0.58, 0.33, 0.42),
        (0.33, 0.58, 0.34, 0.42),
        (0.67, 0.58, 0.33, 0.42),
    ),
    "grid_3x2": tuple(
        (col / 3.0, row / 2.0, 1.0 / 3.0, 0.5) for row in range(2) for col in range(3)
    ),
    "grid_3x3": tuple(
        (col / 3.0, row / 3.0, 1.0 / 3.0, 1.0 / 3.0) for row in range(3) for col in range(3)
    ),
    "grid_4x3": tuple(
        (col / 4.0, row / 3.0, 0.25, 1.0 / 3.0) for row in range(3) for col in range(4)
    ),
    "free_grid": tuple(
        (col / 4.0, row / 3.0, 0.25, 1.0 / 3.0) for row in range(3) for col in range(4)
    ),
}


def _ultraview_icon_color(*, active: bool) -> QColor:
    """Rest icons stay muted; mode/panel-open icons pick up titanium blue."""
    return QColor(UV_BRAND if active else UV_MUTED)


def layout_thumbnail_icon(layout_id: str) -> QIcon:
    """Paint a paper-card preview: inset canvas, gutters, weighted hero slot."""
    logical_w, logical_h = _LAYOUT_THUMB_SIZE.width(), _LAYOUT_THUMB_SIZE.height()
    dpr = icon_device_pixel_ratio()
    pixmap = QPixmap(max(1, int(round(logical_w * dpr))), max(1, int(round(logical_h * dpr))))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(UV_LINE)
    painter.setBrush(UV_PAPER)
    painter.drawRoundedRect(QRectF(0.5, 0.5, logical_w - 1.0, logical_h - 1.0), 7, 7)
    inset = QRectF(5.0, 5.0, logical_w - 10.0, logical_h - 10.0)
    painter.setPen(Qt.NoPen)
    painter.setBrush(UV_CANVAS_DEEP)
    painter.drawRoundedRect(inset, 4, 4)
    cells = _LAYOUT_THUMB_SCHEMES.get(str(layout_id), _LAYOUT_THUMB_SCHEMES["grid_2x2"])
    gutter = 2.4
    hero = str(layout_id) in _HERO_LAYOUT_IDS
    slot_line = QColor(UV_BRAND.red(), UV_BRAND.green(), UV_BRAND.blue(), 55)
    aux_fill = QColor("#E2EAEC")
    hero_fill = QColor("#C9DBDE")
    for index, (left, top, width, height) in enumerate(cells):
        x = inset.x() + left * inset.width() + gutter
        y = inset.y() + top * inset.height() + gutter
        w = max(2.0, width * inset.width() - gutter * 2.0)
        h = max(2.0, height * inset.height() - gutter * 2.0)
        painter.setBrush(hero_fill if hero and index == 0 else aux_fill)
        painter.setPen(slot_line)
        painter.drawRoundedRect(QRectF(x, y, w, h), 2.2, 2.2)
    painter.end()
    return QIcon(pixmap)


def _repolish(widget: QWidget) -> None:
    """Refresh QSS after a dynamic-property state change."""
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def _set_flag(widget: QWidget, name: str, enabled: bool) -> None:
    """Use string properties so QSS attribute selectors are stable in PyQt5."""
    value = "true" if enabled else "false"
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    _repolish(widget)


def _icon_button(
    parent: QWidget,
    *,
    object_name: str,
    icon: QIcon,
    tooltip: str,
    accessible_name: str,
    size: int = 32,
    icon_size: int = 18,
) -> QToolButton:
    """Create one consistent, keyboard-accessible icon-only control."""
    button = QToolButton(parent)
    button.setObjectName(object_name)
    button.setIcon(icon)
    button.setIconSize(QSize(icon_size, icon_size))
    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
    button.setAutoRaise(True)
    button.setAutoFillBackground(False)
    button.setAttribute(Qt.WA_StyledBackground, True)
    button.setFixedSize(size, size)
    button.setFocusPolicy(Qt.TabFocus)
    button.setToolTip(tooltip)
    button.setAccessibleName(accessible_name)
    button.setProperty("role", "icon")
    button.setProperty("chrome", "ultraview")
    button.setProperty("active", "false")
    button.setProperty("modeActive", "false")
    button.setProperty("panelOpen", "false")
    return button


def _rail_button(
    parent: QWidget,
    *,
    object_name: str,
    icon: QIcon,
    tooltip: str,
    accessible_name: str,
) -> QToolButton:
    return _icon_button(
        parent,
        object_name=object_name,
        icon=icon,
        tooltip=tooltip,
        accessible_name=accessible_name,
        size=RAIL_BUTTON_SIZE,
        icon_size=RAIL_ICON_SIZE,
    )


class _ElidedLabel(QLabel):
    """A label which retains full text for accessible name and tooltip use."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.set_full_text(text)

    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = str(text or "")
        self._apply_text()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_text()

    def _apply_text(self) -> None:
        metrics = self.fontMetrics()
        available = max(0, self.width())
        self.setText(metrics.elidedText(self._full_text, Qt.ElideRight, available))
        self.setToolTip(self._full_text)
        self.setAccessibleName(self._full_text)


class _InlineNameEditor(QLineEdit):
    """Transient in-place name field. Enter/blur commit; Esc cancel."""

    committed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrame(False)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._settled = False
        self._armed = False
        self.returnPressed.connect(self._emit_committed)
        QTimer.singleShot(0, self._arm)

    def _arm(self) -> None:
        self._armed = True

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self._emit_cancelled()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if self._armed:
            self._emit_committed()

    def _emit_committed(self) -> None:
        if self._settled:
            return
        self._settled = True
        self.committed.emit(self.text())

    def _emit_cancelled(self) -> None:
        if self._settled:
            return
        self._settled = True
        self.cancelled.emit()

    def discard(self) -> None:
        """Suppress commit/cancel while the host tears the editor down."""
        self._settled = True


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
        widget.raise_()
        _set_flag(widget, "active", True)
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

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._canvas is not None:
            self._canvas.setGeometry(self.contentsRect())
        for key, overlay in self._overlays.items():
            if overlay.isVisible():
                self.set_overlay_geometry(key, overlay.geometry())

    def paintEvent(self, event) -> None:  # noqa: N802
        """Paint the cached Titanium Amber canvas beneath all Qt children."""
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
            (QPointF(width * 0.88, height * 0.09), max(width, height) * 0.42, UV_GLOW_AMBER),
            (QPointF(width * 0.64, height * 1.04), max(width, height) * 0.48, UV_GLOW_COPPER),
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
        for stop, color in ((0.0, UV_BRAND), (0.55, UV_AMBER), (1.0, QColor(titanium_color("copper")))):
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


class StickyPopover(QMenu):
    """Rounded Miro-style 4×4 Sticky palette with a deliberately simple Stack.

    This widget only emits an intent and the chosen semantic palette token.
    Page/controller code owns object creation and its single undo transaction.
    """

    palette_selected = pyqtSignal(str)
    stack_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewStickyPopover")
        self._selected_palette = STICKY_PALETTE_TOKENS[0]
        self._palette_buttons: dict[str, QToolButton] = {}
        apply_rounded_menu_chrome(self)
        self._build_palette()
        self.addSeparator()
        self._stack = self.addAction("Stack")
        self._stack.setProperty("authorAction", "stack")
        self._stack.triggered.connect(self.request_stack)

    def palette_tokens(self) -> tuple[str, ...]:
        return STICKY_PALETTE_TOKENS

    def palette_buttons(self) -> tuple[QToolButton, ...]:
        return tuple(self._palette_buttons[token] for token in STICKY_PALETTE_TOKENS)

    def selected_palette(self) -> str:
        return self._selected_palette

    def choose_palette(self, token: str) -> None:
        checked = str(token)
        if checked not in self._palette_buttons:
            raise ValueError(f"unknown Sticky palette: {checked}")
        self._selected_palette = checked
        for candidate, button in self._palette_buttons.items():
            button.setChecked(candidate == checked)
        self.palette_selected.emit(checked)

    def request_stack(self) -> None:
        self.stack_requested.emit(self._selected_palette)

    def _build_palette(self) -> None:
        host = QWidget(self)
        host.setObjectName("ultraViewStickyPaletteGrid")
        grid = QGridLayout(host)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for index, token in enumerate(STICKY_PALETTE_TOKENS):
            fill, border, _foreground = sticky_colors(token, DEFAULT_THEME)
            button = QToolButton(host)
            button.setObjectName(f"ultraViewStickyPalette{token.title()}Button")
            button.setProperty("palette", token)
            button.setCheckable(True)
            button.setAutoRaise(False)
            button.setFixedSize(28, 28)
            button.setToolTip(f"便签颜色：{token}")
            button.setAccessibleName(f"便签颜色：{token}")
            button.setStyleSheet(
                "QToolButton {"
                f"background-color: rgb({fill[0]}, {fill[1]}, {fill[2]});"
                f"border: 1px solid rgb({border[0]}, {border[1]}, {border[2]});"
                "border-radius: 4px; }"
                "QToolButton:checked { border: 2px solid #2563eb; }"
            )
            button.clicked.connect(self._on_palette_clicked)
            self._palette_buttons[token] = button
            grid.addWidget(button, index // 4, index % 4)
        self._palette_buttons[self._selected_palette].setChecked(True)
        action = QWidgetAction(self)
        action.setDefaultWidget(host)
        self.addAction(action)

    def _on_palette_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_palette(str(sender.property("palette") or ""))


class ShapePopover(QMenu):
    """Rounded menu exposing precisely the nine V1 shape and line choices."""

    shape_selected = pyqtSignal(str)
    _SHAPES = (
        ("line", "Line"),
        ("arrow", "Arrow"),
        ("elbow_arrow", "Elbow arrow"),
        ("block_arrow", "Block arrow"),
        ("rectangle", "Rectangle"),
        ("oval", "Oval"),
        ("rhombus", "Rhombus"),
        ("triangle", "Triangle"),
        ("divider", "Divider"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewShapePopover")
        apply_rounded_menu_chrome(self)
        for index, (shape, label) in enumerate(self._SHAPES):
            if index == 4:
                self.addSeparator()
            action = self.addAction(label)
            action.setProperty("shapeType", shape)
            action.triggered.connect(self._on_shape_triggered)

    def shape_types(self) -> tuple[str, ...]:
        return tuple(shape for shape, _label in self._SHAPES)

    def choose_shape(self, shape: str) -> None:
        checked = str(shape)
        if checked not in self.shape_types():
            raise ValueError(f"unknown author shape: {checked}")
        self.shape_selected.emit(checked)

    def _on_shape_triggered(self) -> None:
        sender = self.sender()
        if sender is not None:
            self.choose_shape(str(sender.property("shapeType") or ""))


@dataclass(frozen=True)
class DrawPreset:
    """One local, non-persistent draw preset projected by :class:`DrawPopover`."""

    palette: str
    width_px_100: int


class DrawPopover(QMenu):
    """Rounded Pen/Highlighter preset picker plus Eraser and Lasso intents."""

    tool_selected = pyqtSignal(str, int)
    _SUBTOOLS = ("pen", "highlighter", "eraser", "lasso")
    _DEFAULT_PRESETS = {
        "pen": (
            DrawPreset("ink", 2), DrawPreset("blue", 4), DrawPreset("red", 8),
        ),
        "highlighter": (
            DrawPreset("yellow", 8), DrawPreset("green", 12), DrawPreset("pink", 16),
        ),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewDrawPopover")
        self._presets = dict(self._DEFAULT_PRESETS)
        self._active_tool = "pen"
        self._active_preset = 0
        apply_rounded_menu_chrome(self)
        self._build_actions()

    def subtools(self) -> tuple[str, ...]:
        return self._SUBTOOLS

    def presets(self, tool: str) -> tuple[DrawPreset, ...]:
        return tuple(self._presets.get(str(tool), ()))

    def active_tool(self) -> tuple[str, int]:
        return self._active_tool, self._active_preset

    def set_presets(self, tool: str, presets: tuple[DrawPreset, ...]) -> None:
        checked = str(tool)
        if checked not in {"pen", "highlighter"} or len(presets) != 3:
            raise ValueError("Pen and Highlighter require exactly three presets")
        if not all(isinstance(preset, DrawPreset) for preset in presets):
            raise TypeError("draw presets must be DrawPreset instances")
        self._presets[checked] = tuple(presets)
        self.clear()
        self._build_actions()

    def choose_tool(self, tool: str, preset_index: int = 0) -> None:
        checked = str(tool)
        if checked not in self._SUBTOOLS:
            raise ValueError(f"unknown draw tool: {checked}")
        index = int(preset_index)
        if checked in self._presets and not 0 <= index < len(self._presets[checked]):
            raise ValueError(f"unknown {checked} preset: {index}")
        if checked not in self._presets:
            index = 0
        self._active_tool = checked
        self._active_preset = index
        self.tool_selected.emit(checked, index)

    def _build_actions(self) -> None:
        labels = {"pen": "Pen", "highlighter": "Highlighter"}
        for tool in ("pen", "highlighter"):
            submenu = add_rounded_submenu(self, labels[tool])
            for index, preset in enumerate(self._presets[tool], start=1):
                action = submenu.addAction(f"Preset {index} · {preset.width_px_100}px")
                action.setProperty("drawTool", tool)
                action.setProperty("presetIndex", index - 1)
                action.triggered.connect(self._on_draw_action_triggered)
        self.addSeparator()
        for tool, label in (("eraser", "Eraser"), ("lasso", "Lasso")):
            action = self.addAction(label)
            action.setProperty("drawTool", tool)
            action.setProperty("presetIndex", 0)
            action.triggered.connect(self._on_draw_action_triggered)

    def _on_draw_action_triggered(self) -> None:
        sender = self.sender()
        if sender is not None:
            self.choose_tool(
                str(sender.property("drawTool") or ""),
                int(sender.property("presetIndex") or 0),
            )


class TextFormattingToolbar(QFrame):
    """Small typed formatting surface for a selected/new Board text object.

    The surface intentionally knows no ``QTextDocument``.  It emits compact
    object-level changes, leaving editor selection semantics to the authoring
    controller and keeping V1 honest about its whole-box formatting contract.
    """

    format_requested = pyqtSignal(str, object)
    _FONT_ROLES = ("sans", "serif", "mono")
    _ALIGNMENTS = ("left", "center", "right")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewTextFormattingToolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("surface", "island")
        self._format = {
            "font_role": "sans", "font_size": 14, "bold": False, "italic": False,
            "underline": False, "align": "left", "list_style": "none",
            "text_palette": "ink", "fill_palette": None, "locked": False,
        }
        self._buttons: dict[str, QToolButton] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        layout.addWidget(
            self._menu_button(
                "font_role", "Sans", "字体", (("sans", "Sans"), ("serif", "Serif"), ("mono", "Mono")),
            )
        )
        layout.addWidget(
            self._menu_button(
                "font_size", "14", "字号", tuple((size, str(size)) for size in (8, 10, 12, 14, 18, 24, 32, 48)),
            )
        )
        for key, label, tooltip in (
            ("bold", "B", "加粗"), ("italic", "I", "斜体"), ("underline", "U", "下划线"),
        ):
            button = self._format_button(key, label, tooltip, checkable=True)
            button.clicked.connect(self._on_toggle_format)
            layout.addWidget(button)
        divider = QFrame(self)
        divider.setFrameShape(QFrame.VLine)
        divider.setFixedWidth(1)
        layout.addWidget(divider)
        for alignment, label in (("left", "左"), ("center", "中"), ("right", "右")):
            button = self._format_button(f"align:{alignment}", label, f"{label}对齐", checkable=True)
            button.setProperty("alignment", alignment)
            button.clicked.connect(self._on_alignment_clicked)
            layout.addWidget(button)
        layout.addWidget(
            self._menu_button(
                "list_style", "•", "列表", (("none", "无列表"), ("bullet", "项目符号"), ("number", "编号列表")),
            )
        )
        layout.addWidget(
            self._menu_button(
                "text_palette", "A", "文字颜色", (("ink", "墨色"), ("blue", "蓝色"), ("red", "红色"), ("green", "绿色")),
            )
        )
        layout.addWidget(
            self._menu_button(
                "fill_palette", "▨", "文字底色", ((None, "透明"), ("yellow", "黄色"), ("blue", "蓝色"), ("green", "绿色")),
            )
        )
        lock = self._format_button("locked", "锁", "锁定", checkable=True)
        lock.clicked.connect(self._on_toggle_format)
        layout.addWidget(lock)

    def button(self, key: str) -> QToolButton | None:
        return self._buttons.get(str(key))

    def formatting(self) -> dict[str, object]:
        return dict(self._format)

    def set_available(self, enabled: bool, reason: str = "") -> None:
        text = str(reason or "文字格式")
        for button in self._buttons.values():
            button.setEnabled(bool(enabled))
            button.setToolTip(text if not enabled else button.accessibleName())

    def set_font_role(self, role: str) -> None:
        checked = str(role)
        if checked not in self._FONT_ROLES:
            raise ValueError(f"unknown text font role: {checked}")
        self._set_format("font_role", checked)

    def set_font_size(self, size: int) -> None:
        checked = int(size)
        if not 8 <= checked <= 96:
            raise ValueError("text font size must be 8..96")
        self._set_format("font_size", checked)

    def set_alignment(self, alignment: str) -> None:
        checked = str(alignment)
        if checked not in self._ALIGNMENTS:
            raise ValueError(f"unknown text alignment: {checked}")
        self._set_format("align", checked)
        for candidate in self._ALIGNMENTS:
            button = self._buttons[f"align:{candidate}"]
            button.setChecked(candidate == checked)

    def set_list_style(self, style: str) -> None:
        checked = str(style)
        if checked not in {"none", "bullet", "number"}:
            raise ValueError(f"unknown text list style: {checked}")
        self._set_format("list_style", checked)

    def set_text_palette(self, palette: str) -> None:
        self._set_format("text_palette", str(palette))

    def set_fill_palette(self, palette: str | None) -> None:
        self._set_format("fill_palette", None if palette is None else str(palette))

    def set_locked(self, locked: bool) -> None:
        self._set_format("locked", bool(locked))
        self._buttons["locked"].setChecked(bool(locked))

    def set_link(self, link: str | None) -> None:
        self._set_format("link", None if link is None else str(link))

    def _format_button(self, key: str, label: str, tooltip: str, *, checkable: bool) -> QToolButton:
        button = _icon_button(
            self,
            object_name=f"ultraViewTextToolbar{key.replace(':', '').title()}Button",
            icon=QIcon(),
            tooltip=tooltip,
            accessible_name=tooltip,
            size=28,
            icon_size=16,
        )
        button.setText(label)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setCheckable(checkable)
        button.setProperty("formatKey", key)
        self._buttons[key] = button
        return button

    def _menu_button(
        self,
        key: str,
        label: str,
        tooltip: str,
        choices: tuple[tuple[object, str], ...],
    ) -> QToolButton:
        button = self._format_button(key, label, tooltip, checkable=False)
        menu = QMenu(button)
        apply_rounded_menu_chrome(menu)
        for value, choice_label in choices:
            action = menu.addAction(choice_label)
            action.setProperty("formatMenuKey", key)
            action.setProperty("formatMenuValue", value)
            action.triggered.connect(self._on_menu_format_triggered)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.InstantPopup)
        return button

    def _on_toggle_format(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            key = str(sender.property("formatKey") or "")
            if key in {"bold", "italic", "underline", "locked"}:
                self._set_format(key, sender.isChecked())

    def _on_alignment_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.set_alignment(str(sender.property("alignment") or ""))

    def _on_menu_format_triggered(self) -> None:
        sender = self.sender()
        if sender is None:
            return
        key = str(sender.property("formatMenuKey") or "")
        value = sender.property("formatMenuValue")
        if key == "font_role":
            self.set_font_role(str(value))
        elif key == "font_size":
            self.set_font_size(int(value))
        elif key == "list_style":
            self.set_list_style(str(value))
        elif key == "text_palette":
            self.set_text_palette(str(value))
        elif key == "fill_palette":
            self.set_fill_palette(None if value is None else str(value))

    def _set_format(self, key: str, value: object) -> None:
        if self._format.get(key) == value:
            return
        self._format[key] = value
        self.format_requested.emit(key, value)


class ToolRail(QFrame):
    """The fixed left rail; Page owns which requested panel opens.

    Empty-board CTA state is a local visual flag (``set_empty_board``).  The
    rail never reads ``UltraViewBoardState``; Page decides when the canvas
    has no placed cards.
    """

    panel_requested = pyqtSignal(str)
    tool_requested = pyqtSignal(str)
    tool_pinned_changed = pyqtSignal(str, bool)
    free_grid_toggled = pyqtSignal(bool)
    ref_dropped = pyqtSignal(str, str)
    sync_all_requested = pyqtSignal()

    _PANEL_SPECS: tuple[tuple[str, str, str, Callable[..., QIcon]], ...] = (
        (PANEL_LIBRARY, "Library", "打开 View 库", Icons.ultraview_library),
        (PANEL_LAYOUT, "Layout", "选择 Board 布局", Icons.ultraview_layout),
        (PANEL_FILTER, "Filter", "筛选可对比的 View", Icons.ultraview_filter),
        (PANEL_UNPLACED, "Unplaced", "查看未放置的 View", Icons.ultraview_unplaced),
    )
    _CREATION_SPECS: tuple[tuple[str, str, str], ...] = (
        (AUTHOR_TOOL_SELECT, "Select", "选择对象 (V)"),
        (AUTHOR_TOOL_STICKY, "Sticky", "添加便签贴纸 (N)"),
        (AUTHOR_TOOL_TEXT, "Text", "添加文字 (T)"),
        (AUTHOR_TOOL_SHAPES, "Shapes", "添加形状或连接线"),
        (AUTHOR_TOOL_DRAW, "Draw", "画笔、高亮、擦除或套索 (P)"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewToolRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setProperty("surface", "island")
        self.setFixedWidth(RAIL_WIDTH)
        self._buttons: dict[str, QToolButton] = {}
        self._tool_buttons: dict[str, _AuthorToolButton] = {}
        self._icon_factories: dict[str, Callable[..., QIcon]] = {}
        self._badges: dict[str, QLabel] = {}
        self._active_panel: str | None = None
        self._filter_active = False
        self._free_grid_enabled = False
        self._empty_board = False
        self._stale_count = 0
        self._creation_enabled = False
        self._creation_disabled_reason = "创作工具将在自由网格中可用"
        self._active_tool = AUTHOR_TOOL_SELECT
        self._pinned_tool: str | None = None
        root = QVBoxLayout(self)
        # Eleven 36px targets must remain fully usable in the 800×560 compact
        # stage.  Keep the Miro-like rail as one dense, accessible column
        # instead of allowing Page's safe-band clamp to crop its last tools.
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(1)
        # Visual order: Library, FreeGrid, Layout, Filter, divider, Unplaced,
        # SyncAll.
        for index, (panel_id, short_name, tooltip, icon_factory) in enumerate(self._PANEL_SPECS):
            if index == 1:
                self._free_grid = _rail_button(
                    self,
                    object_name="ultraViewRailFreeGridButton",
                    icon=Icons.ultraview_free_grid(UV_MUTED),
                    tooltip="切换自由网格（12 列基准网格）",
                    accessible_name="切换自由网格（12 列基准网格）",
                )
                self._free_grid.setCheckable(True)
                self._free_grid.clicked.connect(self._on_free_grid_clicked)
                root.addWidget(self._free_grid, 0, Qt.AlignHCenter)
            if index == 3:
                self._add_rail_divider(root, "ultraViewToolRailCreationDivider")
                self._add_creation_section(root)
                self._add_rail_divider(root, "ultraViewToolRailPostCreationDivider")
            button = _rail_button(
                self,
                object_name=f"ultraViewRail{short_name}Button",
                icon=icon_factory(UV_MUTED),
                tooltip=tooltip,
                accessible_name=tooltip,
            )
            button.setProperty("panel", panel_id)
            button.setCheckable(True)
            button.clicked.connect(self._on_panel_clicked)
            self._buttons[panel_id] = button
            self._icon_factories[panel_id] = icon_factory
            root.addWidget(button, 0, Qt.AlignHCenter)
            badge = QLabel(self)
            badge.setObjectName(f"ultraViewRail{short_name}Badge")
            badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            badge.setAlignment(Qt.AlignCenter)
            badge.setMinimumSize(14, 14)
            badge.setProperty("role", "badge")
            badge.hide()
            self._badges[panel_id] = badge
        self._filter_warning = False
        self._filter_dot = QLabel(self)
        self._filter_dot.setObjectName("ultraViewRailFilterWarningDot")
        self._filter_dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._filter_dot.setFixedSize(8, 8)
        self._filter_dot.setToolTip("轴量纲或范围不一致")
        self._filter_dot.setAccessibleName("轴一致性警告")
        self._filter_dot.hide()
        self._sync_all = _rail_button(
            self,
            object_name="ultraViewRailSyncAllButton",
            icon=Icons.ultraview_sync(UV_MUTED),
            tooltip="一键更新源",
            accessible_name="一键更新全部已变化的预览",
        )
        self._sync_all.clicked.connect(self._on_sync_all_clicked)
        root.addWidget(self._sync_all, 0, Qt.AlignHCenter)
        self._sync_all_badge = QLabel(self)
        self._sync_all_badge.setObjectName("ultraViewRailSyncAllBadge")
        self._sync_all_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._sync_all_badge.setAlignment(Qt.AlignCenter)
        self._sync_all_badge.setMinimumSize(14, 14)
        self._sync_all_badge.setProperty("role", "badge")
        self._sync_all_badge.hide()
        self.set_stale_count(0)
        self.set_active_panel(None)
        self._sync_creation_states()

    def panel_button(self, panel_id: str) -> QToolButton | None:
        return self._buttons.get(str(panel_id))

    def free_grid_button(self) -> QToolButton:
        return self._free_grid

    def tool_button(self, tool: str) -> QToolButton | None:
        """Return a creation-tool button without exposing its panel siblings."""
        return self._tool_buttons.get(str(tool))

    def active_tool(self) -> str:
        return self._active_tool

    def pinned_tool(self) -> str | None:
        return self._pinned_tool

    def set_creation_enabled(self, enabled: bool, reason: str = "") -> None:
        """Gate the visible creation section for template/presentation states.

        Page supplies the reason so disabled chrome remains explanatory rather
        than looking like an unavailable implementation stub.
        """
        self._creation_enabled = bool(enabled)
        self._creation_disabled_reason = str(reason or "创作工具仅在自由网格中可用")
        if not self._creation_enabled:
            self._active_tool = AUTHOR_TOOL_SELECT
            self._pinned_tool = None
        self._sync_creation_states()

    set_authoring_enabled = set_creation_enabled

    def set_active_tool(self, tool: str, *, pinned: bool = False) -> None:
        checked = str(tool)
        if checked not in self._tool_buttons:
            raise ValueError(f"unknown authoring tool: {checked}")
        self._active_tool = checked
        self._pinned_tool = checked if pinned and checked != AUTHOR_TOOL_SELECT else None
        self._sync_creation_states()

    def make_sticky_popover(self, parent: QWidget | None = None) -> StickyPopover:
        return StickyPopover(parent or self)

    def make_shape_popover(self, parent: QWidget | None = None) -> ShapePopover:
        return ShapePopover(parent or self)

    def make_draw_popover(self, parent: QWidget | None = None) -> DrawPopover:
        return DrawPopover(parent or self)

    def sync_all_button(self) -> QToolButton:
        return self._sync_all

    def set_stale_count(self, count: int) -> None:
        """Show how many Board previews are stale; zero disables the action."""
        try:
            value = max(0, int(count or 0))
        except (TypeError, ValueError):
            value = 0
        self._stale_count = value
        self._sync_all.setEnabled(value > 0)
        _set_flag(self._sync_all, "attention", value > 0)
        badge = self._sync_all_badge
        badge.setText(str(value) if value else "")
        badge.setToolTip(f"{value} 个预览源已变化" if value else "")
        badge.setAccessibleName(f"已变化预览：{value}" if value else "")
        if value > 0:
            badge.adjustSize()
            hint = badge.sizeHint()
            badge.resize(max(14, hint.width()), max(14, hint.height()))
            badge.show()
        else:
            badge.hide()
        self._sync_all.setToolTip(
            "一键更新源" if value else "没有需要更新的预览"
        )
        self._sync_all.setAccessibleName(
            "一键更新全部已变化的预览" if value else "一键更新源（当前没有已变化预览）"
        )
        self._sync_all.setIcon(
            Icons.ultraview_sync(_ultraview_icon_color(active=value > 0))
        )
        self._position_badges()

    def stale_count(self) -> int:
        return self._stale_count

    def active_panel(self) -> str | None:
        return self._active_panel

    def set_active_panel(self, panel_id: str | None) -> None:
        key = str(panel_id) if panel_id is not None else None
        if key not in self._buttons:
            key = None
        self._active_panel = key
        self._sync_button_states()

    def set_filter_active(self, active: bool) -> None:
        """Keep a non-``all`` compare filter discoverable after closing it."""
        self._filter_active = bool(active)
        self._sync_button_states()

    def set_filter_warning(self, warning: bool) -> None:
        """Show the funnel warning dot while axis facts are inconsistent."""
        self._filter_warning = bool(warning)
        self._filter_dot.setVisible(self._filter_warning)
        if self._filter_warning:
            self._position_badges()

    def filter_warning(self) -> bool:
        return self._filter_warning

    def set_free_grid_enabled(self, enabled: bool) -> None:
        """Project the current free-grid mode without emitting the toggle."""
        self._free_grid_enabled = bool(enabled)
        self._sync_button_states()

    def set_empty_board(self, empty: bool) -> None:
        """Paint View 库 as the empty-canvas primary CTA; retracts once cards exist."""
        wanted = bool(empty)
        if self._empty_board == wanted:
            return
        self._empty_board = wanted
        self._sync_button_states()

    def _sync_button_states(self) -> None:
        for candidate, button in self._buttons.items():
            mode_active = (
                candidate == PANEL_FILTER and self._filter_active
            ) or (
                candidate == PANEL_LAYOUT and not self._free_grid_enabled
            )
            panel_open = candidate == self._active_panel
            empty_cta = candidate == PANEL_LIBRARY and self._empty_board
            _set_flag(button, "modeActive", mode_active)
            _set_flag(button, "panelOpen", panel_open)
            _set_flag(button, "emptyCta", empty_cta)
            _set_flag(button, "active", False)
            button.setChecked(panel_open)
            factory = self._icon_factories.get(candidate)
            if factory is not None:
                # A panel that is open is the user's current navigation
                # destination, just like a persistent mode: it receives the
                # shared filled chrome and must therefore carry a light icon.
                if empty_cta or mode_active or panel_open:
                    button.setIcon(factory(UV_PRESENTATION_ICON))
                else:
                    button.setIcon(
                        factory(_ultraview_icon_color(active=mode_active or panel_open))
                    )
        blocked = self._free_grid.blockSignals(True)
        self._free_grid.setChecked(self._free_grid_enabled)
        self._free_grid.blockSignals(blocked)
        _set_flag(self._free_grid, "modeActive", self._free_grid_enabled)
        _set_flag(self._free_grid, "panelOpen", False)
        _set_flag(self._free_grid, "active", False)
        self._free_grid.setIcon(
            Icons.ultraview_free_grid(
                UV_PRESENTATION_ICON if self._free_grid_enabled else UV_MUTED
            )
        )
        sync_all = getattr(self, "_sync_all", None)
        if sync_all is not None:
            sync_all.setIcon(
                Icons.ultraview_sync(
                    _ultraview_icon_color(active=self._stale_count > 0)
                )
            )

    def _sync_creation_states(self) -> None:
        for tool, button in self._tool_buttons.items():
            is_active = self._creation_enabled and tool == self._active_tool
            is_pinned = self._creation_enabled and tool == self._pinned_tool
            button.setEnabled(self._creation_enabled)
            button.setChecked(is_active)
            button.setToolTip(
                button.accessibleName() if self._creation_enabled else self._creation_disabled_reason
            )
            _set_flag(button, "active", is_active)
            _set_flag(button, "pinned", is_pinned)
            _set_flag(button, "modeActive", False)
            _set_flag(button, "panelOpen", False)
            button.setIcon(_author_tool_icon(tool, active=is_active))

    def _add_rail_divider(self, layout: QVBoxLayout, object_name: str) -> None:
        divider = QFrame(self)
        divider.setObjectName(object_name)
        divider.setFrameShape(QFrame.HLine)
        divider.setFixedHeight(1)
        layout.addWidget(divider, 0)

    def _add_creation_section(self, layout: QVBoxLayout) -> None:
        for tool, short_name, tooltip in self._CREATION_SPECS:
            button = _AuthorToolButton(self)
            button.setObjectName(f"ultraViewRail{short_name}Button")
            button.setIcon(_author_tool_icon(tool, active=False))
            button.setIconSize(QSize(RAIL_ICON_SIZE, RAIL_ICON_SIZE))
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setAutoRaise(True)
            button.setAutoFillBackground(False)
            button.setAttribute(Qt.WA_StyledBackground, True)
            button.setFixedSize(RAIL_BUTTON_SIZE, RAIL_BUTTON_SIZE)
            button.setFocusPolicy(Qt.TabFocus)
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setProperty("role", "icon")
            button.setProperty("chrome", "ultraview")
            button.setProperty("authorTool", tool)
            button.setProperty("active", "false")
            button.setProperty("pinned", "false")
            button.setProperty("modeActive", "false")
            button.setProperty("panelOpen", "false")
            button.setCheckable(True)
            button.clicked.connect(self._on_tool_clicked)
            button.pin_requested.connect(self._on_tool_pin_requested)
            self._tool_buttons[tool] = button
            layout.addWidget(button, 0, Qt.AlignHCenter)

    def set_badge(self, panel_id: str, count: int | None) -> None:
        """Set an exact count badge; zero/None intentionally shows no badge."""
        key = str(panel_id)
        badge = self._badges.get(key)
        if badge is None:
            raise KeyError(key)
        try:
            value = max(0, int(count or 0))
        except (TypeError, ValueError):
            value = 0
        badge.setText(str(value))
        badge.setToolTip(f"{value} 个未放置 View" if value else "")
        badge.setAccessibleName(f"未放置 View：{value}" if value else "")
        if value > 0:
            badge.adjustSize()
            hint = badge.sizeHint()
            badge.resize(max(14, hint.width()), max(14, hint.height()))
            badge.show()
        else:
            badge.hide()
        self._position_badges()

    def badge_text(self, panel_id: str) -> str:
        badge = self._badges.get(str(panel_id))
        return badge.text() if badge is not None else ""

    def set_panel_attention(self, panel_id: str, attention: bool) -> None:
        button = self._buttons.get(str(panel_id))
        if button is None:
            raise KeyError(str(panel_id))
        _set_flag(button, "attention", bool(attention))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_badges()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(RAIL_WIDTH, max(RAIL_CONTENT_HEIGHT, super().sizeHint().height()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _position_badges(self) -> None:
        for panel_id, badge in self._badges.items():
            button = self._buttons[panel_id]
            if badge.isHidden():
                continue
            x = button.x() + button.width() - max(8, badge.width() // 2)
            y = max(0, button.y() - 2)
            x = min(max(0, x), max(0, self.width() - badge.width()))
            badge.move(x, y)
            badge.raise_()
        button = self._buttons.get(PANEL_FILTER)
        if button is not None and not self._filter_dot.isHidden():
            x = min(max(0, button.x() + button.width() - 6), max(0, self.width() - 8))
            y = max(0, button.y() + 2)
            self._filter_dot.move(x, y)
            self._filter_dot.raise_()
        badge = getattr(self, "_sync_all_badge", None)
        button = getattr(self, "_sync_all", None)
        if badge is not None and button is not None and not badge.isHidden():
            x = button.x() + button.width() - max(8, badge.width() // 2)
            y = max(0, button.y() - 2)
            x = min(max(0, x), max(0, self.width() - badge.width()))
            badge.move(x, y)
            badge.raise_()

    def _on_panel_clicked(self) -> None:
        button = self.sender()
        if not isinstance(button, QToolButton):
            return
        panel_id = str(button.property("panel") or "")
        if panel_id in self._buttons:
            self.panel_requested.emit(panel_id)

    def _on_tool_clicked(self) -> None:
        button = self.sender()
        if not isinstance(button, QToolButton) or not self._creation_enabled:
            return
        tool = str(button.property("authorTool") or "")
        if tool not in self._tool_buttons:
            return
        self.set_active_tool(tool, pinned=False)
        self.tool_requested.emit(tool)

    def _on_tool_pin_requested(self, tool: str) -> None:
        checked = str(tool)
        if not self._creation_enabled or checked not in self._tool_buttons:
            return
        now_pinned = checked != self._pinned_tool
        self.set_active_tool(checked, pinned=now_pinned)
        self.tool_pinned_changed.emit(checked, now_pinned)

    def _on_free_grid_clicked(self) -> None:
        self.free_grid_toggled.emit(self._free_grid.isChecked())

    def _on_sync_all_clicked(self) -> None:
        self.sync_all_requested.emit()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(ULTRAVIEW_REF_MIME):
            self.set_panel_attention(PANEL_UNPLACED, True)
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_panel_attention(PANEL_UNPLACED, False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802
        self.set_panel_attention(PANEL_UNPLACED, False)
        try:
            raw = bytes(event.mimeData().data(ULTRAVIEW_REF_MIME)).decode("utf-8")
            ref = parse_ref_payload(json.loads(raw))
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            ref = None
        if ref is None:
            event.ignore()
            return
        self.ref_dropped.emit(ref.section, ref.view_id)
        event.acceptProposedAction()


class BoardIsland(QFrame):
    """Current Board identity plus compact menu/new actions.

    The Page supplies the selected board text and owns the actual menu.  This
    keeps confirmation, Board limits, reordering, and workspace mutation out
    of a presentation widget.
    """

    board_menu_requested = pyqtSignal()
    create_requested = pyqtSignal()
    rename_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setMaximumWidth(BOARD_ISLAND_MAX_WIDTH)
        self.setProperty("surface", "island")
        self._board_id = ""
        self._rename_editor: _InlineNameEditor | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(2)
        self._name = _ElidedLabel("", self)
        self._name.setObjectName("ultraViewBoardIslandName")
        self._name.setMinimumWidth(48)
        self._name.installEventFilter(self)
        layout.addWidget(self._name, 1)
        self._menu = _icon_button(
            self,
            object_name="ultraViewBoardMenuButton",
            icon=Icons.chevron_down(UV_MUTED),
            tooltip="切换或管理 Board",
            accessible_name="切换或管理当前 Board",
        )
        self._menu.clicked.connect(self.board_menu_requested)
        layout.addWidget(self._menu, 0)
        self._add = _icon_button(
            self,
            object_name="ultraViewBoardAddButton",
            icon=Icons.ultraview_add(UV_MUTED),
            tooltip="新建 Board",
            accessible_name="新建 Board",
        )
        self._add.clicked.connect(self.create_requested)
        layout.addWidget(self._add, 0)

    def board_id(self) -> str:
        return self._board_id

    def board_name_label(self) -> QLabel:
        return self._name

    def menu_button(self) -> QToolButton:
        return self._menu

    def add_button(self) -> QToolButton:
        return self._add

    def set_current_board(self, board_id: str, name: str) -> None:
        new_id = str(board_id or "")
        if self._rename_editor is not None and new_id != self._board_id:
            self._close_inline_rename()
        self._board_id = new_id
        self.setProperty("boardId", self._board_id)
        if self._rename_editor is None:
            self._name.set_full_text(str(name or ""))
        self.setAccessibleName(f"当前 Board：{name or ''}")
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = self._name.fontMetrics()
        name_width = min(max(48, metrics.horizontalAdvance(self._name.full_text() or "Board") + 8), 148)
        return QSize(
            min(BOARD_ISLAND_MAX_WIDTH, 8 + name_width + 2 + 32 + 2 + 32 + 4),
            ISLAND_HEIGHT,
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(120, ISLAND_HEIGHT)

    def set_create_enabled(self, enabled: bool, reason: str = "") -> None:
        self._add.setEnabled(bool(enabled))
        self._add.setToolTip(str(reason or "新建 Board"))

    def set_menu_open(self, opened: bool) -> None:
        """Project overlay-open chrome without making the chevron checkable."""
        active = bool(opened)
        _set_flag(self._menu, "panelOpen", active)
        self._menu.setIcon(Icons.chevron_down(_ultraview_icon_color(active=active)))

    def begin_inline_rename(self) -> None:
        """Overlay a line edit on the name; commit emits ``rename_requested``."""
        if self._rename_editor is not None:
            self._rename_editor.setFocus(Qt.OtherFocusReason)
            self._rename_editor.selectAll()
            return
        editor = _InlineNameEditor(self)
        editor.setObjectName("ultraViewBoardIslandRename")
        editor.setFont(self._name.font())
        editor.setText(self._name.full_text())
        editor.setGeometry(self._name.geometry())
        editor.committed.connect(self._on_inline_rename_committed)
        editor.cancelled.connect(self._on_inline_rename_cancelled)
        self._rename_editor = editor
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.OtherFocusReason)
        editor.selectAll()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._name and event.type() == QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton:
                self.begin_inline_rename()
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._rename_editor is not None:
            self._rename_editor.setGeometry(self._name.geometry())

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_F2:
            self.begin_inline_rename()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_inline_rename_committed(self, text: str) -> None:
        self._close_inline_rename()
        cleaned = str(text or "").strip()
        if cleaned:
            self.rename_requested.emit(cleaned)

    def _on_inline_rename_cancelled(self) -> None:
        self._close_inline_rename()

    def _close_inline_rename(self) -> None:
        editor = self._rename_editor
        self._rename_editor = None
        if editor is None:
            return
        editor.discard()
        editor.hide()
        editor.deleteLater()


class _BoardListDelegate(QStyledItemDelegate):
    """Draw check + name + copy/delete without stealing InternalMove."""

    duplicate_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hovered_row = -1
        # Duplicating a Board preserves its layout/reference collection; it is
        # not an image-copy operation.  Use one normalised Font Awesome family
        # for both compact row actions so their optical boxes match.
        self._copy_icon = qta.icon("fa5s.clone", color=UV_MUTED)
        self._delete_icon = qta.icon("fa5s.trash-alt", color=UV_DANGER)

    def set_hovered_row(self, row: int) -> None:
        self._hovered_row = int(row)

    def hovered_row(self) -> int:
        return self._hovered_row

    def paint(self, painter, option, index) -> None:  # noqa: N802
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect.adjusted(4, 2, -4, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = index.row() == self._hovered_row
        current = bool(index.data(_BOARD_CURRENT_ROLE))
        if selected:
            painter.setPen(UV_BRAND)
            painter.setBrush(UV_WASH)
            painter.drawRoundedRect(QRectF(rect), 6, 6)
        elif hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#F7FAFC"))
            painter.drawRoundedRect(QRectF(rect), 6, 6)
        check_rect = QRect(rect.left() + 4, rect.top(), 16, rect.height())
        painter.setPen(UV_BRAND if current else Qt.transparent)
        painter.drawText(check_rect, Qt.AlignCenter, "✓" if current else "")
        copy_rect, delete_rect = self.action_rects(option.rect)
        name_rect = self.name_rect(option.rect)
        metrics = option.fontMetrics
        name = metrics.elidedText(str(index.data(Qt.DisplayRole) or ""), Qt.ElideRight, name_rect.width())
        painter.setPen(UV_INK)
        painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, name)
        self._paint_icon(painter, self._copy_icon, copy_rect)
        self._paint_icon(painter, self._delete_icon, delete_rect)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        del option, index
        return QSize(BOARD_POPOVER_WIDTH - 16, BOARD_ROW_HEIGHT)

    @staticmethod
    def _paint_icon(painter, icon: QIcon, slot: QRect) -> None:
        box = QRect(0, 0, 18, 18)
        box.moveCenter(slot.center())
        icon.paint(painter, box, Qt.AlignCenter)

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        del model
        if event.type() != QEvent.MouseButtonRelease or event.button() != Qt.LeftButton:
            return False
        board_id = str(index.data(Qt.UserRole) or "")
        if not board_id:
            return False
        copy_rect, delete_rect = self.action_rects(option.rect)
        if copy_rect.contains(event.pos()):
            self.duplicate_requested.emit(board_id)
            return True
        if delete_rect.contains(event.pos()):
            self.delete_requested.emit(board_id)
            return True
        return False

    @staticmethod
    def action_rects(item_rect: QRect) -> tuple[QRect, QRect]:
        delete_rect = QRect(
            item_rect.right() - _BOARD_ACTION_WIDTH - 4,
            item_rect.top(),
            _BOARD_ACTION_WIDTH,
            item_rect.height(),
        )
        copy_rect = QRect(
            delete_rect.left() - _BOARD_ACTION_WIDTH,
            item_rect.top(),
            _BOARD_ACTION_WIDTH,
            item_rect.height(),
        )
        return copy_rect, delete_rect

    @staticmethod
    def name_rect(item_rect: QRect) -> QRect:
        rect = item_rect.adjusted(4, 2, -4, -2)
        check_right = rect.left() + 4 + 16
        copy_rect, _delete_rect = _BoardListDelegate.action_rects(item_rect)
        return QRect(
            check_right + 4,
            rect.top(),
            max(0, copy_rect.left() - 4 - check_right - 4),
            rect.height(),
        )


class _BoardList(QListWidget):
    """QListWidget whose Delete key never removes a Board row."""

    reordered = pyqtSignal(str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_id = ""
        self.setObjectName("ultraViewBoardList")
        self.setFrameShape(QFrame.NoFrame)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSizeAdjustPolicy(QAbstractItemView.AdjustToContents)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setDropIndicatorShown(True)
        self.setSpacing(1)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(BOARD_POPOVER_WIDTH - 12, self._content_height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(BOARD_POPOVER_WIDTH - 12, BOARD_ROW_HEIGHT)

    def content_height(self) -> int:
        return self._content_height()

    def _content_height(self) -> int:
        rows = max(1, self.count())
        return rows * BOARD_ROW_HEIGHT + max(0, rows - 1) * self.spacing() + _BOARD_LIST_BOTTOM_PAD

    def startDrag(self, supported_actions) -> None:  # noqa: N802
        item = self.currentItem()
        self._drag_id = str(item.data(Qt.UserRole) or "") if item is not None else ""
        super().startDrag(supported_actions)

    def dropEvent(self, event) -> None:  # noqa: N802
        super().dropEvent(event)
        board_id = self._drag_id
        self._drag_id = ""
        if not board_id:
            return
        for index in range(self.count()):
            item = self.item(index)
            if item is not None and str(item.data(Qt.UserRole) or "") == board_id:
                self.reordered.emit(board_id, index)
                return

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            event.accept()
            return
        super().keyPressEvent(event)


class BoardPopover(QFrame):
    """Single-layer Board list: click to switch, drag to reorder, copy/delete on the row.

    Page owns workspace mutation, confirmation, and the 20-Board cap.  This
    widget only projects the current list and emits typed intents.
    """

    board_selected = pyqtSignal(str)
    duplicate_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    boards_reordered = pyqtSignal(str, int)
    create_requested = pyqtSignal()
    rename_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardPopover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._reordering = False
        self._pending_boards: tuple[tuple[object, ...], str | None] | None = None
        self._rename_editor: _InlineNameEditor | None = None
        self._rename_board_id = ""
        self._pending_rename_id = ""
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._end_reordering)
        root = QVBoxLayout(self)
        root.setContentsMargins(
            _BOARD_POPOVER_MARGIN,
            _BOARD_POPOVER_MARGIN,
            _BOARD_POPOVER_MARGIN,
            _BOARD_POPOVER_MARGIN,
        )
        root.setSpacing(_BOARD_POPOVER_GAP)
        self._list = _BoardList(self)
        self._delegate = _BoardListDelegate(self._list)
        self._list.setItemDelegate(self._delegate)
        self._delegate.duplicate_requested.connect(self.duplicate_requested)
        self._delegate.delete_requested.connect(self.delete_requested)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.reordered.connect(self._on_reordered)
        self._list.installEventFilter(self)
        self._list.viewport().installEventFilter(self)
        self._list.verticalScrollBar().valueChanged.connect(self._sync_rename_editor_geometry)
        root.addWidget(self._list, 0)
        self._create = QToolButton(self)
        self._create.setObjectName("ultraViewBoardPopoverCreate")
        self._create.setText("＋ 新建 Board")
        self._create.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._create.setCursor(Qt.PointingHandCursor)
        self._create.setFocusPolicy(Qt.TabFocus)
        self._create.setFixedHeight(_BOARD_CREATE_HEIGHT)
        self._create.setToolTip("新建 Board")
        self._create.setAccessibleName("新建 Board")
        self._create.clicked.connect(self.create_requested)
        root.addWidget(self._create, 0)

    def list_widget(self) -> QListWidget:
        return self._list

    def create_button(self) -> QToolButton:
        return self._create

    def board_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is None:
                continue
            board_id = str(item.data(Qt.UserRole) or "")
            if board_id:
                ids.append(board_id)
        return tuple(ids)

    def current_board_id(self) -> str:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is not None and bool(item.data(_BOARD_CURRENT_ROLE)):
                return str(item.data(Qt.UserRole) or "")
        return ""

    def action_rects_for(self, board_id: str) -> tuple[QRect, QRect]:
        """Viewport-local copy/delete hit rects for tests."""
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is None or str(item.data(Qt.UserRole) or "") != board_id:
                continue
            rect = self._list.visualItemRect(item)
            return _BoardListDelegate.action_rects(rect)
        return QRect(), QRect()

    def name_rect_for(self, board_id: str) -> QRect:
        """Viewport-local name hit rect for tests."""
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is None or str(item.data(Qt.UserRole) or "") != board_id:
                continue
            return _BoardListDelegate.name_rect(self._list.visualItemRect(item))
        return QRect()

    def begin_inline_rename(self, board_id: str = "") -> None:
        """Overlay a line edit on the row name; commit emits ``rename_requested``."""
        target = str(board_id or self._selected_board_id() or "")
        if not target:
            return
        if self._rename_editor is not None:
            if self._rename_board_id == target:
                self._rename_editor.setFocus(Qt.OtherFocusReason)
                self._rename_editor.selectAll()
                return
            self._close_inline_rename()
        item = self._item_for(target)
        if item is None:
            return
        self._list.setCurrentItem(item)
        rect = _BoardListDelegate.name_rect(self._list.visualItemRect(item))
        if not rect.isValid() or rect.width() < 8:
            return
        editor = _InlineNameEditor(self._list.viewport())
        editor.setObjectName("ultraViewBoardRowRename")
        editor.setFont(self._list.font())
        editor.setText(item.text())
        editor.setGeometry(rect)
        editor.committed.connect(self._on_inline_rename_committed)
        editor.cancelled.connect(self._on_inline_rename_cancelled)
        self._rename_editor = editor
        self._rename_board_id = target
        editor.show()
        editor.raise_()
        editor.setFocus(Qt.OtherFocusReason)
        editor.selectAll()

    def _flush_pending_inline_rename(self) -> None:
        board_id = self._pending_rename_id
        self._pending_rename_id = ""
        if board_id:
            self.begin_inline_rename(board_id)

    def apply_internal_move(self, board_id: str, new_index: int) -> None:
        """Reorder as InternalMove would, then emit the same intent."""
        ids = list(self.board_ids())
        if board_id not in ids:
            return
        old = ids.index(board_id)
        target = max(0, min(int(new_index), len(ids) - 1))
        if old == target:
            return
        item = self._list.takeItem(old)
        if item is None:
            return
        self._list.insertItem(target, item)
        self._list.setCurrentItem(item)
        self._on_reordered(board_id, target)

    def set_boards(self, boards, active_board_id: str | None) -> None:
        if self._reordering:
            self._pending_boards = (tuple(boards), active_board_id)
            if not self._flush_timer.isActive():
                self._flush_timer.start(0)
            return
        self._apply_boards(boards, active_board_id)

    def set_create_enabled(self, enabled: bool, reason: str = "") -> None:
        self._create.setEnabled(bool(enabled))
        self._create.setToolTip(str(reason or "新建 Board"))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(BOARD_POPOVER_WIDTH, board_popover_height(self._list.count()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(BOARD_POPOVER_WIDTH, board_popover_height(1))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_list_to_contents()

    def relayout(self) -> None:
        """Recompute list height after the overlay geometry changes."""
        self._fit_list_to_contents()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._list and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_F2:
                board_id = self._selected_board_id()
                if board_id:
                    self.begin_inline_rename(board_id)
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                board_id = self._selected_board_id()
                if board_id:
                    self.board_selected.emit(board_id)
                return True
        if watched is self._list.viewport():
            if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                item = self._list.itemAt(event.pos())
                if item is not None:
                    item_rect = self._list.visualItemRect(item)
                    copy_rect, delete_rect = _BoardListDelegate.action_rects(item_rect)
                    if copy_rect.contains(event.pos()) or delete_rect.contains(event.pos()):
                        return True
                    if _BoardListDelegate.name_rect(item_rect).contains(event.pos()):
                        board_id = str(item.data(Qt.UserRole) or "")
                        if board_id:
                            self._pending_rename_id = board_id
                            QTimer.singleShot(0, self._flush_pending_inline_rename)
                        return True
            if event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
                if event.button() == Qt.LeftButton:
                    item = self._list.itemAt(event.pos())
                    if item is not None:
                        copy_rect, delete_rect = _BoardListDelegate.action_rects(
                            self._list.visualItemRect(item)
                        )
                        if copy_rect.contains(event.pos()) or delete_rect.contains(event.pos()):
                            if event.type() == QEvent.MouseButtonRelease:
                                board_id = str(item.data(Qt.UserRole) or "")
                                if board_id and copy_rect.contains(event.pos()):
                                    self.duplicate_requested.emit(board_id)
                                elif board_id:
                                    self.delete_requested.emit(board_id)
                            return True
            if event.type() == QEvent.MouseMove:
                row = self._list.indexAt(event.pos()).row()
                if row != self._delegate.hovered_row():
                    self._delegate.set_hovered_row(row)
                    self._list.viewport().update()
                item = self._list.itemAt(event.pos())
                if item is not None:
                    copy_rect, delete_rect = _BoardListDelegate.action_rects(
                        self._list.visualItemRect(item)
                    )
                    if copy_rect.contains(event.pos()):
                        self._list.setToolTip("复制 Board")
                    elif delete_rect.contains(event.pos()):
                        self._list.setToolTip("删除 Board")
                    else:
                        self._list.setToolTip(item.toolTip())
            if event.type() == QEvent.Leave:
                if self._delegate.hovered_row() != -1:
                    self._delegate.set_hovered_row(-1)
                    self._list.viewport().update()
        return super().eventFilter(watched, event)

    def _list_content_height(self) -> int:
        return self._list.content_height()

    def _fit_list_to_contents(self) -> None:
        content = self._list_content_height()
        layout = self.layout()
        if layout is None:
            return
        margins = layout.contentsMargins()
        available = (
            self.height()
            - margins.top()
            - margins.bottom()
            - layout.spacing()
            - self._create.height()
        )
        if available <= 0:
            target = content
        else:
            target = max(BOARD_ROW_HEIGHT, min(content, available))
        if self._list.height() != target:
            self._list.setFixedHeight(target)
        if content <= target + 4:
            self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._list.verticalScrollBar().setValue(0)
            if self._list.height() != content and available >= content:
                self._list.setFixedHeight(content)
        else:
            self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def _selected_board_id(self) -> str:
        item = self._list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        board_id = str(item.data(Qt.UserRole) or "")
        if not board_id:
            return
        # Stay open on the already-current Board so a name double-click can
        # enter inline rename. Canvas click / Esc still close the overlay.
        if board_id == self.current_board_id():
            return
        self.board_selected.emit(board_id)

    def _item_for(self, board_id: str) -> QListWidgetItem | None:
        target = str(board_id or "")
        if not target:
            return None
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item is not None and str(item.data(Qt.UserRole) or "") == target:
                return item
        return None

    def _on_inline_rename_committed(self, text: str) -> None:
        board_id = self._rename_board_id
        self._close_inline_rename()
        cleaned = str(text or "").strip()
        if cleaned and board_id:
            self.rename_requested.emit(board_id, cleaned)

    def _on_inline_rename_cancelled(self) -> None:
        self._close_inline_rename()

    def _close_inline_rename(self) -> None:
        self._pending_rename_id = ""
        editor = self._rename_editor
        self._rename_editor = None
        self._rename_board_id = ""
        if editor is None:
            return
        editor.discard()
        editor.hide()
        editor.deleteLater()

    def _sync_rename_editor_geometry(self, _value: int = 0) -> None:
        editor = self._rename_editor
        if editor is None:
            return
        item = self._item_for(self._rename_board_id)
        if item is None:
            self._close_inline_rename()
            return
        editor.setGeometry(_BoardListDelegate.name_rect(self._list.visualItemRect(item)))

    def _on_reordered(self, board_id: str, new_index: int) -> None:
        self._reordering = True
        self.boards_reordered.emit(str(board_id), int(new_index))
        if not self._flush_timer.isActive():
            self._flush_timer.start(0)

    def _end_reordering(self) -> None:
        self._reordering = False
        pending = self._pending_boards
        self._pending_boards = None
        if pending is not None:
            boards, active_id = pending
            self._apply_boards(boards, active_id)

    def _apply_boards(self, boards, active_board_id: str | None) -> None:
        self._close_inline_rename()
        parsed: list[tuple[str, str]] = []
        for index, board in enumerate(boards or ()):
            board_id = str(getattr(board, "board_id", "") or "")
            if not board_id:
                continue
            name = str(getattr(board, "name", "") or f"Board {index + 1}")
            parsed.append((board_id, name))
        blocked = self._list.blockSignals(True)
        self._list.clear()
        active = str(active_board_id or "")
        current_item: QListWidgetItem | None = None
        for board_id, name in parsed:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, board_id)
            item.setData(_BOARD_CURRENT_ROLE, board_id == active)
            item.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsDragEnabled
                | Qt.ItemIsDropEnabled
            )
            item.setToolTip(name)
            self._list.addItem(item)
            if board_id == active:
                current_item = item
        if current_item is not None:
            self._list.setCurrentItem(current_item)
        self._list.blockSignals(blocked)
        intended = self._list_content_height()
        self._list.setFixedHeight(intended)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.verticalScrollBar().setValue(0)
        self.setMaximumHeight(board_popover_height(max(1, len(parsed))))
        self.updateGeometry()
        self._fit_list_to_contents()


class GlobalIsland(QFrame):
    """Right-top Board-wide display, export and presentation controls."""

    display_requested = pyqtSignal()
    export_requested = pyqtSignal()
    presentation_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewGlobalIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setProperty("surface", "island")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._display = _icon_button(
            self,
            object_name="ultraViewGlobalDisplayButton",
            icon=Icons.ultraview_display(UV_MUTED),
            tooltip="显示标题和来源",
            accessible_name="显示标题和来源",
        )
        self._display.setCheckable(True)
        self._display.clicked.connect(self.display_requested)
        layout.addWidget(self._display, 0)
        self._export = _icon_button(
            self,
            object_name="ultraViewGlobalExportButton",
            icon=Icons.export(UV_MUTED),
            tooltip="复制或导出 Board",
            accessible_name="复制或导出 Board",
        )
        self._export.setCheckable(True)
        self._export.clicked.connect(self.export_requested)
        layout.addWidget(self._export, 0)
        self._presentation = _icon_button(
            self,
            object_name="ultraViewGlobalPresentationButton",
            icon=Icons.ultraview_presentation(UV_MUTED),
            tooltip="进入演示",
            accessible_name="进入演示",
        )
        self._presentation.setCheckable(True)
        self._presentation.toggled.connect(self._on_presentation_toggled)
        layout.addWidget(self._presentation, 0)

    def display_button(self) -> QToolButton:
        return self._display

    def export_button(self) -> QToolButton:
        return self._export

    def presentation_button(self) -> QToolButton:
        return self._presentation

    def set_presentation_checked(self, checked: bool) -> None:
        blocked = self._presentation.blockSignals(True)
        self._presentation.setChecked(bool(checked))
        self._presentation.blockSignals(blocked)
        self._sync_presentation(bool(checked))

    def set_edit_visible(self, visible: bool) -> None:
        self._display.setVisible(bool(visible))
        self._export.setVisible(bool(visible))
        self.updateGeometry()

    def set_active_panel(self, panel_id: str | None) -> None:
        key = str(panel_id or "")
        for name, button in (("display", self._display), ("export", self._export)):
            is_open = name == key
            blocked = button.blockSignals(True)
            button.setChecked(is_open)
            button.blockSignals(blocked)
            _set_flag(button, "panelOpen", is_open)
            _set_flag(button, "modeActive", False)
            _set_flag(button, "active", False)
        self._display.setIcon(
            Icons.ultraview_display(
                UV_PRESENTATION_ICON if key == "display" else UV_MUTED
            )
        )
        self._export.setIcon(
            Icons.export(UV_PRESENTATION_ICON if key == "export" else UV_MUTED)
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        visible = [
            button
            for button in (self._display, self._export, self._presentation)
            if not button.isHidden()
        ]
        count = max(1, len(visible))
        return QSize(
            min(GLOBAL_ISLAND_WIDTH, 8 + count * 32 + max(0, count - 1) * 2),
            ISLAND_HEIGHT,
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def _on_presentation_toggled(self, checked: bool) -> None:
        self._sync_presentation(bool(checked))
        self.presentation_toggled.emit(bool(checked))

    def _sync_presentation(self, checked: bool) -> None:
        _set_flag(self._presentation, "active", checked)
        _set_flag(self, "presentation", checked)
        role = "presentationExit" if checked else "icon"
        if self._presentation.property("role") != role:
            self._presentation.setProperty("role", role)
            _repolish(self._presentation)
        self._presentation.setIcon(
            Icons.ultraview_presentation(
                UV_PRESENTATION_ICON if checked else UV_MUTED
            )
        )
        if not checked:
            self._presentation.setDown(False)
        self._presentation.setToolTip("退出演示" if checked else "进入演示")
        self._presentation.setAccessibleName("退出演示" if checked else "进入演示")


class NavigationIsland(QFrame):
    """Right-bottom navigation actions; zoom state remains page-owned."""

    overview_requested = pyqtSignal()
    zoom_out_requested = pyqtSignal()
    zoom_in_requested = pyqtSignal()
    zoom_fit_requested = pyqtSignal()
    zoom_reset_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewNavigationIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setProperty("surface", "island")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._overview = _icon_button(
            self,
            object_name="ultraViewNavOverviewButton",
            icon=Icons.ultraview_overview(UV_MUTED),
            tooltip="查看整板概览",
            accessible_name="查看整板概览",
        )
        self._overview.clicked.connect(self.overview_requested)
        layout.addWidget(self._overview, 0)
        self._zoom_out = _icon_button(
            self,
            object_name="ultraViewNavZoomOutButton",
            icon=Icons.ultraview_zoom_out(UV_MUTED),
            tooltip="缩小画布",
            accessible_name="缩小画布",
        )
        self._zoom_out.clicked.connect(self.zoom_out_requested)
        layout.addWidget(self._zoom_out, 0)
        self._zoom_label = QLabel("100%", self)
        self._zoom_label.setObjectName("ultraViewNavZoomLabel")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setMinimumWidth(42)
        self._zoom_label.setAccessibleName("当前画布缩放：100%")
        zoom_font = QFont(self._zoom_label.font())
        zoom_font.setStyleHint(QFont.Monospace)
        zoom_font.setFixedPitch(True)
        self._zoom_label.setFont(zoom_font)
        layout.addWidget(self._zoom_label, 0)
        self._zoom_in = _icon_button(
            self,
            object_name="ultraViewNavZoomInButton",
            icon=Icons.ultraview_zoom_in(UV_MUTED),
            tooltip="放大画布",
            accessible_name="放大画布",
        )
        self._zoom_in.clicked.connect(self.zoom_in_requested)
        layout.addWidget(self._zoom_in, 0)
        self._fit = _icon_button(
            self,
            object_name="ultraViewNavFitButton",
            icon=Icons.ultraview_fit(UV_MUTED),
            tooltip="适应内容：图面填满画布，最高 300%",
            accessible_name="适应内容：图面填满画布，最高 300%",
        )
        self._fit.clicked.connect(self.zoom_fit_requested)
        layout.addWidget(self._fit, 0)
        self._reset = _icon_button(
            self,
            object_name="ultraViewNavResetButton",
            icon=Icons.ultraview_reset_zoom(UV_MUTED),
            tooltip="恢复 100% 缩放",
            accessible_name="恢复 100% 缩放",
        )
        self._reset.clicked.connect(self.zoom_reset_requested)
        layout.addWidget(self._reset, 0)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(*DEFAULT_NAVIGATION_ISLAND_SIZE)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def zoom_label(self) -> QLabel:
        return self._zoom_label

    def button(self, action: str) -> QToolButton | None:
        return {
            "overview": self._overview,
            "zoom_out": self._zoom_out,
            "zoom_in": self._zoom_in,
            "fit": self._fit,
            "reset": self._reset,
        }.get(str(action))

    def set_zoom_percent(self, percent: int) -> None:
        value = int(percent)
        self._zoom_label.setText(f"{value}%")
        self._zoom_label.setAccessibleName(f"当前画布缩放：{value}%")
        self._zoom_label.setToolTip(f"当前画布缩放：{value}%")


class StatusIsland(QFrame):
    """Compact read-only / help status without a permanent full-width bar."""

    quickref_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewStatusIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setProperty("surface", "island")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 8, 4)
        layout.setSpacing(4)
        self._quickref = _icon_button(
            self,
            object_name="ultraViewStatusHelpButton",
            icon=Icons.ultraview_help(UV_MUTED),
            tooltip="操作速查",
            accessible_name="打开 UltraView 操作速查",
        )
        self._quickref.clicked.connect(self.quickref_requested)
        layout.addWidget(self._quickref, 0)
        self._message = _ElidedLabel("只读预览 · 不计算", self)
        self._message.setObjectName("ultraViewStatusMessage")
        self._message.setMinimumWidth(96)
        layout.addWidget(self._message, 1)
        self.set_status("只读预览 · 不计算")

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = self._message.fontMetrics()
        text_width = min(280, max(96, metrics.horizontalAdvance(self._message.full_text()) + 12))
        return QSize(
            min(STATUS_ISLAND_WIDTH, 4 + 32 + 4 + text_width + 8),
            ISLAND_HEIGHT,
        )

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(140, ISLAND_HEIGHT)

    def help_button(self) -> QToolButton:
        return self._quickref

    def message_label(self) -> QLabel:
        return self._message

    def set_status(self, text: str, *, level: str = "info") -> None:
        value = str(text or "")
        self._message.set_full_text(value)
        self.setToolTip(value)
        self.setAccessibleName(value)
        self.setProperty("statusLevel", str(level or "info"))
        _repolish(self)
        _repolish(self._message)


class CardContextIsland(QFrame):
    """One selected-card action strip; it holds a ref, never a card QWidget."""

    open_source_requested = pyqtSignal(str, str)
    sync_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    copy_image_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    more_requested = pyqtSignal(str, str)
    rebind_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, str)
    fit_requested = pyqtSignal(str, str)

    _FIT_TOOLTIP = "按原图比例调整卡片"
    _FIT_DISABLED_TOOLTIP = "模板布局的尺寸由模板决定，切到自由网格后可用"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCardContextIsland")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(ISLAND_HEIGHT)
        self.setProperty("surface", "island")
        self.setProperty("orphaned", "false")
        self._section = ""
        self._view_id = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._buttons: dict[str, QToolButton] = {}
        self._orphaned = False
        self._stale = False
        self._fit_enabled = False
        for action, object_name, icon, tooltip in (
            ("open", "ultraViewContextOpenButton", qta.icon("fa5s.external-link-alt", color=UV_MUTED), "打开原 View"),
            ("sync", "ultraViewContextSyncButton", qta.icon("fa5s.sync-alt", color=UV_MUTED), "同步到最新预览"),
            ("focus", "ultraViewContextFocusButton", qta.icon("fa5s.expand", color=UV_MUTED), "临时放大预览"),
            ("fit", "ultraViewContextFitButton", qta.icon("fa5s.vector-square", color=UV_MUTED), self._FIT_TOOLTIP),
            ("more", "ultraViewContextMoreButton", qta.icon("fa5s.ellipsis-v", color=UV_MUTED), "更多卡片操作"),
        ):
            button = _icon_button(
                self,
                object_name=object_name,
                icon=icon,
                tooltip=tooltip,
                accessible_name=tooltip,
            )
            button.setProperty("contextAction", action)
            button.clicked.connect(self._on_action_clicked)
            if action == "sync":
                button.hide()
            self._buttons[action] = button
            layout.addWidget(button, 0)
        self.set_fit_enabled(False)
        self.hide()

    def ref(self) -> tuple[str, str] | None:
        if not self._section or not self._view_id:
            return None
        return self._section, self._view_id

    def button(self, action: str) -> QToolButton | None:
        return self._buttons.get(str(action))

    def show_for(
        self,
        section: str,
        view_id: str,
        *,
        orphaned: bool = False,
        stale: bool = False,
    ) -> None:
        self._section = str(section or "")
        self._view_id = str(view_id or "")
        self.setProperty("section", self._section)
        self.setProperty("viewId", self._view_id)
        self.set_orphaned(orphaned)
        self.set_stale(bool(stale) and not bool(orphaned))
        if self.ref() is None:
            self.hide()
            return
        self.setAccessibleName(f"当前卡片操作：{self._section} {self._view_id}")
        self.show()
        self.raise_()

    def clear_ref(self) -> None:
        self._section = ""
        self._view_id = ""
        self.setProperty("section", "")
        self.setProperty("viewId", "")
        self.hide()

    def set_orphaned(self, orphaned: bool) -> None:
        is_orphaned = bool(orphaned)
        self._orphaned = is_orphaned
        _set_flag(self, "orphaned", is_orphaned)
        if is_orphaned:
            self._buttons["sync"].hide()

    def set_stale(self, stale: bool) -> None:
        self._stale = bool(stale)
        self._buttons["sync"].setVisible(self._stale and not self._orphaned)

    def set_fit_enabled(self, enabled: bool) -> None:
        self._fit_enabled = bool(enabled)
        button = self._buttons.get("fit")
        if button is None:
            return
        button.setEnabled(self._fit_enabled)
        tip = self._FIT_TOOLTIP if self._fit_enabled else self._FIT_DISABLED_TOOLTIP
        button.setToolTip(tip)
        button.setAccessibleName(tip)

    def make_overflow_menu(self, parent: QWidget | None = None) -> QMenu:
        menu = QMenu(parent or self)
        menu.setObjectName("ultraViewCardContextMoreMenu")
        # Every open of the "more" overflow re-creates this menu (callers may
        # also append extra actions/submenus before exec_-ing it); without
        # this it stays parented under the long-lived card-context widget
        # forever, leaking one QMenu (and its children) per open.
        menu.setAttribute(Qt.WA_DeleteOnClose)
        apply_rounded_menu_chrome(menu)
        for action, label in (
            ("copy", "复制本卡图像"),
            ("unplaced", "移到未放置"),
            ("rebind", "重新绑定"),
            ("remove", "从总览移除"),
        ):
            if action == "rebind" and not self._orphaned:
                continue
            item = menu.addAction(label)
            item.setProperty("overflowAction", action)
            item.triggered.connect(self._on_overflow_triggered)
        return menu

    def _on_overflow_triggered(self, _checked: bool = False) -> None:
        sender = self.sender()
        ref = self.ref()
        if sender is None or ref is None:
            return
        action = str(sender.property("overflowAction") or "")
        section, view_id = ref
        emitters = {
            "copy": self.copy_image_requested,
            "unplaced": self.move_to_unplaced_requested,
            "rebind": self.rebind_requested,
            "remove": self.remove_requested,
        }
        signal = emitters.get(action)
        if signal is not None:
            signal.emit(section, view_id)

    def _on_action_clicked(self) -> None:
        sender = self.sender()
        if not isinstance(sender, QToolButton):
            return
        ref = self.ref()
        if ref is None:
            return
        action = str(sender.property("contextAction") or "")
        section, view_id = ref
        emitters = {
            "open": self.open_source_requested,
            "sync": self.sync_requested,
            "focus": self.focus_requested,
            "fit": self.fit_requested,
            "more": self.more_requested,
        }
        signal = emitters.get(action)
        if signal is not None:
            signal.emit(section, view_id)


class LayoutPicker(QFrame):
    """Eight template previews; Page owns confirmation and free-grid history."""

    layout_id_chosen = pyqtSignal(str)

    def __init__(
        self,
        labels: Mapping[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewLayoutPopover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._labels = dict(labels)
        self._buttons: dict[str, QToolButton] = {}
        self._view_count = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)
        heading = QLabel("布局", self)
        heading.setObjectName("ultraViewLayoutPopoverTitle")
        heading.setProperty("role", "popoverTitle")
        root.addWidget(heading, 0)
        self._intro = QLabel(self)
        self._intro.setObjectName("ultraViewLayoutPopoverIntro")
        self._intro.setWordWrap(True)
        self._intro.setText("选择模板 · 当前 0 个 View；自由网格可由左侧独立开关进入")
        root.addWidget(self._intro, 0)
        grid_host = QWidget(self)
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (layout_id, label) in enumerate(self._labels.items()):
            button = QToolButton(self)
            button.setObjectName(f"ultraViewLayoutThumb_{layout_id}")
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(layout_thumbnail_icon(layout_id))
            button.setIconSize(_LAYOUT_THUMB_SIZE)
            button.setToolTip(str(label))
            button.setAccessibleName(str(label))
            button.setProperty("layoutId", layout_id)
            button.setProperty("role", "layoutThumb")
            button.setMinimumSize(_LAYOUT_THUMB_CELL)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            button.clicked.connect(self._on_thumb_clicked)
            self._apply_thumb_caption(button, layout_id, current=False)
            self._group.addButton(button)
            self._buttons[layout_id] = button
            grid.addWidget(button, index // 2, index % 2)
        scroll = QScrollArea(self)
        scroll.setObjectName("ultraViewLayoutPopoverScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        scroll.setWidget(grid_host)
        root.addWidget(scroll, 1)

    def thumb_button(self, layout_id: str) -> QToolButton | None:
        return self._buttons.get(str(layout_id))

    def intro_label(self) -> QLabel:
        return self._intro

    def sizeHint(self) -> QSize:  # noqa: N802
        cell_w, cell_h = _LAYOUT_THUMB_CELL.width(), _LAYOUT_THUMB_CELL.height()
        return QSize(12 + cell_w * 2 + 8 + 12, 10 + 22 + 8 + 36 + 8 + cell_h * 4 + 8 * 3 + 12)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        cell_w = _LAYOUT_THUMB_CELL.width()
        return QSize(12 + cell_w * 2 + 8 + 12, 160)

    def set_current(self, layout_id: str, *, free_grid: bool, view_count: int | None = None) -> None:
        if view_count is not None:
            try:
                self._view_count = max(0, int(view_count))
            except (TypeError, ValueError):
                self._view_count = 0
        is_free_grid = bool(free_grid)
        self._group.setExclusive(not is_free_grid)
        if is_free_grid:
            self._intro.setText("当前为自由网格；选择任一模板即可切回")
        else:
            self._intro.setText(
                f"选择模板 · 当前 {self._view_count} 个 View；自由网格可由左侧独立开关进入"
            )
        for candidate, button in self._buttons.items():
            checked = not is_free_grid and candidate == layout_id
            blocked = button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(blocked)
            self._apply_thumb_caption(button, candidate, current=checked)

    def _capacity_label(self, layout_id: str) -> str:
        slots = LAYOUT_SLOTS.get(str(layout_id), ())
        return f"{len(slots)} 格" if slots else ""

    def _apply_thumb_caption(self, button: QToolButton, layout_id: str, *, current: bool) -> None:
        label = str(self._labels.get(layout_id, layout_id))
        suffix = "当前" if current else self._capacity_label(layout_id)
        button.setText(f"{label}\n{suffix}" if suffix else label)

    def _on_thumb_clicked(self) -> None:
        button = self.sender()
        if not isinstance(button, QToolButton):
            return
        layout_id = str(button.property("layoutId") or "")
        if layout_id:
            self.layout_id_chosen.emit(layout_id)
