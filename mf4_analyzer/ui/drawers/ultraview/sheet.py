"""UltraViewSheet — non-modal Board window that leaves Analyzer analysis live.

UltraView is a read-only snapshot board, not a sixth analysis algorithm.
Hosting it as an independent tool window (same shape as BatchSheet) lets
the user keep working a single-file View while the Board stays visible.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QPushButton, QVBoxLayout, QWidget

from ...widgets.toast import Toast
from ..batch._geometry import (
    clear_tool_window_transient_parent,
    configure_independent_tool_window,
    fit_dialog_to_available_screen,
    present_independent_tool_window,
)


def _alive(obj) -> bool:
    if obj is None:
        return False
    try:
        from PyQt5 import sip
        return not sip.isdeleted(obj)
    except (RuntimeError, TypeError):
        return True


class UltraViewSheet(QDialog):
    def __init__(self, parent, page: QWidget, stack=None):
        super().__init__(parent)
        self.setObjectName("UltraViewSheet")
        self.setWindowTitle("总览")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        configure_independent_tool_window(self)
        self._page = page
        self._stack = stack
        self._stack_index = -1
        self._own_toast = None
        self._last_toast_text = ""
        self._last_toast_kind = ""
        if stack is not None and page is not None:
            index_of = getattr(stack, "indexOf", None)
            if callable(index_of):
                try:
                    self._stack_index = int(index_of(page))
                except Exception:
                    self._stack_index = -1
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        fit_dialog_to_available_screen(
            self, parent, 1280, 800, min_w=800, min_h=560,
        )

    def present(self) -> None:
        """Adopt the Board page and show this window beside the Analyzer."""
        self._adopt_page()
        self._silence_dialog_buttons()
        present_independent_tool_window(self)

    def toast(self, text: str, kind: str = "info") -> None:
        """Paint acknowledgement on this Board window, not the Analyzer."""
        self._last_toast_text = text
        self._last_toast_kind = kind
        if not text:
            return
        if self.isVisible():
            if self._own_toast is None:
                self._own_toast = Toast(self, bottom_margin=12)
            self._own_toast.show_message(text, level=kind)
            return
        parent = self.parent()
        parent_toast = getattr(parent, "toast", None) if parent is not None else None
        if callable(parent_toast):
            parent_toast(text, kind)

    def showEvent(self, event):  # noqa: N802 (Qt API)
        super().showEvent(event)
        clear_tool_window_transient_parent(self)
        self._silence_dialog_buttons()

    def keyPressEvent(self, event):  # noqa: N802 (Qt API)
        # QDialog treats Return as accept() when a default/autoDefault
        # QPushButton exists. This is a tool window, not a modal form.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def _silence_dialog_buttons(self) -> None:
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

    def _adopt_page(self) -> None:
        page = self._page
        if not _alive(page):
            return
        layout = self.layout()
        if layout is None:
            return
        if page.parentWidget() is not self:
            layout.addWidget(page)
        # QStackedWidget explicitly hide()s inactive pages. Reparenting does
        # not clear that flag, and a hidden child is skipped by QLayout —
        # the tool window would open blank. Same contract as
        # ChartStack.take_hint_bar: after changing parent, show the widget.
        page.setVisible(True)

    def _restore_page(self) -> None:
        page = self._page
        stack = self._stack
        if not _alive(page) or not _alive(stack):
            return
        if page.parentWidget() is stack:
            return
        insert = getattr(stack, "insertWidget", None)
        add = getattr(stack, "addWidget", None)
        idx = self._stack_index
        if callable(insert) and idx >= 0:
            insert(idx, page)
            return
        if callable(add):
            add(page)

    def _reset_session(self) -> None:
        page = self._page
        if not _alive(page):
            return
        reset = getattr(page, "reset_sheet_session", None)
        if callable(reset):
            reset()

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        self._reset_session()
        self._restore_page()
        super().closeEvent(event)

    def done(self, result):  # noqa: N802 (Qt API)
        self._reset_session()
        self._restore_page()
        super().done(result)
