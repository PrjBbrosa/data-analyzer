"""CursorPill, _QualityStatusIndicator, and _CURSOR_HTML_SEP constant."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
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
        lay.setContentsMargins(10, 7, 12, 8)
        lay.setSpacing(2)
        self._primary = QLabel("", self)
        self._primary.setObjectName("cursorPillPrimary")
        self._primary.setTextFormat(Qt.RichText)
        self._primary.setTextInteractionFlags(Qt.NoTextInteraction)
        self._toggle_btn = QPushButton("−", self)
        self._toggle_btn.setObjectName("cursorPillToggle")
        self._toggle_btn.setFixedSize(16, 16)
        self._toggle_btn.setCursor(Qt.ArrowCursor)
        self._toggle_btn.clicked.connect(self._toggle_mode)
        # First row: primary readout, then the +/- toggle pinned a fixed gap
        # after the text. The trailing stretch absorbs any extra width a wider
        # detail block contributes below, so the toggle keeps a constant
        # distance from the first line across full/mini instead of jumping with
        # the pill's right edge.
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)
        top_row.addWidget(self._primary, 0, Qt.AlignVCenter)
        top_row.addWidget(self._toggle_btn, 0, Qt.AlignVCenter)
        top_row.addStretch(1)
        self._detail = QLabel("", self)
        self._detail.setObjectName("cursorPillDetail")
        self._detail.setTextFormat(Qt.RichText)
        self._detail.setTextInteractionFlags(Qt.NoTextInteraction)
        self._detail.setVisible(False)
        lay.addLayout(top_row)
        lay.addWidget(self._detail)
        self._drag_offset = None
        # User-positioned flag — true after first manual drag, so resize events
        # respect the chosen spot instead of snapping back to default corner.
        self._user_placed = False
        self._mode = "full"
        self._dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        self._update_toggle_button()

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
        self._dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        if html:
            self._detail.setText(html)
            self._detail.setToolTip("")
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setToolTip("")
            self._detail.setVisible(False)
        self.adjustSize()

    def set_single_detail_html(self, full_html, mini_html, tooltip=""):
        self._dual_rows = []
        self._single_full_detail = full_html or ""
        self._single_mini_detail = mini_html or ""
        self._single_tooltip = tooltip or ""
        self._refresh_detail()
        self.adjustSize()

    def snapshot(self):
        return {
            "primary": self._primary.text(),
            "detail": self._detail.text(),
            "detail_visible": self.has_detail(),
            "detail_tooltip": self._detail.toolTip(),
            "mode": self._mode,
            "dual_rows": list(self._dual_rows),
            "single_full_detail": self._single_full_detail,
            "single_mini_detail": self._single_mini_detail,
            "single_tooltip": self._single_tooltip,
        }

    def restore_snapshot(self, snapshot):
        self._mode = snapshot.get("mode") or "full"
        if self._mode not in {"full", "mini"}:
            self._mode = "full"
        self._primary.setText(snapshot.get("primary") or "")
        self._dual_rows = list(snapshot.get("dual_rows") or [])
        self._single_full_detail = snapshot.get("single_full_detail") or ""
        self._single_mini_detail = snapshot.get("single_mini_detail") or ""
        self._single_tooltip = snapshot.get("single_tooltip") or ""
        self._update_toggle_button()
        if self._dual_rows or self._single_full_detail:
            self._refresh_detail()
        else:
            detail = snapshot.get("detail") if snapshot.get("detail_visible") else ""
            if detail:
                self._detail.setText(detail)
                self._detail.setToolTip(snapshot.get("detail_tooltip") or "")
                self._detail.setVisible(True)
            else:
                self._detail.clear()
                self._detail.setToolTip("")
                self._detail.setVisible(False)
        self.adjustSize()

    def has_detail(self):
        return not self._detail.isHidden() and bool(self._detail.text())

    def clear(self):
        self._primary.clear()
        self._detail.clear()
        self._detail.setToolTip("")
        self._detail.setVisible(False)
        self._dual_rows = []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
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

    def _toggle_mode(self):
        old_right = self.x() + self.width()
        old_top = self.y()
        self._mode = "mini" if self._mode == "full" else "full"
        self._update_toggle_button()
        self._refresh_detail()
        self.adjustSize()
        self.move_preserving_right_edge(old_right, old_top)

    def move_preserving_right_edge(self, right_edge, top):
        parent = self.parentWidget()
        new_x = int(right_edge) - self.width()
        new_y = int(top)
        if parent is not None:
            anchor_right = max(0, min(int(right_edge), parent.width()))
            max_x = max(parent.width() - self.width(), 0)
            max_y = max(parent.height() - self.height(), 0)
            new_x = max(0, min(anchor_right - self.width(), max_x))
            new_y = max(0, min(new_y, max_y))
        self.move(new_x, new_y)

    # Backwards-compatible private alias for internal callers.
    _move_preserving_right_edge = move_preserving_right_edge

    def _update_toggle_button(self):
        self._toggle_btn.setText("+" if self._mode == "mini" else "−")
        self._toggle_btn.setToolTip(
            "展开通道名" if self._mode == "mini" else "收起为数值"
        )
        self._toggle_btn.setProperty("cursorPillMode", self._mode)
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)

    def set_dual_rows(self, rows):
        self._dual_rows = rows or []
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        self._refresh_detail()
        if self._dual_rows:
            self._detail.setVisible(True)
        self.adjustSize()

    def _refresh_detail(self):
        if self._dual_rows:
            from ..plot_helpers import _format_dual_html
            html = (
                _format_dual_html(self._dual_rows)
                if self._mode == "full"
                else _format_mini_html(self._dual_rows)
            )
            tooltip = ""
        elif self._single_full_detail:
            html = (
                self._single_mini_detail
                if self._mode == "mini" and self._single_mini_detail
                else self._single_full_detail
            )
            tooltip = self._single_tooltip if self._mode == "mini" else ""
        else:
            html = ""
            tooltip = ""
        if html:
            self._detail.setText(html)
            self._detail.setToolTip(tooltip)
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setToolTip("")
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
