"""V7 integration: per-section analysis views with pane routing + cache.

Constructs a real MainWindow (offscreen), loads two CSV files, and exercises
the FFT section's whole-view compute, overlay rendering, empty-state on a fresh
view, and cache-hit rendering on view switch-back (no recompute).
"""
import numpy as np
import pytest

from mf4_analyzer.ui.main_window import MainWindow


@pytest.fixture
def two_file_win(qapp, loaded_csv, tmp_path, qtbot):
    """MainWindow with two loaded CSV files (same channel names)."""
    import pandas as pd

    # Second file: same columns, different content so the spectra differ.
    t = np.linspace(0, 1.0, 1000)
    df2 = pd.DataFrame({
        "time": t,
        "speed": 800 * np.sin(2 * np.pi * 7 * t),
        "torque": 40 + 3 * np.cos(2 * np.pi * 4 * t),
    })
    p2 = tmp_path / "sample2.csv"
    df2.to_csv(p2, index=False)

    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(loaded_csv)
    win._load_one(str(p2))
    assert len(win.files) == 2
    return win


def _check_speed_in_both(win):
    """Tick the 'speed' channel in both files via the navigator."""
    fids = list(win.files.keys())
    win.navigator.set_checked_channels(
        [(fids[0], "speed"), (fids[1], "speed")]
    )
    checked = win.navigator.get_checked_channels()
    keys = {(fid, ch) for fid, ch, _c in checked}
    assert (fids[0], "speed") in keys and (fids[1], "speed") in keys


def test_fft_view_overlays_two_files(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)

    win.do_fft()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._amp_curves) == 2, "two checked sources -> two overlay curves"
    assert len(canvas._time_curves) == 2, "lower row overlays the source time traces"
    assert canvas._selected_time_entry_idx == 0

    # the active view's pane 0 captured both sources
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert len(state.panes[0].sources) == 2
    assert "左侧已选 2 个信号" in win.inspector.fft_ctx.lbl_source_summary.text()


def test_fft_all_sources_too_short_warns(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    win.inspector.top.set_range_from_span(0.0, 0.005)

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_fft()

    assert calls == [("warning", "无可计算的图：2 个信号过短")]


def test_fft_all_cached_emits_info_toast(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    win.do_fft()
    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._amp_curves) == 2

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))
    canvas.full_reset()

    win.do_fft()

    assert calls == [("info", "已用缓存结果（参数未变）· 2 图")]
    assert len(canvas._amp_curves) == 2


def test_fft_compute_feedback_success_toast(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_fft()

    assert calls == [("success", "FFT完成 · 2 图")]


def test_fft_split_cache_render_uses_channel_swatch_colors(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft")
    fids = list(win.files.keys())
    red = "#ff0000"
    green = "#00aa00"
    win.navigator.set_channel_colors({
        (fids[0], "speed"): red,
        (fids[1], "speed"): green,
    })

    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win._on_analysis_split("fft", True)
    state.panes[0].sources = [(fids[0], "speed")]
    state.panes[1].sources = [(fids[1], "speed")]

    freq = np.asarray([0.0, 1.0, 2.0], dtype=float)
    amp = np.asarray([1.0, 0.5, 0.25], dtype=float)
    for fid, ch in (state.panes[0].sources + state.panes[1].sources):
        key = win._analysis_cache_key("fft", fid, ch)
        win.analysis_caches["fft"].put(key, (freq, amp, amp ** 2))

    # The currently focused/navigator-checked source is only pane 1. Pane 0
    # still has to render with its own left-side channel swatch color.
    win.navigator.set_checked_channels([(fids[1], "speed")])
    win._render_analysis_view_from_cache("fft", state)

    c0 = win.chart_stack.page_fft.pane_canvas(0)
    c1 = win.chart_stack.page_fft.pane_canvas(1)
    assert c0._amp_curves[0].opts["pen"].color().name() == red
    assert c1._amp_curves[0].opts["pen"].color().name() == green


def test_fft_mode_channel_selection_previews_time_before_compute(two_file_win, qapp):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    qapp.processEvents()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._amp_curves) == 0
    assert len(canvas._time_curves) == 2


def test_fft_time_preview_drag_updates_analysis_time_range(two_file_win, qapp):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    qapp.processEvents()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._time_curves) == 2
    win.inspector.top.chk_range.setChecked(False)

    canvas._plot_time.setXRange(0.2, 0.6, padding=0)
    canvas._plot_time.vb.sigRangeChangedManually.emit(
        canvas._plot_time.vb.state['mouseEnabled'])
    qapp.processEvents()

    assert win.inspector.top.range_enabled() is True
    assert win.inspector.top.range_values() == pytest.approx((0.2, 0.6), abs=1e-6)


