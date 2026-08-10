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


def _seed_active_analysis_attachments(win, fids=None):
    """Attach files to the active analysis View under Stage 1 source isolation.

    Analysis Views own ``attached_file_ids`` (empty by default); auto-attach on
    load only joins the time View. Integration tests that switch into an
    analysis section and then tick navigator channels / Inspector combos must
    seed the active analysis View first, unless they are specifically asserting
    emptiness for a newly created analysis View.
    """
    mode = win.chart_stack.current_mode()
    if mode in getattr(win, "analysis_managers", {}):
        win._attach_files_to_active_context(list(fids or win.files.keys()))


def _check_speed_in_both(win):
    """Tick the 'speed' channel in both files via the navigator."""
    _seed_active_analysis_attachments(win)
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


def test_recovery_render_failure_toasts_warning(two_file_win, monkeypatch):
    win = two_file_win

    def fail_compute():
        raise RuntimeError("boom")

    calls = []
    monkeypatch.setattr(win, "do_fft", fail_compute)
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win._recompute_analysis_section("fft")

    assert calls == [("warning", "恢复渲染失败，请手动点计算")]


def test_fft_nonuniform_skip_reason_matches_feedback_contract(
    two_file_win, monkeypatch
):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    monkeypatch.setattr(win, "_check_uniform_or_prompt", lambda _fd, _mode: False)

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_fft()

    assert calls == [("warning", "无可计算的图：2 个非均匀且未重建")]


def test_fft_split_cache_render_uses_channel_swatch_colors(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
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


def test_fft_cache_miss_shows_click_compute_empty_hint(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())

    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = [(fids[0], "speed")]

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    win._render_analysis_view_from_cache("fft", state)

    assert canvas._empty_hint_item is not None
    assert canvas._empty_hint_item.scene() is not None
    assert canvas._empty_hint_item.isVisible()
    assert "点击" in canvas._empty_hint_text
    assert "计算" in canvas._empty_hint_text
    assert "生成" in canvas._empty_hint_text
    assert win.statusBar.currentMessage() == "参数/源已就绪，点击计算"


def test_fft_preview_clears_cache_miss_empty_hint(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())

    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = [(fids[0], "speed")]

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    win._render_analysis_view_from_cache("fft", state)
    assert canvas._empty_hint_item is not None
    assert canvas._empty_hint_item.isVisible()

    canvas.plot_time_preview([], title="时域预览", clear_spectrum=True)

    assert canvas._empty_hint_text == ""
    assert canvas._empty_hint_item is None


def test_fft_cache_hit_render_clears_cache_miss_empty_hint(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())

    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = [(fids[0], "speed")]

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    win._render_analysis_view_from_cache("fft", state)
    assert canvas._empty_hint_item is not None
    assert canvas._empty_hint_item.isVisible()

    key = win._analysis_cache_key("fft", fids[0], "speed", pane_idx=0)
    freq = np.asarray([0.0, 1.0, 2.0], dtype=float)
    amp = np.asarray([1.0, 0.5, 0.25], dtype=float)
    win.analysis_caches["fft"].put(key, (freq, amp, amp ** 2))

    win._render_analysis_view_from_cache("fft", state)

    assert len(canvas._amp_curves) == 1
    assert canvas._empty_hint_text == ""
    assert canvas._empty_hint_item is None


def test_fft_time_analysis_cache_miss_shows_visible_empty_hint(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())

    mgr = win.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = [(fids[0], "speed")]

    canvas = win.chart_stack.page_fft_time.pane_canvas(0)
    win._render_analysis_view_from_cache("fft_time", state)

    assert canvas._empty_hint_item is not None
    assert canvas._empty_hint_item.scene() is not None
    assert canvas._empty_hint_item.isVisible()
    assert "点击" in canvas._empty_hint_text
    assert "计算" in canvas._empty_hint_text
    assert "生成" in canvas._empty_hint_text
    assert win.statusBar.currentMessage() == "参数/源已就绪，点击计算"


def test_fft_time_no_sources_does_not_show_empty_hint(two_file_win):
    win = two_file_win
    win.toolbar._set_mode("fft_time")

    _seed_active_analysis_attachments(win)
    mgr = win.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = []

    canvas = win.chart_stack.page_fft_time.pane_canvas(0)
    win._render_analysis_view_from_cache("fft_time", state)

    assert canvas._empty_hint_text == ""
    assert canvas._empty_hint_item is None


def test_cache_miss_empty_hint_raises_when_canvas_api_fails(
    two_file_win, monkeypatch
):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())

    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    state.panes[0].sources = [(fids[0], "speed")]

    canvas = win.chart_stack.page_fft.pane_canvas(0)

    def fail_empty_hint(_text):
        raise RuntimeError("broken visible hint")

    monkeypatch.setattr(canvas, "show_empty_hint", fail_empty_hint)

    with pytest.raises(RuntimeError, match="broken visible hint"):
        win._render_analysis_view_from_cache("fft", state)

    assert canvas._empty_hint_text == ""
    assert canvas._empty_hint_item is None


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
    _seed_active_analysis_attachments(win)
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
    _seed_active_analysis_attachments(win)
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
    _seed_active_analysis_attachments(win)
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
    _seed_active_analysis_attachments(win)
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
        @staticmethod
        def cancelled():
            return False

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer,
        "compute",
        staticmethod(fake_compute),
    )
    job, _ctx = win._build_fft_time_job(
        1, fids[0], "speed", win.inspector.fft_time_ctx.get_params(),
        time_range=(0.75, 1.0),
    )
    assert job(DummyWorker()) is not None

    t, sig = _time_range_slice(win.files[fids[0]], "speed", (0.75, 1.0))
    assert seen == pytest.approx([(len(sig), float(t[0]), float(t[-1]))])


def test_fft_time_dispatch_omitted_time_range_uses_inspector_fallback(
    two_file_win, monkeypatch
):
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    _seed_active_analysis_attachments(win)
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
        @staticmethod
        def cancelled():
            return False

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer,
        "compute",
        staticmethod(fake_compute),
    )
    job, _ctx = win._build_fft_time_job(
        1, fids[0], "speed", win.inspector.fft_time_ctx.get_params(),
    )
    assert job(DummyWorker()) is not None
    job, _ctx = win._build_fft_time_job(
        1, fids[0], "speed", win.inspector.fft_time_ctx.get_params(),
        time_range=None,
    )
    assert job(DummyWorker()) is not None

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
    _seed_active_analysis_attachments(win)
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
    _seed_active_analysis_attachments(win)
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


