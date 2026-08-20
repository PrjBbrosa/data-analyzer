"""Author flyouts and selection toolbar. Chrome.py re-exports public names."""
from __future__ import annotations

from collections.abc import Sequence

import qtawesome as qta
from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QRegion
from PyQt5.QtWidgets import (
    QAbstractScrollArea,
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
_STICKY_FLYOUT_MIN_WIDTH = 128
_SHAPE_FLYOUT_MIN_WIDTH = 232
_DRAW_FLYOUT_MIN_WIDTH = 72
_DEFAULT_FLYOUT_MIN_WIDTH = 160
_STICKY_SWATCH = 48
_TOOLBAR_HEIGHT = 48
_CONTROL_SIZE = 36
_FONT_CELL_WIDTH = 112
_SIZE_CELL_WIDTH = 60
_SHAPE_CELL = 42
_DRAW_CELL = 40
_DRAW_PRESET = 36
_DRAW_COLOR = 24
_CATALOG_ROW_HEIGHT = 44
_DRAW_COLORS = ("ink", "blue", "red", "yellow", "green", "pink", "teal", "purple")
_PEN_WIDTHS = (2, 4, 8)
_HIGHLIGHTER_WIDTHS = (8, 12, 16)
_PICKER_GAP = 6


class ToolFlyoutSurface(QFrame):
    """Rounded author flyout. Hosted as a CanvasHost overlay in the page.

    ``popup()`` remains the compatibility seam for isolated tests. Page
    measures ``content_size()`` and places the widget through the host.
    """

    min_width = 0

    def __init__(self, parent: QWidget | None = None, *, windowed: bool = False) -> None:
        if windowed:
            super().__init__(
                parent,
                Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
            )
            apply_popup_shell(self)
        else:
            super().__init__(parent)
        self.setObjectName("ultraViewToolFlyoutSurface")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        if self.min_width > 0:
            self.setMinimumWidth(int(self.min_width))
        self._inner = QFrame(self)
        self._inner.setObjectName("ultraViewToolFlyoutInner")
        self._inner.setAttribute(Qt.WA_StyledBackground, True)
        self._inner.setAttribute(Qt.WA_TranslucentBackground, True)
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
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self._scroll.setSizeAdjustPolicy(QAbstractScrollArea.AdjustToContents)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: 0; }"
            "QScrollArea > QWidget { background: transparent; }"
        )
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
        self._content = QWidget(self._scroll)
        self._content.setObjectName("ultraViewToolFlyoutContent")
        self._content.setAttribute(Qt.WA_TranslucentBackground, True)
        self._content.setAutoFillBackground(False)
        self._body = QVBoxLayout(self._content)
        self._body.setContentsMargins(12, 12, 12, 12)
        self._body.setSpacing(8)
        self._scroll.setWidget(self._content)
        inner_root.addWidget(self._scroll)

    def inner_layout(self) -> QVBoxLayout:
        return self._body

    def content_widget(self) -> QWidget:
        return self._content

    def content_size(self) -> QSize:
        """Natural size of the inner content after polish, ignoring scroll defaults."""
        self.ensurePolished()
        self._inner.ensurePolished()
        self._content.ensurePolished()
        layout = self._content.layout()
        if layout is not None:
            layout.activate()
        hint = self._content.sizeHint()
        width = max(int(hint.width()), int(self.min_width or 0), 1)
        height = max(int(hint.height()), 1)
        return QSize(width, height)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.content_size()

    def popup(self, pos: QPoint) -> None:
        self.setMaximumHeight(16777215)
        natural = self.content_size()
        parent = self.parentWidget()
        width = natural.width()
        height = natural.height()
        if parent is not None:
            avail = parent.rect()
            max_h = max(120, avail.height() - 24)
            use_scroll = height > max_h
            if use_scroll:
                height = max_h
                self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            else:
                self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            local = parent.mapFromGlobal(pos)
            if not avail.adjusted(-80, -80, 80, 80).contains(local):
                local = QPoint(pos)
            left = min(max(avail.left(), local.x()), max(avail.left(), avail.right() - width))
            top = min(max(avail.top(), local.y()), max(avail.top(), avail.bottom() - height))
            self.setGeometry(left, top, width, height)
        else:
            screen = self.screen() or QApplication.primaryScreen()
            avail = screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 720)
            max_h = max(160, avail.bottom() - pos.y() - 8)
            if height > max_h:
                height = max_h
                self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            else:
                self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            left = min(max(avail.left() + 8, pos.x()), avail.right() - width - 8)
            top = min(max(avail.top() + 8, pos.y()), avail.bottom() - height - 8)
            self.setGeometry(left, top, width, height)
        self.show()
        self.raise_()

    def close(self) -> None:
        parent = self.parentWidget()
        key = self.property("overlayId")
        closer = getattr(parent, "close_overlay", None)
        active = getattr(parent, "active_overlay", None)
        if callable(closer) and callable(active) and key and active() == str(key):
            closer(str(key), restore_focus=False)
            return
        super().close()
        self.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_round_clip()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_round_clip()

    def _apply_round_clip(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), _FLYOUT_RADIUS, _FLYOUT_RADIUS)
        region = QRegion(path.toFillPolygon().toPolygon())
        self.setMask(region)

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
    """2×8 Sticky palette flyout. Emits palette/stack intents only."""

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
                "min-width: 44px; max-width: 44px; min-height: 44px; max-height: 44px;"
                "padding: 0; margin: 0;"
                "border-width: 2px; border-style: solid;"
                f"border-color: rgb({border[0]}, {border[1]}, {border[2]});"
                "border-radius: 8px; }"
                "QToolButton:checked { border-color: #4262FF; }"
            )
            button.clicked.connect(self._on_palette_clicked)
            self._palette_buttons[token] = button
            grid.addWidget(button, index // 2, index % 2)
        self._palette_buttons[self._selected_palette].setChecked(True)
        self.inner_layout().addWidget(host)
        self._stack = QToolButton(self._content)
        self._stack.setObjectName("ultraViewStickyStackButton")
        self._stack.setText("Stack")
        self._stack.setIcon(qta.icon("fa5s.layer-group", color="#183039"))
        self._stack.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._stack.setCheckable(True)
        self._stack.setFixedHeight(38)
        self._stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        palette_width = _STICKY_SWATCH * 2 + 8
        self._stack.setFixedWidth(palette_width)
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
        self.setFixedSize(_SHAPE_CELL, _SHAPE_CELL)
        self.setProperty("catalogKind", self._shape)
        self.setProperty("catalogFamily", "shape")
        self.setToolTip(f"{zh} · {en}")
        self.setAccessibleName(zh)
        self.setStyleSheet(
            "QToolButton {"
            "background-color: #FFFFFF;"
            "min-width: 0; min-height: 0; padding: 0; margin: 0;"
            "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
            "border-radius: 8px; }"
            "QToolButton:checked { border-color: #4262FF; }"
        )

    def shape_type(self) -> str:
        return self._shape

    def catalog_kind(self) -> str:
        return self._shape

    def catalog_family(self) -> str:
        return "shape"

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
        self.setFixedHeight(_CATALOG_ROW_HEIGHT)
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
    """Shapes and connectors in one labeled catalog. Dispatch stays typed."""

    min_width = _SHAPE_FLYOUT_MIN_WIDTH
    shape_selected = pyqtSignal(str)
    connector_selected = pyqtSignal(str)
    pin_requested = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewShapePopover")
        self._selected = CLOSED_SHAPE_TYPES[0]
        self._family = "shape"
        self._cells: dict[str, QToolButton] = {}
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
        host.setObjectName("ultraViewShapeCatalog")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        previous_family = ""
        for kind, title, shortcut, family in _SHAPE_CATALOG:
            if previous_family and family != previous_family:
                spacer = QWidget(host)
                spacer.setFixedHeight(8)
                layout.addWidget(spacer)
                divider = QFrame(host)
                divider.setObjectName("ultraViewShapeCatalogDivider")
                divider.setFrameShape(QFrame.NoFrame)
                divider.setFixedHeight(1)
                divider.setStyleSheet("background-color: rgba(50, 86, 97, 40); border: 0;")
                layout.addWidget(divider)
                after = QWidget(host)
                after.setFixedHeight(8)
                layout.addWidget(after)
            button = _CatalogRow(kind, family, title, shortcut, host)
            button.clicked.connect(self._on_cell_clicked)
            self._cells[kind] = button
            layout.addWidget(button)
            previous_family = family
        self._sync_checked()
        self.inner_layout().addWidget(host)
        self._pin = QToolButton(self._content)
        self._pin.hide()

    def _on_cell_clicked(self) -> None:
        sender = self.sender()
        if not isinstance(sender, QToolButton):
            return
        family = str(sender.property("catalogFamily") or "")
        kind = str(sender.property("catalogKind") or "")
        if family == "connector":
            self.choose_connector(kind)
        else:
            self.choose_shape(kind)
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
        self.setFixedSize(_SHAPE_CELL, _SHAPE_CELL)
        self.setProperty("catalogKind", self._kind)
        self.setProperty("catalogFamily", "connector")
        self.setToolTip(f"{zh} · {en}")
        self.setAccessibleName(zh)
        self.setStyleSheet(
            "QToolButton {"
            "background-color: #FFFFFF;"
            "min-width: 0; min-height: 0; padding: 0; margin: 0;"
            "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
            "border-radius: 8px; }"
            "QToolButton:checked { border-color: #4262FF; }"
        )

    def connector_type(self) -> str:
        return self._kind

    def catalog_kind(self) -> str:
        return self._kind

    def catalog_family(self) -> str:
        return "connector"

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
        self.setFixedSize(_DRAW_CELL, _DRAW_CELL)
        self.setToolTip(f"{zh} · {preset.palette} · {preset.width_px_100}px")
        self.setAccessibleName(f"{zh}预设 {self._index + 1}")
        self.setStyleSheet(
            "QToolButton {"
            "background-color: #FFFFFF;"
            "min-width: 0; min-height: 0; padding: 0; margin: 0;"
            "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
            "border-radius: 8px; }"
            "QToolButton:checked { border-color: #4262FF; }"
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
        self.setFixedSize(_DRAW_CELL, _DRAW_CELL)
        if self._tool == DRAW_ERASER:
            self.setToolTip(_ERASER_TOOLTIP)
            self.setAccessibleName("橡皮擦 整笔擦除")
        else:
            self.setToolTip(f"{zh} · {en}")
            self.setAccessibleName(zh)
        self.setStyleSheet(
            "QToolButton {"
            "background-color: #FFFFFF;"
            "min-width: 0; min-height: 0; padding: 0; margin: 0;"
            "border-width: 1px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
            "border-radius: 8px; }"
            "QToolButton:checked { border-color: #4262FF; }"
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
    """Vertical Draw subrail: four tools, then three presets. Editor is opt-in."""

    min_width = _DRAW_FLYOUT_MIN_WIDTH
    tool_selected = pyqtSignal(str, int)
    layoutChanged = pyqtSignal()
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
        self._width_buttons: list[QToolButton] = []
        self._editor: QWidget | None = None
        self._editor_visible = False
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
        shell = QWidget(self._content)
        shell.setObjectName("ultraViewDrawSubrail")
        row = QHBoxLayout(shell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        tools = QWidget(shell)
        tools.setObjectName("ultraViewDrawToolColumn")
        tool_col = QVBoxLayout(tools)
        tool_col.setContentsMargins(0, 0, 0, 0)
        tool_col.setSpacing(4)
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
                button.setFixedSize(_DRAW_CELL, _DRAW_CELL)
                button.setStyleSheet(
                    "QToolButton {"
                    "min-width: 0; min-height: 0; padding: 0; margin: 0;"
                    "background-color: transparent; border: 0; border-radius: 8px; }"
                    "QToolButton:checked { background-color: #EEF1FF; }"
                    "QToolButton:hover { background-color: #F3F5F6; }"
                )
                button.setToolTip(f"{zh} · {en}")
                button.setAccessibleName(zh)
                button.setIcon(qta.icon(
                    "fa5s.highlighter" if tool == "highlighter" else "fa5s.pen",
                    color="#183039",
                ))
                button.setIconSize(QSize(20, 20))
                button.clicked.connect(self._on_tool_cell_clicked)
            self._tool_buttons[tool] = button
            tool_col.addWidget(button, 0, Qt.AlignHCenter)

        divider = QFrame(tools)
        divider.setObjectName("ultraViewDrawCatalogDivider")
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: rgba(50, 86, 97, 40); border: 0;")
        tool_col.addSpacing(8)
        tool_col.addWidget(divider)
        tool_col.addSpacing(8)

        self._buttons["pen"] = []
        for index, preset in enumerate(self._presets["pen"]):
            button = _DrawPresetButton("pen", preset, index, tools)
            button.setFixedSize(_DRAW_PRESET, _DRAW_PRESET)
            button.clicked.connect(self._on_preset_clicked)
            self._buttons["pen"].append(button)
            tool_col.addWidget(button, 0, Qt.AlignHCenter)
        self._buttons["highlighter"] = list(self._buttons["pen"])
        row.addWidget(tools, 0, Qt.AlignTop)

        self._editor = QWidget(shell)
        self._editor.setObjectName("ultraViewDrawPresetEditor")
        editor_col = QVBoxLayout(self._editor)
        editor_col.setContentsMargins(0, 0, 0, 0)
        editor_col.setSpacing(8)
        widths = QWidget(self._editor)
        widths.setObjectName("ultraViewDrawWidthRow")
        width_row = QHBoxLayout(widths)
        width_row.setContentsMargins(0, 0, 0, 0)
        width_row.setSpacing(6)
        self._width_buttons = []
        for index, width in enumerate(_PEN_WIDTHS):
            button = QToolButton(widths)
            button.setObjectName(f"ultraViewDrawWidth{width}Button")
            button.setProperty("drawWidth", width)
            button.setCheckable(True)
            button.setFixedSize(32, 32)
            button.setToolTip(f"线宽 {width}px")
            button.setAccessibleName(f"线宽 {width}px")
            button.clicked.connect(self._on_width_clicked)
            self._width_buttons.append(button)
            width_row.addWidget(button)
        editor_col.addWidget(widths)

        colors = QWidget(self._editor)
        colors.setObjectName("ultraViewDrawColorRow")
        color_grid = QGridLayout(colors)
        color_grid.setContentsMargins(0, 0, 0, 0)
        color_grid.setHorizontalSpacing(6)
        color_grid.setVerticalSpacing(6)
        current = (
            self._presets[self._active_tool][self._active_preset].palette
            if self._active_tool in self._presets
            else "ink"
        )
        for index, token in enumerate(_DRAW_COLORS):
            button = QToolButton(colors)
            button.setObjectName(f"ultraViewDrawColor{token.title()}Button")
            button.setProperty("drawColor", token)
            button.setCheckable(True)
            button.setFixedSize(_DRAW_COLOR, _DRAW_COLOR)
            button.setToolTip(f"画笔颜色：{token}")
            button.setAccessibleName(f"画笔颜色：{token}")
            rgb = ink_color(token, DEFAULT_THEME)
            radius = _DRAW_COLOR // 2
            button.setStyleSheet(
                "QToolButton {"
                f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]});"
                "min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;"
                "padding: 0; margin: 0;"
                "border-width: 2px; border-style: solid; border-color: rgba(32, 48, 56, 40);"
                f"border-radius: {radius}px; }}"
                "QToolButton:checked { border-color: #4262FF; }"
            )
            button.setChecked(token == current)
            button.clicked.connect(self._on_color_clicked)
            self._color_buttons[token] = button
            color_grid.addWidget(button, index // 4, index % 4)
        editor_col.addWidget(colors)
        self._editor.hide()
        row.addWidget(self._editor, 0, Qt.AlignTop)
        self.inner_layout().addWidget(shell)

    def preset_editor_visible(self) -> bool:
        return bool(self._editor_visible)

    def show_preset_editor(self, visible: bool = True) -> None:
        wanted = bool(visible)
        if self._editor is None or self._editor_visible == wanted:
            if wanted and self._editor is not None:
                self._editor.show()
            return
        self._editor_visible = wanted
        self._editor.setVisible(wanted)
        self.layoutChanged.emit()

    def _sync_checked(self) -> None:
        for tool, button in self._tool_buttons.items():
            button.setChecked(tool == self._active_tool)
        ink_tool = self._active_tool if self._active_tool in self._presets else "pen"
        presets = self._presets.get(ink_tool, ())
        for index, button in enumerate(self._buttons["pen"]):
            if index < len(presets):
                button.set_preset(presets[index])
                button.setProperty("drawTool", ink_tool)
                button.setChecked(self._active_tool == ink_tool and index == self._active_preset)
            else:
                button.setChecked(False)
        current = presets[self._active_preset] if presets and 0 <= self._active_preset < len(presets) else None
        widths = _HIGHLIGHTER_WIDTHS if ink_tool == "highlighter" else _PEN_WIDTHS
        for index, button in enumerate(self._width_buttons):
            width = widths[index] if index < len(widths) else widths[-1]
            button.setProperty("drawWidth", width)
            button.setToolTip(f"线宽 {width}px")
            button.setChecked(current is not None and current.width_px_100 == width)
        if current is not None:
            for token, button in self._color_buttons.items():
                button.setChecked(token == current.palette)

    def _on_tool_cell_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_tool(str(sender.property("drawTool") or ""), self._active_preset)

    def _on_preset_clicked(self) -> None:
        sender = self.sender()
        if not isinstance(sender, QToolButton):
            return
        tool = self._active_tool if self._active_tool in DRAW_INK_SUBTOOLS else "pen"
        index = int(sender.property("presetIndex") or 0)
        if tool == self._active_tool and index == self._active_preset:
            self.show_preset_editor(not self._editor_visible)
            return
        self.choose_tool(tool, index)

    def _on_session_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.show_preset_editor(False)
            self.choose_tool(str(sender.property("drawTool") or ""), 0)

    def _on_width_clicked(self) -> None:
        sender = self.sender()
        if not isinstance(sender, QToolButton):
            return
        width = int(sender.property("drawWidth") or 2)
        tool = self._active_tool if self._active_tool in DRAW_INK_SUBTOOLS else "pen"
        presets = list(self._presets[tool])
        index = self._active_preset if 0 <= self._active_preset < len(presets) else 0
        current = presets[index]
        presets[index] = DrawPreset(current.palette, width)
        self.set_presets(tool, tuple(presets))
        self.choose_tool(tool, index)

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

    min_width = 0
    choice_selected = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, windowed=False)
        self.setObjectName("ultraViewFormatChoiceFlyout")
        self._columns = 1

    def present_labels(self, choices: Sequence[tuple[object, str]], *, current=None) -> None:
        self._clear_body()
        host = QWidget(self._content)
        host.setObjectName("ultraViewFormatChoiceList")
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        self._columns = 1
        labels = []
        for value, label in choices:
            labels.append(str(label))
            button = QToolButton(host)
            button.setText(str(label))
            button.setProperty("choiceValue", value)
            button.setCheckable(True)
            button.setChecked(value == current)
            button.setFixedHeight(36)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.setStyleSheet(
                "QToolButton {"
                "background-color: transparent; border: 0; border-radius: 8px;"
                "padding: 0 12px; text-align: left; color: #183039; }"
                "QToolButton:checked { background-color: #EEF1FF; color: #4262FF; }"
                "QToolButton:hover { background-color: #F3F5F6; }"
            )
            button.clicked.connect(self._on_clicked)
            column.addWidget(button)
        named = {item.lower() for item in labels}
        if named & {"sans", "serif", "mono"}:
            self.min_width = 160
        elif all(item == "auto" or item.replace(" px", "").replace(".", "", 1).isdigit() for item in labels):
            self.min_width = 104
        else:
            self.min_width = 120
        self.setMinimumWidth(self.min_width)
        self.inner_layout().addWidget(host)

    def present_palette(
        self,
        tokens: Sequence[object],
        *,
        current=None,
        color_rgb: dict[object, tuple[int, int, int]] | None = None,
    ) -> None:
        self._clear_body()
        host = QWidget(self._content)
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self._columns = 4
        self.min_width = 0
        self.setMinimumWidth(0)
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
        host = QWidget(self._content)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._columns = 1
        self.min_width = _SHAPE_FLYOUT_MIN_WIDTH
        self.setMinimumWidth(_SHAPE_FLYOUT_MIN_WIDTH)
        catalog = {kind: (title, shortcut, family) for kind, title, shortcut, family in _SHAPE_CATALOG}
        for shape in shapes:
            title, shortcut, family = catalog.get(str(shape), (str(shape), "", "shape"))
            button = _CatalogRow(str(shape), family, title, shortcut, host)
            button.setProperty("choiceValue", shape)
            button.setChecked(shape == current)
            button.clicked.connect(self._on_clicked)
            layout.addWidget(button)
        self.inner_layout().addWidget(host)

    def column_count(self) -> int:
        return int(self._columns)

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
        self.setProperty("role", "selectionToolbarCell")
        self.setProperty("chrome", "ultraview")
        if control.key == "font_role":
            self.setFixedSize(_FONT_CELL_WIDTH, _CONTROL_SIZE)
        elif control.key == "font_size":
            self.setFixedSize(_SIZE_CELL_WIDTH, _CONTROL_SIZE)
        else:
            self.setFixedSize(_CONTROL_SIZE, _CONTROL_SIZE)
        self.setCheckable(control.checkable)
        self.setChecked(control.checked)
        self.setEnabled(control.enabled)
        self.setAutoRaise(True)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_StyledBackground, True)
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
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(0)
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
        self._more.setProperty("role", "selectionToolbarCell")
        self._more.setProperty("chrome", "ultraview")
        self._more.setText("⋯")
        self._more.setToolTip("更多")
        self._more.setAccessibleName("更多")
        self._more.setFixedSize(_CONTROL_SIZE, _CONTROL_SIZE)
        self._more.setAutoRaise(True)
        self._more.setAutoFillBackground(False)
        self._more.setAttribute(Qt.WA_StyledBackground, True)
        self._more.clicked.connect(self.more_requested.emit)
        layout.addWidget(self._more)
        self._wide_buttons: list[QToolButton] = []
        self._last_group = ""
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
                ToolbarControl("shape", "形状", "形状", icon_role="shape", value="square", group="style"),
                ToolbarControl("palette", "色板", "色板", icon_role="swatch", value="yellow", group="style"),
                ToolbarControl("font_size", "字号", "字号", icon_role="value", visible_text="14", group="type"),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", group="object"),
            ),
            "text": (
                ToolbarControl("font_role", "字体", "字体", icon_role="value", visible_text="Sans", group="font"),
                ToolbarControl("font_size", "字号", "字号", icon_role="value", visible_text="14", group="font"),
                ToolbarControl("bold", "B", "加粗", checkable=True, icon_role="glyph", visible_text="B", group="format"),
                ToolbarControl("italic", "I", "斜体", checkable=True, icon_role="glyph", visible_text="I", group="format"),
                ToolbarControl("underline", "U", "下划线", checkable=True, icon_role="glyph", visible_text="U", group="format"),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", wide=True, group="object"),
            ),
            "shape": (
                ToolbarControl("shape", "形状", "形状", icon_role="shape", value="rectangle", group="style"),
                ToolbarControl("fill", "填充色", "填充色", icon_role="swatch", value="blue", group="style"),
                ToolbarControl("stroke", "描边色", "描边色", icon_role="swatch", value="ink", group="style"),
                ToolbarControl("width", "线宽", "线宽", icon_role="line", value=2, group="style"),
                ToolbarControl("dash", "线型", "线型", icon_role="dash", value="solid", group="style"),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", wide=True, group="object"),
            ),
            "connector": (
                ToolbarControl("route", "路径", "路径", icon_role="icon", value="straight", group="ends"),
                ToolbarControl("color", "颜色", "颜色", icon_role="swatch", value="ink", group="stroke"),
                ToolbarControl("width", "线宽", "线宽", icon_role="line", value=2, group="stroke"),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", wide=True, group="object"),
            ),
            "stroke": (
                ToolbarControl("tool", "笔种", "笔种", icon_role="icon", value="pen", group="tool"),
                ToolbarControl("color", "颜色", "颜色", icon_role="swatch", value="ink", group="ink"),
                ToolbarControl("width", "线宽", "线宽", icon_role="line", value=4, group="ink"),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", wide=True, group="object"),
            ),
            "mixed": (
                ToolbarControl("duplicate", "复制", "复制 · Ctrl/Cmd+D", icon_role="icon", group="object"),
                ToolbarControl("lock", "锁定", "锁定", checkable=True, icon_role="icon", group="object"),
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
        self._last_group = ""

    def group_dividers(self) -> tuple[QFrame, ...]:
        return tuple(
            widget
            for widget in self._body.findChildren(QFrame)
            if widget.property("role") == "selectionToolbarDivider"
        )

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

    def _add_group_divider(self) -> None:
        wrap = QWidget(self._body)
        wrap.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        inner = QHBoxLayout(wrap)
        inner.setContentsMargins(4, 0, 4, 0)
        inner.setSpacing(0)
        divider = QFrame(wrap)
        divider.setObjectName("ultraViewSelectionToolbarDivider")
        divider.setProperty("role", "selectionToolbarDivider")
        divider.setFixedSize(1, 24)
        inner.addWidget(divider, 0, Qt.AlignVCenter)
        self._body_layout.addWidget(wrap)

    def _add_control(self, control: ToolbarControl) -> None:
        group = str(control.group or "")
        if group and self._last_group and group != self._last_group:
            self._add_group_divider()
        if group:
            self._last_group = group
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
