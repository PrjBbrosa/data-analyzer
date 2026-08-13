"""UltraView View-rail dock: Electric Spectrum chip, separator, measured fit.

``ui/widgets`` owns drawing, size mode, accessibility and ``clicked`` only.
This module must not import MainWindow, the UltraView coordinator, chart_stack,
or numeric/signal packages.
"""
from __future__ import annotations

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import (
    QColor,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)
from PyQt5.QtWidgets import (
    QAbstractButton,
    QFrame,
    QSizePolicy,
    QWidget,
)

ENTRY_HEIGHT = 28
LABEL_TEXT = "UltraView"
ACCESSIBLE_NAME = "打开 UltraView"
TOOLTIP = "打开 UltraView（跨 View 只读对照，不重新计算）"
SPECTRUM_STOPS = ((0.0, "#0969DC"), (0.52, "#734EE6"), (1.0, "#BD299F"))

_PAD_X = 7.0
_PAD_X_RIGHT_FULL = 9.0
_PAD_X_COMPACT = 6.0
_ICON_TILE = 6.0
_ICON_GAP = 2.0
_ICON_RADIUS = 1.6
_ICON_TEXT_GAP = 6.0
_CHROME_RADIUS = 7.0
_BORDER = QColor("#D2DDEA")
_HOVER_FILL = QColor("#F6F8FF")
_HOVER_BORDER = QColor("#B8BDEA")
_PRESSED_FILL = QColor("#EEF1FF")
_PRESSED_BORDER = QColor("#9FA8E8")
_FOCUS_RING = QColor("#1769e0")
_DISABLED_FILL = QColor("#F4F6F9")
_DISABLED_BORDER = QColor("#C5CDD8")
_DISABLED_INK = QColor("#8A97A8")
_SEPARATOR_COLOR = QColor("#D2DDEA")
_SEPARATOR_OBJECT_NAME = "ultraViewEntrySeparator"

__all__ = [
    "ENTRY_HEIGHT",
    "LABEL_TEXT",
    "ACCESSIBLE_NAME",
    "TOOLTIP",
    "SPECTRUM_STOPS",
    "UltraViewEntryButton",
    "make_ultraview_separator",
    "dock_compact_required",
    "UltraViewRailFitter",
]


def _icon_extent() -> float:
    return _ICON_TILE * 2.0 + _ICON_GAP


def _widget_min_width(widget: QWidget) -> int:
    explicit = max(0, int(widget.minimumWidth()))
    min_hint = widget.minimumSizeHint().width()
    hint = widget.sizeHint().width()
    measured = min_hint if min_hint > 0 else max(0, hint)
    return max(explicit, measured)


def _is_separator(widget: QWidget) -> bool:
    return widget.objectName() == _SEPARATOR_OBJECT_NAME


def dock_compact_required(
    *,
    available_width: int,
    non_dock_minimum: int,
    full_dock_hint: int,
    compact_dock_hint: int,
    margins: int,
    spacing: int,
    hysteresis: int = 0,
    currently_compact: bool = False,
) -> bool:
    """Return True when the dock should use icon-only mode.

    Compact vs full is decided from live hints, never from a window-width
    breakpoint. ``full_required`` is the intrinsic width that fits every
    visible non-dock minimum, the full dock, layout margins and spacings.
    Optional hysteresis is a small extra on that same intrinsic sum (capped
    by the full-minus-compact delta) so restore does not chatter at the edge.
    """
    full_required = (
        int(non_dock_minimum)
        + int(full_dock_hint)
        + int(margins)
        + int(spacing)
    )
    extra = 0
    if currently_compact:
        delta = max(0, int(full_dock_hint) - int(compact_dock_hint))
        extra = min(max(0, int(hysteresis)), delta)
    return int(available_width) < full_required + extra


def make_ultraview_separator(parent=None) -> QFrame:
    """1×14 quiet hairline that belongs to the UltraView dock boundary."""
    separator = QFrame(parent)
    separator.setObjectName(_SEPARATOR_OBJECT_NAME)
    separator.setFrameShape(QFrame.NoFrame)
    separator.setFixedSize(1, 14)
    separator.setAttribute(Qt.WA_StyledBackground, True)
    separator.setAutoFillBackground(True)
    palette = separator.palette()
    palette.setColor(QPalette.Window, _SEPARATOR_COLOR)
    separator.setPalette(palette)
    return separator


