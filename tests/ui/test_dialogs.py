import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import numpy as np


def _pg_handle_with_one_curve(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    t = np.linspace(1.0, 3.0, 80)
    canvas.plot_channels([
        ("speed", True, t, 1.0 + np.sin(t), "#1769e0", "rpm")
    ], mode="subplot")
    handle = canvas.axes_list[0]
    handle.set_title("原始标题")
    handle.set_xlabel("时间 (s)")
    handle.set_ylabel("幅值")
    handle.set_xlim(1.0, 3.0)
    handle.set_ylim(1.0, 10.0)
    QCoreApplication.processEvents()
    return canvas, handle


def _pg_canvas_with_one_curve(qapp):
    canvas, _handle = _pg_handle_with_one_curve(qapp)
    return canvas


def _pg_heatmap_handle(qapp):
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        PgHeatmapCanvas,
        _HeatmapAxisHandle,
    )

    canvas = PgHeatmapCanvas(with_slice=False)
    canvas.plot_or_update_heatmap(
        np.arange(9, dtype=float).reshape(3, 3),
        (0.0, 2.0),
        (10.0, 30.0),
        x_label="Time (s)",
        y_label="Frequency (Hz)",
        cmap="viridis",
        amplitude_mode="amplitude",
        z_auto=False,
        z_floor=0.0,
        z_ceiling=8.0,
    )
    return canvas, _HeatmapAxisHandle(canvas)


def test_chart_options_dialog_uses_chinese_labels_and_reads_handle(qapp):
    from PyQt5.QtWidgets import QLabel
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    handle.set_yscale("log")

    dlg = ChartOptionsDialog(None, handle)

    assert dlg.objectName() == "ChartOptionsDialog"
    assert dlg.windowTitle() == "图表选项"
    labels = {label.text() for label in dlg.findChildren(QLabel)}
    for text in ("基础信息", "X 轴", "Y 轴", "标题", "最小值", "最大值", "标签", "刻度"):
        assert text in labels
    assert dlg.edit_title.text() == "原始标题"
    assert dlg.edit_x_label.text() == "时间 (s)"
    assert dlg.edit_y_label.text() == "幅值"
    assert dlg.spin_x_min.value() == pytest.approx(1.0)
    assert dlg.spin_x_max.value() == pytest.approx(3.0)
    assert dlg.combo_x_scale.currentText() == "线性"
    assert dlg.combo_y_scale.currentText() == "对数"


def test_chart_options_dialog_fits_available_height_and_keeps_actions_visible(qapp):
    from PyQt5.QtWidgets import QApplication, QScrollArea
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)
    dlg.show()
    qapp.processEvents()

    available = QApplication.primaryScreen().availableGeometry()
    assert dlg.height() <= available.height()
    assert len(dlg.findChildren(QScrollArea, "chartOptionsScroll")) == 2

    for button in (dlg.btn_reset, dlg.btn_cancel, dlg.btn_apply, dlg.btn_ok):
        assert dlg.rect().contains(button.mapTo(dlg, button.rect().topLeft()))
        assert dlg.rect().contains(button.mapTo(dlg, button.rect().bottomRight()))


def test_chart_options_compact_work_area_does_not_keep_430_floor(qapp, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QScrollArea
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui_kit.dialog_geometry import FrameInsets, IntRect, SCREEN_MARGIN

    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 640, 360),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)
    dlg.show()
    qapp.processEvents()
    assert dlg.width() <= 640 - 2 * SCREEN_MARGIN
    assert dlg.height() <= 360 - 2 * SCREEN_MARGIN
    assert len(dlg.findChildren(QScrollArea, "chartOptionsScroll")) == 2
    for button in (dlg.btn_reset, dlg.btn_cancel, dlg.btn_apply, dlg.btn_ok):
        assert dlg.rect().contains(button.mapTo(dlg, button.rect().bottomRight()))


def test_chart_options_tab_bar_does_not_paint_trailing_white_base(qapp):
    """Unused tab-bar strip must match dialog chrome, not a leftover white slab.

    Global ``QWidget { background:#ffffff }`` otherwise fills the QTabBar
    behind 图形 and past the last tab. Fusion + production QSS, then
    sample a pixel to the right of 「图形」.
    """
    from PyQt5.QtGui import QColor
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui_kit import load_stylesheet

    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)
    dlg.show()
    qapp.processEvents()

    bar = dlg.tabs.tabBar()
    assert not bar.drawBase()
    assert not bar.expanding()
    assert bar.count() == 2
    assert dlg.tabs.tabText(1) == "图形"

    last = bar.tabRect(1)
    sample = bar.mapTo(dlg, last.topRight())
    x = min(dlg.width() - 12, sample.x() + 18)
    y = sample.y() + max(2, last.height() // 2)
    assert x > sample.x() + 4

    color = QColor(dlg.grab().toImage().pixel(x, y))
    # Dialog chrome is #f5f7fb; a leftover QTabBar base is #ffffff.
    assert abs(color.red() - 245) <= 8, color.name()
    assert abs(color.green() - 247) <= 8, color.name()
    assert abs(color.blue() - 251) <= 8, color.name()


def test_chart_options_dialog_applies_axis_values_without_manual_legend(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)
    assert dlg.tabs.count() == 2
    assert not hasattr(dlg, "chk_legend")

    dlg.edit_title.setText("新标题")
    dlg.chk_x_auto.setChecked(False)
    dlg.spin_x_min.setValue(1.0)
    dlg.spin_x_max.setValue(4.0)
    dlg.edit_x_label.setText("时间轴")
    dlg.combo_x_scale.setCurrentText("线性")
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(1.0)
    dlg.spin_y_max.setValue(100.0)
    dlg.edit_y_label.setText("输出")
    dlg.combo_y_scale.setCurrentText("线性")
    dlg.chk_grid.setChecked(False)

    dlg.apply_changes()

    assert "新标题" in handle.get_title()
    assert handle.get_xlim() == pytest.approx((1.0, 4.0))
    assert "时间轴" in handle.get_xlabel()
    assert handle.get_xscale() == "linear"
    assert handle.get_ylim() == pytest.approx((1.0, 100.0))
    assert "输出" in handle.get_ylabel()
    assert handle.get_yscale() == "linear"
    assert handle.plot_item.legend is None


def test_pg_chart_options_x_range_flushes_viewport_envelope(qapp):
    """A programmatic range commit must not paint the old clipped curve."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    canvas, handle = _pg_handle_with_one_curve(qapp)
    canvas.set_xlim(1.8, 2.2)
    line = handle.get_lines()[0].plot_data_item
    clipped_x, _ = line.getData()
    assert float(np.min(clipped_x)) > 1.0
    assert float(np.max(clipped_x)) < 3.0

    dlg = ChartOptionsDialog(None, handle)
    dlg.chk_x_auto.setChecked(False)
    dlg.spin_x_min.setValue(1.0)
    dlg.spin_x_max.setValue(3.0)
    dlg.apply_changes()

    rendered_x, _ = line.getData()
    assert handle.get_xlim() == pytest.approx((1.0, 3.0))
    assert (float(np.min(rendered_x)), float(np.max(rendered_x))) == pytest.approx(
        (1.0, 3.0)
    )
    assert canvas._refresh_pending is False
    assert canvas._refresh_timer.isActive() is False


def test_pg_chart_options_x_autorange_starts_from_full_data_extent(qapp):
    """Auto-X must not derive its new range from the old clipped envelope."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    canvas, handle = _pg_handle_with_one_curve(qapp)
    canvas.set_xlim(1.8, 2.2)

    dlg = ChartOptionsDialog(None, handle)
    dlg.chk_x_auto.setChecked(True)
    dlg.apply_changes()

    rendered_x, _ = handle.get_lines()[0].plot_data_item.getData()
    assert (float(np.min(rendered_x)), float(np.max(rendered_x))) == pytest.approx(
        (1.0, 3.0)
    )
    assert handle.is_autorange("x") is True


def test_chart_options_dialog_reset_restores_opening_values(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    dlg.edit_title.setText("临时标题")
    dlg.spin_x_min.setValue(-99.0)
    dlg.edit_y_label.setText("临时标签")

    dlg.reset_fields()

    assert dlg.edit_title.text() == "原始标题"
    assert dlg.spin_x_min.value() == pytest.approx(1.0)
    assert dlg.edit_y_label.text() == "幅值"


def test_chart_options_dialog_auto_range_disables_manual_fields(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

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

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    assert dlg.tabs.tabText(1) == "图形"
    assert dlg.combo_curve.count() == 1

    dlg.edit_curve_color.setText("#123456")
    dlg.apply_changes()

    assert handle.get_lines()[0].get_color().lower() == "#123456"


def test_pg_chart_options_reads_grid_initial_state(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    canvas = _pg_canvas_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, canvas.axes_list[0])

    assert dlg.chk_grid.isChecked() is True


def test_pg_chart_options_overlay_apply_preserves_x_only_grid(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(900, 480)
    canvas.show()
    t = np.linspace(0.0, 1.0, 200)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t), "#1769e0", "rpm"),
        ("torque", True, t, 50.0 + np.cos(t), "#ef4444", "Nm"),
    ], mode="overlay")
    QCoreApplication.processEvents()

    pi = canvas._x_master_handle.plot_item
    dlg = ChartOptionsDialog(None, canvas.axes_list[0])
    assert dlg.chk_grid.isChecked()
    dlg.apply_changes()
    QCoreApplication.processEvents()

    assert bool(pi.getAxis("bottom").grid)
    assert not pi.getAxis("left").grid
    assert not pi.getAxis("right").grid


