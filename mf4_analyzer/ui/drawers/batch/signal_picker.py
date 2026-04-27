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
    QCheckBox, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QVBoxLayout, QWidget,
)


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

        # ----- chip display button -----
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._display_btn = QPushButton(self)
        self._display_btn.setObjectName("SignalPickerDisplay")
        self._display_btn.setMinimumHeight(28)
        self._display_btn.setStyleSheet(
            "#SignalPickerDisplay {text-align:left; padding:4px 8px;"
            " border:1px solid #cbd5e1; border-radius:6px; background:#fff;}"
        )
        self._display_btn.clicked.connect(self._toggle_popup)
        outer.addWidget(self._display_btn, 1)

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
        self._available = list(available_signals)
        # Drop any selection no longer present.
        self._selected = tuple(s for s in self._selected if s in self._available)
        self._rebuild_list()
        self._refresh_display()

    def set_partially_available(
        self, partially_available: Mapping[str, str] | None
    ) -> None:
        self._partial = dict(partially_available or {})
        # Selected items that became partially-available drop out.
        self._selected = tuple(s for s in self._selected if s not in self._partial)
        self._rebuild_list()
        self._refresh_display()

    def selected(self) -> tuple[str, ...]:
        return self._selected

    def show_popup(self) -> None:
        # Position popup just under the display button.
        global_pos = self._display_btn.mapToGlobal(self._display_btn.rect().bottomLeft())
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
        if self._selected:
            chips = "  ".join(f"[{s} x]" for s in self._selected)
            self._display_btn.setText(f"{chips}  v")
        else:
            self._display_btn.setText("(未选择信号)  v")

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
                # Defer to event-loop tail so we don't close while the focus
                # change is still in flight (ensures the popup actually hides
                # under offscreen Qt where Qt.Popup auto-close may not fire).
                self.hide_popup()
                return False
        return super().eventFilter(obj, event)
