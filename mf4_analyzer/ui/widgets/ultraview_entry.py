"""UltraView View-rail dock: Prism Portal mark, separator, measured fit.

Visual contract is Option A in
``docs/analyzer/ui-prototypes/2026-08-13-ultraview-entry-emphasis-options.html``:
a framed 2×2 board portal, gradient wordmark, no enclosing capsule.

``ui/widgets`` owns drawing, size mode, accessibility and ``clicked`` only.
This module must not import MainWindow, the UltraView coordinator, chart_stack,
or numeric/signal packages.
"""
from __future__ import annotations

import math

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QRectF, QSize, Qt, QTimer
from PyQt5.QtGui import (
    QColor,
    QFont,
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

ENTRY_HEIGHT = 30
LABEL_TEXT = "UltraView"
ACCESSIBLE_NAME = "打开 UltraView"
TOOLTIP = "打开 UltraView（跨 View 只读对照，不重新计算）"
EDITED_TOOLTIP = "打开 UltraView（已编辑）"
SPECTRUM_STOPS = ((0.0, "#0969DC"), (0.52, "#734EE6"), (1.0, "#BD299F"))
# TL, TR, BL, BR — Electric Spectrum mapped onto the 2×2 board, not a wash.
TILE_COLORS = ("#0969DC", "#734EE6", "#734EE6", "#BD299F")

# HTML A used a 27px portal in a 38px mock rail. The product View rail is
# 30px (same as ViewTabBar / the 22px "+" chip centered in that band), so
# the portal stays 20px — 5px pad top/bottom, midline at y=15 with the tabs.
PORTAL_SIZE = 20
COMPACT_WIDTH = 26
_PAD_X_LEFT = 4.0
_PAD_X_RIGHT = 6.0
_PORTAL_RADIUS = 6.0
_PORTAL_INNER_INSET = 1.5
_PORTAL_INNER_RADIUS = 4.5
_QUAD_BOX = 18.0
_QUAD_SCALE = 0.83
_ICON_TILE = 5.0
_ICON_GAP = 2.0
_ICON_RADIUS = 1.5
_ICON_TEXT_GAP = 5.0
_WORD_PX = 12
_WORD_WEIGHT = 76
_WORD_TRACKING = 97.5
_UNDERLINE_HEIGHT = 2.0
_UNDERLINE_GAP = 2.0
_UNDERLINE_REST_SCALE = 0.45
_UNDERLINE_REST_OPACITY = 0.54
_FOCUS_RING = QColor(20, 120, 247, 71)
_PORTAL_INSET = QColor(97, 97, 196, 43)
_PORTAL_INSET_PRESSED = QColor(99, 91, 215, 82)
_PORTAL_INNER = QColor(255, 255, 255, 242)
_PORTAL_SHADOW = QColor(91, 83, 205, 43)
_EDITED_DOT = QColor("#18A861")
_EDITED_DOT_RING = QColor("#FFFFFF")
_EDITED_DOT_SIZE = 7.0
_DISABLED_FILL = QColor("#F4F6F9")
_DISABLED_BORDER = QColor("#C5CDD8")
_DISABLED_INK = QColor("#8A97A8")
# Same hairline as View 栏 section-anchor rule; global QFrame { #fff } would
# otherwise paint this 1px sibling white and make it disappear on the rail.
SEPARATOR_HEIGHT = 18
_SEPARATOR_COLOR = QColor("#C8D2E0")
_SEPARATOR_OBJECT_NAME = "ultraViewEntrySeparator"

__all__ = [
    "ENTRY_HEIGHT",
    "LABEL_TEXT",
    "ACCESSIBLE_NAME",
    "TOOLTIP",
    "EDITED_TOOLTIP",
    "SPECTRUM_STOPS",
    "TILE_COLORS",
    "PORTAL_SIZE",
    "COMPACT_WIDTH",
    "SEPARATOR_HEIGHT",
    "UltraViewEntryButton",
    "make_ultraview_separator",
    "dock_compact_required",
    "UltraViewRailFitter",
]


def _css_linear_gradient(rect: QRectF, deg: float) -> QLinearGradient:
    """CSS ``linear-gradient(Ndeg, …)`` axis across ``rect`` (0deg = up)."""
    rad = math.radians(float(deg))
    dx = math.sin(rad)
    dy = -math.cos(rad)
    cx = rect.center().x()
    cy = rect.center().y()
    half = abs(rect.width() * 0.5 * dx) + abs(rect.height() * 0.5 * dy)
    return QLinearGradient(
        cx - dx * half,
        cy - dy * half,
        cx + dx * half,
        cy + dy * half,
    )


def _modulate(
    color: QColor,
    *,
    saturate: float = 1.0,
    contrast: float = 1.0,
) -> QColor:
    if saturate == 1.0 and contrast == 1.0:
        return QColor(color)
    hue, sat, value, alpha = color.getHsv()
    sat = max(0, min(255, int(round(sat * saturate))))
    value = max(0, min(255, int(round(128 + (value - 128) * contrast))))
    if hue < 0:
        hue = 0
        sat = 0
    return QColor.fromHsv(hue, sat, value, alpha)


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
    """1px dock hairline painted explicitly so app QFrame QSS cannot hide it."""
    separator = _UltraViewSeparator(parent)
    separator.setObjectName(_SEPARATOR_OBJECT_NAME)
    separator.setFrameShape(QFrame.NoFrame)
    separator.setFixedSize(1, SEPARATOR_HEIGHT)
    separator.setAttribute(Qt.WA_StyledBackground, True)
    separator.setAutoFillBackground(False)
    separator.setFocusPolicy(Qt.NoFocus)
    return separator


class _UltraViewSeparator(QFrame):
    def paintEvent(self, event):  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), _SEPARATOR_COLOR)
        finally:
            painter.end()