def test_fft_split_same_source_different_time_ranges_have_distinct_cache_keys(
    two_file_win, qapp
):
    win = two_file_win
    win.toolbar._set_mode("fft")
    fids = list(win.files.keys())
    page = win.chart_stack.page_fft
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)

    win._on_analysis_split("fft", True)
    state.panes[0].sources = [(fids[0], "speed")]
    state.panes[0].time_range = (0.0, 0.35)
    state.panes[1].sources = [(fids[0], "speed")]
    state.panes[1].time_range = (0.55, 1.0)
    win.navigator.set_checked_channels(state.panes[0].sources)
    win.inspector.top.set_range_from_span(0.0, 0.35)

    k0 = win._analysis_cache_key("fft", fids[0], "speed", pane_idx=0)
    k1 = win._analysis_cache_key("fft", fids[0], "speed", pane_idx=1)

    assert k0 != k1

    win.do_fft()
    qapp.processEvents()

    c0 = page.pane_canvas(0)
    c1 = page.pane_canvas(1)
    assert len(c0._amp_curves) == 1
    assert len(c1._amp_curves) == 1
    assert win.analysis_caches["fft"].get(k0) is not None
    assert win.analysis_caches["fft"].get(k1) is not None


def _time_range_slice(fd, ch, time_range):
    lo, hi = time_range
    t = np.asarray(fd.time_array, dtype=float)
    sig = np.asarray(fd.data[ch].to_numpy(copy=False), dtype=float)
    mask = (t >= lo) & (t <= hi)
    return t[mask], sig[mask]


