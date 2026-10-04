"""Cross-view comparison routes through an explicit view target.

Opening the pair is presentation. Render, focus capture, source scope, and
compute dispatch use ``(section, view_id, pane_index)`` rather than whichever
view happens to be the active tab.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication, QSplitter

from mf4_analyzer.signal.frf import FrfEffectiveFacts, FrfResult
from mf4_analyzer.ui.analysis_view_state import MAX_PANES
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window.analysis_comparison import AnalysisComparisonDisplay
from mf4_analyzer.ui.view_tabbar import ViewTabBar


SECTIONS = ("fft", "fft_time", "order", "frf")


@pytest.fixture
def two_file_win(qapp, loaded_csv, tmp_path, qtbot):
    t = np.linspace(0, 1.0, 1000)
    frame = pd.DataFrame({
        "time": t,
        "speed": 800 * np.sin(2 * np.pi * 7 * t),
        "torque": 40 + 3 * np.cos(2 * np.pi * 4 * t),
    })
    path = tmp_path / "sample2.csv"
    frame.to_csv(path, index=False)
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(loaded_csv)
    win._load_one(str(path))
    assert len(win.files) == 2
    return win


def _ctx(win, section):
    return {
        "fft": win.inspector.fft_ctx,
        "fft_time": win.inspector.fft_time_ctx,
        "order": win.inspector.order_ctx,
        "frf": win.inspector.frf_ctx,
    }[section]


def _enter(win, section):
    win.toolbar._set_mode(section)
    win.chart_stack.ensure_analysis_page_ready(section)
    return win._analysis_page(section)


def _pair(win, section):
    mgr = win.analysis_managers[section]
    if len(mgr.views) < 2:
        mgr.new_view(activate=False)
    return mgr, mgr.get(0), mgr.get(1)


def _stamp(win, section, state, **overrides):
    params = dict(_ctx(win, section).current_params())
    params.update(overrides)
    state.params = params
    return params


def _checked(win):
    return {(row[0], row[1]) for row in win.navigator.get_checked_channels()}


def _press():
    return QMouseEvent(
        QEvent.MouseButtonPress,
        QPointF(3, 3),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )


def _curve_y(canvas):
    data = canvas._amp_curves[0].getData()
    return np.asarray(data[1], dtype=float)


def _arm_compute_spies(monkeypatch, win):
    calls = []
    jobs = win._analysis_jobs
    monkeypatch.setattr(jobs, "submit", lambda *a, **k: calls.append("submit") or None)
    monkeypatch.setattr(
        jobs, "submit_batch", lambda *a, **k: calls.append("submit_batch") or None,
    )
    for name in ("do_fft", "do_fft_time", "do_order_time", "do_frf"):
        monkeypatch.setattr(
            win, name, lambda *a, _name=name, **k: calls.append(_name),
        )
    monkeypatch.setattr(
        win._fft_time_coordinator, "request_batch",
        lambda *a, **k: calls.append("fft_time_batch") or 0,
    )
    monkeypatch.setattr(
        win._frf_coordinator, "request",
        lambda *a, **k: calls.append("frf_request") or False,
    )
    monkeypatch.setattr(
        win, "_start_order_batch", lambda *a, **k: calls.append("order_batch"),
    )
    monkeypatch.setattr(
        win, "_recompute_restored_analysis_view",
        lambda *a, **k: calls.append("restore"),
    )
    return calls


def _frf_result(marker):
    facts = FrfEffectiveFacts(
        requested_t_win_s=0.5,
        requested_nperseg=500,
        nperseg=500,
        nfft=500,
        noverlap=250,
        hop=250,
        segments=4,
        fs=1000.0,
        df=2.0,
        n_samples=1000,
        time_start=0.0,
        time_end=1.0,
        window="hanning",
        periodic_window=True,
        detrend="constant",
        max_time_jitter=0.0,
        max_time_difference=0.0,
        invalid_bins=0,
    )
    return FrfResult(
        frequencies=np.array([0.0, 10.0, 20.0]),
        transfer=np.array([marker, marker, marker], dtype=complex),
        pxx=np.ones(3),
        pyy=np.ones(3),
        pxy=np.ones(3, dtype=complex),
        coherence=np.ones(3),
        effective=facts,
        warnings=(),
    )


def test_cached_results_follow_each_views_params(two_file_win, monkeypatch):
    win = two_file_win
    fid_a, fid_b = list(win.files)
    fd = win.files[fid_a]
    time_before = fd.time_array
    fs_before = fd.fs
    page = _enter(win, "fft")
    mgr, host, peer = _pair(win, "fft")
    _stamp(win, "fft", host, window="hanning", t_win_s=2.0, overlap=0.5, amp_y="Linear")
    _stamp(win, "fft", peer, window="hamming", t_win_s=1.0, overlap=0.2, amp_y="Linear")
    for state in (host, peer):
        state.attached_file_ids = [fid_a, fid_b]
    host.add_pane()
    peer.add_pane()
    host.panes[0].sources = [(fid_a, "speed")]
    host.panes[1].sources = [(fid_a, "torque")]
    peer.panes[0].sources = [(fid_b, "torque")]
    peer.panes[1].sources = [(fid_b, "speed")]

    freq = np.linspace(0.0, 8.0, 8)
    seeded = {}
    for state, pane_idx, fid, channel, marker in (
        (host, 0, fid_a, "speed", 1.5),
        (host, 1, fid_a, "torque", 2.5),
        (peer, 0, fid_b, "torque", 4.25),
        (peer, 1, fid_b, "speed", 7.5),
    ):
        amp = np.full(8, marker)
        result = (freq, amp, amp.copy())
        key = win._analysis_cache_key_for_view_source(
            "fft", state, state.panes[pane_idx], pane_idx, fid, channel,
        )
        win.analysis_caches["fft"].put(key, result)
        seeded[(state.view_id, pane_idx)] = (key, result, marker)

    calls = _arm_compute_spies(monkeypatch, win)
    assert win.open_comparison("fft", host.view_id, peer.view_id)
    QApplication.processEvents()
    assert calls == []
    assert fd.time_array is time_before
    assert fd.fs == fs_before
    assert isinstance(win._analysis_context.comparison, AnalysisComparisonDisplay)
    assert len(page.findChildren(ViewTabBar)) == 1
    view_split = page.findChild(QSplitter, "analysisComparisonSplit")
    assert view_split is not None and view_split.orientation() == Qt.Horizontal
    assert view_split.count() == 2
    assert page.pane_count() == 2
    assert page._peer_host.pane_count() == 2
    assert len(host.panes) == 2 and len(peer.panes) == 2
    assert MAX_PANES == 2

    host_canvas = page.pane_canvas(0)
    host_second = page.pane_canvas(1)
    peer_canvas = page.peer_cards()[0].canvas
    peer_second = page.peer_cards()[1].canvas
    assert _curve_y(host_canvas)[0] == pytest.approx(1.5)
    assert _curve_y(host_second)[0] == pytest.approx(2.5)
    assert _curve_y(peer_canvas)[0] == pytest.approx(4.25)
    assert _curve_y(peer_second)[0] == pytest.approx(7.5)
    assert win.analysis_caches["fft"].get(seeded[(host.view_id, 0)][0]) is seeded[(host.view_id, 0)][1]
    assert win.analysis_caches["fft"].get(seeded[(peer.view_id, 0)][0]) is seeded[(peer.view_id, 0)][1]
    assert mgr.active == 0
    assert win._comparison().focused("fft") == (host.view_id, 0)
    assert not win._comparison().axis_linked("fft")
    assert not win._comparison().levels_locked("fft")

    page._peer_host.resize(300, 400)
    page._peer_host.apply_width_orientation()
    assert page._peer_host._split.orientation() == Qt.Vertical

    pins_while_open = {
        slot for slot in win._analysis_pins._slots if slot[1] == str(peer.view_id)
    }
    assert pins_while_open
    win.close_comparison("fft")
    QApplication.processEvents()
    assert calls == []
    assert win._comparison().running_timers() == []
    assert not win._comparison().is_open("fft")
    assert any(slot[1] == str(peer.view_id) for slot in win._analysis_pins._slots)
    assert _curve_y(host_canvas)[0] == pytest.approx(1.5)


def test_focus_capture_source_scope_and_compute_target(two_file_win, monkeypatch):
    win = two_file_win
    fid_a, fid_b = list(win.files)
    page = _enter(win, "fft")
    _mgr, host, peer = _pair(win, "fft")
    _stamp(win, "fft", host, window="hanning", t_win_s=2.0, overlap=0.5, amp_y="Linear")
    _stamp(win, "fft", peer, window="hamming", t_win_s=1.0, overlap=0.2, amp_y="Linear")
    for state in (host, peer):
        state.attached_file_ids = [fid_a, fid_b]
    host.add_pane()
    host.panes[0].sources = [(fid_a, "speed")]
    host.panes[1].sources = [(fid_a, "torque")]
    peer.panes[0].sources = [(fid_b, "torque")]
    assert win.open_comparison("fft", host.view_id, peer.view_id)

    assert _checked(win) == {(fid_a, "speed")}
    assert win.inspector.fft_ctx.combo_win.currentText() == "hanning"

    page._peer_host.eventFilter(page.peer_cards()[0], _press())
    QApplication.processEvents()
    assert win._comparison().focused("fft") == (peer.view_id, 0)
    assert win.analysis_managers["fft"].active == 0
    assert _checked(win) == {(fid_b, "torque")}
    assert win.inspector.fft_ctx.combo_win.currentText() == "hamming"

    spin = win.inspector.fft_ctx.spin_overlap
    spin.blockSignals(True)
    spin.setValue(9)
    page.eventFilter(page._cards[0], _press())
    QApplication.processEvents()
    spin.blockSignals(False)
    assert win._comparison().focused("fft") == (host.view_id, 0)
    assert host.params["window"] == "hanning"
    assert host.params["overlap"] == pytest.approx(0.5)
    assert host.params["t_win_s"] == pytest.approx(2.0)
    assert peer.params["window"] == "hamming"
    assert peer.params["t_win_s"] == pytest.approx(1.0)
    assert peer.params["overlap"] == pytest.approx(0.09)
    assert _checked(win) == {(fid_a, "speed")}

    page.eventFilter(page._cards[1], _press())
    QApplication.processEvents()
    assert win._comparison().focused("fft") == (host.view_id, 1)
    assert _checked(win) == {(fid_a, "torque")}

    assert win.focus_comparison("fft", peer.view_id, 0)
    lookups = []
    cache = win.analysis_caches["fft"]
    original_get = cache.get

    def _get(key):
        lookups.append(key)
        return original_get(key)

    monkeypatch.setattr(cache, "get", _get)
    plotted = []
    original_plot = win._plot_fft_entries

    def _plot(entries, canvas):
        plotted.append(canvas)
        return original_plot(entries, canvas)

    monkeypatch.setattr(win, "_plot_fft_entries", _plot)
    host_curve = page.pane_canvas(0)._amp_curves[0] if page.pane_canvas(0)._amp_curves else None
    win.do_fft()
    assert lookups
    assert {key[0] for key in lookups} == {fid_b}
    assert {key[1] for key in lookups} == {"torque"}
    assert plotted
    assert plotted[0] is page.peer_cards()[0].canvas
    assert all(canvas is not page.pane_canvas(0) for canvas in plotted)
    if host_curve is not None and page.pane_canvas(0)._amp_curves:
        assert page.pane_canvas(0)._amp_curves[0] is host_curve


def test_late_completion_paints_the_view_that_dispatched_it(two_file_win, monkeypatch):
    win = two_file_win
    fid_a, fid_b = list(win.files)
    _enter(win, "fft_time")
    mgr, host, peer = _pair(win, "fft_time")
    _stamp(win, "fft_time", host, window="hanning", t_win_s=2.0)
    _stamp(win, "fft_time", peer, window="hamming", t_win_s=1.0)
    for state in (host, peer):
        state.attached_file_ids = [fid_a, fid_b]
    peer.add_pane()
    host.panes[0].sources = [(fid_a, "speed")]
    peer.panes[0].sources = [(fid_b, "torque")]
    peer.panes[1].sources = [(fid_b, "speed")]
    third_idx = mgr.new_view(activate=False)
    third = mgr.get(third_idx)
    third.panes[0].sources = [(fid_a, "speed")]
    assert win.open_comparison("fft_time", host.view_id, peer.view_id)
    page = win._analysis_page("fft_time")

    painted = []
    monkeypatch.setattr(
        win, "_render_fft_time_on",
        lambda canvas, result, p, source=None: painted.append((canvas, source)),
    )
    result = SimpleNamespace(
        metadata={"frames": 6},
        params=SimpleNamespace(nfft=128),
    )
    ctx = {
        "view_id": peer.view_id,
        "pane_idx": 1,
        "pane_token": id(peer.panes[1]),
        "source": tuple(peer.panes[1].sources[0]),
    }
    win._on_fft_time_render_requested(ctx, result, False)
    assert painted == [(page.peer_cards()[1].canvas, ctx["source"])]
    assert "6" not in win.statusBar.currentMessage()

    assert win.focus_comparison("fft_time", peer.view_id, 1)
    painted.clear()
    win._on_fft_time_render_requested(ctx, result, True)
    assert painted == [(page.peer_cards()[1].canvas, ctx["source"])]
    assert "6" in win.statusBar.currentMessage()

    hidden = {
        "view_id": third.view_id,
        "pane_idx": 0,
        "pane_token": id(third.panes[0]),
        "source": tuple(third.panes[0].sources[0]),
    }
    assert win._fft_time_completion_decision(hidden) == "keep"
    mismatched = dict(ctx, analysis_key=("stale", "key"))
    assert win._fft_time_completion_decision(mismatched) == "reject"
    win.close_comparison("fft_time")
    assert win._fft_time_completion_decision(ctx) == "keep"

    _enter(win, "order")
    order_mgr, order_host, order_peer = _pair(win, "order")
    _stamp(win, "order", order_host, window="hanning")
    _stamp(win, "order", order_peer, window="hamming")
    order_host.panes[0].sources = [(fid_a, "speed")]
    order_peer.panes[0].sources = [(fid_b, "torque")]
    order_peer.panes[0].rpm_source = (fid_b, "speed")
    assert win.open_comparison("order", order_host.view_id, order_peer.view_id)
    order_page = win._analysis_page("order")
    order_painted = []
    monkeypatch.setattr(
        win, "_render_order_on",
        lambda canvas, result, source=None: order_painted.append((canvas, source)),
    )
    order_ctx = {
        "view_id": order_peer.view_id,
        "pane_idx": 0,
        "pane_token": id(order_peer.panes[0]),
        "source": tuple(order_peer.panes[0].sources[0]),
    }
    order_result = SimpleNamespace(times=[0.0, 1.0], orders=[1.0, 2.0])
    win._on_order_job_finished(order_ctx, order_result)
    assert order_painted == [(
        order_page.peer_cards()[0].canvas, order_ctx["source"],
    )]
    assert win._order_completion_decision(
        dict(order_ctx, analysis_key=("stale", "order"))
    ) == "reject"
    win.close_comparison("order")
    assert win._order_completion_decision(order_ctx) == "keep"
    assert win._comparison().running_timers() == []


def test_compute_dispatch_uses_the_focused_view(two_file_win, monkeypatch):
    win = two_file_win
    fid_a, fid_b = list(win.files)

    _enter(win, "fft_time")
    _mgr, host, peer = _pair(win, "fft_time")
    _stamp(win, "fft_time", host, window="hanning", t_win_s=2.0)
    _stamp(win, "fft_time", peer, window="hamming", t_win_s=1.0)
    host.panes[0].sources = [(fid_a, "speed")]
    peer.panes[0].sources = [(fid_b, "torque")]
    peer.panes[0].time_range = (0.1, 0.4)
    host.attached_file_ids = [fid_a, fid_b]
    peer.attached_file_ids = [fid_a, fid_b]
    assert win.open_comparison("fft_time", host.view_id, peer.view_id)
    assert win.focus_comparison("fft_time", peer.view_id, 0)
    batched = []
    monkeypatch.setattr(
        win._fft_time_coordinator, "request_batch",
        lambda candidates: batched.extend(candidates) or 0,
    )
    win.do_fft_time()
    assert batched
    assert all(item["view_id"] == peer.view_id for item in batched)
    assert all(item["source"] == (fid_b, "torque") for item in batched)
    assert batched[0]["time_range"] == (0.1, 0.4)

    _enter(win, "order")
    _mgr, host, peer = _pair(win, "order")
    _stamp(win, "order", host, window="hanning")
    _stamp(win, "order", peer, window="flattop")
    host.attached_file_ids = [fid_a, fid_b]
    peer.attached_file_ids = [fid_a, fid_b]
    host.panes[0].sources = [(fid_a, "speed")]
    peer.panes[0].sources = [(fid_b, "torque")]
    peer.panes[0].rpm_source = (fid_b, "speed")
    assert win.open_comparison("order", host.view_id, peer.view_id)
    assert win.focus_comparison("order", peer.view_id, 0)
    built = []

    def _fake_order_job(pane_idx, fid, ch, rpm, *, state=None, warn=True):
        built.append((None if state is None else state.view_id, (fid, ch), rpm))
        return (lambda worker: None), {
            "view_id": None if state is None else state.view_id,
            "pane_idx": pane_idx,
            "source": (fid, ch),
        }

    monkeypatch.setattr(win, "_build_order_job", _fake_order_job)
    monkeypatch.setattr(win, "_start_order_batch", lambda jobs: built.append("started"))
    win.do_order_time()
    assert ("started" in built)
    assert (peer.view_id, (fid_b, "torque"), (fid_b, "speed")) in built

    _enter(win, "frf")
    _mgr, host, peer = _pair(win, "frf")
    _stamp(win, "frf", host, estimator="h1")
    _stamp(win, "frf", peer, estimator="h2")
    host.attached_file_ids = [fid_a, fid_b]
    peer.attached_file_ids = [fid_a, fid_b]
    host.panes[0].input_source = (fid_a, "speed")
    host.panes[0].output_source = (fid_a, "torque")
    peer.panes[0].input_source = (fid_b, "torque")
    peer.panes[0].output_source = (fid_b, "speed")
    assert win.open_comparison("frf", host.view_id, peer.view_id)
    assert win.inspector.frf_ctx.combo_estimator.currentData() == "h1"
    assert win.focus_comparison("frf", peer.view_id, 0)
    assert win.inspector.frf_ctx.combo_estimator.currentData() == "h2"
    requested = []
    monkeypatch.setattr(
        win, "_build_frf_candidate",
        lambda state, pane_idx, force=False: {
            "view_id": state.view_id,
            "pane_idx": pane_idx,
            "job": None,
        },
    )
    monkeypatch.setattr(
        win._frf_coordinator, "request",
        lambda candidate: requested.append(candidate) or True,
    )
    assert win.do_frf() is True
    assert requested[0]["view_id"] == peer.view_id
    assert requested[0]["pane_idx"] == 0
    assert host.params["estimator"] == "h1"
    assert peer.params["estimator"] == "h2"


def test_relation_survives_rename_and_ends_when_the_peer_is_deleted(two_file_win):
    win = two_file_win
    fid_a, fid_b = list(win.files)
    _enter(win, "fft")
    mgr, host, peer = _pair(win, "fft")
    host.panes[0].sources = [(fid_a, "speed")]
    peer.panes[0].sources = [(fid_b, "torque")]
    for state in (host, peer):
        state.attached_file_ids = [fid_a, fid_b]
    comp = win._comparison()
    assert win.open_comparison("fft", host.view_id, peer.view_id)
    host_id, peer_id = host.view_id, peer.view_id

    win._on_analysis_view_rename("fft", 0, "Alpha")
    mgr.reorder(1, 0)
    assert comp.displayed("fft") == (host_id, peer_id)
    assert comp.peer_of("fft", host_id) == peer_id
    assert mgr.get(mgr.active).view_id == host_id

    peer_idx = next(i for i, state in enumerate(mgr.views) if state.view_id == peer_id)
    win._on_analysis_switch("fft", peer_idx)
    assert mgr.get(mgr.active).view_id == host_id
    assert comp.focused("fft")[0] == peer_id
    assert comp.peer_of("fft", peer_id) is None
    assert comp.peer_of("fft", host_id) == peer_id

    third_idx = mgr.new_view(activate=True)
    third = mgr.get(third_idx)
    assert not comp.is_open("fft")
    assert comp.peer_of("fft", third.view_id) is None
    assert comp.peer_of("fft", host_id) == peer_id
    host_idx = next(i for i, state in enumerate(mgr.views) if state.view_id == host_id)
    mgr.set_active(host_idx)
    assert comp.is_open("fft")
    assert comp.displayed("fft") == (host_id, peer_id)

    store_before = len(win.analysis_caches["fft"]._store)
    copy_idx = mgr.duplicate(host_idx)
    copied = mgr.get(copy_idx)
    assert copied.view_id != host_id
    assert comp.peer_of("fft", copied.view_id) is None
    assert comp.peer_of("fft", host_id) == peer_id
    assert comp.canvas_for("fft", copied.view_id, 0) is None
    assert len(win.analysis_caches["fft"]._store) == store_before

    host_idx = next(i for i, state in enumerate(mgr.views) if state.view_id == host_id)
    mgr.set_active(host_idx)
    assert comp.displayed("fft") == (host_id, peer_id)
    peer_idx = next(i for i, state in enumerate(mgr.views) if state.view_id == peer_id)
    win._on_analysis_delete("fft", peer_idx)
    assert not comp.is_open("fft")
    assert comp.peer_of("fft", host_id) is None
    assert not any(slot[1] == str(peer_id) for slot in win._analysis_pins._slots)
    win._teardown_comparison_display()
    assert comp.running_timers() == []


def test_every_section_uses_one_comparison_owner(two_file_win, monkeypatch):
    win = two_file_win
    fid_a, fid_b = list(win.files)
    owner = win._analysis_context.comparison
    calls = _arm_compute_spies(monkeypatch, win)
    for section, left, right in (
        ("fft", {"window": "hanning", "t_win_s": 2.0}, {"window": "hamming", "t_win_s": 1.0}),
        ("fft_time", {"window": "hanning", "t_win_s": 2.0}, {"window": "hamming", "t_win_s": 1.0}),
        ("order", {"window": "hanning"}, {"window": "hamming"}),
        ("frf", {"estimator": "h1"}, {"estimator": "h2"}),
    ):
        page = _enter(win, section)
        _mgr, host, peer = _pair(win, section)
        _stamp(win, section, host, **left)
        _stamp(win, section, peer, **right)
        host.attached_file_ids = [fid_a, fid_b]
        peer.attached_file_ids = [fid_a, fid_b]
        if section == "frf":
            host.panes[0].input_source = (fid_a, "speed")
            host.panes[0].output_source = (fid_a, "torque")
            peer.panes[0].input_source = (fid_b, "torque")
            peer.panes[0].output_source = (fid_b, "speed")
            host.panes[0].effective_time_range = (0.0, 1.0)
            peer.panes[0].effective_time_range = (0.0, 1.0)
        else:
            host.panes[0].sources = [(fid_a, "speed")]
            peer.panes[0].sources = [(fid_b, "torque")]
        looked = []
        caches = []
        if section != "frf":
            cache = win.analysis_caches[section]
            original = cache.get

            def _get(key, _original=original, _looked=looked):
                _looked.append(key)
                return _original(key)

            monkeypatch.setattr(cache, "get", _get)
            caches.append(cache)
        assert win.open_comparison(section, host.view_id, peer.view_id)
        assert win._comparison() is owner
        assert owner.displayed(section) == (str(host.view_id), str(peer.view_id))
        assert len(page.findChildren(ViewTabBar)) == 1
        assert page.findChild(QSplitter, "analysisComparisonSplit") is not None
        assert len(host.panes) <= MAX_PANES and len(peer.panes) <= MAX_PANES
        if section == "frf":
            host_key = win._frf_cache_key_for_pane(host, host.panes[0])
            peer_key = win._frf_cache_key_for_pane(peer, peer.panes[0])
            assert host_key is not None and peer_key is not None
            assert host_key != peer_key
            host_result = _frf_result(1.0)
            peer_result = _frf_result(2.0)
            win.analysis_caches["frf"].put(host_key, host_result)
            win.analysis_caches["frf"].put(peer_key, peer_result)
            win._render_comparison_view("frf", host)
            win._render_comparison_view("frf", peer)
            assert page.pane_canvas(0)._result is host_result
            assert page.peer_cards()[0].canvas._result is peer_result
        else:
            host_key = win._analysis_cache_key_for_view_source(
                section, host, host.panes[0], 0, fid_a, "speed",
            )
            peer_key = win._analysis_cache_key_for_view_source(
                section, peer, peer.panes[0], 0, fid_b, "torque",
            )
            assert host_key != peer_key
            assert host_key in looked and peer_key in looked
        assert not owner.axis_linked(section)
        assert win.chart_stack.current_mode() == section
        assert win._ultraview_sheet is None
        assert len(_mgr.views) == 2
        win.close_comparison(section)
        QApplication.processEvents()
    assert calls == []
    assert owner.running_timers() == []


def test_axis_link_does_not_change_analysis_params(two_file_win):
    win = two_file_win
    fid_a, fid_b = list(win.files)
    _enter(win, "fft")
    _mgr, host, peer = _pair(win, "fft")
    _stamp(win, "fft", host, window="hanning", t_win_s=2.0)
    _stamp(win, "fft", peer, window="hamming", t_win_s=1.0)
    host.panes[0].sources = [(fid_a, "speed")]
    peer.panes[0].sources = [(fid_b, "torque")]
    host.panes[0].time_range = (0.0, 0.5)
    peer.panes[0].time_range = (0.2, 0.8)
    assert win.open_comparison("fft", host.view_id, peer.view_id)
    before = (
        dict(host.params), dict(peer.params),
        host.panes[0].time_range, peer.panes[0].time_range,
    )
    assert win.set_comparison_axis_linked("fft", True) is True
    assert win._comparison().axis_linked("fft") is True
    assert win.set_comparison_levels_locked("fft", True) is False
    assert win._comparison().levels_locked("fft") is False
    assert (
        dict(host.params), dict(peer.params),
        host.panes[0].time_range, peer.panes[0].time_range,
    ) == before
    assert host.compare.get("x_linked", True) is True
    win.set_comparison_axis_linked("fft", False)
    assert not win._comparison().axis_linked("fft")
    win._teardown_comparison_display()
    assert win._comparison().running_timers() == []
