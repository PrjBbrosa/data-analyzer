"""CursorPill, _QualityStatusIndicator, and _CURSOR_HTML_SEP constant."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QLabel, QPushButton, QVBoxLayout,
)

from PyQt5.QtCore import QRectF

from ._helpers import _format_mini_html

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CURSOR_PILL_RADIUS = 9.0
_CURSOR_PILL_BG = QColor(255, 255, 255, 235)
_CURSOR_PILL_BORDER = QColor("#d8e0eb")

_CURSOR_HTML_SEP = '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class CursorPill(QFrame):
    """Draggable floating pill with a primary line (time / A·B / ΔT) and an
    optional detail block (per-channel Min/Max/Avg/△ as RichText). The
    user can drag it anywhere inside the canvas area."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("cursorPill")
        self.setCursor(Qt.OpenHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 22, 8)
        lay.setSpacing(4)
        self._primary = QLabel("", self)
        self._primary.setObjectName("cursorPillPrimary")
        self._primary.setTextFormat(Qt.RichText)
        self._primary.setTextInteractionFlags(Qt.NoTextInteraction)
        self._detail = QLabel("", self)
        self._detail.setObjectName("cursorPillDetail")
        self._detail.setTextFormat(Qt.RichText)
        self._detail.setTextInteractionFlags(Qt.NoTextInteraction)
        self._detail.setVisible(False)
        lay.addWidget(self._primary)
        lay.addWidget(self._detail)
        self._drag_offset = None
        # User-positioned flag — true after first manual drag, so resize events
        # respect the chosen spot instead of snapping back to default corner.
        self._user_placed = False
        self._mode = "full"
        self._dual_rows = []
        self._toggle_btn = QPushButton("−", self)
        self._toggle_btn.setObjectName("cursorPillToggle")
        self._toggle_btn.setFixedSize(16, 16)
        self._toggle_btn.setCursor(Qt.ArrowCursor)
        self._toggle_btn.clicked.connect(self._toggle_mode)
        self._toggle_btn.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.setBrush(_CURSOR_PILL_BG)
            painter.setPen(QPen(_CURSOR_PILL_BORDER, 1.0))
            painter.drawRoundedRect(rect, _CURSOR_PILL_RADIUS, _CURSOR_PILL_RADIUS)
        finally:
            painter.end()

    def primary_text(self):
        return self._primary.text()

    def set_primary(self, text):
        self._primary.setText(text)
        self.adjustSize()

    def set_detail_html(self, html):
        if html:
            self._detail.setText(html)
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setVisible(False)
        self.adjustSize()

    def has_detail(self):
        return not self._detail.isHidden() and bool(self._detail.text())

    def clear(self):
        self._primary.clear()
        self._detail.clear()
        self._detail.setVisible(False)
        self._dual_rows = []
        self.setVisible(False)

    def mark_user_placed(self, value=True):
        self._user_placed = bool(value)

    def is_user_placed(self):
        return self._user_placed

    # ---- drag handling ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_offset = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and (e.buttons() & Qt.LeftButton):
            parent = self.parentWidget()
            new_top_left = self.mapToParent(e.pos() - self._drag_offset)
            if parent is not None:
                pw, ph = parent.width(), parent.height()
                x = max(0, min(new_top_left.x(), pw - self.width()))
                y = max(0, min(new_top_left.y(), ph - self.height()))
                self.move(x, y)
            else:
                self.move(new_top_left)
            self._user_placed = True
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.setCursor(Qt.OpenHandCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        btn_w = self._toggle_btn.width()
        self._toggle_btn.move(self.width() - btn_w - 4, 4)

    def _toggle_mode(self):
        self._mode = "mini" if self._mode == "full" else "full"
        self._toggle_btn.setText("+" if self._mode == "mini" else "−")
        self._refresh_detail()
        self.adjustSize()

    def set_dual_rows(self, rows):
        self._dual_rows = rows or []
        self._refresh_detail()
        if self._dual_rows:
            self._detail.setVisible(True)
        self.adjustSize()

    def _refresh_detail(self):
        if not self._dual_rows:
            return
        from ..canvases import _format_dual_html
        html = _format_dual_html(self._dual_rows) if self._mode == "full" else _format_mini_html(self._dual_rows)
        if html:
            self._detail.setText(html)
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setVisible(False)


class _QualityStatusIndicator(QFrame):
    """Small hoverable AA status dot overlaid on the chart card chrome."""

    _COLORS = {
        "green": QColor("#22c55e"),
        "yellow": QColor("#f59e0b"),
        "red": QColor("#ef4444"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chartQualityIndicator")
        self.setFixedSize(20, 20)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._state = "red"
        self.set_quality_status({
            "state": "red",
            "tooltip": "抗锯齿未激活：无曲线",
        })

    def set_quality_status(self, status):
        state = str((status or {}).get("state") or "red")
        if state not in self._COLORS:
            state = "red"
        self._state = state
        self.setProperty("qualityState", state)
        self.setToolTip(str((status or {}).get("tooltip") or "抗锯齿状态未知"))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(5.0, 5.0, -5.0, -5.0)
            painter.setBrush(self._COLORS.get(self._state, self._COLORS["red"]))
            painter.setPen(QPen(QColor(255, 255, 255, 230), 1.0))
            painter.drawEllipse(rect)
        finally:
            painter.end()
