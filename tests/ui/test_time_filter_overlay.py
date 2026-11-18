"""Task 3: time-domain filter-overlay wiring.

Constructs a real MainWindow (offscreen), loads one CSV whose single channel
is ``low + high`` (10 Hz + 400 Hz at fs=2000), ticks the channel, and exercises
``MainWindow._build_time_plot_data`` — the pure helper extracted from
``_plot_time_on_canvas``. The filter overlay is a display-layer append: each
checked channel gains a filtered trace, the original trace's ``visible`` flag
follows "显示原始", the filtered trace's follows "显示滤波后".
"""
from tests._helpers.import_tasks import wait_for_imports
import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication

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
    wait_for_imports(win)
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
    data = w._build_time_plot_data().rows
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
    data = w._build_time_plot_data().rows
    names = [d[0] for d in data]
    # one original + one filtered per channel
    assert any("(" in n and "Hz" in n for n in names)
    # filtered series has smaller high-freq energy than original
    orig = next(d for d in data if "Hz)" not in d[0])
    filt = next(d for d in data if "Hz)" in d[0])
    assert np.std(filt[3]) < np.std(orig[3])
    # the original trace stays visible, the filtered trace too (defaults on)
    assert orig[1] is True and filt[1] is True
    fid = orig[6]
    assert orig[7]["appearance_ref"] == {
        "kind": "channel",
        "fid": str(fid),
        "channel": "sig",
    }
    assert filt[7]["companion_of"] == orig[0]
    assert filt[7]["appearance_ref"] == {
        "kind": "companion",
        "fid": str(fid),
        "channel": "sig",
    }


def test_uncheck_show_filtered_hides_trace(
    time_window_with_two_high_low_channels,
):
    w = time_window_with_two_high_low_channels
    w.inspector.filter_panel.set_enabled(True)
    w.inspector.filter_panel.set_kind("低通")
    w.inspector.filter_panel.set_cutoff(50.0)
    w.inspector.filter_panel.chk_filt.setChecked(False)
    data = w._build_time_plot_data().rows
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


def test_lowpass_zero_cutoff_does_not_draw_companion(
    time_window_with_two_high_low_channels,
):
    """F-V2-1: low-pass 0 Hz is a widget value, not an enabled overlay.

    ``capture_payload`` still persists unused band cutoffs (100/2000 Hz).
    Plotting must ignore those fields so a 0 Hz low-pass does not mint
    ``LP 1e-06Hz`` after ``nyquist_guard``.
    """
    w = time_window_with_two_high_low_channels
    panel = w.inspector.filter_panel
    panel.set_kind("低通")
    panel.set_cutoff(0.0)
    panel.set_enabled(True)
    payload = panel.capture_payload()
    assert payload["spec"]["cutoff"] == pytest.approx(0.0)
    assert payload["spec"]["cutoff_lo"] > 0
    assert payload["spec"]["cutoff_hi"] > 0

    data = w._build_time_plot_data().rows
    names = [d[0] for d in data]
    assert data
    assert not any("Hz)" in name for name in names)
    assert not any("LP" in name for name in names)
    assert not any("1e-06" in name or "1e-6" in name for name in names)

    risk = w._estimate_current_time_overlay_risk(
        "overlay", w.navigator.get_checked_channels(),
    )
    assert risk.filter_enabled is False