class UltraViewEntryButton(QAbstractButton):
    """View-rail UltraView chip: shared Electric Spectrum icon + glyph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ultraViewEntry")
        self.setCheckable(False)
        self.setAutoRepeat(False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(ACCESSIBLE_NAME)
        self.setToolTip(TOOLTIP)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedHeight(ENTRY_HEIGHT)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAutoFillBackground(False)
        self._compact = False

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.updateGeometry()
        self.update()

    def is_compact(self) -> bool:
        return self._compact

    def sizeHint(self):  # noqa: N802 - Qt override
        return self._size_hint_for(self._compact)

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        return self._size_hint_for(self._compact)

    def _size_hint_for(self, compact: bool) -> QSize:
        icon_w = _icon_extent()
        if compact:
            width = int(round(_PAD_X_COMPACT + icon_w + _PAD_X_COMPACT))
        else:
            text_w = QFontMetrics(self.font()).horizontalAdvance(LABEL_TEXT)
            width = int(
                round(_PAD_X + icon_w + _ICON_TEXT_GAP + text_w + _PAD_X_RIGHT_FULL)
            )
        return QSize(width, ENTRY_HEIGHT)

    def enterEvent(self, event):  # noqa: N802 - Qt override
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):  # noqa: N802 - Qt override
        super().leaveEvent(event)
        self.update()

    def changeEvent(self, event):  # noqa: N802 - Qt override
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.EnabledChange):
            self.updateGeometry()
            self.update()

    def keyPressEvent(self, event):  # noqa: N802 - Qt override
        # QAbstractButton handles Space. Return/Enter are QPushButton/dialog
        # default-button behaviour; map them to click() without a custom FSM.
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and self.isEnabled()
            and not event.isAutoRepeat()
        ):
            event.accept()
            self.click()
            return
        super().keyPressEvent(event)

    def _chrome_colors(self) -> tuple[QColor | None, QColor]:
        if not self.isEnabled():
            return _DISABLED_FILL, _DISABLED_BORDER
        if self.isDown():
            return _PRESSED_FILL, _PRESSED_BORDER
        if self.underMouse():
            return _HOVER_FILL, _HOVER_BORDER
        return None, _BORDER

    def _brand_origin(self) -> tuple[float, float, float]:
        icon_w = _icon_extent()
        icon_h = icon_w
        pad_left = _PAD_X_COMPACT if self._compact else _PAD_X
        icon_x = pad_left
        icon_y = (self.height() - icon_h) / 2.0
        text_x = icon_x + icon_w + _ICON_TEXT_GAP
        return icon_x, icon_y, text_x

    def _icon_path(self, icon_x: float, icon_y: float) -> QPainterPath:
        path = QPainterPath()
        tile = _ICON_TILE
        gap = _ICON_GAP
        radius = _ICON_RADIUS
        for row in range(2):
            for col in range(2):
                rect = QRectF(
                    icon_x + col * (tile + gap),
                    icon_y + row * (tile + gap),
                    tile,
                    tile,
                )
                path.addRoundedRect(rect, radius, radius)
        return path

    def _text_path(self, text_x: float) -> QPainterPath:
        metrics = QFontMetrics(self.font())
        baseline = (self.height() + metrics.ascent() - metrics.descent()) / 2.0
        path = QPainterPath()
        path.addText(text_x, baseline, self.font(), LABEL_TEXT)
        return path

    def _spectrum_gradient(self, x0: float, x1: float) -> QLinearGradient:
        if x1 <= x0:
            x1 = x0 + 1.0
        gradient = QLinearGradient(x0, 0.0, x1, 0.0)
        for stop, color in SPECTRUM_STOPS:
            gradient.setColorAt(float(stop), QColor(color))
        return gradient

    def paintEvent(self, event):  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            chrome = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            fill, border = self._chrome_colors()
            if fill is None:
                painter.setBrush(Qt.NoBrush)
            else:
                painter.setBrush(fill)
            painter.setPen(QPen(border, 1.0))
            painter.drawRoundedRect(chrome, _CHROME_RADIUS, _CHROME_RADIUS)

            icon_x, icon_y, text_x = self._brand_origin()
            icon_path = self._icon_path(icon_x, icon_y)
            brand = QPainterPath(icon_path)
            text_right = icon_x + _icon_extent()
            if not self._compact:
                text_path = self._text_path(text_x)
                brand.addPath(text_path)
                text_right = text_x + QFontMetrics(self.font()).horizontalAdvance(
                    LABEL_TEXT
                )

            painter.setPen(Qt.NoPen)
            if self.isEnabled():
                painter.setBrush(self._spectrum_gradient(icon_x, text_right))
                painter.drawPath(brand)
            else:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(_DISABLED_INK, 1.0))
                painter.drawPath(icon_path)
                if not self._compact:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(_DISABLED_INK)
                    painter.drawPath(self._text_path(text_x))

            if self.hasFocus() and self.isEnabled():
                focus_rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(_FOCUS_RING, 2.0))
                painter.drawRoundedRect(
                    focus_rect, _CHROME_RADIUS - 1.0, _CHROME_RADIUS - 1.0
                )
        finally:
            painter.end()


_REFIT_EVENTS = frozenset(
    {
        QEvent.Resize,
        QEvent.LayoutRequest,
        QEvent.Show,
        QEvent.Hide,
    }
)


class UltraViewRailFitter(QObject):
    """Deferred host-row fitter: live hints decide full vs icon-only dock."""

    def __init__(self, host, tabbar, entry, extra_widgets=()):
        super().__init__(host)
        self._host = host
        self._tabbar = tabbar
        self._entry = entry
        self._extra_widgets = tuple(extra_widgets)
        self._applying = False
        self._last_signature = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._apply)
        host.installEventFilter(self)
        host.destroyed.connect(self._teardown)
        if tabbar is not None:
            tabbar.installEventFilter(self)
        for extra in self._extra_widgets:
            extra.installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802 - Qt override
        del watched
        if event.type() in _REFIT_EVENTS:
            self.schedule()
        return False

    def schedule(self) -> None:
        if sip.isdeleted(self):
            return
        host = self._host
        entry = self._entry
        if host is None or sip.isdeleted(host):
            return
        if entry is None or sip.isdeleted(entry):
            return
        timer = self._timer
        if timer is None or sip.isdeleted(timer):
            return
        timer.start()

    def _teardown(self, *_args) -> None:
        timer = getattr(self, "_timer", None)
        if timer is not None and not sip.isdeleted(timer):
            timer.stop()

    def _apply(self) -> None:
        if self._applying:
            return
        host = self._host
        entry = self._entry
        if host is None or sip.isdeleted(host):
            return
        if not host.isVisible():
            return
        if entry is None or sip.isdeleted(entry):
            return
        layout = host.layout()
        if layout is None:
            return
        self._applying = True
        try:
            margins = layout.contentsMargins()
            margin_total = margins.left() + margins.right()
            visible: list[QWidget] = []
            non_dock = 0
            separator_width = 0
            for index in range(layout.count()):
                item = layout.itemAt(index)
                widget = item.widget() if item is not None else None
                if widget is None or widget.isHidden():
                    continue
                visible.append(widget)
                if widget is entry:
                    continue
                if _is_separator(widget):
                    separator_width = _widget_min_width(widget)
                    continue
                non_dock += _widget_min_width(widget)
            spacing_total = max(0, len(visible) - 1) * int(layout.spacing())
            full_dock = separator_width + entry._size_hint_for(False).width()
            compact_dock = separator_width + entry._size_hint_for(True).width()
            metrics = QFontMetrics(entry.font())
            hysteresis = max(int(_ICON_TEXT_GAP), int(metrics.averageCharWidth()))
            needed = dock_compact_required(
                available_width=host.width(),
                non_dock_minimum=non_dock,
                full_dock_hint=full_dock,
                compact_dock_hint=compact_dock,
                margins=margin_total,
                spacing=spacing_total,
                hysteresis=hysteresis,
                currently_compact=entry.is_compact(),
            )
            extras_sig = tuple(
                extra.isHidden()
                for extra in self._extra_widgets
                if extra is not None and not sip.isdeleted(extra)
            )
            signature = (needed, extras_sig, host.width(), full_dock, compact_dock)
            if signature == self._last_signature:
                return
            self._last_signature = signature
            if entry.is_compact() != needed:
                entry.set_compact(needed)
            tabbar = self._tabbar
            refresh = getattr(tabbar, "refresh_fit", None) if tabbar is not None else None
            if callable(refresh) and not sip.isdeleted(tabbar):
                refresh()
        finally:
            self._applying = False
