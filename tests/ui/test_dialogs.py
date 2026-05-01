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
