"""Inline-search multi-select picker for the batch dialog.

``SignalPickerPopup`` keeps search in the original channel field.  The popup
contains only the checkbox list, so opening it never introduces a second
search box.  Selected signals use a single responsive row: one or two elided
chips are shown and the remainder is summarized as ``+N``.  This keeps narrow
BatchSheet columns bounded regardless of selection count.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from PyQt5.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QFontMetrics
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QLayout, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui_kit.popup_shell import apply_popup_shell


class SignalChip(QWidget):
    """One bounded signal chip with a removable, pixel-elided label."""

    removeRequested = pyqtSignal(str)

    def __init__(
        self,
        name: str,
        max_label_chars: int = 48,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = str(name)
        self._max_label_chars = max(1, int(max_label_chars))
        self.setObjectName("SignalChip")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedHeight(28)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(7, 2, 3, 2)
        lay.setSpacing(3)

        self._label = QLabel(self)
        self._label.setToolTip(self._name)
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        lay.addWidget(self._label, 1)

        self._remove_btn = QPushButton("×", self)
        self._remove_btn.setObjectName("SignalChipRemove")
        self._remove_btn.setFixedSize(18, 18)
        self._remove_btn.setFlat(True)
        self._remove_btn.clicked.connect(
            lambda: self.removeRequested.emit(self._name)
        )
        lay.addWidget(self._remove_btn)
        self.set_display_width(self.sizeHint().width())

    def name(self) -> str:
        return self._name

    def set_display_width(self, width: int) -> None:
        """Fit the chip to *width* and elide by rendered pixels."""

        bounded = max(68, int(width))
        self.setFixedWidth(bounded)
        text_budget = max(18, bounded - 38)
        source = (
            self._name
            if len(self._name) <= self._max_label_chars
            else self._name[: self._max_label_chars] + "…"
        )
        self._label.setText(
            QFontMetrics(self._label.font()).elidedText(
                source, Qt.ElideRight, text_budget,
            )
        )


class _ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):  # noqa: N802 (Qt API)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class SignalPickerPopup(QWidget):
    """Single-line inline search plus popup multi-select checkbox list."""

    selectionChanged = pyqtSignal(tuple)

    _DISPLAY_HEIGHT = 38
    _MAX_VISIBLE_CHIPS = 2
    _NARROW_TWO_CHIP_THRESHOLD = 390
    _MIN_SEARCH_WIDTH = 42

    def __init__(
        self,
        available_signals: Iterable[str] = (),
        partially_available: Mapping[str, str] | None = None,
        initial_selection: tuple[str, ...] = (),
        parent: QWidget | None = None,
        *,
        single_select: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(self._DISPLAY_HEIGHT)
        self._single_select = bool(single_select)
        self._available: list[str] = list(available_signals)
        self._partial: dict[str, str] = dict(partially_available or {})
        self._partial_selectable = False
        selection = tuple(initial_selection)
        if self._single_select and len(selection) > 1:
            selection = selection[:1]
        self._selected: tuple[str, ...] = selection
        self._suppress_signal = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSizeConstraint(QLayout.SetNoConstraint)

        self._display_frame = _ClickableFrame(self)
        self._display_frame.setObjectName("SignalPickerDisplay")
        self._display_frame.setFrameShape(QFrame.NoFrame)
        self._display_frame.setAttribute(Qt.WA_StyledBackground, True)
        self._display_frame.setStyleSheet(
            "#SignalPickerDisplay {border:1px solid #cbd5e1;"
            " border-radius:7px; background:#fff;}"
            "#SignalPickerDisplay:focus {border-color:#1769e0;}"
        )
        self._display_frame.setFixedHeight(self._DISPLAY_HEIGHT)
        self._display_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._display_frame.clicked.connect(self._open_from_display)

        self._display_layout = QHBoxLayout(self._display_frame)
        self._display_layout.setContentsMargins(5, 4, 4, 4)
        self._display_layout.setSpacing(4)

        self._chip_host = QWidget(self._display_frame)
        self._chip_host.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._chip_host.setFixedHeight(28)
        self._chip_layout = QHBoxLayout(self._chip_host)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(4)
        self._display_layout.addWidget(self._chip_host)

        self._overflow_label = QLabel(self._display_frame)
        self._overflow_label.setObjectName("SignalPickerOverflow")
        self._overflow_label.setAlignment(Qt.AlignCenter)
        self._overflow_label.setStyleSheet(
            "#SignalPickerOverflow {color:#234d78; background:#eef4ff;"
            " border:1px solid #d4e3f8; border-radius:6px; padding:0 6px;}"
        )
        self._overflow_label.setFixedHeight(28)
        self._overflow_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._overflow_label.hide()
        self._display_layout.addWidget(self._overflow_label)

        self._search = QLineEdit(self._display_frame)
        self._search.setObjectName("SignalPickerInlineSearch")
        self._search.setPlaceholderText("搜索信号…")
        self._search.setFrame(False)
        self._search.setMinimumWidth(self._MIN_SEARCH_WIDTH)
        self._search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._search.setStyleSheet(
            "#SignalPickerInlineSearch {border:none; background:transparent;"
            " padding:0 2px; color:#172033;}"
        )
        self._search.textChanged.connect(self._on_search_text_changed)
        self._search.installEventFilter(self)
        self._display_layout.addWidget(self._search, 1)

        self._arrow_button = QPushButton("⌄", self._display_frame)
        self._arrow_button.setObjectName("SignalPickerArrow")
        self._arrow_button.setFixedSize(26, 28)
        self._arrow_button.setFlat(True)
        self._arrow_button.setToolTip("展开信号列表")
        self._arrow_button.setStyleSheet(
            "#SignalPickerArrow {border:none; border-radius:5px; color:#1769e0;"
            " background:#eef4ff; padding:0;}"
            "#SignalPickerArrow:hover {background:#e2edff;}"
        )
        self._arrow_button.clicked.connect(self._toggle_popup)
        self._display_layout.addWidget(self._arrow_button)
        outer.addWidget(self._display_frame, 1)

        self._popup = QFrame(self, Qt.Popup)
        self._popup.setObjectName("SignalPickerPopup")
        apply_popup_shell(self._popup)
        self._popup.setFrameShape(QFrame.NoFrame)
        self._popup.setAttribute(Qt.WA_StyledBackground, True)
        self._popup.setStyleSheet(
            "#SignalPickerPopup {background:#fff; border:1px solid #cbd5e1;"
            " border-radius:8px;}"
        )
        self._popup.setMinimumWidth(280)
        self._popup.setFocusPolicy(Qt.StrongFocus)
        pop_lay = QVBoxLayout(self._popup)
        pop_lay.setContentsMargins(6, 6, 6, 6)
        pop_lay.setSpacing(5)

        self._search_hint = QLabel("直接在上方原通道框输入", self._popup)
        self._search_hint.setObjectName("SignalPickerSearchHint")
        self._search_hint.setStyleSheet(
            "#SignalPickerSearchHint {color:#718096; background:#fbfcfe;"
            " padding:5px 7px; border-radius:5px;}"
        )
        pop_lay.addWidget(self._search_hint)

        self._list = QListWidget(self._popup)
        self._list.setSelectionMode(QListWidget.NoSelection)
        pop_lay.addWidget(self._list, 1)

        self._popup.installEventFilter(self)
        self._rebuild_list()
        self._refresh_display()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_selected(self, signals: Iterable[str]) -> None:
        new = tuple(signals)
        if self._single_select and len(new) > 1:
            new = new[:1]
        if new == self._selected:
            return
        self._selected = new
        self._suppress_signal = True
        try:
            for i in range(self._list.count()):
                item = self._list.item(i)
                checkbox = self._list.itemWidget(item)
                if isinstance(checkbox, QCheckBox):
                    want = item.data(Qt.UserRole) in self._selected
                    if checkbox.isChecked() != want:
                        checkbox.setChecked(want)
        finally:
            self._suppress_signal = False
        self._refresh_display()
        self.selectionChanged.emit(self._selected)

    def set_available(self, available_signals: Iterable[str]) -> None:
        self._available = list(available_signals)
        self._rebuild_list()
        self._refresh_display()

    def set_partially_available(
        self,
        partially_available: Mapping[str, str] | None,
        *,
        selectable: bool = False,
    ) -> None:
        self._partial = dict(partially_available or {})
        self._partial_selectable = bool(selectable)
        keep = tuple(
            signal for signal in self._selected
            if signal in self._available or signal in self._partial
        )
        if keep != self._selected:
            self._selected = keep
            self.selectionChanged.emit(self._selected)
        self._rebuild_list()
        self._refresh_display()

    def selected(self) -> tuple[str, ...]:
        return self._selected

    def show_popup(self) -> None:
        if self._popup.isVisible():
            return
        global_pos = self._display_frame.mapToGlobal(
            self._display_frame.rect().bottomLeft()
        )
        popup_width = max(280, self._display_frame.width())
        self._popup.setFixedWidth(popup_width)
        self._popup.adjustSize()
        self._popup.move(global_pos)
        self._popup.show()
        self._popup.raise_()
        self._popup.setFocus()
        self._arrow_button.setText("⌃")

    def hide_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()
        self._arrow_button.setText("⌄")

    def is_popup_visible(self) -> bool:
        return self._popup.isVisible()

    def visible_items(self) -> list[str]:
        return [
            self._list.item(index).data(Qt.UserRole)
            for index in range(self._list.count())
            if not self._list.item(index).isHidden()
        ]

    def is_disabled(self, signal: str) -> bool:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.UserRole) == signal:
                return not bool(item.flags() & Qt.ItemIsEnabled)
        return False

    def label_for(self, signal: str) -> str:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.UserRole) != signal:
                continue
            checkbox = self._list.itemWidget(item)
            return checkbox.text() if isinstance(checkbox, QCheckBox) else item.text()
        return ""

    def set_search_text(self, text: str) -> None:
        self._search.setText(text)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        """Return a selection-count-independent preferred size."""

        return QSize(220, self._DISPLAY_HEIGHT)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt API)
        return QSize(0, self._DISPLAY_HEIGHT)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _open_from_display(self) -> None:
        self.show_popup()
        self._search.setFocus()

    def _toggle_popup(self) -> None:
        if self.is_popup_visible():
            self.hide_popup()
        else:
            self.show_popup()

    def _rebuild_list(self) -> None:
        self._list.clear()
        names = list(self._available)
        names.extend(name for name in self._partial if name not in names)
        for name in names:
            item = QListWidgetItem(self._list)
            item.setData(Qt.UserRole, name)
            label = name
            if name in self._partial:
                label = f"{name} {self._partial[name]}".strip()
            checkbox = QCheckBox(label, self._list)
            checkbox.setChecked(name in self._selected)
            if name in self._partial and not self._partial_selectable:
                checkbox.setEnabled(False)
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            else:
                checkbox.toggled.connect(
                    lambda checked, signal=name: self._on_checkbox_toggled(
                        signal, checked,
                    )
                )
            self._list.setItemWidget(item, checkbox)
        self._on_search_text_changed(self._search.text())

    def _on_checkbox_toggled(self, signal: str, checked: bool) -> None:
        if self._suppress_signal:
            return
        if self._single_select:
            if checked:
                self._suppress_signal = True
                try:
                    for index in range(self._list.count()):
                        item = self._list.item(index)
                        checkbox = self._list.itemWidget(item)
                        if (
                            isinstance(checkbox, QCheckBox)
                            and item.data(Qt.UserRole) != signal
                            and checkbox.isChecked()
                        ):
                            checkbox.setChecked(False)
                finally:
                    self._suppress_signal = False
                self._selected = (signal,)
            else:
                self._selected = ()
        else:
            selected = list(self._selected)
            if checked and signal not in selected:
                selected.append(signal)
            elif not checked and signal in selected:
                selected.remove(signal)
            self._selected = tuple(selected)
        self._refresh_display()
        self.selectionChanged.emit(self._selected)

    def _on_search_text_changed(self, text: str) -> None:
        needle = text.strip().lower()
        visible_count = 0
        for index in range(self._list.count()):
            item = self._list.item(index)
            name = str(item.data(Qt.UserRole) or "").lower()
            hidden = bool(needle) and needle not in name
            item.setHidden(hidden)
            visible_count += int(not hidden)
        self._search_hint.setText(
            f"直接在上方原通道框输入    {visible_count} 条匹配"
        )
        self._refresh_display()

    def _clear_chips(self) -> None:
        while self._chip_layout.count():
            item = self._chip_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _refresh_display(self) -> None:
        self._clear_chips()
        if not self._selected:
            self._chip_host.hide()
            self._chip_host.setFixedWidth(0)
            self._overflow_label.hide()
            self._overflow_label.clear()
            self._search.setPlaceholderText("搜索信号…")
            self.updateGeometry()
            return

        self._search.setPlaceholderText("继续搜索…")
        frame_width = max(self._display_frame.width(), self.width(), 280)
        search_active = bool(self._search.text())
        visible_count = min(len(self._selected), self._MAX_VISIBLE_CHIPS)
        if search_active:
            # While typing, the original field is the search surface. Hide
            # the selection summary temporarily so the query itself is not
            # reduced to a few trailing characters in narrow columns.
            visible_count = 0
        elif frame_width < self._NARROW_TWO_CHIP_THRESHOLD:
            visible_count = min(visible_count, 1)

        hidden_count = 0 if search_active else len(self._selected) - visible_count
        overflow_width = 0
        if hidden_count:
            self._overflow_label.setText(f"+{hidden_count}")
            self._overflow_label.setToolTip("\n".join(self._selected[visible_count:]))
            self._overflow_label.adjustSize()
            overflow_width = max(32, self._overflow_label.sizeHint().width())
            self._overflow_label.setFixedWidth(overflow_width)
            self._overflow_label.show()
        else:
            self._overflow_label.hide()
            self._overflow_label.clear()
            self._overflow_label.setToolTip("")

        # Display margins + arrow + search + inter-item spacing are reserved
        # before assigning chip widths.  Chips are fixed to the remaining
        # budget, so no selection count can widen the host.
        reserved = 9 + self._arrow_button.width() + self._MIN_SEARCH_WIDTH
        reserved += overflow_width
        reserved += 4 * (visible_count + int(bool(hidden_count)) + 1)
        chip_budget = max(68 * visible_count, frame_width - reserved)
        per_chip = min(180, max(68, chip_budget // max(visible_count, 1)))

        for name in self._selected[:visible_count]:
            chip = SignalChip(name, parent=self._chip_host)
            chip.set_display_width(per_chip)
            chip.removeRequested.connect(self._on_chip_remove_requested)
            self._chip_layout.addWidget(chip)
        host_width = visible_count * per_chip + max(0, visible_count - 1) * 4
        self._chip_host.setFixedWidth(host_width)
        self._chip_host.setVisible(bool(visible_count))
        self.updateGeometry()

    def _on_chip_remove_requested(self, name: str) -> None:
        if name not in self._selected:
            return
        self._selected = tuple(
            signal for signal in self._selected if signal != name
        )
        self._suppress_signal = True
        try:
            for index in range(self._list.count()):
                item = self._list.item(index)
                if item.data(Qt.UserRole) != name:
                    continue
                checkbox = self._list.itemWidget(item)
                if isinstance(checkbox, QCheckBox) and checkbox.isChecked():
                    checkbox.setChecked(False)
        finally:
            self._suppress_signal = False
        self._refresh_display()
        self.selectionChanged.emit(self._selected)

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if hasattr(self, "_chip_layout"):
            self._refresh_display()

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        event_type = event.type()
        if obj is self._search:
            if event_type in (QEvent.FocusIn, QEvent.MouseButtonPress):
                self.show_popup()
            elif event_type == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.hide_popup()
                return True
        elif obj is self._popup:
            if event_type == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self.hide_popup()
                    return True
                if event.key() == Qt.Key_Backspace:
                    self._search.backspace()
                    return True
                if event.text() and event.text().isprintable():
                    self._search.insert(event.text())
                    return True
            if event_type == QEvent.FocusOut:
                new_focus = QApplication.focusWidget()
                if new_focus is self._search:
                    return False
                if new_focus is not None and self._popup.isAncestorOf(new_focus):
                    return False
                self.hide_popup()
        return super().eventFilter(obj, event)
