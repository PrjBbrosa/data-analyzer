"""UltraView compare-filter rail.

Presentation-only filter chrome. Page keeps the live overlay identity through
the widgets façade.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFrame,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.ultraview_state import COMPARE_FILTER_ALL, COMPARE_FILTERS

COMPARE_FILTER_LABELS_ZH = {
    COMPARE_FILTER_ALL: "全部",
    "time": "时间轴",
    "frequency": "频率轴",
    "time_freq": "时频轴",
    "order": "阶次轴",
}


class CompareRail(QFrame):
    compare_filter_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ultraViewCompareRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for filter_id in COMPARE_FILTERS:
            button = QPushButton(COMPARE_FILTER_LABELS_ZH[filter_id], self)
            button.setObjectName("ultraViewCompareButton")
            button.setCheckable(True)
            button.setProperty("filterId", filter_id)
            button.setFocusPolicy(Qt.TabFocus)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._group.addButton(button)
            self._buttons[filter_id] = button
            root.addWidget(button, 0)
        self._buttons[COMPARE_FILTER_ALL].setChecked(True)
        self._group.buttonClicked.connect(self._on_button)
        self._warning = QLabel("", self)
        self._warning.setObjectName("ultraViewAxisWarning")
        self._warning.setWordWrap(True)
        self._warning.hide()
        root.addWidget(self._warning, 0)
        self._filter_id = COMPARE_FILTER_ALL

    def filter_id(self) -> str:
        return self._filter_id

    def set_filter_id(self, filter_id: str) -> None:
        if filter_id not in self._buttons:
            filter_id = COMPARE_FILTER_ALL
        self._filter_id = filter_id
        button = self._buttons[filter_id]
        blocked = button.blockSignals(True)
        button.setChecked(True)
        button.blockSignals(blocked)

    def set_axis_warning(self, text: str) -> None:
        self._warning.setText(text)
        self._warning.setVisible(bool(text))

    def _on_button(self, button: QPushButton) -> None:
        filter_id = str(button.property("filterId") or COMPARE_FILTER_ALL)
        if filter_id == self._filter_id:
            return
        self._filter_id = filter_id
        self.compare_filter_changed.emit(filter_id)