def test_pg_chart_options_reads_yscale_initial_state(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    canvas = _pg_canvas_with_one_curve(qapp)
    handle = canvas.axes_list[0]
    handle.set_yscale("log")

    dlg = ChartOptionsDialog(None, handle)

    assert dlg.combo_y_scale.currentText() == "对数"


def _channel_editor_files(tmp_path):
    import pandas as pd
    from mf4_analyzer.io.file_data import FileData

    df = pd.DataFrame({
        "time": np.arange(20) / 100.0,
        "rpm": np.arange(20.0),
        "spd": np.arange(20.0) * 2,
    })
    fd = FileData(str(tmp_path / "demo.mf4"), df, list(df.columns), {}, 0)
    return {"f0": fd}


def test_channel_editor_empty_export_search_escape_rejects(qapp, qtbot, tmp_path):
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QSignalSpy
    from mf4_analyzer.ui import dialogs

    dlg = dialogs.ChannelEditorDialog(
        None, _channel_editor_files(tmp_path), "f0"
    )
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.export_search.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    rejected = QSignalSpy(dlg.rejected)

    qtbot.keyClick(dlg.export_search, Qt.Key_Escape)
    qapp.processEvents()

    assert len(rejected) == 1
    assert dlg.result() == dlg.Rejected
    assert not dlg.isVisible()


def test_channel_editor_export_search_return_does_not_accept_or_create(
    qapp, qtbot, tmp_path
):
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QSignalSpy
    from mf4_analyzer.ui import dialogs

    dlg = dialogs.ChannelEditorDialog(
        None, _channel_editor_files(tmp_path), "f0"
    )
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg.export_search.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    accepted = QSignalSpy(dlg.accepted)
    ok_clicked = QSignalSpy(dlg.btn_ok.clicked)
    create_clicked = QSignalSpy(dlg.btn_create_single.clicked)

    qtbot.keyClick(dlg.export_search, Qt.Key_Return)
    qapp.processEvents()

    assert len(accepted) == 0
    assert len(ok_clicked) == 0
    assert len(create_clicked) == 0
    assert dlg.isVisible()


def test_single_channel_missing_source_warns(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui import dialogs

    dlg = dialogs.ChannelEditorDialog(None, _channel_editor_files(tmp_path), "f0")
    dlg.combo_src.setCurrentText("missing-source")
    warning_calls = []
    monkeypatch.setattr(
        dialogs.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warning_calls.append(args)),
    )

    dlg._create_single()

    assert warning_calls
    assert warning_calls[0][0] is dlg
    assert warning_calls[0][1] == "无法创建"
    assert "源通道不存在或参数越界" in warning_calls[0][2]


@pytest.mark.parametrize("missing_combo", ["a", "b"])
def test_dual_channel_missing_channel_warns(qapp, tmp_path, monkeypatch, missing_combo):
    from mf4_analyzer.ui import dialogs

    dlg = dialogs.ChannelEditorDialog(None, _channel_editor_files(tmp_path), "f0")
    dlg.combo_a.setCurrentText("rpm")
    dlg.combo_b.setCurrentText("spd")
    if missing_combo == "a":
        dlg.combo_a.setCurrentText("missing-a")
    else:
        dlg.combo_b.setCurrentText("missing-b")
    warning_calls = []
    monkeypatch.setattr(
        dialogs.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warning_calls.append(args)),
    )

    dlg._create_dual()

    assert warning_calls
    assert warning_calls[0][0] is dlg
    assert warning_calls[0][1] == "无法创建"
    assert "源通道不存在或参数越界" in warning_calls[0][2]


def test_single_channel_unknown_op_warns(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui import dialogs

    dlg = dialogs.ChannelEditorDialog(None, _channel_editor_files(tmp_path), "f0")
    dlg.combo_src.setCurrentText("rpm")
    monkeypatch.setattr(dlg.combo_op, "currentIndex", lambda: 99)
    warning_calls = []
    monkeypatch.setattr(
        dialogs.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warning_calls.append(args)),
    )

    dlg._create_single()

    assert warning_calls
    assert warning_calls[0][0] is dlg
    assert warning_calls[0][1] == "无法创建"
    assert "不支持的运算类型" in warning_calls[0][2]


def test_dual_channel_unknown_op_warns(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui import dialogs

    dlg = dialogs.ChannelEditorDialog(None, _channel_editor_files(tmp_path), "f0")
    dlg.combo_a.setCurrentText("rpm")
    dlg.combo_b.setCurrentText("spd")
    monkeypatch.setattr(dlg.combo_op2, "currentIndex", lambda: 99)
    warning_calls = []
    monkeypatch.setattr(
        dialogs.QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: warning_calls.append(args)),
    )

    dlg._create_dual()

    assert warning_calls
    assert warning_calls[0][0] is dlg
    assert warning_calls[0][1] == "无法创建"
    assert "不支持的运算类型" in warning_calls[0][2]