def test_fft_split_same_source_uses_each_pane_time_range(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("fft")
    fids = list(win.files.keys())
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win._on_analysis_split("fft", True)
    state.panes[0].sources = [(fids[0], "speed")]
    state.panes[0].time_range = (0.0, 0.25)
    state.panes[1].sources = [(fids[0], "speed")]
    state.panes[1].time_range = (0.75, 1.0)
    win.navigator.set_checked_channels(state.panes[0].sources)
    win.inspector.top.set_range_from_span(*state.panes[0].time_range)

    seen_slices = []
    real_compute = win._fft_compute_arrays

    def spy_compute(sig, fs, fft_params):
        seen_slices.append((len(sig), float(sig[0]), float(sig[-1])))
        return real_compute(sig, fs, fft_params)

    monkeypatch.setattr(win, "_fft_compute_arrays", spy_compute)

    win.do_fft()

    fd = win.files[fids[0]]
    expected = []
    for rng in (state.panes[0].time_range, state.panes[1].time_range):
        _t, sig = _time_range_slice(fd, "speed", rng)
        expected.append((len(sig), float(sig[0]), float(sig[-1])))

    assert len(seen_slices) == 2
    assert all(length < len(fd.data) for length, _first, _last in seen_slices)
    assert seen_slices == pytest.approx(expected)


def test_fft_cached_render_uses_each_pane_time_range_for_preview(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft")
    fids = list(win.files.keys())
    fid = fids[0]
    page = win.chart_stack.page_fft
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    win._on_analysis_split("fft", True)
    state.panes[0].sources = [(fid, "speed")]
    state.panes[0].time_range = (0.10, 0.20)
    state.panes[1].sources = [(fid, "speed")]
    state.panes[1].time_range = (0.70, 0.90)

    freq = np.asarray([0.0, 1.0, 2.0], dtype=float)
    amp = np.asarray([1.0, 0.5, 0.25], dtype=float)
    for pane_idx in (0, 1):
        key = win._analysis_cache_key("fft", fid, "speed", pane_idx=pane_idx)
        win.analysis_caches["fft"].put(key, (freq, amp, amp ** 2))

    win.inspector.top.set_range_from_span(0.40, 0.45)

    win._render_analysis_view_from_cache("fft", state)

    for pane_idx in (0, 1):
        canvas = page.pane_canvas(pane_idx)
        assert len(canvas._time_curves) == 1
        tx, _ty = canvas._time_curves[0].getData()
        expected_t, _expected_sig = _time_range_slice(
            win.files[fid], "speed", state.panes[pane_idx].time_range
        )
        np.testing.assert_allclose(tx, expected_t)


def test_fft_time_dispatch_uses_explicit_time_range(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    fids = list(win.files.keys())
    win.inspector.top.set_range_from_span(0.0, 0.25)

    seen = []

    from mf4_analyzer.signal import spectrogram as spectrogram_mod

    def fake_compute(
        sig,
        time,
        params,
        channel_name="",
        unit="",
        progress_callback=None,
        cancel_token=None,
    ):
        seen.append((len(sig), float(time[0]), float(time[-1])))
        return object()

    class DummyProgress:
        def emit(self, *args):
            pass

    class DummyWorker:
        progress = DummyProgress()
        cancelled = False

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer,
        "compute",
        staticmethod(fake_compute),
    )
    monkeypatch.setattr(
        win, "_start_fft_time_worker", lambda job: job(DummyWorker())
    )

    assert win._dispatch_fft_time_job(
        1, fids[0], "speed", time_range=(0.75, 1.0)
    )

    t, sig = _time_range_slice(win.files[fids[0]], "speed", (0.75, 1.0))
    assert seen == pytest.approx([(len(sig), float(t[0]), float(t[-1]))])


def test_fft_time_dispatch_omitted_time_range_uses_inspector_fallback(
    two_file_win, monkeypatch
):
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    fids = list(win.files.keys())
    win.inspector.top.set_range_from_span(0.20, 0.30)

    seen = []

    from mf4_analyzer.signal import spectrogram as spectrogram_mod

    def fake_compute(
        sig,
        time,
        params,
        channel_name="",
        unit="",
        progress_callback=None,
        cancel_token=None,
    ):
        seen.append((len(sig), float(time[0]), float(time[-1])))
        return object()

    class DummyProgress:
        def emit(self, *args):
            pass

    class DummyWorker:
        progress = DummyProgress()
        cancelled = False

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer,
        "compute",
        staticmethod(fake_compute),
    )
    monkeypatch.setattr(
        win, "_start_fft_time_worker", lambda job: job(DummyWorker())
    )

    assert win._dispatch_fft_time_job(1, fids[0], "speed")
    assert win._dispatch_fft_time_job(1, fids[0], "speed", time_range=None)

    inspector_t, inspector_sig = _time_range_slice(
        win.files[fids[0]], "speed", (0.20, 0.30)
    )
    full_t = np.asarray(win.files[fids[0]].time_array, dtype=float)
    full_sig = np.asarray(
        win.files[fids[0]].data["speed"].to_numpy(copy=False), dtype=float
    )
    assert len(seen) == 2
    assert seen[0] == pytest.approx(
        (len(inspector_sig), float(inspector_t[0]), float(inspector_t[-1]))
    )
    assert seen[1] == pytest.approx(
        (len(full_sig), float(full_t[0]), float(full_t[-1]))
    )


def test_order_helpers_use_explicit_time_range(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("order")
    fids = list(win.files.keys())
    win.inspector.top.set_range_from_span(0.0, 0.25)

    t, sig = win._order_sig_for((fids[0], "speed"), time_range=(0.75, 1.0))
    rpm = win._order_rpm_for(
        (fids[0], "speed"), len(sig), time_range=(0.75, 1.0)
    )

    expected_t, expected_sig = _time_range_slice(
        win.files[fids[0]], "speed", (0.75, 1.0)
    )
    np.testing.assert_array_equal(t, expected_t)
    np.testing.assert_array_equal(sig, expected_sig)
    np.testing.assert_array_equal(rpm, expected_sig)


def test_analysis_focus_switch_echoes_pane_local_time_range(two_file_win, qapp):
    win = two_file_win
    win.toolbar._set_mode("fft")
    fids = list(win.files.keys())
    page = win.chart_stack.page_fft
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)

    win._on_analysis_split("fft", True)
    state.panes[0].sources = [(fids[0], "speed")]
    state.panes[0].time_range = (0.1, 0.3)
    state.panes[1].sources = [(fids[0], "speed")]
    state.panes[1].time_range = (0.6, 0.9)
    win.inspector.top.set_range_from_span(0.1, 0.3)

    page.set_focused_index(0)
    win._on_analysis_focus_changed("fft", 0)
    assert win.inspector.top.range_enabled() is True
    assert win.inspector.top.range_values() == pytest.approx((0.1, 0.3))

    page.set_focused_index(1)
    assert win.inspector.top.range_enabled() is True
    assert win.inspector.top.range_values() == pytest.approx((0.6, 0.9))


def test_fft_section_switch_away_and_back_preserves_spectrum(two_file_win, qapp):
    """Compute FFT, switch to another section, switch back: the computed
    spectrum must survive. The old mode-entry path ran an unconditional
    ``_refresh_fft_time_preview(clear_spectrum=True)`` that wiped the amplitude
    curves and never restored them. An unchanged round-trip must also reuse the
    retained curves (no wipe + rebuild) and never recompute."""
    win = two_file_win
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    qapp.processEvents()
    win.do_fft()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._amp_curves) == 2
    curves_before = list(canvas._amp_curves)

    compute_calls = {"n": 0}
    real_compute = win._fft_compute_arrays

    def spy_compute(*a, **kw):
        compute_calls["n"] += 1
        return real_compute(*a, **kw)

    win._fft_compute_arrays = spy_compute

    # Round-trip through the order section without touching any fft input.
    win.toolbar._set_mode("order")
    qapp.processEvents()
    win.toolbar._set_mode("fft")
    qapp.processEvents()

    assert len(canvas._amp_curves) == 2, "spectrum must survive a section round-trip"
    assert canvas._amp_curves == curves_before, (
        "unchanged round-trip must reuse the retained curves, not rebuild them")
    assert compute_calls["n"] == 0, "section switch must never recompute"


