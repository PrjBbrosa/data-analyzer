"""Presentation-only “全部 View” popup for the shared View tab rail.

The widget projects immutable row DTOs and emits typed intents. It does not
import MainWindow or mutate ViewManager.
"""
from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ...ui_kit.popup_shell import apply_popup_shell

_SCREEN_MARGIN = 8
_ANCHOR_GAP = 4
_FALLBACK_AVAILABLE_GEOMETRY = QRect(0, 0, 1920, 1080)
_SURFACE_RADIUS = 12.0
_SURFACE_BG = QColor("#ffffff")
_SURFACE_BORDER = QColor("#bfcfe1")
_SEPARATOR = QColor("#c9d5e3")
_FOOTER_BG = QColor("#f8fafc")
_KEEP_ONE_TIP = "至少保留一个 View"
_WELL_INSET = 8.0
# Floor: two compact 「关闭其他 / 关闭全部」 stay clickable. Ceiling: long
# names elide instead of stretching the panel into empty space.
PANEL_MIN_WIDTH = 280
PANEL_MAX_WIDTH = 316
_FOOTER_BUTTON_HEIGHT = 24
_ROW_HEIGHT = 36
_CHIP_PAD = 18
_CLOSE_FILL = QColor("#fff0f2")
_CLOSE_BORDER = QColor("#dfa0a9")
_CLOSE_INK = QColor("#bf3447")
_CLOSE_IDLE = QColor("#7a899d")
_CLOSE_DISABLED = QColor("#c5ced8")


@dataclass(frozen=True)
class ViewOverflowRow:
    view_id: str
    name: str
    ordinal: int
    color: str
    partner_color: str | None
    current: bool
    closable: bool


