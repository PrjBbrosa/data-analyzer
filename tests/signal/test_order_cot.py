import numpy as np
import pytest

from mf4_analyzer.signal.order_cot import COTOrderAnalyzer, COTParams


def _synth_constant_rpm_with_2nd_order(fs=1000.0, dur=10.0, rpm_const=600.0,
                                        order_amp=1.0, noise=0.05):
    """Build a signal with constant RPM and a pure 2nd-order ripple."""
    rng = np.random.default_rng(0)
    t = np.arange(int(fs * dur)) / fs
    rpm = np.full_like(t, rpm_const)
    fpo = rpm_const / 60.0
    f_order2 = 2 * fpo  # 20Hz at 600RPM
    sig = order_amp * np.sin(2 * np.pi * f_order2 * t) + noise * rng.standard_normal(len(t))
    return t, sig, rpm


def test_cot_constant_rpm_resolves_order_2_cleanly():
    t, sig, rpm = _synth_constant_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)

    # Find order 2 column
    o2_idx = int(np.argmin(np.abs(res.orders - 2.0)))
    o2_col = res.amplitude[:, o2_idx]
    o15_col = res.amplitude[:, int(np.argmin(np.abs(res.orders - 1.5)))]
    o25_col = res.amplitude[:, int(np.argmin(np.abs(res.orders - 2.5)))]

    # Order 2 should be at least 10x larger than neighbors at order 1.5 / 2.5
    assert o2_col.mean() > 10 * o15_col.mean(), \
        f"COT failed to isolate order 2: o2={o2_col.mean():.4f} o15={o15_col.mean():.4f}"
    assert o2_col.mean() > 10 * o25_col.mean()


def _synth_swept_rpm_with_2nd_order(fs=1000.0, dur=10.0, rpm_lo=300.0, rpm_hi=900.0,
                                     order_amp=1.0, noise=0.05):
    """Linearly sweeping RPM with a true 2nd-order ripple riding on top."""
    rng = np.random.default_rng(0)
    t = np.arange(int(fs * dur)) / fs
    rpm = rpm_lo + (rpm_hi - rpm_lo) * (t / dur)
    omega = 2 * np.pi * rpm / 60.0  # rad/s instantaneous shaft frequency
    # 2nd order means phase = 2 * cumtrapz(omega)
    phase2 = 2 * np.concatenate([[0.0], np.cumsum(omega[:-1]) * (t[1] - t[0])])
    sig = order_amp * np.sin(phase2) + noise * rng.standard_normal(len(t))
    return t, sig, rpm


def test_cot_swept_rpm_still_isolates_order_2():
    t, sig, rpm = _synth_swept_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)

    o2_idx = int(np.argmin(np.abs(res.orders - 2.0)))
    o2_col = res.amplitude[:, o2_idx]
    # Order 2 should still dominate after sweep (the whole point of COT)
    assert o2_col.mean() > 0.3, \
        f"Sweep COT failed: order 2 mean={o2_col.mean():.4f}"
    # And dominate over neighbors
    o15 = res.amplitude[:, int(np.argmin(np.abs(res.orders - 1.5)))].mean()
    assert o2_col.mean() > 5 * o15


def test_cot_returns_orders_starting_at_order_res():
    t, sig, rpm = _synth_constant_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=8.0,
                  order_res=0.1, time_res=0.5)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    assert np.isclose(res.orders[0], 0.1)
    assert res.orders[-1] <= 8.0


def test_cot_handles_zero_rpm_segment():
    """Signal with a 1-second flat-zero RPM segment should not crash and
    should not produce NaN amplitudes."""
    t, sig, rpm = _synth_constant_rpm_with_2nd_order(dur=5.0)
    rpm[1000:2000] = 0.0  # 1 second of zero RPM
    p = COTParams(samples_per_rev=256, nfft=512, max_order=10.0,
                  order_res=0.1, time_res=0.5, min_rpm_floor=10.0)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    assert np.all(np.isfinite(res.amplitude))


def test_cot_params_validation():
    import pytest
    with pytest.raises(ValueError):
        COTParams(samples_per_rev=0, nfft=1024, max_order=10.0,
                  order_res=0.1, time_res=0.5)
    with pytest.raises(ValueError):
        COTParams(samples_per_rev=256, nfft=0, max_order=10.0,
                  order_res=0.1, time_res=0.5)


