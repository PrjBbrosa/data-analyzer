"""Signal picker chip + popup widget for the batch dialog.

Provides ``SignalPickerPopup`` — a chips-display ``QPushButton`` that opens a
floating ``QFrame`` popup containing a search ``QLineEdit`` plus a multi-select
``QListWidget`` driven by ``QCheckBox`` row widgets. Items in
``partially_available`` are added but disabled (``Qt.ItemIsEnabled`` cleared)
and labelled with the supplied hint (e.g. ``"(2/3)"``).

ESC inside the popup hides it; focus-out also hides it (``Qt.Popup`` window
flag handles platform-level click-outside; the explicit ``clearFocus()`` test
hook is wired via an event filter).
"""
from __future__ import annotations

from typing import Iterable, Mapping

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)


class SignalChip(QWidget):
    """Single-row chip widget: signal label + remove button.

    Emits ``removeRequested(name)`` when the × button is clicked. The
    label elides at ``max_label_chars`` with the full name as tooltip
    so long DBC channel names don't push the chip frame wide.
    """

    removeRequested = pyqtSignal(str)

    def __init__(
        self,
        name: str,
        max_label_chars: int = 48,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self.setObjectName("SignalChip")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 4, 2)
        lay.setSpacing(4)

        display = name if len(name) <= max_label_chars else name[: max_label_chars] + "…"
        self._label = QLabel(display, self)
        self._label.setToolTip(name)
        lay.addWidget(self._label, 1)

        self._remove_btn = QPushButton("×", self)
        self._remove_btn.setObjectName("SignalChipRemove")
        self._remove_btn.setFixedSize(18, 18)
        self._remove_btn.setFlat(True)
        self._remove_btn.clicked.connect(lambda: self.removeRequested.emit(self._name))
        lay.addWidget(self._remove_btn)

    def name(self) -> str:
        return self._name


