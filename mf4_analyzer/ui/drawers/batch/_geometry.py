"""Shared "fit to available screen" clamp for batch dialogs.

Both ``BatchSheet`` and ``BatchPreviewDialog`` used to hard-code
``self.resize(target_w, target_h)`` with no regard for the screen the
dialog would actually open on. On a 1366x768 laptop the client area is
smaller than the hard-coded target, so the bottom of the dialog (footer
buttons in ``BatchSheet``'s case) gets clipped off-screen.

This mirrors the established pattern in
``mf4_analyzer/ui/db_reference_dialog.py::_fit_to_available_screen`` —
screen lookup priority, available-geometry clamp, parent-width clamp,
and a floor — factored out so both batch dialogs share one
implementation instead of drifting apart.
"""
from __future__ import annotations

import weakref

from PyQt5.QtCore import QObject, QTimer, Qt


def configure_independent_tool_window(widget) -> None:
    """Turn a QDialog into a non-modal tool window the host can keep using.

    Modal ``exec_()`` sheets block the Analyzer, so a Batch/UltraView panel
    that should run beside single-file work must be a real ``Qt.Window``.
    """
    widget.setModal(False)
    widget.setWindowModality(Qt.NonModal)
    widget.setWindowFlags(
        Qt.Window
        | Qt.WindowTitleHint
        | Qt.WindowSystemMenuHint
        | Qt.WindowMinMaxButtonsHint
        | Qt.WindowCloseButtonHint
    )


def clear_tool_window_transient_parent(widget) -> None:
    """Drop the native transient-for link to the QWidget parent.

    Parenting a QDialog to MainWindow is useful for lifetime and close-together
    behavior. Cocoa/Win32 still treat that as transient-for, so a click inside
    the tool window activates and raises the Analyzer over it. Independent
    tool windows must not keep that native relationship.
    """
    handle = widget.windowHandle()
    if handle is None:
        widget.winId()
        handle = widget.windowHandle()
    if handle is None:
        return
    try:
        handle.setTransientParent(None)
    except (RuntimeError, TypeError, AttributeError):
        return


def present_independent_tool_window(widget) -> None:
    """Show, raise, then detach from the host window's z-order.

    A minimized tool window is restored first. Maximized and fullscreen bits
    stay set. ``raise_`` / ``activateWindow`` can re-create the native
    transient-for link, so the detach must run last.
    """
    _clear_window_minimized(widget)
    show = getattr(widget, "show", None)
    if callable(show):
        show()
    raiser = getattr(widget, "raise_", None)
    if callable(raiser):
        raiser()
    activate = getattr(widget, "activateWindow", None)
    if callable(activate):
        activate()
    clear_tool_window_transient_parent(widget)


def _clear_window_minimized(widget) -> None:
    """Drop ``Qt.WindowMinimized`` and leave maximized / fullscreen alone."""
    if not _widget_alive(widget):
        return
    state_of = getattr(widget, "windowState", None)
    set_state = getattr(widget, "setWindowState", None)
    if not callable(state_of) or not callable(set_state):
        return
    try:
        state = state_of()
    except (RuntimeError, TypeError):
        return
    if not bool(state & Qt.WindowMinimized):
        return
    try:
        set_state(state & ~Qt.WindowMinimized)
    except (RuntimeError, TypeError):
        return


_NUDGE_BLOCKED_STATES = (
    Qt.WindowMinimized | Qt.WindowMaximized | Qt.WindowFullScreen
)


def show_event_should_nudge(widget, event) -> bool:
    """Nudge only a deliberate show of a normal window.

    Spontaneous shows (window-manager maps) and minimized, maximized, or
    fullscreen windows are left to the platform. Screen changes use
    ``bind_screen_overflow_nudge`` instead of this gate.
    """
    if not _widget_alive(widget) or event is None:
        return False
    spontaneous = getattr(event, "spontaneous", None)
    if callable(spontaneous):
        try:
            if spontaneous():
                return False
        except (RuntimeError, TypeError):
            return False
    state_of = getattr(widget, "windowState", None)
    if not callable(state_of):
        return False
    try:
        state = state_of()
    except (RuntimeError, TypeError):
        return False
    return not bool(state & _NUDGE_BLOCKED_STATES)


class _ScreenOverflowNudge(QObject):
    """One overflow nudge when the tool window's screen changes.

    The ``screenChanged`` slot is this object's bound method. The connection
    is removed on close and again when the host is destroyed.
    """

    def __init__(self, host):
        super().__init__(host)
        # Weak: a strong host pointer here cycles through this child and keeps
        # the tool window's Python wrapper alive after Qt has deleted it.
        self._host_ref = weakref.ref(host)
        self._handle = None
        destroyed = getattr(host, "destroyed", None)
        if destroyed is not None:
            try:
                destroyed.connect(self.unbind)
            except (RuntimeError, TypeError):
                pass

    def _host_widget(self):
        host = self._host_ref()
        if not _widget_alive(host):
            return None
        return host

    def bind(self) -> None:
        host = self._host_widget()
        if host is None:
            return
        handle = host.windowHandle()
        if handle is None:
            try:
                host.winId()
            except (RuntimeError, TypeError, AttributeError):
                return
            host = self._host_widget()
            if host is None:
                return
            handle = host.windowHandle()
        if handle is None:
            return
        if self._handle is handle and _widget_alive(handle):
            return
        self.unbind()
        try:
            handle.screenChanged.connect(self._on_screen_changed)
        except (RuntimeError, TypeError):
            return
        self._handle = handle

    def unbind(self, *_args) -> None:
        handle = self._handle
        self._handle = None
        if handle is None or not _widget_alive(handle):
            return
        try:
            handle.screenChanged.disconnect(self._on_screen_changed)
        except (RuntimeError, TypeError):
            return

    def _on_screen_changed(self, _screen=None) -> None:
        host = self._host_widget()
        if host is None:
            return
        from mf4_analyzer.ui_kit.dialog_geometry import nudge_into_work_area

        parent = None
        try:
            parent = host.parentWidget()
        except (RuntimeError, TypeError):
            parent = None
        nudge_into_work_area(host, parent=parent)