def test_cot_params_has_fs_field():
    """fs is needed by main_window._remember_batch_preset."""
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.05, fs=100.0)
    assert p.fs == 100.0


def test_cot_cancel_token_false_is_bit_identical_to_no_token():
    """Backward compat: a never-true cancel_token must not change one bit."""
    t, sig, rpm = _synth_constant_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5)
    baseline = COTOrderAnalyzer.compute(sig, rpm, t, p)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p, cancel_token=lambda: False)
    np.testing.assert_array_equal(res.amplitude, baseline.amplitude)
    np.testing.assert_array_equal(res.times, baseline.times)
    np.testing.assert_array_equal(res.orders, baseline.orders)


def test_cot_cancel_token_true_raises_cancelled():
    """An always-true token cancels immediately, mirroring spectrogram's
    ``RuntimeError('spectrogram computation cancelled')`` pattern."""
    import pytest
    t, sig, rpm = _synth_constant_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5)
    with pytest.raises(RuntimeError, match="cancelled") as excinfo:
        COTOrderAnalyzer.compute(sig, rpm, t, p, cancel_token=lambda: True)
    assert str(excinfo.value) == "order computation cancelled"


def test_cot_cancel_token_mid_loop_cancels():
    """Token flipping True after N polls still cancels — proves the poll
    sits inside the per-frame loop, not a one-shot check at entry."""
    import pytest
    t, sig, rpm = _synth_constant_rpm_with_2nd_order()
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5)
    state = {'count': 0}

    def cancel_after_three_polls():
        state['count'] += 1
        return state['count'] > 3

    with pytest.raises(RuntimeError, match="cancelled"):
        COTOrderAnalyzer.compute(sig, rpm, t, p,
                                 cancel_token=cancel_after_three_polls)
    # Polled at least 4 times -> the token is consulted per frame.
    assert state['count'] >= 4


def test_cot_result_params_carries_fs():
    """COT result must round-trip fs so downstream code can read result.params.fs."""
    import numpy as np
    rng = np.random.default_rng(0)
    fs = 1000.0
    t = np.arange(int(fs * 5)) / fs
    rpm = np.full_like(t, 600.0)
    sig = np.sin(2 * np.pi * 20 * t) + 0.05 * rng.standard_normal(len(t))
    p = COTParams(samples_per_rev=256, nfft=1024, max_order=10.0,
                  order_res=0.05, time_res=0.5, fs=fs)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    assert res.params.fs == fs


def test_cot_metadata_coverage_wraps_the_support_grid():
    """覆盖区间 = 支撑点各自的半格，不再是整段录制。

    旧语义把 coverage 报成「首帧左沿 → 末帧右沿」，渲染层会把帧均匀铺满这个
    比实际分析区间宽得多的范围。现在 coverage 必须紧贴支撑网格，且因为头尾
    放不下整窗，它一定落在录制区间**里面**。
    """
    fs = 1000.0
    t, sig, rpm = _synth_constant_rpm_with_2nd_order(fs=fs, dur=5.3)
    p = COTParams(
        samples_per_rev=256, nfft=512, max_order=8.0,
        order_res=0.1, time_res=0.5, fs=fs,
    )

    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    md = res.metadata

    step = float(md['time_step_s'])
    assert md['coverage_start'] == pytest.approx(res.times[0] - step / 2.0)
    assert md['coverage_end'] == pytest.approx(res.times[-1] + step / 2.0)
    # 半窗死区是真实物理：分析区间必须缩在录制区间内部。
    assert md['coverage_start'] > float(t[0])
    assert md['coverage_end'] < float(t[-1])


# ---------------------------------------------------------------------------
# Task 5: time_res → hop mapping (兑现 tooltip "越小时间越细")
# ---------------------------------------------------------------------------

def _synth_cot_signal(fs=1000.0, dur=10.0, rpm_const=600.0):
    """Return (t, sig, rpm) with a constant-RPM 2nd-order signal."""
    t, sig, rpm = _synth_constant_rpm_with_2nd_order(
        fs=fs, dur=dur, rpm_const=rpm_const, order_amp=1.0, noise=0.0
    )
    return t, sig, rpm


