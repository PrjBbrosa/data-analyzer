"""Shared selected-background plate. Geometry and interpolation only."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from weakref import ref

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import QFrame, QPushButton, QWidget

from ..motion import (
    DURATION_MS,
    MotionPolicy,
    ValueDriver,
    duration_ms,
    resolve_policy,
    selection_easing,
)

# Scoped to this objectName. Longhands only: a ``border:`` shorthand would
# zero radius if a later state rule omitted it.
_PLATE_TRANSPARENT_QSS = """
QFrame#selectionIndicatorPlate {
    background-color: transparent;
    border-width: 0px;
    border-style: none;
}
"""

_POINTER_EVENTS = (
    QEvent.MouseButtonPress,
    QEvent.MouseButtonRelease,
    QEvent.MouseButtonDblClick,
    QEvent.KeyPress,
    QEvent.KeyRelease,
    QEvent.Wheel,
    QEvent.HoverEnter,
    QEvent.HoverMove,
    QEvent.HoverLeave,
    QEvent.Enter,
    QEvent.Leave,
)
_CHROME_EVENTS = (
    QEvent.MouseButtonPress,
    QEvent.MouseButtonRelease,
    QEvent.HoverEnter,
    QEvent.HoverLeave,
    QEvent.Enter,
    QEvent.Leave,
    QEvent.FocusIn,
    QEvent.FocusOut,
)


@dataclass(frozen=True)
class SelectionIndicatorStyle:
    fill: str
    border: str
    disabled_fill: str
    disabled_border: str
    radius: int
    fill_bottom: str | None = None
    hover_fill: str | None = None
    hover_fill_bottom: str | None = None
    focus_border: str | None = None
    inset: tuple[int, int, int, int] = (0, 0, 0, 0)
    compact_inset: tuple[int, int, int, int] | None = None


def _belongs_to_host(widget: QWidget, host: QWidget) -> bool:
    current: QWidget | None = widget
    while current is not None:
        if current is host:
            return True
        current = current.parentWidget()
    return False


def _is_living(obj) -> bool:
    try:
        return obj is not None and not sip.isdeleted(obj)
    except RuntimeError:
        return False


class _SelectionPlate(QFrame):
    """Input-transparent selected-item plate painted from owner style."""

    def __init__(self, host: QWidget, indicator: "SelectionIndicator") -> None:
        super().__init__(host)
        self.setObjectName("selectionIndicatorPlate")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(_PLATE_TRANSPARENT_QSS)
        self._indicator_ref = ref(indicator)
        self.hide()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange:
            self.update()

    def paintEvent(self, event) -> None:
        del event
        indicator = self._indicator_ref()
        if indicator is None or sip.isdeleted(indicator):
            return
        fill, line = indicator._effective_chrome()
        fill_bottom = indicator._effective_fill_bottom()
        box = indicator._paint_rect(self.rect())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if fill_bottom is not None:
            gradient = QLinearGradient(box.left(), box.top(), box.left(), box.bottom())
            gradient.setColorAt(0.0, QColor(fill))
            gradient.setColorAt(1.0, QColor(fill_bottom))
            painter.setBrush(gradient)
        else:
            painter.setBrush(QColor(fill))
        painter.setPen(QPen(QColor(line), 1.0))
        radius = float(indicator._style.radius)
        painter.drawRoundedRect(box, radius, radius)


class SelectionIndicator(QObject):
    """Move one selected-background plate among a fixed button sequence."""

    def __init__(
        self,
        host: QWidget,
        *,
        buttons: Sequence[QPushButton],
        duration_name: str,
        style: SelectionIndicatorStyle,
    ) -> None:
        if not isinstance(host, QWidget):
            raise TypeError("SelectionIndicator host must be a QWidget")
        if not isinstance(style, SelectionIndicatorStyle):
            raise TypeError("style must be SelectionIndicatorStyle")
        if duration_name not in DURATION_MS:
            known = ", ".join(sorted(DURATION_MS))
            raise ValueError(
                f"unknown motion duration {duration_name!r}; expected one of: {known}"
            )
        super().__init__(host)
        self._host = host
        self._duration_name = duration_name
        self._style = style
        self._policy = resolve_policy(None)
        self._buttons = tuple(buttons)
        for button in self._buttons:
            if not isinstance(button, QPushButton):
                raise TypeError("buttons must be QPushButton instances")
            if not _belongs_to_host(button, host):
                raise ValueError("buttons must share the host widget")
        self._target: QPushButton | None = None
        self._confirmed_rect: QRect | None = None
        self._plate: _SelectionPlate | None = None
        self._driver: ValueDriver | None = None
        self._pointer_over_target = False
        host.installEventFilter(self)
        window = host.window()
        if window is not None and window is not host:
            window.installEventFilter(self)
        for button in self._buttons:
            button.installEventFilter(self)
            button.destroyed.connect(self._on_button_destroyed)

    def set_motion_policy(self, policy: MotionPolicy | None) -> None:
        self._policy = resolve_policy(policy)
        if not self._policy.interpolates():
            self._hide_and_stop()
            return
        self.snap_to_selection()

    def follow(self, button: QPushButton | None, *, animate: bool = False) -> None:
        if sip.isdeleted(self):
            return
        if button is None:
            self._target = None
            self._confirmed_rect = None
            self._pointer_over_target = False
            self._hide_and_stop()
            return
        if not _is_living(button):
            if self._target is not None and not _is_living(self._target):
                self._target = None
                self._confirmed_rect = None
            self._hide_and_stop()
            return
        if button not in self._buttons or not _belongs_to_host(button, self._host):
            self._hide_and_stop()
            return
        rect = self._mapped_rect(button)
        if rect is None or not rect.isValid() or rect.isEmpty():
            self._hide_and_stop()
            return
        if not self._is_visible(button):
            self._target = button
            self._confirmed_rect = QRect(rect)
            self._hide_and_stop()
            return
        if self._is_same_confirmed(button, rect):
            return
        self._target = button
        self._confirmed_rect = QRect(rect)
        self._pointer_over_target = bool(button.underMouse())
        if not self._policy.interpolates():
            self._hide_and_stop()
            return
        driver = self._ensure_driver()
        self._ensure_plate()
        can_animate = (
            animate
            and driver.current() is not None
            and self._is_visible(button)
            and button.isEnabled()
        )
        if can_animate:
            driver.go(rect, duration_ms=duration_ms(self._duration_name, self._policy))
            return
        driver.snap(rect)

    def snap_to_selection(self) -> None:
        if sip.isdeleted(self):
            return
        target = self._target
        if target is None or not _is_living(target):
            self._target = None
            self._confirmed_rect = None
            self._hide_and_stop()
            return
        rect = self._mapped_rect(target)
        if rect is None or not rect.isValid() or rect.isEmpty() or not self._is_visible(target):
            self._hide_and_stop()
            return
        self._confirmed_rect = QRect(rect)
        if not self._policy.interpolates():
            self._hide_and_stop()
            return
        self._ensure_plate()
        self._ensure_driver().snap(rect)

    def driver(self) -> ValueDriver | None:
        if self._driver is not None and sip.isdeleted(self._driver):
            return None
        return self._driver

    def eventFilter(self, watched, event) -> bool:
        if sip.isdeleted(self):
            return False
        kind = event.type()
        if kind in _POINTER_EVENTS or kind in (QEvent.FocusIn, QEvent.FocusOut):
            if kind in _CHROME_EVENTS:
                if watched is self._target:
                    if kind in (QEvent.Enter, QEvent.HoverEnter):
                        self._pointer_over_target = True
                    elif kind in (QEvent.Leave, QEvent.HoverLeave):
                        self._pointer_over_target = False
                self._refresh_plate_chrome()
            return False
        if kind == QEvent.Hide:
            target = self._target
            if watched is self._host:
                self._hide_and_stop()
            elif target is not None and _is_living(target) and not self._is_visible(target):
                self._hide_and_stop()
            return False
        if kind == QEvent.Show:
            if watched is self._host or watched is self._target:
                self.snap_to_selection()
            return False
        if kind == QEvent.Move:
            if watched is self._target or watched in self._buttons:
                self.snap_to_selection()
            return False
        if kind in (QEvent.Resize, QEvent.FontChange, QEvent.WindowDeactivate):
            self.snap_to_selection()
            return False
        if kind == QEvent.EnabledChange:
            self.snap_to_selection()
            plate = self._plate
            if plate is not None and _is_living(plate):
                plate.update()
            return False
        return False

    def _effective_chrome(self) -> tuple[str, str]:
        if not self._target_is_enabled():
            return (self._style.disabled_fill, self._style.disabled_border)
        fill, _bottom = self._enabled_fill_stops()
        return (fill, self._effective_border())

    def _effective_fill_bottom(self) -> str | None:
        if not self._target_is_enabled():
            return None
        _fill, bottom = self._enabled_fill_stops()
        return bottom

    def _enabled_fill_stops(self) -> tuple[str, str | None]:
        if self._target_is_hovered() and self._style.hover_fill:
            return (self._style.hover_fill, self._style.hover_fill_bottom)
        return (self._style.fill, self._style.fill_bottom)

    def _effective_border(self) -> str:
        target = self._target
        if (
            self._style.focus_border
            and target is not None
            and _is_living(target)
            and target.hasFocus()
        ):
            return self._style.focus_border
        return self._style.border

    def _target_is_enabled(self) -> bool:
        target = self._target
        if target is None or not _is_living(target):
            return True
        return bool(target.isEnabled())

    def _target_is_hovered(self) -> bool:
        target = self._target
        if target is None or not _is_living(target) or not target.isEnabled():
            return False
        return bool(self._pointer_over_target or target.underMouse())

    def _effective_inset(self) -> tuple[int, int, int, int]:
        target = self._target
        if (
            target is not None
            and _is_living(target)
            and str(target.property("timeControlDensity") or "") == "compact"
            and self._style.compact_inset is not None
        ):
            return self._style.compact_inset
        return self._style.inset

    def _paint_rect(self, plate_rect: QRect) -> QRectF:
        left, top, right, bottom = self._effective_inset()
        box = QRectF(plate_rect).adjusted(left, top, -right, -bottom)
        if box.width() < 2.0 or box.height() < 2.0:
            box = QRectF(plate_rect)
        return box.adjusted(0.5, 0.5, -0.5, -0.5)

    def _refresh_plate_chrome(self) -> None:
        plate = self._plate
        if plate is not None and _is_living(plate):
            plate.update()

    def _is_same_confirmed(self, button: QPushButton, rect: QRect) -> bool:
        if self._target is not button:
            return False
        if self._confirmed_rect is None or self._confirmed_rect != rect:
            return False
        if not self._policy.interpolates():
            return True
        driver = self._driver
        if (
            driver is not None
            and _is_living(driver)
            and driver.is_active()
            and driver.target() == rect
        ):
            return True
        return self._plate_shows(rect)

    def _plate_shows(self, rect: QRect) -> bool:
        plate = self._plate
        if plate is None or not _is_living(plate) or plate.isHidden():
            return False
        return plate.geometry() == rect

    def _is_visible(self, button: QPushButton) -> bool:
        if not _is_living(button) or not _is_living(self._host):
            return False
        return bool(button.isVisible())

    def _mapped_rect(self, button: QPushButton) -> QRect | None:
        host = self._host
        if not _is_living(button) or not _is_living(host):
            return None
        return QRect(button.mapTo(host, QPoint(0, 0)), button.size())

    def _ensure_plate(self) -> _SelectionPlate:
        if self._plate is None or sip.isdeleted(self._plate):
            self._plate = _SelectionPlate(self._host, self)
        self._stack()
        return self._plate

    def _ensure_driver(self) -> ValueDriver:
        if self._driver is None or sip.isdeleted(self._driver):
            self._driver = ValueDriver(
                self,
                on_value=self._on_rect,
                easing=selection_easing(),
            )
        return self._driver

    def _stack(self) -> None:
        plate = self._plate
        if plate is None or not _is_living(plate):
            return
        plate.lower()
        for button in self._buttons:
            if _is_living(button):
                button.raise_()

    def _hide_and_stop(self) -> None:
        driver = self._driver
        if driver is not None and _is_living(driver) and driver.is_active():
            driver.stop_and_keep()
        plate = self._plate
        if plate is not None and _is_living(plate):
            plate.hide()

    def _on_rect(self, value) -> None:
        if sip.isdeleted(self):
            return
        if not _is_living(self._host):
            return
        plate = self._plate
        if plate is None or not _is_living(plate) or value is None:
            return
        rect = QRect(value)
        if not rect.isValid() or rect.isEmpty():
            return
        plate.setGeometry(rect)
        if not self._policy.interpolates():
            return
        target = self._target
        if target is None or not _is_living(target) or not self._is_visible(target):
            return
        if plate.isHidden():
            plate.show()
        self._stack()

    def _on_button_destroyed(self, *_args) -> None:
        if sip.isdeleted(self):
            return
        target = self._target
        if target is not None and not _is_living(target):
            self._target = None
            self._confirmed_rect = None
            self._hide_and_stop()
