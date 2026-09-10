"""A visible binary choice bound to a hidden, compatibility-state QComboBox."""
from __future__ import annotations

from collections.abc import Sequence

from PyQt5 import sip
from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
)

from ..control_style import CONTROL_COLORS
from ..motion import MotionPolicy, resolve_policy
from .selection_indicator import SelectionIndicator, SelectionIndicatorStyle

# Suppress the QSS checked pill while the shared moving plate owns that chrome.
# Longhand colors only: a ``border:`` shorthand here would zero radius.
# Disabled checked text is muted here; the plate owns the disabled fill.
_MOTION_PILL_HOST_QSS = f"""
QFrame#segmentedChoice QPushButton[role="choice"]:checked {{
    background-color: transparent;
    border-color: transparent;
}}
QFrame#segmentedChoice QPushButton[role="choice"]:checked:disabled,
QFrame#segmentedChoice QPushButton[role="choice"]:checked:disabled:hover,
QFrame#segmentedChoice QPushButton[role="choice"]:checked:disabled:pressed,
QFrame#segmentedChoice QPushButton[role="choice"]:checked:disabled:focus {{
    background-color: transparent;
    border-color: transparent;
    color: {CONTROL_COLORS["CONTROL_TEXT_MUTED"]};
}}
"""


def _is_living(obj) -> bool:
    try:
        return obj is not None and not sip.isdeleted(obj)
    except RuntimeError:
        return False


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
        self._indicator: SelectionIndicator | None = None
        self._direct_activation_index: int | None = None

    @property
    def _motion_driver(self):
        helper = self._indicator
        if not _is_living(helper):
            return None
        return helper.driver()

    @property
    def _selection_pill(self):
        helper = self._indicator
        if not _is_living(helper):
            return None
        plate = helper._plate
        if not _is_living(plate):
            return None
        return plate

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
        helper = self._indicator
        if _is_living(helper):
            helper.set_motion_policy(self._motion_policy)
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
        kind = event.type()
        if kind in (
            QEvent.FontChange,
            QEvent.EnabledChange,
            QEvent.WindowDeactivate,
        ):
            self._snap_indicator()
        if kind == QEvent.EnabledChange:
            self._refresh_enabled_chrome()

    def wheelEvent(self, event) -> None:
        if not self.isEnabled():
            event.accept()
            return
        super().wheelEvent(event)

    def _set_checked_index(self, index: int) -> None:
        for button_index, button in enumerate(self._buttons):
            was_blocked = button.blockSignals(True)
            try:
                button.setChecked(button_index == index)
            finally:
                button.blockSignals(was_blocked)

    def _on_combo_index_changed(self, index: int) -> None:
        requested = self._direct_activation_index
        self._direct_activation_index = None
        self._set_checked_index(index)
        self._follow_indicator(animate=requested is not None and requested == index)
        self.currentIndexChanged.emit(index)

    def _on_button_clicked(self, button: QPushButton) -> None:
        if not self.isEnabled():
            if self._combo is not None:
                self._set_checked_index(self._combo.currentIndex())
            return
        combo = self.bound_combo()
        index = self._group.id(button)
        if index < 0 or combo.currentIndex() == index:
            return
        self._direct_activation_index = index
        try:
            combo.setCurrentIndex(index)
        finally:
            self._direct_activation_index = None

    def _refresh_enabled_chrome(self) -> None:
        pill = self._selection_pill
        if pill is not None:
            pill.update()
        for button in self._buttons:
            button.update()
        self.update()

    def _apply_motion_chrome(self) -> None:
        if self._motion_policy.interpolates():
            self.setStyleSheet(_MOTION_PILL_HOST_QSS)
            return
        self.setStyleSheet("")

    def _current_button(self) -> QPushButton | None:
        combo = self._combo
        if combo is None or not self._buttons:
            return None
        index = combo.currentIndex()
        if not 0 <= index < len(self._buttons):
            return None
        return self._buttons[index]

    def _ensure_indicator(self) -> SelectionIndicator | None:
        if not self._buttons:
            return None
        helper = self._indicator
        if _is_living(helper):
            return helper
        helper = SelectionIndicator(
            self,
            buttons=self._buttons,
            duration_name="selection_control",
            style=SelectionIndicatorStyle(
                fill=CONTROL_COLORS["CONTROL_SURFACE_TOP"],
                border=CONTROL_COLORS["CONTROL_SELECT_LINE"],
                disabled_fill=CONTROL_COLORS["CONTROL_DISABLED_BG"],
                disabled_border=CONTROL_COLORS["CONTROL_DISABLED_LINE"],
                radius=5,
            ),
        )
        self._indicator = helper
        helper.set_motion_policy(self._motion_policy)
        return helper

    def _snap_indicator(self) -> None:
        if not self._motion_policy.interpolates():
            self._teardown_visible_indicator()
            return
        helper = self._ensure_indicator()
        if helper is None:
            return
        helper.follow(self._current_button(), animate=False)
        helper.snap_to_selection()

    def _follow_indicator(self, *, animate: bool) -> None:
        if not self._motion_policy.interpolates():
            self._teardown_visible_indicator()
            return
        helper = self._ensure_indicator()
        if helper is None:
            return
        helper.follow(self._current_button(), animate=animate)

    def _teardown_visible_indicator(self) -> None:
        helper = self._indicator
        if not _is_living(helper):
            return
        helper.set_motion_policy(self._motion_policy)
