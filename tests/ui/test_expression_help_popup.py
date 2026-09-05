# tests/ui/test_expression_help_popup.py
"""Pinnable, draggable 表达式帮助 card behind the ? badge."""
import numpy as np
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QLabel


def _make_files(tmp_path):
    import pandas as pd
    from mf4_analyzer.io.file_data import FileData
    df = pd.DataFrame({"time": np.arange(20) / 100.0,
                       "rpm": np.arange(20.0),
                       "trq": np.arange(20.0) * 2})
    return {"f0": FileData(str(tmp_path / "demo.mf4"), df, list(df.columns), {}, 0)}


def _editor(tmp_path):
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    dlg = ChannelEditorDialog(None, _make_files(tmp_path), "f0")
    dlg.combo_op2.setCurrentIndex(dlg.CUSTOM_OP_INDEX)
    return dlg


def test_badge_click_opens_card_and_second_click_closes(qapp, tmp_path):
    dlg = _editor(tmp_path)
    assert dlg._expr_help_popup is None          # built lazily on first use
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    assert popup is not None and popup.isVisible()
    assert dlg.btn_expr_help.isChecked()
    dlg.btn_expr_help.click()
    assert not popup.isVisible()
    assert not dlg.btn_expr_help.isChecked()


def test_card_close_button_unchecks_the_badge(qapp, tmp_path):
    dlg = _editor(tmp_path)
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    popup._close_btn.click()
    assert not popup.isVisible()
    assert not dlg.btn_expr_help.isChecked()


def test_escape_closes_the_card(qapp, tmp_path):
    from PyQt5.QtGui import QKeyEvent
    dlg = _editor(tmp_path)
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    popup.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not popup.isVisible()
    assert not dlg.btn_expr_help.isChecked()


def test_card_stays_open_while_typing_the_formula(qapp, tmp_path):
    # The whole point of pinning: focus moving to the input must NOT dismiss it.
    dlg = _editor(tmp_path)
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    dlg.edit_expr.setFocus()
    dlg.edit_expr.setText("sqrt(A^2 + B^2)")
    qapp.processEvents()
    assert popup.isVisible()


def test_header_drag_moves_the_card(qapp, tmp_path):
    dlg = _editor(tmp_path)
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    popup.move(300, 300)
    start = popup.pos()
    grab = QPoint(40, 12)                       # inside the header strip
    global_start = popup.mapToGlobal(grab)
    popup.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, grab, global_start,
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    popup.mouseMoveEvent(QMouseEvent(
        QEvent.MouseMove, grab, global_start + QPoint(120, 60),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    popup.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, grab, global_start + QPoint(120, 60),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    assert popup.pos() - start == QPoint(120, 60)
    assert popup._drag_offset is None           # released


def test_drag_ignores_the_close_button_area(qapp, tmp_path):
    dlg = _editor(tmp_path)
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    popup.show()
    qapp.processEvents()
    close_center = popup._close_btn.mapTo(
        popup, popup._close_btn.rect().center())
    popup.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, close_center, popup.mapToGlobal(close_center),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert popup._drag_offset is None           # ✕ click must not start a drag


def test_switching_away_from_custom_op_closes_the_card(qapp, tmp_path):
    dlg = _editor(tmp_path)
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    dlg.combo_op2.setCurrentIndex(0)            # back to A + B
    assert not popup.isVisible()
    assert not dlg.btn_expr_help.isChecked()


def test_hiding_the_editor_hides_the_card(qapp, tmp_path):
    dlg = _editor(tmp_path)
    dlg.show()
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    dlg.hide()
    assert not popup.isVisible()


def test_card_is_a_child_window_of_the_editor(qapp, tmp_path):
    # Parentage is what keeps the card usable under the drawer's application
    # modality — Qt exempts a modal window's own child windows.
    dlg = _editor(tmp_path)
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    assert popup.parent() is dlg
    assert popup.windowFlags() & Qt.FramelessWindowHint


def test_card_content_matches_the_tooltip_reference(qapp, tmp_path):
    from mf4_analyzer.ui import expression_help
    dlg = _editor(tmp_path)
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    texts = " ".join(lbl.text() for lbl in popup.findChildren(QLabel))
    for expr, what in expression_help.EXAMPLES:
        assert expr in texts and what in texts
    for label, funcs in expression_help.FUNCTION_GROUPS:
        assert label in texts and funcs.split()[0] in texts
    assert "pi" in texts


def test_tooltip_text_is_generated_from_the_same_data():
    from mf4_analyzer.ui import expression_help
    tip = expression_help.help_tooltip_text()
    for expr, _what in expression_help.EXAMPLES:
        assert expr in tip
    for _label, funcs in expression_help.FUNCTION_GROUPS:
        assert funcs.split()[0] in tip
    assert max(len(line) for line in tip.splitlines()) <= 52


def test_help_card_scrolls_and_keeps_close_on_compact_work_area(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from PyQt5.QtWidgets import QScrollArea
    from mf4_analyzer.ui_kit.dialog_geometry import FrameInsets, IntRect, SCREEN_MARGIN

    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 640, 360),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    dlg = _editor(tmp_path)
    qtbot.addWidget(dlg)
    dlg.show()
    dlg.btn_expr_help.click()
    popup = dlg._expr_help_popup
    assert popup is not None
    qtbot.waitExposed(popup)
    assert popup.height() <= 360 - 2 * SCREEN_MARGIN
    assert popup.findChildren(QScrollArea, "exprHelpScroll")
    assert popup._close_btn.isVisible()
    assert popup.rect().contains(popup._close_btn.geometry())
