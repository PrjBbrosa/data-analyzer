"""Task 3: time-domain filter-overlay wiring.

Constructs a real MainWindow (offscreen), loads one CSV whose single channel
is ``low + high`` (10 Hz + 400 Hz at fs=2000), ticks the channel, and exercises
``MainWindow._build_time_plot_data`` — the pure helper extracted from
``_plot_time_on_canvas``. The filter overlay is a display-layer append: each
checked channel gains a filtered trace, the original trace's ``visible`` flag
follows "显示原始", the filtered trace's follows "显示滤波后".
"""
import numpy as np
import pytest

from mf4_analyzer.ui.main_window import MainWindow


@pytest.fixture
def time_window_with_two_high_low_channels(qapp, tmp_path, qtbot):
    """MainWindow with one loaded CSV: channel = 10 Hz low + 400 Hz high."""
    import pandas as pd

    fs = 2000.0
    t = np.arange(0, 2.0, 1.0 / fs)
    low = np.sin(2 * np.pi * 10 * t)
    high = np.sin(2 * np.pi * 400 * t)
    df = pd.DataFrame({"time": t, "sig": low + high})
    p = tmp_path / "lowhigh.csv"
    df.to_csv(p, index=False)

    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(p))
    assert len(win.files) == 1
    fid = next(iter(win.files))
    win.navigator.set_checked_channels([(fid, "sig")])
    assert win.navigator.get_checked_channels()
    return win


def test_filter_off_by_default_no_overlay(
    time_window_with_two_high_low_channels,
):
    """A freshly-opened inspector must not overlay filtered traces: filtering
    is opt-in, so a routine plot keeps exactly one trace per checked channel."""
    w = time_window_with_two_high_low_channels
    assert w.inspector.filter_panel.is_enabled() is False
    data = w._build_time_plot_data()
    assert len(data) == 1
    assert not any("Hz)" in d[0] for d in data)


def test_filtered_trace_appended_and_attenuated(
    time_window_with_two_high_low_channels,
):
    w = time_window_with_two_high_low_channels
    w.inspector.filter_panel.set_enabled(True)
    w.inspector.filter_panel.set_kind("低通")
    w.inspector.filter_panel.set_cutoff(50.0)
    w.inspector.filter_panel.set_order(6)
    data = w._build_time_plot_data()
    names = [d[0] for d in data]
    # one original + one filtered per channel
    assert any("(" in n and "Hz" in n for n in names)
    # filtered series has smaller high-freq energy than original
    orig = next(d for d in data if "Hz)" not in d[0])
    filt = next(d for d in data if "Hz)" in d[0])
    assert np.std(filt[3]) < np.std(orig[3])
    # the original trace stays visible, the filtered trace too (defaults on)
    assert orig[1] is True and filt[1] is True


def test_uncheck_show_filtered_hides_trace(
    time_window_with_two_high_low_channels,
):
    w = time_window_with_two_high_low_channels
    w.inspector.filter_panel.set_enabled(True)
    w.inspector.filter_panel.set_kind("低通")
    w.inspector.filter_panel.set_cutoff(50.0)
    w.inspector.filter_panel.chk_filt.setChecked(False)
    data = w._build_time_plot_data()
    # filtered traces present but visible=False (so cancel = just hide)
    filt = [d for d in data if "Hz)" in d[0]]
    assert filt and all(d[1] is False for d in filt)
