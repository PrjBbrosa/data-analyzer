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