def test_fft_single_signal_survives_fft_time_weighting_drift(two_file_win, qapp):
    """Returning to FFT restores the active View's params and keeps the spectrum.

    Cross-section Inspector edits (e.g. FFT-vs-Time audio weighting defaults)
    may mutate the shared FFT Contextual while the FFT page is hidden. Stage 1
    source isolation reapplies the destination View's params on mode entry, so
    that live drift must not overwrite View state or wipe the retained canvas.
    """
    win = two_file_win
    fid = list(win.files.keys())[0]
    win.navigator.set_checked_channels([])
    qapp.processEvents()
    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
    qapp.processEvents()
    win._echo_combo_signal(win.inspector.fft_ctx.combo_sig, (fid, "speed"))
    qapp.processEvents()
    win.do_fft()
    qapp.processEvents()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._amp_curves) == 1
    fft_state = win.analysis_managers["fft"].get(0)
    weighting_before = fft_state.params.get("weighting")
    live_before = win.inspector.fft_ctx.get_params().get("weighting")

    win.toolbar._set_mode("fft_time")
    qapp.processEvents()
    # Poison live FFT Contextual while away; mode re-entry must re-apply View.
    win.inspector.fft_ctx.combo_weighting.setCurrentText("A")
    qapp.processEvents()
    win.toolbar._set_mode("fft")
    qapp.processEvents()
    qapp.processEvents()

    assert len(canvas._amp_curves) == 1
    assert canvas.has_result()
    live_after = win.inspector.fft_ctx.get_params().get("weighting")
    state_after = fft_state.params.get("weighting")
    assert state_after == weighting_before
    assert live_after == live_before == weighting_before
    assert live_after != "A" or weighting_before == "A"
    assert canvas.is_spectrum_stale() is False


def test_fft_signal_combo_previews_time_before_compute(two_file_win, qapp):
    win = two_file_win
    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
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
    _seed_active_analysis_attachments(win)
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
    _seed_active_analysis_attachments(win)
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
    _seed_active_analysis_attachments(win)
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


def _drain_fft_time_jobs(win, qtbot):
    qtbot.waitUntil(
        lambda: not win._analysis_jobs.is_running("fft_time"),
        timeout=15000,
    )


def test_fft_time_split_two_panes_render_distinct_sources(two_file_win, qtbot):
    win = two_file_win
    fids, page = _split_fft_time_two_sources(win)

    win.do_fft_time()
    _drain_fft_time_jobs(win, qtbot)

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
    _drain_fft_time_jobs(win, qtbot)
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
    assert not win._analysis_jobs.is_running("fft_time")
    assert calls["n"] == 0, "split cache hit must not recompute either pane"
    # Both panes re-rendered from the cache onto their OWN canvas.
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()
    cache = win.analysis_caches["fft_time"]
    k0 = win._analysis_cache_key("fft_time", fids[0], "speed")
    k1 = win._analysis_cache_key("fft_time", fids[1], "speed")
    assert page.pane_canvas(0)._result is cache.get(k0)
    assert page.pane_canvas(1)._result is cache.get(k1)


def test_fft_time_restore_recompute_uses_cache_without_service_submission(
    two_file_win, qtbot, monkeypatch
):
    """Project restore re-enters via ``do_fft_time`` and may be cache-only."""
    win = two_file_win
    _fids, page = _split_fft_time_two_sources(win)

    win.do_fft_time()
    _drain_fft_time_jobs(win, qtbot)
    page.pane_canvas(0).full_reset()
    page.pane_canvas(1).full_reset()
    submitted = []
    monkeypatch.setattr(
        win._analysis_jobs,
        "submit_batch",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    win._recompute_analysis_section("fft_time")

    assert submitted == []
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()


def test_fft_time_all_cached_emits_info_toast(two_file_win, qtbot, monkeypatch):
    win = two_file_win
    _fids, page = _split_fft_time_two_sources(win)

    win.do_fft_time()
    _drain_fft_time_jobs(win, qtbot)
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))
    page.pane_canvas(0).full_reset()
    page.pane_canvas(1).full_reset()

    win.do_fft_time()

    assert not win._analysis_jobs.is_running("fft_time")
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
    _drain_fft_time_jobs(win, qtbot)

    assert calls
    level, msg = calls[-1]
    assert level == "warning"
    assert "源通道缺失" in msg
    assert "信号过短" not in msg


def test_fft_time_reentry_busy_toast(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    _seed_active_analysis_attachments(win)
    monkeypatch.setattr(win._analysis_jobs, "is_running", lambda _section: True)
    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_fft_time()

    assert calls == [("info", "FFT-vs-Time进行中，请稍候…")]


def test_fft_time_single_pane_unchanged_by_queue(two_file_win, qtbot):
    # Regression guard: a non-split (1-pane) view computes exactly the focused
    # pane's source — V7 behaviour — and produces exactly one cache entry.
    win = two_file_win
    win.toolbar._set_mode("fft_time")
    _seed_active_analysis_attachments(win)
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
    _drain_fft_time_jobs(win, qtbot)

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
def _drain_order_jobs(win, qtbot):
    qtbot.waitUntil(
        lambda: not win._analysis_jobs.is_running("order"),
        timeout=20000,
    )


def _split_order_two_sources(win):
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
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
    _drain_order_jobs(win, qtbot)

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
    _drain_order_jobs(win, qtbot)
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))
    page.pane_canvas(0).full_reset()
    page.pane_canvas(1).full_reset()

    win.do_order_time()

    assert not win._analysis_jobs.is_running("order")
    assert calls == [("info", "已用缓存结果（参数未变）· 2 图")]
    assert page.pane_canvas(0).has_result()
    assert page.pane_canvas(1).has_result()


def test_order_skip_short_signal_warns(two_file_win, qtbot, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "torque"))
    win._echo_combo_signal(ctx.combo_rpm, (fids[0], "speed"))
    win.inspector.top.set_range_from_span(0.0, 0.05)

    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.do_order_time()
    _drain_order_jobs(win, qtbot)

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
    _drain_order_jobs(win, qtbot)

    assert calls
    level, msg = calls[-1]
    assert level == "warning"
    assert "源通道缺失" in msg
    assert "信号过短" not in msg


