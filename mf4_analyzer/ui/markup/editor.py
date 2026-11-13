from __future__ import annotations

from typing import Callable

from PyQt5.QtCore import QLineF, QPointF, QRect, QRectF, QSettings, QSize, Qt, QTimer
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt5.QtWidgets import (
    QColorDialog,
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
    QMessageBox,
    QShortcut,
    QUndoStack,
    QVBoxLayout,
    QWidget,
)

import qtawesome as qta

from ...ui_kit.icons import icon_device_pixel_ratio
from ..command_registry import _unique_key_bindings
from ..image_utils import pixmap_as_device_pixels as _shared_pixmap_as_device_pixels

# Back-imports so that ``import mf4_analyzer.ui.markup.editor as editor_mod``
# and ``editor_mod.<name>`` continue to resolve after the split.
from .commands import (_AddItemCommand, _CropCommand, _MoveCommand,
                       _DeleteCommand, _GeometryCommand, _StyleCommand)
from .items import _ArrowAnnotationItem, _TextAnnotationItem
from .handles import (
    CROP_ROLE_PREFIX,
    bare_role,
    centered_scale_factor,
    corner_scale_factor,
    handle_hit_tolerance,
    handle_points,
    handle_scene_extent,
    nearest_within_tolerance,
    resize_rect,
)
from .serialization import deserialize_item, item_pen, serialize_item
from .toolbar import (
    STYLE_ICON_SIZE,
    build_style_panel,
    build_toolbar,
    color_button_qss,
    compact_tool_button_qss,
    tool_for_key,
)
from .view import _MarkupGraphicsView

_HIT_TOLERANCE = 12.0
_HIT_SCREEN_PX = 8.0
_HANDLE_HIT_SCREEN_PX = 14.0
_MIN_STROKE_WIDTH = 1
_MAX_STROKE_WIDTH = 24
# D-M5 content floor. The shared tool-window planner may still shrink this
# to the work-area budget; a decorated client cannot fall below D-W1's 200.
_CONTENT_MIN_W = 720
_CONTENT_MIN_H = 480
_TOOL_WINDOW_FLAGS = (
    Qt.Window
    | Qt.WindowTitleHint
    | Qt.WindowSystemMenuHint
    | Qt.WindowMinMaxButtonsHint
    | Qt.WindowCloseButtonHint
)
# Scene chrome is not an annotation. The view tags previews and the rubber band
# with the same data role this filter rejects.
_CHROME_ITEM_DATA = frozenset({
    "editor_handle",
    "crop_overlay",
    "rubber_band",
    "markup_preview",
})


def _pen_pad(pen: QPen, tolerance: float) -> float:
    width = pen.widthF()
    if width <= 0:
        width = 1.0
    return width / 2.0 + tolerance


def _point_in_ellipse(rect: QRectF, point: QPointF) -> bool:
    if rect.width() <= 0 or rect.height() <= 0:
        return False
    rx = rect.width() / 2.0
    ry = rect.height() / 2.0
    dx = (point.x() - rect.center().x()) / rx
    dy = (point.y() - rect.center().y()) / ry
    return dx * dx + dy * dy <= 1.0


def _rect_ring_contains(rect: QRectF, point: QPointF, pad: float) -> bool:
    pad = max(0.0, pad)
    outer = rect.adjusted(-pad, -pad, pad, pad)
    if not outer.contains(point):
        return False
    inner = rect.adjusted(pad, pad, -pad, -pad)
    if inner.width() <= 0 or inner.height() <= 0:
        return True
    return not inner.contains(point)


def _ellipse_ring_contains(rect: QRectF, point: QPointF, pad: float) -> bool:
    pad = max(0.0, pad)
    if not _point_in_ellipse(rect.adjusted(-pad, -pad, pad, pad), point):
        return False
    inner = rect.adjusted(pad, pad, -pad, -pad)
    if inner.width() <= 0 or inner.height() <= 0:
        return True
    return not _point_in_ellipse(inner, point)


