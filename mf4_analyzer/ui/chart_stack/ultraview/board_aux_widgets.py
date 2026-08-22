"""UltraView auxiliary board chrome: minimap, scroll host, overview, focus.

These widgets project or navigate an existing Board. They do not own the
free-grid host or mutate BoardState.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from PyQt5.QtCore import QPoint, QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
)

from mf4_analyzer.ui.ultraview_state import (
    LAYOUT_MODE_FREE_GRID,
    FreeGridPlacement,
    GridBounds,
    UltraViewBoardState,
    UltraViewRef,
)

from .compositor import compose_board, composed_slot_rects
from .free_grid import (
    GridMetrics,
    export_grid_metrics,
    rect_to_pixels,
    screen_grid_metrics,
)
from .layouts import (
    BASE_BOARD_SIZE,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    content_rect,
    slot_rects,
)
from .card_widgets import CardViewModel
from .widgets_common import STATUS_LABELS_ZH


class FreeGridMinimap(QFrame):
    """Cheap free-grid navigator; it draws bounds only, never preview pixels."""

    viewport_requested = pyqtSignal(QRect)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewFreeGridMinimap")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(168, 112)
        self._metrics: GridMetrics | None = None
        self._placements: tuple[FreeGridPlacement, ...] = ()
        self._viewport = QRect()
        self._workspace_extent: GridBounds | None = None

    def set_projection(
        self,
        metrics: GridMetrics,
        placements: Sequence[FreeGridPlacement],
        viewport: QRect,
        workspace_extent: GridBounds | None = None,
    ) -> None:
        self._metrics = metrics
        self._placements = tuple(placements)
        self._viewport = QRect(viewport)
        self._workspace_extent = (
            workspace_extent
            if workspace_extent is not None and not workspace_extent.empty()
            else None
        )
        self.update()

    def _origin_offset(self) -> tuple[int, int]:
        bounds = self._workspace_extent
        return (bounds.column, bounds.row) if bounds is not None else (0, 0)

    def _canvas_size(self) -> tuple[int, int]:
        metrics = self._metrics
        if metrics is None or self._workspace_extent is None:
            return (
                metrics.board_width if metrics is not None else 1,
                metrics.board_height if metrics is not None else 1,
            )
        bounds = self._workspace_extent
        columns = max(1, bounds.column_span)
        rows = max(1, bounds.row_span)
        padding = metrics.exact_padding()
        pitch_x, pitch_y = metrics.exact_pitch()
        cell_w, cell_h = metrics.exact_cell()
        return (
            int(round(2 * padding + (columns - 1) * pitch_x + cell_w)),
            int(round(2 * padding + (rows - 1) * pitch_y + cell_h)),
        )

    def _scale(self) -> tuple[float, float]:
        if self._metrics is None:
            return 1.0, 1.0
        canvas_width, canvas_height = self._canvas_size()
        return (
            max(1, self.width() - 12) / float(max(1, canvas_width)),
            max(1, self.height() - 12) / float(max(1, canvas_height)),
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._metrics is None:
            return
        sx, sy = self._scale()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.fillRect(self.rect(), QColor("#ffffff"))
            painter.setPen(QColor("#d7dee8"))
            painter.drawRect(5, 5, self.width() - 10, self.height() - 10)
            painter.setBrush(QColor("#bcd5f5"))
            painter.setPen(QColor("#6da3d9"))
            for item in self._placements:
                x, y, width, height = rect_to_pixels(
                    item.rect, self._metrics, self._origin_offset()
                )
                painter.drawRect(
                    int(6 + x * sx), int(6 + y * sy),
                    max(1, int(width * sx)), max(1, int(height * sy)),
                )
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QColor("#1769e0"))
            painter.drawRect(
                int(6 + self._viewport.x() * sx),
                int(6 + self._viewport.y() * sy),
                max(2, int(self._viewport.width() * sx)),
                max(2, int(self._viewport.height() * sy)),
            )
        finally:
            painter.end()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._metrics is None or event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)
        sx, sy = self._scale()
        target = QRect(
            max(0, int((event.pos().x() - 6) / sx - self._viewport.width() / 2)),
            max(0, int((event.pos().y() - 6) / sy - self._viewport.height() / 2)),
            self._viewport.width(),
            self._viewport.height(),
        )
        self.viewport_requested.emit(target)
        event.accept()


class BoardScrollArea(QScrollArea):
    """Scroll host that reports viewport geometry to the logical Board."""

    viewport_resized = pyqtSignal(QSize)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardScrollArea")
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.StrongFocus)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.viewport_resized.emit(self.viewport().size())

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        vertical = self.verticalScrollBar()
        horizontal = self.horizontalScrollBar()
        if event.key() == Qt.Key_Home:
            vertical.setValue(vertical.minimum())
            horizontal.setValue(horizontal.minimum())
            event.accept()
            return
        if event.key() == Qt.Key_End:
            vertical.setValue(vertical.maximum())
            horizontal.setValue(horizontal.maximum())
            event.accept()
            return
        if event.key() == Qt.Key_PageDown:
            vertical.setValue(min(vertical.maximum(), vertical.value() + vertical.pageStep()))
            event.accept()
            return
        if event.key() == Qt.Key_PageUp:
            vertical.setValue(max(vertical.minimum(), vertical.value() - vertical.pageStep()))
            event.accept()
            return
        super().keyPressEvent(event)

class BoardOverview(QFrame):
    """Read-only full-board projection used for P1 global scanning.

    This is intentionally a lightweight QImage composition of existing card
    previews.  It owns no canvas and emits a slot intent on click; the Page
    scrolls the real Board back into view afterwards.
    """

    slot_requested = pyqtSignal(str)
    ref_requested = pyqtSignal(str, str)
    close_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewBoardOverview")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._layout_id = "hero_left_4"
        self._ratio = 0.67
        self._models: dict[str, CardViewModel | None] = {}
        self._board: UltraViewBoardState | None = None
        self._records: dict[UltraViewRef, object] = {}
        self._statuses: dict[UltraViewRef, str] = {}
        self._slot_map: dict[str, tuple[int, int, int, int]] = {}
        self._free_metrics: GridMetrics | None = None
        self._free_rects: dict[str, tuple[int, int, int, int]] = {}
        self._free_refs: dict[str, UltraViewRef] = {}
        self._image = QImage()
        self._content = QRect()
        self._compose_dirty = True
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        bar = QHBoxLayout()
        title = QLabel("整板概览", self)
        title.setObjectName("ultraViewBoardOverviewTitle")
        bar.addWidget(title)
        bar.addStretch(1)
        close = QToolButton(self)
        close.setObjectName("ultraViewBoardOverviewClose")
        close.setText("返回阅读")
        close.clicked.connect(self.close_requested)
        bar.addWidget(close)
        root.addLayout(bar)
        self._preview = QLabel(self)
        self._preview.setObjectName("ultraViewBoardOverviewImage")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        root.addWidget(self._preview, 1)

    def set_board(self, layout_id: str, ratio: float, models: Mapping[str, CardViewModel | None]) -> None:
        self._layout_id = layout_id
        self._ratio = ratio
        self._models = dict(models)
        self._board = None
        self._records = {}
        self._statuses = {}
        self._free_metrics = None
        self._free_rects = {}
        self._free_refs = {}
        self._slot_map = {}
        self._request_compose()

    def set_free_grid(
        self,
        placements: Sequence[FreeGridPlacement],
        models: Mapping[UltraViewRef, CardViewModel],
    ) -> None:
        self._free_metrics = screen_grid_metrics(placements)
        self._free_rects = {
            f"grid:{item.ref.section}:{item.ref.view_id}": rect_to_pixels(
                item.rect, self._free_metrics
            )
            for item in placements
        }
        self._free_refs = {
            f"grid:{item.ref.section}:{item.ref.view_id}": item.ref
            for item in placements
        }
        self._models = {
            f"grid:{item.ref.section}:{item.ref.view_id}": models[item.ref]
            for item in placements
            if item.ref in models
        }
        self._board = None
        self._records = {}
        self._statuses = {}
        self._slot_map = dict(self._free_rects)
        self._request_compose()

    def set_projection(
        self,
        board: UltraViewBoardState,
        records: Mapping[UltraViewRef, object],
        statuses: Mapping[UltraViewRef, str],
    ) -> None:
        """Bind the overview to the same compositor the PNG export uses."""
        self._board = board
        self._records = dict(records)
        self._statuses = dict(statuses)
        self._layout_id = board.layout_id
        self._ratio = board.primary_ratio
        if board.layout_mode == LAYOUT_MODE_FREE_GRID:
            self._free_metrics = export_grid_metrics(board.free_grid)
            self._free_refs = {
                f"grid:{item.ref.section}:{item.ref.view_id}": item.ref
                for item in board.free_grid
            }
        else:
            self._free_metrics = None
            self._free_refs = {}
        self._slot_map = composed_slot_rects(board, title=False)
        self._free_rects = dict(self._slot_map) if self._free_metrics is not None else {}
        self._request_compose()

    def _request_compose(self) -> None:
        self._compose_dirty = True
        if self.isVisible():
            self._compose()
            self._compose_dirty = False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._compose_dirty:
            self._compose()
            self._compose_dirty = False

    def slot_id_at(self, pos: QPoint) -> str | None:
        if self._image.isNull() or self._preview.pixmap() is None:
            return None
        pixmap = self._preview.pixmap()
        draw_w, draw_h = pixmap.width(), pixmap.height()
        origin_x = self._preview.x() + (self._preview.width() - draw_w) // 2
        origin_y = self._preview.y() + (self._preview.height() - draw_h) // 2
        if not QRect(origin_x, origin_y, draw_w, draw_h).contains(pos):
            return None
        scale_x = self._image.width() / float(max(1, draw_w))
        scale_y = self._image.height() / float(max(1, draw_h))
        px = int((pos.x() - origin_x) * scale_x)
        py = int((pos.y() - origin_y) * scale_y)
        for slot_id, rect in self._slot_rects().items():
            if QRect(*rect).contains(px, py):
                return slot_id
        return None

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            slot_id = self.slot_id_at(event.pos())
            if slot_id is not None:
                if slot_id.startswith("grid:"):
                    ref = self._free_refs.get(slot_id)
                    if ref is not None:
                        self.ref_requested.emit(ref.section, ref.view_id)
                else:
                    self.slot_requested.emit(slot_id)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            self.close_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_image()

    def _slot_rects(self) -> dict[str, tuple[int, int, int, int]]:
        if self._slot_map:
            return dict(self._slot_map)
        if self._free_metrics is not None:
            return dict(self._free_rects)
        return slot_rects(self._layout_id, content_rect(BASE_BOARD_SIZE), self._ratio)

    def _compose(self) -> None:
        if self._board is not None:
            self._image = compose_board(
                self._board,
                self._records,
                self._statuses,
                scale=1,
                title=False,
            )
            self._slot_map = composed_slot_rects(self._board, title=False)
            self._fit_image()
            return
        if self._free_metrics is not None:
            image_size = (self._free_metrics.board_width, self._free_metrics.board_height)
        else:
            image_size = BASE_BOARD_SIZE
        image = QImage(*image_size, QImage.Format_ARGB32)
        image.fill(QColor("#f5f7fb"))
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            for slot_id, (x, y, width, height) in self._slot_rects().items():
                model = self._models.get(slot_id)
                painter.setPen(QColor("#d7dee8"))
                painter.setBrush(QColor("#ffffff"))
                painter.drawRoundedRect(x, y, width, height, 5, 5)
                if model is None:
                    painter.setPen(QColor("#64748b"))
                    painter.drawText(QRect(x, y, width, height), Qt.AlignCenter, "空槽")
                    continue
                header_h = CARD_HEADER_HEIGHT if model.show_title else 0
                footer_h = CARD_FOOTER_HEIGHT if model.show_source else 0
                painter.setPen(QColor("#1b2430"))
                if header_h:
                    painter.drawText(QRect(x + 8, y, width - 16, header_h), Qt.AlignVCenter | Qt.AlignLeft, model.title or model.view_id)
                raw = model.image if isinstance(model.image, QImage) else None
                image_rect = QRect(x + 4, y + header_h, max(0, width - 8), max(0, height - header_h - footer_h))
                if raw is not None and not raw.isNull():
                    painter.drawImage(image_rect, raw)
                else:
                    painter.setPen(QColor("#64748b"))
                    painter.drawText(image_rect, Qt.AlignCenter, STATUS_LABELS_ZH.get(model.status, "尚无可用结果"))
                if footer_h:
                    painter.fillRect(x + 1, y + height - footer_h, width - 2, footer_h, QColor("#eef2f7"))
                    painter.setPen(QColor("#5b6775"))
                    painter.drawText(QRect(x + 8, y + height - footer_h, width - 16, footer_h), Qt.AlignVCenter | Qt.AlignLeft, model.source_summary)
        finally:
            painter.end()
        self._image = image
        self._fit_image()

    def _fit_image(self) -> None:
        if self._image.isNull():
            self._preview.setPixmap(QPixmap())
            return
        size = self._preview.size()
        if size.width() < 2 or size.height() < 2:
            return
        self._preview.setPixmap(QPixmap.fromImage(self._image).scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class FocusLayer(QFrame):
    closed = pyqtSignal()
    open_source_requested = pyqtSignal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewFocusLayer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()
        self._section = ""
        self._view_id = ""
        self._image: QImage | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        panel = QFrame(self)
        panel.setObjectName("ultraViewFocusPanel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 8, 8, 8)
        self._title = QLabel("", panel)
        self._title.setObjectName("ultraViewFocusTitle")
        self._sync_badge = QLabel("同步中", panel)
        self._sync_badge.setObjectName("ultraViewFocusSyncing")
        self._sync_badge.setAttribute(Qt.WA_StyledBackground, True)
        self._sync_badge.hide()
        close_btn = QToolButton(panel)
        close_btn.setText("×")
        close_btn.setObjectName("ultraViewFocusClose")
        close_btn.clicked.connect(self.close_layer)
        head.addWidget(self._title, 1)
        head.addWidget(self._sync_badge, 0)
        head.addWidget(close_btn, 0)
        panel_layout.addLayout(head)
        self._image_host = QLabel(panel)
        self._image_host.setObjectName("ultraViewFocusImage")
        self._image_host.setAlignment(Qt.AlignCenter)
        self._image_host.setMinimumSize(QSize(120, 80))
        self._image_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        panel_layout.addWidget(self._image_host, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 8, 12, 10)
        note = QLabel("临时查看 · 不改变源 View · 不超过原始像素 100%", panel)
        self._open = QPushButton("打开原 View", panel)
        self._open.setObjectName("ultraViewOpenSourceButton")
        self._open.clicked.connect(self._emit_open)
        foot.addWidget(note, 1)
        foot.addWidget(self._open, 0)
        panel_layout.addLayout(foot)
        root.addWidget(panel, 1)

    def open_source_button(self) -> QPushButton:
        return self._open

    def current_ref(self) -> tuple[str, str] | None:
        if not self._section or not self._view_id:
            return None
        return (self._section, self._view_id)

    def image_host_size(self) -> tuple[int, int]:
        size = self._image_host.size()
        return (max(1, int(size.width())), max(1, int(size.height())))

    def set_syncing(self, syncing: bool) -> None:
        self._sync_badge.setVisible(bool(syncing))
        if syncing:
            self._sync_badge.raise_()

    def displayed_pixmap_size(self) -> QSize:
        pixmap = self._image_host.pixmap()
        if pixmap is None or pixmap.isNull():
            return QSize(0, 0)
        return pixmap.size()

    def raw_image_size(self) -> QSize:
        if self._image is None:
            return QSize(0, 0)
        return QSize(self._image.width(), self._image.height())

    def show_ref(
        self,
        section: str,
        view_id: str,
        title: str,
        image: QImage | None,
    ) -> None:
        self._section = section
        self._view_id = view_id
        self._image = image
        self._title.setText(title or view_id)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self._refit()

    def close_layer(self) -> None:
        self.hide()
        self._image = None
        self._section = ""
        self._view_id = ""
        self._sync_badge.hide()
        self._image_host.setPixmap(QPixmap())
        self.closed.emit()

    def _emit_open(self) -> None:
        if self._section and self._view_id:
            self.open_source_requested.emit(self._section, self._view_id)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close_layer()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        child = self.childAt(event.pos())
        if child is None or child is self:
            self.close_layer()
            event.accept()
            return
        super().mousePressEvent(event)

    def _refit(self) -> None:
        if self._image is None:
            self._image_host.setPixmap(QPixmap())
            return
        raw_w = self._image.width()
        raw_h = self._image.height()
        avail = self._image_host.size()
        cap_w = max(1, min(avail.width(), raw_w))
        cap_h = max(1, min(avail.height(), raw_h))
        pixmap = QPixmap.fromImage(self._image)
        scaled = pixmap.scaled(cap_w, cap_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._image_host.setPixmap(scaled)
