"""Pinnable 参数帮助 card behind the single-op parameter ? badge."""
from __future__ import annotations

import numpy as np
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent


def _make_files(tmp_path):
    import pandas as pd
    from mf4_analyzer.io.file_data import FileData

    df = pd.DataFrame({
        "time": np.arange(20) / 100.0,
        "rpm": np.arange(20.0),
    })
    return {"f0": FileData(str(tmp_path / "demo.mf4"), df, list(df.columns), {}, 0)}


def _editor(tmp_path):
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog

    return ChannelEditorDialog(None, _make_files(tmp_path), "f0")


def test_param_badge_opens_card_and_second_click_closes(qapp, tmp_path):
    from PyQt5.QtWidgets import QLabel

    dlg = _editor(tmp_path)
    assert dlg._param_help_popup is None
    dlg.btn_param_help.click()
    popup = dlg._param_help_popup
    assert popup is not None and popup.isVisible()
    assert dlg.btn_param_help.isChecked()
    titles = [
        w.text() for w in popup.findChildren(QLabel)
        if w.objectName() == "exprHelpTitle"
    ]
    assert titles == ["参数帮助"]
    dlg.btn_param_help.click()
    assert not popup.isVisible()
    assert not dlg.btn_param_help.isChecked()


def test_param_and_expr_help_are_mutually_exclusive(qapp, tmp_path):
    dlg = _editor(tmp_path)
    dlg.combo_op2.setCurrentIndex(dlg.CUSTOM_OP_INDEX)
    dlg.btn_param_help.click()
    assert dlg._param_help_popup.isVisible()
    dlg.btn_expr_help.click()
    assert dlg._expr_help_popup.isVisible()
    assert not dlg.btn_param_help.isChecked()
    assert not dlg._param_help_popup.isVisible()


def test_param_card_escape_closes(qapp, tmp_path):
    dlg = _editor(tmp_path)
    dlg.btn_param_help.click()
    popup = dlg._param_help_popup
    popup.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not popup.isVisible()
    assert not dlg.btn_param_help.isChecked()


def test_hiding_editor_hides_param_card(qapp, tmp_path):
    dlg = _editor(tmp_path)
    dlg.show()
    dlg.btn_param_help.click()
    popup = dlg._param_help_popup
    dlg.hide()
    assert not popup.isVisible()


def test_param_help_tooltip_mentions_window_length():
    from mf4_analyzer.ui.expression_help import param_help_tooltip_text

    tip = param_help_tooltip_text()
    assert "窗长" in tip
    assert "样点" in tip
    assert "滑动平均" in tip
