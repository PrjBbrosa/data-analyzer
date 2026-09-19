"""Round-2 View isolation: chart-options appearance on the production path."""
from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.ui.dialogs import ChartOptionsDialog
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.view_state import (
    _encode_channel_key,
    appearance_channel_key,
)

from tests.ui.test_view_state_isolation import (
    _enable_lowpass,
    _fid,
    _flush,
    _make_loaded_window,
    _new_attached_view,
    _save_canvas_png,
    _set_checked,
    _wait_time_view_idle,
)


def _apply_chart_options(window, canvas, handle, monkeypatch, **fields):
    captured = {}

    def fake_edit(parent, axis_handle):
        dlg = ChartOptionsDialog(parent, axis_handle)
        captured["dlg"] = dlg
        if "title" in fields:
            dlg.edit_title.setText(fields["title"])
        if "x_label" in fields:
            dlg.edit_x_label.setText(fields["x_label"])
        if "y_label" in fields:
            dlg.edit_y_label.setText(fields["y_label"])
        if "x_scale" in fields:
            dlg.combo_x_scale.setCurrentText(
                "对数" if fields["x_scale"] == "log" else "线性"
            )
        if "y_scale" in fields:
            dlg.combo_y_scale.setCurrentText(
                "对数" if fields["y_scale"] == "log" else "线性"
            )
        if "grid" in fields:
            dlg.chk_grid.setChecked(bool(fields["grid"]))
        if "curve_index" in fields:
            dlg.combo_curve.setCurrentIndex(int(fields["curve_index"]))
        if "curve_color" in fields:
            dlg.edit_curve_color.setText(fields["curve_color"])
        if "y_auto" in fields:
            dlg.chk_y_auto.setChecked(bool(fields["y_auto"]))
        if "y_min" in fields:
            dlg.spin_y_min.setValue(float(fields["y_min"]))
        if "y_max" in fields:
            dlg.spin_y_max.setValue(float(fields["y_max"]))
        dlg.apply_changes()
        return bool(dlg.was_applied())

    monkeypatch.setattr(
        "mf4_analyzer.ui._axis_interaction.edit_chart_options_dialog",
        fake_edit,
    )
    assert canvas._open_chart_options_for_handle(handle) is True
    return captured.get("dlg")


def _torque_handle(window):
    canvas = window.canvas_time
    assert canvas.axes_list
    return canvas, canvas.axes_list[0]