def test_time_res_different_values_give_different_n_frames():
    """RED until time_res → hop is wired.

    Same signal; two distinct time_res values must produce strictly different
    n_frames — proving hop is no longer hardcoded.  Under the old 75%-overlap
    hardcode both n_frames are identical, so this test is RED until the fix.
    """
    t, sig, rpm = _synth_cot_signal()

    p_coarse = COTParams(samples_per_rev=256, nfft=512, max_order=10.0,
                         order_res=0.1, time_res=0.5)
    p_fine = COTParams(samples_per_rev=256, nfft=512, max_order=10.0,
                       order_res=0.1, time_res=0.1)

    res_coarse = COTOrderAnalyzer.compute(sig, rpm, t, p_coarse)
    res_fine = COTOrderAnalyzer.compute(sig, rpm, t, p_fine)

    assert res_coarse.metadata['frames'] != res_fine.metadata['frames'], (
        f"time_res=0.5 and time_res=0.1 produced identical n_frames="
        f"{res_coarse.metadata['frames']}; hop must still be hardcoded."
    )


def test_smaller_time_res_gives_more_frames():
    """Monotonicity: time_res ↓ → n_frames ↑ (finer time grid)."""
    t, sig, rpm = _synth_cot_signal()

    results = {}
    for tr in (0.05, 0.1, 0.2, 0.5):
        p = COTParams(samples_per_rev=256, nfft=512, max_order=10.0,
                      order_res=0.1, time_res=tr)
        results[tr] = COTOrderAnalyzer.compute(sig, rpm, t, p).metadata['frames']

    time_res_sorted = sorted(results.keys())          # ascending time_res
    frames_sorted = [results[tr] for tr in time_res_sorted]
    # frames must be non-increasing (finer time_res → more frames)
    for i in range(len(frames_sorted) - 1):
        assert frames_sorted[i] >= frames_sorted[i + 1], (
            f"monotonicity broken: time_res={time_res_sorted[i]} gave "
            f"{frames_sorted[i]} frames but time_res={time_res_sorted[i+1]} "
            f"gave {frames_sorted[i+1]} frames (expected >= relationship)"
        )
    # At least one step must be strictly fewer for the coarser resolution
    assert frames_sorted[0] > frames_sorted[-1], (
        "Smallest time_res must produce strictly more frames than largest; "
        f"got {frames_sorted[0]} vs {frames_sorted[-1]}"
    )


def test_extreme_small_time_res_is_floored_at_one_angle_sample():
    """极小 time_res：网格步长被抬到「一个角度样本」这条线，不爆内存。

    网格再密也不可能比角度域采样更细，支撑点数上限就是可能的帧起点数
    ——正好等于旧实现 hop 被夹到 1 时的帧数。
    """
    t, sig, rpm = _synth_cot_signal()
    nfft = 512
    p = COTParams(samples_per_rev=256, nfft=nfft, max_order=10.0,
                  order_res=0.1, time_res=1e-9)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    md = res.metadata
    assert md['time_step_s'] > 1e-9          # 被下限抬过
    assert md['frames'] >= 1
    assert md['frames'] <= int(md['angle_samples']) - nfft + 1
    assert np.all(np.isfinite(res.amplitude))


def test_extreme_large_time_res_falls_back_to_one_centred_frame():
    """极大 time_res：没有整点落进可放窗区间 → 兜底单帧，覆盖不撑爆 x 轴。"""
    t, sig, rpm = _synth_cot_signal()
    nfft = 512
    p = COTParams(samples_per_rev=256, nfft=nfft, max_order=10.0,
                  order_res=0.1, time_res=1e6)
    res = COTOrderAnalyzer.compute(sig, rpm, t, p)
    md = res.metadata
    assert md['frames'] == 1
    # 兜底帧报的是它自己那个窗的真实中心，覆盖不超出录制区间。
    assert float(t[0]) <= md['coverage_start'] < md['coverage_end'] <= float(t[-1])
    assert np.all(np.isfinite(res.amplitude))