def test_pg_axis_handle_rebuild_legend_stays_available_without_dialog_tab(qapp):
    """The dialog no longer exposes legend rebuild. The adapter method stays."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    canvas = _pg_canvas_with_one_curve(qapp)
    handle = canvas.axes_list[0]
    plot_item = handle.plot_item
    dlg = ChartOptionsDialog(None, handle)
    assert dlg.tabs.count() == 2
    assert not hasattr(dlg, "chk_legend")

    handle.rebuild_legend()
    legend = plot_item.legend
    assert legend is not None
    assert len(legend.items) == 1

    handle.rebuild_legend()
    assert plot_item.legend is legend
    assert len(legend.items) == 1


def test_pg_chart_options_curve_color_syncs_owning_axis_color(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui._axis_handle import PG_AXIS_NEUTRAL_COLOR

    canvas = _pg_canvas_with_one_curve(qapp)
    handle = canvas.axes_list[0]
    line = handle.get_lines()[0]
    axis = handle.plot_item.getAxis("left")
    dlg = ChartOptionsDialog(None, handle)

    dlg.edit_curve_color.setText("#123456")
    dlg.apply_changes()

    assert line.get_color().lower() == "#123456"
    assert axis.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
    assert axis.textPen().color().name().lower() == "#123456"

    seen = []
    canvas.cursor_info.connect(seen.append)
    canvas._emit_single_cursor_html(0.5)

    assert canvas.channel_data["speed"][2].lower() == "#123456"
    assert "#123456" in seen[-1]
    assert "#1769e0" not in seen[-1]


def test_pg_chart_options_curve_color_updates_inside_label_badge(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 800)
    canvas.show()
    t = np.linspace(0.0, 1.0, 200)
    name = "[diya luntai] Rte_ActRetPlausi_mActiveReturnMotorTorq4C VeryLongChannelName"
    canvas.plot_channels([
        (name, True, t, np.sin(t * 12.0), "#1769e0", "Nm"),
        (
            "[diya luntai] Rte_ESChkPlausi_mESMotorTorque_xds16 VeryLongChannelName",
            True,
            t,
            np.cos(t * 10.0),
            "#ef4444",
            "Nm",
        ),
    ], mode="subplot")
    QCoreApplication.processEvents()

    assert canvas._inside_label_items
    dlg = ChartOptionsDialog(None, canvas.axes_list[0])
    dlg.edit_curve_color.setText("#123456")
    dlg.apply_changes()
    QCoreApplication.processEvents()

    assert canvas.channel_data[name][2].lower() == "#123456"
    assert canvas._inside_label_items[0].color.name().lower() == "#123456"
    assert canvas._inside_label_items[0].border.color().name().lower() == "#123456"


def test_pg_chart_options_title_hides_inside_label_via_apply(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 800)
    t = np.linspace(0.0, 1.0, 200)
    rows = [
        (
            "[diya luntai] Rte_ActRetPlausi_mActiveReturnMotorTorq4C VeryLongChannelName",
            True,
            t,
            np.sin(t * 12.0),
            "#1769e0",
            "Nm",
        ),
        (
            "[diya luntai] Rte_ESChkPlausi_mESMotorTorque_xds16 VeryLongChannelName",
            True,
            t,
            np.cos(t * 10.0),
            "#ef4444",
            "Nm",
        ),
    ]
    canvas.plot_channels(rows, mode="subplot")
    QCoreApplication.processEvents()
    assert canvas._inside_label_items
    assert canvas._inside_label_items[0].isVisible()

    dlg = ChartOptionsDialog(None, canvas.axes_list[0])
    dlg.edit_title.setText("Custom subplot title")
    dlg.apply_changes()
    QCoreApplication.processEvents()

    assert "Custom subplot title" in canvas.axes_list[0].get_title()
    assert not canvas._inside_label_items[0].isVisible()


def test_overlay_chart_options_marks_shared_x(qapp):
    from PyQt5.QtCore import QCoreApplication
    from PyQt5.QtWidgets import QLabel

    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    t = np.linspace(1.0, 10.0, 32)
    rows = [
        ("speed", True, t, 1.0 + np.sin(t), "#1769e0", "rpm"),
        ("torque", True, t, 50.0 + np.cos(t), "#ef4444", "Nm"),
    ]
    canvas.plot_channels(rows, mode="overlay")
    QCoreApplication.processEvents()
    assert all(handle.shares_x_axis() for handle in canvas.axes_list)

    dlg = ChartOptionsDialog(None, canvas.axes_list[1])
    note = dlg.findChild(QLabel, "chartOptionsSharedNote")
    assert note is not None
    assert "X 为共享轴" in note.text()

    subplot = TimeDomainCanvasPG()
    subplot.plot_channels(rows, mode="subplot")
    QCoreApplication.processEvents()
    assert subplot.axes_list
    assert all(not handle.shares_x_axis() for handle in subplot.axes_list)


def test_pg_chart_options_overlay_aux_axis_yscale_updates_own_curve(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    t = np.linspace(1.0, 10.0, 200)
    rows = [
        ("speed", True, t, 1.0 + np.sin(t), "#1769e0", "rpm"),
        ("torque", True, t, 50.0 + np.cos(t), "#ef4444", "Nm"),
    ]
    canvas.plot_channels(rows, mode="overlay")
    aux_handle = canvas.axes_list[1]
    aux_line = canvas._channel_lines["torque"][1].plot_data_item
    assert aux_line.opts["logMode"][1] is False

    dlg = ChartOptionsDialog(None, aux_handle)
    dlg.combo_y_scale.setCurrentText("对数")
    dlg.spin_y_min.setValue(1.0)
    dlg.spin_y_max.setValue(100.0)
    dlg.apply_changes()

    assert aux_handle.get_yscale() == "log"
    assert aux_line.opts["logMode"][1] is True


def test_chart_options_dialog_applies_heatmap_map_and_range(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _resolve_colormap

    canvas, handle = _pg_heatmap_handle(qapp)
    mappable = handle.get_mappables()[0]
    dlg = ChartOptionsDialog(None, handle)
    levels_before = mappable.get_clim()

    assert dlg.combo_cmap.currentText() == "viridis"
    assert dlg.combo_cmap.findText("gnuplot2") >= 0
    dlg.combo_cmap.setCurrentText("gnuplot2")
    dlg.chk_color_auto.setChecked(False)
    dlg.spin_color_min.setValue(1.0)
    dlg.spin_color_max.setValue(5.0)
    assert dlg.spin_color_min.isEnabled()
    assert dlg.spin_color_max.isEnabled()

    dlg.apply_changes()

    assert mappable.get_cmap().name == "gnuplot2"
    assert mappable.get_clim() == pytest.approx((1.0, 5.0))
    expected_lut = _resolve_colormap("gnuplot2").getLookupTable(
        0.0, 1.0, 256, alpha=True)
    np.testing.assert_array_equal(
        canvas._img.getColorMap().getLookupTable(0.0, 1.0, 256, alpha=True),
        expected_lut,
    )
    np.testing.assert_array_equal(
        canvas._cbar.colorMap().getLookupTable(0.0, 1.0, 256, alpha=True),
        expected_lut,
    )
    assert levels_before == pytest.approx((0.0, 8.0))

    dlg.chk_color_auto.setChecked(True)
    assert not dlg.spin_color_min.isEnabled()
    assert not dlg.spin_color_max.isEnabled()


def test_chart_options_log_axis_rejects_non_positive(qapp, monkeypatch):
    """Log + non-positive range is rejected before any axis write."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    set_ylim_calls = []
    set_yscale_calls = []

    original_set_ylim = handle.set_ylim
    original_set_yscale = handle.set_yscale

    def record_set_ylim(*args, **kwargs):
        set_ylim_calls.append((args, kwargs))
        return original_set_ylim(*args, **kwargs)

    def record_set_yscale(*args, **kwargs):
        set_yscale_calls.append((args, kwargs))
        return original_set_yscale(*args, **kwargs)

    handle.set_ylim = record_set_ylim
    handle.set_yscale = record_set_yscale
    _mute_chart_warning(monkeypatch)

    dlg.combo_y_scale.setCurrentText("对数")
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(-1.0)
    dlg.spin_y_max.setValue(10.0)
    dlg.apply_changes()

    assert set_yscale_calls == [], set_yscale_calls
    assert set_ylim_calls == [], set_ylim_calls
    assert "y" in dlg._invalid_axes
    assert dlg.was_applied() is False


