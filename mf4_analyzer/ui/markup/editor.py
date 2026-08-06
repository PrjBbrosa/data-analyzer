from __future__ import annotations

from typing import Callable

from PyQt5.QtCore import QLineF, QPointF, QRect, QRectF, QSettings, QSize, Qt, QTimer
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QToolButton,
    QUndoStack,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

import qtawesome as qta

from ...ui_kit.icons import icon_device_pixel_ratio

# Back-imports so that ``import mf4_analyzer.ui.markup.editor as editor_mod``
# and ``editor_mod.<name>`` continue to resolve after the split.
from .commands import (_AddItemCommand, _CropCommand, _MoveCommand,
                       _DeleteCommand, _GeometryCommand, _StyleCommand)
from .items import _ArrowAnnotationItem, _TextAnnotationItem
from .serialization import deserialize_item, item_pen, serialize_item
from .view import _MarkupGraphicsView

_HIT_TOLERANCE = 12.0
_HIT_SCREEN_PX = 8.0
_HANDLE_HIT_SCREEN_PX = 14.0


def _pixmap_as_device_pixels(pixmap: QPixmap) -> QPixmap:
    copy = QPixmap(pixmap)
    if copy.isNull() or abs(copy.devicePixelRatioF() - 1.0) < 1e-9:
        return copy
    normalized = QPixmap.fromImage(copy.toImage())
    normalized.setDevicePixelRatio(1.0)
    return normalized