def _write_invalid_spike_mf4(path):
    """Fs=1000, N=1000, zeros except index 500 = 1000 and invalid=True."""
    from asammdf import MDF, Signal

    count = 1000
    time = np.arange(count, dtype=np.float64) / 1000.0
    samples = np.zeros(count, dtype=np.float64)
    samples[500] = 1000.0
    invalidation = np.zeros(count, dtype=np.uint8)
    invalidation[500] = 1
    mdf = MDF(version="4.10")
    mdf.append(Signal(
        samples=samples,
        timestamps=time,
        name="torque",
        unit="Nm",
        invalidation_bits=invalidation,
    ))
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def test_invalid_spike_native_plot_rejects_the_filter_companion(
    qapp, qtbot, tmp_path,
):
    """R02 on a real MainWindow: the invalid pulse must not be filtered.

    Uses the explicit native import and ``plot_time``. The expected valid
    samples are zero; the assertion does not treat another filter call as the
    oracle.
    """
    from mf4_analyzer.io.signal_access import read_signal

    path = _write_invalid_spike_mf4(tmp_path / "invalid-spike.mf4")
    win = MainWindow()
    qtbot.addWidget(win)
    win.chart_stack.set_mode("time")
    win.request_explicit_native_import(path)
    wait_for_imports(win)
    assert len(win.files) == 1
    fid, fd = next(iter(win.files.items()))
    assert fd.is_native is True
    series = read_signal(fd, "torque")
    raw = np.array(series.values, copy=True)
    assert float(series.sampling.fs_hz) == pytest.approx(1000.0)
    assert bool(np.asarray(series.validity)[500]) is True
    win.navigator.set_checked_channels([(fid, "torque")])
    panel = win.inspector.filter_panel
    panel.set_kind("低通")
    panel.set_order(6)
    panel.set_cutoff(50.0)
    panel.set_enabled(True)
    result = win.plot_time()
    canvas = win.chart_stack.focused_canvas()
    QCoreApplication.processEvents()
    companions = [
        row for row in getattr(result, "rows", ())
        if len(row) >= 8 and isinstance(row[7], dict) and row[7].get("companion_of")
    ]
    drawn_names = list(canvas._companion_names)
    if companions or drawn_names:
        payload = np.asarray(companions[0][3], dtype=float) if companions else None
        drawn = None
        for key, name, pair in canvas._channel_lines.composite_items():
            if key in canvas._companion_names or "Hz" in str(name):
                _x, y = pair[1].plot_data_item.getData()
                drawn = np.asarray(y, dtype=float)
                break

        def _at(array, index):
            if array is None or np.asarray(array).size <= index:
                return None
            return float(np.asarray(array, dtype=float)[index])

        pytest.fail(
            "invalid 千值脉冲进入了 MainWindow 滤波："
            f"payload[499]={_at(payload, 499)!r} payload[500]={_at(payload, 500)!r} "
            f"drawn[499]={_at(drawn, 499)!r} drawn[500]={_at(drawn, 500)!r} "
            f"companion_names={drawn_names!r} "
            f"issues={[getattr(issue, 'detail', '') for issue in getattr(result, 'issues', ())]!r}"
        )
    assert result.issues, "拒绝 companion 时必须给出原因"
    text = " ".join(
        f"{issue.target_channel} {issue.detail}" for issue in result.issues
    )
    assert "torque" in text
    assert ("有效段" in text) or ("缩小" in text)
    originals = [
        row for row in result.rows
        if "torque" in str(row[0])
    ]
    assert originals
    finite = np.asarray(originals[0][3], dtype=float)
    finite = finite[np.isfinite(finite)]
    assert finite.size
    assert np.max(np.abs(finite)) == 0.0
    np.testing.assert_array_equal(np.asarray(series.values), raw)
    assert not canvas._companion_names
    assert "有效段" in win.statusBar.currentMessage()


def _companion_names(canvas):
    return {
        str(name)
        for key, name, _pair in canvas._channel_lines.composite_items()
        if key in canvas._companion_names or "Hz" in str(name)
    }


def test_valid_segment_and_filter_toggle_do_not_keep_a_stale_companion(
    qapp, qtbot, tmp_path,
):
    """A zero segment filters to zero. Closing the filter or widening onto the
    invalid pulse removes that companion instead of leaving the previous one.
    """
    from mf4_analyzer.io.signal_access import read_signal

    path = _write_invalid_spike_mf4(tmp_path / "segment-spike.mf4")
    win = MainWindow()
    qtbot.addWidget(win)
    win.chart_stack.set_mode("time")
    win.request_explicit_native_import(path)
    wait_for_imports(win)
    fid, fd = next(iter(win.files.items()))
    series = read_signal(fd, "torque")
    win.navigator.set_checked_channels([(fid, "torque")])
    panel = win.inspector.filter_panel
    panel.set_kind("低通")
    panel.set_order(6)
    panel.set_cutoff(50.0)
    panel.set_enabled(True)
    win.inspector.top.set_range_enabled(True)
    win.inspector.top.set_range_values(float(series.time[0]), float(series.time[180]))
    ranged = win.plot_time()
    canvas = win.chart_stack.focused_canvas()
    QCoreApplication.processEvents()
    companions = [
        row for row in ranged.rows
        if len(row) >= 8 and isinstance(row[7], dict) and row[7].get("companion_of")
    ]
    assert len(companions) == 1
    np.testing.assert_array_equal(np.asarray(companions[0][3], dtype=float), 0.0)
    assert _companion_names(canvas)

    win.inspector.top.set_range_enabled(False)
    rejected = win.plot_time()
    QCoreApplication.processEvents()
    assert not [
        row for row in rejected.rows
        if len(row) >= 8 and isinstance(row[7], dict) and row[7].get("companion_of")
    ]
    assert any(issue.code == "filter_quality" for issue in rejected.issues)
    assert not canvas._companion_names
    assert "有效段" in win.statusBar.currentMessage()

    panel.set_enabled(False)
    hidden = win.plot_time()
    QCoreApplication.processEvents()
    assert not [
        row for row in hidden.rows
        if len(row) >= 8 and isinstance(row[7], dict) and row[7].get("companion_of")
    ]
    assert not canvas._companion_names
    assert any("torque" in str(row[0]) for row in hidden.rows)


