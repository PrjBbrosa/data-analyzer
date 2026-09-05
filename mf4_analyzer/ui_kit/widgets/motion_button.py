"""Sample QPushButton with optional chrome-color interpolation.

This subclass is created only by the native-motion demo and its tests. It
does not replace production ``QPushButton`` instances. Missing / ``None``
policy keeps the standard QSS paint path and starts no animation.
"""
from __future__ import annotations

from dataclasses import dataclass

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QRect, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QStyleOptionFocusRect

from mf4_analyzer.ui_kit.control_style import CONTROL_COLORS, CONTROL_HEIGHTS, set_control_role
from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui_kit.motion import (
    MotionPolicy,
    POLICY_OFF,
    ValueDriver,
    duration_ms,
    resolve_policy,
)


SAMPLE_ROLES = ("primary", "secondary", "quiet", "icon")
SAMPLE_LABELS = {
    "primary": "确定",
    "secondary": "取消",
    "quiet": "更多",
    "icon": "",
}
_CHROME_ROLES = SAMPLE_ROLES
_RADIUS = 8.0


def _token(name: str, alpha: int = 255) -> QColor:
    color = QColor(CONTROL_COLORS[name])
    color.setAlpha(alpha)
    return color


_TRANSPARENT = QColor(0, 0, 0, 0)


@dataclass(frozen=True)
class _Chrome:
    fill_top: QColor
    fill_bottom: QColor
    border: QColor
    text: QColor


def _solid(fill: QColor, border: QColor, text: QColor) -> _Chrome:
    return _Chrome(fill, QColor(fill), border, text)


def _gradient(top: QColor, bottom: QColor, border: QColor, text: QColor) -> _Chrome:
    return _Chrome(top, bottom, border, text)


def _build_chrome_table() -> dict[str, dict[str, _Chrome]]:
    disabled = _solid(
        _token("CONTROL_DISABLED_BG"),
        _token("CONTROL_DISABLED_LINE"),
        _token("CONTROL_TEXT_MUTED"),
    )
    quiet_disabled = _solid(_TRANSPARENT, _TRANSPARENT, _token("CONTROL_TEXT_MUTED"))
    return {
        "primary": {
            "idle": _gradient(
                _token("CONTROL_ACCENT_HI"),
                _token("CONTROL_ACCENT"),
                _token("CONTROL_ACCENT_BORDER"),
                _token("CONTROL_SURFACE_TOP"),
            ),
            "hover": _solid(
                _token("CONTROL_ACCENT_HI"),
                _token("CONTROL_ACCENT"),
                _token("CONTROL_SURFACE_TOP"),
            ),
            "pressed": _solid(
                _token("CONTROL_ACCENT_DARK"),
                _token("CONTROL_ACCENT_DARK"),
                _token("CONTROL_SURFACE_TOP"),
            ),
            "checked": _solid(
                _token("CONTROL_ACCENT"),
                _token("CONTROL_ACCENT_BORDER"),
                _token("CONTROL_SURFACE_TOP"),
            ),
            "disabled": disabled,
        },
        "secondary": {
            "idle": _gradient(
                _token("CONTROL_SURFACE_TOP"),
                _token("CONTROL_ACCENT_WASH"),
                _token("CONTROL_ACCENT_LINE_SOFT"),
                _token("CONTROL_ACCENT"),
            ),
            "hover": _solid(
                _token("CONTROL_ACCENT_WASH"),
                _token("CONTROL_ACCENT"),
                _token("CONTROL_ACCENT_DARK"),
            ),
            "pressed": _solid(
                _token("CONTROL_TRACK"),
                _token("CONTROL_ACCENT_LINE_SOFT"),
                _token("CONTROL_ACCENT"),
            ),
            "checked": _solid(
                _token("CONTROL_ACCENT_WASH"),
                _token("CONTROL_ACCENT"),
                _token("CONTROL_ACCENT_DARK"),
            ),
            "disabled": disabled,
        },
        "quiet": {
            "idle": _solid(_TRANSPARENT, _TRANSPARENT, _token("CONTROL_TEXT_MUTED")),
            "hover": _solid(
                _token("CONTROL_ACCENT_WASH"),
                _token("CONTROL_LINE_HOVER"),
                _token("CONTROL_TEXT"),
            ),
            "pressed": _solid(
                _token("CONTROL_TRACK"),
                _token("CONTROL_TRACK_LINE"),
                _token("CONTROL_TEXT_MUTED"),
            ),
            "checked": _solid(
                _token("CONTROL_ACCENT_WASH"),
                _token("CONTROL_SELECT_LINE"),
                _token("CONTROL_TEXT_ON_SELECT"),
            ),
            "disabled": quiet_disabled,
        },
        "icon": {
            "idle": _solid(_TRANSPARENT, _TRANSPARENT, _token("CONTROL_TEXT_MUTED")),
            "hover": _solid(
                _token("CONTROL_ACCENT_WASH"),
                _token("CONTROL_LINE_HOVER"),
                _token("CONTROL_TEXT"),
            ),
            "pressed": _solid(
                _token("CONTROL_TRACK"),
                _token("CONTROL_TRACK_LINE"),
                _token("CONTROL_TEXT_MUTED"),
            ),
            "checked": _solid(
                _token("CONTROL_ACCENT_WASH"),
                _token("CONTROL_SELECT_LINE"),
                _token("CONTROL_TEXT_ON_SELECT"),
            ),
            "disabled": quiet_disabled,
        },
        "": {
            "idle": _gradient(
                _token("CONTROL_SURFACE_TOP"),
                _token("CONTROL_SURFACE_BOTTOM"),
                _token("CONTROL_LINE"),
                _token("CONTROL_TEXT"),
            ),
            "hover": _solid(
                _token("CONTROL_ACCENT_WASH"),
                _token("CONTROL_LINE_HOVER"),
                _token("CONTROL_TEXT"),
            ),
            "pressed": _solid(
                _token("CONTROL_TRACK"),
                _token("CONTROL_LINE"),
                _token("CONTROL_TEXT"),
            ),
            "checked": _solid(
                _token("CONTROL_ACCENT_WASH"),
                _token("CONTROL_SELECT_LINE"),
                _token("CONTROL_TEXT_ON_SELECT"),
            ),
            "disabled": disabled,
        },
    }