class ViewOverflowPopup(QFrame):
    """Parented ``Qt.Popup`` listing every View with row and bulk close intents."""

    switch_requested = pyqtSignal(str)
    close_requested = pyqtSignal(str)
    close_others_requested = pyqtSignal(str)
    close_all_requested = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("viewOverflowPopup")
        apply_popup_shell(self)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFocusPolicy(Qt.StrongFocus)
        self._keep_view_id = ""
        self._closed_emitted = False
        self._fitted_width = 0
        self._row_name_buttons: list[QPushButton] = []
        self._row_close_buttons: list[_OverflowCloseButton] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._surface = _OverflowSurface(self)
        self._surface.setObjectName("viewOverflowSurface")
        surface_lay = QVBoxLayout(self._surface)
        surface_lay.setContentsMargins(0, 0, 0, 0)
        surface_lay.setSpacing(0)
        root.addWidget(self._surface)

        header = QWidget(self._surface)
        header.setObjectName("viewOverflowHeader")
        header_lay = QHBoxLayout(header)
        header_lay.setContentsMargins(14, 11, 14, 11)
        header_lay.setSpacing(12)
        title = QLabel("全部 View", header)
        title.setObjectName("viewOverflowTitle")
        header_lay.addWidget(title, 1)
        self._count = QLabel(header)
        self._count.setObjectName("viewOverflowCount")
        header_lay.addWidget(self._count, 0, Qt.AlignVCenter)
        surface_lay.addWidget(header)

        self._scroll = QScrollArea(self._surface)
        self._scroll.setObjectName("viewOverflowList")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._scroll.setFocusPolicy(Qt.NoFocus)
        self._list_host = QWidget(self._scroll)
        self._list_host.setObjectName("viewOverflowListHost")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(6, 4, 6, 6)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list_host)
        self._list_well = _OverflowListWell(self._surface)
        self._list_well.setObjectName("viewOverflowListWell")
        # Widget contentsMargins (not layout margins) shrink contentsRect so
        # the well stroke can sit in the 8px pad, inside the clip, outside the
        # opaque scroll child.
        self._list_well.setContentsMargins(int(_WELL_INSET), 0, int(_WELL_INSET), 0)
        well_lay = QVBoxLayout(self._list_well)
        well_lay.setContentsMargins(0, 0, 0, 0)
        well_lay.setSpacing(0)
        well_lay.addWidget(self._scroll)
        surface_lay.addWidget(self._list_well, 1)

        footer = QWidget(self._surface)
        footer.setObjectName("viewOverflowFooter")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(10, 8, 10, 10)
        footer_lay.setSpacing(8)
        self._close_others = QPushButton("关闭其他", footer)
        self._close_others.setObjectName("viewOverflowCloseOthers")
        self._close_others.setCursor(Qt.PointingHandCursor)
        self._close_others.setFixedHeight(_FOOTER_BUTTON_HEIGHT)
        self._close_others.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._close_others.clicked.connect(self._emit_close_others)
        self._close_all = QPushButton("关闭全部", footer)
        self._close_all.setObjectName("viewOverflowCloseAll")
        self._close_all.setCursor(Qt.PointingHandCursor)
        self._close_all.setFixedHeight(_FOOTER_BUTTON_HEIGHT)
        self._close_all.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._close_all.setProperty("variant", "softDanger")
        self._close_all.clicked.connect(self._emit_close_all)
        footer_lay.addWidget(self._close_others)
        footer_lay.addWidget(self._close_all)
        surface_lay.addWidget(footer)

        self.setMinimumWidth(PANEL_MIN_WIDTH)
        self.setMaximumWidth(PANEL_MAX_WIDTH)

    def populate(self, rows: list[ViewOverflowRow]) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._row_name_buttons = []
        self._row_close_buttons = []
        current = next((row for row in rows if row.current), None)
        self._keep_view_id = current.view_id if current is not None else ""
        closable = any(row.closable for row in rows) and len(rows) > 1
        self._count.setText(f"{len(rows)} 个")
        for row in rows:
            self._list_layout.insertWidget(
                self._list_layout.count() - 1, self._make_row(row)
            )
        self._close_others.setEnabled(closable)
        self._close_all.setEnabled(closable)
        keep_tip = "" if closable else _KEEP_ONE_TIP
        self._close_others.setToolTip(keep_tip)
        self._close_all.setToolTip(keep_tip)
        self._close_others.setAccessibleDescription(keep_tip)
        self._close_all.setAccessibleDescription(keep_tip)
        keep_width = self.isVisible() and self._fitted_width >= PANEL_MIN_WIDTH
        if not keep_width:
            self._fitted_width = self._preferred_panel_width(rows)
        if self.isVisible():
            self._apply_panel_size(self._fitted_width)
            self._elide_visible_names()
            self._restore_pointer_chrome()
            QTimer.singleShot(0, self._after_reproject)
        elif self._row_name_buttons:
            self._row_name_buttons[0].setFocus(Qt.PopupFocusReason)

    def sizeHint(self) -> QSize:
        width = self._fitted_width or PANEL_MIN_WIDTH
        return QSize(width, super().sizeHint().height())

    def show_at(self, anchor: QWidget) -> None:
        available = self._available_geometry_for(anchor)
        max_w = max(PANEL_MIN_WIDTH, available.width() - 2 * _SCREEN_MARGIN)
        max_h = max(160, available.height() - 2 * _SCREEN_MARGIN)
        self.setMaximumHeight(max_h)
        width = self._clamp(
            self._fitted_width or PANEL_MIN_WIDTH,
            PANEL_MIN_WIDTH,
            min(PANEL_MAX_WIDTH, max_w),
        )
        self._fitted_width = width
        self._apply_panel_size(width)

        width = self.width()
        height = self.height()
        anchor_top_left = anchor.mapToGlobal(anchor.rect().topLeft())
        anchor_bottom_left = anchor.mapToGlobal(anchor.rect().bottomLeft())
        left = available.left() + _SCREEN_MARGIN
        right = available.right() - _SCREEN_MARGIN - width + 1
        x = self._clamp(anchor_top_left.x(), left, right)

        top = available.top() + _SCREEN_MARGIN
        bottom = available.bottom() - _SCREEN_MARGIN - height + 1
        below = anchor_bottom_left.y() + 1 + _ANCHOR_GAP
        above = anchor_top_left.y() - _ANCHOR_GAP - height
        if below <= bottom:
            y = below
        elif above >= top:
            y = above
        else:
            y = self._clamp(below, top, bottom)
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self._elide_visible_names()
        if self._row_name_buttons:
            self._row_name_buttons[0].setFocus(Qt.PopupFocusReason)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._emit_closed()

    def closeEvent(self, event):
        super().closeEvent(event)
        self._emit_closed()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_Down) and self._row_name_buttons:
            event.accept()
            self._move_row_focus(-1 if key == Qt.Key_Up else 1)
            return
        if key == Qt.Key_Delete:
            event.accept()
            return
        super().keyPressEvent(event)

    def _move_row_focus(self, step: int) -> None:
        buttons = [btn for btn in self._row_name_buttons if btn.isVisible()]
        if not buttons:
            return
        current = self.focusWidget()
        try:
            idx = buttons.index(current)
        except ValueError:
            idx = 0 if step > 0 else len(buttons) - 1
        else:
            idx = (idx + step) % len(buttons)
        buttons[idx].setFocus(Qt.TabFocusReason)

    def _scrollbar_gutter(self) -> int:
        bar = self._scroll.verticalScrollBar()
        hinted = bar.sizeHint().width() if bar is not None else 0
        metric = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        return max(8, hinted, metric)

    def _preferred_panel_width(self, rows: list[ViewOverflowRow]) -> int:
        fm = self.fontMetrics()
        longest_name = 0
        for row in rows:
            longest_name = max(longest_name, fm.horizontalAdvance(row.name) + 8)
        chip = fm.horizontalAdvance("当前") + _CHIP_PAD
        # list margins 6+6, row padding 8+4, swatch 28, close 27, gaps 7*3
        row_chrome = 6 + 8 + 28 + 7 + 7 + 7 + 27 + 4 + 6
        row_w = (
            row_chrome
            + longest_name
            + chip
            + self._scrollbar_gutter()
            + 2 * int(_WELL_INSET)
        )
        header_w = 14 + fm.horizontalAdvance("全部 View") + 12 + 52 + 14
        footer_w = 10 + 118 + 8 + 118 + 10
        return self._clamp(max(row_w, header_w, footer_w), PANEL_MIN_WIDTH, PANEL_MAX_WIDTH)

    def _apply_panel_size(self, width: int) -> None:
        header = self.findChild(QWidget, "viewOverflowHeader")
        footer = self.findChild(QWidget, "viewOverflowFooter")
        header_h = header.sizeHint().height() if header is not None else 40
        footer_h = footer.sizeHint().height() if footer is not None else 40
        rows = max(0, self._list_layout.count() - 1)
        list_h = 10 + rows * _ROW_HEIGHT + max(0, rows - 1) * 2
        max_h = self.maximumHeight()
        if max_h > 100000:
            max_h = 480
        height = header_h + footer_h + list_h
        height = min(max(height, header_h + footer_h + 72), max_h)
        self.setFixedWidth(width)
        self.setFixedHeight(height)

    def _elide_visible_names(self) -> None:
        for btn in self._row_name_buttons:
            if not btn.isVisible():
                continue
            full = str(btn.property("fullName") or btn.accessibleName() or "")
            if not full:
                continue
            budget = max(24, btn.width() - 6)
            btn.setText(btn.fontMetrics().elidedText(full, Qt.ElideRight, budget))

    def _restore_pointer_chrome(self) -> None:
        if not self.isVisible():
            return
        target = self._chrome_at(QCursor.pos())
        for btn in self._row_close_buttons:
            if btn.isVisible():
                btn.set_hovered(btn is target)

    def _chrome_at(self, global_pos: QPoint):
        for btn in self._row_close_buttons:
            if not btn.isVisible() or not btn.isEnabled():
                continue
            if btn.rect().contains(btn.mapFromGlobal(global_pos)):
                return btn
        return None

    def _after_reproject(self) -> None:
        self._elide_visible_names()
        self._restore_pointer_chrome()

    def _make_row(self, row: ViewOverflowRow) -> QWidget:
        host = QWidget(self._list_host)
        host.setObjectName("viewOverflowRow")
        host.setProperty("current", "true" if row.current else "false")
        host.setProperty("viewId", row.view_id)
        lay = QHBoxLayout(host)
        lay.setContentsMargins(8, 4, 4, 4)
        lay.setSpacing(7)

        swatch = QLabel(host)
        swatch.setObjectName("viewOverflowRowSwatch")
        swatch.setFixedSize(28, 16)
        swatch.setPixmap(_row_swatch_pixmap(row.color, row.partner_color))
        lay.addWidget(swatch, 0, Qt.AlignVCenter)

        name = QPushButton(row.name, host)
        name.setObjectName("viewOverflowRowName")
        name.setCursor(Qt.PointingHandCursor)
        name.setAttribute(Qt.WA_Hover, True)
        name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        name.setProperty("fullName", row.name)
        name.setToolTip(row.name)
        name.setProperty("viewId", row.view_id)
        name.setAccessibleName(row.name)
        name.clicked.connect(self._emit_switch_from_sender)
        lay.addWidget(name, 1)
        self._row_name_buttons.append(name)

        chip = QLabel("当前" if row.current else "", host)
        chip.setObjectName("viewOverflowCurrentChip")
        chip.setVisible(row.current)
        lay.addWidget(chip, 0, Qt.AlignVCenter)

        close = _OverflowCloseButton(host)
        close.setObjectName("viewOverflowRowClose")
        close.setProperty("viewId", row.view_id)
        close.setAccessibleName(f"关闭 View「{row.name}」")
        close.setEnabled(row.closable)
        close.setToolTip(_KEEP_ONE_TIP if not row.closable else "关闭此 View")
        close.setAccessibleDescription(_KEEP_ONE_TIP if not row.closable else "")
        close.clicked.connect(self._emit_close_from_sender)
        lay.addWidget(close, 0, Qt.AlignVCenter)
        self._row_close_buttons.append(close)
        return host

    def _sender_view_id(self) -> str:
        sender = self.sender()
        if sender is None:
            return ""
        return str(sender.property("viewId") or "")

    def _emit_switch_from_sender(self) -> None:
        view_id = self._sender_view_id()
        if not view_id:
            return
        self.switch_requested.emit(view_id)

    def _emit_close_from_sender(self) -> None:
        view_id = self._sender_view_id()
        if not view_id:
            return
        self.close_requested.emit(view_id)

    def _emit_close_others(self) -> None:
        if not self._close_others.isEnabled() or not self._keep_view_id:
            return
        self.close_others_requested.emit(self._keep_view_id)

    def _emit_close_all(self) -> None:
        if not self._close_all.isEnabled():
            return
        self.close_all_requested.emit()

    def _emit_closed(self) -> None:
        if self._closed_emitted:
            return
        self._closed_emitted = True
        self.closed.emit()

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        if hi < lo:
            return lo
        return max(lo, min(hi, value))

    @staticmethod
    def _available_geometry_for(anchor: QWidget) -> QRect:
        window = anchor.window() if anchor is not None else None
        handle = window.windowHandle() if window is not None else None
        screen = handle.screen() if handle is not None else None
        if screen is None and anchor is not None:
            screen = QGuiApplication.screenAt(
                anchor.mapToGlobal(anchor.rect().center())
            )
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(_FALLBACK_AVAILABLE_GEOMETRY)
        return screen.availableGeometry()


