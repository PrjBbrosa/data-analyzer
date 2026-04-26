from __future__ import annotations

import numpy as np

from mf4_analyzer.signal.order import OrderAnalyzer


def test_order_track_recovers_bin_aligned_tone_amplitude():
    fs = 2048.0
    nfft = 2048
    n = nfft * 3
    target_order = 2.0
    rpm = np.full(n, 2880.0)
    freq_per_order = rpm[0] / 60.0
    tone_freq = target_order * freq_per_order
    amplitude = 2.5
    t = np.arange(n, dtype=float) / fs
    sig = amplitude * np.sin(2 * np.pi * tone_freq * t)

    _, order_amp = OrderAnalyzer.extract_order_track(
        sig,
        rpm,
        fs,
        target=target_order,
        nfft=nfft,
    )

    assert order_amp.size > 0
    assert np.isclose(np.median(order_amp), amplitude, rtol=0.03)


def test_rpm_order_counts_are_per_frame_not_per_nonzero(monkeypatch):
    """compute_rpm_order_result 的 counts 应按帧数累加，而非按非零幅值次数。

    用 monkeypatch stub 掉 `_order_amplitudes_batch`，让一半 frame 返回 0、
    一半返回 1。这样：
    - 旧语义 (`counts += values > 0`) → counts ≈ N_total/2
    - 新语义 (`counts += 1`)             → counts == N_total
    旧实现下断言必然 FAIL；新实现下必然 PASS——彻底排除 FFT leakage 误判。
    """
    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams

    call_state = {'global_idx': 0}

    def stub_batch(frames, rpm_means, fs, orders, nfft, window_array):
        n_frames_in_chunk = frames.shape[0]
        out = np.zeros((n_frames_in_chunk, len(orders)), dtype=float)
        for local_i in range(n_frames_in_chunk):
            global_i = call_state['global_idx']
            call_state['global_idx'] += 1
            if global_i % 2 == 0:
                out[local_i, :] = 1.0          # 偶数帧：所有 order 都非零
            # 奇数帧：维持 0
        return out

    monkeypatch.setattr(
        OrderAnalyzer, '_order_amplitudes_batch', staticmethod(stub_batch)
    )

    # 恒速 rpm → 所有帧落入同一个 rpm_bin
    fs = 1024.0
    nfft = 512
    n = nfft * 8                                # 实际帧数 = (n - nfft)/hop + 1，由 _frame_starts 决定
    rpm = np.full(n, 600.0)
    sig = np.zeros(n)
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=10.0,
                                  order_res=0.5, rpm_res=10.0)
    expected_frames = len(OrderAnalyzer._frame_starts(n, nfft, max(nfft // 4, 1)))
    assert expected_frames >= 4   # 否则区分不了 N vs N/2

    result = OrderAnalyzer.compute_rpm_order_result(sig, rpm, params)

    populated_bin = int(np.argmax(result.counts.sum(axis=1)))
    populated_count = result.counts[populated_bin, 0]   # 任意 order 列都该一致

    # 关键断言：counts 必须等于总帧数，而非约一半
    assert populated_count == expected_frames, (
        f"counts must be per-frame; expected {expected_frames}, "
        f"got {populated_count} (旧 nonzero-count 语义会得 ~{expected_frames // 2})"
    )
    # 同 bin 的 counts 跨 order 列必须一致（按帧累加）
    assert np.all(result.counts[populated_bin] == expected_frames)


def test_rpm_bin_index_vectorized_matches_argmin_at_boundaries():
    """rpm_bin 索引向量化 (broadcast argmin) 必须与逐帧 argmin 完全等价，
    含半-bin tie / rpm_min 边界 / rpm_max 边界 / rpm_res 不能整除区间。"""
    rpm_min, rpm_max, rpm_res = 600.0, 3550.0, 100.0   # 区间 2950 不能被 100 整除
    rpm_bins = np.arange(rpm_min, rpm_max + rpm_res * 0.5, rpm_res)
    # 构造一组刁钻的 rpm_means
    rpm_means = np.array([
        rpm_min,                       # 紧贴左边界
        rpm_min - 5,                   # 略低于左边界
        rpm_max,                       # 紧贴右边界
        rpm_max + 5,                   # 略高于右边界
        rpm_min + rpm_res * 0.5,       # 完美半-bin tie（argmin 取小）
        rpm_min + rpm_res * 0.5 + 1e-9,
        rpm_min + rpm_res * 0.5 - 1e-9,
        rpm_min + rpm_res * 1.5,       # 第二个半-bin tie
        rpm_min + 1234.5,              # 区间内任意点
    ])
    # 逐帧 argmin（reference）
    expected = np.array([
        int(np.argmin(np.abs(rpm_bins - x))) for x in rpm_means
    ])
    # 向量化 broadcast argmin（候选实现）
    diffs = np.abs(rpm_means[:, None] - rpm_bins[None, :])
    actual = np.argmin(diffs, axis=1)
    np.testing.assert_array_equal(actual, expected)


def test_time_order_recovers_target_order_amplitude():
    """compute_time_order_result 在恒速 RPM 下应能恢复目标 order 的幅值。"""
    fs = 2048.0
    nfft = 2048
    n = nfft * 5
    rpm_const = 1800.0
    rpm = np.full(n, rpm_const)
    target_order = 3.0
    freq = target_order * rpm_const / 60.0
    amp = 1.7
    t = np.arange(n, dtype=float) / fs
    sig = amp * np.sin(2 * np.pi * freq * t)

    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=10.0,
                                  order_res=0.5, time_res=0.1)
    result = OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
    # 找到 target_order 对应的列
    j = int(np.argmin(np.abs(result.orders - target_order)))
    recovered = np.median(result.amplitude[:, j])
    assert np.isclose(recovered, amp, rtol=0.05), (
        f"target order amplitude {recovered}, expected {amp}"
    )


def test_time_order_vectorized_matches_loop():
    """向量化路径应与 per-frame 实现产出完全一致的结果。"""
    fs = 1024.0
    nfft = 512
    n = nfft * 4
    rng = np.random.default_rng(42)
    sig = rng.standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs

    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=10.0,
                                  order_res=0.5, time_res=0.05)
    result = OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
    # 抽 3 帧手算 baseline
    orders = OrderAnalyzer._orders(params.max_order, params.order_res)
    hop = max(int(fs * params.time_res), 1)
    starts = list(range(0, n - nfft + 1, hop))
    for idx in [0, len(starts) // 2, len(starts) - 1]:
        s = starts[idx]
        rpm_mean = float(np.nanmean(rpm[s:s + nfft]))
        baseline = OrderAnalyzer._order_amplitudes(
            sig[s:s + nfft], rpm_mean, fs, orders, nfft, params.window
        )
        np.testing.assert_allclose(result.amplitude[idx], baseline, rtol=1e-9)


def test_vectorized_paths_match_loop_for_all_results():
    """compute_time/rpm_order_result 与 extract_order_track_result 都必须
    与逐帧 _order_amplitudes 完全一致（rtol=1e-9）。"""
    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    fs = 1024.0
    nfft = 512
    n = nfft * 6 + 100
    rng = np.random.default_rng(7)
    sig = rng.standard_normal(n)
    rpm = np.linspace(600.0, 2400.0, n)
    t = np.arange(n, dtype=float) / fs

    # === time-order ===
    p_time = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)
    r_time = OrderAnalyzer.compute_time_order_result(sig, rpm, t, p_time)
    orders = OrderAnalyzer._orders(p_time.max_order, p_time.order_res)
    hop = max(int(fs * p_time.time_res), 1)
    starts = OrderAnalyzer._frame_starts(n, nfft, hop)
    expected_full = np.zeros((len(starts), len(orders)))
    for i, s in enumerate(starts):
        rpm_mean = float(np.nanmean(rpm[s:s + nfft]))
        expected_full[i] = OrderAnalyzer._order_amplitudes(
            sig[s:s + nfft], rpm_mean, fs, orders, nfft, p_time.window
        )
    np.testing.assert_allclose(r_time.amplitude, expected_full, rtol=1e-9)

    # === rpm-order（codex round-2 A5：本路径之前漏测） ===
    p_rpm = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, rpm_res=200.0)
    r_rpm = OrderAnalyzer.compute_rpm_order_result(sig, rpm, p_rpm)
    orders_rpm = OrderAnalyzer._orders(p_rpm.max_order, p_rpm.order_res)
    rpm_min = float(np.nanmin(rpm))
    rpm_max = float(np.nanmax(rpm))
    rpm_bins = np.arange(rpm_min, rpm_max + p_rpm.rpm_res * 0.5, p_rpm.rpm_res)
    hop_rpm = max(nfft // 4, 1)
    starts_rpm = OrderAnalyzer._frame_starts(n, nfft, hop_rpm)
    expected_matrix = np.zeros((len(rpm_bins), len(orders_rpm)))
    expected_counts = np.zeros((len(rpm_bins), len(orders_rpm)))
    for s in starts_rpm:
        rpm_mean = float(np.nanmean(rpm[s:s + nfft]))
        ri = int(np.argmin(np.abs(rpm_bins - rpm_mean)))     # 与 spec §4 保留 argmin 一致
        values = OrderAnalyzer._order_amplitudes(
            sig[s:s + nfft], rpm_mean, fs, orders_rpm, nfft, p_rpm.window
        )
        expected_matrix[ri] += values
        expected_counts[ri] += 1                              # 与 spec §4 counts 帧数语义一致
    expected_amp = expected_matrix / np.maximum(expected_counts, 1)
    np.testing.assert_allclose(r_rpm.amplitude, expected_amp, rtol=1e-9)
    np.testing.assert_array_equal(r_rpm.counts, expected_counts)

    # === order-track ===
    p_track = OrderAnalysisParams(fs=fs, nfft=nfft, target_order=2.5)
    r_track = OrderAnalyzer.extract_order_track_result(sig, rpm, p_track)
    track_orders = np.array([p_track.target_order])
    hop_track = max(nfft // 4, 1)
    starts_track = OrderAnalyzer._frame_starts(n, nfft, hop_track)
    expected_track = np.zeros(len(starts_track))
    for i, s in enumerate(starts_track):
        rpm_mean = float(np.nanmean(rpm[s:s + nfft]))
        expected_track[i] = OrderAnalyzer._order_amplitudes(
            sig[s:s + nfft], rpm_mean, fs, track_orders, nfft, p_track.window
        )[0]
    np.testing.assert_allclose(r_track.amplitude, expected_track, rtol=1e-9)


def test_metadata_records_nyquist_clipped_at_median_rpm_orders():
    """高 max_order × 低 RPM 场景下，metadata 应标注被裁剪的 order 列数。"""
    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    fs = 1024.0           # Nyquist = 512 Hz
    nfft = 1024
    n = nfft * 4
    rpm = np.full(n, 600.0)   # rpm/60 = 10 Hz
    sig = np.random.default_rng(0).standard_normal(n)
    t = np.arange(n, dtype=float) / fs
    # max_order = 100 → 最大 freq = 100 * 10 = 1000 Hz > Nyquist 512 Hz
    # → 约 ((100 - 51.2) / 0.5) ≈ 97 个 order 列被裁
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=100.0,
                                  order_res=0.5, time_res=0.1)
    r = OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
    assert 'nyquist_clipped_at_median_rpm' in r.metadata
    assert r.metadata['nyquist_clipped_at_median_rpm'] > 0
    # 裁剪列对应的 amplitude 必须是 0
    median_fpo = 600.0 / 60.0
    nyq = fs * 0.5
    clipped_mask = r.orders * median_fpo > nyq
    assert np.allclose(r.amplitude[:, clipped_mask], 0.0)


def test_order_compute_memory_within_chunk_budget():
    """高 nfft 下 chunk frames 峰值应受 _ORDER_BATCH_FRAMES 限制，不随 N_total_frames 线性增长。"""
    import tracemalloc
    from mf4_analyzer.signal.order import (
        OrderAnalyzer, OrderAnalysisParams, _ORDER_BATCH_FRAMES,
    )
    fs = 4096.0
    nfft = 4096
    # 1500 frames @ nfft=4096：未 chunk 时 frame stack 峰值 ~50 MB；
    # chunk 后峰值应受 (_ORDER_BATCH_FRAMES * nfft * 8B) ≈ 8 MB 控制
    n = nfft + (nfft // 4) * 1500
    rpm = np.linspace(600.0, 3000.0, n)
    sig = np.random.default_rng(0).standard_normal(n).astype(np.float32).astype(float)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)

    tracemalloc.start()
    OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # chunk_frames 上界 ~8 MB；加上 spectra/输出 matrix/numpy overhead 留 4× headroom
    chunk_budget_mb = (_ORDER_BATCH_FRAMES * nfft * 8) / (1024 * 1024)
    assert peak < chunk_budget_mb * 4 * 1024 * 1024, (
        f"peak {peak / 1024 / 1024:.1f} MB > 4× chunk budget {chunk_budget_mb:.1f} MB"
    )


def test_compute_time_order_result_respects_cancel_token():
    fs = 1024.0
    nfft = 256
    n = nfft * 100
    sig = np.random.default_rng(0).standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs

    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.01)

    state = {'count': 0}
    def cancel_after_first_batch():
        state['count'] += 1
        return state['count'] >= 2

    import pytest
    with pytest.raises(RuntimeError, match="cancelled"):
        OrderAnalyzer.compute_time_order_result(
            sig, rpm, t, params, cancel_token=cancel_after_first_batch
        )


def test_compute_time_order_result_calls_progress():
    fs = 1024.0
    nfft = 256
    n = nfft * 50
    sig = np.random.default_rng(0).standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs

    from mf4_analyzer.signal.order import OrderAnalyzer, OrderAnalysisParams
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)

    calls = []
    def cb(cur, tot):
        calls.append((cur, tot))

    OrderAnalyzer.compute_time_order_result(sig, rpm, t, params, progress_callback=cb)
    assert len(calls) >= 1
    assert calls[-1][0] == calls[-1][1]   # 末尾 cur == total
