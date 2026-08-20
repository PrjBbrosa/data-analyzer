"""Author flyouts and selection toolbar. Chrome.py re-exports public names."""
from __future__ import annotations

from collections.abc import Sequence

import qtawesome as qta
from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui_kit.popup_shell import apply_popup_shell

from .author_render import shape_path
from .author_style import (
    DEFAULT_THEME,
    STICKY_PALETTE_TOKENS,
    ink_color,
    pen_color,
    sticky_colors,
)
from .author_selection import (
    FORBIDDEN_TOOLBAR_WORDS,
    SelectionCapabilities,
    ToolbarControl,
)
from .author_tools import (
    CLOSED_SHAPE_TYPES,
    CONNECTOR_TYPES,
    DEFAULT_DRAW_PRESETS,
    DEFAULT_DRAW_SUBTOOL,
    DRAW_ERASER,
    DRAW_INK_SUBTOOLS,
    DRAW_LASSO,
    DRAW_SUBTOOLS,
    DrawPreset,
    is_draw_ink_subtool,
    normalize_draw_subtool,
)

_FLYOUT_RADIUS = 16
_TOOLBAR_RADIUS = 12
_SURFACE = QColor("#FFFFFF")
_LINE = QColor(32, 48, 56, 40)
_SELECTION_BLUE = "#4262FF"
_INK = QColor("#183039")
_STICKY_FLYOUT_MIN_WIDTH = 260
_DEFAULT_FLYOUT_MIN_WIDTH = 248
_STICKY_SWATCH = 50
_TOOLBAR_HEIGHT = 48
_CONTROL_SIZE = 38
_DRAW_COLORS = ("ink", "blue", "red", "yellow", "green", "pink", "teal", "purple")
_PEN_WIDTHS = (2, 4, 8)
_HIGHLIGHTER_WIDTHS = (8, 12, 16)


class ToolFlyoutSurface(QFrame):
    """Non-modal rounded QFrame flyout. ``popup()`` matches the old QMenu seam."""

    min_width = 0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        apply_popup_shell(self)
        self.setObjectName("ultraViewToolFlyoutSurface")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        if self.min_width > 0:
            self.setMinimumWidth(int(self.min_width))
        self._inner = QFrame(self)
        self._inner.setObjectName("ultraViewToolFlyoutInner")
        self._inner.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)
        inner_root = QVBoxLayout(self._inner)
        inner_root.setContentsMargins(0, 0, 0, 0)
        inner_root.setSpacing(0)
        self._scroll = QScrollArea(self._inner)
        self._scroll.setObjectName("ultraViewToolFlyoutScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: 0; }")
        self._content = QWidget(self._scroll)
        self._content.setObjectName("ultraViewToolFlyoutContent")
        self._body = QVBoxLayout(self._content)
        self._body.setContentsMargins(12, 12, 12, 12)
        self._body.setSpacing(8)
        self._scroll.setWidget(self._content)
        inner_root.addWidget(self._scroll)

    def inner_layout(self) -> QVBoxLayout:
        return self._body

    def popup(self, pos: QPoint) -> None:
        self.setMaximumHeight(16777215)
        self.adjustSize()
        hint = self.sizeHint()
        width = max(hint.width(), int(self.min_width or 0))
        height = hint.height()
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
        max_h = max(160, avail.bottom() - pos.y() - 8)
        if height > max_h:
            self.setMaximumHeight(max_h)
            height = max_h
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        else:
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left = min(max(avail.left() + 8, pos.x()), avail.right() - width - 8)
        top = min(max(avail.top() + 8, pos.y()), avail.bottom() - height - 8)
        self.setGeometry(left, top, width, height)
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect().adjusted(0, 0, -1, -1)), _FLYOUT_RADIUS, _FLYOUT_RADIUS)
        painter.fillPath(path, _SURFACE)
        painter.setPen(_LINE)
        painter.drawPath(path)


