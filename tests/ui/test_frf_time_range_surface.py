"""FRF must expose the same explicit analysis-time range as other sections."""
from __future__ import annotations

import numpy as np
import pandas as pd

from mf4_analyzer.io import FileData
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.time_xaxis import CustomXAxisSpec, EXACT_SOURCE


def _window_with_pair(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    time = np.arange(2_000, dtype=float) / 1_000.0
    frame = pd.DataFrame({
        "input": np.sin(2 * np.pi * 20.0 * time),
        "output": np.cos(2 * np.pi * 20.0 * time),
    })
    fid = "source-a"
    win.files[fid] = FileData(
        "source-a.csv", frame, list(frame.columns), {}, fs=1_000.0,
    )
    win.files[fid].time_array = time
    win.view_manager.get(0).attached_file_ids = [fid]
    pane = win.analysis_managers["frf"].get(0).panes[0]
    pane.input_source = (fid, "input")
    pane.output_source = (fid, "output")
    win._update_combos()
    win.inspector.frf_ctx.set_input_source(pane.input_source)
    win.inspector.frf_ctx.set_output_source(pane.output_source)
    win.toolbar._set_mode("frf")
    return win, pane


def test_frf_range_checkbox_only_captures_its_visible_inputs(qtbot):
    win, pane = _window_with_pair(qtbot)
    top = win.inspector.top
    top.set_range_values(0.25, 0.75)
    top.chk_range.setChecked(True)
    win.inspector.frf_ctx.spin_t_win.setValue(0.1)

    assert pane.time_range == (0.25, 0.75)
    top.chk_range.setChecked(False)
    assert pane.time_range is None


def test_frf_range_from_time_is_an_explicit_snapshot(qtbot):
    win, pane = _window_with_pair(qtbot)
    top = win.inspector.top
    win.view_manager.get(0).xlim = (0.4, 1.2)
    win._sync_frf_range_from_time_action()

    assert not top.btn_range_from_time.isHidden()
    assert top.btn_range_from_time.isEnabled()
    assert (
        top.btn_range_from_time.sizeHint().height()
        == top.btn_range_max.sizeHint().height()
    )
    top.btn_range_from_time.click()

    assert top.range_values() == (0.4, 1.2)
    assert top.range_enabled()
    assert pane.time_range == (0.4, 1.2)

    win._on_time_canvas_xrange_changed(0.5, 1.0)
    assert top.range_values() == (0.4, 1.2)
    assert pane.time_range == (0.4, 1.2)


def test_frf_range_from_time_explains_why_custom_x_is_unavailable(qtbot):
    win, _pane = _window_with_pair(qtbot)
    win.view_manager.get(0).axis_opts = {
        "x_axis": CustomXAxisSpec(
            mode="channel", resolver=EXACT_SOURCE,
            source_fid="source-a", channel="input",
        ).to_axis_opts(),
    }
    win._sync_frf_range_from_time_action()

    button = win.inspector.top.btn_range_from_time
    assert not button.isEnabled()
    assert button.toolTip() == (
        "当前时域横轴不是物理时间，无法作为 FRF 时间范围；"
        "请切回时间轴或手动输入秒范围。"
    )


def test_frf_max_uses_the_shared_range_without_mutating_the_time_view(qtbot):
    win, pane = _window_with_pair(qtbot)
    win.view_manager.get(0).time_range = (0.1, 0.3)
    win._on_time_range_max_requested()

    assert pane.time_range == (0.0, 1.999)
    assert win.view_manager.get(0).time_range == (0.1, 0.3)


def test_frf_compute_reads_the_same_pane_range_shown_in_the_inspector(qtbot):
    win, pane = _window_with_pair(qtbot)
    pane.input_source = ("source-a", "input")
    pane.output_source = ("source-a", "output")
    top = win.inspector.top
    top.set_range_values(0.25, 0.75)
    top.chk_range.setChecked(True)
    win.inspector.frf_ctx.spin_t_win.setValue(0.1)

    candidate = win._build_frf_candidate(
        win.analysis_managers["frf"].get(0), 0,
    )

    assert candidate["time_range"] == (0.25, 0.75)
    assert pane.time_range == top.range_values()