def test_fft_signal_combo_previews_time_before_compute(two_file_win, qapp):
    win = two_file_win
    win.toolbar._set_mode("fft")
    win.navigator.set_checked_channels([])
    qapp.processEvents()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    # No nav channels checked AND no signal picked yet -> no phantom default
    # preview. The auto-select-first-signal behavior was removed so opening a
    # never-computed project (or clearing the selection) plots nothing.
    assert len(canvas._amp_curves) == 0
    assert len(canvas._time_curves) == 0

    # Explicitly picking a signal in the combo previews its time trace before
    # the user hits 计算 — the preview-before-compute UX is now selection-driven.
    win.inspector.fft_ctx.combo_sig.setCurrentIndex(0)
    qapp.processEvents()
    assert len(canvas._amp_curves) == 0
    assert len(canvas._time_curves) == 1


def test_new_view_is_empty_then_switch_back_hits_cache(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    win.do_fft()
    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._amp_curves) == 2

    cache = win.analysis_caches["fft"]

    # New View 2: fresh empty view, no sources -> empty canvas (no curves).
    win._on_analysis_new("fft")
    mgr = win.analysis_managers["fft"]
    assert mgr.active == 1
    assert len(canvas._amp_curves) == 0, "fresh view starts with an empty canvas"

    # Switch back to View 1: cache hit must re-render the 2 curves WITHOUT
    # recomputing. Spy on cache.get vs compute.
    get_calls = {"n": 0}
    real_get = cache.get

    def spy_get(key):
        get_calls["n"] += 1
        return real_get(key)

    cache.get = spy_get
    compute_calls = {"n": 0}
    real_compute = win._fft_compute_arrays

    def spy_compute(*a, **kw):
        compute_calls["n"] += 1
        return real_compute(*a, **kw)

    win._fft_compute_arrays = spy_compute

    win._on_analysis_switch("fft", 0)

    assert mgr.active == 0
    assert len(canvas._amp_curves) == 2, "switch-back re-renders the 2 cached curves"
    assert len(canvas._time_curves) == 2
    assert get_calls["n"] >= 2, "both sources looked up in the cache on switch"
    assert compute_calls["n"] == 0, "switch-back must NOT recompute (cache hit)"


def test_fft_time_focus_switch_preserves_previous_pane_source(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    fids = list(win.files.keys())
    page = win.chart_stack.page_fft_time
    mgr = win.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)

    win._on_analysis_split("fft_time", True)
    assert page.focused_index() == 0

    win._echo_combo_signal(win.inspector.fft_time_ctx.combo_sig, (fids[0], "speed"))
    page.set_focused_index(1)

    assert state.panes[0].sources == [(fids[0], "speed")]


def test_analysis_view_switch_missing_compare_defaults_lock_levels_true(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    mgr = win.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)
    state.compare = {}

    win._on_analysis_view_switched("fft_time", mgr.active)

    assert win.chart_stack.page_fft_time.btn_lock_levels.isChecked() is True


# ----------------------------------------------------------------------
# V7b: heatmap (FFT-vs-Time / Order) split multi-pane sequential compute
# queue. Two panes, two DIFFERENT sources → each pane must render its OWN
# source's result, never the focused pane / pane 0 twice.
# ----------------------------------------------------------------------
def _split_fft_time_two_sources(win):
    """Switch to fft_time mode, split into 2 panes, assign file0/speed to
    pane 0 and file1/speed to pane 1. Returns ``(fids, page)``.

    ``do_fft_time`` first captures the FOCUSED pane's source from the
    inspector selection, so the focused pane (0) is wired via the combo and
    the non-focused pane (1) is set directly on the view state — exactly how
    the live UI populates the two panes."""
    win.toolbar._set_mode("fft_time")
    fids = list(win.files.keys())
    mgr = win.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)
    page = win.chart_stack.page_fft_time
    # Enter split (adds pane 1) via the same handler the toolbar uses.
    win._on_analysis_split("fft_time", True)
    assert page.pane_count() == 2
    assert page.focused_index() == 0
    # Focused pane (0) source comes from the inspector selection (capture
    # reads current_signal); set it via the combo so capture stores it.
    win._echo_combo_signal(
        win.inspector.fft_time_ctx.combo_sig, (fids[0], "speed"))
    # Non-focused pane (1): set directly on the state (the live UI does this
    # via focus-switch + echo; here we pin it deterministically).
    state.panes[1].sources = [(fids[1], "speed")]
    # Pick a small NFFT so the 1000-sample signals yield several frames fast.
    ctx = win.inspector.fft_time_ctx
    i = ctx.combo_nfft.findText("512")
    if i >= 0:
        ctx.combo_nfft.setCurrentIndex(i)
    return fids, page


def _drain_fft_time_queue(win, qtbot):
    qtbot.waitUntil(
        lambda: win._fft_time_thread is None and not win._fft_time_queue,
        timeout=15000,
    )