def test_chart_options_log_axis_warning_blocks_close(qapp, monkeypatch):
    """Apply with log + non-positive range pops a warning and does not accept."""
    from PyQt5.QtWidgets import QDialog, QMessageBox
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

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
    """Log + positive limits are committed as engineering values."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    engineering_calls = []
    original = handle.set_engineering_ylim

    def record_engineering(lo, hi):
        engineering_calls.append((lo, hi))
        return original(lo, hi)

    handle.set_engineering_ylim = record_engineering

    dlg.combo_y_scale.setCurrentText("对数")
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(0.1)
    dlg.spin_y_max.setValue(10.0)
    dlg.apply_changes()

    assert engineering_calls, "set_engineering_ylim was not called"
    assert engineering_calls[-1][0] == pytest.approx(0.1)
    assert engineering_calls[-1][1] == pytest.approx(10.0)
    assert handle.get_engineering_ylim() == pytest.approx((0.1, 10.0))
    assert dlg._invalid_axes == []
    assert dlg.was_applied() is True


def test_chart_options_log_axis_positive_range_ok_button_accepts(qapp, monkeypatch):
    """Log + positive range via OK-button path: dialog accepts, no warning fires."""
    from PyQt5.QtWidgets import QDialog
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

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


def _assert_unique_default(dialog, confirm):
    from PyQt5.QtWidgets import QPushButton

    defaults = [btn for btn in dialog.findChildren(QPushButton) if btn.isDefault()]
    assert defaults == [confirm], (
        f"expected unique default {confirm.text()!r}, got "
        f"{[btn.text() for btn in defaults]}"
    )
    for btn in dialog.findChildren(QPushButton):
        if btn is confirm:
            continue
        assert btn.autoDefault() is False, (
            f"{btn.text()!r} must not be autoDefault when {confirm.text()!r} is default"
        )


def test_channel_editor_has_one_explicit_confirm_default(qapp, tmp_path):
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog

    dlg = ChannelEditorDialog(None, _channel_editor_files(tmp_path), "f0")
    _assert_unique_default(dlg, dlg.btn_ok)


def test_chart_options_has_one_explicit_ok_default(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)
    _assert_unique_default(dlg, dlg.btn_ok)
    assert dlg.btn_curve_color.autoDefault() is False


def test_validation_failure_keeps_dialog_open_and_focuses_first_error(
    qapp, qtbot, monkeypatch
):
    from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    canvas, handle = _pg_handle_with_one_curve(qapp)
    qtbot.addWidget(canvas)
    dlg = ChartOptionsDialog(None, handle)
    qtbot.addWidget(dlg)
    dlg.combo_y_scale.setCurrentText("对数")
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(-1.0)
    dlg.spin_y_max.setValue(10.0)
    dlg.show()
    qtbot.waitExposed(dlg)

    monkeypatch.setattr(
        "mf4_analyzer.ui.dialogs.QMessageBox.warning",
        staticmethod(lambda *args, **kwargs: QMessageBox.Ok),
    )
    dlg._accept_with_apply()
    qapp.processEvents()

    assert dlg.isVisible()
    assert dlg.result() != QDialog.Accepted
    assert "y" in dlg._invalid_axes
    focus = QApplication.focusWidget()
    assert focus is dlg.spin_y_min or dlg.spin_y_min.isAncestorOf(focus)


def test_dangerous_confirmation_escape_and_return_are_safe(
    qapp, qtbot, tmp_path, monkeypatch
):
    from PyQt5.QtCore import QTimer, Qt
    from PyQt5.QtWidgets import QMessageBox as _QMessageBox
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    from mf4_analyzer.ui.dialogs import channel_editor as channel_editor_mod

    dlg = ChannelEditorDialog(None, _channel_editor_files(tmp_path), "f0")
    qtbot.addWidget(dlg)
    dlg.show()
    qtbot.waitExposed(dlg)
    dlg._create_single()
    created = dict(dlg.new_channels)
    assert created
    for item in dlg._iter_export_items():
        if item.text() in created:
            item.setCheckState(Qt.Checked)

    seen = {}

    def fake_question(
        parent,
        title,
        text,
        buttons=_QMessageBox.Yes | _QMessageBox.No,
        defaultButton=_QMessageBox.NoButton,
    ):
        box = _QMessageBox(parent)
        box.setIcon(_QMessageBox.Question)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(buttons)
        box.setDefaultButton(defaultButton)

        def _inspect_and_return():
            yes = box.button(_QMessageBox.Yes)
            no = box.button(_QMessageBox.No)
            seen["yes_is_default"] = bool(yes is not None and yes.isDefault())
            seen["no_is_default"] = bool(no is not None and no.isDefault())
            qtbot.keyClick(box, Qt.Key_Return)

        QTimer.singleShot(0, _inspect_and_return)
        result = box.exec_()
        box.hide()
        box.setParent(None)
        box.deleteLater()
        qapp.processEvents()
        return result

    monkeypatch.setattr(channel_editor_mod.QMessageBox, "question", fake_question)
    dlg.btn_delete.click()
    qapp.processEvents()

    assert seen.get("no_is_default")
    assert not seen.get("yes_is_default")
    assert dlg.new_channels == created


def test_empty_ultraview_search_escape_bubbles_to_sheet_reject(qapp, qtbot):
    """C7: a hostless SearchField must not swallow its sheet's Esc close."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QSignalSpy
    from PyQt5.QtWidgets import QDialog, QVBoxLayout, QWidget
    from mf4_analyzer.ui.drawers.ultraview import UltraViewSheet
    from mf4_analyzer.ui_kit.widgets import SearchField

    page = QWidget()
    page_layout = QVBoxLayout(page)
    field = SearchField("搜索 View、信号或分析类型…", page)
    page_layout.addWidget(field)
    sheet = UltraViewSheet(None, page)
    qtbot.addWidget(page)
    qtbot.addWidget(sheet)
    sheet.present()
    qtbot.waitExposed(sheet)
    field.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()

    rejected = QSignalSpy(sheet.rejected)
    qtbot.keyClick(field, Qt.Key_Escape)
    qapp.processEvents()

    assert len(rejected) == 1
    assert sheet.result() == QDialog.Rejected
    assert not sheet.isVisible()


def test_analysis_chart_options_policy_is_read_only_until_axis_apply(qapp, qtbot):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    canvas, handle = _pg_heatmap_handle(qapp)
    qtbot.addWidget(canvas)
    applied = []
    canvas.analysis_range_adapter = (lambda: {'x_auto': True, 'y_auto': True}, applied.append)
    handle.set_xlim(.5, 1.)
    before = handle.get_xlim()
    dialog = ChartOptionsDialog(None, handle)
    qtbot.addWidget(dialog)
    assert dialog.chk_x_auto.isChecked()
    assert applied == []
    dialog.reject()
    assert applied == []
    dialog = ChartOptionsDialog(None, handle)
    qtbot.addWidget(dialog)
    dialog.edit_title.setText('only title')
    dialog.apply_changes()
    assert applied == []
    assert handle.get_xlim() == pytest.approx(before)
    dialog.chk_x_auto.setChecked(False)
    dialog.spin_x_min.setValue(.2)
    dialog.spin_x_max.setValue(.8)
    dialog.apply_changes()
    assert applied[-1] == {'x': (False, (.2, .8))}
    dialog.chk_x_auto.setChecked(True)
    dialog.apply_changes()
    assert applied[-1]['x'][0] is True
    assert 'y' not in applied[-1]


