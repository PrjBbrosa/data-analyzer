import threading

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.ui.dialogs.channel_editor import ChannelEditorDialog


@pytest.fixture
def editor(qtbot, tmp_path):
    parent = QWidget()
    qtbot.addWidget(parent)
    df = pd.DataFrame({"time": np.arange(20) / 100., "a": np.arange(20.), "b": np.arange(20.) * 2})
    files = {key: FileData(str(tmp_path / (key + ".mf4")), df.copy(), list(df.columns), {}, 0)
             for key in ("one", "two")}
    dialog = ChannelEditorDialog(parent, files, "one")
    dialog.combo_op2.setCurrentIndex(dialog.CUSTOM_OP_INDEX)
    dialog.combo_a.setCurrentText("a")
    dialog.combo_b.setCurrentText("b")
    dialog.edit_expr.setText("A + B")
    yield dialog
    dialog.hide()


def test_check_does_not_register_and_click_toggles_tip(editor):
    editor.btn_expr_check.click()
    assert editor.new_channels == {}
    assert editor.edit_expr.property("checkState") == "ok"
    assert editor._expr_check_tip.isVisible()
    editor.btn_expr_check.click()
    assert not editor._expr_check_tip.isVisible()
    editor.btn_expr_check.click()
    assert editor._expr_check_tip.isVisible()


@pytest.mark.parametrize("expr,state,can_create", [
    ("A +", "error", False), ("A + C", "error", False),
    ("A / B", "error", True), ("sqrt(-1 + 0*A)", "error", False),
    ("mean(A)", "ok", True), ("", "error", False),
])
def test_check_feedback_and_creation_policy(editor, expr, state, can_create):
    editor.edit_expr.setText(expr)
    editor.btn_expr_check.click()
    assert editor.edit_expr.property("checkState") == state
    assert editor.btn_create_dual.isEnabled() == can_create
    assert editor.new_channels == {}
    if can_create:
        editor.btn_create_dual.click()
        assert len(editor.new_channels) == 1


def test_modification_invalidates_but_name_does_not(editor):
    editor.btn_expr_check.click()
    editor.edit_name2.setText("named")
    assert editor.edit_expr.property("checkState") == "ok"
    editor.edit_expr.setText("A * 2")
    assert editor.edit_expr.property("checkState") == ""
    assert not editor._expr_check_tip.isVisible()
    editor.btn_expr_check.click()
    editor.combo_b.setCurrentText("a")
    assert editor.edit_expr.property("checkState") == ""
    editor.btn_expr_check.click()
    editor.combo_file.setCurrentIndex(1)
    assert editor.edit_expr.property("checkState") == ""


def test_creation_rechecks_mutated_source_even_after_green_check(editor):
    editor.edit_expr.setText("A")
    editor.btn_expr_check.click()
    editor.fd.data.loc[:, "a"] = 91.
    editor.btn_create_dual.click()
    np.testing.assert_array_equal(next(iter(editor.new_channels.values()))[0], np.full(20, 91.))


def test_A_only_and_removed_source(editor):
    editor.new_channels["short"] = (np.zeros(2), "")
    editor.combo_b.addItem("short")
    editor.combo_b.setCurrentText("short")
    editor.edit_expr.setText("A")
    editor.btn_expr_check.click()
    assert editor.edit_expr.property("checkState") == "ok"
    editor.edit_expr.setText("A+B")
    editor.btn_expr_check.click()
    assert "长度" in editor.btn_expr_check.toolTip()
    editor.removed_channels.add("a")
    editor.edit_expr.setText("A")
    editor.btn_expr_check.click()
    assert "不存在" in editor.btn_expr_check.toolTip()


def test_popup_shell_and_escape(editor, qtbot):
    editor.btn_expr_check.click()
    tip = editor._expr_check_tip
    assert tip.parent() is editor
    assert tip.testAttribute(Qt.WA_TranslucentBackground)
    assert tip.windowFlags() & Qt.FramelessWindowHint
    qtbot.keyClick(editor.edit_expr, Qt.Key_Escape)
    assert not tip.isVisible()


