"""A visible binary choice bound to a hidden, compatibility-state QComboBox."""
from __future__ import annotations

from collections.abc import Sequence

from PyQt5.QtCore import QEvent, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from ..control_style import CONTROL_COLORS
from ..motion import MotionPolicy, ValueDriver, duration_ms, resolve_policy

# Suppress the QSS checked pill while the shared moving plate owns that chrome.
# Longhand colors only: a ``border:`` shorthand here would zero radius.
_MOTION_PILL_HOST_QSS = """
QFrame#segmentedChoice QPushButton[role="choice"]:checked {
    background-color: transparent;
    border-color: transparent;
}
"""


class _SelectionPill(QFrame):
    """Input-transparent selected-segment plate. Geometry is owned by the choice."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmentedChoicePill")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(QColor(CONTROL_COLORS["CONTROL_SURFACE_TOP"]))
        painter.setPen(QPen(QColor(CONTROL_COLORS["CONTROL_SELECT_LINE"]), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 5, 5)


class SegmentedChoice(QFrame):
    """Render exactly two combo items as equal-width, mutually exclusive buttons.

    The bound combo remains the authoritative state/API surface.  It is hidden
    rather than removed so existing preset, project-state and signal consumers
    keep using ``currentData()`` and ``setCurrentIndex()`` unchanged.
    """

    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("segmentedChoice")
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo: QComboBox | None = None
        self._buttons: tuple[QPushButton, ...] = ()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonClicked.connect(self._on_button_clicked)
        self._layout = QHBoxLayout(self)
        # 32px outer track = 26px segment + 2px inner margins + 1px border.
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(0)
        self._motion_policy = resolve_policy(None)
        self._selection_pill: _SelectionPill | None = None
        self._motion_driver: ValueDriver | None = None

    def bind(
        self,
        combo: QComboBox,
        *,
        labels: Sequence[str] | None = None,
    ) -> "SegmentedChoice":
        """Hide and bind one two-item ``QComboBox`` as the state owner."""
        if self._combo is not None:
            raise RuntimeError("SegmentedChoice is already bound")
        if combo.count() != 2:
            raise ValueError("SegmentedChoice requires a combo with exactly two items")
        if labels is not None and len(labels) != combo.count():
            raise ValueError("SegmentedChoice labels must match the combo item count")

        self._combo = combo
        combo.setParent(self)
        combo.hide()
        display_labels = tuple(labels) if labels is not None else tuple(
            combo.itemText(index) for index in range(combo.count())
        )
        buttons = []
        for index, text in enumerate(display_labels):
            button = QPushButton(str(text), self)
            button.setCheckable(True)
            button.setProperty("role", "choice")
            item_tip = combo.itemData(index, Qt.ToolTipRole)
            button.setToolTip(str(item_tip or combo.toolTip() or ""))
            self._group.addButton(button, index)
            self._layout.addWidget(button, 1)
            buttons.append(button)
        self._buttons = tuple(buttons)
        combo.currentIndexChanged.connect(self._on_combo_index_changed)
        self.sync_from_bound_combo()
        return self

    def bound_combo(self) -> QComboBox:
        """Return the hidden QComboBox that retains the public state contract."""
        if self._combo is None:
            raise RuntimeError("SegmentedChoice is not bound")
        return self._combo

    def buttons(self) -> tuple[QPushButton, ...]:
        """Return the visible buttons in the same order as the combo items."""
        return self._buttons

    def currentIndex(self) -> int:
        return self.bound_combo().currentIndex()

    def setCurrentIndex(self, index: int) -> None:
        self.bound_combo().setCurrentIndex(index)

    def motion_policy(self) -> MotionPolicy:
        return self._motion_policy

    def set_motion_policy(self, policy: MotionPolicy | None) -> None:
        """Apply an explicit per-instance policy and snap chrome to business state."""
        self._motion_policy = resolve_policy(policy)
        self._apply_motion_chrome()
        if self._motion_policy.interpolates():
            self._snap_indicator()
        else:
            self._teardown_visible_indicator()

    def sync_from_bound_combo(self) -> None:
        """Refresh button state after a deliberate signal-blocked combo update."""
        if self._combo is None:
            return
        self._set_checked_index(self._combo.currentIndex())
        self._snap_indicator()

    def refresh_from_bound_combo(self) -> None:
        """Refresh two mutable combo labels and their inherited tooltips.

        Some owners switch between two fixed vocabularies (for example,
        ``Auto``/``Fixed`` and ``自动``/``手动``) while retaining one state
        combo.  The item count remains a binary contract; only its display
        labels may change.
        """
        combo = self.bound_combo()
        if combo.count() != len(self._buttons):
            raise ValueError(
                "SegmentedChoice bound combo no longer has exactly two items"
            )
        for index, button in enumerate(self._buttons):
            button.setText(combo.itemText(index))
            item_tip = combo.itemData(index, Qt.ToolTipRole)
            button.setToolTip(str(item_tip or combo.toolTip() or ""))
        self.sync_from_bound_combo()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._snap_indicator()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._snap_indicator()

    def hideEvent(self, event) -> None:
        self._snap_indicator()
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.FontChange,
            QEvent.EnabledChange,
            QEvent.WindowDeactivate,
        ):
            self._snap_indicator()

    def _set_checked_index(self, index: int) -> None:
        for button_index, button in enumerate(self._buttons):
            was_blocked = button.blockSignals(True)
            try:
                button.setChecked(button_index == index)
            finally:
                button.blockSignals(was_blocked)

    def _on_combo_index_changed(self, index: int) -> None:
        self._set_checked_index(index)
        self._follow_indicator(animate=True)
        self.currentIndexChanged.emit(index)

    def _on_button_clicked(self, button: QPushButton) -> None:
        combo = self.bound_combo()
        index = self._group.id(button)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)

    def _apply_motion_chrome(self) -> None:
        if self._motion_policy.interpolates():
            self.setStyleSheet(_MOTION_PILL_HOST_QSS)
            self._ensure_indicator()
            return
        self.setStyleSheet("")

    def _ensure_driver(self) -> ValueDriver:
        if self._motion_driver is None:
            self._motion_driver = ValueDriver(self, on_value=self._on_indicator_rect)
        return self._motion_driver

    def _ensure_indicator(self) -> _SelectionPill:
        if self._selection_pill is None:
            self._selection_pill = _SelectionPill(self)
        self._stack_indicator()
        return self._selection_pill

    def _stack_indicator(self) -> None:
        pill = self._selection_pill
        if pill is None:
            return
        pill.lower()
        for button in self._buttons:
            button.raise_()

    def _measured_target_rect(self) -> QRect | None:
        if self._combo is None or not self._buttons:
            return None
        index = self._combo.currentIndex()
        if not 0 <= index < len(self._buttons):
            return None
        rect = QRect(self._buttons[index].geometry())
        if not rect.isValid() or rect.isEmpty():
            return None
        return rect

    def _snap_indicator(self) -> None:
        if not self._motion_policy.interpolates():
            self._teardown_visible_indicator()
            return
        target = self._measured_target_rect()
        if target is None:
            return
        self._ensure_indicator()
        self._ensure_driver().snap(target)

    def _follow_indicator(self, *, animate: bool) -> None:
        if not self._motion_policy.interpolates():
            self._teardown_visible_indicator()
            return
        target = self._measured_target_rect()
        if target is None:
            return
        self._ensure_indicator()
        driver = self._ensure_driver()
        if not animate or not self.isVisible() or driver.current() is None:
            driver.snap(target)
            return
        driver.go(target, duration_ms=duration_ms("segment", self._motion_policy))

    def _teardown_visible_indicator(self) -> None:
        driver = self._motion_driver
        if driver is not None:
            target = self._measured_target_rect()
            if target is not None:
                driver.snap(target)
            elif driver.is_active():
                driver.stop_and_keep()
        pill = self._selection_pill
        if pill is not None:
            pill.hide()

    def _on_indicator_rect(self, value) -> None:
        pill = self._selection_pill
        if pill is None or value is None:
            return
        rect = QRect(value)
        if not rect.isValid():
            return
        pill.setGeometry(rect)
        if self._motion_policy.interpolates() and pill.isHidden():
            pill.show()
            self._stack_indicator()