def test_analysis_chart_options_unchanged_apply_reapplies_parameters(qapp, qtbot):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    canvas, handle = _pg_heatmap_handle(qapp)
    qtbot.addWidget(canvas)
    applied = []
    canvas.analysis_range_adapter = (lambda: {'x_auto': True, 'y_auto': True}, applied.append)
    dialog = ChartOptionsDialog(None, handle)
    qtbot.addWidget(dialog)
    dialog.apply_changes()
    assert set(applied[-1]) == {'x', 'y'}
    assert all(policy[0] for policy in applied[-1].values())


def _mute_chart_warning(monkeypatch):
    calls = []

    def fake(parent, title, text, *args, **kwargs):
        calls.append({"parent": parent, "title": title, "text": text})
        return 0

    monkeypatch.setattr(
        "mf4_analyzer.ui.dialogs.QMessageBox.warning",
        staticmethod(fake),
    )
    return calls


class _FakeCurve:
    def __init__(self, label, color, key):
        self.label = label
        self.color = color
        self.key = key
        self.plot_data_item = object()

    def get_label(self):
        return self.label

    def get_color(self):
        return self.color

    def set_color(self, color):
        self.color = color

    def get_visible(self):
        return True

    def composite_key(self):
        return self.key


class _FakeCmap:
    def __init__(self, name):
        self.name = name


class _BareMappable:
    """Color mappable without the new auto-policy methods."""

    def __init__(self, *, clim=(0.0, 8.0), cmap="viridis"):
        self.clim = clim
        self.cmap_name = cmap
        self.clim_calls = []

    def get_cmap(self):
        return _FakeCmap(self.cmap_name)

    def set_cmap(self, name):
        self.cmap_name = name

    def get_clim(self):
        return self.clim

    def set_clim(self, lo, hi):
        self.clim_calls.append((float(lo), float(hi)))
        self.clim = (float(lo), float(hi))

    def get_array(self):
        return None


class _FakeMappable:
    def __init__(self, *, auto=None, clim=(0.0, 8.0), cmap="viridis"):
        self._auto = auto
        self.clim = clim
        self.cmap_name = cmap
        self.clim_calls = []
        self.policy_calls = []

    def get_cmap(self):
        return _FakeCmap(self.cmap_name)

    def set_cmap(self, name):
        self.cmap_name = name

    def get_clim(self):
        return self.clim

    def set_clim(self, lo, hi):
        self.clim_calls.append((float(lo), float(hi)))
        self.clim = (float(lo), float(hi))

    def is_color_auto(self):
        if self._auto is None:
            raise AssertionError("is_color_auto should not be called")
        return self._auto

    def apply_color_policy(self, auto, lo, hi):
        self.policy_calls.append((bool(auto), float(lo), float(hi)))
        self._auto = bool(auto)

    def get_array(self):
        return None


class _FakeChartHandle:
    """AxisHandle stand-in so dialog tests can pin the frozen contract."""

    def __init__(self):
        self.title = "原始标题"
        self.xlabel = "时间"
        self.ylabel = "幅值"
        self.x_scale = "linear"
        self.y_scale = "linear"
        self.grid_on = True
        self.xlim = (1.0, 3.0)
        self.ylim = (1.0, 10.0)
        self.x_auto = False
        self.y_auto = False
        self.lines = []
        self.mappables = []
        self.title_calls = []
        self.grid_calls = []
        self.box_x = []
        self.box_y = []
        self.eng_x = []
        self.eng_y = []
        self.scale_x = []
        self.scale_y = []
        self.autos = []
        self.legend_calls = 0
        self.redraws = 0
        self.target_text = ""
        self.share_x = False
        self.log_support = {"x": True, "y": True}
        self.legend_support = None

    def get_xlim(self):
        return self.xlim

    def set_xlim(self, lo, hi):
        self.box_x.append((lo, hi))
        self.xlim = (float(lo), float(hi))
        self.x_auto = False

    def get_ylim(self):
        return self.ylim

    def set_ylim(self, lo, hi):
        self.box_y.append((lo, hi))
        self.ylim = (float(lo), float(hi))
        self.y_auto = False

    def autoscale(self, axis="both"):
        self.autos.append(axis)
        if axis in ("x", "both"):
            self.x_auto = True
        if axis in ("y", "both"):
            self.y_auto = True

    def set_xscale(self, scale):
        self.scale_x.append(scale)
        self.x_scale = scale

    def set_yscale(self, scale):
        self.scale_y.append(scale)
        self.y_scale = scale

    def get_xscale(self):
        return self.x_scale

    def get_yscale(self):
        return self.y_scale

    def get_xlabel(self):
        return self.xlabel

    def set_xlabel(self, label):
        self.xlabel = label

    def get_ylabel(self):
        return self.ylabel

    def set_ylabel(self, label):
        self.ylabel = label

    def get_title(self):
        return self.title

    def set_title(self, title):
        self.title_calls.append(title)
        self.title = title

    def grid(self, enabled):
        self.grid_calls.append(bool(enabled))
        self.grid_on = bool(enabled)

    def is_grid_enabled(self):
        return self.grid_on

    def get_lines(self):
        return list(self.lines)

    def get_mappables(self):
        return list(self.mappables)

    def rebuild_legend(self):
        self.legend_calls += 1

    def sync_line_axis_color(self, line, color):
        return None

    def request_redraw(self):
        self.redraws += 1

    def is_autorange(self, axis="x"):
        return self.x_auto if axis == "x" else self.y_auto

    def supports_log_scale(self, axis):
        return bool(self.log_support.get(axis, True))

    def supports_legend_rebuild(self):
        if self.legend_support is None:
            return bool(self.lines)
        return bool(self.legend_support)

    def chart_options_target_text(self):
        return self.target_text

    def shares_x_axis(self):
        return bool(self.share_x)