def test_fft_time_split_two_panes_render_distinct_sources(two_file_win, qtbot):
    win = two_file_win
    fids, page = _split_fft_time_two_sources(win)

    win.do_fft_time()
    _drain_fft_time_queue(win, qtbot)

    c0 = page.pane_canvas(0)
    c1 = page.pane_canvas(1)
    # Both panes computed and rendered.
    assert c0.has_result(), "pane 0 (file0/speed) must have a result"
    assert c1.has_result(), "pane 1 (file1/speed) must have a result"
    # Each pane rendered ITS OWN source, not the same one twice. The two
    # files carry different 'speed' content (5 Hz vs 7 Hz), so the cached
    # SpectrogramResults differ — pin that the canvases hold DISTINCT results.
    assert c0._result is not None and c1._result is not None
    assert c0._result is not c1._result, "panes must not share one result"
    # The cache holds one entry per (fid, ch) source key — distinct keys.
    cache = win.analysis_caches["fft_time"]
    k0 = win._analysis_cache_key("fft_time", fids[0], "speed")
    k1 = win._analysis_cache_key("fft_time", fids[1], "speed")
    assert k0 != k1
    assert cache.get(k0) is not None and cache.get(k1) is not None
    # The per-pane result must match the source's own cache entry (the
    # load-bearing correctness: pane idx → right canvas).
    assert c0._result is cache.get(k0)
    assert c1._result is cache.get(k1)


def test_fft_time_split_cache_hit_renders_both_panes_without_recompute(
    two_file_win, qtbot, monkeypatch
):
    win = two_file_win
    fids, page = _split_fft_time_two_sources(win)

    # First compute populates the cache for both panes.
    win.do_fft_time()
    _drain_fft_time_queue(win, qtbot)
    r0_first = page.pane_canvas(0)._result
    r1_first = page.pane_canvas(1)._result
    assert r0_first is not None and r1_first is not None

    # Clear the canvases so a re-render is observable, but KEEP the cache.
    page.pane_canvas(0).full_reset()
    page.pane_canvas(1).full_reset()
    assert not page.pane_canvas(0).has_result()
    assert not page.pane_canvas(1).has_result()

    # Spy on the analyzer compute — a second do_fft_time must hit the cache
    # for BOTH panes and never recompute, never dispatch a worker.
    from mf4_analyzer.signal import spectrogram as spectrogram_mod
    calls = {"n": 0}
    real = spectrogram_mod.SpectrogramAnalyzer.compute

    def spy(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer, "compute", staticmethod(spy)
    )

    win.do_fft_time()
    # No worker should have been dispatched (pure cache-hit synchronous path).
    assert win._fft_time_thread is None
    assert calls["n"] == 0, "split cache hit must not recompute either pane"
    # Both panes re-rendered from the cache onto their OWN canvas.
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()
    cache = win.analysis_caches["fft_time"]
    k0 = win._analysis_cache_key("fft_time", fids[0], "speed")
    k1 = win._analysis_cache_key("fft_time", fids[1], "speed")
    assert page.pane_canvas(0)._result is cache.get(k0)
    assert page.pane_canvas(1)._result is cache.get(k1)


def test_fft_time_all_cached_emits_info_toast(two_file_win, qtbot, monkeypatch):
    win = two_file_win
    _fids, page = _split_fft_time_two_sources(win)

    win.do_fft_time()
    _drain_fft_time_queue(win, qtbot)
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))
    page.pane_canvas(0).full_reset()
    page.pane_canvas(1).full_reset()

    win.do_fft_time()

    assert win._fft_time_thread is None
    assert calls == [("info", "已用缓存结果（参数未变）· 2 图")]
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()


def test_fft_time_skip_missing_source_warns_without_short_signal_reason(
    two_file_win, qtbot, monkeypatch
):
    win = two_file_win
    _fids, _page = _split_fft_time_two_sources(win)
    mgr = win.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)
    state.panes[1].sources = [(state.panes[1].sources[0][0], "missing_signal")]

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_fft_time()
    _drain_fft_time_queue(win, qtbot)

    assert calls
    level, msg = calls[-1]
    assert level == "warning"
    assert "源通道缺失" in msg
    assert "信号过短" not in msg


