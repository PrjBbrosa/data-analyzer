"""View-scoped analysis pickers + X reframing when the plotted extent shrinks.

Analysis pickers follow each analysis section's active View attachments
(Stage 1 source isolation), not the focused TimeDomain View.

* The FFT / FFT-vs-Time / Order signal pickers enumerate channels from the
  active analysis View's ``attached_file_ids``.
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
    """MainWindow with a long and a short recording, both auto-attached to time."""
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


def _seed_analysis_attachments(win, fids):
    for section, mgr in win.analysis_managers.items():
        mgr.get(mgr.active).attached_file_ids = list(fids)
    win._refresh_analysis_candidates()


def test_signal_pickers_only_offer_files_attached_to_analysis_view(win_two_files):
    win, long_fid, short_fid = win_two_files
    _seed_analysis_attachments(win, [long_fid, short_fid])
    for section, fids in _all_picker_fids(win).items():
        assert set(fids) == {long_fid, short_fid}, section

    # Time detach must NOT shrink analysis pickers once analysis owns attachments.
    win._detach_files_from_focused_view([short_fid], label="short.csv")
    assert short_fid in win.files
    for section, fids in _all_picker_fids(win).items():
        assert set(fids) == {long_fid, short_fid}, section

    # Narrow only the FFT active View; other sections keep both.
    win.analysis_managers["fft"].get(0).attached_file_ids = [long_fid]
    win._refresh_analysis_candidates("fft")
    assert set(_picker_fids(win.inspector.fft_ctx)) == {long_fid}
    assert set(_picker_fids(win.inspector.fft_time_ctx)) == {long_fid, short_fid}
    assert set(_picker_fids(win.inspector.order_ctx)) == {long_fid, short_fid}


def test_signal_pickers_follow_analysis_view_switch(win_two_files):
    win, long_fid, short_fid = win_two_files
    fft = win.analysis_managers["fft"]
    fft.get(0).attached_file_ids = [long_fid]
    win._on_mode_changed("fft")
    win._on_analysis_new("fft")
    # Fresh analysis View starts empty: nothing offered.
    assert _picker_fids(win.inspector.fft_ctx) == []

    win._attach_files_to_active_context([short_fid])
    assert set(_picker_fids(win.inspector.fft_ctx)) == {short_fid}

    win._on_analysis_switch("fft", 0)
    assert set(_picker_fids(win.inspector.fft_ctx)) == {long_fid}


def test_order_rpm_picker_is_scoped_to_order_attachments(win_two_files):
    win, long_fid, short_fid = win_two_files
    win.analysis_managers["order"].get(0).attached_file_ids = [long_fid]
    win._refresh_analysis_candidates("order")
    combo = win.inspector.order_ctx.combo_rpm
    fids = {
        combo.itemData(i)[0]
        for i in range(combo.count())
        if combo.itemData(i) is not None
    }
    assert fids == {long_fid}


def test_file_remove_action_stays_available_in_every_analysis_mode(
    win_two_files, qapp, monkeypatch,
):
    """All analysis modes retain the focused analysis View's file-removal action."""
    win, long_fid, short_fid = win_two_files
    monkeypatch.setattr(win, "_confirm_analysis_detach", lambda *a, **k: True)
    tree = win.navigator.channel_list.tree
    item = win.navigator.channel_list._file_items[short_fid]

    for mode in ("fft", "fft_time", "frf", "order"):
        mgr = win.analysis_managers[mode]
        mgr.get(0).attached_file_ids = [long_fid, short_fid]
        win._on_mode_changed(mode)
        qapp.processEvents()

        assert not tree.isColumnHidden(2), mode
        win.navigator.channel_list._on_item_clicked(item, 2)
        assert short_fid not in mgr.get(0).attached_file_ids, mode

        win._attach_files_to_active_context([short_fid])
        assert short_fid in mgr.get(0).attached_file_ids, mode


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