def test_order_reentry_emits_busy_toast(two_file_win, monkeypatch):
    win = two_file_win
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    monkeypatch.setattr(win._analysis_jobs, "is_running", lambda _section: True)
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
from mf4_analyzer.ui.analysis_view_state import (
    AnalysisViewState,
    PaneState,
    analysis_view_source_fids,
)


def _stamp_view_attachments(view):
    """Ensure constructed analysis views cover every pane role fid."""
    view.attached_file_ids = analysis_view_source_fids(view)
    return view


def _stamp_views(views):
    for view in views:
        _stamp_view_attachments(view)
    return views



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
    return _stamp_views([v0, v1])


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
    return _stamp_views([v0, v1])


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
                params=v.params, compare=v.compare,
                attached_file_ids=[fid_remap[f] for f in v.attached_file_ids],
            ))
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


# ----------------------------------------------------------------------
# dB reference defaults Task 8: nested AnalysisViewState schema 1 -> 2
# migration (spec §13 S3/S5). Each section/View's own db_reference_mode +
# value, and each pane's saved (fid, ch) sources, survive a project
# save/reopen round-trip independently of one another.
# ----------------------------------------------------------------------
def test_project_reopen_preserves_auto_manual_per_section_and_pane_sources(
    two_file_win, tmp_path, qtbot
):
    win = two_file_win
    fids = list(win.files.keys())

    fft_v0 = AnalysisViewState(
        name="FFT-Auto", tab_color="#1f77b4",
        panes=[PaneState(sources=[(fids[0], "speed")])],
        params={"window": "hanning", "nfft": 1024,
                "db_reference_mode": "auto", "db_reference": 1.0},
    )
    fft_v1 = AnalysisViewState(
        name="FFT-Manual", tab_color="#ff7f0e",
        panes=[PaneState(sources=[(fids[1], "speed")])],
        params={"window": "hamming", "nfft": 2048,
                "db_reference_mode": "manual", "db_reference": 3.3e-6},
    )
    order_v0 = AnalysisViewState(
        name="ORD-Manual", tab_color="#2ca02c",
        panes=[PaneState(sources=[(fids[0], "torque")],
                         rpm_source=(fids[0], "speed"))],
        params={"max_order": 20, "nfft": 512, "order_res": 0.1,
                "time_res": 0.05,
                "db_reference_mode": "manual", "db_reference": 5e-6},
    )
    order_v1 = AnalysisViewState(
        name="ORD-Auto", tab_color="#d62728",
        panes=[PaneState(sources=[(fids[1], "torque")],
                         rpm_source=(fids[1], "speed"))],
        params={"max_order": 32, "nfft": 1024, "order_res": 0.2,
                "time_res": 0.1,
                "db_reference_mode": "auto", "db_reference": 1.0},
    )
    _stamp_views([fft_v0, fft_v1, order_v0, order_v1])

    win.toolbar._set_mode("fft")
    # Manual is the ACTIVE view here -- its params get RE-CAPTURED from the
    # live inspector at save time, but Manual never auto-resolves off the
    # source, so the round-trip stays exact/deterministic.
    _install_views(win, "fft", [fft_v0, fft_v1], active=1)
    win.toolbar._set_mode("order")
    _install_views(win, "order", [order_v0, order_v1], active=0)

    proj = tmp_path / "db_ref_reopen.tlproj"
    win.save_project(proj)

    win2 = MainWindow()
    qtbot.addWidget(win2)
    win2.open_project(proj)

    fids2 = list(win2.files.keys())
    fid_remap = {fids[i]: fids2[i] for i in range(2)}

    mgr_fft = win2.analysis_managers["fft"]
    assert mgr_fft.active == 1
    # v0 (Auto) is INACTIVE -> its params round-trip verbatim.
    assert mgr_fft.views[0].params["db_reference_mode"] == "auto"
    assert mgr_fft.views[0].params["db_reference"] == pytest.approx(1.0)
    assert [tuple(s) for s in mgr_fft.views[0].panes[0].sources] == [
        (fid_remap[fids[0]], "speed")
    ]
    # v1 (Manual) is ACTIVE -> re-captured, still exact.
    assert mgr_fft.views[1].params["db_reference_mode"] == "manual"
    assert mgr_fft.views[1].params["db_reference"] == pytest.approx(3.3e-6)
    assert [tuple(s) for s in mgr_fft.views[1].panes[0].sources] == [
        (fid_remap[fids[1]], "speed")
    ]

    mgr_order = win2.analysis_managers["order"]
    assert mgr_order.active == 0
    # v0 (Manual) is ACTIVE -> re-captured, still exact.
    assert mgr_order.views[0].params["db_reference_mode"] == "manual"
    assert mgr_order.views[0].params["db_reference"] == pytest.approx(5e-6)
    assert [tuple(s) for s in mgr_order.views[0].panes[0].sources] == [
        (fid_remap[fids[0]], "torque")
    ]
    # v1 (Auto) is INACTIVE -> verbatim.
    assert mgr_order.views[1].params["db_reference_mode"] == "auto"
    assert mgr_order.views[1].params["db_reference"] == pytest.approx(1.0)
    assert [tuple(s) for s in mgr_order.views[1].panes[0].sources] == [
        (fid_remap[fids[1]], "torque")
    ]


def test_project_save_in_time_mode_does_not_replace_inactive_analysis_sources(
    two_file_win, tmp_path
):
    """Switching to Time-domain mode changes the SAME navigator FFT's
    analysis view reads its focused source from; saving from Time mode must
    not let that later navigator selection clobber the inactive FFT view's
    already-captured (fid, ch) sources OR its db_reference_mode/value -- the
    Task 8 nested-schema migration must not disturb this pre-existing
    fid-remap + inactive-source-capture contract (spec §13 S3). Mirrors
    ``test_project_save_preserves_all_analysis_sections_after_time_selection``
    (the pre-existing source-only regression) with the db_reference key
    added, and stays at the SAVE boundary (raw JSON) rather than a full
    reopen (see
    ``test_project_reopen_in_time_mode_does_not_replace_inactive_analysis_sources``
    below for the RESTORE-side companion, fixed in
    ``_capture_analysis_sources`` / ``open_project``)."""
    import json

    win = two_file_win
    fids = list(win.files.keys())

    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
    win.navigator.set_checked_channels([(fids[0], "speed")])
    win.inspector.fft_ctx.db_reference_control.set_mode("manual")
    win.inspector.fft_ctx.spin_db_ref.setValue(2.2e-6)
    # Switching away captures FFT's source + reference into its own state.
    win.toolbar._set_mode("time")
    # A Time-domain selection on the SAME navigator must not overwrite the
    # inactive FFT view's saved source.
    win.navigator.set_checked_channels([(fids[1], "torque")])

    proj = tmp_path / "session_time_mode_db_ref.tlproj"
    win.save_project(proj)
    raw = json.loads(proj.read_text(encoding="utf-8"))

    fft_view = raw["analysis_views"]["fft"]["views"][0]
    assert fft_view["panes"][0]["sources"] == [[fids[0], "speed"]]
    assert fft_view["params"]["db_reference_mode"] == "manual"
    assert fft_view["params"]["db_reference"] == pytest.approx(2.2e-6)


