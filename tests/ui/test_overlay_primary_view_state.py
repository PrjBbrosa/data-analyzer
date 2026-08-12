"""设为左轴 (overlay primary) must belong to the focused View, not the window.

Regression cover for the silent revert: ``_on_primary_channel_requested`` used
to write only ``MainWindow._overlay_primary``.  Every path that re-projects a
View onto a canvas (``_render_view_to_canvas`` / ``_project_view_controls`` →
``view_bridge.apply_controls_from_state``) rewrites that attribute from
``ViewState.overlay_primary``, so a pick that never reached the View state was
silently reverted to the first checked channel by the next 加入文件 /
应用通道配置 / 打开项目 / View 切换 — and was never persisted into a project.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
from PyQt5.QtCore import Qt

from mf4_analyzer.ui.main_window import MainWindow


def _left_axis_channel_name(canvas):
    handle = canvas.axes_list[0]
    for _ck, name, (h, _line) in canvas._channel_lines.composite_items():
        if h is handle:
            return name
    return None


def _write_csv(path, columns):
    t = np.linspace(0.0, 1.0, 400)
    frame = {"time": t}
    frame.update({name: fn(t) for name, fn in columns.items()})
    pd.DataFrame(frame).to_csv(path, index=False)
    return path


def _load_files(w, qapp, paths):
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([str(p) for p in paths], "")):
        w.load_files()
    qapp.processEvents()


def _check_all_channels(w, qapp, fid):
    fi = w.channel_list._file_items[fid]
    w.channel_list._updating = True
    for i in range(fi.childCount()):
        fi.child(i).setCheckState(0, Qt.Checked)
    w.channel_list._updating = False
    w.channel_list.channels_changed.emit()
    qapp.processEvents()


def _make_window(qapp, qtbot, tmp_path):
    p = _write_csv(tmp_path / "one.csv", {
        "speed": lambda t: np.sin(2 * np.pi * 5 * t),
        "torque": lambda t: np.cos(2 * np.pi * 3 * t),
        "pressure": lambda t: 0.5 * t,
    })
    w = MainWindow()
    qtbot.addWidget(w)
    w.resize(1500, 800)
    w.show()
    qtbot.waitExposed(w)
    _load_files(w, qapp, [p])
    fid = next(iter(w.files))
    _check_all_channels(w, qapp, fid)
    w.chart_stack.set_plot_mode('overlay')
    qapp.processEvents()
    w.plot_time()
    qapp.processEvents()
    return w, fid


def test_view_reprojection_keeps_pick(qapp, qtbot, tmp_path):
    """Any re-projection of the active View must not revert the pick."""
    w, fid = _make_window(qapp, qtbot, tmp_path)
    w.navigator.primary_channel_requested.emit(fid, 'pressure')
    qapp.processEvents()
    w._apply_active_view(w.view_manager.active)
    qapp.processEvents()
    assert _left_axis_channel_name(w.canvas_time).endswith("pressure")


def test_new_view_then_back_keeps_pick(qapp, qtbot, tmp_path):
    """View 新建 + 切回 already captured before projecting — keep it green."""
    w, fid = _make_window(qapp, qtbot, tmp_path)
    w.navigator.primary_channel_requested.emit(fid, 'pressure')
    qapp.processEvents()
    w._on_view_new()
    qapp.processEvents()
    w._switch_view(0)
    qapp.processEvents()
    assert _left_axis_channel_name(w.canvas_time).endswith("pressure")


def test_pick_lands_in_focused_view_state(qapp, qtbot, tmp_path):
    """The pick must live in ViewState so it can survive a project save/load."""
    w, fid = _make_window(qapp, qtbot, tmp_path)
    assert w.view_manager.get(w.view_manager.active).overlay_primary is None
    w.navigator.primary_channel_requested.emit(fid, 'pressure')
    qapp.processEvents()
    state = w.view_manager.get(w.view_manager.active)
    assert state.overlay_primary == (fid, 'pressure')


def test_attaching_another_file_keeps_pick(qapp, qtbot, tmp_path):
    """Real trigger: 加入文件 goes through ``_attach_files_to_focused_view`` →
    ``_project_view_controls`` with no capture in front of it."""
    w, fid = _make_window(qapp, qtbot, tmp_path)
    w.navigator.primary_channel_requested.emit(fid, 'pressure')
    qapp.processEvents()
    assert _left_axis_channel_name(w.canvas_time).endswith("pressure")

    second = _write_csv(tmp_path / "two.csv", {
        "flow": lambda t: np.sin(2 * np.pi * 2 * t),
    })
    _load_files(w, qapp, [second])
    w.plot_time()
    qapp.processEvents()

    assert w._overlay_primary == (fid, 'pressure')
    assert _left_axis_channel_name(w.canvas_time).endswith("pressure")


def test_pick_lands_in_focused_split_pane_view(qapp, qtbot, tmp_path):
    """Split: the pick belongs to the pane that has focus, not always 主栏."""
    w, fid = _make_window(qapp, qtbot, tmp_path)
    w._on_view_new()
    qapp.processEvents()
    _check_all_channels(w, qapp, fid)
    w.chart_stack.set_plot_mode('overlay')
    qapp.processEvents()
    w.plot_time()
    qapp.processEvents()

    primary_idx = w.view_manager.active
    other_idx = 0 if primary_idx != 0 else 1
    w.view_manager.set_split(other_idx)
    qapp.processEvents()
    if w.chart_stack.secondary_canvas() is None:
        import pytest
        pytest.skip("split pane unavailable in this environment")

    w._on_chart_focus_changed(True)
    qapp.processEvents()
    focused_idx = w._focused_view_idx
    assert focused_idx == w._secondary_view_idx

    w.navigator.primary_channel_requested.emit(fid, 'pressure')
    qapp.processEvents()

    assert w.view_manager.get(focused_idx).overlay_primary == (fid, 'pressure')
    unfocused_idx = w._primary_view_idx
    assert w.view_manager.get(unfocused_idx).overlay_primary != (fid, 'pressure')


def test_fft_mode_overlay_primary_survives_reproject_and_save(qapp, qtbot, tmp_path):
    """D-3: picking 设为左轴 in FFT must land on the time View and survive.

    A1 still forbids capturing analysis-projected attached/checked/colors.
    """
    w, fid = _make_window(qapp, qtbot, tmp_path)
    tv = w.view_manager.get(w.view_manager.active)
    attached_before = list(tv.attached_file_ids)
    checked_before = list(tv.checked)
    colors_before = dict(tv.colors)
    assert attached_before
    w._capture_focused_view()

    w.chart_stack.set_mode("fft")
    w.inspector.set_mode("fft")
    fft_state = w.analysis_managers["fft"].get(0)
    fft_state.attached_file_ids = []
    w._project_analysis_attachments("fft", fft_state)
    qapp.processEvents()

    w.navigator.primary_channel_requested.emit(fid, "pressure")
    qapp.processEvents()

    tv = w.view_manager.get(w.view_manager.active)
    assert tv.overlay_primary == (fid, "pressure")
    assert w._overlay_primary == (fid, "pressure")
    assert tv.attached_file_ids == attached_before
    assert tv.checked == checked_before
    assert tv.colors == colors_before

    w.chart_stack.set_mode("time")
    w.inspector.set_mode("time")
    w._apply_active_view(w.view_manager.active)
    qapp.processEvents()
    assert w._overlay_primary == (fid, "pressure")
    assert _left_axis_channel_name(w.canvas_time).endswith("pressure")

    w.chart_stack.set_mode("fft")
    w.inspector.set_mode("fft")
    proj = tmp_path / "overlay-fft.tlproj"
    w.save_project(proj)

    w2 = MainWindow()
    qtbot.addWidget(w2)
    w2.open_project(proj)
    fid2 = next(iter(w2.files))
    assert w2.view_manager.get(0).overlay_primary == (fid2, "pressure")