def test_fft_time_reentry_busy_toast(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("fft_time")

    class RunningThread:
        def isRunning(self):
            return True

        def quit(self):
            pass

        def wait(self, _timeout=None):
            return True

    win._fft_time_thread = RunningThread()
    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_fft_time()

    assert calls == [("info", "FFT-vs-Time进行中，请稍候…")]


def test_fft_time_single_pane_unchanged_by_queue(two_file_win, qtbot):
    # Regression guard: a non-split (1-pane) view computes exactly the focused
    # pane's source — V7 behaviour — and produces exactly one cache entry.
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    fids = list(win.files.keys())
    page = win.chart_stack.page_fft_time
    assert page.pane_count() == 1
    # Focused single pane sources from the inspector selection.
    win._echo_combo_signal(
        win.inspector.fft_time_ctx.combo_sig, (fids[0], "speed"))
    ctx = win.inspector.fft_time_ctx
    i = ctx.combo_nfft.findText("512")
    if i >= 0:
        ctx.combo_nfft.setCurrentIndex(i)

    win.do_fft_time()
    _drain_fft_time_queue(win, qtbot)

    assert page.pane_canvas(0).has_result()
    cache = win.analysis_caches["fft_time"]
    k0 = win._analysis_cache_key("fft_time", fids[0], "speed")
    assert cache.get(k0) is not None
    assert page.pane_canvas(0)._result is cache.get(k0)


# ----------------------------------------------------------------------
# V7b: Order (COT) split queue. Same per-pane-correctness contract; Order
# carries a rpm_source per pane and never sets canvas._result (Order mode),
# so distinctness is pinned on the analysis cache + display matrices.
# ----------------------------------------------------------------------
def _drain_order_queue(win, qtbot):
    qtbot.waitUntil(
        lambda: win._order_thread is None and not win._order_queue,
        timeout=20000,
    )


def _split_order_two_sources(win):
    win.toolbar._set_mode("order")
    fids = list(win.files.keys())
    mgr = win.analysis_managers["order"]
    state = mgr.get(mgr.active)
    page = win.chart_stack.page_order
    win._on_analysis_split("order", True)
    assert page.pane_count() == 2
    assert page.focused_index() == 0

    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "torque"))
    win._echo_combo_signal(ctx.combo_rpm, (fids[0], "speed"))
    state.panes[1].sources = [(fids[1], "torque")]
    state.panes[1].rpm_source = (fids[1], "speed")
    return fids, page, state


def test_order_split_two_panes_render_distinct_sources(two_file_win, qtbot):
    win = two_file_win
    fids, page, _state = _split_order_two_sources(win)

    win.do_order_time()
    _drain_order_queue(win, qtbot)

    c0 = page.pane_canvas(0)
    c1 = page.pane_canvas(1)
    assert c0.has_result(), "Order pane 0 must have a result"
    assert c1.has_result(), "Order pane 1 must have a result"
    cache = win.analysis_caches["order"]
    k0 = win._analysis_cache_key(
        "order", fids[0], "torque", rpm_source=(fids[0], "speed"))
    k1 = win._analysis_cache_key(
        "order", fids[1], "torque", rpm_source=(fids[1], "speed"))
    assert k0 != k1
    r0 = cache.get(k0)
    r1 = cache.get(k1)
    assert r0 is not None and r1 is not None
    assert r0 is not r1, "each pane cached its OWN COT result"
    # The two files' torque content differs (4 Hz vs 3 Hz cosine), so the
    # rendered display matrices must NOT be identical — proves pane idx →
    # correct canvas (not the same source rendered twice). The two sources
    # even yield different frame counts, so a shape mismatch alone already
    # proves distinct routing; when shapes match, the contents must differ.
    assert c0._matrix_disp is not None and c1._matrix_disp is not None
    if c0._matrix_disp.shape == c1._matrix_disp.shape:
        assert not np.array_equal(c0._matrix_disp, c1._matrix_disp), (
            "both panes rendered the SAME matrix — pane routing is wrong"
        )
    # The per-pane result must trace back to the source's OWN cache entry.
    assert np.array_equal(c0._matrix_disp.shape, np.asarray(r0.amplitude.T).shape)
    assert np.array_equal(c1._matrix_disp.shape, np.asarray(r1.amplitude.T).shape)


def test_order_all_cached_emits_info_toast(two_file_win, qtbot, monkeypatch):
    win = two_file_win
    _fids, page, _state = _split_order_two_sources(win)

    win.do_order_time()
    _drain_order_queue(win, qtbot)
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))
    page.pane_canvas(0).full_reset()
    page.pane_canvas(1).full_reset()

    win.do_order_time()

    assert win._order_thread is None
    assert calls == [("info", "已用缓存结果（参数未变）· 2 图")]
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()


def test_order_skip_short_signal_warns(two_file_win, qtbot, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("order")
    fids = list(win.files.keys())
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "torque"))
    win._echo_combo_signal(ctx.combo_rpm, (fids[0], "speed"))
    win.inspector.top.set_range_from_span(0.0, 0.05)

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_order_time()
    _drain_order_queue(win, qtbot)

    assert calls == [("warning", "无可计算的图：1 个信号过短")]


def test_order_missing_source_warns_without_short_signal_reason(
    two_file_win, qtbot, monkeypatch
):
    win = two_file_win
    _fids, _page, state = _split_order_two_sources(win)
    state.panes[1].sources = [(state.panes[1].sources[0][0], "missing_signal")]

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_order_time()
    _drain_order_queue(win, qtbot)

    assert calls
    level, msg = calls[-1]
    assert level == "warning"
    assert "源通道缺失" in msg
    assert "信号过短" not in msg


