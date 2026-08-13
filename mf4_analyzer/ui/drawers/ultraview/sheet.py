"""UltraViewSheet — non-modal Board window that leaves Analyzer analysis live.

UltraView is a read-only snapshot board, not a sixth analysis algorithm.
Hosting it as an independent tool window (same shape as BatchSheet) lets
the user keep working a single-file View while the Board stays visible.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QWidget

from ..batch._geometry import (
    configure_independent_tool_window,
    fit_dialog_to_available_screen,
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
        configure_independent_tool_window(self)
        self._page = page
        self._stack = stack
        self._stack_index = -1
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
        self.show()
        self.raise_()
        self.activateWindow()

    def _adopt_page(self) -> None:
        page = self._page
        if not _alive(page):
            return
        layout = self.layout()
        if layout is None:
            return
        if page.parentWidget() is not self:
            layout.addWidget(page)

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

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        self._restore_page()
        super().closeEvent(event)

    def done(self, result):  # noqa: N802 (Qt API)
        self._restore_page()
        super().done(result)
