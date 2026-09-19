"""Offscreen QDialog.exec_() must fail fast instead of hanging the session."""


def test_unstubbed_qdialog_exec_fails_instead_of_hanging(qapp, qtbot):
    from PyQt5.QtWidgets import QDialog

    dialog = QDialog()
    qtbot.addWidget(dialog)
    try:
        dialog.exec_()
    except RuntimeError as exc:
        assert "QDialog.exec_() blocked" in str(exc)
        assert "test_unstubbed_qdialog_exec_fails_instead_of_hanging" in str(exc)
    else:
        raise AssertionError("unstubbed exec_() must raise instead of hanging")


def test_unstubbed_qmenu_exec_fails_before_entering_its_event_loop(qapp, qtbot):
    from PyQt5.QtWidgets import QMenu

    menu = QMenu()
    qtbot.addWidget(menu)
    try:
        menu.exec_()
    except RuntimeError as exc:
        assert "QMenu.exec() attempted" in str(exc)
        assert "test_unstubbed_qmenu_exec_fails_before_entering_its_event_loop" in str(exc)
    else:
        raise AssertionError("unstubbed QMenu.exec_() must fail before blocking")


def test_unstubbed_native_static_modal_fails_before_constructing_a_dialog(qapp):
    from PyQt5.QtWidgets import QFileDialog

    try:
        QFileDialog.getOpenFileName()
    except RuntimeError as exc:
        assert "QFileDialog.getOpenFileName() attempted" in str(exc)
        assert "test_unstubbed_native_static_modal_fails_before_constructing_a_dialog" in str(exc)
    else:
        raise AssertionError("unstubbed native static helper must fail immediately")


def test_early_exec_return_cancels_its_timeout_before_reusing_dialog(qapp, qtbot):
    """A completed invocation must never let its old timer close the next one."""
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QDialog

    dialog = QDialog()
    qtbot.addWidget(dialog)

    QTimer.singleShot(0, dialog.accept)
    assert dialog.exec_() == QDialog.Accepted

    # Let another normal event-loop turn happen before the same dialog is
    # reused.  The old 800 ms callback is now 500 ms away, earlier than the
    # intentional acceptance below, which makes a leaked callback observable
    # without waiting for the guard's own timeout.
    qtbot.wait(300)
    QTimer.singleShot(650, dialog.accept)
    assert dialog.exec_() == QDialog.Accepted