def test_order_reentry_emits_busy_toast(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("order")

    class RunningThread:
        def isRunning(self):
            return True

        def quit(self):
            pass

        def wait(self, _timeout=None):
            return True

    win._order_thread = RunningThread()
    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_order_time()

    assert calls == [("info", "时间-阶次进行中，请稍候…")]


# ----------------------------------------------------------------------
# V10: project save -> reopen round-trip for analysis_views. Build two
# views per section (one split + distinct sources + edited params/compare),
# save to a .tlproj, reopen in a FRESH MainWindow, and assert the full
# view tree (count / active / pane count / sources / params / compare)
# survives. Old projects without analysis_views are covered separately.
# ----------------------------------------------------------------------
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState


def _fft_views(fids):
    """Two fft views: v0 single-pane, v1 split (overlay + 2nd pane). Only the
    fft-real param keys (window/nfft/overlap) are set so the non-active view's
    stored params round-trip verbatim."""
    v0 = AnalysisViewState(
        name="FFT-A", tab_color="#1f77b4",
        panes=[PaneState(sources=[(fids[0], "speed")])],
        params={"window": "hanning", "nfft": 1024, "overlap": 0.5},
        compare={"x_linked": True, "levels_locked": False},
    )
    v1 = AnalysisViewState(
        name="FFT-B", tab_color="#ff7f0e",
        panes=[
            PaneState(sources=[(fids[0], "speed"), (fids[1], "speed")]),
            PaneState(sources=[(fids[1], "torque")]),
        ],
        params={"window": "hamming", "nfft": 2048, "overlap": 0.75},
        compare={"x_linked": False, "levels_locked": True},
    )
    return [v0, v1]


def _order_views(fids):
    """Two order views: v0 single-pane (sig+rpm), v1 split with distinct rpm.
    Order's get_params keys are max_order/nfft/order_res/time_res."""
    v0 = AnalysisViewState(
        name="ORD-A", tab_color="#2ca02c",
        panes=[PaneState(sources=[(fids[0], "torque")],
                         rpm_source=(fids[0], "speed"))],
        params={"max_order": 20, "nfft": 512, "order_res": 0.1,
                "time_res": 0.05},
        compare={"x_linked": True, "levels_locked": True},
    )
    v1 = AnalysisViewState(
        name="ORD-B", tab_color="#d62728",
        panes=[
            PaneState(sources=[(fids[0], "torque")],
                      rpm_source=(fids[0], "speed")),
            PaneState(sources=[(fids[1], "torque")],
                      rpm_source=(fids[1], "speed")),
        ],
        params={"max_order": 32, "nfft": 1024, "order_res": 0.2,
                "time_res": 0.1},
        compare={"x_linked": False, "levels_locked": False},
    )
    return [v0, v1]


def _install_views(win, section, views, active):
    """Install pre-built view states on a section manager and seed the live
    UI from the active view (so save-time capture is idempotent, mirroring
    a user who left that view focused)."""
    mgr = win.analysis_managers[section]
    mgr.views = views
    mgr.active = active
    mgr.views_changed.emit()
    # active_changed -> _on_analysis_view_switched: applies structure +
    # params + focused-pane source into the inspector / navigator so the
    # subsequent _capture_active_analysis_view reads back the same values.
    mgr.active_changed.emit(active)


def _assert_section_equal(win, section, expected_views, expected_active,
                          expected_active_params, param_keys):
    mgr = win.analysis_managers[section]
    assert len(mgr.views) == len(expected_views), f"{section}: view count"
    assert mgr.active == expected_active, f"{section}: active index"
    for i, (got, exp) in enumerate(zip(mgr.views, expected_views)):
        assert len(got.panes) == len(exp.panes), f"{section} v{i}: pane count"
        for pi, (gp, ep) in enumerate(zip(got.panes, exp.panes)):
            assert [tuple(s) for s in gp.sources] == [tuple(s) for s in ep.sources], \
                f"{section} v{i} pane{pi}: sources"
            assert (tuple(gp.rpm_source) if gp.rpm_source else None) == \
                (tuple(ep.rpm_source) if ep.rpm_source else None), \
                f"{section} v{i} pane{pi}: rpm_source"
        # Params: the ACTIVE view's params are re-captured from the live
        # inspector at save time, so compare against what get_params() emitted
        # (captured below). NON-active views keep their stored params verbatim.
        if i == expected_active:
            for k in param_keys:
                assert got.params.get(k) == expected_active_params.get(k), \
                    (f"{section} active v{i}: param {k} "
                     f"({got.params.get(k)} != {expected_active_params.get(k)})")
        else:
            for k in param_keys:
                assert got.params.get(k) == exp.params.get(k), \
                    (f"{section} v{i}: param {k} "
                     f"({got.params.get(k)} != {exp.params.get(k)})")
        assert got.compare.get("x_linked") == exp.compare["x_linked"], \
            f"{section} v{i}: compare.x_linked"
        assert got.compare.get("levels_locked") == exp.compare["levels_locked"], \
            f"{section} v{i}: compare.levels_locked"


# Param keys that BOTH appear in the section's get_params AND round-trip
# through apply_params (so a view restore reproduces them).
_SECTION_PARAM_KEYS = {
    "fft": ("window", "nfft", "overlap"),
    "fft_time": ("window", "nfft", "overlap"),
    "order": ("max_order", "nfft", "order_res", "time_res"),
}


def test_analysis_views_survive_project_save_reopen(two_file_win, tmp_path, qtbot):
    win = two_file_win
    fids = list(win.files.keys())
    fft_views = _fft_views(fids)
    order_views = _order_views(fids)
    fft_time_views = _fft_views(fids)  # fft_time shares fft's param shape
    actives = {"fft": 1, "order": 0, "fft_time": 1}

    win.toolbar._set_mode("fft")
    _install_views(win, "fft", fft_views, active=actives["fft"])
    win.toolbar._set_mode("order")
    _install_views(win, "order", order_views, active=actives["order"])
    win.toolbar._set_mode("fft_time")
    _install_views(win, "fft_time", fft_time_views, active=actives["fft_time"])

    # The active view's params are whatever the live inspector holds at save —
    # capture them per section so the assertion compares apples to apples.
    expected_active_params = {
        sec: dict(win._analysis_ctx(sec).get_params())
        for sec in ("fft", "order", "fft_time")
    }

    proj = tmp_path / "session.tlproj"
    win.save_project(proj)
    assert proj.exists()

    # Reopen in a FRESH MainWindow so nothing leaks via shared state.
    win2 = MainWindow()
    qtbot.addWidget(win2)
    win2.open_project(proj)

    # Files were re-loaded; the new fids may differ, but the channel names and
    # ordering are preserved, so remap reproduces the same (fid, ch) pairs
    # relative to the new fid order.
    fids2 = list(win2.files.keys())
    assert len(fids2) == 2, "both files reopened"
    fid_remap = {fids[i]: fids2[i] for i in range(2)}

    def remap_views(views):
        out = []
        for v in views:
            panes = []
            for p in v.panes:
                panes.append(PaneState(
                    sources=[(fid_remap[f], c) for f, c in p.sources],
                    rpm_source=((fid_remap[p.rpm_source[0]], p.rpm_source[1])
                                if p.rpm_source else None),
                ))
            out.append(AnalysisViewState(
                name=v.name, tab_color=v.tab_color, panes=panes,
                params=v.params, compare=v.compare))
        return out

    _assert_section_equal(
        win2, "fft", remap_views(fft_views), actives["fft"],
        expected_active_params["fft"], _SECTION_PARAM_KEYS["fft"])
    _assert_section_equal(
        win2, "order", remap_views(order_views), actives["order"],
        expected_active_params["order"], _SECTION_PARAM_KEYS["order"])
    _assert_section_equal(
        win2, "fft_time", remap_views(fft_time_views), actives["fft_time"],
        expected_active_params["fft_time"], _SECTION_PARAM_KEYS["fft_time"])


def test_project_save_preserves_all_analysis_sections_after_time_selection(
    two_file_win, tmp_path
):
    import json

    win = two_file_win
    fids = list(win.files.keys())

    win.toolbar._set_mode("fft")
    win.navigator.set_checked_channels([(fids[0], "speed")])
    # Switching away should first capture FFT's source into its own state.
    win.toolbar._set_mode("time")
    # Time-domain selection changes the same navigator, but must not overwrite
    # the inactive FFT view's saved sources.
    win.navigator.set_checked_channels([(fids[1], "torque")])

    proj = tmp_path / "session_sections.tlproj"
    win.save_project(proj)
    raw = json.loads(proj.read_text(encoding="utf-8"))

    assert set(raw["analysis_views"]) >= {"fft", "fft_time", "order"}
    fft_sources = raw["analysis_views"]["fft"]["views"][0]["panes"][0]["sources"]
    assert fft_sources == [[fids[0], "speed"]]


def test_old_project_without_analysis_views_loads_with_defaults(
    two_file_win, tmp_path, qtbot
):
    """Backward compatibility: a project saved before V10 has no
    analysis_views key. Loading it must leave each section at its default
    single view rather than crash."""
    import json
    win = two_file_win
    proj = tmp_path / "legacy.tlproj"
    win.save_project(proj)
    # Strip analysis_views to simulate a pre-V10 file.
    raw = json.loads(proj.read_text(encoding="utf-8"))
    raw.pop("analysis_views", None)
    proj.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    win2 = MainWindow()
    qtbot.addWidget(win2)
    win2.open_project(proj)  # must not raise

    for sec in ("fft", "order", "fft_time"):
        mgr = win2.analysis_managers[sec]
        assert len(mgr.views) == 1, f"{sec}: legacy load keeps the default view"
        assert mgr.active == 0
