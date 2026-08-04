# tests/ui/test_channel_editor_expression.py
"""自定义表达式 row of the 双通道运算 group."""
import numpy as np
import pytest
from PyQt5.QtWidgets import QMessageBox


def _make_files(tmp_path):
    import pandas as pd
    from mf4_analyzer.io.file_data import FileData
    df = pd.DataFrame({"time": np.arange(20) / 100.0,
                       "rpm": np.arange(20.0),
                       "trq": np.arange(20.0) * 2})
    fd = FileData(str(tmp_path / "demo.mf4"), df, list(df.columns),
                  {"rpm": "rpm", "trq": "Nm"}, 0)
    return {"f0": fd}


def _editor(tmp_path):
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    dlg = ChannelEditorDialog(None, _make_files(tmp_path), "f0")
    dlg.combo_a.setCurrentIndex(dlg.combo_a.findText("rpm"))
    dlg.combo_b.setCurrentIndex(dlg.combo_b.findText("trq"))
    return dlg


def _select_custom(dlg):
    dlg.combo_op2.setCurrentIndex(dlg.CUSTOM_OP_INDEX)
    return dlg


def test_custom_op_is_last_entry(qapp, tmp_path):
    dlg = _editor(tmp_path)
    items = [dlg.combo_op2.itemText(i) for i in range(dlg.combo_op2.count())]
    assert items[:6] == ["A + B", "A - B", "A × B", "A ÷ B", "max(A,B)", "min(A,B)"]
    assert items[dlg.CUSTOM_OP_INDEX] == "自定义表达式…"


def test_expression_row_hidden_until_custom_op_selected(qapp, tmp_path):
    dlg = _editor(tmp_path)
    for w in (dlg.lbl_expr, dlg.edit_expr, dlg.lbl_expr_help, dlg.lbl_expr_hint):
        assert w.isHidden()
    _select_custom(dlg)
    for w in (dlg.lbl_expr, dlg.edit_expr, dlg.lbl_expr_help, dlg.lbl_expr_hint):
        assert not w.isHidden()
    dlg.combo_op2.setCurrentIndex(0)
    assert dlg.edit_expr.isHidden() and dlg.lbl_expr_help.isHidden()


def test_help_badge_tooltip_documents_variables_functions_and_examples(qapp, tmp_path):
    dlg = _select_custom(_editor(tmp_path))
    tip = dlg.lbl_expr_help.toolTip()
    assert tip == dlg.edit_expr.toolTip()      # hovering either shows the same
    for token in ("A = 通道A", "B = 通道B", "t = 时间", "^", "sqrt", "mean",
                  "where", "pi", "sqrt(A^2 + B^2)"):
        assert token in tip
    # Hand-wrapped for the glass tooltip: no line may sprawl.
    assert max(len(line) for line in tip.splitlines()) <= 52


def test_creates_channel_from_expression_with_parens_coeff_and_sqrt(qapp, tmp_path):
    dlg = _select_custom(_editor(tmp_path))
    dlg.edit_expr.setText("sqrt(A^2 + B^2) * 0.5")
    dlg.edit_name2.setText("mag")
    dlg._create_dual()
    assert "mag" in dlg.new_channels
    values, unit = dlg.new_channels["mag"]
    rpm = np.arange(20.0)
    assert np.allclose(values, np.sqrt(rpm ** 2 + (2 * rpm) ** 2) * 0.5)
    assert unit == ""          # a free-form formula has no derivable unit
    # the new channel is immediately reusable as a source
    assert dlg.combo_src.findText("mag") >= 0
    assert dlg.combo_a.findText("mag") >= 0


def test_auto_name_derived_from_expression(qapp, tmp_path):
    dlg = _select_custom(_editor(tmp_path))
    dlg.edit_expr.setText("(A - B) / 2")
    dlg._create_dual()
    assert list(dlg.new_channels) == ["expr_A_B_2"]


def test_expression_can_reference_time(qapp, tmp_path):
    dlg = _select_custom(_editor(tmp_path))
    dlg.edit_expr.setText("A * t")
    dlg._create_dual()
    values = dlg.new_channels["expr_A_t"][0]
    assert np.allclose(values, np.arange(20.0) * (np.arange(20) / 100.0))


def test_expression_can_use_channel_created_earlier(qapp, tmp_path):
    dlg = _select_custom(_editor(tmp_path))
    dlg.edit_expr.setText("A + 1")
    dlg.edit_name2.setText("shifted")
    dlg._create_dual()
    dlg.combo_a.setCurrentIndex(dlg.combo_a.findText("shifted"))
    dlg.edit_expr.setText("A * 2")
    dlg.edit_name2.setText("doubled")
    dlg._create_dual()
    assert np.allclose(dlg.new_channels["doubled"][0], (np.arange(20.0) + 1) * 2)


def test_duplicate_name_is_suffixed(qapp, tmp_path):
    dlg = _select_custom(_editor(tmp_path))
    dlg.edit_expr.setText("A * 2")
    dlg.edit_name2.setText("rpm")     # collides with an existing column
    dlg._create_dual()
    assert "rpm_1" in dlg.new_channels


def test_scalar_expression_fills_whole_channel(qapp, tmp_path):
    dlg = _select_custom(_editor(tmp_path))
    dlg.edit_expr.setText("mean(A)")
    dlg.edit_name2.setText("bias")
    dlg._create_dual()
    assert np.allclose(dlg.new_channels["bias"][0], np.full(20, np.mean(np.arange(20.0))))


@pytest.mark.parametrize(("expr", "match"), [
    ("", "表达式"),
    ("A +", "语法"),
    ("foo(A)", "函数"),
    ("nope * 2", "未知变量"),
    ("A[0]", "语法"),
])
def test_bad_expression_warns_and_creates_nothing(qapp, tmp_path, monkeypatch, expr, match):
    dlg = _select_custom(_editor(tmp_path))
    seen = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda parent, title, text, *a, **k: seen.append(text))
    dlg.edit_expr.setText(expr)
    dlg._create_dual()
    assert dlg.new_channels == {}
    assert seen and match in seen[0]


def test_all_nan_result_is_refused(qapp, tmp_path, monkeypatch):
    dlg = _select_custom(_editor(tmp_path))
    seen = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda parent, title, text, *a, **k: seen.append(text))
    dlg.edit_expr.setText("sqrt(-1 + 0*A)")
    dlg._create_dual()
    assert dlg.new_channels == {}
    assert seen and "NaN" in seen[0]


def test_expression_only_needing_A_ignores_B_length(qapp, tmp_path, monkeypatch):
    # A shorter staged channel selected as B must not block an A-only formula.
    dlg = _select_custom(_editor(tmp_path))
    dlg.new_channels["short"] = (np.zeros(3), "")
    dlg.combo_b.addItem("short")
    dlg.combo_b.setCurrentIndex(dlg.combo_b.findText("short"))
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: pytest.fail("A-only expression must not warn"))
    dlg.edit_expr.setText("A * 3")
    dlg.edit_name2.setText("tripled")
    dlg._create_dual()
    assert np.allclose(dlg.new_channels["tripled"][0], np.arange(20.0) * 3)


def test_builtin_ops_still_work_after_refactor(qapp, tmp_path):
    dlg = _editor(tmp_path)
    dlg.combo_op2.setCurrentIndex(0)      # A + B
    dlg._create_dual()
    name = "add_rpm_trq"
    assert name in dlg.new_channels
    assert np.allclose(dlg.new_channels[name][0], np.arange(20.0) * 3)