class UltraViewEntryButton(QAbstractButton):
    """View-rail UltraView mark: Prism Portal + Electric Spectrum wordmark."""

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
        self._keyboard_focus = False
        self._has_content = False

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.updateGeometry()
        self.update()

    def is_compact(self) -> bool:
        return self._compact

    def set_has_content(self, has_content: bool) -> None:
        """Show the small edited marker when any UltraView card is configured."""
        has_content = bool(has_content)
        if has_content == self._has_content:
            return
        self._has_content = has_content
        self.setToolTip(EDITED_TOOLTIP if has_content else TOOLTIP)
        self.update()

    def has_content(self) -> bool:
        return self._has_content

    def sizeHint(self):  # noqa: N802 - Qt override
        return self._size_hint_for(self._compact)

    def minimumSizeHint(self):  # noqa: N802 - Qt override
        return self._size_hint_for(self._compact)

    def _brand_font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(_WORD_PX)
        font.setWeight(_WORD_WEIGHT)
        font.setLetterSpacing(QFont.PercentageSpacing, _WORD_TRACKING)
        font.setStyleStrategy(QFont.PreferAntialias)
        return font

    def _size_hint_for(self, compact: bool) -> QSize:
        if compact:
            return QSize(COMPACT_WIDTH, ENTRY_HEIGHT)
        text_w = QFontMetrics(self._brand_font()).horizontalAdvance(LABEL_TEXT)
        width = int(
            round(
                _PAD_X_LEFT
                + PORTAL_SIZE
                + _ICON_TEXT_GAP
                + text_w
                + _PAD_X_RIGHT
            )
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

    def focusInEvent(self, event):  # noqa: N802 - Qt override
        self._keyboard_focus = event.reason() in (
            Qt.TabFocusReason,
            Qt.BacktabFocusReason,
            Qt.ShortcutFocusReason,
        )
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):  # noqa: N802 - Qt override
        self._keyboard_focus = False
        super().focusOutEvent(event)
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

    def _energy(self) -> tuple[float, float]:
        if not self.isEnabled():
            return 1.0, 1.0
        if self.isDown():
            return 1.18, 1.03
        if self.underMouse():
            return 1.1, 1.0
        return 1.0, 1.0

    def _portal_rect(self) -> QRectF:
        # +1px optical sit: the 1px rail hairlines read as the true frame,
        # so a geometric mid looks a pixel high against those anchors.
        y = (float(self.height()) - float(PORTAL_SIZE)) / 2.0 + 1.0
        y = max(0.0, min(y, float(self.height()) - float(PORTAL_SIZE)))
        if self._compact:
            x = (float(self.width()) - float(PORTAL_SIZE)) / 2.0
        else:
            x = _PAD_X_LEFT
        return QRectF(x, y, float(PORTAL_SIZE), float(PORTAL_SIZE))

    def _text_path(self) -> QPainterPath:
        font = self._brand_font()
        metrics = QFontMetrics(font)
        portal = self._portal_rect()
        # Glyph midline shares the portal center (View tab mid ≈ y+14).
        baseline = portal.center().y() + (
            metrics.ascent() - metrics.descent()
        ) / 2.0
        text_x = portal.right() + _ICON_TEXT_GAP
        path = QPainterPath()
        path.addText(text_x, baseline, font, LABEL_TEXT)
        return path

    def _underline_rect(self, text_bounds: QRectF) -> QRectF:
        width = max(1.0, text_bounds.width() - 2.0)
        if self.underMouse() or self.isDown():
            width_scale = 1.0
        else:
            width_scale = _UNDERLINE_REST_SCALE
        top = min(
            text_bounds.bottom() + _UNDERLINE_GAP,
            float(self.height()) - _UNDERLINE_HEIGHT - 0.5,
        )
        return QRectF(
            text_bounds.left(),
            top,
            width * width_scale,
            _UNDERLINE_HEIGHT,
        )

    def _fill_spectrum(self, gradient: QLinearGradient, *, saturate: float, contrast: float) -> None:
        for stop, color in SPECTRUM_STOPS:
            painted = _modulate(QColor(color), saturate=saturate, contrast=contrast)
            gradient.setColorAt(float(stop), painted)

    def _paint_portal(
        self,
        painter: QPainter,
        portal: QRectF,
        *,
        saturate: float,
        contrast: float,
    ) -> None:
        if self.isDown() and self.isEnabled():
            shadow = portal.adjusted(-0.5, 1.5, 0.5, 2.5)
            painter.setPen(Qt.NoPen)
            painter.setBrush(_PORTAL_SHADOW)
            painter.drawRoundedRect(shadow, _PORTAL_RADIUS, _PORTAL_RADIUS)

        if self.isEnabled():
            fill = _css_linear_gradient(portal, 140.0)
            wash = (
                (0.0, QColor(9, 105, 220, 33)),
                (0.55, QColor(115, 78, 230, 31)),
                (1.0, QColor(189, 41, 159, 31)),
            )
            for stop, color in wash:
                fill.setColorAt(
                    float(stop),
                    _modulate(color, saturate=saturate, contrast=contrast),
                )
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(_DISABLED_FILL)
        painter.drawRoundedRect(portal, _PORTAL_RADIUS, _PORTAL_RADIUS)

        ring = portal.adjusted(0.5, 0.5, -0.5, -0.5)
        ring_color = (
            _DISABLED_BORDER
            if not self.isEnabled()
            else (
                _PORTAL_INSET_PRESSED
                if self.isDown()
                else _PORTAL_INSET
            )
        )
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(ring_color, 1.0))
        painter.drawRoundedRect(ring, _PORTAL_RADIUS, _PORTAL_RADIUS)

        inner = portal.adjusted(
            _PORTAL_INNER_INSET + 0.5,
            _PORTAL_INNER_INSET + 0.5,
            -(_PORTAL_INNER_INSET + 0.5),
            -(_PORTAL_INNER_INSET + 0.5),
        )
        painter.setPen(QPen(_PORTAL_INNER if self.isEnabled() else QColor(255, 255, 255, 180), 1.0))
        painter.drawRoundedRect(inner, _PORTAL_INNER_RADIUS, _PORTAL_INNER_RADIUS)

    def _paint_quad(
        self,
        painter: QPainter,
        portal: QRectF,
        *,
        saturate: float,
        contrast: float,
    ) -> None:
        # Map the CSS 24×24 quad (scale .83 around its center) into widget
        # space instead of painter.scale(), so tile edges stay sharp at 1×.
        cx = portal.center().x()
        cy = portal.center().y()
        grid = _ICON_TILE * 2.0 + _ICON_GAP
        origin = (_QUAD_BOX - grid) / 2.0
        tile = _ICON_TILE * _QUAD_SCALE
        step = (_ICON_TILE + _ICON_GAP) * _QUAD_SCALE
        radius = _ICON_RADIUS * _QUAD_SCALE
        origin_x = cx + (origin - _QUAD_BOX / 2.0) * _QUAD_SCALE
        origin_y = cy + (origin - _QUAD_BOX / 2.0) * _QUAD_SCALE
        painter.setPen(Qt.NoPen)
        for index, (row, col) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
            rect = QRectF(
                origin_x + col * step,
                origin_y + row * step,
                tile,
                tile,
            )
            if self.isEnabled():
                color = _modulate(
                    QColor(TILE_COLORS[index]),
                    saturate=saturate,
                    contrast=contrast,
                )
                painter.setBrush(color)
            else:
                painter.setBrush(_DISABLED_INK)
            painter.drawRoundedRect(rect, radius, radius)

    def _paint_word(self, painter: QPainter, *, saturate: float, contrast: float) -> None:
        path = self._text_path()
        bounds = path.boundingRect()
        if self.isEnabled():
            gradient = _css_linear_gradient(bounds, 100.0)
            self._fill_spectrum(gradient, saturate=saturate, contrast=contrast)
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(_DISABLED_INK)
        painter.drawPath(path)

        underline = self._underline_rect(bounds)
        if underline.width() <= 0:
            return
        opacity = (
            1.0
            if self.isEnabled() and (self.underMouse() or self.isDown())
            else _UNDERLINE_REST_OPACITY
        )
        painter.save()
        painter.setOpacity(opacity if self.isEnabled() else 0.35)
        if self.isEnabled():
            gradient = QLinearGradient(underline.left(), 0.0, underline.right(), 0.0)
            self._fill_spectrum(gradient, saturate=saturate, contrast=contrast)
            painter.setBrush(gradient)
        else:
            painter.setBrush(_DISABLED_INK)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(underline, 99.0, 99.0)
        painter.restore()

    def _edited_dot_rect(self, portal: QRectF) -> QRectF:
        size = _EDITED_DOT_SIZE
        return QRectF(
            portal.right() - size + 1.0,
            portal.top() - 1.0,
            size,
            size,
        )

    def _paint_edited_dot(self, painter: QPainter, portal: QRectF) -> None:
        if not self._has_content:
            return
        painter.setBrush(_EDITED_DOT)
        painter.setPen(QPen(_EDITED_DOT_RING, 1.2))
        painter.drawEllipse(self._edited_dot_rect(portal))

    def paintEvent(self, event):  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            saturate, contrast = self._energy()
            portal = self._portal_rect()
            self._paint_portal(painter, portal, saturate=saturate, contrast=contrast)
            self._paint_quad(painter, portal, saturate=saturate, contrast=contrast)
            self._paint_edited_dot(painter, portal)
            if not self._compact:
                self._paint_word(painter, saturate=saturate, contrast=contrast)
            if self._keyboard_focus and self.isEnabled():
                # :focus-visible only — mouse/show focus must not resurrect
                # the discarded capsule chrome around the wordmark.
                focus = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(_FOCUS_RING, 2.0))
                painter.drawRoundedRect(focus, _PORTAL_RADIUS, _PORTAL_RADIUS)
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
