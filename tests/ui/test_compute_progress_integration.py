from types import SimpleNamespace

import numpy as np

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window import _fft_mixin as fft_mod
from mf4_analyzer.ui.plot_risk import PlotRisk, PlotRiskLevel


def _risk(level):
    return PlotRisk(
        level=level,
        channel_count=9 if level is PlotRiskLevel.DANGER else 1,
        series_count=9 if level is PlotRiskLevel.DANGER else 1,
        sample_total=6_000_000 if level is PlotRiskLevel.DANGER else 2,
        max_channel_samples=6_000_000 if level is PlotRiskLevel.DANGER else 2,
        filter_enabled=False,
        reasons=("test",),
    )


def _time_row():
    return (
        "speed",
        True,
        np.array([0.0, 1.0], dtype=float),
        np.array([1.0, 2.0], dtype=float),
        "#2563eb",
        "rpm",
        "f1",
    )


def _make_time_window(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    win.files["f1"] = object()
    monkeypatch.setattr(
        win.channel_list,
        "get_checked_channels",
        lambda: [("f1", "speed", "#2563eb")],
    )
    monkeypatch.setattr(
        win.chart_stack,
        "plot_mode_for_canvas",
        lambda _canvas: "subplot",
    )
    monkeypatch.setattr(
        win,
        "_estimate_current_time_overlay_risk",
        lambda _mode, _checked: _risk(PlotRiskLevel.OK),
    )
    monkeypatch.setattr(win.canvas_time, "set_tick_density", lambda *_args: None)
    return win


def _install_progress_spies(monkeypatch, win, order):
    active_token = object()

    def begin(label, total=None, token=None):
        order.append(("begin", label))
        return active_token

    def finish(label=None, token=None):
        order.append(("finish", token))

    monkeypatch.setattr(win, "_begin_compute_progress", begin)
    monkeypatch.setattr(win, "_finish_compute_progress", finish)
    return active_token


def test_time_domain_progress_wraps_build_and_plot(qapp, qtbot, monkeypatch):
    win = _make_time_window(qapp, qtbot, monkeypatch)
    order = []
    token = _install_progress_spies(monkeypatch, win, order)

    def build(*_args, **_kwargs):
        order.append(("build", None))
        return [_time_row()]

    def plot(*_args, **_kwargs):
        order.append(("plot", None))

    monkeypatch.setattr(win, "_build_time_plot_data", build)
    monkeypatch.setattr(win.canvas_time, "plot_channels", plot)

    win._plot_time_on_canvas(win.canvas_time, update_primary_ui=True)

    assert order == [
        ("begin", "时间域绘制中"),
        ("build", None),
        ("plot", None),
        ("finish", token),
    ]


def test_time_domain_progress_finishes_on_empty_data(qapp, qtbot, monkeypatch):
    win = _make_time_window(qapp, qtbot, monkeypatch)
    order = []
    token = _install_progress_spies(monkeypatch, win, order)

    def build(*_args, **_kwargs):
        order.append(("build", None))
        return []

    monkeypatch.setattr(win, "_build_time_plot_data", build)
    monkeypatch.setattr(
        win.canvas_time,
        "plot_channels",
        lambda *_args, **_kwargs: order.append(("plot", None)),
    )

    win._plot_time_on_canvas(win.canvas_time, update_primary_ui=True)

    assert order == [
        ("begin", "时间域绘制中"),
        ("build", None),
        ("finish", token),
    ]


def test_time_domain_danger_cancel_does_not_begin_progress(
    qapp, qtbot, monkeypatch
):
    win = _make_time_window(qapp, qtbot, monkeypatch)
    order = []
    _install_progress_spies(monkeypatch, win, order)
    monkeypatch.setattr(
        win.chart_stack,
        "plot_mode_for_canvas",
        lambda _canvas: "overlay",
    )
    monkeypatch.setattr(
        win,
        "_estimate_current_time_overlay_risk",
        lambda _mode, _checked: _risk(PlotRiskLevel.DANGER),
    )
    monkeypatch.setattr(
        win,
        "_confirm_overlay_risk",
        lambda _risk: order.append(("confirm", None)) or False,
    )
    monkeypatch.setattr(
        win,
        "_build_time_plot_data",
        lambda *_args, **_kwargs: order.append(("build", None)) or [_time_row()],
    )
    monkeypatch.setattr(
        win.canvas_time,
        "plot_channels",
        lambda *_args, **_kwargs: order.append(("plot", None)),
    )

    win._plot_time_on_canvas(
        win.canvas_time,
        update_primary_ui=True,
        user_initiated=True,
    )

    assert order == [("confirm", None)]


def _make_fft_window(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    t = np.arange(16, dtype=float) / 16.0
    sig = np.sin(2.0 * np.pi * t)
    fs = 16.0
    win.files["f1"] = SimpleNamespace()
    monkeypatch.setattr(win, "_get_sig", lambda: (t, sig, fs))
    monkeypatch.setattr(win, "_check_uniform_or_prompt", lambda *_args: True)
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "fft")
    monkeypatch.setattr(
        win.inspector.fft_ctx,
        "current_signal",
        lambda: ("f1", "speed"),
    )
    monkeypatch.setattr(
        win.inspector.fft_ctx,
        "current_params",
        lambda: {
            "window": "hann",
            "nfft": 16,
            "nfft_mode": "fixed",
            "avg_mode": "单帧",
            "overlap": 0,
            "x_auto": True,
            "y_auto": True,
            "amp_y": "Linear",
        },
    )
    monkeypatch.setattr(win.inspector.fft_ctx, "fs", lambda: fs)
    monkeypatch.setattr(win.inspector.fft_ctx.combo_sig, "currentText", lambda: "speed")
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: False)
    monkeypatch.setattr(win.inspector.top, "tick_density", lambda: (10, 8))
    monkeypatch.setattr(win.canvas_fft, "set_tick_density", lambda *_args: None)
    monkeypatch.setattr(win, "_remember_batch_preset", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(win, "toast", lambda *_args, **_kwargs: None)
    return win


def test_fft_single_progress_wraps_compute_and_plot(qapp, qtbot, monkeypatch):
    win = _make_fft_window(qapp, qtbot, monkeypatch)
    order = []
    token = _install_progress_spies(monkeypatch, win, order)

    def compute(*_args, **_kwargs):
        order.append(("compute", None))
        return (
            np.array([0.0, 1.0, 2.0], dtype=float),
            np.array([0.0, 2.0, 1.0], dtype=float),
            np.array([0.0, 4.0, 1.0], dtype=float),
        )

    def plot(*_args, **_kwargs):
        order.append(("plot", None))

    monkeypatch.setattr(win, "_fft_compute_arrays", compute)
    monkeypatch.setattr(win.canvas_fft, "plot_spectra", plot)

    win._do_fft_single()

    assert order == [
        ("begin", "FFT 计算中"),
        ("compute", None),
        ("plot", None),
        ("finish", token),
    ]


def test_fft_single_progress_finishes_when_compute_raises(
    qapp, qtbot, monkeypatch
):
    win = _make_fft_window(qapp, qtbot, monkeypatch)
    order = []
    token = _install_progress_spies(monkeypatch, win, order)

    def compute(*_args, **_kwargs):
        order.append(("compute", None))
        raise RuntimeError("boom")

    monkeypatch.setattr(win, "_fft_compute_arrays", compute)
    monkeypatch.setattr(
        fft_mod.QMessageBox,
        "critical",
        lambda *_args, **_kwargs: order.append(("critical", None)),
    )

    win._do_fft_single()

    assert order == [
        ("begin", "FFT 计算中"),
        ("compute", None),
        ("finish", token),
        ("critical", None),
    ]


def test_fft_multi_source_progress_wraps_cache_misses_only(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()

    state = win.analysis_managers["fft"].get(win.analysis_managers["fft"].active)
    state.panes[0].sources = [("f1", "speed"), ("f2", "speed")]
    win.files["f1"] = SimpleNamespace()
    win.files["f2"] = SimpleNamespace()

    order = []
    token_by_label = []

    def begin(label, total=None, token=None):
        tok = object()
        token_by_label.append(tok)
        order.append(("begin", label))
        return tok

    def finish(label=None, token=None):
        order.append(("finish", token))

    monkeypatch.setattr(win, "_begin_compute_progress", begin)
    monkeypatch.setattr(win, "_finish_compute_progress", finish)
    monkeypatch.setattr(win, "_capture_active_analysis_view", lambda _section: None)
    monkeypatch.setattr(win, "_analysis_channel_color_map", lambda: {})
    monkeypatch.setattr(win, "_check_uniform_or_prompt", lambda *_args: True)
    monkeypatch.setattr(win, "_pane_time_range_for", lambda *_args: None)
    monkeypatch.setattr(win, "_emit_compute_feedback", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        win.inspector.fft_ctx,
        "current_params",
        lambda: {
            "window": "hann",
            "nfft": 16,
            "nfft_mode": "fixed",
            "avg_mode": "单帧",
            "overlap": 0,
        },
    )
    monkeypatch.setattr(
        win,
        "_resolve_fft_effective_params",
        lambda params, _n, _fs: dict(params),
    )
    monkeypatch.setattr(
        win,
        "_fft_analysis_cache_key",
        lambda fid, ch, _params, _time_range: (fid, ch),
    )

    def fetch(fid, _ch, time_range=None):
        marker = 1.0 if fid == "f1" else 2.0
        return np.full(16, marker, dtype=float), 16.0

    def compute(sig, _fs, _params):
        order.append(("compute", int(sig[0])))
        return (
            np.array([0.0, 1.0], dtype=float),
            np.array([1.0, 2.0], dtype=float),
            np.array([1.0, 4.0], dtype=float),
        )

    monkeypatch.setattr(win, "_fft_fetch_signal", fetch)
    monkeypatch.setattr(win, "_fft_compute_arrays", compute)
    monkeypatch.setattr(
        win,
        "_fft_entry_from_cache",
        lambda result, fid, ch, color, time_range=None: {"fid": fid, "ch": ch},
    )
    monkeypatch.setattr(
        win,
        "_plot_fft_entries",
        lambda entries, canvas: order.append(("plot", len(entries))),
    )

    win.do_fft()

    assert [item[0] for item in order] == [
        "begin",
        "compute",
        "finish",
        "begin",
        "compute",
        "finish",
        "plot",
    ]
    assert order[0] == ("begin", "FFT 计算中")
    assert order[1] == ("compute", 1)
    assert order[2] == ("finish", token_by_label[0])
    assert order[3] == ("begin", "FFT 计算中")
    assert order[4] == ("compute", 2)
    assert order[5] == ("finish", token_by_label[1])

    order.clear()
    token_by_label.clear()

    win.do_fft()

    assert order == [("plot", 2)]
    assert token_by_label == []


def test_fft_time_progress_maps_half_single_job_to_half_total(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    calls = []
    win._fft_time_progress_token = token
    win._fft_time_progress_total_jobs = 1
    win._fft_time_progress_completed_jobs = 0

    monkeypatch.setattr(
        win,
        "_update_compute_progress",
        lambda current, total, label=None, token=None: calls.append(
            (current, total, label, token)
        ),
    )

    win._on_fft_time_progress(50, 100)

    assert calls == [(500, 1000, "FFT-时间 1/1", token)]


def test_fft_time_progress_aggregates_second_job_halfway(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    calls = []
    win._fft_time_progress_token = token
    win._fft_time_progress_total_jobs = 2
    win._fft_time_progress_completed_jobs = 1

    monkeypatch.setattr(
        win,
        "_update_compute_progress",
        lambda current, total, label=None, token=None: calls.append(
            (current, total, label, token)
        ),
    )

    win._on_fft_time_progress(50, 100)

    assert calls == [(750, 1000, "FFT-时间 2/2", token)]


def test_fft_time_thread_done_keeps_progress_for_remaining_job(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    started = []
    finished = []
    win._fft_time_queue = [("pane1", "f2", "speed")]
    win._fft_time_progress_token = token
    win._fft_time_progress_total_jobs = 2
    win._fft_time_progress_completed_jobs = 0

    monkeypatch.setattr(
        win,
        "_start_next_fft_time_job",
        lambda: started.append("next"),
    )
    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._on_fft_time_thread_done()

    assert win._fft_time_progress_completed_jobs == 1
    assert win._fft_time_progress_token is token
    assert finished == []
    assert started == ["next"]


def test_fft_time_thread_done_never_finishes_while_queue_remains(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    started = []
    finished = []
    win._fft_time_queue = [("pane1", "f2", "speed")]
    win._fft_time_progress_token = token
    win._fft_time_progress_total_jobs = 1
    win._fft_time_progress_completed_jobs = 0

    monkeypatch.setattr(
        win,
        "_start_next_fft_time_job",
        lambda: started.append("next"),
    )
    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._on_fft_time_thread_done()

    assert win._fft_time_progress_completed_jobs == 1
    assert win._fft_time_progress_token is token
    assert finished == []
    assert started == ["next"]


def test_fft_time_thread_done_finishes_progress_on_final_job(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    finished = []
    win._fft_time_queue = []
    win._fft_time_progress_token = token
    win._fft_time_progress_total_jobs = 2
    win._fft_time_progress_completed_jobs = 1

    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._on_fft_time_thread_done()

    assert win._fft_time_progress_completed_jobs == 2
    assert finished == [((), {"token": token})]
    assert win._fft_time_progress_token is None


def test_fft_time_skipped_queue_items_advance_and_finish_progress(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    finished = []
    win._fft_time_queue = [(0, "f1", "missing"), (1, "f2", "short")]
    win._fft_time_progress_token = token
    win._fft_time_progress_total_jobs = 2
    win._fft_time_progress_completed_jobs = 0

    monkeypatch.setattr(win, "_pane_time_range_for", lambda *_args: None)
    monkeypatch.setattr(win, "_dispatch_fft_time_job", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._start_next_fft_time_job()

    assert win._fft_time_progress_completed_jobs == 2
    assert finished == [((), {"token": token})]
    assert win._fft_time_progress_token is None
    assert win._fft_time_queue == []


def _fft_time_progress_params():
    return {
        "fs": 16.0,
        "window": "hann",
        "nfft": 16,
        "nfft_effective": 16,
        "nfft_mode": "fixed",
        "overlap": 0.0,
        "remove_mean": False,
        "weighting": "None",
    }


def _make_fft_time_dispatch_window(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    state = win.analysis_managers["fft_time"].get(
        win.analysis_managers["fft_time"].active
    )
    state.panes[0].sources = [("f1", "speed")]
    win.files["f1"] = SimpleNamespace()
    params = _fft_time_progress_params()

    monkeypatch.setattr(win, "_capture_active_analysis_view", lambda _section: None)
    monkeypatch.setattr(win.inspector.fft_time_ctx, "get_params", lambda: params)
    monkeypatch.setattr(win, "_pane_time_range_for", lambda *_args: None)
    monkeypatch.setattr(
        win,
        "_fft_time_effective_params_for_source",
        lambda p, fid, ch, time_range: (dict(p), (0.0, 1.0)),
    )
    monkeypatch.setattr(
        win,
        "_fft_time_analysis_cache_key",
        lambda fid, ch, p, pane_idx: ("analysis", fid, ch, pane_idx),
    )
    monkeypatch.setattr(
        win,
        "_fft_time_cache_key",
        lambda key_params: ("lru", key_params["fid"], key_params["channel"]),
    )
    monkeypatch.setattr(win, "_render_fft_time_on", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        win,
        "_emit_compute_feedback",
        lambda *_args, **_kwargs: None,
    )
    return win


def test_fft_time_do_begins_progress_for_cache_miss_only(
    qapp, qtbot, monkeypatch
):
    win = _make_fft_time_dispatch_window(qapp, qtbot, monkeypatch)
    progress_token = object()
    begin_calls = []
    started = []

    monkeypatch.setattr(
        win,
        "_begin_compute_progress",
        lambda label, total=None, token=None: begin_calls.append((label, total))
        or progress_token,
    )
    monkeypatch.setattr(
        win,
        "_fft_time_cache_get",
        lambda _key: None,
    )
    monkeypatch.setattr(
        win,
        "_start_next_fft_time_job",
        lambda: started.append(list(win._fft_time_queue)),
    )

    win.do_fft_time()

    assert begin_calls == [("FFT-时间 1/1", 1000)]
    assert win._fft_time_progress_token is progress_token
    assert win._fft_time_progress_total_jobs == 1
    assert win._fft_time_progress_completed_jobs == 0
    assert started == [[(0, "f1", "speed")]]

    begin_calls.clear()
    started.clear()
    cached = SimpleNamespace(metadata={"frames": 1})
    monkeypatch.setattr(win, "_fft_time_cache_get", lambda _key: cached)

    win.do_fft_time()

    assert begin_calls == []
    assert started == []
    assert win._fft_time_progress_token is None
    assert win._fft_time_progress_total_jobs == 0
    assert win._fft_time_queue == []
