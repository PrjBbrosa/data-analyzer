from __future__ import annotations

import numpy as np

from mf4_analyzer.signal.order import OrderAnalyzer


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
