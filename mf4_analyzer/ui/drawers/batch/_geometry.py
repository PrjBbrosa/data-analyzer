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

from PyQt5.QtCore import Qt


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

    ``raise_`` / ``activateWindow`` can re-create the native transient-for
    link, so the detach must run last.
    """
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


def fit_dialog_to_available_screen(
    dialog, parent, target_w: int, target_h: int, *, min_w: int, min_h: int,
) -> None:
    """Resize ``dialog`` to the shared screen budget, then leave it resizable.

    Forwards to ``ui_kit.dialog_geometry.fit_window``. Content minimums
    cannot break the available-geometry budget. Does not call
    ``setMaximumSize``, so later test/user resizes still work.
    """
    from mf4_analyzer.ui_kit.dialog_geometry import fit_window

    modal = True
    is_modal = getattr(dialog, "isModal", None)
    if callable(is_modal):
        try:
            modal = bool(is_modal())
        except RuntimeError:
            modal = True
    fit_window(
        dialog,
        (int(target_w), int(target_h)),
        parent=parent,
        content_minimum=(int(min_w), int(min_h)),
        clamp_width_to_parent=bool(modal and parent is not None),
    )
