"""Glass-style tooltip replacement for the entire application.

Call ``install_glass_tooltips(app)`` once after QApplication is created.
All widgets that have a toolTip() set will use the glass popup instead of
the native Qt tooltip, positioned just below the hovered widget.
"""
from PyQt5.QtCore import QEvent, QObject, QPoint, QTimer, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


class _GlassTooltipPopup(QWidget):
    """Singleton glass-style tooltip popup."""

    _instance = None

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)

        self._label = QLabel()
        self._label.setStyleSheet(
            "background: transparent; color: #1e293b; font-size: 12px;"
        )
        lay.addWidget(self._label)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def show_for(self, text, anchor):
        """Show tooltip with *text* anchored just below *anchor* (global coords)."""
        self._label.setText(text)
        self.adjustSize()
        # Center horizontally on anchor, place below it
        x = anchor.x() - self.width() // 2
        y = anchor.y()
        # Use the screen that contains the anchor point, not self.screen(), which
        # returns the popup's previous screen and causes tooltips to jump to the
        # wrong monitor in dual-screen setups.
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is not None:
            sg = screen.availableGeometry()
            x = max(sg.left() + 4, min(x, sg.right() - self.width() - 4))
            if y + self.height() + 4 > sg.bottom():
                y = anchor.y() - self.height() - 5
        self.move(x, y)
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
            except Exception:
                return False
            if text:
                # Anchor: center-bottom of widget + 5 px gap
                anchor = watched.mapToGlobal(
                    QPoint(watched.width() // 2, watched.height() + 5)
                )
                _GlassTooltipPopup.instance().show_for(text, anchor)
                return True  # suppress native tooltip

        elif etype in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Hide):
            popup = _GlassTooltipPopup.instance()
            if popup.isVisible():
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