_CHROME = _build_chrome_table()


def _mix_channel(start: int, end: int, amount: float) -> int:
    return int(round(start + (end - start) * amount))


def _mix_color(start: QColor, end: QColor, amount: float) -> QColor:
    amount = 0.0 if amount < 0.0 else 1.0 if amount > 1.0 else float(amount)
    return QColor(
        _mix_channel(start.red(), end.red(), amount),
        _mix_channel(start.green(), end.green(), amount),
        _mix_channel(start.blue(), end.blue(), amount),
        _mix_channel(start.alpha(), end.alpha(), amount),
    )


def _mix_chrome(start: _Chrome, end: _Chrome, amount: float) -> _Chrome:
    return _Chrome(
        _mix_color(start.fill_top, end.fill_top, amount),
        _mix_color(start.fill_bottom, end.fill_bottom, amount),
        _mix_color(start.border, end.border, amount),
        _mix_color(start.text, end.text, amount),
    )


def make_sample_button(
    role: str,
    parent=None,
    *,
    icon_edge: int | None = None,
) -> MotionButton:
    """Build one of the four first-round sample buttons."""
    if role not in SAMPLE_LABELS:
        raise ValueError(f"unknown sample role {role!r}; expected one of {SAMPLE_ROLES}")
    button = MotionButton(SAMPLE_LABELS[role], parent)
    if role == "icon":
        set_control_role(button, role, size="compact")
        button.setIcon(Icons.search())
        button.setIconSize(QSize(16, 16))
        edge = 28 if icon_edge is None else int(icon_edge)
        button.setFixedSize(edge, edge)
    else:
        set_control_role(button, role, size="base")
        button.setFixedHeight(CONTROL_HEIGHTS["base"])
    return button


