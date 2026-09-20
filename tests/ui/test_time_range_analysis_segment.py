"""T0/T3: analysis 全时段/指定范围 is intent, not Home or compute.

UI 双选项只映射 ``chk_range`` False/True；模型仍是
``pane.time_range is None`` (full) 或 tuple (显式请求)。

这些用例编码 T3 mixin 合同。当前 HEAD 上 FFT 切回全时段仍会
``_reset_time_preview_to_extents``，因此部分断言会红——那是 T0。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.main_window import MainWindow
from tests.ui.test_analysis_time_range_confirm import (
    _set_analysis_range_specified,
)


ANALYSIS_SECTIONS = ("fft", "fft_time", "order", "frf")
_HOME_METHODS = (
    "_reset_time_preview_to_extents",
    "reset_view_to_data_extents",
    "full_reset",
)
_COMPUTE_METHODS = (
    "do_fft",
    "do_fft_time",
    "do_order_time",
    "do_frf",
    "_fft_compute_arrays",
    "_start_order_batch",
    "_do_fft_single",
    "_do_order_time_single",
    "_do_fft_time_single",
)


def _register_file(win, name, duration, columns, *, n=201):
    time = np.linspace(0.0, float(duration), int(n))
    data = {}
    for idx, column in enumerate(columns):
        if column == "rpm":
            data[column] = np.full(int(n), 1200.0)
        else:
            data[column] = np.sin(time + idx)
    frame = pd.DataFrame(data)
    before = set(win.files)
    fd = win._register_file_data(
        f"{name}.csv",
        frame,
        list(columns),
        {},
        fs=float(n - 1) / float(duration),
    )
    fd.time_array = time
    fid = next(item for item in win.files if item not in before)
    return fid, time


def _enter_section(win, section, fids):
    win.toolbar._set_mode(section)
    attach = getattr(win, "_attach_files_to_active_analysis_view", None)
    if callable(attach):
        attach(section, list(fids))
    mgr = win.analysis_managers[section]
    win._project_analysis_attachments(section, mgr.get(mgr.active))


def _ready_analysis_section(qtbot, section, *, duration=10.0, n=201):
    if section == "frf":
        from tests.ui.test_frf_time_range_surface import _window_with_pair

        win, pane = _window_with_pair(qtbot)
        state = win.analysis_managers["frf"].get(0)
        return win, state, pane, pane.input_source[0]
    win = MainWindow()
    qtbot.addWidget(win)
    if section == "order":
        fid, _time = _register_file(win, "order", duration, ("sig", "rpm"), n=n)
        _enter_section(win, "order", [fid])
        win._refresh_analysis_candidates("order")
        ctx = win.inspector.order_ctx
        win._echo_combo_signal(ctx.combo_sig, (fid, "sig"))
        win._echo_combo_signal(ctx.combo_rpm, (fid, "rpm"))
        mgr = win.analysis_managers["order"]
        state = mgr.get(mgr.active)
        pane = state.panes[0]
        pane.sources = [(fid, "sig")]
        pane.rpm_source = (fid, "rpm")
        pane.time_range = None
        win._apply_analysis_time_range("order", state)
        return win, state, pane, fid
    if section == "fft_time":
        fid, _time = _register_file(win, "stft", duration, ("sig",), n=n)
        _enter_section(win, "fft_time", [fid])
        win._refresh_analysis_candidates("fft_time")
        ctx = win.inspector.fft_time_ctx
        win._echo_combo_signal(ctx.combo_sig, (fid, "sig"))
        mgr = win.analysis_managers["fft_time"]
        state = mgr.get(mgr.active)
        pane = state.panes[0]
        pane.sources = [(fid, "sig")]
        pane.time_range = None
        win._apply_analysis_time_range("fft_time", state)
        return win, state, pane, fid
    fid, _time = _register_file(win, "fft", duration, ("sig",), n=n)
    _enter_section(win, "fft", [fid])
    win.navigator.set_checked_channels([(fid, "sig")])
    win._ch_changed()
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    pane.sources = [(fid, "sig")]
    pane.time_range = None
    win._apply_analysis_time_range("fft", state)
    return win, state, pane, fid


def _spy_analysis_compute(win, monkeypatch):
    calls = []

    def _track(name):
        def _inner(*_a, **_k):
            calls.append(name)
            return False

        return _inner

    for name in _COMPUTE_METHODS:
        if hasattr(win, name):
            monkeypatch.setattr(win, name, _track(name))
    for owner_name, method in (
        ("_fft_time_coordinator", "request_batch"),
        ("_frf_coordinator", "request"),
        ("_analysis_jobs", "submit_batch"),
    ):
        owner = getattr(win, owner_name, None)
        if owner is None or not hasattr(owner, method):
            continue
        monkeypatch.setattr(owner, method, _track(f"{owner_name}.{method}"))
    return calls


def _spy_home_and_reset(win, section):
    calls = []
    page = win._analysis_page(section)
    canvas = page.focused_canvas() if page is not None else None
    if canvas is None and page is not None:
        canvas = page.pane_canvas(0)
    if canvas is None:
        return calls, None
    for name in _HOME_METHODS:
        orig = getattr(canvas, name, None)
        if not callable(orig):
            continue

        def _wrap(*_a, _name=name, _orig=orig, **_k):
            calls.append(_name)
            return _orig(*_a, **_k)

        setattr(canvas, name, _wrap)
    return calls, canvas


def _forbid_confirm(win, monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("range toggle must not open the confirm dialog")

    monkeypatch.setattr(win, "_ask_use_local_time_range", _boom)


def _spy_fft_preview_refresh(win, monkeypatch):
    calls = []
    real = win._refresh_fft_time_preview

    def _inner(clear_spectrum=True):
        calls.append(bool(clear_spectrum))
        return real(clear_spectrum=clear_spectrum)

    monkeypatch.setattr(win, "_refresh_fft_time_preview", _inner)
    return calls


@pytest.mark.parametrize("section", ANALYSIS_SECTIONS)
def test_selecting_specified_range_writes_pane_without_compute(
    qapp, qtbot, monkeypatch, section,
):
    win, state, pane, _fid = _ready_analysis_section(qtbot, section)
    assert pane.time_range is None
    _forbid_confirm(win, monkeypatch)
    compute = _spy_analysis_compute(win, monkeypatch)
    home, _canvas = _spy_home_and_reset(win, section)
    refresh = (
        _spy_fft_preview_refresh(win, monkeypatch) if section == "fft" else []
    )

    _set_analysis_range_specified(win.inspector.top, True)
    qapp.processEvents()

    assert win.inspector.top.range_enabled() is True
    assert pane.time_range is not None
    assert pane.time_range[0] < pane.time_range[1]
    assert compute == []
    assert home == []
    assert True not in refresh


@pytest.mark.parametrize("section", ANALYSIS_SECTIONS)
def test_selecting_full_clears_pane_without_home_or_compute(
    qapp, qtbot, monkeypatch, section,
):
    """切全时段：pane.time_range is None、清草稿、不 Home/heatmap reset、不计算.

    T0: FFT 当前仍会 ``_reset_time_preview_to_extents``，本例对该 section 会红。
    T3 去掉 preview Home 后应变绿。允许 ``_refresh_fft_time_preview(False)``.
    """
    win, state, pane, _fid = _ready_analysis_section(qtbot, section)
    top = win.inspector.top
    _set_analysis_range_specified(top, True)
    qapp.processEvents()
    assert pane.time_range is not None
    assert top.range_enabled() is True
    _forbid_confirm(win, monkeypatch)
    compute = _spy_analysis_compute(win, monkeypatch)
    home, _canvas = _spy_home_and_reset(win, section)
    refresh = (
        _spy_fft_preview_refresh(win, monkeypatch) if section == "fft" else []
    )

    _set_analysis_range_specified(top, False)
    qapp.processEvents()

    assert pane.time_range is None
    assert top.range_enabled() is False
    assert win._analysis_context.time_range.draft_for(
        section, state.view_id, 0,
    ) is None
    assert compute == []
    assert "_reset_time_preview_to_extents" not in home
    assert "reset_view_to_data_extents" not in home
    assert "full_reset" not in home
    assert True not in refresh


def test_full_programmatic_set_range_values_does_not_emit_or_draft(
    qapp, qtbot,
):
    win, state, pane, _fid = _ready_analysis_section(qtbot, "fft")
    top = win.inspector.top
    assert pane.time_range is None
    assert top.range_enabled() is False
    edited = []
    top.range_edited.connect(lambda lo, hi: edited.append((lo, hi)))
    calls = []
    real = win._analysis_context.time_range.apply_user_edit

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    win._analysis_context.time_range.apply_user_edit = spy
    top.set_range_values(1.25, 8.5)
    assert edited == []
    assert calls == []
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0,
    ) is None
    assert pane.time_range is None
    assert top.range_enabled() is False


def test_section_switch_saves_outgoing_and_does_not_write_into_incoming(
    qapp, qtbot,
):
    win = MainWindow()
    qtbot.addWidget(win)
    fid, _time = _register_file(win, "shared", 10.0, ("sig", "rpm"), n=201)
    _enter_section(win, "fft", [fid])
    win.navigator.set_checked_channels([(fid, "sig")])
    win._ch_changed()
    fft_state = win.analysis_managers["fft"].get(
        win.analysis_managers["fft"].active
    )
    fft_pane = fft_state.panes[0]
    fft_pane.sources = [(fid, "sig")]
    fft_pane.time_range = None
    win._apply_analysis_time_range("fft", fft_state)
    top = win.inspector.top
    _set_analysis_range_specified(top, True)
    qapp.processEvents()
    fft_range = fft_pane.time_range
    assert fft_range is not None

    _enter_section(win, "order", [fid])
    win._refresh_analysis_candidates("order")
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fid, "sig"))
    win._echo_combo_signal(ctx.combo_rpm, (fid, "rpm"))
    order_state = win.analysis_managers["order"].get(
        win.analysis_managers["order"].active
    )
    order_pane = order_state.panes[0]
    order_pane.sources = [(fid, "sig")]
    order_pane.rpm_source = (fid, "rpm")
    win._apply_analysis_time_range("order", order_state)

    assert order_pane.time_range is None
    assert top.range_enabled() is False
    assert fft_pane.time_range == pytest.approx(fft_range)
    assert win._analysis_context.time_range.draft_for(
        "order", order_state.view_id, 0,
    ) is None

    win.toolbar._set_mode("fft")
    win._apply_analysis_time_range("fft", fft_state)
    assert fft_pane.time_range == pytest.approx(fft_range)
    assert top.range_enabled() is True
    assert order_pane.time_range is None


def test_fft_preview_pan_does_not_write_range_or_arm(qapp, qtbot, monkeypatch):
    win, state, pane, _fid = _ready_analysis_section(qtbot, "fft")
    top = win.inspector.top
    assert pane.time_range is None
    assert top.range_enabled() is False
    span_calls = []
    value_calls = []
    monkeypatch.setattr(
        top,
        "set_range_from_span",
        lambda *a, **k: span_calls.append((a, k)),
    )
    real_values = top.set_range_values

    def _values(*a, **k):
        value_calls.append((a, k))
        return real_values(*a, **k)

    monkeypatch.setattr(top, "set_range_values", _values)
    drafts = []
    real_edit = win._analysis_context.time_range.apply_user_edit

    def _edit(*a, **k):
        drafts.append((a, k))
        return real_edit(*a, **k)

    monkeypatch.setattr(win._analysis_context.time_range, "apply_user_edit", _edit)
    handled = win._on_fft_preview_range_changed(0, 0.4, 1.1)
    assert handled is True
    assert span_calls == []
    assert value_calls == []
    assert drafts == []
    assert pane.time_range is None
    assert top.range_enabled() is False
    assert win._analysis_context.time_range.draft_for(
        "fft", state.view_id, 0,
    ) is None
