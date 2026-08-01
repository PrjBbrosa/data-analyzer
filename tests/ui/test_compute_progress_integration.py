from types import SimpleNamespace

import numpy as np

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window.window import TimePlotBuildResult
from mf4_analyzer.ui.main_window import _order_mixin as order_mod
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


def _time_result(*rows):
    result = TimePlotBuildResult(rows=list(rows))
    result.attempted_channel_keys.add(("f1", "speed"))
    if rows:
        result.successful_channel_keys.add(("f1", "speed"))
    return result


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

    def begin(label, total=None, token=None, process_events=True):
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
        return _time_result(_time_row())

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
        return _time_result()

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
        lambda *_args, **_kwargs: (
            order.append(("build", None)) or _time_result(_time_row())
        ),
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

    def begin(label, total=None, token=None, process_events=True):
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


def test_fft_time_service_progress_maps_half_single_job_to_half_total(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    calls = []
    win._analysis_progress_tokens["fft_time"] = token
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (0, 1)
    )

    monkeypatch.setattr(
        win,
        "_update_compute_progress",
        lambda current, total, label=None, token=None: calls.append(
            (current, total, label, token)
        ),
    )

    win._on_fft_time_job_progress(500, 1000)

    assert calls == [(500, 1000, "FFT-时间 1/1", token)]


def test_fft_time_service_progress_uses_second_job_batch_counts(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    calls = []
    win._analysis_progress_tokens["fft_time"] = token
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (1, 2)
    )

    monkeypatch.setattr(
        win,
        "_update_compute_progress",
        lambda current, total, label=None, token=None: calls.append(
            (current, total, label, token)
        ),
    )

    win._on_fft_time_job_progress(750, 1000)

    assert calls == [(750, 1000, "FFT-时间 2/2", token)]


def test_fft_time_service_progress_noops_without_ui_token(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    calls = []
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (0, 1)
    )

    monkeypatch.setattr(
        win,
        "_update_compute_progress",
        lambda current, total, label=None, token=None: calls.append(
            (current, total, label, token)
        ),
    )

    win._on_fft_time_job_progress(500, 1000)

    assert calls == []


def test_fft_time_service_progress_keeps_ui_active_before_final_job(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    finished = []
    win._analysis_progress_tokens["fft_time"] = token
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (1, 2)
    )
    monkeypatch.setattr(win._analysis_jobs, "is_running", lambda _section: True)
    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._on_fft_time_job_progress(500, 1000)

    assert win._analysis_progress_tokens["fft_time"] is token
    assert finished == []


def test_fft_time_service_progress_keeps_ui_active_while_section_running(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    finished = []
    win._analysis_progress_tokens["fft_time"] = token
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (1, 2)
    )
    monkeypatch.setattr(win._analysis_jobs, "is_running", lambda _section: True)
    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._on_fft_time_job_progress(500, 1000)

    assert win._analysis_progress_tokens["fft_time"] is token
    assert finished == []


def test_fft_time_service_final_progress_finishes_ui_outcome(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    finished = []
    win._analysis_progress_tokens["fft_time"] = token
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (2, 2)
    )
    monkeypatch.setattr(win._analysis_jobs, "is_running", lambda _section: False)

    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._on_fft_time_job_progress(1000, 1000)

    assert finished == [((), {"token": token})]
    assert "fft_time" not in win._analysis_progress_tokens


