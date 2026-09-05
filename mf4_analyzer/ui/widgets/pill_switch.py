"""Reusable compact pill toggle switch + clickable paired label.

Extracted from the GPU-render control so other sections (time-domain 滤波) can
share the exact same visual — track / knob colours, 44×24 size, disabled tint.
``PillSwitch`` is a hand-painted ``QAbstractButton``; ``toggled(bool)`` /
``isChecked()`` / ``setChecked()`` behave like a normal checkable button, so a
caller can swap a ``QCheckBox`` for it without touching its enable/sync logic.
"""
from PyQt5.QtCore import QEvent, Qt, QSize, QRectF
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import QAbstractButton, QLabel

from ...ui_kit.control_style import CONTROL_COLORS
from ...ui_kit.motion import (
    POLICY_OFF,
    ValueDriver,
    duration_ms,
    resolve_policy,
)


def _token(name):
    return QColor(CONTROL_COLORS[name])


def _mix_color(start, end, progress):
    t = 0.0 if progress <= 0.0 else 1.0 if progress >= 1.0 else float(progress)
    return QColor(
        int(round(start.red() + (end.red() - start.red()) * t)),
        int(round(start.green() + (end.green() - start.green()) * t)),
        int(round(start.blue() + (end.blue() - start.blue()) * t)),
        int(round(start.alpha() + (end.alpha() - start.alpha()) * t)),
    )


