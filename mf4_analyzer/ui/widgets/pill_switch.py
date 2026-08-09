"""Reusable compact pill toggle switch + clickable paired label.

Extracted from the GPU-render control so other sections (time-domain 滤波) can
share the exact same visual — track / knob colours, 44×24 size, disabled tint.
``PillSwitch`` is a hand-painted ``QAbstractButton``; ``toggled(bool)`` /
``isChecked()`` / ``setChecked()`` behave like a normal checkable button, so a
caller can swap a ``QCheckBox`` for it without touching its enable/sync logic.
"""
from PyQt5.QtCore import Qt, QSize, QRectF
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import QAbstractButton, QLabel

from ...ui_kit.control_style import CONTROL_COLORS


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
        color = lambda name: QColor(CONTROL_COLORS[name])

        # Each state only changes ink.  The shared 44×24 geometry, track
        # rect, knob diameter and left/right insets stay fixed throughout.
        if not enabled:
            track_top = color("CONTROL_DISABLED_BG")
            track_bottom = color("CONTROL_TRACK")
            border = color("CONTROL_DISABLED_LINE")
            knob_top = color("CONTROL_SURFACE_TOP")
            knob_bottom = color("CONTROL_SURFACE_BOTTOM")
            knob_border = color("CONTROL_DISABLED_LINE")
        elif on:
            if self.isDown():
                track_top = color("CONTROL_ACCENT")
                track_bottom = color("CONTROL_ACCENT_DARK")
                border = color("CONTROL_ACCENT_DARK")
            elif self.underMouse():
                track_top = color("CONTROL_ACCENT_HI")
                track_bottom = color("CONTROL_ACCENT_HI")
                border = color("CONTROL_ACCENT_BORDER")
            else:
                track_top = color("CONTROL_ACCENT_HI")
                track_bottom = color("CONTROL_ACCENT")
                border = color("CONTROL_ACCENT_BORDER")
            knob_top = color("CONTROL_SURFACE_TOP")
            knob_bottom = color("CONTROL_SURFACE_BOTTOM")
            knob_border = color("CONTROL_LINE")
        elif self.isDown():
            track_top = color("CONTROL_TRACK")
            track_bottom = color("CONTROL_TRACK")
            border = color("CONTROL_LINE_HOVER")
            knob_top = color("CONTROL_SURFACE_TOP")
            knob_bottom = color("CONTROL_SURFACE_BOTTOM")
            knob_border = color("CONTROL_LINE_HOVER")
        elif self.underMouse():
            track_top = color("CONTROL_SURFACE_TOP")
            track_bottom = color("CONTROL_SURFACE_BOTTOM")
            border = color("CONTROL_LINE_HOVER")
            knob_top = color("CONTROL_SURFACE_TOP")
            knob_bottom = color("CONTROL_SURFACE_BOTTOM")
            knob_border = color("CONTROL_LINE")
        else:
            track_top = color("CONTROL_SURFACE_BOTTOM")
            track_bottom = color("CONTROL_TRACK")
            border = color("CONTROL_TRACK_LINE")
            knob_top = color("CONTROL_SURFACE_TOP")
            knob_bottom = color("CONTROL_SURFACE_BOTTOM")
            knob_border = color("CONTROL_LINE")

        rect = QRectF(1.0, 2.0, self.width() - 2.0, self.height() - 4.0)
        radius = rect.height() / 2.0
        track_gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        track_gradient.setColorAt(0.0, track_top)
        track_gradient.setColorAt(1.0, track_bottom)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(track_gradient)
        painter.drawRoundedRect(rect, radius, radius)

        diameter = rect.height() - 4.0
        knob_x = (
            rect.right() - diameter - 2.0
            if on else rect.left() + 2.0
        )
        knob_rect = QRectF(knob_x, rect.top() + 2.0, diameter, diameter)
        # Keep the knob white, but let its final few pixels cool very slightly
        # toward the lower edge so it does not read as a flat cut-out.
        knob_gradient = QLinearGradient(knob_rect.topLeft(), knob_rect.bottomLeft())
        knob_gradient.setColorAt(0.0, knob_top)
        knob_gradient.setColorAt(0.72, knob_top)
        knob_gradient.setColorAt(1.0, knob_bottom)
        painter.setPen(QPen(knob_border, 1.0))
        painter.setBrush(knob_gradient)
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