def test_fft_time_service_skips_advance_and_finish_ui_progress(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    finished = []
    win._analysis_progress_tokens["fft_time"] = token
    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._analysis_jobs.submit_batch(
        "fft_time", [(None, {"skip": "missing"}), (None, {"skip": "short"})]
    )

    assert finished == [((), {"token": token})]
    assert "fft_time" not in win._analysis_progress_tokens


def _fft_time_service_params():
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
    params = _fft_time_service_params()

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
    monkeypatch.setattr(win, "_render_fft_time_on", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        win,
        "_emit_compute_feedback",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        win,
        "_build_fft_time_job",
        lambda pane_idx, fid, ch, raw_params, **_kwargs: (
            (lambda _worker: object()),
            {
                "render_params": dict(raw_params),
                "analysis_key": ("analysis", fid, ch, pane_idx),
                "pane_idx": pane_idx,
                "source": (fid, ch),
            },
        ),
    )
    return win


def test_fft_time_do_begins_progress_for_cache_miss_only(
    qapp, qtbot, monkeypatch
):
    win = _make_fft_time_dispatch_window(qapp, qtbot, monkeypatch)
    progress_token = object()
    begin_calls = []
    submitted = []

    monkeypatch.setattr(
        win,
        "_begin_compute_progress",
        lambda label, total=None, token=None, process_events=True:
            begin_calls.append((label, total, process_events))
        or progress_token,
    )
    monkeypatch.setattr(
        win.analysis_caches["fft_time"],
        "get",
        lambda _key: None,
    )
    monkeypatch.setattr(
        win._analysis_jobs,
        "submit_batch",
        lambda section, jobs, **_kwargs: submitted.append((section, list(jobs))),
    )

    win.do_fft_time()

    assert begin_calls == [("FFT-时间 1/1", 1000, False)]
    assert win._analysis_progress_tokens["fft_time"] is progress_token
    assert submitted[0][0] == "fft_time"
    assert submitted[0][1][0][1]["source"] == ("f1", "speed")

    # The submit spy intentionally does not run the service completion path.
    win._analysis_progress_tokens.pop("fft_time")
    begin_calls.clear()
    submitted.clear()
    cached = SimpleNamespace(metadata={"frames": 1})
    monkeypatch.setattr(
        win.analysis_caches["fft_time"], "get", lambda _key: cached
    )

    win.do_fft_time()

    assert begin_calls == []
    assert submitted == []
    assert "fft_time" not in win._analysis_progress_tokens


def test_order_service_progress_maps_quarter_single_job_to_quarter_total(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    calls = []
    win._analysis_progress_tokens["order"] = token
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (0, 1)
    )

    monkeypatch.setattr(
        win,
        "_update_compute_progress",
        lambda current, total, label=None, token=None: calls.append(
            (current, total, label, token)
        ),
    )

    win._on_order_job_progress(250, 1000)

    assert calls == [(250, 1000, "阶次 1/1", token)]


def test_order_rpm_for_manual_mode_returns_constant_array(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.inspector.order_ctx.set_rpm_mode("manual")
    win.inspector.order_ctx.spin_manual_rpm.setValue(1234.0)

    rpm = win._order_rpm_for(None, 5)

    assert rpm.tolist() == [1234.0] * 5


def test_order_cache_params_include_manual_rpm_mode_and_value(qapp, qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.inspector.order_ctx.set_rpm_mode("manual")
    win.inspector.order_ctx.spin_manual_rpm.setValue(1234.0)
    p = {
        "nfft": 256,
        "nfft_mode": "fixed",
        "max_order": 20,
        "order_res": 0.1,
        "time_res": 0.05,
        "samples_per_rev": 256,
        "rpm_factor": 1.0,
        "fs": 1000.0,
        "weighting": "None",
        "rpm_mode": "manual",
        "manual_rpm": 1234.0,
    }

    params = win._order_compute_cache_params(p, ("f1", "rpm"), None)

    assert params["rpm_mode"] == "manual"
    assert params["manual_rpm"] == 1234.0
    assert params["rpm_source"] is None

    active_params = win._analysis_compute_params("order")
    assert active_params["rpm_mode"] == "manual"
    assert active_params["manual_rpm"] == 1234.0


def test_order_service_progress_uses_second_job_batch_counts(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    calls = []
    win._analysis_progress_tokens["order"] = token
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (1, 2)
    )

    monkeypatch.setattr(
        win,
        "_update_compute_progress",
        lambda current, total, label=None, token=None: calls.append(
            (current, total, label, token)
        ),
    )

    win._on_order_job_progress(750, 1000)

    assert calls == [(750, 1000, "阶次 2/2", token)]


def test_order_service_progress_noops_without_ui_token(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    calls = []
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (0, 1)
    )

    monkeypatch.setattr(
        win,
        "_update_compute_progress",
        lambda current, total, label=None, token=None: calls.append(
            (current, total, label, token)
        ),
    )

    win._on_order_job_progress(250, 1000)

    assert calls == []


def test_order_service_progress_noops_after_token_clear(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    calls = []
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (0, 1)
    )

    monkeypatch.setattr(
        win,
        "_update_compute_progress",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    win._on_order_job_progress(500, 1000)

    assert calls == []


def test_order_service_progress_keeps_ui_active_before_final_job(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    finished = []
    win._analysis_progress_tokens["order"] = token
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (1, 2)
    )
    monkeypatch.setattr(win._analysis_jobs, "is_running", lambda _section: True)
    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._on_order_job_progress(500, 1000)

    assert win._analysis_progress_tokens["order"] is token
    assert finished == []


def test_order_service_final_progress_finishes_ui_outcome(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    finished = []
    win._analysis_progress_tokens["order"] = token
    monkeypatch.setattr(
        win._analysis_jobs, "progress_counts", lambda _section: (2, 2)
    )
    monkeypatch.setattr(win._analysis_jobs, "is_running", lambda _section: False)

    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._on_order_job_progress(1000, 1000)

    assert finished == [((), {"token": token})]
    assert "order" not in win._analysis_progress_tokens


def test_order_service_skips_advance_and_finish_ui_progress(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    token = object()
    finished = []
    win._analysis_progress_tokens["order"] = token
    monkeypatch.setattr(
        win,
        "_finish_compute_progress",
        lambda *args, **kwargs: finished.append((args, kwargs)),
    )

    win._analysis_jobs.submit_batch(
        "order", [(None, {"skip": "missing"}), (None, {"skip": "short"})]
    )

    assert finished == [((), {"token": token})]
    assert "order" not in win._analysis_progress_tokens


def _make_order_dispatch_window(qapp, qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    state = win.analysis_managers["order"].get(
        win.analysis_managers["order"].active
    )
    state.panes[0].sources = [("f1", "torque")]
    state.panes[0].rpm_source = ("f1", "rpm")
    win.files["f1"] = SimpleNamespace()

    monkeypatch.setattr(win, "_capture_active_analysis_view", lambda _section: None)
    monkeypatch.setattr(
        win,
        "_analysis_cache_key",
        lambda section, fid, ch, rpm_source=None, pane_idx=None: (
            section,
            fid,
            ch,
            rpm_source,
            pane_idx,
        ),
    )
    monkeypatch.setattr(win, "_render_order_on", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        win,
        "_emit_compute_feedback",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        win,
        "_build_order_job",
        lambda pane_idx, fid, ch, rpm_source: (
            (lambda _worker: object()),
            {
                "analysis_key": ("order", fid, ch, rpm_source, pane_idx),
                "pane_idx": pane_idx,
                "source": (fid, ch),
            },
        ),
    )
    return win


def test_order_do_begins_progress_for_cache_miss_only(
    qapp, qtbot, monkeypatch
):
    win = _make_order_dispatch_window(qapp, qtbot, monkeypatch)
    progress_token = object()
    begin_calls = []
    submitted = []

    monkeypatch.setattr(
        win,
        "_begin_compute_progress",
        lambda label, total=None, token=None, process_events=True:
            begin_calls.append((label, total, process_events))
        or progress_token,
    )
    monkeypatch.setattr(win.analysis_caches["order"], "get", lambda _key: None)
    monkeypatch.setattr(
        win._analysis_jobs,
        "submit_batch",
        lambda section, jobs, **_kwargs: submitted.append((section, list(jobs))),
    )

    win.do_order_time()

    assert begin_calls == [("阶次 1/1", 1000, False)]
    assert win._analysis_progress_tokens["order"] is progress_token
    assert submitted[0][0] == "order"
    assert submitted[0][1][0][1]["source"] == ("f1", "torque")

    cached_win = _make_order_dispatch_window(qapp, qtbot, monkeypatch)
    cached_begin_calls = []
    cached_submitted = []
    cached = SimpleNamespace(metadata={"frames": 1})
    monkeypatch.setattr(
        cached_win,
        "_begin_compute_progress",
        lambda label, total=None, token=None, process_events=True:
            cached_begin_calls.append((label, total, process_events))
        or object(),
    )
    monkeypatch.setattr(
        cached_win.analysis_caches["order"],
        "get",
        lambda _key: cached,
    )
    monkeypatch.setattr(
        cached_win._analysis_jobs,
        "submit_batch",
        lambda section, jobs, **_kwargs: cached_submitted.append((section, list(jobs))),
    )

    cached_win.do_order_time()

    assert cached_begin_calls == []
    assert cached_submitted == []
    assert "order" not in cached_win._analysis_progress_tokens


class _FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            try:
                slot(*args)
            except TypeError:
                slot()


class _FakeOrderWorker:
    instances = []

    def __init__(self, job):
        self.job = job
        self.progress = _FakeSignal()
        self.finished = _FakeSignal()
        self.failed = _FakeSignal()
        self.cancelled_called = False
        self.__class__.instances.append(self)

    def moveToThread(self, _thread):
        pass

    def cancelled(self):
        self.cancelled_called = True
        return False

    def cancel(self):
        self.cancelled_called = True

    def run(self):
        result = self.job(self)
        self.finished.emit(result)

    def deleteLater(self):
        pass


class _FakeOrderThread:
    instances = []

    def __init__(self, *_args, **_kwargs):
        self.started = _FakeSignal()
        self.finished = _FakeSignal()
        self.running = False
        self.__class__.instances.append(self)

    def start(self):
        self.running = True

    def quit(self):
        self.running = False
        self.finished.emit()

    def isRunning(self):
        return self.running

    def deleteLater(self):
        pass


class _FakeFrame:
    def __init__(self, **columns):
        self._columns = {
            name: np.asarray(values, dtype=float)
            for name, values in columns.items()
        }
        self.columns = list(self._columns)

    def __getitem__(self, name):
        return SimpleNamespace(values=self._columns[name])


def test_order_job_closure_passes_progress_callback_and_cancel_token(
    qapp, qtbot, monkeypatch
):
    win = MainWindow()
    qtbot.addWidget(win)
    qapp.processEvents()
    n = 128
    t = np.linspace(0.0, 1.0, n)
    win.files["f1"] = SimpleNamespace(
        time_array=t,
        data=_FakeFrame(
            torque=np.sin(t),
            rpm=np.full(n, 1200.0),
        ),
    )
    progress_calls = []
    fake_result = SimpleNamespace(metadata={"frames": 1})

    monkeypatch.setattr(win, "_pane_time_range_for", lambda *_args: None)
    monkeypatch.setattr(win, "_warn_if_order_speed_unsuitable", lambda _rpm: True)
    monkeypatch.setattr(win.inspector.order_ctx, "fs", lambda: 128.0)
    monkeypatch.setattr(win.inspector.order_ctx, "rpm_factor", lambda: 1.0)
    monkeypatch.setattr(
        win.inspector.order_ctx,
        "current_params",
        lambda: {"samples_per_rev": 16},
    )
    monkeypatch.setattr(
        win.inspector.order_ctx,
        "get_params",
        lambda: {
            "nfft": 16,
            "nfft_effective": 16,
            "window": "hanning",
            "max_order": 8.0,
            "order_res": 0.5,
            "time_res": 0.1,
            "weighting": "None",
        },
    )
    monkeypatch.setattr(
        win,
        "_resolve_order_effective_params",
        lambda op, _rpm, _t: dict(
            op,
            nfft_effective=16,
            max_order=8.0,
            order_res=0.5,
            time_res=0.1,
        ),
    )
    monkeypatch.setattr(
        win,
        "_order_analysis_cache_key",
        lambda *_args, **_kwargs: ("order", "f1", "torque"),
    )
    from mf4_analyzer.signal.order_cot import COTOrderAnalyzer

    def fake_compute(*_args, progress_callback=None, cancel_token=None, **_kwargs):
        assert progress_callback is not None
        assert cancel_token is not None
        progress_callback(1, 2)
        return fake_result

    monkeypatch.setattr(COTOrderAnalyzer, "compute", fake_compute)

    job, ctx = win._build_order_job(0, "f1", "torque", ("f1", "rpm"))

    class Worker:
        progress = SimpleNamespace(emit=lambda *args: progress_calls.append(args))

        @staticmethod
        def cancelled():
            return False

    assert job(Worker()) is fake_result
    assert ctx == {
        "analysis_key": ("order", "f1", "torque"),
        "pane_idx": 0,
        "source": ("f1", "torque"),
    }
    assert progress_calls == [(1, 2)]