def test_view_switch_drops_a_filtered_companion(qapp, qtbot, tmp_path):
    path = _write_invalid_spike_mf4(tmp_path / "view-spike.mf4")
    win = MainWindow()
    qtbot.addWidget(win)
    win.chart_stack.set_mode("time")
    win.request_explicit_native_import(path)
    wait_for_imports(win)
    fid, _fd = next(iter(win.files.items()))
    win.navigator.set_checked_channels([(fid, "torque")])
    panel = win.inspector.filter_panel
    panel.set_kind("低通")
    panel.set_cutoff(50.0)
    panel.set_order(6)
    panel.set_enabled(True)
    win.inspector.top.set_range_enabled(True)
    from mf4_analyzer.io.signal_access import read_signal
    series = read_signal(win.files[fid], "torque")
    win.inspector.top.set_range_values(float(series.time[0]), float(series.time[180]))
    shown = win.plot_time()
    canvas = win.chart_stack.focused_canvas()
    QCoreApplication.processEvents()
    assert any(
        len(row) >= 8 and isinstance(row[7], dict) and row[7].get("companion_of")
        for row in shown.rows
    )
    assert canvas._companion_names
    first = win.view_manager.active
    win._capture_current_view()
    second = win.view_manager.new_view(activate=True)
    QCoreApplication.processEvents()
    assert second != first
    assert not canvas._companion_names
    win._switch_view(first)
    QCoreApplication.processEvents()
    restored = win.plot_time()
    QCoreApplication.processEvents()
    for row in restored.rows:
        meta = row[7] if len(row) >= 8 and isinstance(row[7], dict) else {}
        if not meta.get("companion_of"):
            continue
        y = np.asarray(row[3], dtype=float)
        finite = y[np.isfinite(y)]
        assert finite.size
        assert np.max(np.abs(finite)) == 0.0
    drawn = [
        np.asarray(pair[1].plot_data_item.getData()[1], dtype=float)
        for key, _name, pair in canvas._channel_lines.composite_items()
        if key in canvas._companion_names
    ]
    for y in drawn:
        finite = y[np.isfinite(y)]
        if finite.size:
            assert np.max(np.abs(finite)) == 0.0
    assert any("torque" in str(row[0]) for row in restored.rows)


def test_clean_channel_still_filters_when_a_sibling_is_rejected(
    qapp, qtbot, tmp_path,
):
    from asammdf import MDF, Signal
    from mf4_analyzer.io.signal_access import read_signal

    count = 1000
    time = np.arange(count, dtype=np.float64) / 1000.0
    torque = np.zeros(count, dtype=np.float64)
    torque[500] = 1000.0
    invalidation = np.zeros(count, dtype=np.uint8)
    invalidation[500] = 1
    speed = np.zeros(count, dtype=np.float64)
    path = tmp_path / "pair.mf4"
    mdf = MDF(version="4.10")
    mdf.append([
        Signal(
            samples=torque, timestamps=time, name="torque", unit="Nm",
            invalidation_bits=invalidation,
        ),
        Signal(samples=speed, timestamps=time, name="speed", unit="rpm"),
    ])
    mdf.save(str(path), overwrite=True)
    mdf.close()

    win = MainWindow()
    qtbot.addWidget(win)
    win.chart_stack.set_mode("time")
    win.request_explicit_native_import(path)
    wait_for_imports(win)
    fid, fd = next(iter(win.files.items()))
    assert read_signal(fd, "speed").sampling.fs_hz == pytest.approx(1000.0)
    win.navigator.set_checked_channels([(fid, "torque"), (fid, "speed")])
    panel = win.inspector.filter_panel
    panel.set_kind("低通")
    panel.set_order(6)
    panel.set_cutoff(50.0)
    panel.set_enabled(True)
    result = win.plot_time()
    companions = [
        row for row in result.rows
        if len(row) >= 8 and isinstance(row[7], dict) and row[7].get("companion_of")
    ]
    assert len(companions) == 1
    assert "speed" in str(companions[0][7]["companion_of"])
    np.testing.assert_array_equal(np.asarray(companions[0][3], dtype=float), 0.0)
    assert any(
        issue.code == "filter_quality" and issue.target_channel == "torque"
        for issue in result.issues
    )
    assert not any(issue.target_channel == "speed" for issue in result.issues)
    originals = [row for row in result.rows if row not in companions]
    assert len(originals) == 2


def test_filter_state_change_invalidates_time_canvas_cache(
    time_window_with_two_high_low_channels, monkeypatch,
):
    w = time_window_with_two_high_low_channels
    canvas = w.chart_stack.focused_canvas()
    reasons = []
    orig = canvas.invalidate_envelope_cache

    def record(reason):
        reasons.append(reason)
        return orig(reason)

    monkeypatch.setattr(canvas, "invalidate_envelope_cache", record)

    w._plot_time_on_canvas(canvas)
    w.inspector.filter_panel.set_enabled(True)
    w.inspector.filter_panel.set_kind("低通")
    w.inspector.filter_panel.set_cutoff(50.0)
    w._plot_time_on_canvas(canvas)

    assert "filter state changed" in reasons
