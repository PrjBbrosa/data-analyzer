import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from matplotlib.figure import Figure
import numpy as np


def _axes():
    fig = Figure(figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([1, 2, 3], [1, 4, 9], label="曲线1")
    ax.set_title("原始标题")
    ax.set_xlabel("时间 (s)")
    ax.set_ylabel("幅值")
    ax.set_xlim(1.0, 3.0)
    ax.set_ylim(1.0, 10.0)
    return ax


def test_chart_options_dialog_uses_chinese_labels_and_reads_axes(qapp):
    from PyQt5.QtWidgets import QLabel
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes()
    ax.set_yscale("log")

    dlg = ChartOptionsDialog(None, ax)

    assert dlg.objectName() == "ChartOptionsDialog"
    assert dlg.windowTitle() == "图表选项"
    labels = {label.text() for label in dlg.findChildren(QLabel)}
    for text in ("基础信息", "X 轴", "Y 轴", "图例", "标题", "最小值", "最大值", "标签", "刻度"):
        assert text in labels
    assert dlg.edit_title.text() == "原始标题"
    assert dlg.edit_x_label.text() == "时间 (s)"
    assert dlg.edit_y_label.text() == "幅值"
    assert dlg.spin_x_min.value() == pytest.approx(1.0)
    assert dlg.spin_x_max.value() == pytest.approx(3.0)
    assert dlg.combo_x_scale.currentText() == "线性"
    assert dlg.combo_y_scale.currentText() == "对数"


def test_chart_options_dialog_applies_axis_values_and_legend(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes()
    dlg = ChartOptionsDialog(None, ax)

    dlg.edit_title.setText("新标题")
    dlg.spin_x_min.setValue(1.0)
    dlg.spin_x_max.setValue(4.0)
    dlg.edit_x_label.setText("时间轴")
    dlg.combo_x_scale.setCurrentText("线性")
    dlg.spin_y_min.setValue(1.0)
    dlg.spin_y_max.setValue(100.0)
    dlg.edit_y_label.setText("输出")
    dlg.combo_y_scale.setCurrentText("对数")
    dlg.chk_grid.setChecked(False)
    dlg.chk_legend.setChecked(True)

    dlg.apply_changes()

    assert ax.get_title() == "新标题"
    assert ax.get_xlim() == pytest.approx((1.0, 4.0))
    assert ax.get_xlabel() == "时间轴"
    assert ax.get_xscale() == "linear"
    assert ax.get_ylim() == pytest.approx((1.0, 100.0))
    assert ax.get_ylabel() == "输出"
    assert ax.get_yscale() == "log"
    assert ax.get_legend() is not None


def test_chart_options_dialog_reset_restores_opening_values(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes()
    dlg = ChartOptionsDialog(None, ax)

    dlg.edit_title.setText("临时标题")
    dlg.spin_x_min.setValue(-99.0)
    dlg.edit_y_label.setText("临时标签")

    dlg.reset_fields()

    assert dlg.edit_title.text() == "原始标题"
    assert dlg.spin_x_min.value() == pytest.approx(1.0)
    assert dlg.edit_y_label.text() == "幅值"


def test_chart_options_dialog_auto_range_disables_manual_fields(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes()
    dlg = ChartOptionsDialog(None, ax)

    dlg.chk_x_auto.setChecked(True)
    assert not dlg.spin_x_min.isEnabled()
    assert not dlg.spin_x_max.isEnabled()
    dlg.chk_x_auto.setChecked(False)
    assert dlg.spin_x_min.isEnabled()
    assert dlg.spin_x_max.isEnabled()

    dlg.chk_y_auto.setChecked(True)
    assert not dlg.spin_y_min.isEnabled()
    assert not dlg.spin_y_max.isEnabled()


def test_chart_options_dialog_applies_curve_color(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes()
    dlg = ChartOptionsDialog(None, ax)

    assert dlg.tabs.tabText(1) == "图形"
    assert dlg.combo_curve.count() == 1

    dlg.edit_curve_color.setText("#123456")
    dlg.apply_changes()

    assert ax.lines[0].get_color().lower() == "#123456"


def test_chart_options_dialog_applies_heatmap_cmap_and_range(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    fig = Figure(figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)
    im = ax.imshow(np.arange(9, dtype=float).reshape(3, 3), cmap="viridis")

    dlg = ChartOptionsDialog(None, ax)

    assert dlg.combo_cmap.currentText() == "viridis"
    dlg.combo_cmap.setCurrentText("turbo")
    dlg.chk_color_auto.setChecked(False)
    dlg.spin_color_min.setValue(1.0)
    dlg.spin_color_max.setValue(5.0)
    assert dlg.spin_color_min.isEnabled()
    assert dlg.spin_color_max.isEnabled()

    dlg.apply_changes()

    assert im.get_cmap().name == "turbo"
    assert im.get_clim() == pytest.approx((1.0, 5.0))

    dlg.chk_color_auto.setChecked(True)
    assert not dlg.spin_color_min.isEnabled()
    assert not dlg.spin_color_max.isEnabled()


def test_chart_options_log_axis_rejects_non_positive(qapp):
    """Log scale + non-positive vmin/vmax must skip set_ylim and record axis."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes()
    dlg = ChartOptionsDialog(None, ax)

    set_ylim_calls = []
    set_yscale_calls = []

    original_set_ylim = dlg.ax.set_ylim
    original_set_yscale = dlg.ax.set_yscale

    def record_set_ylim(*args, **kwargs):
        set_ylim_calls.append((args, kwargs))
        return original_set_ylim(*args, **kwargs)

    def record_set_yscale(*args, **kwargs):
        set_yscale_calls.append((args, kwargs))
        return original_set_yscale(*args, **kwargs)

    dlg.ax.set_ylim = record_set_ylim
    dlg.ax.set_yscale = record_set_yscale

    dlg._apply_axis(
        axis="y",
        auto=False,
        vmin=-1,
        vmax=10,
        label="Y",
        scale_text="对数",
    )

    # set_yscale('log') was called, set_ylim was NOT called for the bad range
    assert any(args and args[0] == "log" for args, _ in set_yscale_calls), \
        f"set_yscale('log') not called: {set_yscale_calls}"
    assert set_ylim_calls == [], (
        f"set_ylim should not be called when log + non-positive range, "
        f"got {set_ylim_calls}"
    )
    assert "y" in dlg._invalid_axes


def test_chart_options_log_axis_warning_blocks_close(qapp, monkeypatch):
    """Apply with log + non-positive range pops a warning and does not accept."""
    from PyQt5.QtWidgets import QDialog, QMessageBox
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes()
    dlg = ChartOptionsDialog(None, ax)

    # Configure: Y log + manual range with vmin=-1
    dlg.combo_y_scale.setCurrentText("对数")
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(-1.0)
    dlg.spin_y_max.setValue(10.0)

    warning_calls = []

    def fake_warning(parent, title, text, *args, **kwargs):
        warning_calls.append({"parent": parent, "title": title, "text": text})
        return QMessageBox.Ok

    monkeypatch.setattr(
        "mf4_analyzer.ui.dialogs.QMessageBox.warning",
        staticmethod(fake_warning),
    )

    # Drive the OK-button slot directly (avoid exec_() under offscreen)
    dlg._accept_with_apply()

    assert len(warning_calls) == 1, (
        f"QMessageBox.warning should fire exactly once, got {warning_calls}"
    )
    assert warning_calls[0]["parent"] is dlg, "warning parent must be the dialog"
    # Dialog did not accept -- result code is not Accepted
    assert dlg.result() != QDialog.Accepted, (
        f"dialog must not be accepted on invalid log range, "
        f"got result={dlg.result()}"
    )
    assert "y" in dlg._invalid_axes


def test_chart_options_log_axis_positive_range_applies(qapp, monkeypatch):
    """Log + positive vmin/vmax applies set_ylim and clears _invalid_axes."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes()
    dlg = ChartOptionsDialog(None, ax)

    set_ylim_calls = []
    original_set_ylim = dlg.ax.set_ylim

    def record_set_ylim(*args, **kwargs):
        set_ylim_calls.append((args, kwargs))
        return original_set_ylim(*args, **kwargs)

    dlg.ax.set_ylim = record_set_ylim

    dlg.combo_y_scale.setCurrentText("对数")
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(0.1)
    dlg.spin_y_max.setValue(10.0)

    # Use the public apply slot so reset of _invalid_axes is exercised
    dlg.apply_changes()

    assert any(
        args and args[0] == pytest.approx(0.1) and args[1] == pytest.approx(10.0)
        for args, _ in set_ylim_calls
    ), f"set_ylim(0.1, 10.0) not called, got {set_ylim_calls}"
    assert dlg._invalid_axes == []
    assert dlg.was_applied() is True


def test_chart_options_log_axis_positive_range_ok_button_accepts(qapp, monkeypatch):
    """Log + positive range via OK-button path: dialog accepts, no warning fires."""
    from PyQt5.QtWidgets import QDialog
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes()
    dlg = ChartOptionsDialog(None, ax)

    # Configure: Y log + manual range with positive vmin/vmax (mirrors the
    # apply_changes happy-path test, but exercises _accept_with_apply instead).
    dlg.combo_y_scale.setCurrentText("对数")
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(0.1)
    dlg.spin_y_max.setValue(10.0)

    # Spy on QMessageBox.warning: must NOT be called on the happy path.
    warning_calls = []

    def fake_warning(parent, title, text, *args, **kwargs):
        warning_calls.append({"parent": parent, "title": title, "text": text})
        return 0  # any return; should not be reached

    monkeypatch.setattr(
        "mf4_analyzer.ui.dialogs.QMessageBox.warning",
        staticmethod(fake_warning),
    )

    # Spy on accept(): wrap the real method so semantics survive (result code
    # is set via done(Accepted)) while we can also assert it was invoked.
    accept_calls = []
    real_accept = dlg.accept

    def recording_accept():
        accept_calls.append(True)
        real_accept()

    dlg.accept = recording_accept

    # Drive the OK-button slot directly (avoid exec_() under offscreen).
    dlg._accept_with_apply()

    # No warning on the happy path.
    assert len(warning_calls) == 0, (
        f"QMessageBox.warning must not fire on valid log range, got {warning_calls}"
    )
    # apply_changes succeeded: no invalid axes recorded, was_applied flips True.
    assert dlg._invalid_axes == []
    assert dlg.was_applied() is True
    # accept() was invoked exactly once by _accept_with_apply.
    assert len(accept_calls) == 1, (
        f"dialog.accept() must be called exactly once, got {len(accept_calls)}"
    )
    # Result code is QDialog.Accepted (set by the underlying done(Accepted)).
    assert dlg.result() == QDialog.Accepted, (
        f"dialog must be accepted on valid log range, got result={dlg.result()}"
    )