def test_project_reopen_in_time_mode_does_not_replace_inactive_analysis_sources(
    two_file_win, tmp_path, qtbot
):
    """Full save -> reopen round-trip companion to
    ``test_project_save_in_time_mode_does_not_replace_inactive_analysis_sources``:
    the SAVE-time invariant proven above does not by itself prove
    ``open_project()`` preserves it on the receiving end. ``open_project()``
    queues a post-load auto-recompute for the FFT section's restored (but
    uncached) view via ``QTimer.singleShot(0, ...)``, then -- because the
    saved ``current_mode`` is 'time' -- synchronously applies the Time view
    via ``_apply_active_view`` -> ``_plot_time_on_canvas`` ->
    ``_begin_compute_progress(process_events=True)``. That
    ``QApplication.processEvents()`` call drains the still-pending singleShot
    EARLY, still inside ``open_project()``: ``do_fft()``'s "capture current
    live selection into the active view" step must not read the shared
    Time/FFT navigator at that point, since it has already been overwritten
    with the Time view's own restored checked channels -- it must leave the
    already-correct restored FFT source alone
    (docs/lessons-learned/signal-processing/2026-07-12-processevents-drains-
    queued-recompute-during-restore.md)."""
    win = two_file_win
    fids = list(win.files.keys())

    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
    win.navigator.set_checked_channels([(fids[0], "speed")])
    # Switching away captures FFT's source into its own view state first.
    win.toolbar._set_mode("time")
    # A Time-domain selection on the SAME navigator, still displayed when the
    # project is saved (current_mode == 'time').
    win.navigator.set_checked_channels([(fids[1], "torque")])

    proj = tmp_path / "session_time_mode_reopen.tlproj"
    win.save_project(proj)

    win2 = MainWindow()
    qtbot.addWidget(win2)
    win2.open_project(proj)

    fids2 = list(win2.files.keys())
    fid_remap = {fids[i]: fids2[i] for i in range(2)}

    mgr_fft = win2.analysis_managers["fft"]
    assert [tuple(s) for s in mgr_fft.views[0].panes[0].sources] == [
        (fid_remap[fids[0]], "speed")
    ], "FFT's restored source must survive open_project(), not be replaced by Time's navigator selection"


def test_project_save_preserves_all_analysis_sections_after_time_selection(
    two_file_win, tmp_path
):
    import json

    win = two_file_win
    fids = list(win.files.keys())

    win.toolbar._set_mode("fft")
    _seed_active_analysis_attachments(win)
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


def test_save_project_success_toasts_success(two_file_win, tmp_path, monkeypatch):
    win = two_file_win
    calls = []
    monkeypatch.setattr(win, "toast", lambda msg, level: calls.append((level, msg)))

    win.save_project(tmp_path / "saved.tlproj")

    assert calls == [("success", "已保存项目")]


def test_open_project_render_failure_toasts_warning(
    two_file_win, tmp_path, qtbot, monkeypatch
):
    proj = tmp_path / "render_failure.tlproj"
    two_file_win.save_project(proj)

    win2 = MainWindow()
    qtbot.addWidget(win2)

    def fail_apply(_idx):
        raise RuntimeError("boom")

    calls = []
    monkeypatch.setattr(win2, "_apply_active_view", fail_apply)
    monkeypatch.setattr(win2, "toast", lambda msg, level: calls.append((level, msg)))

    win2.open_project(proj)

    assert ("warning", "恢复渲染失败，请手动点计算") in calls


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


# ----------------------------------------------------------------------
# dB reference defaults Task 5: MainWindow-owned service, ChannelReferenceFacts
# adapter, and Auto/Manual resolution propagation.
# Spec: docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md §8.
# Plan: docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md
# Task 5, Step 5.1.
# ----------------------------------------------------------------------

def test_channel_reference_facts_reads_head_quantity_unit_and_db_reference(
    two_file_win, tmp_path,
):
    """The facts adapter reads ONLY FileData metadata (channel_metadata's
    quantity/unit/raw db_reference string, is_audio_source()) -- never a
    sample array (docs/lessons-learned/signal-processing/
    2026-06-22-head-calibration-is-metadata-not-sample-gain.md). Missing
    (fid, ch) -> empty facts, never a crash."""
    import numpy as np
    from mf4_analyzer.io.loader import DataLoader
    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer import db_reference
    from tests._helpers.head_hdf_factory import write_head_hdf

    win = two_file_win
    n = 4
    p = write_head_hdf(
        tmp_path / "facts.hdf", n_scans=n, delta=1.0, start_of_data=2048,
        channels=[
            {"name": "ACC", "factor": 1, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 1.0, "db_reference": "2e-006",
             "samples": np.arange(n, dtype=float)},
        ])
    groups = DataLoader.load_hdf(str(p))
    g = groups[0]
    fd = FileData(
        str(p), g["data"], g["channels"], g["units"], 99,
        source_metadata=g["source_metadata"],
        channel_metadata=g["channel_metadata"],
        label_suffix=g["label_suffix"],
    )
    fid = "head-facts"
    win.files[fid] = fd

    facts = win._channel_reference_facts(fid, "ACC")
    assert isinstance(facts, db_reference.ChannelReferenceFacts)
    assert facts.quantity == "acceleration"
    assert facts.unit == "m/s^2"
    assert facts.metadata_reference == "2e-006"
    assert facts.is_audio_source is False

    # Missing channel / missing file -> empty facts, no crash.
    empty = win._channel_reference_facts(fid, "does-not-exist")
    assert empty.quantity == "" and empty.unit == ""
    empty2 = win._channel_reference_facts("no-such-file", "ACC")
    assert empty2.quantity == "" and empty2.unit == ""