def _is_hollow_shape(item) -> bool:
    """Rects and ellipses with no fill are stroke-only. Filled badges are not."""
    if not isinstance(item, (QGraphicsRectItem, QGraphicsEllipseItem)):
        return False
    brush = item.brush()
    if brush.style() == Qt.NoBrush:
        return True
    return brush.color().alpha() == 0


def _pixmap_as_device_pixels(pixmap: QPixmap) -> QPixmap:
    normalized = _shared_pixmap_as_device_pixels(pixmap)
    if normalized is None:
        return QPixmap(pixmap)
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
        "number": "ph.number-square-one",
    }
    _TOOL_ICON_COLOR = "#334155"          # idle glyph on the white chip
    _TOOL_ICON_COLOR_ACTIVE = "#ffffff"   # selected glyph on the solid accent chip
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
        super().__init__(parent, _TOOL_WINDOW_FLAGS)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
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
        self._toolbar = None
        self._capability_hint_shown = False
        self._user_close_request = False
        self._asking_close = False

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
        self._toolbar = self._build_toolbar()
        layout.addWidget(self._toolbar)
        layout.addWidget(self._view, 1)
        self._fit_to_work_area()
        self.setFocusPolicy(Qt.StrongFocus)
        self._install_history_shortcuts()

    def isModal(self) -> bool:  # noqa: N802 - QDialog seam the shared fitter calls
        """Independent tool window: do not clamp width to the host."""
        return False

    def showEvent(self, event):
        from ..drawers.batch._geometry import (
            arm_post_show_geometry_check,
            clear_tool_window_transient_parent,
        )

        super().showEvent(event)
        # raise_/activate can recreate the host transient-for link; clear it
        # here and again after present_independent_tool_window.
        clear_tool_window_transient_parent(self)
        if not self._initial_fit_done:
            self._initial_fit_done = True
            QTimer.singleShot(0, self.fit_to_window)
        self._maybe_show_capability_hint()
        arm_post_show_geometry_check(self)

    def _check_tool_window_geometry(self) -> None:
        from ..drawers.batch._geometry import finish_post_show_geometry_check

        finish_post_show_geometry_check(self, self._fit_to_work_area)

    def _preferred_client_size(self) -> tuple[int, int]:
        """Image at 100% plus the toolbar and the view frame."""
        scene = self._scene.sceneRect()
        image_w = max(1, int(round(scene.width())))
        image_h = max(1, int(round(scene.height())))
        bar_w = 0
        bar_h = 0
        bar = self._toolbar
        if bar is not None:
            hint = bar.sizeHint()
            bar_w = max(0, int(hint.width()))
            bar_h = max(0, int(hint.height()))
        frame = max(0, int(self._view.frameWidth())) * 2
        margin_w = 0
        margin_h = 0
        layout = self.layout()
        if layout is not None:
            margins = layout.contentsMargins()
            margin_w = int(margins.left()) + int(margins.right())
            margin_h = int(margins.top()) + int(margins.bottom())
        return (
            max(image_w, bar_w) + frame + margin_w,
            image_h + bar_h + frame + margin_h,
        )

    def _fit_to_work_area(self) -> None:
        from ..drawers.batch._geometry import fit_dialog_to_available_screen

        width, height = self._preferred_client_size()
        fit_dialog_to_available_screen(
            self,
            self.parentWidget(),
            width,
            height,
            min_w=_CONTENT_MIN_W,
            min_h=_CONTENT_MIN_H,
        )

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
            self._hint_toast = Toast(
                self,
                margin_provider=self._toast_bottom_chrome_clearance,
            )
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
        self._set_history_shortcuts_enabled(False)

    def _on_text_focus_out(self, item) -> None:
        # Defer so we never mutate the scene from inside the item's own event.
        self._set_history_shortcuts_enabled(True)
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
        # Success is the new clean state, so a following close does not ask again.
        self._undo_stack.setClean()
        self.close()
        return result

    def save_result(self) -> bool:
        path = self._get_save_path()
        if not path:
            return False
        saved = bool(self.render_result().save(path))
        if saved:
            self._undo_stack.setClean()
        return saved

    def request_close(self) -> bool:
        """User close from Esc's last step or the toolbar close button.

        A spontaneous title-bar close reaches the same confirm in ``closeEvent``.
        Returns True when the editor accepted the close.
        """
        self._user_close_request = True
        try:
            self.close()
        finally:
            self._user_close_request = False
        try:
            from PyQt5 import sip
            if sip.isdeleted(self):
                return True
        except (RuntimeError, TypeError):
            return True
        return not self.isVisible()

    def closeEvent(self, event):
        # Programmatic close() (finish path, test teardown) is not spontaneous
        # and does not prompt. The title bar closes the QWindow, which delivers
        # a spontaneous close event and must ask when the stack is dirty.
        if self._asking_close:
            event.ignore()
            return
        user_close = self._user_close_request or bool(event.spontaneous())
        if user_close and not self._undo_stack.isClean():
            decision = self._ask_close_decision()
            if decision == "cancel":
                event.ignore()
                return
            if decision == "copy":
                self.finish_and_copy()
                event.accept()
                super().closeEvent(event)
                return
        super().closeEvent(event)

    def _ask_close_decision(self) -> str:
        """Return ``copy``, ``discard``, or ``cancel``.

        Standard buttons so tests can click ``QMessageBox.Save`` /
        ``Discard`` / ``Cancel`` on ``QApplication.activeModalWidget()``.
        """
        self._asking_close = True
        try:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Question)
            box.setWindowTitle("关闭标注")
            box.setText("标注尚未完成复制。")
            box.setStandardButtons(
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            box.button(QMessageBox.Save).setText("完成复制")
            box.button(QMessageBox.Discard).setText("放弃")
            box.button(QMessageBox.Cancel).setText("取消")
            box.setDefaultButton(QMessageBox.Cancel)
            box.setEscapeButton(QMessageBox.Cancel)
            choice = box.exec_()
        finally:
            self._asking_close = False
        if choice == QMessageBox.Save:
            return "copy"
        if choice == QMessageBox.Discard:
            return "discard"
        return "cancel"

    def _get_save_path(self) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存标注图片",
            "",
            "PNG (*.png);;JPEG (*.jpg)",
        )
        return path

    # ---- chrome construction (implemented in toolbar.py) ----

    def _toast_bottom_chrome_clearance(self) -> int:
        """Clearance from the editor's own toolbar height (+ breathing gap)."""
        bar = getattr(self, "_toolbar", None)
        height = int(bar.height()) if bar is not None else 0
        if height <= 0:
            from ..widgets import Toast
            return Toast.DEFAULT_BOTTOM_MARGIN
        return height + 12

    def _build_toolbar(self) -> QWidget:
        return build_toolbar(self)

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
        self.refresh_handles()

    def actual_size(self) -> None:
        self.set_zoom(1.0)

    def fit_to_window(self) -> None:
        """Fit the image in the viewport without enlarging past 100%."""
        scene = self._scene.sceneRect()
        viewport = self._view.viewport().size()
        if (
            scene.width() <= 0
            or scene.height() <= 0
            or viewport.width() <= 1
            or viewport.height() <= 1
        ):
            self._view.setTransform(QTransform().scale(1.0, 1.0))
            self._zoom = 1.0
            self._auto_fit = True
            self.refresh_handles()
            return
        self._view.fitInView(scene, Qt.KeepAspectRatio)
        fitted = float(self._view.transform().m11())
        if not (0.0 < fitted <= 1.0):
            self._view.setTransform(QTransform().scale(1.0, 1.0))
            fitted = 1.0
        self._zoom = fitted
        self._auto_fit = True
        self.refresh_handles()

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
        width = int(width)
        if width < _MIN_STROKE_WIDTH:
            width = _MIN_STROKE_WIDTH
        elif width > _MAX_STROKE_WIDTH:
            width = _MAX_STROKE_WIDTH
        entries = []
        for item in self.selected_markup_items():
            if isinstance(item, QGraphicsTextItem):
                # Stroke width is meaningless for text; recording a style
                # change here would just litter the undo stack with no-ops.
                continue
            before = self._item_style(item)
            entries.append((item, before, (before[0], width)))
        self._stroke_width = width
        if entries:
            self._undo_stack.push(_StyleCommand(self, entries))
        self._refresh_style_button_icon()
        self._sync_style_panel()
        self.refresh_handles()

    def choose_custom_color(self) -> None:
        """Pick a session color, including alpha, from the palette's last entry."""
        color = QColorDialog.getColor(
            QColor(self._color),
            self,
            "更多颜色",
            QColorDialog.ShowAlphaChannel,
        )
        if not color.isValid():
            return
        self.set_color(QColor(color))

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
        return compact_tool_button_qss()

    def _color_button_qss(self) -> str:
        return color_button_qss()

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
            button.setIconSize(STYLE_ICON_SIZE)

    def _build_style_panel(self, menu):
        return build_style_panel(self, menu)

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

    def activate_markup_item(self, item) -> None:
        """Select the item just drawn and show its handles. The tool stays."""
        self.clear_selection()
        if item is None or item.scene() is not self._scene:
            return
        item.setSelected(True)
        self.refresh_handles()

    def select_markup_in_rect(self, rect: QRectF, *, additive: bool) -> None:
        """Rubber-band result. ``additive`` (Shift) keeps the previous selection."""
        found = []
        seen = set()
        for item in self._scene.items(
            rect, Qt.IntersectsItemShape, Qt.DescendingOrder
        ):
            markup = self._as_markup_item(item)
            if markup is None or id(markup) in seen:
                continue
            seen.add(id(markup))
            found.append(markup)
        if not additive:
            self.clear_selection()
        for markup in found:
            markup.setSelected(True)
        self.refresh_handles()

    def markup_item_at(self, point: QPointF):
        """Top-level markup whose visible stroke or filled body contains ``point``.

        Hollow rects and ellipses match the stroke plus tolerance, not the
        interior. Children of a ``QGraphicsItemGroup`` normalize to the group.
        """
        tol = self._screen_hit_tolerance()
        region = QRectF(point.x() - tol, point.y() - tol, tol * 2, tol * 2)
        candidates = self._ordered_markup(
            list(self._scene.items(point))
            + list(
                self._scene.items(
                    region, Qt.IntersectsItemShape, Qt.DescendingOrder
                )
            )
        )
        for markup in candidates:
            if self._counts_as_visible_hit(markup, point, tol):
                return markup
        return None

    def hollow_markup_containing(self, point: QPointF):
        """Selected-move target: interior of a hollow rect or ellipse.

        The hit is the top-level markup item, never a group child. Stroke hits
        are left to ``markup_item_at``.
        """
        seen = set()
        for item in self._scene.items(point):
            markup = self._as_markup_item(item)
            if markup is None or id(markup) in seen:
                continue
            seen.add(id(markup))
            if self._hollow_interior_contains(markup, point):
                return markup
        return None

    def _screen_hit_tolerance(self) -> float:
        return _HIT_SCREEN_PX / max(self._zoom, 0.1)

    def _ordered_markup(self, items):
        ordered = []
        seen = set()
        for item in items:
            markup = self._as_markup_item(item)
            if markup is None or id(markup) in seen:
                continue
            seen.add(id(markup))
            ordered.append(markup)
        return ordered

    def _counts_as_visible_hit(self, markup, point: QPointF, tol: float) -> bool:
        if isinstance(markup, QGraphicsItemGroup):
            return any(
                self._child_visible_hit(child, point, tol)
                for child in markup.childItems()
            )
        if _is_hollow_shape(markup):
            return self._near_hollow_stroke(markup, markup.mapFromScene(point), tol)
        # Non-hollow items are already limited to the point or its tolerance box.
        return True

    def _child_visible_hit(self, child, point: QPointF, tol: float) -> bool:
        local = child.mapFromScene(point)
        if _is_hollow_shape(child):
            return self._near_hollow_stroke(child, local, tol)
        if child.shape().contains(local):
            return True
        probe = QRectF(local.x() - tol, local.y() - tol, tol * 2, tol * 2)
        return child.shape().intersects(probe)

    def _near_hollow_stroke(self, item, local: QPointF, tol: float) -> bool:
        pad = _pen_pad(item.pen(), tol)
        rect = item.rect()
        if isinstance(item, QGraphicsEllipseItem):
            return _ellipse_ring_contains(rect, local, pad)
        return _rect_ring_contains(rect, local, pad)

    def _hollow_interior_contains(self, markup, point: QPointF) -> bool:
        shapes = (
            list(markup.childItems())
            if isinstance(markup, QGraphicsItemGroup)
            else [markup]
        )
        tol = self._screen_hit_tolerance()
        for shape in shapes:
            if not _is_hollow_shape(shape):
                continue
            local = shape.mapFromScene(point)
            rect = shape.rect()
            inside = (
                _point_in_ellipse(rect, local)
                if isinstance(shape, QGraphicsEllipseItem)
                else rect.contains(local)
            )
            if inside and not self._near_hollow_stroke(shape, local, tol):
                return True
        return False

    def _as_markup_item(self, item):
        while item is not None and item.parentItem() is not None:
            item = item.parentItem()
        if item is None or item is self._background_item:
            return None
        if item.data(0) in _CHROME_ITEM_DATA:
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
        tol = handle_hit_tolerance(_HANDLE_HIT_SCREEN_PX, self._zoom)
        centers = [h.sceneBoundingRect().center() for h in self._handles]
        index = nearest_within_tolerance(centers, point, tol)
        return None if index is None else self._handles[index]

    def _cursor_for(self, point: QPointF):
        handle = self.handle_at(point)
        if handle is not None:
            role = bare_role(getattr(handle, "_role", ""))
            return self._HANDLE_CURSORS.get(role, Qt.SizeAllCursor)
        if self._tool == "select":
            if self.markup_item_at(point) is not None:
                return Qt.SizeAllCursor
            hollow = self.hollow_markup_containing(point)
            if hollow is not None and hollow.isSelected():
                return Qt.SizeAllCursor
            return Qt.ArrowCursor
        return Qt.CrossCursor

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
        side = handle_scene_extent(self._zoom)
        handle = QGraphicsRectItem(-side / 2.0, -side / 2.0, side, side)
        handle.setData(0, "editor_handle")
        handle._role = role
        handle._target = target
        handle.setZValue(80)
        handle.setPos(point)
        pen = QPen(QColor("#1769e0"))
        pen.setCosmetic(True)
        pen.setWidthF(1.0)
        handle.setPen(pen)
        handle.setBrush(QBrush(QColor("#ffffff")))
        self._scene.addItem(handle)
        self._handles.append(handle)

    def _add_handles_for_item(self, item):
        if isinstance(item, QGraphicsRectItem):
            for role, point in handle_points(item.rect()).items():
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
        for role, point in handle_points(self._active_crop_rect).items():
            self._make_handle(point, CROP_ROLE_PREFIX + role, None)

    def _drag_crop_handle(self, role: str, point: QPointF):
        self.set_active_crop_rect(
            resize_rect(self._active_crop_rect, role, point)
        )

    def _drag_rect_handle(self, item: QGraphicsRectItem, role: str, point: QPointF):
        item.setRect(resize_rect(item.rect(), role, item.mapFromScene(point)))

    def _drag_scale_handle(self, item, point: QPointF):
        rect = item.boundingRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        if isinstance(item, QGraphicsItemGroup):
            # Badges grow about their centre so the number stays put.
            center = rect.center()
            scale = centered_scale_factor(
                item.mapToScene(center), point, rect.width(), rect.height()
            )
            item.setTransformOriginPoint(center)
            item.setScale(scale)
            return
        top_left = rect.topLeft()
        item.setTransformOriginPoint(top_left)
        scale = corner_scale_factor(
            item.mapToScene(top_left), point, rect.width(), rect.height()
        )
        if scale is None:
            return
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

    # ---- painted icons ----
    # These stay here rather than moving to toolbar.py with the rest of the
    # chrome: _icon_canvas resolves icon_device_pixel_ratio from this module's
    # globals, and tests/ui/test_color_swatch_hidpi.py patches it here to fake
    # a 2x screen. Re-exporting the function elsewhere copies the binding, not
    # the scope, so that patch would stop reaching the code under test.

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

    def _install_history_shortcuts(self) -> None:
        self._undo_shortcuts = []
        self._redo_shortcuts = []
        for seq in _unique_key_bindings(
            QKeySequence.Undo, fallback_to_standard=True
        ):
            shortcut = QShortcut(seq, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._on_undo_shortcut)
            self._undo_shortcuts.append(shortcut)
        for seq in _unique_key_bindings(
            QKeySequence.Redo, fallback_to_standard=True
        ):
            shortcut = QShortcut(seq, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(self._on_redo_shortcut)
            self._redo_shortcuts.append(shortcut)

    def _set_history_shortcuts_enabled(self, enabled: bool) -> None:
        for shortcut in (*self._undo_shortcuts, *self._redo_shortcuts):
            shortcut.setEnabled(enabled)

    def _text_item_is_editing(self) -> bool:
        focused = self._scene.focusItem()
        if not isinstance(focused, QGraphicsTextItem):
            return False
        return bool(focused.textInteractionFlags() & Qt.TextEditorInteraction)

    def _on_undo_shortcut(self) -> None:
        if self._text_item_is_editing():
            return
        self._undo_stack.undo()

    def _on_redo_shortcut(self) -> None:
        if self._text_item_is_editing():
            return
        self._undo_stack.redo()

    def keyPressEvent(self, event):
        # Q-2: Ctrl+Enter finishes and copies; plain Enter only confirms a crop.
        # Esc: draft → text edit → crop → selection → close. Dirty close asks 完成复制 / 放弃 / 取消.
        key = event.key()
        modifiers = event.modifiers()
        command = bool(modifiers & (Qt.ControlModifier | Qt.MetaModifier))

        if key == Qt.Key_Escape:
            event.accept()
            if self._view.cancel_in_progress_draft():
                return
            if self._text_item_is_editing():
                focused = self._scene.focusItem()
                if focused is not None:
                    focused.clearFocus()
                return
            if self.active_crop_rect().isValid():
                self.cancel_active_crop()
                return
            if self.selected_markup_items():
                self.clear_selection()
                return
            self.request_close()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            # Plain Enter only confirms an in-progress crop. While editing text
            # the text item consumes Enter as a newline before we reach here.
            if command:
                self.finish_and_copy()
                event.accept()
                return
            if self.active_crop_rect().isValid():
                self.apply_active_crop()
                event.accept()
                return
            super().keyPressEvent(event)
            return
        if command and key == Qt.Key_A:
            self.select_all_annotations()
            event.accept()
            return
        if command and key == Qt.Key_C:
            self.copy_selected_annotations()
            event.accept()
            return
        if command and key == Qt.Key_S:
            self.save_result()
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
            self.set_stroke_width(self._stroke_width - 1)
            event.accept()
            return
        if key == Qt.Key_BracketRight:
            self.set_stroke_width(self._stroke_width + 1)
            event.accept()
            return

        if not command:
            tool = tool_for_key(key)
            if tool is not None:
                self.set_tool(tool)
                event.accept()
                return
        super().keyPressEvent(event)