class _OverflowListWell(QWidget):
    """Owns the list well stroke. Parent paint cannot show through this layer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), _SURFACE_BG)
        # Outset the stroke by 0.5px into the contents-margin pad so the 1px
        # line stays inside this widget's clip and is not covered by the scroll.
        well = QRectF(self.contentsRect()).adjusted(-0.5, 0.5, 0.5, -0.5)
        if well.width() > 2 and well.height() > 2:
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.setPen(QPen(_SEPARATOR, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(well)
        painter.end()


class _OverflowCloseButton(QPushButton):
    """Paints hover itself; QSS :hover does not survive this translucent popup."""

    def __init__(self, parent=None):
        super().__init__("×", parent)
        self._hovered = False
        self.setFixedSize(27, 27)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setFocusPolicy(Qt.TabFocus)

    def set_hovered(self, hovered: bool) -> None:
        hovered = bool(hovered) and self.isEnabled()
        if self._hovered == hovered:
            return
        self._hovered = hovered
        self.update()

    def enterEvent(self, event):
        self.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.set_hovered(False)
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        if not self.isEnabled():
            ink = _CLOSE_DISABLED
            fill = None
            border = None
        elif self._hovered or self.isDown():
            ink = _CLOSE_INK
            fill = _CLOSE_FILL
            border = _CLOSE_BORDER
        else:
            ink = _CLOSE_IDLE
            fill = None
            border = None
        if fill is not None:
            painter.setPen(QPen(border, 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 6, 6)
        painter.setPen(ink)
        painter.drawText(self.rect(), Qt.AlignCenter, "×")
        painter.end()


class _OverflowSurface(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, _SURFACE_RADIUS, _SURFACE_RADIUS)
        painter.fillPath(path, _SURFACE_BG)
        footer = self.findChild(QWidget, "viewOverflowFooter")
        if footer is not None:
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(QRectF(footer.geometry()), _FOOTER_BG)
            painter.restore()
        painter.setPen(QPen(_SURFACE_BORDER, 1))
        painter.drawPath(path)
        painter.end()


def _row_swatch_pixmap(hex_color: str, partner_color=None):
    from PyQt5.QtGui import QPixmap

    color = QColor(hex_color)
    if not color.isValid():
        color = QColor("#2d7ff9")
    pixmap = QPixmap(28, 16)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    rect = QRectF(0.5, 0.5, 27, 15)
    partner = QColor(partner_color) if partner_color else None
    if partner is not None and partner.isValid():
        clip = QPainterPath()
        clip.addRoundedRect(rect, 4, 4)
        painter.setClipPath(clip)
        mid = rect.center().x()
        painter.fillRect(QRectF(rect.left(), rect.top(), mid - rect.left(), rect.height()), color)
        painter.fillRect(QRectF(mid, rect.top(), rect.right() - mid, rect.height()), partner)
        painter.fillRect(QRectF(mid - 0.5, rect.top(), 1.0, rect.height()), QColor("#ffffff"))
        painter.setClipping(False)
        painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 4, 4)
    else:
        painter.setPen(QPen(color.darker(115), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 4, 4)
    painter.end()
    return pixmap