class MotionButton(QPushButton):
    """QPushButton sample whose chrome colors can interpolate under a policy."""

    def __init__(self, *args, role: str | None = None, size: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._motion_policy = POLICY_OFF
        self._filter_window = None
        self._hover_driver = ValueDriver(self, on_value=self._on_chrome_value)
        self._press_driver = ValueDriver(self, on_value=self._on_chrome_value)
        self._hover_driver.snap(0.0)
        self._press_driver.snap(0.0)
        self.setAttribute(Qt.WA_Hover, True)
        self.pressed.connect(self._on_pressed)
        self.released.connect(self._on_released)
        if role is not None:
            set_control_role(self, role, size=size)
        elif size is not None:
            self.setProperty("controlSize", size)

    def setDown(self, down):
        was_down = self.isDown()
        super().setDown(down)
        if was_down == self.isDown():
            return
        self._sync_press_from_down()

    def motion_policy(self) -> MotionPolicy:
        return self._motion_policy

    def set_motion_policy(self, policy: MotionPolicy | None) -> None:
        self._motion_policy = resolve_policy(policy)
        self._snap_to_business_state()
        self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        if not self._motion_policy.interpolates() or not self.isEnabled():
            return
        if self.isDown():
            return
        self._hover_driver.go(1.0, duration_ms=duration_ms("hover_in", self._motion_policy))

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self._motion_policy.interpolates():
            return
        if self.isDown():
            self._hover_driver.snap(0.0)
            return
        self._hover_driver.go(0.0, duration_ms=duration_ms("hover_out", self._motion_policy))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange:
            self._snap_to_business_state()

    def hideEvent(self, event):
        self._clear_transients()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._bind_window_filter()

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.WindowDeactivate
            and watched is self._filter_window
            and self._motion_policy.interpolates()
        ):
            self._clear_transients()
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        if not self._motion_policy.interpolates():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        chrome = self._displayed_chrome()
        self._paint_chrome(painter, chrome)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        if self.isDefault() and self.isEnabled():
            self.style().drawPrimitive(QStyle.PE_FrameDefaultButton, opt, painter, self)
            painter.save()
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(_token("CONTROL_ACCENT"), 2.0))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), _RADIUS - 1.0, _RADIUS - 1.0)
            painter.restore()
        self._paint_contents(painter, opt, chrome)
        if opt.state & QStyle.State_HasFocus:
            focus = QStyleOptionFocusRect()
            focus.state = opt.state
            focus.rect = self.style().subElementRect(QStyle.SE_PushButtonFocusRect, opt, self)
            focus.backgroundColor = chrome.fill_top
            self.style().drawPrimitive(QStyle.PE_FrameFocusRect, focus, painter, self)
            painter.save()
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(_token("CONTROL_ACCENT"), 1.0, Qt.DotLine))
            painter.drawRoundedRect(self.rect().adjusted(3, 3, -4, -4), _RADIUS - 2.0, _RADIUS - 2.0)
            painter.restore()

    def _on_pressed(self) -> None:
        self._sync_press_from_down()

    def _on_released(self) -> None:
        self._sync_press_from_down()

    def _sync_press_from_down(self) -> None:
        if not self._motion_policy.interpolates() or not self.isEnabled():
            return
        if self.isDown():
            self._press_driver.snap(1.0)
            return
        self._press_driver.go(0.0, duration_ms=duration_ms("release", self._motion_policy))

    def _on_chrome_value(self, _value) -> None:
        self.update()

    def _chrome_role(self) -> str:
        role = self.property("role")
        if role in _CHROME_ROLES:
            return str(role)
        return ""

    def _displayed_chrome(self) -> _Chrome:
        table = _CHROME[self._chrome_role()]
        if not self.isEnabled():
            return table["disabled"]
        if self.isChecked():
            return table["checked"]
        rest = _mix_chrome(
            table["idle"],
            table["hover"],
            float(self._hover_driver.current() or 0.0),
        )
        press_amount = float(self._press_driver.current() or 0.0)
        if press_amount <= 0.0:
            return rest
        return _mix_chrome(rest, table["pressed"], press_amount)

    def _paint_chrome(self, painter: QPainter, chrome: _Chrome) -> None:
        rect = self.rect().adjusted(0, 0, -1, -1)
        if chrome.fill_top == chrome.fill_bottom:
            brush = chrome.fill_top
        else:
            brush = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            brush.setColorAt(0.0, chrome.fill_top)
            brush.setColorAt(1.0, chrome.fill_bottom)
        painter.setPen(QPen(chrome.border, 1.0))
        painter.setBrush(brush)
        painter.drawRoundedRect(rect, _RADIUS, _RADIUS)

    def _paint_contents(self, painter: QPainter, opt: QStyleOptionButton, chrome: _Chrome) -> None:
        contents = self.style().subElementRect(QStyle.SE_PushButtonContents, opt, self)
        icon = self.icon()
        text = self.text()
        has_icon = not icon.isNull()
        has_text = bool(text)
        icon_size = self.iconSize()
        paint_mode = QIcon.Disabled if not self.isEnabled() else QIcon.Normal
        paint_state = QIcon.On if self.isChecked() else QIcon.Off
        if has_icon and has_text:
            spacing = self.style().pixelMetric(QStyle.PM_LayoutHorizontalSpacing, opt, self)
            if spacing < 0:
                spacing = 4
            text_width = self.fontMetrics().horizontalAdvance(text)
            total = icon_size.width() + spacing + text_width
            left = contents.x() + max(0, (contents.width() - total) // 2)
            icon_top = contents.y() + max(0, (contents.height() - icon_size.height()) // 2)
            icon.paint(
                painter,
                QRect(left, icon_top, icon_size.width(), icon_size.height()),
                Qt.AlignCenter,
                paint_mode,
                paint_state,
            )
            text_rect = QRect(
                left + icon_size.width() + spacing,
                contents.y(),
                max(text_width, contents.right() - (left + icon_size.width() + spacing) + 1),
                contents.height(),
            )
            painter.setPen(chrome.text)
            painter.setFont(self.font())
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft | Qt.TextShowMnemonic, text)
            return
        if has_icon:
            icon.paint(painter, contents, Qt.AlignCenter, paint_mode, paint_state)
            return
        if has_text:
            painter.setPen(chrome.text)
            painter.setFont(self.font())
            painter.drawText(contents, Qt.AlignCenter | Qt.TextShowMnemonic, text)

    def _snap_to_business_state(self) -> None:
        if (
            not self._motion_policy.interpolates()
            or not self.isEnabled()
            or not self.isVisible()
        ):
            self._clear_transients()
            return
        hover = 1.0 if self.underMouse() and not self.isDown() else 0.0
        press = 1.0 if self.isDown() else 0.0
        self._hover_driver.snap(hover)
        self._press_driver.snap(press)

    def _clear_transients(self) -> None:
        self._hover_driver.snap(0.0)
        self._press_driver.snap(0.0)

    def _bind_window_filter(self) -> None:
        window = self.window()
        previous = self._filter_window
        if previous is not None and previous is not window:
            if not sip.isdeleted(previous):
                previous.removeEventFilter(self)
        self._filter_window = window
        if window is not None and not sip.isdeleted(window):
            window.installEventFilter(self)