def test_selected_head_channel_auto_applies_metadata_reference(two_file_win, qapp):
    """Selecting a channel with legal metadata in an Auto View resolves and
    displays the metadata reference (spec 8.1 step 2)."""
    win = two_file_win
    fid = list(win.files.keys())[0]
    win.files[fid].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²",
                  "db_reference": "2e-6"},
    }
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    qapp.processEvents()
    ctx = win.inspector.order_ctx
    assert ctx.db_reference_control.mode() == "auto"

    win._echo_combo_signal(ctx.combo_sig, (fid, "speed"))
    qapp.processEvents()

    assert ctx.db_reference_control.mode() == "auto"
    assert ctx.db_reference_control.editor.value() == pytest.approx(2e-6)
    assert "通道 metadata" in ctx.db_reference_control.full_source_text()


def test_metadata_preference_off_uses_user_or_system_catalog(two_file_win, qapp):
    """``prefer_channel_metadata=False`` skips step 2 (metadata) and falls to
    the unhidden system builtin (spec 8.1 step 4)."""
    win = two_file_win
    fid = list(win.files.keys())[0]
    win.files[fid].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²",
                  "db_reference": "2e-6"},
    }
    result = win.db_reference_store.save(
        overrides=[], custom=[], hidden_builtin_ids=[],
        prefer_channel_metadata=False,
    )
    assert result.ok

    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    qapp.processEvents()
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fid, "speed"))
    qapp.processEvents()

    assert ctx.db_reference_control.editor.value() == pytest.approx(1e-6)
    assert "系统默认" in ctx.db_reference_control.full_source_text()


def test_invalid_metadata_falls_through_to_catalog(two_file_win, qapp):
    """A non-numeric/invalid metadata db_reference is skipped (never crashes)
    and falls through to the catalog match (spec §7 R3)."""
    win = two_file_win
    fid = list(win.files.keys())[0]
    win.files[fid].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²",
                  "db_reference": "not-a-number"},
    }
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    qapp.processEvents()
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fid, "speed"))
    qapp.processEvents()

    assert ctx.db_reference_control.editor.value() == pytest.approx(1e-6)
    assert "系统默认" in ctx.db_reference_control.full_source_text()


def test_manual_view_ignores_source_and_catalog_changes(two_file_win, qapp):
    """A Manual View's value/mode survive both a source change and a catalog
    save untouched (spec 8.1 step 1 / 8.3)."""
    win = two_file_win
    fids = list(win.files.keys())
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    qapp.processEvents()
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "speed"))
    qapp.processEvents()

    # Simulate a prior manual commit (Task 4 owns the exact keypress path;
    # here we drive the same public control API a real commit would leave
    # behind: an explicit value + Manual mode).
    ctx.db_reference_control.editor.setValue(9.5)
    ctx.db_reference_control.set_mode("manual")

    win.files[fids[0]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "3e-7"},
    }
    win._echo_combo_signal(ctx.combo_sig, (fids[1], "torque"))
    qapp.processEvents()
    assert ctx.db_reference_control.mode() == "manual"
    assert ctx.db_reference_control.editor.value() == pytest.approx(9.5)

    result = win.db_reference_store.save(
        overrides=[], custom=[], hidden_builtin_ids=[], prefer_channel_metadata=True,
    )
    assert result.ok
    win._on_db_reference_catalog_saved("order")

    assert ctx.db_reference_control.mode() == "manual"
    assert ctx.db_reference_control.editor.value() == pytest.approx(9.5)


def test_catalog_save_rerenders_visible_auto_view_without_compute(two_file_win, qtbot):
    """Saving the catalog while the Order section is visible re-renders it
    from the existing cache -- zero compute-worker dispatch (spec 8.3)."""
    win = two_file_win
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "torque"))
    win._echo_combo_signal(ctx.combo_rpm, (fids[0], "speed"))

    win.do_order_time()
    _drain_order_jobs(win, qtbot)
    assert win.chart_stack.page_order.pane_canvas(0).has_result()

    # Give the focused source real metadata so the resolve below is
    # observable (system-catalog force reference) rather than the
    # empty-unit generic default.
    win.files[fids[0]].channel_metadata = {"torque": {"quantity": "force", "unit": "N"}}

    result = win.db_reference_store.save(
        overrides=[], custom=[], hidden_builtin_ids=[], prefer_channel_metadata=True,
    )
    assert result.ok

    win._on_db_reference_catalog_saved("order")

    assert ctx.db_reference_control.editor.value() == pytest.approx(1e-6)
    assert not win._analysis_jobs.is_running("order"), "a catalog save must never dispatch a compute worker"
    assert win.chart_stack.page_order.pane_canvas(0).has_result()


def test_focused_pane_controls_do_not_overwrite_inactive_pane_resolution(
    two_file_win, qapp,
):
    """Auto resolves per PANE (spec 8.4): switching focus updates the
    control to the newly-focused pane's own resolution, and switching back
    restores the FIRST pane's resolution -- neither switch mutates the
    other pane's saved ``sources``."""
    win = two_file_win
    fids = list(win.files.keys())
    # Metadata must be in place BEFORE the split helper's own initial combo
    # echo below, since re-selecting the SAME already-current index later
    # would not re-fire signal_changed (Qt only emits on an actual change).
    win.files[fids[0]].channel_metadata = {
        "torque": {"quantity": "force", "unit": "N", "db_reference": "5e-6"},
    }
    win.files[fids[1]].channel_metadata = {
        "torque": {"quantity": "force", "unit": "N", "db_reference": "8e-6"},
    }
    fids, page, state = _split_order_two_sources(win)
    ctx = win.inspector.order_ctx
    qapp.processEvents()
    assert ctx.db_reference_control.editor.value() == pytest.approx(5e-6)

    page.set_focused_index(1)
    qapp.processEvents()
    assert ctx.db_reference_control.editor.value() == pytest.approx(8e-6)
    assert state.panes[0].sources == [(fids[0], "torque")]

    page.set_focused_index(0)
    qapp.processEvents()
    assert ctx.db_reference_control.editor.value() == pytest.approx(5e-6)
    assert state.panes[1].sources == [(fids[1], "torque")]


