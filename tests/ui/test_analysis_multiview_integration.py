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
