"""Author flyouts and selection toolbar. Chrome.py re-exports public names."""
from __future__ import annotations

from PyQt5.QtCore import QPoint, QPointF, QRectF, QSettings, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui_kit.popup_shell import apply_popup_shell

from .author_render import shape_path
from .author_style import DEFAULT_THEME, STICKY_PALETTE_TOKENS, pen_color, sticky_colors
from .author_selection import INDETERMINATE, SelectionCapabilities
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

_FLYOUT_RADIUS = 12
_SURFACE = QColor("#FFFFFF")
_LINE = QColor(32, 48, 56, 40)


class ToolFlyoutSurface(QFrame):
    """Non-modal rounded QFrame flyout. ``popup()`` matches the old QMenu seam."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        apply_popup_shell(self)
        self.setObjectName("ultraViewToolFlyoutSurface")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._inner = QFrame(self)
        self._inner.setObjectName("ultraViewToolFlyoutInner")
        self._inner.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._inner)
        self._body = QVBoxLayout(self._inner)
        self._body.setContentsMargins(10, 10, 10, 10)
        self._body.setSpacing(8)

    def inner_layout(self) -> QVBoxLayout:
        return self._body

    def popup(self, pos: QPoint) -> None:
        self.adjustSize()
        self.move(pos)
        self.show()
        self.raise_()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(248, 220)

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

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = bool(pinned)
        self._pin.setChecked(self._pinned)

    def _build_palette(self) -> None:
        title = QLabel("便签贴纸")
        title.setObjectName("ultraViewStickyFlyoutTitle")
        self.inner_layout().addWidget(title)
        host = QWidget(self._inner)
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
            button.setFixedSize(28, 28)
            button.setToolTip(f"便签颜色：{token}")
            button.setAccessibleName(f"便签颜色：{token}")
            button.setStyleSheet(
                "QToolButton {"
                f"background-color: rgb({fill[0]}, {fill[1]}, {fill[2]});"
                "border-width: 1px; border-style: solid;"
                f"border-color: rgb({border[0]}, {border[1]}, {border[2]});"
                "border-radius: 4px; }"
                "QToolButton:checked { border-width: 2px; border-color: #4262FF; }"
            )
            button.clicked.connect(self._on_palette_clicked)
            self._palette_buttons[token] = button
            grid.addWidget(button, index // 4, index % 4)
        self._palette_buttons[self._selected_palette].setChecked(True)
        self.inner_layout().addWidget(host)
        self._pin = QToolButton(self._inner)
        self._pin.setObjectName("ultraViewStickyPinButton")
        self._pin.setText("固定连续创建")
        self._pin.setCheckable(True)
        self._pin.setToolTip("固定后连续放置便签")
        self._pin.setAccessibleName("固定连续创建")
        self._pin.clicked.connect(self._on_pin_clicked)
        self.inner_layout().addWidget(self._pin)

    def _on_palette_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_palette(str(sender.property("stickyPalette") or ""))
            self.close()

    def _on_pin_clicked(self) -> None:
        self._pinned = self._pin.isChecked()
        self.pin_requested.emit(self._pinned)


_SHAPE_CELL_LABELS = {
    "rectangle": ("矩形", "Rectangle"),
    "rounded_rectangle": ("圆角矩形", "Rounded Rectangle"),
    "oval": ("椭圆", "Oval"),
    "rhombus": ("菱形", "Diamond"),
    "triangle": ("三角形", "Triangle"),
}


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


class ShapePopover(ToolFlyoutSurface):
    """5-cell closed-shape flyout. Connectors stay out of this surface."""

    shape_selected = pyqtSignal(str)
    pin_requested = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewShapePopover")
        self._selected = CLOSED_SHAPE_TYPES[0]
        self._cells: dict[str, _ShapeCellButton] = {}
        self._pinned = False
        self._build_cells()

    def shape_types(self) -> tuple[str, ...]:
        return CLOSED_SHAPE_TYPES

    def cell_buttons(self) -> tuple[QToolButton, ...]:
        return tuple(self._cells[shape] for shape in CLOSED_SHAPE_TYPES)

    def selected_shape(self) -> str:
        return self._selected

    def choose_shape(self, shape: str) -> None:
        checked = str(shape)
        if checked not in self._cells:
            raise ValueError(f"unknown author shape: {checked}")
        self._selected = checked
        for candidate, button in self._cells.items():
            button.setChecked(candidate == checked)
        self.shape_selected.emit(checked)

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = bool(pinned)
        self._pin.setChecked(self._pinned)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(268, 132)

    def _build_cells(self) -> None:
        title = QLabel("形状")
        title.setObjectName("ultraViewShapeFlyoutTitle")
        self.inner_layout().addWidget(title)
        host = QWidget(self._inner)
        host.setObjectName("ultraViewShapeCellGrid")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for index, shape in enumerate(CLOSED_SHAPE_TYPES):
            button = _ShapeCellButton(shape, host)
            button.clicked.connect(self._on_cell_clicked)
            self._cells[shape] = button
            grid.addWidget(button, 0, index)
        self._cells[self._selected].setChecked(True)
        self.inner_layout().addWidget(host)
        self._pin = QToolButton(self._inner)
        self._pin.setObjectName("ultraViewShapePinButton")
        self._pin.setText("固定连续创建")
        self._pin.setCheckable(True)
        self._pin.setToolTip("固定后连续放置形状")
        self._pin.setAccessibleName("固定连续创建")
        self._pin.clicked.connect(self._on_pin_clicked)
        self.inner_layout().addWidget(self._pin)

    def _on_cell_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_shape(str(sender.property("shapeType") or ""))
            self.close()

    def _on_pin_clicked(self) -> None:
        self._pinned = self._pin.isChecked()
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

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(220, 132)

    def _build_cells(self) -> None:
        title = QLabel("连接线")
        title.setObjectName("ultraViewConnectorFlyoutTitle")
        self.inner_layout().addWidget(title)
        host = QWidget(self._inner)
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
        self._pin = QToolButton(self._inner)
        self._pin.setObjectName("ultraViewConnectorPinButton")
        self._pin.setText("固定连续创建")
        self._pin.setCheckable(True)
        self._pin.setToolTip("固定后连续放置连接线")
        self._pin.setAccessibleName("固定连续创建")
        self._pin.clicked.connect(self._on_pin_clicked)
        self.inner_layout().addWidget(self._pin)

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

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(248, 248)

    def _build_rows(self) -> None:
        title = QLabel("画笔")
        title.setObjectName("ultraViewDrawFlyoutTitle")
        self.inner_layout().addWidget(title)
        for tool in DRAW_INK_SUBTOOLS:
            zh, en = _DRAW_ROW_LABELS[tool]
            row_host = QWidget(self._inner)
            row_host.setObjectName(f"ultraViewDraw{tool.title()}Row")
            row = QHBoxLayout(row_host)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            label = QLabel(zh)
            label.setObjectName(f"ultraViewDraw{tool.title()}Label")
            label.setToolTip(f"{zh} · {en}")
            row.addWidget(label)
            self._buttons[tool] = []
            for index, preset in enumerate(self._presets[tool]):
                button = _DrawPresetButton(tool, preset, index, row_host)
                button.clicked.connect(self._on_preset_clicked)
                self._buttons[tool].append(button)
                row.addWidget(button)
            row.addStretch(1)
            self.inner_layout().addWidget(row_host)
        for tool in (DRAW_ERASER, DRAW_LASSO):
            zh, en = _DRAW_ROW_LABELS[tool]
            row_host = QWidget(self._inner)
            row_host.setObjectName(f"ultraViewDraw{tool.title()}Row")
            row = QHBoxLayout(row_host)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            label = QLabel(zh)
            label.setObjectName(f"ultraViewDraw{tool.title()}Label")
            if tool == DRAW_ERASER:
                label.setToolTip(_ERASER_TOOLTIP)
            else:
                label.setToolTip(f"{zh} · {en}")
            row.addWidget(label)
            button = _DrawSessionButton(tool, row_host)
            button.clicked.connect(self._on_session_clicked)
            self._session_buttons[tool] = button
            row.addWidget(button)
            row.addStretch(1)
            self.inner_layout().addWidget(row_host)

    def _sync_checked(self) -> None:
        for tool, buttons in self._buttons.items():
            for index, button in enumerate(buttons):
                button.setChecked(tool == self._active_tool and index == self._active_preset)
        for tool, button in self._session_buttons.items():
            button.setChecked(tool == self._active_tool)

    def _on_preset_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_tool(
                str(sender.property("drawTool") or ""),
                int(sender.property("presetIndex") or 0),
            )
            self.close()

    def _on_session_clicked(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            self.choose_tool(str(sender.property("drawTool") or ""), 0)
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


class SelectionToolbar(QFrame):
    """40 px typed selection chrome. Page owns when it is shown."""

    format_requested = pyqtSignal(str, object)
    more_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewSelectionToolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(40)
        self._kind = ""
        self._compact = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._spine_bar = QFrame(self)
        self._spine_bar.setObjectName("ultraViewSignalSpine")
        self._spine_bar.setFixedSize(3, 18)
        self._spine_label = QLabel("NOTE")
        self._spine_label.setObjectName("ultraViewSignalSpineLabel")
        layout.addWidget(self._spine_bar)
        layout.addWidget(self._spine_label)
        self._body = QWidget(self)
        self._body_layout = QHBoxLayout(self._body)
        self._body_layout.setContentsMargins(4, 0, 0, 0)
        self._body_layout.setSpacing(2)
        layout.addWidget(self._body, 1)
        self._more = QToolButton(self)
        self._more.setObjectName("ultraViewSelectionToolbarMore")
        self._more.setText("⋯")
        self._more.setToolTip("更多")
        self._more.setAccessibleName("更多")
        self._more.clicked.connect(self.more_requested.emit)
        layout.addWidget(self._more)
        self._wide_buttons: list[QToolButton] = []
        self.set_kind("sticky")

    def kind(self) -> str:
        return self._kind

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        for button in self._wide_buttons:
            button.setVisible(not self._compact)

    def set_kind(self, kind: str) -> None:
        checked = str(kind or "sticky")
        self._kind = checked
        labels = {
            "sticky": "NOTE",
            "text": "TEXT",
            "shape": "SHAPE",
            "connector": "LINE",
            "stroke": "INK",
            "card": "FFT",
        }
        self._spine_label.setText(labels.get(checked, "MIXED"))
        self._spine_bar.setProperty("kind", "card" if checked == "card" else "author")
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._wide_buttons = []
        if checked == "sticky":
            self._add_body_button("palette", "色板")
            self._add_body_button("shape", "方形", wide=True)
            self._add_body_button("lock", "锁定")
        elif checked == "text":
            whole = "应用到整个文本框"
            self._add_body_button("font_role", "Sans", tooltip=f"字体 · {whole}")
            self._add_body_button("font_size", "14", tooltip=f"字号 · {whole}")
            self._add_body_button("bold", "B", tooltip=f"加粗 · {whole}", checkable=True)
            self._add_body_button("italic", "I", tooltip=f"斜体 · {whole}", checkable=True)
            self._add_body_button("underline", "U", tooltip=f"下划线 · {whole}", checkable=True)
            self._add_body_button("align", "左", tooltip=f"对齐 · {whole}")
            self._add_body_button("list_style", "列表", tooltip=f"列表 · {whole}", wide=True)
            self._add_body_button("text_palette", "A", tooltip=f"文字颜色 · {whole}", wide=True)
            self._add_body_button("fill_palette", "底", tooltip=f"底色 · {whole}", wide=True)
            self._add_body_button("link", "链接", tooltip=f"链接 · {whole}", wide=True)
            self._add_body_button("lock", "锁定", tooltip="锁定", wide=True)
        elif checked == "shape":
            self._add_body_button("shape", "类型", tooltip="切换形状，保留框/文字/样式")
            self._add_body_button("fill", "填充", tooltip="填充色")
            self._add_body_button("stroke", "描边", tooltip="描边色")
            self._add_body_button("width", "线宽", tooltip="描边宽度")
            self._add_body_button("dash", "线型", tooltip="实线或虚线")
            self._add_body_button("corner", "圆角", tooltip="圆角半径")
            self._add_body_button("text", "文字", tooltip="编辑形状内文字", wide=True)
            self._add_body_button("lock", "锁定", tooltip="锁定", wide=True)
        elif checked == "connector":
            self._add_body_button("route", "路径", tooltip="直线或正交折线")
            self._add_body_button("start_head", "起点", tooltip="起点箭头")
            self._add_body_button("end_head", "终点", tooltip="终点箭头")
            self._add_body_button("color", "颜色", tooltip="连接线颜色")
            self._add_body_button("width", "线宽", tooltip="线宽")
            self._add_body_button("dash", "线型", tooltip="实线或虚线")
            self._add_body_button("label", "标签", tooltip="编辑整线文字", wide=True)
            self._add_body_button("lock", "锁定", tooltip="锁定", wide=True)
        elif checked == "card":
            self._add_body_button("open", "打开源")
            self._add_body_button("sync", "同步", wide=True)
            self._add_body_button("fit", "Card Fit")
        elif checked == "stroke":
            self._add_body_button("tool", "钢笔", tooltip="钢笔或荧光笔")
            self._add_body_button("color", "颜色", tooltip="笔画颜色")
            self._add_body_button("width", "线宽", tooltip="笔画宽度")
            self._add_body_button("lock", "锁定", tooltip="锁定", wide=True)
        elif checked in {"mixed", "card_author"}:
            self._add_body_button("duplicate", "复制", tooltip="复制 · Ctrl/Cmd+D")
            self._add_body_button("lock", "锁定", tooltip="锁定")
        for index in range(self._body_layout.count()):
            widget = self._body_layout.itemAt(index).widget()
            if widget is not None:
                widget.show()
        self.set_compact(self._compact)

    def apply_capabilities(self, caps: SelectionCapabilities) -> None:
        """Rebuild controls from a typed resolver result."""
        self._kind = str(caps.kind or "mixed")
        self._spine_label.setText(str(caps.spine or "MIXED"))
        self._spine_bar.setProperty("kind", "card" if self._kind == "card" else "author")
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._wide_buttons = []
        for control in caps.controls:
            self._add_body_button(
                control.key,
                control.label,
                wide=control.wide,
                tooltip=control.tooltip or control.label,
                checkable=control.checkable,
            )
            button = self.button(control.key)
            if button is None:
                continue
            if control.checkable:
                button.setChecked(bool(control.checked))
            button.setEnabled(bool(control.enabled))
            if control.mixed:
                button.setText(INDETERMINATE)
        for index in range(self._body_layout.count()):
            widget = self._body_layout.itemAt(index).widget()
            if widget is not None:
                widget.show()
        self.set_compact(self._compact)

    def button(self, key: str) -> QToolButton | None:
        for index in range(self._body_layout.count()):
            widget = self._body_layout.itemAt(index).widget()
            if isinstance(widget, QToolButton) and widget.property("formatKey") == key:
                if widget.isHidden():
                    return None
                return widget
        return None

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
                button.setText("—")

    def _add_body_button(
        self,
        key: str,
        label: str,
        *,
        wide: bool = False,
        tooltip: str | None = None,
        checkable: bool = False,
    ) -> None:
        button = QToolButton(self._body)
        button.setObjectName(f"ultraViewSelection{key.title()}Button")
        button.setText(label)
        tip = str(tooltip or label)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.setCheckable(checkable)
        button.clicked.connect(self._emit_format)
        button.setProperty("formatKey", key)
        self._body_layout.addWidget(button)
        if wide:
            self._wide_buttons.append(button)

    def _emit_format(self) -> None:
        sender = self.sender()
        if isinstance(sender, QToolButton):
            key = str(sender.property("formatKey") or "")
            value: object = sender.isChecked() if sender.isCheckable() else True
            self.format_requested.emit(key, value)
