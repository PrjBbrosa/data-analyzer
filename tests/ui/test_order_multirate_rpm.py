"""Multi-rate Order (COT) support: signal and motor-speed channels sampled at
DIFFERENT rates (e.g. signal 48 kHz, motor speed 1 kHz) within the same logical
recording.

The COT core (``order_cot.py``) is sample-rate agnostic but requires the three
inputs ``(sig, rpm, t)`` to be equal length on one shared time base. The UI data
prep layer (``_order_mixin._order_rpm_for``) used to bail with ``None`` ("缺转速")
whenever ``len(rpm) != len(sig)``. These tests pin the upsample-motor-speed
behaviour: the lower-rate motor-speed channel is interpolated onto the signal's
time axis (never downsampling the wideband signal), so multi-rate panes compute
instead of being skipped.

EPS context: ``rpm`` here is the EPS MOTOR SPEED used as the order base.
"""
import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.ui.main_window import MainWindow


def _register_file(win, fid, df):
    """Build a FileData from ``df`` (must carry a 'time' column) and register
    it on ``win`` under ``fid``."""
    chs = list(df.columns)
    units = {c: "" for c in chs}
    fd = FileData(str(fid) + ".csv", df, chs, units)
    win.files[fid] = fd
    return fd


@pytest.fixture
def multirate_win(qapp, qtbot):
    """MainWindow with a 48 kHz signal file and a separate 1 kHz motor-speed
    file, sharing the same 1-second time span (same origin, overlapping range,
    same total duration). The motor speed ramps linearly so interpolation is
    exact and the COT order axis is predictable."""
    win = MainWindow()
    qtbot.addWidget(win)
    win.files.clear()

    dur = 1.0
    fs_sig = 48000.0
    fs_rpm = 1000.0

    t_sig = np.arange(int(dur * fs_sig)) / fs_sig
    t_rpm = np.arange(int(dur * fs_rpm)) / fs_rpm

    # Motor speed ramps 600 -> 1800 rpm linearly over the second.
    rpm_lo = 600.0
    rpm_hi = 1800.0
    rpm_t = rpm_lo + (rpm_hi - rpm_lo) * (t_rpm / dur)

    # Order-2 content rides the instantaneous motor speed: a chirp whose
    # instantaneous frequency is 2 * rpm(t)/60. Phase = 2*pi * integral f dt.
    rpm_at_sig = rpm_lo + (rpm_hi - rpm_lo) * (t_sig / dur)
    inst_freq = 2.0 * rpm_at_sig / 60.0
    phase = 2.0 * np.pi * np.cumsum(inst_freq) / fs_sig
    sig = np.sin(phase)

    df_sig = pd.DataFrame({"time": t_sig, "vib": sig})
    df_rpm = pd.DataFrame({"time": t_rpm, "n_motor": rpm_t})
    _register_file(win, "fsig", df_sig)
    _register_file(win, "frpm", df_rpm)

    win.toolbar._set_mode("order")
    return win


def test_order_rpm_for_upsamples_motor_speed_to_signal_axis(multirate_win):
    """RED before fix: a 1 kHz motor-speed channel against a 48 kHz signal must
    NOT return None. It is interpolated onto the signal's time axis so the
    returned array is signal-length and time-aligned."""
    win = multirate_win
    fd_sig = win.files["fsig"]
    t_sig = np.asarray(fd_sig.time_array, dtype=float)
    n = len(t_sig)

    rpm = win._order_rpm_for(("frpm", "n_motor"), n, t_sig=t_sig)

    assert rpm is not None, "multi-rate motor speed must align, not be dropped"
    assert len(rpm) == n

    # Contract: linear interpolation of the 1 kHz ramp onto the 48 kHz axis,
    # with np.interp's endpoint clamp past the last speed sample.
    t_rpm = np.asarray(win.files["frpm"].time_array, dtype=float)
    rpm_t = win.files["frpm"].data["n_motor"].to_numpy(copy=False)
    expected = np.interp(t_sig, t_rpm, rpm_t)
    np.testing.assert_allclose(rpm, expected, rtol=1e-9, atol=1e-9)

    # Over the OVERLAPPING span (t_sig <= last speed sample) the linear ramp is
    # reproduced exactly — proving a true upsample, not a step/hold.
    overlap = t_sig <= t_rpm[-1]
    ramp = 600.0 + (1800.0 - 600.0) * (t_sig / 1.0)
    np.testing.assert_allclose(rpm[overlap], ramp[overlap], rtol=1e-9, atol=1e-6)


def test_order_multirate_cot_resolves_order_peak(multirate_win):
    """End-to-end: after alignment, COT computes and shows a peak at order 2
    (the synthetic content rides 2x motor speed)."""
    from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams

    win = multirate_win
    fd_sig = win.files["fsig"]
    t_sig = np.asarray(fd_sig.time_array, dtype=float)
    sig = fd_sig.data["vib"].to_numpy(copy=False)
    n = len(sig)

    rpm = win._order_rpm_for(("frpm", "n_motor"), n, t_sig=t_sig)
    assert rpm is not None

    p = COTParams(
        samples_per_rev=64,
        nfft=512,
        window="hanning",
        max_order=10.0,
        order_res=0.05,
        time_res=0.05,
        fs=48000.0,
    )
    result = COTOrderAnalyzer.compute(sig, rpm, t_sig, p)

    # Average across time frames, find the dominant order.
    mean_amp = result.amplitude.mean(axis=0)
    peak_order = result.orders[int(np.argmax(mean_amp))]
    assert peak_order == pytest.approx(2.0, abs=0.25)


def test_order_rpm_for_equal_length_unchanged(multirate_win):
    """Regression: when motor speed and signal are ALREADY equal length, the
    aligned path must be a no-op (identical values, same length) — zero
    behaviour change for the common single-rate path."""
    win = multirate_win
    fd_sig = win.files["fsig"]
    t_sig = np.asarray(fd_sig.time_array, dtype=float)
    n = len(t_sig)

    # Build a same-rate motor-speed channel on the signal file itself.
    fd_sig.data["n_same"] = 600.0 + 1200.0 * (t_sig / 1.0)

    factor = win.inspector.order_ctx.rpm_factor()
    expected = fd_sig.data["n_same"].to_numpy(copy=False) * factor

    # With t_sig provided AND lengths already matching, no interpolation runs.
    rpm = win._order_rpm_for(("fsig", "n_same"), n, t_sig=t_sig)
    assert rpm is not None
    assert len(rpm) == n
    np.testing.assert_array_equal(rpm, expected)

    # And without t_sig (legacy call), identical result.
    rpm_legacy = win._order_rpm_for(("fsig", "n_same"), n)
    np.testing.assert_array_equal(rpm_legacy, expected)


def test_order_rpm_for_nonmonotonic_motor_axis_skips(multirate_win):
    """Boundary: if the motor-speed channel's own time axis is degenerate
    (non strictly increasing), alignment is unsafe — keep the existing
    skip-the-pane (return None) behaviour rather than producing garbage."""
    win = multirate_win
    fd_sig = win.files["fsig"]
    t_sig = np.asarray(fd_sig.time_array, dtype=float)
    n = len(t_sig)

    # Corrupt the rpm file's time axis to be non-monotonic.
    fd_rpm = win.files["frpm"]
    bad_t = np.asarray(fd_rpm.time_array, dtype=float).copy()
    bad_t[10] = bad_t[5]  # introduce a non-increasing step
    fd_rpm.time_array = bad_t

    rpm = win._order_rpm_for(("frpm", "n_motor"), n, t_sig=t_sig)
    assert rpm is None
