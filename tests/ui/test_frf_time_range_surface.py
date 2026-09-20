"""FRF must expose the same explicit analysis-time range as other sections."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io import FileData
from mf4_analyzer.ui.main_window import MainWindow
from tests.ui.test_analysis_time_range_confirm import (
    _set_analysis_range_specified,
    _user_commit_range,
)


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


def _spy_frf_home(win):
    calls = []
    canvas = win.chart_stack.page_frf.pane_canvas(0)
    for name in (
        "reset_view_to_data_extents",
        "_reset_time_preview_to_extents",
        "full_reset",
    ):
        orig = getattr(canvas, name, None)
        if not callable(orig):
            continue

        def _wrap(*_a, _name=name, _orig=orig, **_k):
            calls.append(_name)
            return _orig(*_a, **_k)

        setattr(canvas, name, _wrap)
    return calls


def test_frf_range_checkbox_only_captures_its_visible_inputs(qtbot, monkeypatch):
    win, pane = _window_with_pair(qtbot)
    top = win.inspector.top
    top.set_range_values(0.0, 1.999)
    top.spin_start.setValue(0.25)
    top.spin_end.setValue(0.75)
    top.flush_pending_range_edit(emit=True)
    compute = []
    monkeypatch.setattr(win, "do_frf", lambda *a, **k: compute.append("do_frf"))
    coordinator = getattr(win, "_frf_coordinator", None)
    if coordinator is not None:
        monkeypatch.setattr(
            coordinator, "request", lambda *a, **k: compute.append("request")
        )
    home = _spy_frf_home(win)
    _set_analysis_range_specified(top, True)
    win.inspector.frf_ctx.spin_t_win.setValue(0.1)

    assert pane.time_range == pytest.approx((0.25, 0.75))
    assert not hasattr(top, "btn_range_from_time")
    _set_analysis_range_specified(top, False)
    assert pane.time_range is None
    assert top.range_values() == pytest.approx((0.0, 1.999))
    assert win._analysis_context.time_range.draft_for(
        "frf", win.analysis_managers["frf"].get(0).view_id, 0
    ) is None
    assert compute == []
    assert home == []


def test_frf_switching_to_full_clears_range_without_home(qtbot, monkeypatch):
    """T3: 切全时段清 pane 范围且不 Home。不要要求「全部」按钮可见。"""
    win, pane = _window_with_pair(qtbot)
    state = win.analysis_managers["frf"].get(0)
    pane.time_range = (0.25, 0.75)
    win.inspector.top.set_range_from_span(0.25, 0.75)
    win._capture_analysis_time_range("frf", state, pane_idx=0)
    win.view_manager.get(0).time_range = (0.1, 0.3)
    compute = []
    monkeypatch.setattr(win, "do_frf", lambda *a, **k: compute.append("do_frf"))
    coordinator = getattr(win, "_frf_coordinator", None)
    if coordinator is not None:
        monkeypatch.setattr(
            coordinator, "request", lambda *a, **k: compute.append("request")
        )
    home = _spy_frf_home(win)
    _set_analysis_range_specified(win.inspector.top, False)

    assert pane.time_range is None
    assert win.inspector.top.range_enabled() is False
    assert win.inspector.top.range_values() == pytest.approx((0.0, 1.999))
    assert win.view_manager.get(0).time_range == (0.1, 0.3)
    assert win._analysis_context.time_range.draft_for(
        "frf", state.view_id, 0
    ) is None
    assert compute == []
    assert home == []


def test_frf_max_requested_converts_to_full_without_time_home(qtbot):
    """Compatibility path: analysis max-requested still means full, not Time Home."""
    win, pane = _window_with_pair(qtbot)
    state = win.analysis_managers["frf"].get(0)
    pane.time_range = (0.25, 0.75)
    win.inspector.top.set_range_from_span(0.25, 0.75)
    win._capture_analysis_time_range("frf", state, pane_idx=0)
    win.view_manager.get(0).time_range = (0.1, 0.3)
    home = _spy_frf_home(win)
    win._on_time_range_max_requested()

    assert pane.time_range is None
    assert win.inspector.top.range_enabled() is False
    assert win.inspector.top.range_values() == pytest.approx((0.0, 1.999))
    assert win.view_manager.get(0).time_range == (0.1, 0.3)
    assert win._analysis_context.time_range.draft_for(
        "frf", state.view_id, 0
    ) is None
    assert home == []


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


def test_frf_missing_role_cannot_use_local_or_full(qtbot, monkeypatch):
    win, pane = _window_with_pair(qtbot)
    pane.output_source = None
    win.inspector.frf_ctx.set_output_source(None)
    top = win.inspector.top
    top.set_range_limits(-10.0, 20.0)
    _user_commit_range(top, 0.25, 0.75)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "local")
    assert win._offer_analysis_time_range_before_compute("frf") is False
    assert pane.time_range is None
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "full")
    assert win._offer_analysis_time_range_before_compute("frf") is False
    assert pane.time_range is None


def test_frf_no_intersection_cannot_use_local_or_full(qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    in_t = np.linspace(0.0, 1.0, 101)
    out_t = np.linspace(3.0, 4.0, 101)
    win.files["in"] = FileData(
        "in.csv",
        pd.DataFrame({"input": np.sin(in_t)}),
        ["input"],
        {},
        fs=100.0,
    )
    win.files["in"].time_array = in_t
    win.files["out"] = FileData(
        "out.csv",
        pd.DataFrame({"output": np.cos(out_t)}),
        ["output"],
        {},
        fs=100.0,
    )
    win.files["out"].time_array = out_t
    pane = win.analysis_managers["frf"].get(0).panes[0]
    pane.input_source = ("in", "input")
    pane.output_source = ("out", "output")
    win.toolbar._set_mode("frf")
    top = win.inspector.top
    top.set_range_limits(-10.0, 20.0)
    _user_commit_range(top, 0.2, 0.8)
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "local")
    assert win._offer_analysis_time_range_before_compute("frf") is False
    assert pane.time_range is None
    monkeypatch.setattr(win, "_ask_use_local_time_range", lambda *a, **k: "full")
    assert win._offer_analysis_time_range_before_compute("frf") is False
    assert pane.time_range is None


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
