"""FRF must expose the same explicit analysis-time range as other sections."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io import FileData
from mf4_analyzer.ui.main_window import MainWindow


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
    top.set_range_values(0.0, 1.999)
    top.spin_start.setValue(0.25)
    top.spin_end.setValue(0.75)
    top.flush_pending_range_edit(emit=True)
    top.chk_range.setChecked(True)
    win.inspector.frf_ctx.spin_t_win.setValue(0.1)

    assert pane.time_range == pytest.approx((0.25, 0.75))
    assert not hasattr(top, "btn_range_from_time")
    top.chk_range.setChecked(False)
    assert pane.time_range is None
    assert top.range_values() == pytest.approx((0.0, 1.999))
    assert win._analysis_context.time_range.draft_for(
        "frf", win.analysis_managers["frf"].get(0).view_id, 0
    ) is None


def test_frf_view_all_does_not_arm_range_or_mutate_time_view(qtbot):
    win, pane = _window_with_pair(qtbot)
    state = win.analysis_managers["frf"].get(0)
    pane.time_range = (0.25, 0.75)
    win.inspector.top.set_range_from_span(0.25, 0.75)
    win._capture_analysis_time_range("frf", state, pane_idx=0)
    win.view_manager.get(0).time_range = (0.1, 0.3)
    win._on_time_range_max_requested()

    assert pane.time_range is None
    assert win.inspector.top.range_enabled() is False
    assert win.inspector.top.range_values() == pytest.approx((0.0, 1.999))
    assert win.view_manager.get(0).time_range == (0.1, 0.3)
    assert win._analysis_context.time_range.draft_for(
        "frf", state.view_id, 0
    ) is None


def test_time_domain_view_all_does_not_convert_analysis_pane_to_full(qtbot):
    win, pane = _window_with_pair(qtbot)
    state = win.analysis_managers["frf"].get(0)
    win.inspector.top.set_range_from_span(0.25, 0.75)
    win._capture_analysis_time_range("frf", state, pane_idx=0)
    assert pane.time_range == pytest.approx((0.25, 0.75))

    win.chart_stack.set_mode("time")
    win.inspector.set_mode("time")
    win._on_time_range_max_requested()

    assert pane.time_range == pytest.approx((0.25, 0.75))
    assert win._analysis_context.time_range.draft_for(
        "frf", state.view_id, 0
    ) is None


def test_frf_compute_reads_the_same_pane_range_shown_in_the_inspector(qtbot):
    win, pane = _window_with_pair(qtbot)
    pane.input_source = ("source-a", "input")
    pane.output_source = ("source-a", "output")
    top = win.inspector.top
    top.set_range_from_span(0.25, 0.75)
    win._capture_analysis_time_range(
        "frf", win.analysis_managers["frf"].get(0), pane_idx=0
    )
    win.inspector.frf_ctx.spin_t_win.setValue(0.1)

    candidate = win._build_frf_candidate(
        win.analysis_managers["frf"].get(0), 0,
    )

    assert candidate["time_range"] == pytest.approx((0.25, 0.75))
    assert pane.time_range == pytest.approx(top.range_values())