class StickyPopover(ToolFlyoutSurface):
    """4×4 Sticky palette flyout. Emits palette/stack intents only."""

    min_width = _STICKY_FLYOUT_MIN_WIDTH
    palette_selected = pyqtSignal(str)
    stack_requested = pyqtSignal(str)
    pin_requested = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewStickyPopover")
        self._selected_palette = STICKY_PALETTE_TOKENS[0]
        self._palette_buttons: dict[str, QToolButton] = {}
        self._pinned = False
        self._build_palette()

    def palette_tokens(self) -> tuple[str, ...]:
        return STICKY_PALETTE_TOKENS

    def palette_buttons(self) -> tuple[QToolButton, ...]:
        return tuple(self._palette_buttons[token] for token in STICKY_PALETTE_TOKENS)

    def selected_palette(self) -> str:
        return self._selected_palette

    def choose_palette(self, token: str, *, emit: bool = True) -> None:
        checked = str(token)
        if checked not in self._palette_buttons:
            raise ValueError(f"unknown Sticky palette: {checked}")
        self._selected_palette = checked
        for candidate, button in self._palette_buttons.items():
            button.setChecked(candidate == checked)
        if emit:
            self.palette_selected.emit(checked)

    def request_stack(self) -> None:
        self.stack_requested.emit(self._selected_palette)

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = bool(pinned)
        self._stack.setChecked(self._pinned)

    def _build_palette(self) -> None:
        host = QWidget(self._content)
        host.setObjectName("ultraViewStickyPaletteGrid")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, token in enumerate(STICKY_PALETTE_TOKENS):
            fill, border, _foreground = sticky_colors(token, DEFAULT_THEME)
            button = QToolButton(host)
            button.setObjectName(f"ultraViewStickyPalette{token.title()}Button")
            button.setProperty("stickyPalette", token)
            button.setCheckable(True)
            button.setAutoRaise(False)
            button.setFixedSize(_STICKY_SWATCH, _STICKY_SWATCH)
            button.setToolTip(f"便签颜色：{token}")
            button.setAccessibleName(f"便签颜色：{token}")
            button.setStyleSheet(
                "QToolButton {"
                f"background-color: rgb({fill[0]}, {fill[1]}, {fill[2]});"
                "border-width: 1px; border-style: solid;"
                f"border-color: rgb({border[0]}, {border[1]}, {border[2]});"
                "border-radius: 8px; }"
                "QToolButton:checked { border-width: 2px; border-color: #4262FF; }"
            )
            button.clicked.connect(self._on_palette_clicked)
            self._palette_buttons[token] = button
            grid.addWidget(button, index // 4, index % 4)
        self._palette_buttons[self._selected_palette].setChecked(True)
        self.inner_layout().addWidget(host)
        self._stack = QToolButton(self._content)
        self._stack.setObjectName("ultraViewStickyStackButton")
        self._stack.setText("Stack")
        self._stack.setIcon(qta.icon("fa5s.layer-group", color="#183039"))
        self._stack.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._stack.setCheckable(True)
        self._stack.setFixedHeight(38)
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._stack.setToolTip("连续放置便签")
        self._stack.setAccessibleName("Stack 连续放置")
        self._stack.clicked.connect(self._on_stack_clicked)
        self.inner_layout().addWidget(self._stack)
        self._pin = self._stack

    def _on_palette_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_palette(str(sender.property("stickyPalette") or ""))
            self.close()

    def _on_stack_clicked(self) -> None:
        self._pinned = True
        self._stack.setChecked(True)
        self.pin_requested.emit(True)
        self.stack_requested.emit(self._selected_palette)
        self.close()

    def _on_pin_clicked(self) -> None:
        self._on_stack_clicked()


_SHAPE_CELL_LABELS = {
    "rectangle": ("矩形", "Rectangle"),
    "rounded_rectangle": ("圆角矩形", "Rounded Rectangle"),
    "oval": ("椭圆", "Oval"),
    "rhombus": ("菱形", "Diamond"),
    "triangle": ("三角形", "Triangle"),
}
_SHAPE_CATALOG = (
    ("line", "直线", "L", "connector"),
    ("arrow", "箭头", "", "connector"),
    ("elbow_arrow", "折线", "", "connector"),
    ("rectangle", "矩形", "R", "shape"),
    ("rounded_rectangle", "圆角矩形", "", "shape"),
    ("oval", "椭圆", "O", "shape"),
    ("rhombus", "菱形", "", "shape"),
    ("triangle", "三角", "", "shape"),
)


class _ShapeCellButton(QToolButton):
    """40×40 path preview. Tooltip is the Chinese name plus the English type."""

    def __init__(self, shape: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shape = str(shape)
        zh, en = _SHAPE_CELL_LABELS.get(self._shape, (self._shape, self._shape))
        self.setObjectName(f"ultraViewShapeCell{self._shape.title().replace('_', '')}Button")
        self.setProperty("shapeType", self._shape)
        self.setCheckable(True)
        self.setFixedSize(40, 40)
        self.setToolTip(f"{zh} · {en}")
        self.setAccessibleName(zh)
        self.setStyleSheet(
            "QToolButton {"
            "background-color: #FFFFFF;"
            "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
            "border-radius: 8px; }"
            "QToolButton:checked { border-width: 2px; border-color: #4262FF; }"
        )

    def shape_type(self) -> str:
        return self._shape

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        inset = QRectF(self.rect()).adjusted(8.0, 8.0, -8.0, -8.0)
        path = shape_path(self._shape, inset, corner_radius=8 if self._shape == "rounded_rectangle" else 0)
        if path.isEmpty():
            return
        painter.setPen(QPen(QColor(24, 48, 57), 1.4))
        painter.setBrush(QColor(66, 98, 255, 28))
        painter.drawPath(path)


class _CatalogRow(QToolButton):
    """One icon + short name + optional shortcut row for Shapes & Connectors."""

    def __init__(
        self,
        kind: str,
        family: str,
        title: str,
        shortcut: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = str(kind)
        self._family = str(family)
        self.setObjectName(f"ultraViewShapeCatalog{kind.title().replace('_', '')}Row")
        self.setProperty("catalogKind", self._kind)
        self.setProperty("catalogFamily", self._family)
        self.setCheckable(True)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setText(title)
        if shortcut:
            self.setToolTip(f"{title} ({shortcut})")
        else:
            self.setToolTip(title)
        self.setAccessibleName(title)
        self.setShortcutLabel(shortcut)
        self.setStyleSheet(
            "QToolButton {"
            "background-color: transparent; border: 0; border-radius: 8px;"
            "padding-left: 34px; text-align: left; color: #183039; }"
            "QToolButton:checked { background-color: #EEF1FF; color: #4262FF; }"
            "QToolButton:hover { background-color: #F3F5F6; }"
        )

    def setShortcutLabel(self, shortcut: str) -> None:  # noqa: N802
        self._shortcut = str(shortcut or "")

    def catalog_kind(self) -> str:
        return self._kind

    def catalog_family(self) -> str:
        return self._family

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        icon_box = QRectF(8.0, 6.0, 24.0, 24.0)
        painter.setPen(QPen(_INK, 1.6))
        painter.setBrush(QColor(66, 98, 255, 28) if self._family == "shape" else Qt.NoBrush)
        if self._family == "shape":
            path = shape_path(
                self._kind,
                icon_box.adjusted(2, 2, -2, -2),
                corner_radius=6 if self._kind == "rounded_rectangle" else 0,
            )
            if not path.isEmpty():
                painter.drawPath(path)
        else:
            inset = icon_box.adjusted(2.0, 8.0, -2.0, -8.0)
            path = QPainterPath()
            if self._kind == "elbow_arrow":
                path.moveTo(inset.left(), inset.bottom())
                path.lineTo(inset.center().x(), inset.bottom())
                path.lineTo(inset.center().x(), inset.top())
                path.lineTo(inset.right(), inset.top())
            else:
                path.moveTo(inset.left(), inset.center().y())
                path.lineTo(inset.right(), inset.center().y())
            painter.drawPath(path)
            if self._kind in {"arrow", "elbow_arrow"}:
                tip = path.currentPosition()
                painter.setPen(Qt.NoPen)
                painter.setBrush(_INK)
                painter.drawPolygon(QPolygonF([
                    tip,
                    QPointF(tip.x() - 6.0, tip.y() - 3.5),
                    QPointF(tip.x() - 6.0, tip.y() + 3.5),
                ]))
        if self._shortcut:
            painter.setPen(QColor("#66787E"))
            painter.drawText(
                self.rect().adjusted(0, 0, -10, 0),
                Qt.AlignVCenter | Qt.AlignRight,
                self._shortcut,
            )


class ShapePopover(ToolFlyoutSurface):
    """Shapes and connectors in one catalog. Dispatch stays typed."""

    min_width = _DEFAULT_FLYOUT_MIN_WIDTH
    shape_selected = pyqtSignal(str)
    connector_selected = pyqtSignal(str)
    pin_requested = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewShapePopover")
        self._selected = CLOSED_SHAPE_TYPES[0]
        self._family = "shape"
        self._cells: dict[str, _CatalogRow] = {}
        self._pinned = False
        self._build_cells()

    def shape_types(self) -> tuple[str, ...]:
        return CLOSED_SHAPE_TYPES

    def connector_types(self) -> tuple[str, ...]:
        return CONNECTOR_TYPES

    def cell_buttons(self) -> tuple[QToolButton, ...]:
        return tuple(self._cells[kind] for kind, *_rest in _SHAPE_CATALOG)

    def selected_shape(self) -> str:
        return self._selected

    def choose_shape(self, shape: str) -> None:
        checked = str(shape)
        if checked not in CLOSED_SHAPE_TYPES:
            raise ValueError(f"unknown author shape: {checked}")
        self._selected = checked
        self._family = "shape"
        self._sync_checked()
        self.shape_selected.emit(checked)

    def choose_connector(self, kind: str) -> None:
        checked = str(kind)
        if checked not in CONNECTOR_TYPES:
            raise ValueError(f"unknown connector type: {checked}")
        self._selected = checked
        self._family = "connector"
        self._sync_checked()
        self.connector_selected.emit(checked)

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = bool(pinned)

    def _sync_checked(self) -> None:
        for kind, button in self._cells.items():
            button.setChecked(kind == self._selected)

    def _build_cells(self) -> None:
        host = QWidget(self._content)
        host.setObjectName("ultraViewShapeCellGrid")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for kind, title, shortcut, family in _SHAPE_CATALOG:
            button = _CatalogRow(kind, family, title, shortcut, host)
            button.clicked.connect(self._on_cell_clicked)
            self._cells[kind] = button
            layout.addWidget(button)
        self._sync_checked()
        self.inner_layout().addWidget(host)
        self._pin = QToolButton(self._content)
        self._pin.hide()

    def _on_cell_clicked(self) -> None:
        sender = self.sender()
        if not isinstance(sender, _CatalogRow):
            return
        if sender.catalog_family() == "connector":
            self.choose_connector(sender.catalog_kind())
        else:
            self.choose_shape(sender.catalog_kind())
        self.close()

    def _on_pin_clicked(self) -> None:
        self._pinned = not self._pinned
        self.pin_requested.emit(self._pinned)


_CONNECTOR_CELL_LABELS = {
    "line": ("直线", "Straight Line"),
    "arrow": ("箭头", "Arrow"),
    "elbow_arrow": ("折线箭头", "Elbow Arrow"),
}


class _ConnectorCellButton(QToolButton):
    """40×40 path preview for Straight / Arrow / Elbow Arrow."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = str(kind)
        zh, en = _CONNECTOR_CELL_LABELS.get(self._kind, (self._kind, self._kind))
        self.setObjectName(f"ultraViewConnectorCell{self._kind.title().replace('_', '')}Button")
        self.setProperty("connectorType", self._kind)
        self.setCheckable(True)
        self.setFixedSize(40, 40)
        self.setToolTip(f"{zh} · {en}")
        self.setAccessibleName(zh)
        self.setStyleSheet(
            "QToolButton {"
            "background-color: #FFFFFF;"
            "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
            "border-radius: 8px; }"
            "QToolButton:checked { border-width: 2px; border-color: #4262FF; }"
        )

    def connector_type(self) -> str:
        return self._kind

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        inset = QRectF(self.rect()).adjusted(8.0, 18.0, -8.0, -18.0)
        path = QPainterPath()
        if self._kind == "elbow_arrow":
            path.moveTo(inset.left(), inset.center().y())
            path.lineTo(inset.center().x(), inset.center().y())
            path.lineTo(inset.center().x(), inset.top())
            path.lineTo(inset.right(), inset.top())
        else:
            path.moveTo(inset.left(), inset.center().y())
            path.lineTo(inset.right(), inset.center().y())
        painter.setPen(QPen(QColor(24, 48, 57), 1.4))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        if self._kind in {"arrow", "elbow_arrow"}:
            tip = path.currentPosition()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(24, 48, 57))
            painter.drawPolygon(QPolygonF([
                tip,
                QPointF(tip.x() - 6.0, tip.y() - 3.5),
                QPointF(tip.x() - 6.0, tip.y() + 3.5),
            ]))


class ConnectorPopover(ToolFlyoutSurface):
    """3-cell connector flyout. Closed shapes stay out of this surface."""

    min_width = _DEFAULT_FLYOUT_MIN_WIDTH
    connector_selected = pyqtSignal(str)
    pin_requested = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewConnectorPopover")
        self._selected = CONNECTOR_TYPES[1]
        self._cells: dict[str, _ConnectorCellButton] = {}
        self._pinned = False
        self._build_cells()

    def connector_types(self) -> tuple[str, ...]:
        return CONNECTOR_TYPES

    def cell_buttons(self) -> tuple[QToolButton, ...]:
        return tuple(self._cells[kind] for kind in CONNECTOR_TYPES)

    def selected_connector(self) -> str:
        return self._selected

    def choose_connector(self, kind: str) -> None:
        checked = str(kind)
        if checked not in self._cells:
            raise ValueError(f"unknown connector type: {checked}")
        self._selected = checked
        for candidate, button in self._cells.items():
            button.setChecked(candidate == checked)
        self.connector_selected.emit(checked)

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = bool(pinned)
        self._pin.setChecked(self._pinned)

    def _build_cells(self) -> None:
        host = QWidget(self._content)
        host.setObjectName("ultraViewConnectorCellGrid")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, kind in enumerate(CONNECTOR_TYPES):
            button = _ConnectorCellButton(kind, host)
            button.clicked.connect(self._on_cell_clicked)
            self._cells[kind] = button
            grid.addWidget(button, 0, index)
        self._cells[self._selected].setChecked(True)
        self.inner_layout().addWidget(host)
        self._pin = QToolButton(self._content)
        self._pin.setObjectName("ultraViewConnectorPinButton")
        self._pin.hide()

    def _on_cell_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_connector(str(sender.property("connectorType") or ""))
            self.close()

    def _on_pin_clicked(self) -> None:
        self._pinned = self._pin.isChecked()
        self.pin_requested.emit(self._pinned)


_DRAW_ROW_LABELS = {
    "pen": ("钢笔", "Pen"),
    "highlighter": ("荧光笔", "Highlighter"),
    DRAW_ERASER: ("橡皮擦", "Eraser"),
    DRAW_LASSO: ("套索", "Lasso"),
}
_ERASER_TOOLTIP = "橡皮擦 · 整笔擦除"
_LASSO_TOOLTIP = "套索 · 按对象中心选择"


class _DrawPresetButton(QToolButton):
    """40×40 chip with a real color/width stroke preview."""

    def __init__(self, tool: str, preset: DrawPreset, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool = str(tool)
        self._preset = preset
        self._index = int(index)
        zh, en = _DRAW_ROW_LABELS.get(self._tool, (self._tool, self._tool))
        self.setObjectName(f"ultraViewDrawPreset{self._tool.title()}{self._index}Button")
        self.setProperty("drawTool", self._tool)
        self.setProperty("presetIndex", self._index)
        self.setCheckable(True)
        self.setFixedSize(40, 40)
        self.setToolTip(f"{zh} · {preset.palette} · {preset.width_px_100}px")
        self.setAccessibleName(f"{zh}预设 {self._index + 1}")
        self.setStyleSheet(
            "QToolButton {"
            "background-color: #FFFFFF;"
            "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
            "border-radius: 8px; }"
            "QToolButton:checked { border-width: 2px; border-color: #4262FF; }"
        )

    def draw_tool(self) -> str:
        return self._tool

    def preset_index(self) -> int:
        return self._index

    def preset(self) -> DrawPreset:
        return self._preset

    def set_preset(self, preset: DrawPreset) -> None:
        self._preset = preset
        zh, _en = _DRAW_ROW_LABELS.get(self._tool, (self._tool, self._tool))
        self.setToolTip(f"{zh} · {preset.palette} · {preset.width_px_100}px")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = QColor(*pen_color(self._preset.palette, tool=self._tool, theme=DEFAULT_THEME))
        pen = QPen(color)
        pen.setWidthF(max(2.0, min(10.0, float(self._preset.width_px_100))))
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        mid = float(self.height()) / 2.0
        painter.drawLine(QPointF(8.0, mid), QPointF(float(self.width()) - 8.0, mid))


class _DrawSessionButton(QToolButton):
    """40×40 Eraser/Lasso cell. Tooltip states whole-stroke erase; no precision."""

    def __init__(self, tool: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tool = str(tool)
        zh, en = _DRAW_ROW_LABELS.get(self._tool, (self._tool, self._tool))
        self.setObjectName(f"ultraViewDraw{self._tool.title()}Button")
        self.setProperty("drawTool", self._tool)
        self.setCheckable(True)
        self.setFixedSize(40, 40)
        if self._tool == DRAW_ERASER:
            self.setToolTip(_ERASER_TOOLTIP)
            self.setAccessibleName("橡皮擦 整笔擦除")
        else:
            self.setToolTip(f"{zh} · {en}")
            self.setAccessibleName(zh)
        self.setStyleSheet(
            "QToolButton {"
            "background-color: #FFFFFF;"
            "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
            "border-radius: 8px; }"
            "QToolButton:checked { border-width: 2px; border-color: #4262FF; }"
        )

    def draw_tool(self) -> str:
        return self._tool

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = QColor("#2A3A42")
        pen = QPen(color)
        pen.setWidthF(2.0)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if self._tool == DRAW_ERASER:
            painter.drawLine(QPointF(10.0, 26.0), QPointF(26.0, 10.0))
            painter.drawRect(QRectF(18.0, 8.0, 10.0, 8.0))
            return
        path = QPainterPath()
        path.moveTo(10.0, 24.0)
        path.cubicTo(10.0, 12.0, 18.0, 8.0, 26.0, 14.0)
        path.cubicTo(30.0, 18.0, 28.0, 28.0, 18.0, 28.0)
        path.cubicTo(14.0, 28.0, 12.0, 24.0, 14.0, 20.0)
        painter.drawPath(path)


class DrawPopover(ToolFlyoutSurface):
    """Pen/Highlighter presets plus live Eraser and Lasso in one QFrame."""

    min_width = _DEFAULT_FLYOUT_MIN_WIDTH
    tool_selected = pyqtSignal(str, int)
    SETTINGS_GROUP = "UltraViewDrawPresets"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewDrawPopover")
        self._presets = {key: tuple(value) for key, value in DEFAULT_DRAW_PRESETS.items()}
        self._load_presets()
        self._active_tool = DEFAULT_DRAW_SUBTOOL
        self._active_preset = 0
        self._buttons: dict[str, list[_DrawPresetButton]] = {"pen": [], "highlighter": []}
        self._session_buttons: dict[str, _DrawSessionButton] = {}
        self._tool_buttons: dict[str, QToolButton] = {}
        self._color_buttons: dict[str, QToolButton] = {}
        self._build_rows()
        self._sync_checked()

    def subtools(self) -> tuple[str, ...]:
        return DRAW_SUBTOOLS

    def presets(self, tool: str) -> tuple[DrawPreset, ...]:
        if not is_draw_ink_subtool(tool):
            return ()
        return tuple(self._presets.get(normalize_draw_subtool(tool), ()))

    def preset_buttons(self, tool: str) -> tuple[QToolButton, ...]:
        if not is_draw_ink_subtool(tool):
            return ()
        return tuple(self._buttons.get(normalize_draw_subtool(tool), ()))

    def session_button(self, tool: str) -> QToolButton | None:
        return self._session_buttons.get(str(tool))

    def active_tool(self) -> tuple[str, int]:
        return self._active_tool, self._active_preset

    def set_presets(self, tool: str, presets: tuple[DrawPreset, ...]) -> None:
        checked = normalize_draw_subtool(tool)
        if checked not in DRAW_INK_SUBTOOLS or len(presets) != 3:
            raise ValueError("Pen and Highlighter require exactly three presets")
        if not all(isinstance(preset, DrawPreset) for preset in presets):
            raise TypeError("draw presets must be DrawPreset instances")
        self._presets[checked] = tuple(presets)
        for index, button in enumerate(self._buttons.get(checked, ())):
            button.set_preset(presets[index])
        self._save_presets()

    def choose_tool(self, tool: str, preset_index: int = 0) -> None:
        checked = normalize_draw_subtool(tool)
        if checked in (DRAW_ERASER, DRAW_LASSO):
            self._active_tool = checked
            self._active_preset = 0
            self._sync_checked()
            self.tool_selected.emit(checked, 0)
            return
        presets = self._presets.get(checked, ())
        index = int(preset_index)
        if not 0 <= index < len(presets):
            raise ValueError(f"unknown {checked} preset: {index}")
        self._active_tool = checked
        self._active_preset = index
        self._sync_checked()
        self.tool_selected.emit(checked, index)

    def _build_rows(self) -> None:
        tools = QWidget(self._content)
        tools.setObjectName("ultraViewDrawToolRow")
        tool_row = QHBoxLayout(tools)
        tool_row.setContentsMargins(0, 0, 0, 0)
        tool_row.setSpacing(8)
        for tool in DRAW_SUBTOOLS:
            zh, en = _DRAW_ROW_LABELS[tool]
            if tool in (DRAW_ERASER, DRAW_LASSO):
                button = _DrawSessionButton(tool, tools)
                button.clicked.connect(self._on_session_clicked)
                self._session_buttons[tool] = button
            else:
                button = QToolButton(tools)
                button.setObjectName(f"ultraViewDraw{tool.title()}Button")
                button.setProperty("drawTool", tool)
                button.setCheckable(True)
                button.setFixedSize(42, 42)
                button.setToolTip(f"{zh} · {en}")
                button.setAccessibleName(zh)
                button.setIcon(qta.icon(
                    "fa5s.highlighter" if tool == "highlighter" else "fa5s.pen",
                    color="#183039",
                ))
                button.setIconSize(QSize(20, 20))
                button.clicked.connect(self._on_tool_cell_clicked)
            self._tool_buttons[tool] = button
            tool_row.addWidget(button)
        tool_row.addStretch(1)
        self.inner_layout().addWidget(tools)

        widths = QWidget(self._content)
        widths.setObjectName("ultraViewDrawWidthRow")
        width_row = QHBoxLayout(widths)
        width_row.setContentsMargins(0, 0, 0, 0)
        width_row.setSpacing(8)
        self._buttons["pen"] = []
        for index, preset in enumerate(self._presets["pen"]):
            button = _DrawPresetButton("pen", preset, index, widths)
            button.clicked.connect(self._on_preset_clicked)
            self._buttons["pen"].append(button)
            width_row.addWidget(button)
        self._buttons["highlighter"] = list(self._buttons["pen"])
        width_row.addStretch(1)
        self.inner_layout().addWidget(widths)

        colors = QWidget(self._content)
        colors.setObjectName("ultraViewDrawColorRow")
        color_row = QHBoxLayout(colors)
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.setSpacing(6)
        current = self._presets[self._active_tool][self._active_preset].palette if self._active_tool in self._presets else "ink"
        for token in _DRAW_COLORS:
            button = QToolButton(colors)
            button.setObjectName(f"ultraViewDrawColor{token.title()}Button")
            button.setProperty("drawColor", token)
            button.setCheckable(True)
            button.setFixedSize(22, 22)
            button.setToolTip(f"画笔颜色：{token}")
            button.setAccessibleName(f"画笔颜色：{token}")
            rgb = ink_color(token, DEFAULT_THEME)
            button.setStyleSheet(
                "QToolButton {"
                f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]});"
                "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
                "border-radius: 11px; }"
                "QToolButton:checked { border-width: 2px; border-color: #4262FF; }"
            )
            button.setChecked(token == current)
            button.clicked.connect(self._on_color_clicked)
            self._color_buttons[token] = button
            color_row.addWidget(button)
        color_row.addStretch(1)
        self.inner_layout().addWidget(colors)

    def _sync_checked(self) -> None:
        for tool, button in self._tool_buttons.items():
            button.setChecked(tool == self._active_tool)
        widths = _PEN_WIDTHS if self._active_tool != "highlighter" else _HIGHLIGHTER_WIDTHS
        if self._active_tool in self._presets:
            current = self._presets[self._active_tool][self._active_preset]
            for index, button in enumerate(self._buttons["pen"]):
                width = widths[index] if index < len(widths) else current.width_px_100
                button.set_preset(DrawPreset(current.palette, width))
                button.setChecked(index == self._active_preset)
            for token, button in self._color_buttons.items():
                button.setChecked(token == current.palette)
        else:
            for button in self._buttons["pen"]:
                button.setChecked(False)

    def _on_tool_cell_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_tool(str(sender.property("drawTool") or ""), self._active_preset)
            self.close()

    def _on_preset_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            tool = self._active_tool if self._active_tool in DRAW_INK_SUBTOOLS else "pen"
            self.choose_tool(tool, int(sender.property("presetIndex") or 0))
            self.close()

    def _on_session_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_tool(str(sender.property("drawTool") or ""), 0)
            self.close()

    def _on_color_clicked(self) -> None:
        sender = self.sender()
        if not isinstance(sender, QToolButton):
            return
        token = str(sender.property("drawColor") or "ink")
        tool = self._active_tool if self._active_tool in DRAW_INK_SUBTOOLS else "pen"
        presets = list(self._presets[tool])
        index = self._active_preset if 0 <= self._active_preset < len(presets) else 0
        current = presets[index]
        presets[index] = DrawPreset(token, current.width_px_100)
        self.set_presets(tool, tuple(presets))
        self.choose_tool(tool, index)
        self.close()

    def _settings(self) -> QSettings:
        settings = QSettings()
        settings.beginGroup(self.SETTINGS_GROUP)
        return settings

    def _load_presets(self) -> None:
        settings = self._settings()
        try:
            loaded: dict[str, tuple[DrawPreset, ...]] = {}
            for tool in DRAW_INK_SUBTOOLS:
                chips = []
                for index in range(3):
                    palette = settings.value(f"{tool}/{index}/palette")
                    width = settings.value(f"{tool}/{index}/width_px_100")
                    if palette is None or width is None:
                        chips = []
                        break
                    try:
                        chips.append(DrawPreset(str(palette), int(width)))
                    except (TypeError, ValueError):
                        chips = []
                        break
                if len(chips) == 3:
                    loaded[tool] = tuple(chips)
            if loaded:
                self._presets.update(loaded)
        finally:
            settings.endGroup()

    def _save_presets(self) -> None:
        settings = self._settings()
        try:
            for tool, presets in self._presets.items():
                for index, preset in enumerate(presets):
                    settings.setValue(f"{tool}/{index}/palette", preset.palette)
                    settings.setValue(f"{tool}/{index}/width_px_100", int(preset.width_px_100))
        finally:
            settings.endGroup()


class FormatChoiceFlyout(ToolFlyoutSurface):
    """Anchored picker reused by the selection toolbar. Height follows content."""

    min_width = _STICKY_FLYOUT_MIN_WIDTH
    choice_selected = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewFormatChoiceFlyout")

    def present_labels(self, choices: Sequence[tuple[object, str]], *, current=None) -> None:
        self._clear_body()
        host = QWidget(self._inner)
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        columns = 2 if len(choices) <= 6 else 4
        for index, (value, label) in enumerate(choices):
            button = QToolButton(host)
            button.setText(str(label))
            button.setProperty("choiceValue", value)
            button.setCheckable(True)
            button.setChecked(value == current)
            button.clicked.connect(self._on_clicked)
            grid.addWidget(button, index // columns, index % columns)
        self.inner_layout().addWidget(host)

    def present_palette(
        self,
        tokens: Sequence[object],
        *,
        current=None,
        color_rgb: dict[object, tuple[int, int, int]] | None = None,
    ) -> None:
        self._clear_body()
        host = QWidget(self._inner)
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, token in enumerate(tokens):
            button = QToolButton(host)
            button.setFixedSize(28, 28)
            button.setProperty("choiceValue", token)
            button.setCheckable(True)
            button.setChecked(token == current)
            label = "透明" if token is None else str(token)
            button.setToolTip(label)
            button.setAccessibleName(label)
            rgb = (color_rgb or {}).get(token)
            if rgb is None and token is None:
                rgb = (255, 255, 255)
            if rgb is not None:
                button.setStyleSheet(
                    "QToolButton {"
                    f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]});"
                    "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
                    "border-radius: 4px; }"
                    "QToolButton:checked { border-width: 2px; border-color: #4262FF; }"
                )
            else:
                button.setText(label)
            button.clicked.connect(self._on_clicked)
            grid.addWidget(button, index // 4, index % 4)
        self.inner_layout().addWidget(host)

    def present_shapes(self, shapes: Sequence[str], *, current: str | None = None) -> None:
        self._clear_body()
        host = QWidget(self._inner)
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, shape in enumerate(shapes):
            button = _ShapeCellButton(shape, host)
            button.setProperty("choiceValue", shape)
            button.setChecked(shape == current)
            button.clicked.connect(self._on_clicked)
            grid.addWidget(button, 0, index)
        self.inner_layout().addWidget(host)

    def _clear_body(self) -> None:
        layout = self.inner_layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choice_selected.emit(sender.property("choiceValue"))
            self.close()


_ICON_FOR_KEY = {
    "lock": "fa5s.lock",
    "duplicate": "fa5s.clone",
    "align": "fa5s.align-left",
    "align_left": "fa5s.align-left",
    "align_center": "fa5s.align-center",
    "align_right": "fa5s.align-right",
    "align_top": "fa5s.arrow-up",
    "align_middle": "fa5s.arrows-alt-v",
    "align_bottom": "fa5s.arrow-down",
    "list_style": "fa5s.list-ul",
    "link": "fa5s.link",
    "text": "fa5s.font",
    "label": "fa5s.tag",
    "route": "fa5s.slash",
    "start_head": "fa5s.long-arrow-alt-left",
    "end_head": "fa5s.long-arrow-alt-right",
    "tool": "fa5s.pen",
    "corner": "fa5s.vector-square",
    "distribute_h": "fa5s.arrows-alt-h",
    "distribute_v": "fa5s.arrows-alt-v",
}


class _FormatButton(QToolButton):
    """Icon / swatch / line / short-value control. Visible text is the exception."""

    def __init__(self, control: ToolbarControl, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._control = control
        self.setObjectName(f"ultraViewSelection{control.key.title().replace('_', '')}Button")
        self.setProperty("formatKey", control.key)
        self.setProperty("iconRole", control.icon_role)
        self.setProperty("mixed", "true" if control.mixed else "false")
        self.setFixedSize(_CONTROL_SIZE, _CONTROL_SIZE)
        self.setCheckable(control.checkable)
        self.setChecked(control.checked)
        self.setEnabled(control.enabled)
        self.setAutoRaise(True)
        tip = control.tooltip or control.label
        self.setToolTip(tip)
        self.setAccessibleName(tip)
        if control.icon_role in {"value", "glyph"} and control.visible_text and not control.mixed:
            self.setText(control.visible_text)
            self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        else:
            self.setText("")
            self.setToolButtonStyle(Qt.ToolButtonIconOnly)
            icon_name = _ICON_FOR_KEY.get(control.key)
            if icon_name and control.icon_role == "icon":
                if control.key == "lock" and control.checked:
                    icon_name = "fa5s.lock"
                elif control.key == "lock":
                    icon_name = "fa5s.unlock"
                self.setIcon(qta.icon(icon_name, color="#183039"))
                self.setIconSize(QSize(18, 18))

    def control(self) -> ToolbarControl:
        return self._control

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        role = self._control.icon_role
        if role not in {"swatch", "line", "dash", "shape"} and not self._control.mixed:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        box = QRectF(self.rect()).adjusted(8.0, 8.0, -8.0, -8.0)
        if self._control.mixed:
            painter.setPen(QPen(QColor("#66787E"), 1.6))
            painter.drawLine(box.topLeft(), box.bottomRight())
            return
        value = self._control.value
        if role == "swatch":
            if value is None:
                painter.setPen(QPen(_LINE, 1.0))
                painter.setBrush(QColor("#FFFFFF"))
            else:
                try:
                    rgb = sticky_colors(value, DEFAULT_THEME)[0]
                except (KeyError, ValueError, TypeError):
                    try:
                        rgb = ink_color(value, DEFAULT_THEME)
                    except (KeyError, ValueError, TypeError):
                        rgb = (66, 98, 255)
                painter.setPen(QPen(QColor(32, 48, 56, 50), 1.0))
                painter.setBrush(QColor(*rgb[:3]))
            painter.drawRoundedRect(box, 6.0, 6.0)
            return
        if role in {"line", "dash"}:
            color = QColor("#183039")
            pen = QPen(color, 2.0 if role == "dash" else max(1.5, float(value or 2)))
            if role == "dash" and value == "dashed":
                pen.setStyle(Qt.DashLine)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            mid = box.center().y()
            painter.drawLine(QPointF(box.left(), mid), QPointF(box.right(), mid))
            return
        if role == "shape":
            kind = str(value or "rectangle")
            path = shape_path(
                kind if kind in CLOSED_SHAPE_TYPES else "rectangle",
                box,
                corner_radius=6 if kind == "rounded_rectangle" else 0,
            )
            if path.isEmpty() and kind in {"square", "wide"}:
                path = QPainterPath()
                path.addRoundedRect(box, 4.0 if kind == "square" else 8.0, 4.0)
            painter.setPen(QPen(_INK, 1.4))
            painter.setBrush(QColor(66, 98, 255, 28))
            if not path.isEmpty():
                painter.drawPath(path)


class SelectionToolbar(QFrame):
    """48 px icon-first selection chrome. Page owns when it is shown."""

    format_requested = pyqtSignal(str, object)
    more_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewSelectionToolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedHeight(_TOOLBAR_HEIGHT)
        self._kind = ""
        self._compact = False
        self._caps: SelectionCapabilities | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 5, 4, 5)
        layout.setSpacing(2)
        self._spine_bar = QFrame(self)
        self._spine_bar.hide()
        self._spine_label = QLabel("")
        self._spine_label.hide()
        self._body = QWidget(self)
        self._body_layout = QHBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(2)
        layout.addWidget(self._body, 1)
        self._more = QToolButton(self)
        self._more.setObjectName("ultraViewSelectionToolbarMore")
        self._more.setText("⋯")
        self._more.setToolTip("更多")
        self._more.setAccessibleName("更多")
        self._more.setFixedSize(_CONTROL_SIZE, _CONTROL_SIZE)
        self._more.clicked.connect(self.more_requested.emit)
        layout.addWidget(self._more)
        self._wide_buttons: list[QToolButton] = []
        self.set_kind("sticky")

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect().adjusted(0, 0, -1, -1)), _TOOLBAR_RADIUS, _TOOLBAR_RADIUS)
        painter.fillPath(path, _SURFACE)
        painter.setPen(_LINE)
        painter.drawPath(path)

    def kind(self) -> str:
        return self._kind

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        wide = set(self._wide_buttons)
        for index in range(self._body_layout.count()):
            widget = self._body_layout.itemAt(index).widget()
            if widget is None:
                continue
            if widget in wide:
                widget.setVisible(not self._compact)
            else:
                widget.show()

    def set_kind(self, kind: str) -> None:
        checked = str(kind or "sticky")
        self._kind = checked
        self._clear_body()
        if checked in {"card", "card_author"}:
            self.set_compact(self._compact)
            return
        placeholders = {
            "sticky": (
                ToolbarControl("shape", "形状", "形状", icon_role="shape", value="square"),
                ToolbarControl("palette", "色板", "色板", icon_role="swatch", value="yellow"),
                ToolbarControl("font_size", "字号", "字号", icon_role="value", visible_text="14", wide=True),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon"),
            ),
            "text": (
                ToolbarControl("font_role", "字体", "字体", icon_role="value", visible_text="Sans"),
                ToolbarControl("font_size", "字号", "字号", icon_role="value", visible_text="14"),
                ToolbarControl("bold", "B", "加粗", checkable=True, icon_role="glyph", visible_text="B"),
                ToolbarControl("italic", "I", "斜体", checkable=True, icon_role="glyph", visible_text="I"),
                ToolbarControl("underline", "U", "下划线", checkable=True, icon_role="glyph", visible_text="U"),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", wide=True),
            ),
            "shape": (
                ToolbarControl("shape", "形状", "形状", icon_role="shape", value="rectangle"),
                ToolbarControl("fill", "填充色", "填充色", icon_role="swatch", value="blue"),
                ToolbarControl("stroke", "描边色", "描边色", icon_role="swatch", value="ink"),
                ToolbarControl("width", "线宽", "线宽", icon_role="line", value=2),
                ToolbarControl("dash", "线型", "线型", icon_role="dash", value="solid"),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", wide=True),
            ),
            "connector": (
                ToolbarControl("route", "路径", "路径", icon_role="icon", value="straight"),
                ToolbarControl("color", "颜色", "颜色", icon_role="swatch", value="ink"),
                ToolbarControl("width", "线宽", "线宽", icon_role="line", value=2),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", wide=True),
            ),
            "stroke": (
                ToolbarControl("tool", "笔种", "笔种", icon_role="icon", value="pen"),
                ToolbarControl("color", "颜色", "颜色", icon_role="swatch", value="ink"),
                ToolbarControl("width", "线宽", "线宽", icon_role="line", value=4),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", wide=True),
            ),
            "mixed": (
                ToolbarControl("duplicate", "复制", "复制 · Ctrl/Cmd+D", icon_role="icon"),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon"),
            ),
        }
        for control in placeholders.get(checked, ()):
            self._add_control(control)
        self.set_compact(self._compact)

    def apply_capabilities(self, caps: SelectionCapabilities) -> None:
        """Rebuild controls from a typed resolver result."""
        self._caps = caps
        self._kind = str(caps.kind or "mixed")
        self._clear_body()
        if self._kind in {"card", "card_author", "empty", ""}:
            self.set_compact(self._compact)
            return
        for control in caps.controls:
            self._add_control(control)
        self.set_compact(self._compact)

    def button(self, key: str) -> QToolButton | None:
        found = None
        for widget in self.findChildren(QToolButton):
            if widget.property("formatKey") != key:
                continue
            if widget is self._more or widget.isHidden():
                continue
            found = widget
        return found

    def more_button(self) -> QToolButton:
        return self._more

    def capabilities(self) -> SelectionCapabilities | None:
        return self._caps

    def overflow_keys(self) -> tuple[str, ...]:
        if not self._compact or self._caps is None:
            return ()
        return tuple(control.key for control in self._caps.controls if control.wide)

    def _clear_body(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._wide_buttons = []

    def set_shape_type(self, shape: str) -> None:
        """Hide corner control for shapes that do not have semantic corners."""
        allow_corner = str(shape) in {"rectangle", "rounded_rectangle"}
        for index in range(self._body_layout.count()):
            widget = self._body_layout.itemAt(index).widget()
            if not isinstance(widget, QToolButton):
                continue
            key = str(widget.property("formatKey") or "")
            if key == "corner":
                widget.setVisible(allow_corner)
            else:
                widget.show()
        self.set_compact(self._compact)

    def set_mixed_keys(self, keys: tuple[str, ...]) -> None:
        for key in keys:
            button = self.button(key)
            if button is not None:
                button.setProperty("mixed", "true")
                button.setText("")

    def visible_button_texts(self) -> tuple[str, ...]:
        texts = []
        for index in range(self._body_layout.count()):
            widget = self._body_layout.itemAt(index).widget()
            if isinstance(widget, QToolButton) and widget.isVisible():
                texts.append(widget.text().strip())
        if self._more.isVisible():
            texts.append(self._more.text().strip())
        return tuple(text for text in texts if text)

    def forbidden_visible_words(self) -> tuple[str, ...]:
        found = []
        for text in self.visible_button_texts():
            if text in FORBIDDEN_TOOLBAR_WORDS:
                found.append(text)
        return tuple(found)

    def _add_control(self, control: ToolbarControl) -> None:
        button = _FormatButton(control, self._body)
        button.clicked.connect(self._emit_format)
        self._body_layout.addWidget(button)
        button.show()
        if control.wide:
            self._wide_buttons.append(button)

    def _add_body_button(
        self,
        key: str,
        label: str,
        *,
        wide: bool = False,
        tooltip: str | None = None,
        checkable: bool = False,
    ) -> None:
        self._add_control(
            ToolbarControl(
                key,
                label,
                tooltip or label,
                checkable=checkable,
                wide=wide,
                icon_role="glyph" if key in {"bold", "italic", "underline"} else "icon",
                visible_text=label if key in {"bold", "italic", "underline", "font_role", "font_size"} else "",
            )
        )

    def _emit_format(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            key = str(sender.property("formatKey") or "")
            value: object = sender.isChecked() if sender.isCheckable() else True
            self.format_requested.emit(key, value)
