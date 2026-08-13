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
from PyQt5.QtWidgets import QApplication


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


def fit_dialog_to_available_screen(
    dialog, parent, target_w: int, target_h: int, *, min_w: int, min_h: int,
) -> None:
    """Resize ``dialog`` to ``target_w``x``target_h`` clamped to the screen.

    Screen lookup priority: the screen under ``parent``'s center, then the
    application's primary screen, then no clamp at all (target size is
    used as-is). ``QApplication.screenAt`` can raise before the parent
    window is mapped, so it is guarded with try/except.

    Only ``dialog.resize(...)`` is called — never
    ``setMaximumHeight``/``setMaximumSize`` — so tests that explicitly
    resize the dialog afterwards (e.g. to exercise a specific size) are
    never blocked, and users can still freely enlarge the window by hand.
    """
    screen = None
    if parent is not None:
        try:
            screen = QApplication.screenAt(parent.geometry().center())
        except Exception:
            screen = None
    if screen is None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None

    max_w, max_h = target_w, target_h
    if screen is not None:
        avail = screen.availableGeometry()
        # 72px accounts for the Windows title bar (~31px) plus border/
        # shadow chrome that resize() does not itself cover, since
        # resize() sets the client-area size only.
        max_w = min(max_w, avail.width() - 48)
        max_h = min(max_h, avail.height() - 72)
    modal = True
    is_modal = getattr(dialog, "isModal", None)
    if callable(is_modal):
        try:
            modal = bool(is_modal())
        except Exception:
            modal = True
    if modal and parent is not None and parent.width() > 0:
        # A modal should never be wider than its host window. Independent
        # tool windows may sit beside the Analyzer and use the screen.
        max_w = min(max_w, parent.width() - 24)

    max_w = max(min_w, max_w)
    max_h = max(min_h, max_h)
    dialog.resize(max_w, max_h)
