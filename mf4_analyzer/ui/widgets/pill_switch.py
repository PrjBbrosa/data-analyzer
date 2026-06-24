"""Reusable compact pill toggle switch + clickable paired label.

Extracted from the GPU-render control so other sections (time-domain 滤波) can
share the exact same visual — track / knob colours, 44×24 size, disabled tint.
``PillSwitch`` is a hand-painted ``QAbstractButton``; ``toggled(bool)`` /
``isChecked()`` / ``setChecked()`` behave like a normal checkable button, so a
caller can swap a ``QCheckBox`` for it without touching its enable/sync logic.
"""
from PyQt5.QtCore import Qt, QSize, QRectF
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QAbstractButton, QLabel


class PillSwitch(QAbstractButton):
    """Compact hand-painted pill switch (44×24). Drop-in for a checkable button."""

    def __init__(self, parent=None, *, object_name=None, accessible_name=None):
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        if accessible_name:
            self.setAccessibleName(accessible_name)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 24)

    def sizeHint(self):
        return QSize(44, 24)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        on = self.isChecked()
        enabled = self.isEnabled()
        track = QColor("#1769e0" if on else "#dbe3ee")
        border = QColor("#1769e0" if on else "#aeb9c9")
        knob = QColor("#ffffff")
        knob_border = QColor("#d1d9e5")
        if not enabled:
            track = QColor("#edf1f6")
            border = QColor("#d5dde8")
            knob = QColor("#f8fafc")
            knob_border = QColor("#e2e8f0")

        rect = QRectF(1.0, 2.0, self.width() - 2.0, self.height() - 4.0)
        radius = rect.height() / 2.0
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(track)
        painter.drawRoundedRect(rect, radius, radius)

        diameter = rect.height() - 4.0
        knob_x = (
            rect.right() - diameter - 2.0
            if on else rect.left() + 2.0
        )
        knob_rect = QRectF(knob_x, rect.top() + 2.0, diameter, diameter)
        painter.setPen(QPen(knob_border, 1.0))
        painter.setBrush(knob)
        painter.drawEllipse(knob_rect)


class PillSwitchLabel(QLabel):
    """Clickable text label paired with a :class:`PillSwitch` (click → toggle)."""

    def __init__(self, text, switch, parent=None, *, object_name=None):
        super().__init__(text, parent)
        self._switch = switch
        if object_name:
            self.setObjectName(object_name)
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._switch.isEnabled():
            self._switch.click()
            event.accept()
            return
        super().mousePressEvent(event)
