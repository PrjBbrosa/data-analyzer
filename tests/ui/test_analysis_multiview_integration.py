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
    assert len(canvas._psd_curves) == 2

    # the active view's pane 0 captured both sources
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    assert len(state.panes[0].sources) == 2


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
    assert get_calls["n"] >= 2, "both sources looked up in the cache on switch"
    assert compute_calls["n"] == 0, "switch-back must NOT recompute (cache hit)"


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


def test_order_split_two_panes_render_distinct_sources(two_file_win, qtbot):
    win = two_file_win
    win.toolbar._set_mode("order")
    fids = list(win.files.keys())
    mgr = win.analysis_managers["order"]
    state = mgr.get(mgr.active)
    page = win.chart_stack.page_order
    win._on_analysis_split("order", True)
    assert page.pane_count() == 2
    assert page.focused_index() == 0
    # Two distinct signal sources, each with a rpm source. abs(rpm) is used by
    # COT so the sinusoidal 'speed' supplies a valid time-varying |rpm|.
    # Focused pane (0): wire signal + rpm through the inspector combos so the
    # capture step (which reads current_signal/current_rpm) stores them.
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "torque"))
    win._echo_combo_signal(ctx.combo_rpm, (fids[0], "speed"))
    # Non-focused pane (1): set directly on the state.
    state.panes[1].sources = [(fids[1], "torque")]
    state.panes[1].rpm_source = (fids[1], "speed")

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
