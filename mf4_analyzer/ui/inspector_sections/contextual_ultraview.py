"""UltraView Inspector context: BoardState intents only, no MainWindow."""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..ultraview_state import (
    COMPARE_FILTER_ALL,
    COMPARE_FILTERS,
    LAYOUT_SLOTS,
    UltraViewBoardState,
    UltraViewRef,
    default_board,
    layout_slots,
    parse_ref_payload,
    placement_for,
)
from ._helpers import _make_group_header, _make_params_card

_LAYOUT_LABELS = {
    "split_horizontal": "左右双图",
    "split_vertical": "上下双图",
    "grid_2x2": "2 × 2",
    "hero_left_4": "左主图 + 3 辅图",
    "hero_top_4": "上主图 + 3 辅图",
    "grid_3x2": "3 × 2",
}
_FILTER_LABELS = {
    COMPARE_FILTER_ALL: "全部",
    "time": "时间轴",
    "frequency": "频率轴",
    "time_freq": "时频轴",
    "order": "阶次轴",
}


class UltraViewContextual(QWidget):
    """Fifth Inspector context. Emits Board intents; never imports MainWindow."""

    layout_changed = pyqtSignal(str)
    ratio_nudge_requested = pyqtSignal(int)
    open_source_requested = pyqtSignal(str, str)
    focus_requested = pyqtSignal(str, str)
    shift_slot_requested = pyqtSignal(str, str, int)
    set_primary_requested = pyqtSignal(str, str)
    replace_arm_requested = pyqtSignal(str, str)
    move_to_unplaced_requested = pyqtSignal(str, str)
    remove_ref_requested = pyqtSignal(str, str)
    compare_filter_changed = pyqtSignal(str)
    show_titles_toggled = pyqtSignal(bool)
    show_sources_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ultraViewContextual")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._board = default_board()
        self._selected: UltraViewRef | None = None
        self._filter = COMPARE_FILTER_ALL
        self._applying = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        card, lay = _make_params_card(self, "ultraViewInspectorCard")
        lay.addWidget(_make_group_header("总览", parent=card))
        self._name = QLabel(self._board.name, card)
        self._name.setObjectName("ultraViewInspectorName")
        self._name.setWordWrap(True)
        lay.addWidget(self._name)

        self._layout_combo = QComboBox(card)
        self._layout_combo.setObjectName("ultraViewInspectorLayout")
        for layout_id in LAYOUT_SLOTS:
            self._layout_combo.addItem(_LAYOUT_LABELS[layout_id], layout_id)
        self._layout_combo.currentIndexChanged.connect(self._on_layout)
        lay.addWidget(self._layout_combo)

        ratio_row = QHBoxLayout()
        self._ratio_label = QLabel("主图比例", card)
        self._btn_ratio_down = QPushButton("−5%", card)
        self._btn_ratio_up = QPushButton("+5%", card)
        self._btn_ratio_down.clicked.connect(lambda: self.ratio_nudge_requested.emit(-1))
        self._btn_ratio_up.clicked.connect(lambda: self.ratio_nudge_requested.emit(1))
        ratio_row.addWidget(self._ratio_label, 1)
        ratio_row.addWidget(self._btn_ratio_down, 0)
        ratio_row.addWidget(self._btn_ratio_up, 0)
        lay.addLayout(ratio_row)

        self._chk_titles = QCheckBox("显示标题", card)
        self._chk_sources = QCheckBox("显示来源", card)
        self._chk_titles.setChecked(True)
        self._chk_sources.setChecked(True)
        self._chk_titles.toggled.connect(self._on_titles)
        self._chk_sources.toggled.connect(self._on_sources)
        lay.addWidget(self._chk_titles)
        lay.addWidget(self._chk_sources)

        self._filter_combo = QComboBox(card)
        self._filter_combo.setObjectName("ultraViewInspectorFilter")
        for key in COMPARE_FILTERS:
            self._filter_combo.addItem(_FILTER_LABELS[key], key)
        self._filter_combo.currentIndexChanged.connect(self._on_filter)
        lay.addWidget(self._filter_combo)

        lay.addWidget(_make_group_header("选中卡片", parent=card))
        self._selected_label = QLabel("未选择", card)
        self._selected_label.setObjectName("ultraViewInspectorSelected")
        self._selected_label.setWordWrap(True)
        lay.addWidget(self._selected_label)

        self._btn_open = QPushButton("打开原 View", card)
        self._btn_focus = QPushButton("临时放大", card)
        self._btn_prev = QPushButton("前移", card)
        self._btn_next = QPushButton("后移", card)
        self._btn_primary = QPushButton("设为主图", card)
        self._btn_replace = QPushButton("替换", card)
        self._btn_unplaced = QPushButton("移到未放置", card)
        self._btn_remove = QPushButton("从总览移除", card)
        for button, slot in (
            (self._btn_open, self._emit_open),
            (self._btn_focus, self._emit_focus),
            (self._btn_prev, lambda: self._emit_shift(-1)),
            (self._btn_next, lambda: self._emit_shift(1)),
            (self._btn_primary, self._emit_primary),
            (self._btn_replace, self._emit_replace),
            (self._btn_unplaced, self._emit_unplaced),
            (self._btn_remove, self._emit_remove),
        ):
            button.clicked.connect(slot)
            lay.addWidget(button)

        root.addWidget(card)
        self._sync_enabled()

    def set_board(self, board: UltraViewBoardState, selected=None, compare_filter=COMPARE_FILTER_ALL) -> None:
        self._applying = True
        try:
            self._board = board
            parsed = selected
            if not isinstance(parsed, UltraViewRef):
                parsed = parse_ref_payload(selected) if selected is not None else None
            self._selected = parsed
            self._filter = str(compare_filter or COMPARE_FILTER_ALL)
            self._name.setText(board.name)
            idx = self._layout_combo.findData(board.layout_id)
            if idx >= 0:
                self._layout_combo.setCurrentIndex(idx)
            self._ratio_label.setText(f"主图比例 {board.primary_ratio:.2f}")
            self._chk_titles.setChecked(bool(board.show_titles))
            self._chk_sources.setChecked(bool(board.show_sources))
            fidx = self._filter_combo.findData(self._filter)
            if fidx >= 0:
                self._filter_combo.setCurrentIndex(fidx)
            if self._selected is None:
                self._selected_label.setText("未选择")
            else:
                self._selected_label.setText(
                    f"{self._selected.section} / {self._selected.view_id}"
                )
            self._sync_enabled()
        finally:
            self._applying = False

    def _sync_enabled(self) -> None:
        has = self._selected is not None
        placed = (
            has
            and placement_for(self._board, self._selected) is not None
        )
        for button in (
            self._btn_open, self._btn_focus, self._btn_replace,
            self._btn_unplaced, self._btn_remove, self._btn_prev,
            self._btn_next, self._btn_primary,
        ):
            button.setEnabled(has)
        self._btn_prev.setEnabled(placed)
        self._btn_next.setEnabled(placed)
        self._btn_primary.setEnabled(placed)
        slots = layout_slots(self._board.layout_id)
        self._btn_ratio_down.setEnabled("primary" in slots)
        self._btn_ratio_up.setEnabled("primary" in slots)

    def _on_layout(self, _index: int) -> None:
        if self._applying:
            return
        layout_id = self._layout_combo.currentData()
        if layout_id:
            self.layout_changed.emit(str(layout_id))

    def _on_filter(self, _index: int) -> None:
        if self._applying:
            return
        key = self._filter_combo.currentData()
        if key:
            self.compare_filter_changed.emit(str(key))

    def _on_titles(self, checked: bool) -> None:
        if not self._applying:
            self.show_titles_toggled.emit(bool(checked))

    def _on_sources(self, checked: bool) -> None:
        if not self._applying:
            self.show_sources_toggled.emit(bool(checked))

    def _emit_open(self) -> None:
        if self._selected is not None:
            self.open_source_requested.emit(self._selected.section, self._selected.view_id)

    def _emit_focus(self) -> None:
        if self._selected is not None:
            self.focus_requested.emit(self._selected.section, self._selected.view_id)

    def _emit_shift(self, delta: int) -> None:
        if self._selected is not None:
            self.shift_slot_requested.emit(
                self._selected.section, self._selected.view_id, int(delta)
            )

    def _emit_primary(self) -> None:
        if self._selected is not None:
            self.set_primary_requested.emit(
                self._selected.section, self._selected.view_id
            )

    def _emit_replace(self) -> None:
        if self._selected is not None:
            self.replace_arm_requested.emit(
                self._selected.section, self._selected.view_id
            )

    def _emit_unplaced(self) -> None:
        if self._selected is not None:
            self.move_to_unplaced_requested.emit(
                self._selected.section, self._selected.view_id
            )

    def _emit_remove(self) -> None:
        if self._selected is not None:
            self.remove_ref_requested.emit(
                self._selected.section, self._selected.view_id
            )
