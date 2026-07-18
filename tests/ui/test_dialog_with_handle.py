"""``ChartOptionsDialog`` constructor accepts pyqtgraph ``AxisHandle``s."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtWidgets import QFrame, QGroupBox, QLabel, QPushButton


def _pg_handle_with_curve(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    t = np.linspace(1.0, 3.0, 80)
    canvas.plot_channels([
        ("curve", True, t, 1.0 + np.sin(t), "#1769e0", "rpm")
    ], mode="subplot")
    handle = canvas.axes_list[0]
    handle.set_title("原始标题")
    handle.set_xlabel("时间")
    handle.set_ylabel("幅值")
    handle.set_xlim(1.0, 3.0)
    handle.set_ylim(1.0, 10.0)
    QCoreApplication.processEvents()
    return canvas, handle


# ---------------------------------------------------------------------------
# Constructor accepts an existing AxisHandle
# ---------------------------------------------------------------------------


def test_dialog_accepts_axis_handle_constructor(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)

    dlg = ChartOptionsDialog(None, handle)
    assert dlg.handle is handle
    assert dlg.edit_title.text() == "原始标题"
    assert dlg.spin_x_min.value() == pytest.approx(1.0)
    assert dlg.spin_x_max.value() == pytest.approx(3.0)


def test_dialog_rejects_raw_pyqtgraph_plot_item(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    import pyqtgraph as pg

    with pytest.raises(TypeError, match="unsupported axis object: PlotItem"):
        ChartOptionsDialog(None, pg.PlotItem())


# ---------------------------------------------------------------------------
# Apply / Reset / Log-scale toggle
# ---------------------------------------------------------------------------


def test_dialog_apply_changes_round_trips_via_handle(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    dlg.edit_title.setText("新标题")
    dlg.chk_x_auto.setChecked(False)
    dlg.spin_x_min.setValue(0.5)
    dlg.spin_x_max.setValue(5.0)
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(0.1)
    dlg.spin_y_max.setValue(20.0)
    dlg.edit_x_label.setText("时间轴")
    dlg.edit_y_label.setText("输出")

    dlg.apply_changes()

    assert "新标题" in handle.get_title()
    assert handle.get_xlim() == pytest.approx((0.5, 5.0))
    assert handle.get_ylim() == pytest.approx((0.1, 20.0))
    assert "时间轴" in handle.get_xlabel()
    assert "输出" in handle.get_ylabel()


def test_dialog_reset_restores_opening_values(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    dlg.edit_title.setText("临时标题")
    dlg.spin_x_min.setValue(-99.0)
    dlg.reset_fields()

    assert dlg.edit_title.text() == "原始标题"
    assert dlg.spin_x_min.value() == pytest.approx(1.0)


def test_dialog_log_scale_toggle_applies_via_handle(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    dlg.combo_y_scale.setCurrentText("对数")
    dlg.apply_changes()

    assert handle.get_yscale() == "log"
    assert handle.get_xscale() == "linear"


def test_dialog_log_scale_with_non_positive_range_falls_back_to_autoscale(
    qapp, monkeypatch,
):
    from mf4_analyzer.ui import dialogs as dlg_mod
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    dlg.combo_y_scale.setCurrentText("对数")
    dlg.spin_y_min.setValue(-1.0)
    dlg.spin_y_max.setValue(10.0)

    warning_calls: list[tuple] = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warning_calls.append(args)),
    )

    dlg.apply_changes()

    assert "y" in dlg._invalid_axes
    assert dlg.was_applied() is False
    assert len(warning_calls) == 1
    assert handle.is_autorange("y") is True


def test_grid_apply_skipped_when_checkbox_unchanged(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    calls = []
    handle.grid = lambda enabled: calls.append(enabled)

    dlg.apply_changes()

    assert calls == []


def test_grid_apply_runs_when_checkbox_changed(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    calls = []
    handle.grid = lambda enabled: calls.append(enabled)

    dlg.chk_grid.setChecked(not dlg._initial["grid"])
    dlg.apply_changes()

    assert calls == [not dlg._initial["grid"]]


def test_dialog_disables_cmap_combo_without_heatmap(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    assert hasattr(dlg, "combo_cmap")
    assert not dlg.combo_cmap.isEnabled()
    assert hasattr(dlg, "spin_color_min")
    assert hasattr(dlg, "spin_color_max")
    assert hasattr(dlg, "chk_color_auto")


# ---------------------------------------------------------------------------
# Layout-snapshot: visible widget tree byte-identical pre/post refactor
# ---------------------------------------------------------------------------


def _snapshot_widget_text(dlg) -> dict:
    """Capture every user-visible string the dialog renders."""
    labels = sorted(w.text() for w in dlg.findChildren(QLabel))
    buttons = sorted(w.text() for w in dlg.findChildren(QPushButton))
    groupboxes = sorted(w.title() for w in dlg.findChildren(QGroupBox))
    frames = sorted(
        w.objectName() for w in dlg.findChildren(QFrame) if w.objectName()
    )
    return {
        "labels": labels,
        "buttons": buttons,
        "groupboxes": groupboxes,
        "frames": frames,
        "window_title": dlg.windowTitle(),
        "object_name": dlg.objectName(),
    }


EXPECTED_SNAPSHOT = {
    "labels": sorted([
        "图表选项",
        "目标：原始标题",
        "基础信息",
        "X 轴",
        "Y 轴",
        "曲线",
        "色图与色阶",
        "图例",
        "标题",
        "最小值", "最大值", "标签", "刻度",
        "最小值", "最大值", "标签", "刻度",
        "对象", "颜色",
        "色图", "最小值", "最大值",
    ]),
    "buttons": sorted([
        "重置", "取消", "应用", "确定", "选择",
    ]),
    "groupboxes": [],
    "frames": sorted([
        "chartOptionsTitle", "chartOptionsSubtitle",
        "chartOptionsGroup", "chartOptionsGroup", "chartOptionsGroup",
        "chartOptionsGroup", "chartOptionsGroup", "chartOptionsGroup",
        "chartOptionsScroll", "chartOptionsScroll", "chartOptionsScroll",
        "chartOptionsGroupTitle", "chartOptionsGroupTitle",
        "chartOptionsGroupTitle", "chartOptionsGroupTitle",
        "chartOptionsGroupTitle", "chartOptionsGroupTitle",
        "qt_tabwidget_stackedwidget",
    ]),
    "window_title": "图表选项",
    "object_name": "ChartOptionsDialog",
}


def test_dialog_layout_snapshot_is_byte_identical_for_handle(qapp):
    """Pin labels/buttons/object names so Task 5 cannot alter the UI."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)
    snap = _snapshot_widget_text(dlg)

    assert snap == EXPECTED_SNAPSHOT


def test_dialog_layout_snapshot_matches_for_fresh_handle(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)
    snap = _snapshot_widget_text(dlg)

    assert snap == EXPECTED_SNAPSHOT