def test_chart_options_title_log_grid_survive_replot_and_view_switch(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.chart_stack.set_plot_mode("subplot")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    fid = _fid(w)

    _apply_chart_options(
        w, canvas, handle, monkeypatch,
        title="ViewA标题",
        y_label="扭矩覆盖",
        y_scale="log",
        grid=False,
        y_auto=False,
        y_min=40.0,
        y_max=70.0,
    )
    _flush(qapp)
    assert "ViewA标题" in handle.get_title()
    assert "扭矩覆盖" in handle.get_ylabel()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False
    appearance = w.view_manager.get(0).chart_appearance
    spec = appearance["axes"].get(appearance_channel_key(fid, "torque")) or {}
    assert spec.get("title") == "ViewA标题" or "ViewA标题" in str(spec.get("title"))
    assert spec.get("y_scale") == "log"
    assert spec.get("grid") is False

    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    assert "ViewA标题" in handle.get_title()
    assert "扭矩覆盖" in handle.get_ylabel()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas_b, handle_b = _torque_handle(w)
    _apply_chart_options(
        w, canvas_b, handle_b, monkeypatch,
        title="ViewB标题",
        y_label="B轴",
        y_scale="linear",
        grid=True,
    )
    _flush(qapp)

    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    assert "ViewA标题" in handle.get_title()
    assert "扭矩覆盖" in handle.get_ylabel()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False
    assert "ViewB标题" not in handle.get_title()


def test_chart_options_x_label_writes_through_custom_x(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch, x_label="Elapsed",
    )
    _flush(qapp)
    spec = w.view_manager.get(0).axis_opts.get("x_axis") or {}
    assert spec.get("label") == "Elapsed"
    assert w._custom_xlabel == "Elapsed"
    assert "chart_appearance" in w.view_manager.get(0).to_dict()
    assert "x_label" not in (w.view_manager.get(0).chart_appearance or {})

    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    assert "Elapsed" in handle.get_xlabel()


def test_ordinary_chart_options_recolor_stays_view_owned(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch, curve_color="#123456",
    )
    _flush(qapp)
    assert w.view_manager.get(0).colors[(fid, "torque")].lower() == "#123456"

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas_b, handle_b = _torque_handle(w)
    _apply_chart_options(
        w, canvas_b, handle_b, monkeypatch, curve_color="#abcdef",
    )
    _flush(qapp)

    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    colors = w.navigator.get_channel_colors()
    assert colors[(fid, "torque")].lower() == "#123456"


def test_filter_companion_recolor_is_view_owned(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    _enable_lowpass(w, 50.0)
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    lines = handle.get_lines()
    assert len(lines) >= 2
    companion_index = next(
        i for i, line in enumerate(lines)
        if "(" in (line.get_label() or "")
    )
    _apply_chart_options(
        w, canvas, handle, monkeypatch,
        curve_index=companion_index,
        curve_color="#aa00aa",
    )
    _flush(qapp)
    encoded = _encode_channel_key((fid, "torque"))
    appearance = w.view_manager.get(0).chart_appearance
    assert appearance["companion_colors"][encoded].lower() == "#aa00aa"
    assert (fid, "torque") not in w.view_manager.get(0).colors or (
        w.view_manager.get(0).colors.get((fid, "torque"), "").lower() != "#aa00aa"
    )

    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    companion = next(
        line for line in handle.get_lines()
        if "(" in (line.get_label() or "")
    )
    assert companion.get_color().lower() == "#aa00aa"


def test_duplicate_and_save_reopen_keep_chart_appearance(
    qtbot, qapp, loaded_csv, monkeypatch, tmp_path,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch,
        title="保存标题",
        y_scale="log",
        grid=False,
        y_auto=False,
        y_min=40.0,
        y_max=70.0,
    )
    _flush(qapp)
    w._on_view_duplicate(0)
    _flush(qapp)
    assert w.view_manager.active == 1
    copy_state = w.view_manager.get(1)
    orig = w.view_manager.get(0)
    assert copy_state.chart_appearance["axes"]
    assert orig.chart_appearance["axes"]
    _wait_time_view_idle(qtbot, w)
    canvas_copy, handle_copy = _torque_handle(w)
    _apply_chart_options(
        w, canvas_copy, handle_copy, monkeypatch,
        title="副本标题",
        y_scale="linear",
        grid=True,
    )
    _flush(qapp)
    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    assert "保存标题" in handle.get_title()
    assert handle.get_yscale() == "log"

    proj = tmp_path / "appearance.tlproj"
    w.save_project(proj)
    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(proj)
    qapp.processEvents()
    restored._switch_view(0)
    _wait_time_view_idle(qtbot, restored)
    _set_checked(restored, "torque")
    restored.plot_time()
    _wait_time_view_idle(qtbot, restored)
    _canvas, handle = _torque_handle(restored)
    assert "保存标题" in handle.get_title()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False


def test_split_unfocused_chart_options_do_not_stamp_focused_view(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch, title="主图标题", y_scale="log",
    )
    _flush(qapp)

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    w._switch_view(0)
    _flush(qapp)
    w.view_manager.set_split(1)
    _flush(qapp)
    w.chart_stack.set_focused_card(w.chart_stack._time_card)
    _flush(qapp)

    secondary = w.chart_stack.secondary_canvas()
    assert secondary is not None
    assert secondary.axes_list
    _apply_chart_options(
        w, secondary, secondary.axes_list[0], monkeypatch,
        title="分屏标题",
        y_scale="linear",
    )
    _flush(qapp)
    primary = w.view_manager.get(0).chart_appearance
    compare = w.view_manager.get(1).chart_appearance
    pkey = appearance_channel_key(fid, "torque")
    assert (primary.get("axes") or {}).get(pkey, {}).get("y_scale") == "log"
    assert (compare.get("axes") or {}).get(pkey, {}).get("title") in (
        "分屏标题",
        None,
    ) or "分屏标题" in str((compare.get("axes") or {}).get(pkey, {}).get("title"))


def test_offscreen_appearance_pngs_and_axis_values(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    evidence = Path(".state/view-state-isolation")
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.chart_stack.set_plot_mode("subplot")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    w.resize(1100, 700)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch,
        title="A外观",
        y_scale="log",
        grid=False,
        y_auto=False,
        y_min=40.0,
        y_max=70.0,
    )
    _flush(qapp)
    _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round2-view-a.png",
    )
    fid = _fid(w)
    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas_b, handle_b = _torque_handle(w)
    _apply_chart_options(
        w, canvas_b, handle_b, monkeypatch,
        title="B外观",
        y_scale="linear",
        grid=True,
    )
    _flush(qapp)
    _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round2-view-b.png",
    )
    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round2-view-a-after-b.png",
    )
    assert "A外观" in handle.get_title()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False
    lo, hi = handle.get_ylim()
    assert lo > 0 and hi > lo