# ----------------------------------------------------------------------
# dB reference defaults Task 6: FFT per-source conversion, mixed labels,
# legend/readout disclosure, and render-signature identity.
# Spec: docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md
# §14 (label formatter), §15 C1 (FFT render consumer), §16 (cache boundaries).
# Plan: docs/analyzer/plans/2026-07-12-db-reference-defaults-and-labeling-implementation.md
# Task 6, Step 6.1.
# ----------------------------------------------------------------------

def test_fft_auto_overlay_converts_each_entry_with_its_source_reference(two_file_win):
    """Each overlay entry converts its own CACHED LINEAR amplitude with its
    OWN source's resolved reference -- not a single global control value
    bound to only the first checked channel (spec §15 C1 / plan Step 6.2)."""
    from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer

    win = two_file_win
    fids = list(win.files.keys())
    win.files[fids[0]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "2e-6"},
    }
    win.files[fids[1]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "5e-6"},
    }
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    win.inspector.fft_ctx.combo_amp_y.setCurrentText("dB")

    win.do_fft()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._entries) == 2
    e0, e1 = canvas._entries
    r0 = e0["db_reference_resolution"]
    r1 = e1["db_reference_resolution"]
    assert r0.value == pytest.approx(2e-6)
    assert r1.value == pytest.approx(5e-6)
    np.testing.assert_allclose(
        e0["amp"],
        SpectrogramAnalyzer.amplitude_to_db(e0["amp_for_xlim"], reference=r0.value),
    )
    np.testing.assert_allclose(
        e1["amp"],
        SpectrogramAnalyzer.amplitude_to_db(e1["amp_for_xlim"], reference=r1.value),
    )


def test_fft_same_reference_uses_exact_axis_label(two_file_win):
    """Every checked source resolving to the SAME (value, unit) identity ->
    the axis shows the exact canonical label, not the mixed fallback (spec
    §15 C1 / Step 6.3)."""
    from mf4_analyzer import db_reference

    win = two_file_win
    fids = list(win.files.keys())
    for fid in fids:
        win.files[fid].channel_metadata = {
            "speed": {"quantity": "acceleration", "unit": "m/s²"},
        }
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    win.inspector.fft_ctx.combo_amp_y.setCurrentText("dB")

    win.do_fft()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    e0, e1 = canvas._entries
    r0, r1 = e0["db_reference_resolution"], e1["db_reference_resolution"]
    assert (r0.value, r0.unit) == (r1.value, r1.unit)
    expected = db_reference.format_amplitude_label(
        r0, weighting="None", output_scale="db")
    assert expected == "Amplitude (dB re 1×10⁻⁶ m/s²)"
    assert canvas._plot_amp.getAxis("left").labelText == expected
    # legend/readout stays the plain base label -- one shared reference
    # needs no per-curve disclosure.
    assert e0["legend_label"] == e0["label"]
    assert e1["legend_label"] == e1["label"]


def test_fft_mixed_reference_uses_per_curve_axis_and_entry_labels(two_file_win):
    """Two DISTINCT (value, unit) identities collapse the axis to the mixed
    label and every curve discloses its own reference (spec §15 C1 / Step
    6.3) -- never let one source's reference become the global axis."""
    from mf4_analyzer import db_reference

    win = two_file_win
    fids = list(win.files.keys())
    win.files[fids[0]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "2e-6"},
    }
    win.files[fids[1]].channel_metadata = {
        "speed": {"quantity": "force", "unit": "N", "db_reference": "5e-6"},
    }
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    win.inspector.fft_ctx.combo_amp_y.setCurrentText("dB")

    win.do_fft()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert canvas._plot_amp.getAxis("left").labelText == (
        "Amplitude (dB · per-curve reference)"
    )

    e0, e1 = canvas._entries
    r0, r1 = e0["db_reference_resolution"], e1["db_reference_resolution"]
    note0 = db_reference.format_reference_note(r0, weighting="None")
    note1 = db_reference.format_reference_note(r1, weighting="None")
    assert e0["legend_label"] == f"{e0['label']} · {note0}"
    assert e1["legend_label"] == f"{e1['label']} · {note1}"
    assert e0["legend_label"] != e1["legend_label"]
    # base source label is untouched -- the lower time-preview row (which
    # reuses these same entries) must never carry a reference suffix.
    assert e0["label"] == f"{win._file_display_name(fids[0])} · speed"
    assert e1["label"] == f"{win._file_display_name(fids[1])} · speed"


def test_fft_mixed_a_weighting_uses_dba_per_curve_label(two_file_win):
    """A-weighted + dB + mixed references -> the axis/per-curve tokens use
    'dBA', never 'dB' (spec §14.2)."""
    win = two_file_win
    fids = list(win.files.keys())
    win.files[fids[0]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "2e-6"},
    }
    win.files[fids[1]].channel_metadata = {
        "speed": {"quantity": "force", "unit": "N", "db_reference": "5e-6"},
    }
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    win.inspector.fft_ctx.combo_amp_y.setCurrentText("dB")
    win.inspector.fft_ctx.combo_weighting.setCurrentText("A")

    win.do_fft()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    assert canvas._plot_amp.getAxis("left").labelText == (
        "Amplitude (dBA · per-curve reference)"
    )
    e0, e1 = canvas._entries
    assert "dBA re" in e0["legend_label"]
    assert "dBA re" in e1["legend_label"]
    assert "dBA" not in e0["label"]  # base label never carries the token


def test_fft_cached_reentry_reformats_after_catalog_change_without_compute(
    two_file_win,
):
    """A catalog save while FFT is visible re-resolves + reformats from the
    existing cache -- zero recompute (spec §8.3 / §16)."""
    win = two_file_win
    fids = list(win.files.keys())
    for fid in fids:
        win.files[fid].channel_metadata = {
            "speed": {"quantity": "acceleration", "unit": "m/s²"},
        }
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    win.inspector.fft_ctx.combo_amp_y.setCurrentText("dB")
    win.do_fft()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    before = canvas._entries[0]["db_reference_resolution"].value
    assert before == pytest.approx(1e-6)

    compute_calls = {"n": 0}
    real_compute = win._fft_compute_arrays

    def spy(*a, **kw):
        compute_calls["n"] += 1
        return real_compute(*a, **kw)

    win._fft_compute_arrays = spy

    result = win.db_reference_store.save(
        overrides=[{
            "builtin_id": "acceleration.si",
            "label": "振动加速度",
            "unit": "m/s²",
            "aliases": ["m/s²", "m/s^2", "m/s2"],
            "reference": 3e-6,
        }],
        custom=[], hidden_builtin_ids=[], prefer_channel_metadata=True,
    )
    assert result.ok

    win._on_db_reference_catalog_saved("fft")

    after = canvas._entries[0]["db_reference_resolution"].value
    assert after == pytest.approx(3e-6)
    assert compute_calls["n"] == 0


