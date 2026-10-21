"""Small, non-modal click tip used by the expression check button."""
from PyQt5.QtCore import QEvent, QPoint, QRectF, Qt
from PyQt5.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from ...ui_kit.dialog_geometry import move_in_screen
from ...ui_kit.popup_shell import apply_popup_shell


class ExpressionCheckTip(QWidget):
    """A parented tooltip window; no focus grab or modal event loop."""

    def __init__(self, parent, anchor, row):
        super().__init__(parent, Qt.ToolTip)
        apply_popup_shell(self)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._anchor = anchor
        self._row = row
        self._filter_installed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        self.title_label = QLabel(self)
        self.body_label = QLabel(self)
        for label in (self.title_label, self.body_label):
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.body_label.setStyleSheet("color: #637186; background: transparent; font-size: 12px;")

    def show_message(self, title, body, state):
        self.title_label.setText(title)
        self.body_label.setText(body)
        color = {"ok": "#248653", "error": "#ca414b"}.get(state, "#172132")
        self.title_label.setStyleSheet(
            f"color: {color}; background: transparent; font-size: 12px; font-weight: 600;"
        )
        anchor = self._anchor.mapToGlobal(self._anchor.rect().bottomRight())
        screen = QGuiApplication.screenAt(anchor) or self._anchor.screen()
        available = screen.availableGeometry().adjusted(8, 8, -8, -8)
        self.setFixedWidth(min(278, available.width()))
        self.ensurePolished()
        self.layout().activate()
        # QLabel.sizeHint wraps at its preferred width; using that hint for a
        # fixed-width window leaves unnecessary vertical space between lines.
        self.setFixedHeight(self.layout().totalHeightForWidth(self.width()))
        x = max(available.left(), min(anchor.x() - self.width(), available.right() - self.width() + 1))
        y = anchor.y() + 7
        if y + self.height() > available.bottom():
            y = self._anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 7
        y = max(available.top(), min(y, available.bottom() - self.height() + 1))
        move_in_screen(self, QPoint(x, y))
        if not self._filter_installed:
            QApplication.instance().installEventFilter(self)
            self._filter_installed = True
        self.show()

    def hideEvent(self, event):
        if self._filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._filter_installed = False
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.hide()
            return True
        if event.type() == QEvent.MouseButtonPress:
            point = event.globalPos()
            row_rect = self._row.rect()
            row_rect.moveTopLeft(self._row.mapToGlobal(QPoint(0, 0)))
            if not row_rect.contains(point) and not self.frameGeometry().contains(point):
                self.hide()
        elif event.type() == QEvent.FocusIn and isinstance(obj, QWidget):
            if obj is not self._row and not self._row.isAncestorOf(obj):
                self.hide()
        elif event.type() in (QEvent.Wheel, QEvent.ApplicationDeactivate):
            self.hide()
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        # Explicit paint avoids native/QSS rectangular backing on translucent
        # top-level windows. The outer corner pixels stay transparent.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#d5dfe9"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 6, 6)