def test_chart_options_empty_title_commits_blank_string(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    dlg = ChartOptionsDialog(None, handle)
    dlg.edit_title.setText("   ")
    dlg.apply_changes()

    assert handle.title_calls == [""]
    assert handle.get_title() == ""
    assert dlg.was_applied() is True


def test_chart_options_grid_round_trip_writes_each_change(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    handle.grid_on = True
    dlg = ChartOptionsDialog(None, handle)
    assert dlg.chk_grid.isChecked() is True

    dlg.chk_grid.setChecked(False)
    dlg.apply_changes()
    dlg.chk_grid.setChecked(True)
    dlg.apply_changes()

    assert handle.grid_calls == [False, True]
    assert handle.is_grid_enabled() is True


def test_chart_options_failed_log_after_success_keeps_applied_chart(qapp, monkeypatch):
    from PyQt5.QtWidgets import QDialog
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    dlg = ChartOptionsDialog(None, handle)
    warnings = _mute_chart_warning(monkeypatch)

    dlg.edit_title.setText("已提交")
    dlg.apply_changes()
    assert dlg.was_applied() is True
    assert handle.get_title() == "已提交"
    title_calls = list(handle.title_calls)
    scale_calls = list(handle.scale_y)

    dlg.combo_y_scale.setCurrentText("对数")
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(-5.0)
    dlg.spin_y_max.setValue(1.0)
    dlg._accept_with_apply()

    assert dlg.result() != QDialog.Accepted
    assert dlg.was_applied() is True
    assert handle.get_title() == "已提交"
    assert handle.title_calls == title_calls
    assert handle.get_yscale() == "linear"
    assert handle.scale_y == scale_calls
    assert handle.get_ylim() == pytest.approx((1.0, 10.0))
    assert warnings
    assert "Y 最小值" in warnings[-1]["text"]


def test_chart_options_invalid_color_and_reversed_clim_do_not_write(qapp, monkeypatch):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    curve = _FakeCurve("speed", "#112233", ("src", "speed"))
    heat = _BareMappable(clim=(0.0, 8.0))
    handle.lines = [curve]
    handle.mappables = [heat]
    dlg = ChartOptionsDialog(None, handle)
    warnings = _mute_chart_warning(monkeypatch)

    dlg.edit_curve_color.setText("not-a-color")
    dlg.apply_changes()

    assert curve.color == "#112233"
    assert dlg.was_applied() is False
    assert handle.get_title() == "原始标题"
    assert any("颜色" in item["text"] for item in warnings)

    dlg.edit_curve_color.setText("#112233")
    dlg.chk_color_auto.setChecked(False)
    dlg.spin_color_min.setValue(8.0)
    dlg.spin_color_max.setValue(2.0)
    warnings.clear()
    dlg.apply_changes()

    assert heat.clim_calls == []
    assert heat.clim == pytest.approx((0.0, 8.0))
    assert dlg.was_applied() is False
    assert any("色阶最小值" in item["text"] for item in warnings)


def test_chart_options_unedited_tiny_range_keeps_original_float(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    handle.xlim = (1e-8, 5e-8)
    handle.ylim = (1.0, 2.0)
    state = {"x": (1e-8, 5e-8)}

    def get_engineering_xlim():
        return state["x"]

    def set_engineering_xlim(lo, hi):
        handle.eng_x.append((lo, hi))
        state["x"] = (lo, hi)

    handle.get_engineering_xlim = get_engineering_xlim
    handle.set_engineering_xlim = set_engineering_xlim

    dlg = ChartOptionsDialog(None, handle)
    assert dlg.spin_x_min.value() == pytest.approx(0.0)
    dlg.apply_changes()

    assert handle.box_x == []
    assert state["x"][0] == 1e-8
    assert state["x"][1] == 5e-8
    if handle.eng_x:
        assert handle.eng_x[-1][0] == 1e-8
        assert handle.eng_x[-1][1] == 5e-8

    dlg.spin_x_max.lineEdit().selectAll()
    dlg.spin_x_max.lineEdit().insert("9e-8")
    dlg.spin_x_max.lineEdit().textEdited.emit(dlg.spin_x_max.lineEdit().text())
    dlg.apply_changes()

    assert handle.box_x == []
    assert handle.eng_x[-1][0] == 1e-8
    assert handle.eng_x[-1][1] == 9e-8


def test_chart_options_title_only_does_not_rewrite_color_auto(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    heat = _FakeMappable(auto=True, clim=(1.0, 4.0))
    handle.mappables = [heat]
    dlg = ChartOptionsDialog(None, handle)
    assert dlg.chk_color_auto.isChecked() is True

    dlg.edit_title.setText("只改标题")
    dlg.apply_changes()

    assert heat.policy_calls == []
    assert heat.clim_calls == []
    assert heat.is_color_auto() is True
    assert handle.get_title() == "只改标题"
    assert dlg.chk_color_auto.isChecked() is True


def test_chart_options_missing_color_auto_does_not_hardcode_manual(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    heat = _BareMappable(clim=(1.0, 4.0))
    handle.mappables = [heat]
    opened = ChartOptionsDialog(None, handle)
    initial_checked = opened.chk_color_auto.isChecked()
    opened.edit_title.setText("只改标题")
    opened.apply_changes()

    assert heat.clim_calls == []
    assert opened.chk_color_auto.isChecked() is initial_checked


def test_chart_options_reset_restores_drafts_without_touching_chart(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    first = _FakeCurve("same", "#111111", ("file-a", "torque"))
    second = _FakeCurve("same", "#222222", ("file-b", "torque"))
    handle.lines = [first, second]
    dlg = ChartOptionsDialog(None, handle)
    assert dlg.btn_reset.text() == "还原"
    assert "撤销" in dlg.btn_reset.toolTip()
    assert "立即" in dlg.btn_reset.toolTip()
    assert dlg.btn_reset.isEnabled() is False

    dlg.edit_title.setText("草稿标题")
    dlg.edit_curve_color.setText("#aaaaaa")
    dlg.combo_curve.setCurrentIndex(1)
    dlg.edit_curve_color.setText("#bbbbbb")
    dlg.combo_curve.setCurrentIndex(0)

    assert dlg.edit_curve_color.text().lower() == "#aaaaaa"
    dlg.reset_fields()

    assert dlg.edit_title.text() == "原始标题"
    assert dlg.edit_curve_color.text().lower() == "#111111"
    dlg.combo_curve.setCurrentIndex(1)
    assert dlg.edit_curve_color.text().lower() == "#222222"
    assert handle.get_title() == "原始标题"
    assert first.color == "#111111"
    assert second.color == "#222222"
    assert handle.title_calls == []


def test_chart_options_target_shared_axis_and_disabled_capabilities(qapp, monkeypatch):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    handle.target_text = "时域 · 子图 2 · 副轴"
    handle.share_x = True
    handle.log_support = {"x": False, "y": False}
    handle.lines = []
    handle.legend_support = False
    dlg = ChartOptionsDialog(None, handle)

    assert "时域 · 子图 2 · 副轴" in dlg.findChild(
        __import__("PyQt5.QtWidgets", fromlist=["QLabel"]).QLabel,
        "chartOptionsSubtitle",
    ).text()
    note = " ".join(
        label.text()
        for label in dlg.findChildren(
            __import__("PyQt5.QtWidgets", fromlist=["QLabel"]).QLabel
        )
    )
    assert "标题与网格属于整张图" in note
    assert "X 为共享轴" in note
    assert not dlg.combo_x_scale.isEnabled()
    assert not dlg.combo_y_scale.isEnabled()
    assert "对数" in dlg.combo_x_scale.toolTip()
    assert not dlg.edit_curve_color.isEnabled()
    assert not hasattr(dlg, "chk_legend")

    warnings = _mute_chart_warning(monkeypatch)
    dlg.combo_y_scale.setCurrentText("对数")
    dlg.apply_changes()
    assert handle.scale_y == []
    assert handle.legend_calls == 0
    assert warnings == []


def test_chart_options_help_copy_covers_the_dialog_contract():
    from mf4_analyzer.ui import hints, quickref

    hint_text = " ".join(hint.text for hint in hints.all_hints())
    quick_text = " ".join(
        f"{row.desc} {row.sub or ''}"
        for group in quickref.QUICKREF
        for row in group.rows
    )
    combined = hint_text + " " + quick_text
    for phrase in (
        "空标题",
        "打开时",
        "还原",
        "对数",
        "频响",
        "共享",
        "共轴图例逐行显示",
    ):
        assert phrase in combined, phrase


def test_chart_options_constructor_does_not_write_the_chart(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    dlg = ChartOptionsDialog(None, handle)

    assert handle.title_calls == []
    assert handle.box_x == []
    assert handle.box_y == []
    assert handle.redraws == 0
    assert dlg.was_applied() is False
    assert dlg.btn_reset.isEnabled() is False


def test_chart_options_restore_discards_unapplied_draft(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    dlg = ChartOptionsDialog(None, handle)
    dlg.edit_title.setText("草稿标题")
    dlg.spin_x_min.setValue(-4.0)
    assert dlg.btn_reset.isEnabled() is True

    dlg.btn_reset.click()

    assert dlg.edit_title.text() == "原始标题"
    assert dlg.spin_x_min.value() == pytest.approx(1.0)
    assert handle.get_title() == "原始标题"
    assert handle.title_calls == []
    assert handle.redraws == 0
    assert dlg.was_applied() is False
    assert dlg.btn_reset.isEnabled() is False


def test_chart_options_restore_writes_applied_title_and_ranges(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    handle.title = "已有标题"
    handle.xlim = (2.0, 8.0)
    handle.ylim = (3.0, 9.0)
    dlg = ChartOptionsDialog(None, handle)
    dlg.edit_title.setText("临时标题")
    dlg.chk_x_auto.setChecked(False)
    dlg.spin_x_min.setValue(0.0)
    dlg.spin_x_max.setValue(4.0)
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(0.5)
    dlg.spin_y_max.setValue(5.0)
    dlg.edit_y_label.setText("临时轴")
    dlg.apply_changes()
    assert handle.get_title() == "临时标题"
    assert handle.get_xlim() == pytest.approx((0.0, 4.0))
    assert handle.get_ylim() == pytest.approx((0.5, 5.0))
    assert dlg.was_applied() is True

    dlg.btn_reset.click()

    assert handle.get_title() == "已有标题"
    assert handle.get_xlim() == pytest.approx((2.0, 8.0))
    assert handle.get_ylim() == pytest.approx((3.0, 9.0))
    assert handle.get_ylabel() == "幅值"
    assert dlg.edit_title.text() == "已有标题"
    assert dlg.was_applied() is True
    assert dlg.btn_reset.isEnabled() is False


def test_chart_options_restore_round_trips_auto_and_can_edit_again(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    dlg = ChartOptionsDialog(None, handle)
    dlg.chk_x_auto.setChecked(True)
    dlg.chk_y_auto.setChecked(True)
    dlg.apply_changes()
    assert handle.autos[-2:] == ["x", "y"]
    assert handle.x_auto is True
    assert handle.y_auto is True

    dlg.btn_reset.click()

    assert handle.get_xlim() == pytest.approx((1.0, 3.0))
    assert handle.get_ylim() == pytest.approx((1.0, 10.0))
    assert handle.x_auto is False
    assert dlg.chk_x_auto.isChecked() is False
    assert dlg.btn_reset.isEnabled() is False

    dlg.edit_title.setText("再次")
    dlg.apply_changes()
    assert handle.get_title() == "再次"
    dlg.btn_reset.click()
    assert handle.get_title() == "原始标题"
    assert dlg.btn_reset.isEnabled() is False


def test_chart_options_restore_ignores_invalid_draft_and_keeps_cancel_ok(qapp):
    from PyQt5.QtWidgets import QDialog
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    dlg = ChartOptionsDialog(None, handle)
    dlg.chk_x_auto.setChecked(False)
    dlg.spin_x_min.setValue(1.2)
    dlg.spin_x_max.setValue(2.5)
    dlg.edit_title.setText("已应用")
    dlg.apply_changes()
    dlg.spin_x_min.lineEdit().setText("nope")
    dlg.spin_x_min.lineEdit().textEdited.emit("nope")
    assert dlg.btn_reset.isEnabled() is True

    dlg.btn_reset.click()

    assert handle.get_xlim() == pytest.approx((1.0, 3.0))
    assert handle.get_title() == "原始标题"
    assert "nope" not in dlg.spin_x_min.lineEdit().text()
    dlg.btn_cancel.click()
    assert dlg.result() == QDialog.Rejected
    assert handle.get_title() == "原始标题"
    assert dlg.was_applied() is True

    again = ChartOptionsDialog(None, handle)
    again.edit_title.setText("第二次")
    again.apply_changes()
    again.btn_reset.click()
    again.btn_ok.click()
    assert again.result() == QDialog.Accepted
    assert handle.get_title() == "原始标题"


def test_chart_options_restore_puts_each_same_name_curve_back(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    handle = _FakeChartHandle()
    first = _FakeCurve("same", "#111111", ("file-a", "torque"))
    second = _FakeCurve("same", "#222222", ("file-b", "torque"))
    handle.lines = [first, second]
    dlg = ChartOptionsDialog(None, handle)
    dlg.edit_curve_color.setText("#aaaaaa")
    dlg.combo_curve.setCurrentIndex(1)
    dlg.edit_curve_color.setText("#bbbbbb")
    dlg.apply_changes()
    assert first.color.lower() == "#aaaaaa"
    assert second.color.lower() == "#bbbbbb"

    dlg.btn_reset.click()

    assert first.color.lower() == "#111111"
    assert second.color.lower() == "#222222"
    dlg.combo_curve.setCurrentIndex(1)
    assert dlg.edit_curve_color.text().lower() == "#222222"


def test_chart_options_restore_reverts_heatmap_scale_and_cmap(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    canvas, handle = _pg_heatmap_handle(qapp)
    mappable = handle.get_mappables()[0]
    dlg = ChartOptionsDialog(None, handle)
    opened_clim = mappable.get_clim()
    assert dlg.chk_color_auto.isChecked() is False
    dlg.combo_cmap.setCurrentText("gnuplot2")
    dlg.spin_color_min.setValue(1.0)
    dlg.spin_color_max.setValue(5.0)
    dlg.apply_changes()
    assert mappable.get_cmap().name == "gnuplot2"
    assert mappable.get_clim() == pytest.approx((1.0, 5.0))
    assert canvas._z_color_auto is False

    dlg.btn_reset.click()

    assert mappable.get_cmap().name == "viridis"
    assert mappable.get_clim() == pytest.approx(opened_clim)
    assert mappable.is_color_auto() is False
    assert dlg.btn_reset.isEnabled() is False

    dlg.chk_color_auto.setChecked(True)
    dlg.apply_changes()
    assert mappable.is_color_auto() is True
    dlg.btn_reset.click()
    assert mappable.is_color_auto() is False
    assert mappable.get_clim() == pytest.approx(opened_clim)


def test_pg_chart_options_restore_flushes_x_and_leaves_the_other_axis(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas, handle = _pg_handle_with_one_curve(qapp)
    line = handle.get_lines()[0].plot_data_item
    dlg = ChartOptionsDialog(None, handle)
    dlg.edit_title.setText("Applied title")
    dlg.chk_x_auto.setChecked(False)
    dlg.spin_x_min.setValue(1.8)
    dlg.spin_x_max.setValue(2.2)
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(0.2)
    dlg.spin_y_max.setValue(3.0)
    dlg.apply_changes()
    clipped, _y = line.getData()
    assert float(np.min(clipped)) > 1.0
    assert "Applied title" in handle.get_title()

    dlg.btn_reset.click()
    QCoreApplication.processEvents()

    rendered, _y = line.getData()
    assert handle.get_xlim() == pytest.approx((1.0, 3.0))
    assert handle.get_ylim() == pytest.approx((1.0, 10.0))
    assert (float(np.min(rendered)), float(np.max(rendered))) == pytest.approx((1.0, 3.0))
    assert "原始标题" in handle.get_title()
    assert "Applied title" not in handle.get_title()
    assert canvas._refresh_pending is False

    other = TimeDomainCanvasPG()
    other.resize(640, 360)
    t = np.linspace(1.0, 3.0, 80)
    other.plot_channels([
        ("speed", True, t, 1.0 + np.sin(t), "#1769e0", "rpm"),
        ("torque", True, t, 2.0 + np.cos(t), "#ef4444", "Nm"),
    ], mode="subplot")
    QCoreApplication.processEvents()
    sibling = other.axes_list[0]
    sibling.set_ylim(0.5, 2.5)
    target = other.axes_list[1]
    target.set_ylim(1.1, 3.3)
    QCoreApplication.processEvents()
    target_dlg = ChartOptionsDialog(None, target)
    assert target_dlg.chk_y_auto.isChecked() is False
    opened_y = (target_dlg._opened["y_min"], target_dlg._opened["y_max"])
    target_dlg.spin_y_min.setValue(0.4)
    target_dlg.spin_y_max.setValue(6.0)
    target_dlg.apply_changes()
    assert target.get_ylim() == pytest.approx((0.4, 6.0))
    assert sibling.get_ylim() == pytest.approx((0.5, 2.5))
    target_dlg.btn_reset.click()
    assert target.get_ylim() == pytest.approx(opened_y)
    assert sibling.get_ylim() == pytest.approx((0.5, 2.5))


def test_chart_options_restore_returns_live_autorange(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    handle.autoscale(axis="x")
    handle.autoscale(axis="y")
    dlg = ChartOptionsDialog(None, handle)
    assert dlg.chk_x_auto.isChecked() is True
    assert dlg.chk_y_auto.isChecked() is True
    dlg.chk_x_auto.setChecked(False)
    dlg.spin_x_min.setValue(1.4)
    dlg.spin_x_max.setValue(2.1)
    dlg.chk_y_auto.setChecked(False)
    dlg.spin_y_min.setValue(1.2)
    dlg.spin_y_max.setValue(4.0)
    dlg.apply_changes()
    assert handle.is_autorange("x") is False
    assert handle.get_xlim() == pytest.approx((1.4, 2.1))

    dlg.btn_reset.click()

    assert handle.is_autorange("x") is True
    assert handle.is_autorange("y") is True
    assert dlg.chk_x_auto.isChecked() is True
    assert dlg.spin_x_min.isEnabled() is False
    assert dlg.btn_reset.isEnabled() is False


def test_coaxis_channel_labels_survive_chart_options_without_legend_tab(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    t = np.linspace(0.0, 1.0, 64)
    group = {"axis_group": 1}
    canvas.plot_channels([
        ("torque", True, t, np.sin(t), "#1769e0", "Nm", "fid-1", group),
        ("angle", True, t, np.cos(t), "#ef4444", "deg", "fid-1", group),
    ], mode="subplot")
    QCoreApplication.processEvents()
    assert len(canvas.axes_list) == 1
    handle = canvas.axes_list[0]
    before = [name for name, _color, _unit in canvas._subplot_legend_members(handle)]
    assert before == ["torque", "angle"]

    dlg = ChartOptionsDialog(None, handle)
    assert dlg.tabs.tabText(0) == "坐标轴"
    assert dlg.tabs.tabText(1) == "图形"
    dlg.edit_title.setText("共轴标题")
    dlg.apply_changes()
    QCoreApplication.processEvents()

    after = [name for name, _color, _unit in canvas._subplot_legend_members(handle)]
    assert after == ["torque", "angle"]
    assert len(handle.get_lines()) == 2


def _form_page(widget):
    host = widget.parentWidget()
    while host is not None and not host.objectName() == "chartOptionsScroll":
        host = host.parentWidget()
    if host is None:
        return widget.window()
    return host.widget()


def _form_edge(widget, side):
    page = _form_page(widget)
    rect = widget.rect()
    point = rect.topLeft() if side == "left" else rect.topRight()
    return widget.mapTo(page, point).x()


def _assert_shared_field_column(fields):
    lefts = [_form_edge(widget, "left") for widget in fields]
    rights = [_form_edge(widget, "right") for widget in fields]
    assert max(lefts) - min(lefts) <= 1, lefts
    assert max(rights) - min(rights) <= 1, rights
    assert min(widget.width() for widget in fields) > 180


def test_chart_options_form_columns_track_dialog_width(qapp):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QScrollArea, QStyleFactory
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    from mf4_analyzer.ui_kit import load_stylesheet

    load_stylesheet(qapp)
    _canvas, handle = _pg_handle_with_one_curve(qapp)
    styles = [name for name in ("macintosh", "Windows", "Fusion") if name in QStyleFactory.keys()]
    assert "Fusion" in styles
    previous = qapp.style().objectName()
    try:
        for style_name in styles:
            qapp.setStyle(style_name)
            dlg = ChartOptionsDialog(None, handle)
            dlg.show()
            qapp.processEvents()
            dlg.resize(430, max(dlg.height(), 720))
            qapp.processEvents()
            dlg.tabs.setCurrentIndex(0)
            qapp.processEvents()
            axis_fields = [
                dlg.edit_title, dlg.spin_x_min, dlg.spin_x_max, dlg.edit_x_label,
                dlg.combo_x_scale, dlg.spin_y_min, dlg.edit_y_label, dlg.combo_y_scale,
            ]
            _assert_shared_field_column(axis_fields)
            narrow = dlg.spin_x_min.width()
            dlg.chk_x_auto.setChecked(True)
            qapp.processEvents()
            assert dlg.spin_x_min.width() == narrow
            assert dlg.spin_x_min.isEnabled() is False
            dlg.chk_x_auto.setChecked(False)
            dlg.spin_x_min.lineEdit().setText("-1.234567890123e-6")
            dlg.spin_x_min.lineEdit().textEdited.emit(dlg.spin_x_min.lineEdit().text())
            qapp.processEvents()
            assert dlg.spin_x_min.width() == narrow

            dlg.resize(680, dlg.height())
            qapp.processEvents()
            assert dlg.spin_x_min.width() >= narrow + 140
            assert dlg.edit_title.width() == dlg.spin_x_min.width()
            assert dlg.combo_y_scale.width() == dlg.edit_title.width()

            dlg.tabs.setCurrentIndex(1)
            qapp.processEvents()
            appearance_fields = [
                dlg.combo_curve, dlg.combo_cmap, dlg.spin_color_min, dlg.spin_color_max,
            ]
            _assert_shared_field_column(appearance_fields)
            assert abs(
                _form_edge(dlg.btn_curve_color, "right")
                - _form_edge(dlg.combo_curve, "right")
            ) <= 2
            assert dlg.edit_curve_color.width() + dlg.btn_curve_color.width() < dlg.combo_curve.width() + 8
            assert _form_edge(dlg.combo_curve, "left") == _form_edge(dlg.edit_title, "left")
            for scroll in dlg.findChildren(QScrollArea, "chartOptionsScroll"):
                assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            assert dlg.rect().contains(dlg.btn_ok.mapTo(dlg, dlg.btn_ok.rect().bottomRight()))
    finally:
        if previous:
            qapp.setStyle(previous)
