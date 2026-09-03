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
    for text in ("基础信息", "X 轴", "Y 轴", "图例", "标题", "最小值", "最大值", "标签", "刻度"):
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
    assert len(dlg.findChildren(QScrollArea, "chartOptionsScroll")) == 3

    for button in (dlg.btn_reset, dlg.btn_cancel, dlg.btn_apply, dlg.btn_ok):
        assert dlg.rect().contains(button.mapTo(dlg, button.rect().topLeft()))
        assert dlg.rect().contains(button.mapTo(dlg, button.rect().bottomRight()))


def test_chart_options_tab_bar_does_not_paint_trailing_white_base(qapp):
    """Unused tab-bar strip must match dialog chrome, not a leftover white slab.

    Global ``QWidget { background:#ffffff }`` otherwise fills the QTabBar
    behind 图形/图例 and past the last tab. Fusion + production QSS, then
    sample a pixel to the right of 「图例」.
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
    assert bar.count() == 3
    assert dlg.tabs.tabText(2) == "图例"

    last = bar.tabRect(2)
    sample = bar.mapTo(dlg, last.topRight())
    x = min(dlg.width() - 12, sample.x() + 18)
    y = sample.y() + max(2, last.height() // 2)
    assert x > sample.x() + 4

    color = QColor(dlg.grab().toImage().pixel(x, y))
    # Dialog chrome is #f5f7fb; a leftover QTabBar base is #ffffff.
    assert abs(color.red() - 245) <= 8, color.name()
    assert abs(color.green() - 247) <= 8, color.name()
    assert abs(color.blue() - 251) <= 8, color.name()


def test_chart_options_dialog_applies_axis_values_and_legend(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

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
    dlg.chk_legend.setChecked(True)

    dlg.apply_changes()

    assert "新标题" in handle.get_title()
    assert handle.get_xlim() == pytest.approx((1.0, 4.0))
    assert "时间轴" in handle.get_xlabel()
    assert handle.get_xscale() == "linear"
    assert handle.get_ylim() == pytest.approx((1.0, 100.0))
    assert "输出" in handle.get_ylabel()
    assert handle.get_yscale() == "linear"
    assert handle.plot_item.legend is not None


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


def test_pg_chart_options_rebuilds_legend_idempotently(qapp):
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    canvas = _pg_canvas_with_one_curve(qapp)
    handle = canvas.axes_list[0]
    plot_item = handle.plot_item
    dlg = ChartOptionsDialog(None, handle)

    dlg.chk_legend.setChecked(True)
    dlg.apply_changes()
    legend = plot_item.legend
    assert legend is not None
    assert len(legend.items) == 1

    dlg.apply_changes()
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


def test_chart_options_log_axis_rejects_non_positive(qapp):
    """Log scale + non-positive vmin/vmax must skip set_ylim and record axis."""
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
    """Log + positive vmin/vmax applies set_ylim and clears _invalid_axes."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    _canvas, handle = _pg_handle_with_one_curve(qapp)
    dlg = ChartOptionsDialog(None, handle)

    set_ylim_calls = []
    original_set_ylim = handle.set_ylim

    def record_set_ylim(*args, **kwargs):
        set_ylim_calls.append((args, kwargs))
        return original_set_ylim(*args, **kwargs)

    handle.set_ylim = record_set_ylim

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