def test_fft_render_signature_tracks_per_source_resolution_not_global_first_source(
    two_file_win,
):
    """The render signature changes when ANY checked source's resolved
    reference changes -- including the SECOND (non-first) checked source, not
    just the one a legacy single global control value would have tracked
    (spec §15 C1 / plan Step 6.5)."""
    win = two_file_win
    fids = list(win.files.keys())
    win.files[fids[0]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "2e-6"},
    }
    win.files[fids[1]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "5e-6"},
    }
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)

    sig_before = win._fft_render_signature()

    win.files[fids[1]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "9e-6"},
    }
    sig_after = win._fft_render_signature()

    assert sig_before != sig_after


def test_fft_hover_readout_discloses_each_curve_reference(two_file_win):
    """The hover readout row label for each curve is the SAME
    'legend_label' the curve is plotted under -- a mixed-reference overlay
    discloses each curve's own dB[A] re ... in the readout too (spec §15
    C1)."""
    win = two_file_win
    fids = list(win.files.keys())
    win.files[fids[0]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "2e-6"},
    }
    win.files[fids[1]].channel_metadata = {
        "speed": {"quantity": "force", "unit": "N", "db_reference": "5e-6"},
    }
    win.toolbar._set_mode("fft")
    _check_speed_in_both(win)
    win.inspector.fft_ctx.combo_amp_y.setCurrentText("dB")
    win.do_fft()

    canvas = win.chart_stack.page_fft.pane_canvas(0)
    e0, e1 = canvas._entries
    rows = canvas.readout_at(0.0)
    labels = {label for label, _f, _amp in rows}
    assert e0["legend_label"] in labels
    assert e1["legend_label"] in labels
    assert e0["legend_label"] != e0["label"]  # mixed -> disclosure appended


# ----------------------------------------------------------------------
# dB reference defaults Task 7: FFT-vs-Time / Order colorbar, slice and
# readout/remark share ONE per-pane-resolved label context (spec §15 C2/C3),
# and a heatmap section's manual colour window shifts with a reference
# change (spec §8.3.1).
# ----------------------------------------------------------------------
def test_fft_time_dba_colorbar_slice_and_readout_share_reference(two_file_win, qtbot):
    """FFT-vs-Time's colorbar, slice amplitude axis and readout/remark Z
    unit all show the SAME dBA-with-reference text, resolved from the
    pane's OWN source (spec §15 C2)."""
    from mf4_analyzer import db_reference

    win = two_file_win
    fids = list(win.files.keys())
    win.files[fids[0]].channel_metadata = {
        "speed": {"quantity": "acceleration", "unit": "m/s²", "db_reference": "1e-6"},
    }
    win.toolbar._set_mode("fft_time")
    _seed_active_analysis_attachments(win)
    ctx = win.inspector.fft_time_ctx
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "speed"))
    ctx.combo_weighting.setCurrentText("A")
    i = ctx.combo_nfft.findText("512")
    if i >= 0:
        ctx.combo_nfft.setCurrentIndex(i)

    win.do_fft_time()
    qtbot.waitUntil(
        lambda: not win._analysis_jobs.is_running("fft_time"),
        timeout=15000,
    )

    canvas = win.chart_stack.page_fft_time.pane_canvas(0)
    assert canvas.has_result()
    resolution = win._resolve_db_reference_for_source(
        "fft_time", (fids[0], "speed"))
    expected_label = db_reference.format_amplitude_label(
        resolution, weighting="A", output_scale="db")
    expected_note = db_reference.format_reference_note(
        resolution, weighting="A")
    assert "dBA re" in expected_label
    assert canvas._cbar.getAxis("left").labelText == expected_label
    assert canvas._slice_plot.getAxis("left").labelText == expected_label
    assert canvas._readout_unit() == expected_note
    assert canvas._z_unit() == expected_note


def test_order_db_colorbar_slice_and_readout_share_reference(two_file_win, qtbot):
    """Order's colorbar, slice amplitude axis and readout/remark Z unit all
    show the SAME reference-aware text (spec §15 C3), resolved from the
    pane's OWN source rather than a bare 'Amplitude (dB re <n>)' literal."""
    from mf4_analyzer import db_reference

    win = two_file_win
    fids = list(win.files.keys())
    win.files[fids[0]].channel_metadata = {
        "torque": {"quantity": "force", "unit": "N", "db_reference": "5e-6"},
    }
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "torque"))
    win._echo_combo_signal(ctx.combo_rpm, (fids[0], "speed"))

    win.do_order_time()
    qtbot.waitUntil(
        lambda: not win._analysis_jobs.is_running("order"),
        timeout=20000,
    )

    canvas = win.chart_stack.page_order.pane_canvas(0)
    assert canvas.has_result()
    resolution = win._resolve_db_reference_for_source("order", (fids[0], "torque"))
    expected_label = db_reference.format_amplitude_label(
        resolution, weighting="None", output_scale="db")
    expected_note = db_reference.format_reference_note(
        resolution, weighting="None")
    assert "dB re 5" in expected_label
    assert canvas._cbar.getAxis("left").labelText == expected_label
    assert canvas._current_amplitude_axis_label() == expected_label
    assert canvas._readout_unit() == expected_note
    assert canvas._z_unit() == expected_note


def test_heatmap_two_panes_resolve_distinct_saved_sources(two_file_win, qtbot):
    """Each Order pane's colorbar must resolve reference from its OWN saved
    source (spec §8.4), not the FOCUSED pane's control value -- the two
    files' 'torque' channel carries DIFFERENT metadata references here."""
    from mf4_analyzer import db_reference

    win = two_file_win
    fids = list(win.files.keys())
    win.files[fids[0]].channel_metadata = {
        "torque": {"quantity": "force", "unit": "N", "db_reference": "5e-6"},
    }
    win.files[fids[1]].channel_metadata = {
        "torque": {"quantity": "force", "unit": "N", "db_reference": "8e-6"},
    }
    fids, page, _state = _split_order_two_sources(win)

    win.do_order_time()
    _drain_order_jobs(win, qtbot)

    c0 = page.pane_canvas(0)
    c1 = page.pane_canvas(1)
    assert c0.has_result() and c1.has_result()
    r0 = win._resolve_db_reference_for_source("order", (fids[0], "torque"))
    r1 = win._resolve_db_reference_for_source("order", (fids[1], "torque"))
    assert r0.value != r1.value
    label0 = db_reference.format_amplitude_label(
        r0, weighting="None", output_scale="db")
    label1 = db_reference.format_amplitude_label(
        r1, weighting="None", output_scale="db")
    assert label0 != label1
    assert c0._cbar.getAxis("left").labelText == label0
    assert c1._cbar.getAxis("left").labelText == label1


