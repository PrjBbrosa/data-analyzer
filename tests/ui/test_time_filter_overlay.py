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


# --- bug A: live 显示原始/显示滤波后 toggle = setVisible 秒生效, no re-plot -----
def _plot_with_filter(w):
    """Enable a low-pass filter and plot the time domain so the canvas has a
    built chart with one original + one dashed companion per channel."""
    w.chart_stack.set_mode('time')
    w.inspector.filter_panel.set_enabled(True)
    w.inspector.filter_panel.set_kind("低通")
    w.inspector.filter_panel.set_cutoff(50.0)
    w.plot_time()


def test_live_uncheck_show_original_hides_without_replot(
    time_window_with_two_high_low_channels, monkeypatch,
):
    """Unchecking 显示原始 must flip the solid original hidden IMMEDIATELY via
    setVisible — WITHOUT triggering a full plot_time re-plot."""
    w = time_window_with_two_high_low_channels
    _plot_with_filter(w)
    canvas = w.chart_stack.focused_canvas()
    # one original + one companion (single channel → single axis).
    src_pdi = canvas._channel_lines["MOTOR/sig" if "MOTOR/sig" in canvas._channel_lines
                                    else next(iter(
        n for n in canvas._channel_lines if n not in canvas._companion_names))][1]
    src_name = next(n for n in canvas._channel_lines
                    if n not in canvas._companion_names)
    assert canvas._channel_lines[src_name][1].plot_data_item.isVisible() is True

    replot_calls = []
    monkeypatch.setattr(w, "plot_time",
                        lambda *a, **k: replot_calls.append(1))

    # Toggle the checkbox → fires original_visibility_changed → live setVisible.
    w.inspector.filter_panel.chk_orig.setChecked(False)
    assert canvas._channel_lines[src_name][1].plot_data_item.isVisible() is False
    # No re-plot was triggered.
    assert replot_calls == []
    # Companion (dashed) stays visible and its axis survives.
    comp_name = next(n for n in canvas._companion_names)
    assert canvas._channel_lines[comp_name][1].plot_data_item.isVisible() is True
    assert len(canvas.axes_list) >= 1

    # Re-check restores the original (still no re-plot).
    w.inspector.filter_panel.chk_orig.setChecked(True)
    assert canvas._channel_lines[src_name][1].plot_data_item.isVisible() is True
    assert replot_calls == []


def test_live_uncheck_show_filtered_hides_companion_without_replot(
    time_window_with_two_high_low_channels, monkeypatch,
):
    w = time_window_with_two_high_low_channels
    _plot_with_filter(w)
    canvas = w.chart_stack.focused_canvas()
    comp_name = next(n for n in canvas._companion_names)
    assert canvas._channel_lines[comp_name][1].plot_data_item.isVisible() is True

    replot_calls = []
    monkeypatch.setattr(w, "plot_time",
                        lambda *a, **k: replot_calls.append(1))

    w.inspector.filter_panel.chk_filt.setChecked(False)
    assert canvas._channel_lines[comp_name][1].plot_data_item.isVisible() is False
    assert replot_calls == []
