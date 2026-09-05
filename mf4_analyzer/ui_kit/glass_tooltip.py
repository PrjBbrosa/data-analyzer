"""Glass-style tooltip replacement for the entire application.

Call ``install_glass_tooltips(app)`` once after QApplication is created.
All widgets that have a toolTip() set will use the glass popup instead of
the native Qt tooltip, positioned just below the hovered widget.
"""
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QApplication, QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from .dialog_geometry import (
    FrameInsets,
    IntRect,
    SCREEN_MARGIN,
    apply_plan,
    client_budget,
    plan_geometry,
    resolve_available_rect,
)

_PREFERRED_WIDTH = 380
_LAYOUT_H_MARGINS = 24
_LAYOUT_V_MARGINS = 12
_LIST_SUMMARY_TRIGGER = 12
_LIST_SUMMARY_KEEP = 8


def _wrap_anywhere(text, font, max_width):
    """Insert breaks so long unspaced paths wrap inside *max_width*."""
    if max_width <= 0:
        return text
    fm = QFontMetrics(font)
    out = []
    for paragraph in text.split("\n"):
        if not paragraph:
            out.append("")
            continue
        line = ""
        for char in paragraph:
            trial = line + char
            if line and fm.horizontalAdvance(trial) > max_width:
                out.append(line)
                line = char
            else:
                line = trial
        out.append(line)
    return "\n".join(out)


def _display_tooltip_text(text):
    """Summarize huge item lists for display only; leave ordinary paths intact."""
    lines = text.splitlines()
    nonempty = [line for line in lines if line.strip()]
    if len(nonempty) < _LIST_SUMMARY_TRIGGER:
        return text
    kept = nonempty[:_LIST_SUMMARY_KEEP]
    omitted = len(nonempty) - len(kept)
    return "\n".join(kept) + f"\n另有 {omitted} 项"


class _GlassTooltipPopup(QWidget):
    """Singleton glass-style tooltip popup."""

    _instance = None

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.destroyed.connect(type(self)._clear_instance)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)

        self._scroll = QScrollArea(self)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self._scroll.viewport().setAutoFillBackground(False)

        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.PlainText)
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._label.setStyleSheet(
            "background: transparent; color: #1e293b; font-size: 12px;"
        )
        self._scroll.setWidget(self._label)
        lay.addWidget(self._scroll)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    @classmethod
    def _clear_instance(cls, _object=None):
        cls._instance = None

    @classmethod
    def existing(cls):
        """Return the live popup without creating one during teardown."""
        popup = cls._instance
        if popup is not None and sip.isdeleted(popup):
            cls._instance = None
            return None
        return popup

    @classmethod
    def instance(cls):
        popup = cls.existing()
        if popup is None:
            popup = cls()
            cls._instance = popup
        return popup

    def show_for(self, text, anchor):
        """Show tooltip with *text* anchored just below *anchor* (global coords)."""
        available = resolve_available_rect(anchor_global=anchor, widget=self)
        budget = client_budget(available, FrameInsets(), SCREEN_MARGIN)
        max_frame_w = min(_PREFERRED_WIDTH, max(1, budget.width))
        max_label_w = max(1, max_frame_w - _LAYOUT_H_MARGINS)
        display = _wrap_anywhere(
            _display_tooltip_text(text), self._label.font(), max_label_w,
        )
        self._label.setMaximumWidth(max_label_w)
        self._label.setText(display)
        self._label.adjustSize()
        label_hint = self._label.sizeHint()
        inner_w = min(max(1, label_hint.width()), max_label_w)
        inner_h = max(1, label_hint.height())
        max_inner_h = max(1, budget.height - _LAYOUT_V_MARGINS)
        shown_h = min(inner_h, max_inner_h)
        self._scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if inner_h > shown_h else Qt.ScrollBarAlwaysOff
        )
        self._scroll.setFixedSize(inner_w, shown_h)
        frame_w = inner_w + _LAYOUT_H_MARGINS
        frame_h = shown_h + _LAYOUT_V_MARGINS
        self.resize(frame_w, frame_h)
        point = anchor if isinstance(anchor, QPoint) else QPoint(int(anchor.x()), int(anchor.y()))
        placed = IntRect(point.x() - frame_w // 2, point.y(), max(1, frame_w), 1)
        plan = plan_geometry(
            available,
            (frame_w, frame_h),
            frame=FrameInsets(),
            margin=SCREEN_MARGIN,
            anchor=placed,
            position="below",
            gap=0,
        )
        apply_plan(self, plan)
        self.show()
        self._hide_timer.stop()

    def schedule_hide(self, delay_ms=120):
        if not self._hide_timer.isActive():
            self._hide_timer.start(delay_ms)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(
            float(r.x()), float(r.y()),
            float(r.width()), float(r.height()),
            10.0, 10.0,
        )

        # Frosted glass: semi-transparent white fill
        p.fillPath(path, QColor(255, 255, 255, 230))

        # Subtle cool border
        pen = QPen(QColor(209, 219, 235, 200))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)


class _TooltipEventFilter(QObject):
    """Application-level event filter that intercepts QEvent.ToolTip."""

    def eventFilter(self, watched, event):  # noqa: N802
        etype = event.type()

        if etype == QEvent.ToolTip:
            try:
                text = watched.toolTip()
            except RuntimeError:
                return False
            if text:
                # Anchor: center-bottom of widget + 5 px gap
                try:
                    anchor = watched.mapToGlobal(
                        QPoint(watched.width() // 2, watched.height() + 5)
                    )
                except RuntimeError:
                    return False
                _GlassTooltipPopup.instance().show_for(text, anchor)
                return True  # suppress native tooltip

        elif etype in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Hide):
            popup = _GlassTooltipPopup.existing()
            if popup is not None and popup.isVisible():
                popup.schedule_hide()

        return False


_filter = None


def install_glass_tooltips(app=None):
    """Replace native Qt tooltips with glass-style popups app-wide."""
    from PyQt5.QtWidgets import QApplication

    global _filter
    target = app or QApplication.instance()
    if target is None:
        raise RuntimeError("QApplication must exist before install_glass_tooltips()")
    _filter = _TooltipEventFilter()
    target.installEventFilter(_filter)
