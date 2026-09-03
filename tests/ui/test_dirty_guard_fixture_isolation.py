"""The suite-level dirty-close decision must outlive a test's monkeypatch undo."""

from __future__ import annotations

import time

from PyQt5.QtCore import QTimer

from mf4_analyzer.ui.main_window import MainWindow


def test_dirty_guard_discard_patch_survives_monkeypatch_undo(qapp, qtbot, monkeypatch):
    """A shown dirty window must still close promptly after ``monkeypatch.undo()``.

    The 2 s callback prevents a regression from leaving an offscreen modal
    event loop behind; it is a no-op after the synchronous close returns.
    """
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qapp.processEvents()
    window._project_dirty.mark_user_mutation()

    close_returned = False

    def _quit_if_close_is_still_blocked():
        if not close_returned:
            qapp.quit()

    QTimer.singleShot(2000, _quit_if_close_is_still_blocked)
    monkeypatch.undo()
    started = time.monotonic()
    window.close()
    close_returned = True

    assert time.monotonic() - started <= 0.5
    assert not window.isVisible()