class PillSwitch(QAbstractButton):
    """Compact hand-painted pill switch (44×24). Drop-in for a checkable button."""

    def __init__(self, parent=None, *, object_name=None, accessible_name=None):
        self._motion_policy = POLICY_OFF
        self._value_driver = None
        self._present = 0.0
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

    def motion_policy(self):
        return self._motion_policy

    def set_motion_policy(self, policy):
        self._motion_policy = resolve_policy(policy)
        self._snap_presentation_to_checked()

    def checkStateSet(self):
        super().checkStateSet()
        self._follow_checked_state()

    def nextCheckState(self):
        super().nextCheckState()
        self._follow_checked_state()

    def hideEvent(self, event):
        self._snap_presentation_to_checked()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        kind = event.type()
        if kind == QEvent.EnabledChange:
            self._snap_presentation_to_checked()
        elif kind == QEvent.ActivationChange and not self.isActiveWindow():
            self._snap_presentation_to_checked()

    def _should_interpolate(self):
        return (
            self._motion_policy.interpolates()
            and self.isVisible()
            and self.isEnabled()
            and not self.signalsBlocked()
        )

    def _ensure_driver(self):
        if self._value_driver is None:
            self._value_driver = ValueDriver(self, on_value=self._on_present_value)
            self._value_driver.snap(self._present)
        return self._value_driver

    def _on_present_value(self, value):
        self._present = 0.0 if value is None else float(value)
        self.update()

    def _snap_presentation_to_checked(self):
        end = 1.0 if self.isChecked() else 0.0
        if self._value_driver is not None:
            self._value_driver.snap(end)
            return
        self._present = end
        self.update()

    def _follow_checked_state(self):
        end = 1.0 if self.isChecked() else 0.0
        if not self._should_interpolate():
            self._snap_presentation_to_checked()
            return
        self._ensure_driver().go(
            end, duration_ms=duration_ms("switch", self._motion_policy)
        )

    def _presentation(self):
        driver = self._value_driver
        if driver is not None:
            current = driver.current()
            if current is not None:
                return max(0.0, min(1.0, float(current)))
        return 1.0 if self.isChecked() else 0.0

    def _paints_interpolated(self):
        driver = self._value_driver
        return bool(
            self.isEnabled()
            and driver is not None
            and driver.is_active()
        )

    def _enabled_ink(self, on):
        if on:
            if self.isDown():
                track_top = _token("CONTROL_ACCENT")
                track_bottom = _token("CONTROL_ACCENT_DARK")
                border = _token("CONTROL_ACCENT_DARK")
            elif self.underMouse():
                track_top = _token("CONTROL_ACCENT_HI")
                track_bottom = _token("CONTROL_ACCENT_HI")
                border = _token("CONTROL_ACCENT_BORDER")
            else:
                track_top = _token("CONTROL_ACCENT_HI")
                track_bottom = _token("CONTROL_ACCENT")
                border = _token("CONTROL_ACCENT_BORDER")
            knob_top = _token("CONTROL_SURFACE_TOP")
            knob_bottom = _token("CONTROL_SURFACE_BOTTOM")
            knob_border = _token("CONTROL_LINE")
        elif self.isDown():
            track_top = _token("CONTROL_TRACK")
            track_bottom = _token("CONTROL_TRACK")
            border = _token("CONTROL_LINE_HOVER")
            knob_top = _token("CONTROL_SURFACE_TOP")
            knob_bottom = _token("CONTROL_SURFACE_BOTTOM")
            knob_border = _token("CONTROL_LINE_HOVER")
        elif self.underMouse():
            track_top = _token("CONTROL_SURFACE_TOP")
            track_bottom = _token("CONTROL_SURFACE_BOTTOM")
            border = _token("CONTROL_LINE_HOVER")
            knob_top = _token("CONTROL_SURFACE_TOP")
            knob_bottom = _token("CONTROL_SURFACE_BOTTOM")
            knob_border = _token("CONTROL_LINE")
        else:
            track_top = _token("CONTROL_SURFACE_BOTTOM")
            track_bottom = _token("CONTROL_TRACK")
            border = _token("CONTROL_TRACK_LINE")
            knob_top = _token("CONTROL_SURFACE_TOP")
            knob_bottom = _token("CONTROL_SURFACE_BOTTOM")
            knob_border = _token("CONTROL_LINE")
        return (
            track_top,
            track_bottom,
            border,
            knob_top,
            knob_bottom,
            knob_border,
        )

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        on = self.isChecked()
        enabled = self.isEnabled()
        interpolate = self._paints_interpolated()
        progress = self._presentation() if interpolate else (1.0 if on else 0.0)

        # Each state only changes ink.  The shared 44×24 geometry, track
        # rect, knob diameter and left/right insets stay fixed throughout.
        if not enabled:
            track_top = _token("CONTROL_DISABLED_BG")
            track_bottom = _token("CONTROL_TRACK")
            border = _token("CONTROL_DISABLED_LINE")
            knob_top = _token("CONTROL_SURFACE_TOP")
            knob_bottom = _token("CONTROL_SURFACE_BOTTOM")
            knob_border = _token("CONTROL_DISABLED_LINE")
        elif interpolate:
            off_ink = self._enabled_ink(False)
            on_ink = self._enabled_ink(True)
            track_top = _mix_color(off_ink[0], on_ink[0], progress)
            track_bottom = _mix_color(off_ink[1], on_ink[1], progress)
            border = _mix_color(off_ink[2], on_ink[2], progress)
            knob_top = _mix_color(off_ink[3], on_ink[3], progress)
            knob_bottom = _mix_color(off_ink[4], on_ink[4], progress)
            knob_border = _mix_color(off_ink[5], on_ink[5], progress)
        else:
            (
                track_top,
                track_bottom,
                border,
                knob_top,
                knob_bottom,
                knob_border,
            ) = self._enabled_ink(on)

        rect = QRectF(1.0, 2.0, self.width() - 2.0, self.height() - 4.0)
        radius = rect.height() / 2.0
        track_gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        track_gradient.setColorAt(0.0, track_top)
        track_gradient.setColorAt(1.0, track_bottom)
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(track_gradient)
        painter.drawRoundedRect(rect, radius, radius)

        diameter = rect.height() - 4.0
        knob_left = rect.left() + 2.0
        knob_right = rect.right() - diameter - 2.0
        if interpolate:
            knob_x = knob_left + (knob_right - knob_left) * progress
        else:
            knob_x = knob_right if on else knob_left
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