def test_view_switch_restore_renders_pane_own_reference_label(two_file_win, qtbot):
    """The view-switch cache-restore path (ViewManager.active_changed ->
    _on_analysis_view_switched -> _render_analysis_view_from_cache ->
    _render_cached_heatmap) must thread the RESTORED pane's own saved
    ``(fid, ch)`` source into the heatmap renderer -- not fall back to the
    generic resolution -- exactly like the live-compute render path already
    does (flagged gap from Task 7; spec §15 C3, §8.4)."""
    from mf4_analyzer import db_reference

    win = two_file_win
    fids = list(win.files.keys())
    win.files[fids[0]].channel_metadata = {
        "torque": {"quantity": "force", "unit": "N", "db_reference": "5e-6"},
    }
    win.files[fids[1]].channel_metadata = {
        "torque": {"quantity": "force", "unit": "N", "db_reference": "8e-6"},
    }
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    mgr = win.analysis_managers["order"]
    ctx = win.inspector.order_ctx
    page = win.chart_stack.page_order

    # View 1 (already active): source A.
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "torque"))
    win._echo_combo_signal(ctx.combo_rpm, (fids[0], "speed"))
    win.do_order_time()
    _drain_order_jobs(win, qtbot)

    # View 2: source B -- a DIFFERENT file/reference metadata.
    assert mgr.new_view() == 1
    _seed_active_analysis_attachments(win)
    win._echo_combo_signal(ctx.combo_sig, (fids[1], "torque"))
    win._echo_combo_signal(ctx.combo_rpm, (fids[1], "speed"))
    win.do_order_time()
    _drain_order_jobs(win, qtbot)

    # Switch BACK to View 1: this must never recompute (spec §4) -- it
    # renders pane 0's OWN saved source (fids[0], "torque") from cache via
    # the view-switch restore path.
    mgr.set_active(0)

    canvas = page.pane_canvas(0)
    resolution_a = win._resolve_db_reference_for_source(
        "order", (fids[0], "torque"))
    expected_label_a = db_reference.format_amplitude_label(
        resolution_a, weighting="None", output_scale="db")
    assert "dB re 5" in expected_label_a
    assert canvas._cbar.getAxis("left").labelText == expected_label_a

    # Switch to View 2: same restore path, must resolve source B distinctly
    # rather than reusing View 1's (or a generic) resolution.
    mgr.set_active(1)
    resolution_b = win._resolve_db_reference_for_source(
        "order", (fids[1], "torque"))
    expected_label_b = db_reference.format_amplitude_label(
        resolution_b, weighting="None", output_scale="db")
    assert "dB re 8" in expected_label_b
    assert expected_label_a != expected_label_b
    assert canvas._cbar.getAxis("left").labelText == expected_label_b


def test_order_view_switch_with_cold_cache_does_not_submit_worker(
    two_file_win, qtbot, monkeypatch,
):
    """Applying a View's saved display reference is restore, not compute.

    The dB-reference editor emits ``valueChanged`` while params are projected
    into the live Inspector.  That programmatic signal must not schedule the
    normal user-edit cache-render callback: on a cold cache that callback
    would otherwise fall through to an Order worker submission.
    """
    win = two_file_win
    fids = list(win.files.keys())
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    mgr = win.analysis_managers["order"]
    first = mgr.get(mgr.active)
    first.panes[0].sources = [(fids[0], "torque")]
    first.panes[0].rpm_source = (fids[0], "speed")
    first.params = dict(win.inspector.order_ctx.get_params())
    first.params["db_reference"] = 2.0

    assert mgr.new_view() == 1
    _seed_active_analysis_attachments(win)
    second = mgr.get(mgr.active)
    second.panes[0].sources = [(fids[1], "torque")]
    second.panes[0].rpm_source = (fids[1], "speed")
    second.params = dict(win.inspector.order_ctx.get_params())
    second.params["db_reference"] = 3.0

    win.analysis_caches["order"].clear()
    submitted = []
    monkeypatch.setattr(
        win._analysis_jobs,
        "submit_batch",
        lambda section, jobs, **kwargs: submitted.append(
            (section, len(list(jobs)), kwargs)
        ),
    )

    mgr.set_active(0)
    qtbot.wait(50)

    assert submitted == []


def test_heatmap_reference_change_rerenders_cached_result_without_worker(
    two_file_win, qtbot,
):
    """A catalog save that changes the focused source's Auto reference
    re-renders the VISIBLE Order colorbar from cache -- with the NEW
    reference-aware label -- and dispatches zero compute workers (spec
    §8.3)."""
    win = two_file_win
    win.toolbar._set_mode("order")
    _seed_active_analysis_attachments(win)
    fids = list(win.files.keys())
    ctx = win.inspector.order_ctx
    win._echo_combo_signal(ctx.combo_sig, (fids[0], "torque"))
    win._echo_combo_signal(ctx.combo_rpm, (fids[0], "speed"))

    win.do_order_time()
    _drain_order_jobs(win, qtbot)
    canvas = win.chart_stack.page_order.pane_canvas(0)
    assert canvas.has_result()
    label_before = canvas._cbar.getAxis("left").labelText

    win.files[fids[0]].channel_metadata = {
        "torque": {"quantity": "force", "unit": "N"},
    }
    result = win.db_reference_store.save(
        overrides=[], custom=[], hidden_builtin_ids=[], prefer_channel_metadata=True,
    )
    assert result.ok
    win._on_db_reference_catalog_saved("order")

    label_after = canvas._cbar.getAxis("left").labelText
    assert label_after != label_before
    assert not win._analysis_jobs.is_running("order"), "a catalog save must never dispatch a compute worker"
    assert canvas.has_result()
