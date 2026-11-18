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


def _count_light_prepare(win, state, pane, fd):
    """Count full hashes, value copies and anti-alias calls on the production light path."""
    import mf4_analyzer.analysis_signal_prepare as prepare_mod
    from mf4_analyzer.analysis_signal_prepare import array_content_hash

    hashes = []
    copies = []
    filters = []
    loads = []
    reads = []
    real_hash = array_content_hash
    real_array = prepare_mod.np.array
    real_filter = prepare_mod._apply_antialias
    real_load = prepare_mod.load_native_channel

    def hash_spy(values):
        hashes.append(int(np.ascontiguousarray(np.asarray(values)).nbytes))
        return real_hash(values)

    def array_spy(obj, *args, **kwargs):
        out = real_array(obj, *args, **kwargs)
        # Signal-sized copies only. Filter-design coefficients are a few
        # dozen bytes and are not a full value duplicate of the request.
        nbytes = int(np.asarray(out).nbytes) if kwargs.get("copy") is True else 0
        if nbytes >= 8 * 1000:
            copies.append(nbytes)
        return out

    def filter_spy(*args, **kwargs):
        filters.append(int(np.asarray(args[0]).shape[0]))
        return real_filter(*args, **kwargs)

    def load_spy(*args, **kwargs):
        loads.append(True)
        return real_load(*args, **kwargs)

    import mf4_analyzer.io.signal_access as access_mod

    real_read = access_mod.read_signal

    def read_spy(*args, **kwargs):
        reads.append(kwargs.get("span", args[2] if len(args) > 2 else None))
        return real_read(*args, **kwargs)

    def snapshot():
        return {
            "hashes": list(hashes),
            "hash_bytes": int(sum(hashes)),
            "copies": list(copies),
            "filters": list(filters),
            "loads": len(loads),
            "reads": len(reads),
        }

    def reset():
        hashes.clear()
        copies.clear()
        filters.clear()
        loads.clear()
        reads.clear()

    prepare_mod.array_content_hash = hash_spy
    prepare_mod.np.array = array_spy
    prepare_mod._apply_antialias = filter_spy
    prepare_mod.load_native_channel = load_spy
    access_mod.read_signal = read_spy
    try:
        described = win._frf_prepare_native_pair(
            state, pane, fd, fd, materialize=False,
        )
        direct = snapshot()
        reset()
        key = win._frf_cache_key_for_pane(state, pane)
        lookup = snapshot()
    finally:
        prepare_mod.array_content_hash = real_hash
        prepare_mod.np.array = real_array
        prepare_mod._apply_antialias = real_filter
        prepare_mod.load_native_channel = real_load
        access_mod.read_signal = real_read
    return described, key, direct, lookup


def _attach_native_frf(win, pane, fd, *, align):
    fid = "native-light"
    win.files[fid] = fd
    state = win.analysis_managers["frf"].get(0)
    state.attached_file_ids = [fid]
    state.params["align_then_compute"] = bool(align)
    win.inspector.frf_ctx.chk_align_then_compute.setChecked(bool(align))
    pane.input_source = (fid, "stimulus")
    pane.output_source = (fid, "response")
    return state


def test_native_light_frf_lookup_does_not_hash_or_copy(qtbot, tmp_path, monkeypatch):
    """Production lookup must not hash or copy either a cross-rate or a same-axis pair."""
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
    from tests.test_batch_source_integration import _native_integer_ratio_frf

    monkeypatch.setattr(
        "mf4_analyzer.ui.main_window.window.QMessageBox.question",
        lambda *args, **kwargs: None,
    )
    win, pane = _window_with_pair(qtbot)
    cross = _native_integer_ratio_frf(tmp_path / "cross.mf4")
    state = _attach_native_frf(win, pane, cross, align=True)
    described, key, cross_direct, cross_lookup = _count_light_prepare(win, state, pane, cross)
    assert described["input_values"] is None and described["output_values"] is None
    assert key is not None

    rate = 1000.0
    count = 4000
    axis = np.arange(count) / rate
    store = NativeSignalStore.build(
        "native-same-light",
        [AxisSpec("t0", "clock", "time", "s", axis, fs_status="known", fs_hz=rate)],
        [
            ChannelSpec(0, 0, "stimulus", "t0", np.sin(axis), unit="Nm"),
            ChannelSpec(0, 1, "response", "t0", 2.0 * np.sin(axis), unit="Nm"),
        ],
    )
    same = FileData.from_native_store(tmp_path / "same.mf4", store)
    state = _attach_native_frf(win, pane, same, align=False)
    described, key, same_direct, same_lookup = _count_light_prepare(win, state, pane, same)
    assert described["input_values"] is None and described["output_values"] is None
    assert key is not None
    report = {
        "cross_direct": cross_direct,
        "cross_lookup": cross_lookup,
        "same_direct": same_direct,
        "same_lookup": same_lookup,
    }
    for label, counts in (
        ("cross_direct", cross_direct),
        ("cross_lookup", cross_lookup),
        ("same_direct", same_direct),
        ("same_lookup", same_lookup),
    ):
        assert counts["hash_bytes"] == 0, report
        assert counts["copies"] == [], report
        assert counts["filters"] == [], report
        assert counts["loads"] == 0, report
        assert counts["reads"] == 0, report


