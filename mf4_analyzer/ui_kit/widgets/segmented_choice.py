"""A visible binary choice bound to a hidden, compatibility-state QComboBox."""
from __future__ import annotations

from collections.abc import Sequence

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QButtonGroup, QComboBox, QFrame, QHBoxLayout, QPushButton, QSizePolicy


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

    def sync_from_bound_combo(self) -> None:
        """Refresh button state after a deliberate signal-blocked combo update."""
        if self._combo is None:
            return
        self._set_checked_index(self._combo.currentIndex())

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

    def _set_checked_index(self, index: int) -> None:
        for button_index, button in enumerate(self._buttons):
            was_blocked = button.blockSignals(True)
            try:
                button.setChecked(button_index == index)
            finally:
                button.blockSignals(was_blocked)

    def _on_combo_index_changed(self, index: int) -> None:
        self._set_checked_index(index)
        self.currentIndexChanged.emit(index)

    def _on_button_clicked(self, button: QPushButton) -> None:
        combo = self.bound_combo()
        index = self._group.id(button)
        if index >= 0 and combo.currentIndex() != index:
            combo.setCurrentIndex(index)
