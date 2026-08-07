"""View-scoped analysis pickers + X reframing when the plotted extent shrinks.

Both behaviours answer the same complaint: the UI kept offering / showing
something that belongs to data the current View is not looking at.

* The FFT / FFT-vs-Time / Order signal pickers used to enumerate every loaded
  file. Ten files open with one dragged into the View meant ten files' channels
  were searchable, and picking one produced an analysis with no counterpart in
  the navigator, the channel tree, or the chart.
* The replot path preserves the visible X window so ticking a channel does not
  yank the viewport away from a zoom. When the replot swapped in a *shorter*
  recording the stale window survived anyway — 49.5 s of data framed by a 185 s
  window left over from another file, i.e. a mostly blank chart.
"""
import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.main_window import MainWindow


def _write_csv(path, *, duration, channels):
    t = np.linspace(0.0, duration, 400)
    df = pd.DataFrame({"time": t})
    for name in channels:
        df[name] = np.sin(2 * np.pi * 3 * t)
    df.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def win_two_files(qapp, qtbot, tmp_path):
    """MainWindow with a long and a short recording, both auto-attached."""
    long_p = _write_csv(
        tmp_path / "long.csv", duration=30.0, channels=["speed", "torque"]
    )
    short_p = _write_csv(
        tmp_path / "short.csv", duration=3.0, channels=["rack_force"]
    )
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(long_p)
    win._load_one(short_p)
    assert len(win.files) == 2
    long_fid, short_fid = list(win.files)
    return win, long_fid, short_fid


def _picker_fids(ctx):
    """File ids currently offered by a section's signal picker."""
    combo = ctx.combo_sig
    return [
        combo.itemData(i)[0]
        for i in range(combo.count())
        if combo.itemData(i) is not None
    ]


def _all_picker_fids(win):
    return {
        "fft": _picker_fids(win.inspector.fft_ctx),
        "fft_time": _picker_fids(win.inspector.fft_time_ctx),
        "order": _picker_fids(win.inspector.order_ctx),
    }


def test_signal_pickers_only_offer_files_attached_to_focused_view(win_two_files):
    win, long_fid, short_fid = win_two_files
    idx, state = win._focused_time_view_state()
    assert set(state.attached_file_ids) == {long_fid, short_fid}
    for section, fids in _all_picker_fids(win).items():
        assert set(fids) == {long_fid, short_fid}, section

    win._detach_files_from_focused_view([short_fid], label="short.csv")

    # Still loaded — just not in this View, so not searchable from it.
    assert short_fid in win.files
    assert set(win.view_manager.get(idx).attached_file_ids) == {long_fid}
    for section, fids in _all_picker_fids(win).items():
        assert set(fids) == {long_fid}, section


def test_signal_pickers_follow_view_switch(win_two_files):
    win, long_fid, short_fid = win_two_files
    win._detach_files_from_focused_view([short_fid], label="short.csv")

    win._on_view_new()
    # A fresh View has no attached files: nothing to analyse, nothing offered.
    for section, fids in _all_picker_fids(win).items():
        assert fids == [], section

    win._attach_files_to_focused_view([short_fid])
    for section, fids in _all_picker_fids(win).items():
        assert set(fids) == {short_fid}, section

    win._switch_view(0)
    for section, fids in _all_picker_fids(win).items():
        assert set(fids) == {long_fid}, section


def test_order_rpm_picker_is_scoped_too(win_two_files):
    win, long_fid, short_fid = win_two_files
    win._detach_files_from_focused_view([short_fid], label="short.csv")
    combo = win.inspector.order_ctx.combo_rpm
    fids = {
        combo.itemData(i)[0]
        for i in range(combo.count())
        if combo.itemData(i) is not None
    }
    assert fids == {long_fid}


def _visible_xlim(win):
    return win.canvas_time.get_visible_xlim()


def test_replot_reframes_when_the_plotted_extent_shrinks(win_two_files, qapp):
    """Swapping to a shorter recording must not keep the longer window."""
    win, long_fid, short_fid = win_two_files
    win.navigator.set_checked_channels([(long_fid, "speed")])
    win.plot_time()
    qapp.processEvents()
    lo, hi = _visible_xlim(win)
    assert hi == pytest.approx(30.0, abs=0.5)

    win.navigator.set_checked_channels([(short_fid, "rack_force")])
    win._ch_changed()
    qapp.processEvents()

    lo, hi = _visible_xlim(win)
    assert hi == pytest.approx(3.0, abs=0.2), "framed the 3 s recording, not 30 s"
    assert lo == pytest.approx(0.0, abs=0.2)


def test_replot_keeps_a_user_zoom_inside_unchanged_data(win_two_files, qapp):
    """The preserve-X behaviour itself must survive: a zoom is a subset."""
    win, long_fid, _short_fid = win_two_files
    win.navigator.set_checked_channels([(long_fid, "speed")])
    win.plot_time()
    qapp.processEvents()

    win.canvas_time.restore_visible_xlim((10.0, 20.0))
    qapp.processEvents()
    assert _visible_xlim(win) == pytest.approx((10.0, 20.0), abs=0.01)

    # Tick a second channel from the same file: same extent, so the zoom stays.
    win.navigator.set_checked_channels(
        [(long_fid, "speed"), (long_fid, "torque")]
    )
    win._ch_changed()
    qapp.processEvents()

    assert _visible_xlim(win) == pytest.approx((10.0, 20.0), abs=0.01)


def test_preserved_window_fit_rule(win_two_files):
    """Unit-level truth table for the reframe predicate."""
    win, long_fid, _short = win_two_files
    win.navigator.set_checked_channels([(long_fid, "speed")])
    win.plot_time()
    canvas = win.canvas_time
    union_lo, union_hi = canvas.get_data_x_union()
    span = union_hi - union_lo

    fits = win._preserved_xlim_fits_data
    assert fits(canvas, union_lo, union_hi), "full view == extent"
    assert fits(canvas, union_lo + 0.3 * span, union_lo + 0.6 * span), "zoom in"
    assert not fits(canvas, union_lo, union_hi + 5 * span), "window overruns data"
    assert not fits(canvas, union_lo - 5 * span, union_hi), "window starts early"
