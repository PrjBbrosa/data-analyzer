"""UltraViewSheet — non-modal Board window that leaves Analyzer analysis live.

UltraView is a read-only snapshot board, not a sixth analysis algorithm.
Hosting it as an independent tool window (same shape as BatchSheet) lets
the user keep working a single-file View while the Board stays visible.
"""
from __future__ import annotations

import logging

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QDialog, QPushButton, QVBoxLayout, QWidget

from ...widgets.toast import Toast
from ..batch._geometry import (
    arm_post_show_geometry_check,
    bind_screen_overflow_nudge,
    clear_tool_window_transient_parent,
    configure_independent_tool_window,
    finish_post_show_geometry_check,
    fit_dialog_to_available_screen,
    note_tool_window_phase,
    present_independent_tool_window,
    show_event_should_nudge,
    unbind_screen_overflow_nudge,
)

_LOG = logging.getLogger(__name__)


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
        self.setWindowTitle("UltraView")
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
        note_tool_window_phase(self, "construct-end")

    def present(self) -> None:
        """Adopt the Board page and show this window beside the Analyzer."""
        self._adopt_page()
        self._silence_dialog_buttons()
        present_independent_tool_window(self)
        self._fit_page_on_open()

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
        note_tool_window_phase(self, "show-enter")
        super().showEvent(event)
        clear_tool_window_transient_parent(self)
        self._silence_dialog_buttons()
        if show_event_should_nudge(self, event):
            from mf4_analyzer.ui_kit.dialog_geometry import nudge_into_work_area

            nudge_into_work_area(self, parent=self.parentWidget())
        bind_screen_overflow_nudge(self)
        arm_post_show_geometry_check(self)
        note_tool_window_phase(self, "show-return")

    def _check_tool_window_geometry(self) -> None:
        finish_post_show_geometry_check(self, self._refit_for_geometry_recovery)

    def _refit_for_geometry_recovery(self) -> None:
        fit_dialog_to_available_screen(
            self, self.parentWidget(), 1280, 800, min_w=800, min_h=560,
        )

    def _fit_page_on_open(self) -> None:
        if not _alive(self):
            return
        page = self._page
        if not _alive(page):
            return
        fitter = getattr(page, "fit_on_open", None)
        if callable(fitter):
            fitter()

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

    def release_page(self) -> None:
        """Return the Board page to its stack. Safe to call more than once."""
        self._restore_page()

    def _warn_restore_failed(self, *, page_dead: bool, stack_dead: bool) -> None:
        _LOG.warning(
            "UltraViewSheet could not restore the Board page "
            "(page_dead=%s, stack_dead=%s)",
            page_dead,
            stack_dead,
        )

    def _restore_page(self) -> None:
        page = self._page
        stack = self._stack
        page_dead = page is not None and not _alive(page)
        stack_dead = stack is not None and not _alive(stack)
        if page_dead or stack_dead:
            self._warn_restore_failed(page_dead=page_dead, stack_dead=stack_dead)
            return
        if page is None or stack is None:
            return
        try:
            parent = page.parentWidget()
        except RuntimeError:
            self._warn_restore_failed(page_dead=True, stack_dead=stack_dead)
            return
        # Already home, or a newer sheet adopted the page. A second release
        # must not pull the page back off that sheet.
        if parent is stack or (parent is not None and parent is not self):
            return
        insert = getattr(stack, "insertWidget", None)
        add = getattr(stack, "addWidget", None)
        idx = self._stack_index
        try:
            if callable(insert) and idx >= 0:
                insert(idx, page)
                return
            if callable(add):
                add(page)
        except RuntimeError:
            self._warn_restore_failed(page_dead=False, stack_dead=True)

    def _reset_session(self) -> None:
        page = self._page
        if not _alive(page):
            return
        reset = getattr(page, "reset_sheet_session", None)
        if callable(reset):
            reset()

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        self._reset_session()
        self.release_page()
        unbind_screen_overflow_nudge(self)
        super().closeEvent(event)

    def done(self, result):  # noqa: N802 (Qt API)
        self._reset_session()
        self.release_page()
        unbind_screen_overflow_nudge(self)
        super().done(result)

    def event(self, event):  # noqa: N802 (Qt API)
        # deleteLater skips closeEvent. Return the page before Qt deletes
        # this sheet and every child that is still parented here.
        if event.type() == QEvent.DeferredDelete:
            unbind_screen_overflow_nudge(self)
            self.release_page()
        return super().event(event)