def test_stale_background_create_cannot_publish(editor, qtbot, monkeypatch):
    from mf4_analyzer.ui.dialogs import _expression_check as jobs
    started, release = threading.Event(), threading.Event()
    evaluate = jobs.check_channel_expression

    def blocked(*args):
        started.set()
        assert release.wait(3)
        return evaluate(*args)

    monkeypatch.setattr(jobs.ExpressionCheckRunner, "INLINE_SAMPLES", 0)
    monkeypatch.setattr(jobs, "check_channel_expression", blocked)
    editor.btn_create_dual.click()
    qtbot.waitUntil(started.is_set)
    editor.edit_expr.setText("A * 2")
    release.set()
    qtbot.waitUntil(lambda: editor._expr_check_runner._job is None)
    assert editor.new_channels == {}
    assert editor.edit_expr.property("checkState") == ""
    editor.btn_expr_check.click()
    qtbot.waitUntil(lambda: editor.edit_expr.property("checkState") == "ok")


def test_hide_invalidates_background_result(editor, qtbot, monkeypatch):
    from mf4_analyzer.ui.dialogs import _expression_check as jobs
    monkeypatch.setattr(jobs.ExpressionCheckRunner, "INLINE_SAMPLES", 0)
    editor.show()
    editor.btn_create_dual.click()
    editor.hide()
    qtbot.waitUntil(lambda: editor._expr_check_runner._job is None)
    assert editor.new_channels == {}
    assert editor.edit_expr.property("checkState") == ""


def test_rendered_input_colors_tip_corners_and_narrow_geometry(editor, qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    old_sheet = qapp.styleSheet()
    try:
        load_stylesheet(qapp)
        editor.resize(336, 900)
        editor.show()
        qapp.processEvents()
        assert editor.width() == 336
        assert (editor.btn_expr_check.width(), editor.btn_expr_check.height()) == (28, 28)
        assert editor.edit_expr.width() >= 100
        for expr, color in (("A + B", "#248653"), ("A +", "#ca414b")):
            editor.edit_expr.setText(expr)
            editor.btn_expr_check.click()
            qapp.processEvents()
            image = editor.edit_expr.grab().toImage()
            assert image.pixelColor(image.width() // 2, 0).name() == color
            tip = editor._expr_check_tip
            image = tip.grab().toImage()
            assert image.pixelColor(0, 0).alpha() == 0
            assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() == 255
            assert tip.height() < 85
        group = editor._expr_row.parentWidget()
        assert editor.combo_a.mapTo(group, editor.combo_a.rect().topRight()).x() == editor._expr_row.mapTo(group, editor._expr_row.rect().topRight()).x()
    finally:
        editor.hide()
        qapp.setStyleSheet(old_sheet)


def test_runner_coalesces_pending_requests(editor, qtbot, monkeypatch):
    from mf4_analyzer.ui.dialogs import _expression_check as jobs
    started, release = threading.Event(), threading.Event()
    expressions, finished = [], []
    evaluate = jobs.check_channel_expression

    def blocked(expr, *args):
        expressions.append(expr)
        if expr == "A+1":
            started.set()
            assert release.wait(3)
        return evaluate(expr, *args)

    def receive(token, result, error):
        finished.append((token, result, error))

    monkeypatch.setattr(jobs.ExpressionCheckRunner, "INLINE_SAMPLES", 0)
    monkeypatch.setattr(jobs, "check_channel_expression", blocked)
    runner = jobs.ExpressionCheckRunner(editor)
    runner.completed.connect(receive)
    runner.submit(1, "A+1", np.arange(2.), {"A": np.ones(2)})
    try:
        qtbot.waitUntil(started.is_set)
        runner.submit(2, "A+2", np.arange(2.), {"A": np.ones(2)})
        runner.submit(3, "A+3", np.arange(2.), {"A": np.ones(2)})
    finally:
        release.set()
    qtbot.waitUntil(lambda: len(finished) == 1)
    assert expressions == ["A+1", "A+3"]
    assert finished[0][0] == 3 and finished[0][2] is None