class _ClickableFrame(QFrame):
    """QFrame subclass that emits ``clicked`` on left mouse press.

    Used as the chip-display container so a click anywhere inside the
    frame area (including on the placeholder label or the scroll
    viewport background) toggles the popup. Children that consume
    presses themselves (the remove ``×`` button, chip label) shadow this
    naturally — they get the event first per Qt event delivery rules.
    """

    clicked = pyqtSignal()

    def mousePressEvent(self, event):  # noqa: N802 (Qt API)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class SignalPickerPopup(QWidget):
    """Chips display + popup multi-select picker for signal names."""

    selectionChanged = pyqtSignal(tuple)

    def __init__(
        self,
        available_signals: Iterable[str] = (),
        partially_available: Mapping[str, str] | None = None,
        initial_selection: tuple[str, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._available: list[str] = list(available_signals)
        self._partial: dict[str, str] = dict(partially_available or {})
        self._selected: tuple[str, ...] = tuple(initial_selection)
        self._suppress_signal = False

        # ----- chip display frame (replaces single-line button) -----
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._display_frame = _ClickableFrame(self)
        self._display_frame.setObjectName("SignalPickerDisplay")
        self._display_frame.setFrameShape(QFrame.NoFrame)
        self._display_frame.setStyleSheet(
            "#SignalPickerDisplay {border:1px solid #cbd5e1; border-radius:6px;"
            " background:#fff;}"
        )
        self._display_frame.setMinimumHeight(28)
        # Width is bounded by the parent column; height grows with chip count
        # but is capped at MAX_VISIBLE_ROWS via the internal scroll container.
        self._display_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Click anywhere on the frame (including children that don't consume
        # the press) toggles the popup. The remove × button is a QPushButton
        # so it consumes its own press without bubbling.
        self._display_frame.clicked.connect(self._toggle_popup)

        frame_lay = QVBoxLayout(self._display_frame)
        frame_lay.setContentsMargins(4, 4, 4, 4)
        frame_lay.setSpacing(3)

        # Chip-row sizing constants. The display frame's sizeHint must
        # GROW with chip count (issue-1 contract) up to MAX_VISIBLE_ROWS,
        # then plateau (further chips scroll). A QScrollArea alone does
        # NOT propagate inner content size to the parent's sizeHint, so
        # we explicitly drive _chip_scroll's max/min height from the
        # current chip count in _refresh_display below.
        self._CHIP_ROW_HEIGHT = 26   # one chip row's pixel height (incl. spacing)
        self._CHIP_MAX_VISIBLE_ROWS = 3
        self._CHIP_FRAME_VPADDING = 8  # frame_lay top+bottom margins (4+4)

        # Scrollable inner area for chips (caps the visible height).
        self._chip_scroll = QScrollArea(self._display_frame)
        self._chip_scroll.setFrameShape(QFrame.NoFrame)
        self._chip_scroll.setWidgetResizable(True)
        self._chip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._chip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Hard ceiling on the scroll area's height; _refresh_display sets
        # the soft height (= row_count * row_height) below this ceiling so
        # _display_frame.sizeHint() honestly reflects chip count.
        self._chip_scroll.setMaximumHeight(
            self._CHIP_MAX_VISIBLE_ROWS * self._CHIP_ROW_HEIGHT
        )

        self._chip_host = QWidget(self._chip_scroll)
        self._chip_layout = QVBoxLayout(self._chip_host)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(2)
        self._chip_layout.addStretch(1)
        self._chip_scroll.setWidget(self._chip_host)
        frame_lay.addWidget(self._chip_scroll, 1)

        self._placeholder_label = QLabel("(未选择信号)  ▾", self._display_frame)
        self._placeholder_label.setStyleSheet("color:#94a3b8; padding:2px 4px;")
        # Make the placeholder transparent to mouse events so a click on it
        # bubbles through to _ClickableFrame.mousePressEvent and opens the
        # popup. (QLabel by default does not consume left-button presses,
        # but it stops propagation through child→parent in some Qt builds —
        # WA_TransparentForMouseEvents is the explicit, portable fix.)
        self._placeholder_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        frame_lay.addWidget(self._placeholder_label)

        # Likewise for the scroll viewport's empty area: chips themselves
        # are children of _chip_host; clicks landing on host empty space
        # should propagate up. QScrollArea.viewport() is a normal QWidget
        # that does NOT consume left presses, so press events naturally
        # bubble to _display_frame — no extra setup needed there.

        outer.addWidget(self._display_frame, 1)

        # ----- popup -----
        self._popup = QFrame(self, Qt.Popup)
        self._popup.setObjectName("SignalPickerPopup")
        self._popup.setFrameShape(QFrame.StyledPanel)
        self._popup.setStyleSheet(
            "#SignalPickerPopup {background:#fff; border:1px solid #cbd5e1;"
            " border-radius:8px;}"
        )
        self._popup.setMinimumWidth(280)
        # Strong focus on the popup itself so clearFocus() emits a real
        # FocusOut event (the test path simulates click-away that way).
        self._popup.setFocusPolicy(Qt.StrongFocus)
        pop_lay = QVBoxLayout(self._popup)
        pop_lay.setContentsMargins(8, 8, 8, 8)
        pop_lay.setSpacing(6)

        self._search = QLineEdit(self._popup)
        self._search.setPlaceholderText("搜索信号…")
        self._search.textChanged.connect(self._on_search_text_changed)
        pop_lay.addWidget(self._search)

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
        new = tuple(s for s in signals)
        if new == self._selected:
            return
        self._selected = new
        # Sync checkboxes (without re-emitting per click).
        self._suppress_signal = True
        try:
            for i in range(self._list.count()):
                item = self._list.item(i)
                name = item.data(Qt.UserRole)
                cb = self._list.itemWidget(item)
                if isinstance(cb, QCheckBox):
                    want = name in self._selected
                    if cb.isChecked() != want:
                        cb.setChecked(want)
        finally:
            self._suppress_signal = False
        self._refresh_display()
        self.selectionChanged.emit(self._selected)

    def set_available(self, available_signals: Iterable[str]) -> None:
        # Preserve _selected intact across this mutator (ultrareview
        # bug_002). The settling call is set_partially_available — that
        # is where reconciliation happens against the COMBINED universe.
        # Performing it here would drop names that are about to land in
        # the partial dict during a paired (set_available; set_partial)
        # universe swap, defeating BatchSheet.signals_marked_unavailable.
        self._available = list(available_signals)
        self._rebuild_list()
        self._refresh_display()

    def set_partially_available(
        self, partially_available: Mapping[str, str] | None
    ) -> None:
        self._partial = dict(partially_available or {})
        # Reconcile against the now-coherent (available, partial) pair:
        # keep names present in either set; drop only names that vanished
        # from BOTH. Emit selectionChanged iff the tuple actually changed
        # (ultrareview bug_002).
        keep = tuple(
            s for s in self._selected
            if s in self._available or s in self._partial
        )
        if keep != self._selected:
            self._selected = keep
            self.selectionChanged.emit(self._selected)
        self._rebuild_list()
        self._refresh_display()

    def selected(self) -> tuple[str, ...]:
        return self._selected

    def show_popup(self) -> None:
        # Position popup just under the display frame.
        global_pos = self._display_frame.mapToGlobal(
            self._display_frame.rect().bottomLeft()
        )
        self._popup.move(global_pos)
        self._popup.adjustSize()
        self._popup.show()
        self._popup.raise_()
        # Focus the popup frame itself (StrongFocus) so a programmatic
        # clearFocus() — used by tests to simulate click-away — actually
        # produces a FocusOut event we can observe in eventFilter.
        self._popup.setFocus()

    def hide_popup(self) -> None:
        if self._popup.isVisible():
            self._popup.hide()

    def is_popup_visible(self) -> bool:
        return self._popup.isVisible()

    def visible_items(self) -> list[str]:
        out: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if not item.isHidden():
                out.append(item.data(Qt.UserRole))
        return out

    def is_disabled(self, signal: str) -> bool:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == signal:
                return not bool(item.flags() & Qt.ItemIsEnabled)
        return False

    def label_for(self, signal: str) -> str:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == signal:
                cb = self._list.itemWidget(item)
                if isinstance(cb, QCheckBox):
                    return cb.text()
                return item.text()
        return ""

    def set_search_text(self, text: str) -> None:
        self._search.setText(text)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _toggle_popup(self) -> None:
        if self.is_popup_visible():
            self.hide_popup()
        else:
            self.show_popup()

    def _rebuild_list(self) -> None:
        self._list.clear()
        # Available signals are checkable; partially-available are disabled.
        all_names = list(self._available)
        for name in self._partial.keys():
            if name not in all_names:
                all_names.append(name)
        for name in all_names:
            item = QListWidgetItem(self._list)
            item.setData(Qt.UserRole, name)
            label = name
            if name in self._partial:
                hint = self._partial[name]
                label = f"{name} {hint}".strip()
            cb = QCheckBox(label, self._list)
            if name in self._partial:
                cb.setEnabled(False)
                # Clear the item-level flag so is_disabled() reads False -> True.
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            else:
                cb.setChecked(name in self._selected)
                cb.toggled.connect(lambda checked, s=name: self._on_checkbox_toggled(s, checked))
            self._list.setItemWidget(item, cb)

    def _on_checkbox_toggled(self, signal: str, checked: bool) -> None:
        if self._suppress_signal:
            return
        sel = list(self._selected)
        if checked and signal not in sel:
            sel.append(signal)
        elif not checked and signal in sel:
            sel.remove(signal)
        self._selected = tuple(sel)
        self._refresh_display()
        self.selectionChanged.emit(self._selected)

    def _on_search_text_changed(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = (item.data(Qt.UserRole) or "").lower()
            item.setHidden(bool(needle) and needle not in name)

    def _refresh_display(self) -> None:
        # Tear down existing chip rows (everything except the trailing stretch).
        while self._chip_layout.count() > 1:
            item = self._chip_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not self._selected:
            self._placeholder_label.setVisible(True)
            self._chip_scroll.setVisible(False)
            # Reset the scroll area's fixed height so the frame collapses
            # to placeholder height when nothing is selected.
            self._chip_scroll.setFixedHeight(0)
            self.updateGeometry()
            return
        self._placeholder_label.setVisible(False)
        self._chip_scroll.setVisible(True)
        for name in self._selected:
            chip = SignalChip(name, parent=self._chip_host)
            chip.removeRequested.connect(self._on_chip_remove_requested)
            # Insert before the trailing stretch.
            self._chip_layout.insertWidget(self._chip_layout.count() - 1, chip)
        # Drive the scroll area's height from the chip count so
        # _display_frame.sizeHint().height() actually grows with
        # selection up to MAX_VISIBLE_ROWS, then plateaus (further
        # chips scroll). Without this, the QScrollArea reports a
        # fixed minimumSizeHint and the frame's overall sizeHint stays
        # constant — defeating the issue-1 contract test.
        visible_rows = min(len(self._selected), self._CHIP_MAX_VISIBLE_ROWS)
        target_h = visible_rows * self._CHIP_ROW_HEIGHT
        self._chip_scroll.setFixedHeight(target_h)
        self.updateGeometry()

    def _on_chip_remove_requested(self, name: str) -> None:
        if name not in self._selected:
            return
        sel = tuple(s for s in self._selected if s != name)
        self._selected = sel
        # Mirror the checkbox state in the popup so re-opening shows the
        # current truth.
        self._suppress_signal = True
        try:
            for i in range(self._list.count()):
                item = self._list.item(i)
                if item.data(Qt.UserRole) == name:
                    cb = self._list.itemWidget(item)
                    if isinstance(cb, QCheckBox) and cb.isChecked():
                        cb.setChecked(False)
        finally:
            self._suppress_signal = False
        self._refresh_display()
        self.selectionChanged.emit(self._selected)

    # ------------------------------------------------------------------
    # Event handling for the popup
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event):  # noqa: N802 (Qt signature)
        if obj is self._popup:
            etype = event.type()
            if etype == QEvent.KeyPress and event.key() == Qt.Key_Escape:
                self.hide_popup()
                return True
            if etype == QEvent.FocusOut:
                # If focus moved to a descendant of the popup (e.g. the
                # search QLineEdit), keep the popup open — otherwise the
                # user can never click into the inner search field
                # (ultrareview bug_015). Only hide when focus actually
                # left the popup subtree.
                new_focus = QApplication.focusWidget()
                if new_focus is not None and self._popup.isAncestorOf(new_focus):
                    return False
                self.hide_popup()
                return False
        return super().eventFilter(obj, event)