def bind_screen_overflow_nudge(widget) -> None:
    """Connect ``windowHandle().screenChanged`` to one overflow-only nudge."""
    if not _widget_alive(widget):
        return
    watcher = getattr(widget, "_screen_overflow_nudge", None)
    if not isinstance(watcher, _ScreenOverflowNudge) or not _widget_alive(watcher):
        watcher = _ScreenOverflowNudge(widget)
        widget._screen_overflow_nudge = watcher
    watcher.bind()


def unbind_screen_overflow_nudge(widget) -> None:
    """Drop the screen-change nudge, if this window still has one."""
    if not _widget_alive(widget):
        return
    watcher = getattr(widget, "_screen_overflow_nudge", None)
    if isinstance(watcher, _ScreenOverflowNudge) and _widget_alive(watcher):
        watcher.unbind()


def _widget_alive(widget) -> bool:
    if widget is None:
        return False
    try:
        from PyQt5 import sip
        return not sip.isdeleted(widget)
    except (RuntimeError, TypeError):
        return True


def fit_dialog_to_available_screen(
    dialog, parent, target_w: int, target_h: int, *, min_w: int, min_h: int,
) -> None:
    """Resize ``dialog`` to the shared screen budget, then leave it resizable.

    Forwards to ``ui_kit.dialog_geometry.fit_window``. Content minimums
    cannot break the available-geometry budget. Does not call
    ``setMaximumSize``, so later test/user resizes still work.

    After a fit that was applied, the minimum is the lesser of the content
    floor and the client that was actually applied. A degenerate decorated
    plan is not applied; the dialog is then resized to the content floor
    and that same minimum is set, still never above the applied client.
    """
    from mf4_analyzer.ui_kit.dialog_geometry import (
        decorated_plan_is_degenerate,
        fit_window,
    )
    from mf4_analyzer.ui_kit.layout_diagnostics import (
        detailed_layout_enabled,
        note_tool_window_geometry,
    )

    modal = True
    is_modal = getattr(dialog, "isModal", None)
    if callable(is_modal):
        try:
            modal = bool(is_modal())
        except RuntimeError:
            modal = True
    plan = fit_window(
        dialog,
        (int(target_w), int(target_h)),
        parent=parent,
        content_minimum=(int(min_w), int(min_h)),
        clamp_width_to_parent=bool(modal and parent is not None),
    )
    if decorated_plan_is_degenerate(dialog, plan):
        dialog.resize(int(min_w), int(min_h))
    applied_w = int(dialog.width())
    applied_h = int(dialog.height())
    dialog.setMinimumSize(
        min(int(min_w), max(0, applied_w)),
        min(int(min_h), max(0, applied_h)),
    )
    if detailed_layout_enabled() and _widget_alive(dialog):
        from mf4_analyzer.ui_kit.dialog_geometry import tool_window_plan_facts

        note_tool_window_geometry(
            dialog, "plan", plan=tool_window_plan_facts(dialog, plan),
        )


def note_tool_window_phase(widget, phase: str) -> None:
    """Lifecycle size checkpoint. Silent unless the layout switch is on."""
    from mf4_analyzer.ui_kit.layout_diagnostics import note_tool_window_geometry

    note_tool_window_geometry(widget, phase)


def arm_post_show_geometry_check(widget) -> None:
    """Schedule one post-show size check. The slot is a bound method."""
    if not _widget_alive(widget):
        return
    if getattr(widget, "_geometry_check_running", False):
        return
    widget._geometry_retry_used = False
    if getattr(widget, "_geometry_check_pending", False):
        return
    checker = getattr(widget, "_check_tool_window_geometry", None)
    if not callable(checker):
        return
    widget._geometry_check_pending = True
    QTimer.singleShot(0, checker)


def _client_needs_geometry_recovery(widget) -> bool:
    from mf4_analyzer.ui_kit.dialog_geometry import MIN_DECORATED_CLIENT

    width = int(widget.width())
    height = int(widget.height())
    if width < int(widget.minimumWidth()) or height < int(widget.minimumHeight()):
        return True
    return width < MIN_DECORATED_CLIENT or height < MIN_DECORATED_CLIENT


def finish_post_show_geometry_check(widget, refit) -> None:
    """Compare the client with its minimum once. Refit at most once per show."""
    if not _widget_alive(widget):
        return
    if getattr(widget, "_geometry_check_running", False):
        return
    widget._geometry_check_running = True
    try:
        widget._geometry_check_pending = False
        if (
            not getattr(widget, "_geometry_retry_used", False)
            and _client_needs_geometry_recovery(widget)
        ):
            widget._geometry_retry_used = True
            before_w = int(widget.width())
            before_h = int(widget.height())
            refit()
            if _widget_alive(widget):
                from mf4_analyzer.ui_kit.layout_diagnostics import (
                    warn_tool_window_geometry_recovered,
                )

                warn_tool_window_geometry_recovered(
                    widget, before_width=before_w, before_height=before_h,
                )
        if _widget_alive(widget):
            note_tool_window_phase(widget, "after-show-tick")
    finally:
        if _widget_alive(widget):
            widget._geometry_check_running = False