class MarkupEditor(QWidget):
    """Lightweight image markup editor backed by a QGraphicsScene."""

    TOOLS = ("select", "crop", "arrow", "line", "rect", "pen", "text", "number")
    _TOOL_ICONS = {
        "select": "ph.cursor",
        "crop": "ph.crop",
        "arrow": "ph.arrow-up-right",
        "line": "ph.line-segment",
        "rect": "ph.rectangle",
        "pen": "ph.pencil-simple",
        "text": "ph.text-t",
        "number": "ph.number-circle-one",
    }
    _TOOL_ICON_COLOR = "#1769e0"          # blue tool glyphs
    _TOOL_ICON_COLOR_ACTIVE = "#ffffff"   # contrast glyph on the selected chip
    _HANDLE_CURSORS = {
        "tl": Qt.SizeFDiagCursor,
        "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor,
        "bl": Qt.SizeBDiagCursor,
        "top": Qt.SizeVerCursor,
        "bottom": Qt.SizeVerCursor,
        "left": Qt.SizeHorCursor,
        "right": Qt.SizeHorCursor,
    }

    def __init__(
        self,
        pixmap: QPixmap,
        on_done: Callable[[QPixmap], None] | None = None,
        parent=None,
    ):
        super().__init__(parent, Qt.Window)
        self.setObjectName("MarkupEditor")
        self.setWindowTitle("图片标注")

        self._on_done = on_done
        self._current_pixmap = _pixmap_as_device_pixels(pixmap)
        self._tool = "select"
        self._color = QColor("#e53935")
        self._stroke_width = 4
        self._text_px = self._default_text_px(self._current_pixmap)
        self._number_radius = self._default_number_radius(self._current_pixmap)
        self._undo_stack = QUndoStack(self)
        self._zoom = 1.0
        self._handles = []
        self._active_crop_rect = QRectF()
        self._crop_item = None
        self._annotation_clipboard = []
        self._initial_fit_done = False
        self._auto_fit = True
        self._hint_settings = QSettings()
        self._hint_toast = None
        self._capability_hint_shown = False

        self._scene = QGraphicsScene(self)
        self._background_item = QGraphicsPixmapItem(self._current_pixmap)
        self._background_item.setZValue(0)
        self._background_item.setAcceptedMouseButtons(Qt.NoButton)
        self._background_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self._background_item.setFlag(QGraphicsItem.ItemIsMovable, False)
        self._scene.addItem(self._background_item)
        self._set_scene_to_pixmap_size()
        self._scene.selectionChanged.connect(self.refresh_handles)

        self._view = _MarkupGraphicsView(self)
        self._view.setObjectName("markupGraphicsView")
        self._view.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self._view.setDragMode(QGraphicsView.RubberBandDrag)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._view, 1)
        self.resize(960, 640)
        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_fit_done:
            self._initial_fit_done = True
            QTimer.singleShot(0, self.fit_to_window)
        self._maybe_show_capability_hint()

    def set_hint_settings(self, settings):
        """Inject a QSettings store (tests pass a temp INI)."""
        self._hint_settings = settings

    def _maybe_show_capability_hint(self):
        if self._capability_hint_shown:
            return
        self._capability_hint_shown = True
        from .. import hints
        state = hints.HintState(
            discovered=hints.load_discovered(self._hint_settings)
        )
        hint = hints.discovery_hint(state, scope="markup")
        if hint is None:
            return
        if self._hint_toast is None:
            from ..widgets import Toast
            self._hint_toast = Toast(self)
        self._hint_toast.show_message(hint.text, level="info")
        hints.mark_discovered(self._hint_settings, hint.id)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._initial_fit_done and self._auto_fit:
            QTimer.singleShot(0, self.fit_to_window)

    def add_rect_item(self, rect: QRectF) -> QGraphicsRectItem:
        item = QGraphicsRectItem(rect)
        item.setPen(self._pen())
        item.setBrush(QBrush(Qt.NoBrush))
        self._add_markup_item(item)
        return item

    def add_line_item(self, rect: QRectF) -> QGraphicsLineItem:
        item = QGraphicsLineItem(rect.left(), rect.top(), rect.right(), rect.bottom())
        item.setPen(self._pen())
        self._add_markup_item(item)
        return item

    def add_arrow_item(self, rect: QRectF) -> QGraphicsItem:
        item = _ArrowAnnotationItem(
            QPointF(rect.left(), rect.top()),
            QPointF(rect.right(), rect.bottom()),
            self._pen(),
            self._color,
        )
        self._add_markup_item(item)
        return item

    def add_path_item(self, path) -> QGraphicsPathItem:
        item = QGraphicsPathItem(path)
        item.setPen(self._pen())
        item.setTransformOriginPoint(item.boundingRect().topLeft())
        self._add_markup_item(item)
        return item

    @staticmethod
    def _default_text_px(pixmap: QPixmap) -> int:
        # Text lives in image-pixel space and is viewed fit-to-window, so a
        # fixed point size renders tiny on a chart copy (the source is grabbed
        # at 2x hi-DPI). Scale the default to ~3.5% of the copied image height,
        # clamped to a legible band; users can still fine-tune via the corner
        # scale handle.
        height = max(1, pixmap.height())
        return int(min(64, max(24, round(height * 0.035))))

    def _make_text_item(self, point: QPointF, text: str, color, font_px) -> _TextAnnotationItem:
        item = _TextAnnotationItem(text, self)
        item.setDefaultTextColor(QColor(color))
        font = item.font()
        font.setPixelSize(max(1, int(font_px)))
        item.setFont(font)
        item.setPos(point)
        item.setFlag(QGraphicsItem.ItemIsFocusable, True)
        return item

    def add_text_item(self, point: QPointF, text: str = "") -> QGraphicsTextItem:
        item = self._make_text_item(point, text, self._color, self._text_px)
        item.setZValue(1)
        item.setFlag(QGraphicsItem.ItemIsSelectable, True)
        item.setFlag(QGraphicsItem.ItemIsMovable, True)
        item._committed = False
        # Add to the scene immediately but defer the undo entry until the box
        # has content, so an empty box that is abandoned leaves no add/delete
        # noise in the undo history.
        self._scene.addItem(item)
        self._begin_text_edit(item)
        self.refresh_handles()
        return item

    def _begin_text_edit(self, item) -> None:
        item.setTextInteractionFlags(Qt.TextEditorInteraction)
        item.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self._view.setFocus(Qt.MouseFocusReason)
        item.setFocus(Qt.MouseFocusReason)
        self._scene.setFocusItem(item, Qt.MouseFocusReason)

    def _on_text_focus_out(self, item) -> None:
        # Defer so we never mutate the scene from inside the item's own event.
        QTimer.singleShot(0, lambda: self._finalize_text_item(item))

    def _finalize_text_item(self, item) -> None:
        if item.scene() is not self._scene:
            return
        has_text = bool(item.toPlainText().strip())
        committed = getattr(item, "_committed", False)
        if not has_text:
            if committed:
                self._undo_stack.push(_DeleteCommand(self._scene, [item]))
            else:
                self._scene.removeItem(item)
            self.refresh_handles()
            return
        if not committed:
            item._committed = True
            self._undo_stack.push(_AddItemCommand(self._scene, item))
        self.refresh_handles()

    def focus_text_item(self, item: QGraphicsTextItem):
        self.clear_selection()
        item.setSelected(True)
        self._begin_text_edit(item)
        self.refresh_handles()

    @staticmethod
    def _default_number_radius(pixmap: QPixmap) -> int:
        # Badges share the text scaling rationale: a fixed radius is tiny on a
        # hi-DPI chart copy. Track ~3% of image height, clamped to a legible
        # band.
        height = max(1, pixmap.height())
        return int(min(48, max(16, round(height * 0.03))))

    def _next_number(self) -> int:
        # Derive the next badge value from the badges already in the scene so
        # undo/redo and deletion never produce a duplicate number.
        used = []
        for item in self._markup_items():
            if isinstance(item, QGraphicsItemGroup):
                for child in item.childItems():
                    if isinstance(child, QGraphicsSimpleTextItem):
                        try:
                            used.append(int(child.text()))
                        except ValueError:
                            pass
        return (max(used) + 1) if used else 1

    def add_number_item(self, rect: QRectF) -> QGraphicsItemGroup:
        number = self._next_number()
        x = rect.left()
        y = rect.top()

        label = QGraphicsSimpleTextItem(str(number))
        label.setBrush(QBrush(Qt.white))
        font = label.font()
        font.setBold(True)
        font.setPixelSize(max(1, round(self._number_radius * 1.25)))
        label.setFont(font)
        text_rect = label.boundingRect()
        radius = max(
            self._stroke_width * 3,
            self._number_radius,
            text_rect.width() / 2 + 6,
            text_rect.height() / 2 + 4,
        )

        circle = QGraphicsEllipseItem(QRectF(-radius, -radius, radius * 2, radius * 2))
        circle.setPen(self._pen())
        circle.setBrush(QBrush(self._color))
        label.setPos(-text_rect.width() / 2, -text_rect.height() / 2)

        group = QGraphicsItemGroup()
        group.addToGroup(circle)
        group.addToGroup(label)
        group.setPos(QPointF(x, y))
        group.setTransformOriginPoint(group.boundingRect().center())
        self._add_markup_item(group)
        return group

    def apply_crop_rect(self, crop_rect: QRectF) -> None:
        bounds = QRectF(
            0, 0, self._current_pixmap.width(), self._current_pixmap.height()
        )
        rect = crop_rect.normalized().intersected(bounds)
        if rect.isEmpty():
            return

        qrect = QRect(
            int(round(rect.left())),
            int(round(rect.top())),
            int(round(rect.width())),
            int(round(rect.height())),
        ).intersected(self._current_pixmap.rect())
        if qrect.isEmpty():
            return

        self._undo_stack.push(_CropCommand(self, qrect))

    def render_result(self) -> QPixmap:
        self._scene.clearSelection()
        hidden_items = list(self._handles)
        if self._crop_item is not None:
            hidden_items.append(self._crop_item)
        previous_visibility = [(item, item.isVisible()) for item in hidden_items]
        for item, _visible in previous_visibility:
            item.setVisible(False)
        width = self._current_pixmap.width()
        height = self._current_pixmap.height()
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)

        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        source = QRectF(0, 0, width, height)
        self._scene.render(painter, QRectF(image.rect()), source)
        painter.end()
        for item, visible in previous_visibility:
            item.setVisible(visible)
        return QPixmap.fromImage(image)

    def finish_and_copy(self) -> QPixmap:
        result = self.render_result()
        if self._on_done is not None:
            self._on_done(result)
        self.close()
        return result

    def save_result(self) -> bool:
        path = self._get_save_path()
        if not path:
            return False
        return self.render_result().save(path)

    def _get_save_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存标注图片",
            "",
            "PNG (*.png);;JPEG (*.jpg)",
        )
        return path

    def _build_toolbar(self) -> QWidget:
        toolbar = QWidget(self)
        toolbar.setObjectName("markupEditorToolbar")
        layout = QGridLayout(toolbar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(0)

        def make_group(name: str):
            group = QWidget(toolbar)
            group.setObjectName(name)
            group_layout = QHBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(6)
            return group, group_layout

        left_group, left_layout = make_group("markupToolbarLeftGroup")
        center_group, center_layout = make_group("markupToolbarCenterGroup")
        right_group, right_layout = make_group("markupToolbarRightGroup")

        close_btn = QToolButton(left_group)
        close_btn.setObjectName("markupCloseButton")
        close_btn.setText("")
        close_btn.setIcon(qta.icon("ph.x", color="#dc2626"))
        close_btn.setIconSize(QSize(24, 24))
        close_btn.setToolTip("关闭 (Esc)")
        close_btn.setAutoRaise(True)
        close_btn.setFixedSize(QSize(44, 44))
        close_btn.setStyleSheet(
            "QToolButton#markupCloseButton {"
            "padding: 0px;"
            "border: 1px solid #f2b8b8; border-radius: 6px;"
            "background: #fffafa;"
            "}"
            "QToolButton#markupCloseButton:hover {"
            "background: #fee2e2; border-color: #dc2626;"
            "}"
        )
        close_btn.clicked.connect(self.close)
        left_layout.addWidget(close_btn)

        self._style_button = QToolButton(center_group)
        self._style_button.setObjectName("markupStyleButton")
        self._style_button.setToolTip("样式（颜色 / 线宽） · [ ] 调线宽")
        self._style_button.setAutoRaise(True)
        self._style_button.setIconSize(QSize(54, 24))
        self._style_button.setFixedSize(QSize(76, 44))
        self._style_button.setPopupMode(QToolButton.InstantPopup)
        self._style_button.setStyleSheet(self._compact_tool_button_qss())
        style_menu = QMenu(self._style_button)
        style_menu.setObjectName("markupStyleMenu")
        # Match the rounded-popup shell contract: QSS radius needs a transparent
        # menu window, and macOS needs native frame/shadow disabled so no square
        # backing remains behind the rounded style panel.
        style_menu.setWindowFlags(
            style_menu.windowFlags()
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        style_menu.setAttribute(Qt.WA_TranslucentBackground, True)
        # Make the menu a transparent shell: the rounded surface lives on the
        # inner panel below. Otherwise the global QMenu rule paints a square
        # white rect (radius 12 > padding) that pokes past the rounded corners.
        style_menu.setStyleSheet(
            "QMenu#markupStyleMenu { background: transparent; border: none; padding: 0px; }"
        )
        style_action = QWidgetAction(style_menu)
        style_action.setDefaultWidget(self._build_style_panel(style_menu))
        style_menu.addAction(style_action)
        self._style_button.setMenu(style_menu)
        center_layout.addWidget(self._style_button)
        self._refresh_style_button_icon()

        tool_group = QButtonGroup(toolbar)
        tool_group.setExclusive(True)
        labels = {
            "select": "选择",
            "crop": "裁剪",
            "arrow": "箭头",
            "line": "直线",
            "rect": "矩形",
            "pen": "画笔",
            "text": "文字",
            "number": "序号",
        }
        self._tool_buttons = {}
        for tool in self.TOOLS:
            active = tool == self._tool
            button = QToolButton(center_group)
            button.setText("")
            button.setIcon(self._tool_icon(tool, active))
            button.setIconSize(QSize(24, 24))
            button.setToolTip(f"{labels[tool]} ({tool[0].upper()})")
            button.setObjectName(f"markupTool_{tool}")
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setFixedSize(QSize(44, 44))
            button.setStyleSheet(self._compact_tool_button_qss())
            button.clicked.connect(
                lambda checked=False, name=tool: self.set_tool(name)
            )
            if active:
                button.setChecked(True)
            tool_group.addButton(button)
            center_layout.addWidget(button)
            self._tool_buttons[tool] = button

        undo_btn = QToolButton(center_group)
        undo_btn.setObjectName("markupUndoButton")
        undo_btn.setText("")
        undo_btn.setIcon(qta.icon("ph.arrow-counter-clockwise", color="#374151"))
        undo_btn.setIconSize(QSize(24, 24))
        undo_btn.setToolTip("撤销 (Ctrl+Z)")
        undo_btn.setAutoRaise(True)
        undo_btn.setFixedSize(QSize(44, 44))
        undo_btn.setStyleSheet(self._compact_tool_button_qss())
        undo_btn.clicked.connect(self._undo_stack.undo)
        center_layout.addWidget(undo_btn)

        redo_btn = QToolButton(center_group)
        redo_btn.setObjectName("markupRedoButton")
        redo_btn.setText("")
        redo_btn.setIcon(qta.icon("ph.arrow-clockwise", color="#374151"))
        redo_btn.setIconSize(QSize(24, 24))
        redo_btn.setToolTip("重做 (Ctrl+Y)")
        redo_btn.setAutoRaise(True)
        redo_btn.setFixedSize(QSize(44, 44))
        redo_btn.setStyleSheet(self._compact_tool_button_qss())
        redo_btn.clicked.connect(self._undo_stack.redo)
        center_layout.addWidget(redo_btn)

        save_btn = QPushButton("保存", right_group)
        save_btn.setObjectName("markupSaveButton")
        save_btn.clicked.connect(self.save_result)
        right_layout.addWidget(save_btn)

        done_btn = QPushButton("完成复制", right_group)
        done_btn.setObjectName("markupDoneButton")
        done_btn.setProperty("variant", "primary")
        done_btn.setStyleSheet(
            "QPushButton#markupDoneButton {"
            "background: #1769e0; color: white; border: none;"
            "border-radius: 6px; padding: 6px 14px; font-weight: 600;"
            "}"
            "QPushButton#markupDoneButton:hover { background: #0f5ec8; }"
        )
        done_btn.clicked.connect(self.finish_and_copy)
        right_layout.addWidget(done_btn)

        layout.addWidget(left_group, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(center_group, 0, 1, Qt.AlignCenter)
        layout.addWidget(right_group, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 0)
        layout.setColumnStretch(2, 1)
        return toolbar

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self._zoom * factor)

    def zoom_in(self) -> None:
        self.zoom_by(1.15)

    def zoom_out(self) -> None:
        self.zoom_by(1 / 1.15)

    def set_zoom(self, zoom: float) -> None:
        self._auto_fit = False
        self._zoom = min(8.0, max(0.1, float(zoom)))
        self._view.setTransform(QTransform().scale(self._zoom, self._zoom))

    def actual_size(self) -> None:
        self.set_zoom(1.0)

    def fit_to_window(self) -> None:
        self._view.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
        self._zoom = self._view.transform().m11()
        self._auto_fit = True

    def set_color(self, color: QColor) -> None:
        entries = []
        for item in self.selected_markup_items():
            before = self._item_style(item)
            entries.append((item, before, (QColor(color), before[1])))
        self._color = QColor(color)
        if entries:
            self._undo_stack.push(_StyleCommand(self, entries))
        self._refresh_style_button_icon()
        self._sync_style_panel()
        self.refresh_handles()

    def set_stroke_width(self, width: int) -> None:
        entries = []
        for item in self.selected_markup_items():
            if isinstance(item, QGraphicsTextItem):
                # Stroke width is meaningless for text; recording a style
                # change here would just litter the undo stack with no-ops.
                continue
            before = self._item_style(item)
            entries.append((item, before, (before[0], int(width))))
        self._stroke_width = int(width)
        if entries:
            self._undo_stack.push(_StyleCommand(self, entries))
        self._refresh_style_button_icon()
        self._sync_style_panel()
        self.refresh_handles()

    def set_tool(self, tool: str) -> None:
        if tool not in self.TOOLS:
            raise ValueError(f"unknown markup tool: {tool}")
        self._tool = tool
        self._view.setDragMode(
            QGraphicsView.RubberBandDrag if tool == "select" else QGraphicsView.NoDrag
        )
        if tool != "crop":
            self.cancel_active_crop()
        self._sync_tool_buttons()

    def _set_scene_to_pixmap_size(self) -> None:
        self._scene.setSceneRect(self._background_item.boundingRect())

    def _pen(self) -> QPen:
        pen = QPen(self._color, self._stroke_width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def _compact_tool_button_qss(self) -> str:
        return (
            "QToolButton {"
            "padding: 0px;"
            "border: 1px solid #c9d6ea; border-radius: 6px;"
            "background: #ffffff;"
            "}"
            "QToolButton:hover { background: #eef4ff; border-color: #1769e0; }"
            # Selected tool: solid accent fill behind the white (contrast) glyph.
            "QToolButton:checked { background: #1769e0; border-color: #1769e0; }"
        )

    def _color_button_qss(self) -> str:
        # Same rounded chip as the tools; selected swatch gets a blue ring
        # (not a fill) so the colour stays readable.
        return (
            "QToolButton {"
            "padding: 0px;"
            "border: 1px solid #c9d6ea; border-radius: 6px;"
            "background: #ffffff;"
            "}"
            "QToolButton:hover { background: #eef4ff; border-color: #1769e0; }"
            "QToolButton:checked { border: 2px solid #1769e0; background: #eaf2ff; }"
        )

    def _tool_icon(self, tool: str, active: bool) -> QIcon:
        color = self._TOOL_ICON_COLOR_ACTIVE if active else self._TOOL_ICON_COLOR
        return qta.icon(self._TOOL_ICONS[tool], color=color)

    def _sync_tool_buttons(self) -> None:
        for tool, button in getattr(self, "_tool_buttons", {}).items():
            active = tool == self._tool
            if button.isChecked() != active:
                button.setChecked(active)
            button.setIcon(self._tool_icon(tool, active))

    def _sync_style_panel(self) -> None:
        # Reflect the current colour/width in the popup so the active choice is
        # visible (rounded chip + selected highlight, like the tool buttons).
        target = QColor(self._color).name().lower()
        for hexname, button in getattr(self, "_color_buttons", {}).items():
            button.setChecked(hexname == target)
        for width, button in getattr(self, "_width_buttons", {}).items():
            active = width == self._stroke_width
            button.setChecked(active)
            button.setIcon(self._width_icon(width, "#ffffff" if active else "#374151"))

    def _add_markup_item(self, item):
        item.setZValue(1)
        item.setFlag(QGraphicsItem.ItemIsSelectable, True)
        item.setFlag(QGraphicsItem.ItemIsMovable, True)
        self._undo_stack.push(_AddItemCommand(self._scene, item))
        self.refresh_handles()

    def _apply_style_to(self, item, color, width):
        pen = QPen(QColor(color), int(width))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if isinstance(item, QGraphicsRectItem):
            item.setPen(pen)
        elif isinstance(item, QGraphicsLineItem):
            item.setPen(pen)
        elif isinstance(item, QGraphicsPathItem):
            item.setPen(pen)
        elif isinstance(item, QGraphicsTextItem):
            item.setDefaultTextColor(QColor(color))
        elif isinstance(item, _ArrowAnnotationItem):
            item.set_pen(pen, QColor(color))
        elif isinstance(item, QGraphicsItemGroup):
            for child in item.childItems():
                if isinstance(child, QGraphicsEllipseItem):
                    child.setPen(pen)
                    child.setBrush(QBrush(QColor(color)))

    def _refresh_style_button_icon(self):
        button = getattr(self, "_style_button", None)
        if button is not None:
            button.setIcon(self._style_button_icon(self._color, self._stroke_width))
            button.setIconSize(QSize(54, 24))

    def _build_style_panel(self, menu):
        panel = QWidget()
        panel.setObjectName("markupStylePanel")
        # The panel is the only visible surface inside the transparent menu
        # shell, so it carries the rounded background/border itself.
        panel.setAttribute(Qt.WA_StyledBackground, True)
        panel.setStyleSheet(
            "QWidget#markupStylePanel {"
            "background: #ffffff;"
            "border: 1px solid #c9d6ea;"
            "border-radius: 10px;"
            "}"
        )
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        self._color_buttons = {}
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        for name, color in (
            ("红色", "#e53935"),
            ("橙色", "#f97316"),
            ("黄色", "#eab308"),
            ("绿色", "#059669"),
            ("蓝色", "#2563eb"),
            ("黑色", "#111827"),
        ):
            button = QToolButton(panel)
            button.setObjectName(f"markupColor_{color[1:]}")
            button.setIcon(self._color_icon(QColor(color)))
            button.setIconSize(QSize(18, 18))
            button.setToolTip(name)
            button.setAutoRaise(True)
            button.setCheckable(True)
            button.setFixedSize(QSize(30, 30))
            button.setStyleSheet(self._color_button_qss())
            button.clicked.connect(
                lambda checked=False, c=color, m=menu: (
                    self.set_color(QColor(c)),
                    m.hide(),
                )
            )
            color_row.addWidget(button)
            self._color_buttons[color.lower()] = button
        outer.addLayout(color_row)

        self._width_buttons = {}
        width_row = QHBoxLayout()
        width_row.setSpacing(8)
        for width in (2, 4, 6, 8):
            button = QToolButton(panel)
            button.setObjectName(f"markupWidth_{width}")
            button.setIcon(self._width_icon(width))
            button.setIconSize(QSize(24, 18))
            button.setToolTip(f"{width}px")
            button.setAutoRaise(True)
            button.setCheckable(True)
            button.setFixedSize(QSize(34, 30))
            button.setStyleSheet(self._compact_tool_button_qss())
            button.clicked.connect(
                lambda checked=False, w=width, m=menu: (
                    self.set_stroke_width(w),
                    m.hide(),
                )
            )
            width_row.addWidget(button)
            self._width_buttons[width] = button
        outer.addLayout(width_row)
        self._sync_style_panel()
        return panel

    def selected_markup_items(self):
        items = []
        seen = set()
        for item in self._scene.selectedItems():
            markup = self._as_markup_item(item)
            if markup is None or id(markup) in seen:
                continue
            seen.add(id(markup))
            items.append(markup)
        return items

    def clear_selection(self):
        for item in self.selected_markup_items():
            item.setSelected(False)
        self.refresh_handles()

    def select_all_annotations(self):
        for item in self._markup_items():
            item.setSelected(True)
        self.refresh_handles()

    def move_selection_by(self, dx: float, dy: float):
        moves = [
            (
                item,
                QPointF(item.pos()),
                QPointF(item.pos().x() + dx, item.pos().y() + dy),
            )
            for item in self.selected_markup_items()
        ]
        if moves:
            self._undo_stack.push(_MoveCommand(moves))
        self.refresh_handles()

    def delete_selected_annotations(self):
        items = [
            item for item in self.selected_markup_items()
            if item.scene() is self._scene
        ]
        if items:
            self._undo_stack.push(_DeleteCommand(self._scene, items))
        self.refresh_handles()

    def copy_selected_annotations(self):
        self._annotation_clipboard = [
            self._serialize_item(item) for item in self.selected_markup_items()
        ]

    def paste_annotations(self):
        payloads = [payload for payload in self._annotation_clipboard if payload is not None]
        if not payloads:
            return []
        self.clear_selection()
        pasted = []
        self._undo_stack.beginMacro("粘贴标注")
        for payload in payloads:
            item = self._deserialize_item(payload)
            if item is None:
                continue
            item.moveBy(12, 12)
            item.setSelected(True)
            pasted.append(item)
        self._undo_stack.endMacro()
        self.refresh_handles()
        return pasted

    def markup_item_at(self, point: QPointF):
        exact = self._first_markup(self._scene.items(point))
        if exact is not None:
            return exact
        tol = _HIT_SCREEN_PX / max(self._zoom, 0.1)
        region = QRectF(point.x() - tol, point.y() - tol, tol * 2, tol * 2)
        return self._first_markup(
            self._scene.items(region, Qt.IntersectsItemShape, Qt.DescendingOrder)
        )

    def _first_markup(self, items):
        seen = set()
        for item in items:
            markup = self._as_markup_item(item)
            if markup is None or id(markup) in seen:
                continue
            seen.add(id(markup))
            return markup
        return None

    def _as_markup_item(self, item):
        while item is not None and item.parentItem() is not None:
            item = item.parentItem()
        if item is None or item is self._background_item:
            return None
        if item.data(0) in {"editor_handle", "crop_overlay"}:
            return None
        return item

    def set_active_crop_rect(self, rect: QRectF):
        rect = rect.normalized().intersected(self._scene.sceneRect())
        if rect.isEmpty():
            return
        self._active_crop_rect = QRectF(rect)
        if self._crop_item is None:
            self._crop_item = QGraphicsRectItem()
            self._crop_item.setData(0, "crop_overlay")
            self._crop_item.setZValue(40)
            self._crop_item.setPen(QPen(QColor("#1769e0"), 1, Qt.DashLine))
            self._crop_item.setBrush(QBrush(QColor(23, 105, 224, 38)))
            self._crop_item.setAcceptedMouseButtons(Qt.NoButton)
            self._scene.addItem(self._crop_item)
        self._crop_item.setRect(self._active_crop_rect)
        self.refresh_handles()

    def active_crop_rect(self):
        return QRectF(self._active_crop_rect)

    def apply_active_crop(self):
        if not self._active_crop_rect.isValid() or self._active_crop_rect.isEmpty():
            return
        rect = QRectF(self._active_crop_rect)
        self.cancel_active_crop()
        self.apply_crop_rect(rect)

    def cancel_active_crop(self):
        self._active_crop_rect = QRectF()
        if self._crop_item is not None and self._crop_item.scene() is self._scene:
            self._scene.removeItem(self._crop_item)
        self._crop_item = None
        self.refresh_handles()

    def handle_at(self, point: QPointF):
        tol = _HANDLE_HIT_SCREEN_PX / max(self._zoom, 0.1)
        nearest = None
        nearest_distance = None
        for handle in self._handles:
            center = handle.sceneBoundingRect().center()
            hit_rect = QRectF(
                center.x() - tol,
                center.y() - tol,
                tol * 2,
                tol * 2,
            )
            if hit_rect.contains(point):
                distance = (center.x() - point.x()) ** 2 + (center.y() - point.y()) ** 2
                if nearest_distance is None or distance < nearest_distance:
                    nearest = handle
                    nearest_distance = distance
        return nearest

    def _cursor_for(self, point: QPointF):
        handle = self.handle_at(point)
        if handle is not None:
            role = getattr(handle, "_role", "")
            if role.startswith("crop_"):
                role = role[5:]
            return self._HANDLE_CURSORS.get(role, Qt.SizeAllCursor)
        if self.markup_item_at(point) is not None:
            return Qt.SizeAllCursor
        return Qt.ArrowCursor if self._tool == "select" else Qt.CrossCursor

    def drag_handle(self, handle, point: QPointF):
        role = getattr(handle, "_role", "")
        target = getattr(handle, "_target", None)
        if role.startswith("crop_"):
            self._drag_crop_handle(role, point)
        elif isinstance(target, QGraphicsRectItem):
            self._drag_rect_handle(target, role, point)
        elif isinstance(target, QGraphicsLineItem):
            local = target.mapFromScene(point)
            line = target.line()
            if role == "p1":
                line.setP1(local)
            else:
                line.setP2(local)
            target.setLine(line)
        elif isinstance(target, _ArrowAnnotationItem):
            target.set_endpoint(role, target.mapFromScene(point))
        elif isinstance(target, (QGraphicsTextItem, QGraphicsPathItem, QGraphicsItemGroup)):
            self._drag_scale_handle(target, point)
        self.refresh_handles()

    def refresh_handles(self):
        self._clear_handles()
        if self._tool == "crop" and self._crop_item is not None:
            self._add_crop_handles()
            return
        for item in self.selected_markup_items():
            self._add_handles_for_item(item)

    def _clear_handles(self):
        for handle in self._handles:
            if handle.scene() is self._scene:
                self._scene.removeItem(handle)
        self._handles = []

    def _make_handle(self, point: QPointF, role: str, target=None):
        handle = QGraphicsRectItem(-4, -4, 8, 8)
        handle.setData(0, "editor_handle")
        handle._role = role
        handle._target = target
        handle.setZValue(80)
        handle.setPos(point)
        handle.setPen(QPen(QColor("#1769e0"), 1))
        handle.setBrush(QBrush(QColor("#ffffff")))
        self._scene.addItem(handle)
        self._handles.append(handle)

    def _add_handles_for_item(self, item):
        if isinstance(item, QGraphicsRectItem):
            rect = item.rect()
            points = {
                "tl": rect.topLeft(),
                "top": QPointF(rect.center().x(), rect.top()),
                "tr": rect.topRight(),
                "right": QPointF(rect.right(), rect.center().y()),
                "br": rect.bottomRight(),
                "bottom": QPointF(rect.center().x(), rect.bottom()),
                "bl": rect.bottomLeft(),
                "left": QPointF(rect.left(), rect.center().y()),
            }
            for role, point in points.items():
                self._make_handle(item.mapToScene(point), role, item)
        elif isinstance(item, QGraphicsLineItem):
            line = item.line()
            self._make_handle(item.mapToScene(line.p1()), "p1", item)
            self._make_handle(item.mapToScene(line.p2()), "p2", item)
        elif isinstance(item, _ArrowAnnotationItem):
            self._make_handle(item.mapToScene(item.start), "p1", item)
            self._make_handle(item.mapToScene(item.end), "p2", item)
        elif isinstance(item, QGraphicsTextItem):
            self._add_scale_handle(item)
        elif isinstance(item, (QGraphicsPathItem, QGraphicsItemGroup)):
            self._add_scale_handle(item)

    def _add_scale_handle(self, item):
        rect = item.boundingRect()
        self._make_handle(item.mapToScene(rect.bottomRight()), "scale", item)

    def _add_crop_handles(self):
        rect = self._active_crop_rect
        for role, point in {
            "crop_tl": rect.topLeft(),
            "crop_top": QPointF(rect.center().x(), rect.top()),
            "crop_tr": rect.topRight(),
            "crop_right": QPointF(rect.right(), rect.center().y()),
            "crop_br": rect.bottomRight(),
            "crop_bottom": QPointF(rect.center().x(), rect.bottom()),
            "crop_bl": rect.bottomLeft(),
            "crop_left": QPointF(rect.left(), rect.center().y()),
        }.items():
            self._make_handle(point, role, None)

    def _drag_crop_handle(self, role: str, point: QPointF):
        rect = QRectF(self._active_crop_rect)
        if role == "crop_tl":
            rect.setTopLeft(point)
        elif role == "crop_top":
            rect.setTop(point.y())
        elif role == "crop_tr":
            rect.setTopRight(point)
        elif role == "crop_right":
            rect.setRight(point.x())
        elif role == "crop_br":
            rect.setBottomRight(point)
        elif role == "crop_bottom":
            rect.setBottom(point.y())
        elif role == "crop_bl":
            rect.setBottomLeft(point)
        elif role == "crop_left":
            rect.setLeft(point.x())
        self.set_active_crop_rect(rect.normalized())

    def _drag_rect_handle(self, item: QGraphicsRectItem, role: str, point: QPointF):
        local = item.mapFromScene(point)
        rect = QRectF(item.rect())
        if role == "tl":
            rect.setTopLeft(local)
        elif role == "top":
            rect.setTop(local.y())
        elif role == "tr":
            rect.setTopRight(local)
        elif role == "right":
            rect.setRight(local.x())
        elif role == "br":
            rect.setBottomRight(local)
        elif role == "bottom":
            rect.setBottom(local.y())
        elif role == "bl":
            rect.setBottomLeft(local)
        elif role == "left":
            rect.setLeft(local.x())
        item.setRect(rect.normalized())

    def _drag_scale_handle(self, item, point: QPointF):
        rect = item.boundingRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        if isinstance(item, QGraphicsItemGroup):
            center = rect.center()
            center_scene = item.mapToScene(center)
            half_width = max(rect.width() / 2.0, 0.001)
            half_height = max(rect.height() / 2.0, 0.001)
            scale = max(
                abs(point.x() - center_scene.x()) / half_width,
                abs(point.y() - center_scene.y()) / half_height,
                0.25,
            )
            item.setTransformOriginPoint(center)
            item.setScale(scale)
            return
        top_left = rect.topLeft()
        top_left_scene = item.mapToScene(top_left)
        item.setTransformOriginPoint(top_left)
        candidates = []
        if rect.width() > 0.001:
            candidates.append((point.x() - top_left_scene.x()) / rect.width())
        if rect.height() > 0.001:
            candidates.append((point.y() - top_left_scene.y()) / rect.height())
        if not candidates:
            return
        scale = max(max(candidates), 0.25)
        current = float(item.scale())
        if abs(scale - current) < 1e-9:
            scale = current
        item.setScale(scale)

    def _item_style(self, item):
        if isinstance(item, QGraphicsTextItem):
            return (QColor(item.defaultTextColor()), self._stroke_width)
        pen = self._item_pen(item)
        if pen is not None:
            return (QColor(pen.color()), pen.width())
        return (QColor(self._color), self._stroke_width)

    def _geometry_snapshot(self, item):
        if isinstance(item, QGraphicsRectItem):
            return ("rect", QRectF(item.rect()), QPointF(item.pos()))
        if isinstance(item, _ArrowAnnotationItem):
            return (
                "arrow",
                QPointF(item.start),
                QPointF(item.end),
                QPointF(item.pos()),
            )
        if isinstance(item, QGraphicsLineItem):
            return ("line", QLineF(item.line()), QPointF(item.pos()))
        return ("scale", float(item.scale()), QPointF(item.pos()))

    def _restore_geometry(self, item, snapshot):
        kind = snapshot[0]
        if kind == "rect":
            item.setRect(snapshot[1])
            item.setPos(snapshot[2])
        elif kind == "arrow":
            item.prepareGeometryChange()
            item.start = QPointF(snapshot[1])
            item.end = QPointF(snapshot[2])
            item.setPos(snapshot[3])
            item.update()
        elif kind == "line":
            item.setLine(snapshot[1])
            item.setPos(snapshot[2])
        else:
            item.setScale(snapshot[1])
            item.setPos(snapshot[2])
        self.refresh_handles()

    def _markup_items(self):
        items = []
        seen = set()
        for item in self._scene.items():
            markup = self._as_markup_item(item)
            if markup is None or markup.scene() is not self._scene:
                continue
            if id(markup) in seen:
                continue
            seen.add(id(markup))
            items.append(markup)
        return items

    def _item_positions(self):
        return {item: QPointF(item.pos()) for item in self._markup_items()}

    def _apply_crop_state(self, pixmap: QPixmap, positions):
        self._current_pixmap = _pixmap_as_device_pixels(pixmap)
        self._background_item.setPixmap(self._current_pixmap)
        for item, pos in positions.items():
            if item.scene() is self._scene:
                item.setPos(pos)
        self._set_scene_to_pixmap_size()
        self.fit_to_window()

    # ---- clipboard payloads (implemented in serialization.py) ----

    def _serialize_item(self, item):
        return serialize_item(
            item,
            default_color=self._color,
            default_width=self._stroke_width,
            default_text_px=self._text_px,
            default_number_radius=self._number_radius,
        )

    def _deserialize_item(self, payload):
        return deserialize_item(self, payload)

    def _item_pen(self, item):
        return item_pen(item)

    @staticmethod
    def _icon_canvas(w: int, h: int):
        """Allocate a transparent icon buffer at the screen's device pixel
        ratio so the painted shape stays crisp on Retina instead of being a 1x
        bitmap that Qt upscales. Draw with LOGICAL ``w``/``h`` coordinates."""
        ratio = icon_device_pixel_ratio()
        pix = QPixmap(round(w * ratio), round(h * ratio))
        pix.setDevicePixelRatio(ratio)
        pix.fill(Qt.transparent)
        return pix

    def _color_icon(self, color: QColor):
        pix = self._icon_canvas(18, 18)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#d0d7e2"), 1))
        painter.setBrush(QBrush(color))
        painter.drawEllipse(QRectF(3, 3, 12, 12))
        painter.end()
        return QIcon(pix)

    def _width_icon(self, width: int, color: str = "#374151"):
        pix = self._icon_canvas(24, 18)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(4, 9), QPointF(20, 9))
        painter.end()
        return QIcon(pix)

    def _style_button_icon(self, color: QColor, width: int):
        pix = self._icon_canvas(44, 18)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#d0d7e2"), 1))
        painter.setBrush(QBrush(QColor(color)))
        painter.drawEllipse(QRectF(2, 4, 11, 11))
        painter.setPen(
            QPen(QColor("#374151"), max(1, int(width)), Qt.SolidLine, Qt.RoundCap)
        )
        painter.drawLine(QPointF(20, 9), QPointF(40, 9))
        painter.end()
        return QIcon(pix)

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        command = bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))

        if key == Qt.Key_Escape:
            focused = self._scene.focusItem()
            if isinstance(focused, QGraphicsTextItem):
                focused.clearFocus()
            elif self.active_crop_rect().isValid():
                self.cancel_active_crop()
            else:
                self.close()
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            # Enter never finishes the copy (too easy to fire by accident); it
            # only confirms an in-progress crop. While editing text the text
            # item consumes Enter as a newline before we ever reach here.
            if self.active_crop_rect().isValid():
                self.apply_active_crop()
                event.accept()
                return
            super().keyPressEvent(event)
            return
        if command and key == Qt.Key_Z:
            self._undo_stack.undo()
            event.accept()
            return
        if command and key == Qt.Key_Y:
            self._undo_stack.redo()
            event.accept()
            return
        if command and key == Qt.Key_A:
            self.select_all_annotations()
            event.accept()
            return
        if command and key == Qt.Key_C:
            self.copy_selected_annotations()
            event.accept()
            return
        if command and key == Qt.Key_V:
            self.paste_annotations()
            event.accept()
            return
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected_annotations()
            event.accept()
            return
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if modifiers & Qt.ShiftModifier else 1
            dx = (-step if key == Qt.Key_Left else step if key == Qt.Key_Right else 0)
            dy = (-step if key == Qt.Key_Up else step if key == Qt.Key_Down else 0)
            self.move_selection_by(dx, dy)
            event.accept()
            return
        if command and key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_in()
            event.accept()
            return
        if command and key == Qt.Key_Minus:
            self.zoom_out()
            event.accept()
            return
        if key == Qt.Key_0:
            self.actual_size()
            event.accept()
            return
        if key == Qt.Key_BracketLeft:
            self.set_stroke_width(max(1, self._stroke_width - 1))
            event.accept()
            return
        if key == Qt.Key_BracketRight:
            self.set_stroke_width(self._stroke_width + 1)
            event.accept()
            return

        shortcuts = {
            Qt.Key_V: "select",
            Qt.Key_A: "arrow",
            Qt.Key_L: "line",
            Qt.Key_R: "rect",
            Qt.Key_P: "pen",
            Qt.Key_T: "text",
            Qt.Key_N: "number",
            Qt.Key_C: "crop",
        }
        if key in shortcuts and not command:
            self.set_tool(shortcuts[key])
            event.accept()
            return
        super().keyPressEvent(event)