def test_gui_range_input_keeps_shared_origin_and_known_gain(qtbot, tmp_path):
    """Inspector range plus the real candidate job, checked against the known gain."""
    from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
    from tests.test_batch_source_integration import _native_integer_ratio_frf

    win, pane = _window_with_pair(qtbot)
    first = _native_integer_ratio_frf(tmp_path / "gui-a.mf4")
    state = _attach_native_frf(win, pane, first, align=True)
    top = win.inspector.top
    top.set_range_from_span(0.1001, 3.5)
    win._capture_analysis_time_range("frf", state, pane_idx=0)
    pane.input_source = ("native-light", "stimulus")
    pane.output_source = ("native-light", "response")
    assert pane.time_range == pytest.approx((0.1001, 3.5))

    class _Worker:
        def cancelled(self):
            return False

        class progress:
            @staticmethod
            def emit(*_args, **_kwargs):
                return None

    candidate = win._build_frf_candidate(state, 0)
    result = candidate["job"](_Worker())
    assert candidate["time_range"][0] >= 0.1001 - 1e-9
    assert candidate["time_range"][1] <= 3.5 + 1e-9
    band = (
        (result.coherence >= 0.99)
        & (np.abs(result.frequencies - 80.0) <= 1000.0 / max(result.frequencies.size, 1))
    )
    assert np.any(band)
    gain_db = 20.0 * np.log10(np.abs(result.transfer[band]))
    phase = np.angle(result.transfer[band], deg=True)
    assert np.max(np.abs(gain_db - 20.0 * np.log10(2.0))) <= 0.1
    assert np.max(np.abs(phase)) <= 1.0
    lookup = win._frf_cache_key_for_pane(state, pane)
    from mf4_analyzer.ui.main_window.frf_coordinator import frf_compute_cache_params
    job_key = win.analysis_caches["frf"].make_key(
        candidate["input_source"],
        candidate["output_source"],
        frf_compute_cache_params(candidate["params"]),
        candidate["time_range"],
    )
    assert lookup == job_key

    rate = 1000.0
    count = 400
    axis = 0.2 + np.arange(count) / rate
    changed = NativeSignalStore.build(
        "native-same-light",
        [AxisSpec("t0", "clock", "time", "s", axis, fs_status="known", fs_hz=rate)],
        [
            ChannelSpec(0, 0, "stimulus", "t0", np.sin(axis), unit="Nm"),
            ChannelSpec(0, 1, "response", "t0", 3.0 * np.sin(axis), unit="Nm"),
        ],
    )
    other = FileData.from_native_store(tmp_path / "changed.mf4", changed)
    original = NativeSignalStore.build(
        "native-same-light",
        [AxisSpec("t0", "clock", "time", "s", axis, fs_status="known", fs_hz=rate)],
        [
            ChannelSpec(0, 0, "stimulus", "t0", np.sin(axis), unit="Nm"),
            ChannelSpec(0, 1, "response", "t0", 2.0 * np.sin(axis), unit="Nm"),
        ],
    )
    base = FileData.from_native_store(tmp_path / "base.mf4", original)
    pane.time_range = None
    state.params["align_then_compute"] = False
    win.inspector.frf_ctx.chk_align_then_compute.setChecked(False)
    pane.input_source = ("native-light", "stimulus")
    pane.output_source = ("native-light", "response")
    win.files["native-light"] = base
    base_key = win._frf_cache_key_for_pane(state, pane)
    win.files["native-light"] = other
    changed_key = win._frf_cache_key_for_pane(state, pane)
    assert base_key is not None and changed_key is not None
    assert base_key != changed_key


def test_frf_explicit_boundary_alignment_preserves_end_without_compute(qtbot, monkeypatch):
    win, pane = _window_with_pair(qtbot)
    state = win.analysis_managers['frf'].get(0)
    source = win.files['source-a']
    source.time_array = source.time_array + 0.0170556
    win._apply_analysis_time_range('frf', state)
    top = win.inspector.top
    _set_analysis_range_specified(top, True)
    top.spin_start.setValue(0.017)
    top.spin_end.setValue(1.5)
    top.flush_pending_range_edit()
    assert pane.time_range == (0.017, 1.5)

    prompts = []
    compute = []
    dirty = []
    real_dirty = win._dirty_frf_pane

    def choose_align(_lo, _hi, conflicts):
        prompts.append(conflicts)
        return 'align'

    def record_dirty(*args, **kwargs):
        dirty.append(args[1])
        return real_dirty(*args, **kwargs)

    monkeypatch.setattr(win, '_ask_use_local_time_range', choose_align)
    monkeypatch.setattr(win, '_dirty_frf_pane', record_dirty)
    monkeypatch.setattr(win, 'do_frf', lambda *a, **k: compute.append('do_frf'))
    monkeypatch.setattr(
        win._frf_coordinator, 'request', lambda *a, **k: compute.append('request'),
    )

    assert win._offer_analysis_time_range_before_compute('frf') is True
    assert pane.time_range == (0.0170556, 1.5)
    assert top.range_values() == pane.time_range
    assert top.range_enabled() is True
    assert dirty == [0]
    assert len(prompts) == 1
    assert compute == []

    assert win._offer_analysis_time_range_before_compute('frf') is True
    assert len(prompts) == 1
    assert dirty == [0]
    assert compute == []
