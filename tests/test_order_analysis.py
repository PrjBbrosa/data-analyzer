from __future__ import annotations

from contextlib import contextmanager

import numpy as np
import pytest

from mf4_analyzer.signal import order as order_mod
from mf4_analyzer.signal.order import OrderAnalysisParams, OrderAnalyzer

_REAL_ORDER_AMPLITUDES_BATCH = OrderAnalyzer._order_amplitudes_batch


def _time_order_scene(*, nfft, n_frames, fs=1024.0, time_res=0.05):
    hop = max(int(fs * float(time_res)), 1)
    n = int(nfft) + (int(n_frames) - 1) * hop
    starts = list(range(0, n - nfft + 1, hop))
    assert len(starts) == n_frames
    rng = np.random.default_rng(0)
    sig = rng.standard_normal(n)
    rpm = np.linspace(600.0, 1800.0, n)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(
        fs=fs, nfft=nfft, max_order=5.0, order_res=0.5, time_res=time_res,
    )
    return sig, rpm, t, params, hop, n


def _spy_completed_batches(monkeypatch):
    sizes = []

    def spy(frames, rpm_means, fs, orders, nfft, window_array):
        sizes.append(int(np.asarray(frames).shape[0]))
        return _REAL_ORDER_AMPLITUDES_BATCH(
            frames, rpm_means, fs, orders, nfft, window_array,
        )

    monkeypatch.setattr(OrderAnalyzer, "_order_amplitudes_batch", spy)
    return sizes


@contextmanager
def _isolated_tracemalloc():
    """Record whether tracing was on, isolate the probe, restore on the way out.

    ``finally`` runs after exceptions so a failing compute cannot leave
    tracemalloc started (or stopped) relative to the enter state.
    """
    import tracemalloc

    was_tracing = tracemalloc.is_tracing()
    if was_tracing:
        tracemalloc.stop()
    tracemalloc.start()
    try:
        yield tracemalloc
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        if was_tracing:
            tracemalloc.start()


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

    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=10.0,
                                  order_res=0.5, time_res=0.1)
    result = OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
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

    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=10.0,
                                  order_res=0.5, time_res=0.05)
    result = OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
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
    """High-nfft measured node: peak vs a cap-tied chunk bound, not a product ceiling.

    Independent frame count (do not trust the old ``nfft//4`` hop comment):
    hop = max(int(fs * time_res), 1) = max(int(4096 * 0.05), 1) = 204
    n = nfft + (nfft // 4) * 1500 = 4096 + 1024 * 1500 = 1_540_096
    n_frames = (n - nfft) // hop + 1 = 1_536_000 // 204 + 1 = 7530

    The 4× ``_ORDER_BATCH_FRAMES * nfft * 8`` budget scales with the batch cap.
    That is a relative chunk bound for this measured node, not an independently
    baselined product memory ceiling.
    """
    from mf4_analyzer.signal.order import _ORDER_BATCH_FRAMES

    fs = 4096.0
    nfft = 4096
    n = nfft + (nfft // 4) * 1500
    rpm = np.linspace(600.0, 3000.0, n)
    sig = np.random.default_rng(0).standard_normal(n).astype(np.float32).astype(float)
    t = np.arange(n, dtype=float) / fs
    params = OrderAnalysisParams(fs=fs, nfft=nfft, max_order=5.0,
                                  order_res=0.5, time_res=0.05)
    hop = max(int(fs * params.time_res), 1)
    n_frames = (n - nfft) // hop + 1
    assert hop == 204
    assert n_frames == 7530

    with _isolated_tracemalloc() as tracemalloc:
        OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
        _, peak = tracemalloc.get_traced_memory()

    chunk_budget_mb = (_ORDER_BATCH_FRAMES * nfft * 8) / (1024 * 1024)
    assert peak < chunk_budget_mb * 4 * 1024 * 1024, (
        f"peak {peak / 1024 / 1024:.1f} MB > 4× chunk budget {chunk_budget_mb:.1f} MB"
    )


def test_order_memory_probe_restores_tracemalloc_after_exception():
    import tracemalloc

    was_tracing = tracemalloc.is_tracing()
    with pytest.raises(ValueError, match="shorter than nfft"):
        with _isolated_tracemalloc():
            params = OrderAnalysisParams(fs=1024.0, nfft=256)
            OrderAnalyzer.compute_time_order_result(
                np.array([1.0]), np.array([600.0]), np.array([0.0]), params,
            )
            raise AssertionError("compute should have failed before this")
    assert tracemalloc.is_tracing() is was_tracing


def test_order_batch_size_tracks_cap_not_total_frames(monkeypatch):
    cap = 4
    monkeypatch.setattr(order_mod, "_ORDER_BATCH_FRAMES", cap)
    observed = {}
    for n_frames in (8, 20):
        sizes = _spy_completed_batches(monkeypatch)
        sig, rpm, t, params, _hop, _n = _time_order_scene(
            nfft=64, n_frames=n_frames, time_res=0.01,
        )
        OrderAnalyzer.compute_time_order_result(sig, rpm, t, params)
        observed[n_frames] = list(sizes)
        assert max(sizes) == cap
        assert sum(sizes) == n_frames
        assert sizes == [cap] * (n_frames // cap) + (
            [n_frames % cap] if n_frames % cap else []
        )
    assert len(observed[20]) > len(observed[8])
    assert max(observed[20]) == max(observed[8]) == cap


def test_compute_time_order_result_respects_cancel_token(monkeypatch):
    sig, rpm, t, params, _hop, _n = _time_order_scene(nfft=64, n_frames=12, time_res=0.01)
    monkeypatch.setattr(order_mod, "_ORDER_BATCH_FRAMES", 4)
    sizes = _spy_completed_batches(monkeypatch)

    state = {"count": 0}

    def cancel_before_first_fft():
        state["count"] += 1
        return state["count"] >= 2

    with pytest.raises(RuntimeError, match="cancelled"):
        OrderAnalyzer.compute_time_order_result(
            sig, rpm, t, params, cancel_token=cancel_before_first_fft,
        )
    assert sizes == []


def test_compute_time_order_result_cancels_after_first_completed_batch(monkeypatch):
    n_frames = 12
    cap = 4
    monkeypatch.setattr(order_mod, "_ORDER_BATCH_FRAMES", cap)
    sig, rpm, t, params, _hop, _n = _time_order_scene(
        nfft=64, n_frames=n_frames, time_res=0.01,
    )
    sizes = _spy_completed_batches(monkeypatch)
    progress = []

    def cancel_after_completed_batch():
        return len(sizes) >= 1

    def cb(cur, tot):
        progress.append((int(cur), int(tot)))

    with pytest.raises(RuntimeError, match="cancelled"):
        OrderAnalyzer.compute_time_order_result(
            sig, rpm, t, params,
            progress_callback=cb,
            cancel_token=cancel_after_completed_batch,
        )
    assert len(sizes) == 1
    assert sizes[0] == cap
    assert progress
    assert all(cur < tot for cur, tot in progress)
    assert (n_frames, n_frames) not in progress


def test_compute_time_order_result_calls_progress(monkeypatch):
    n_frames = 10
    cap = 4
    monkeypatch.setattr(order_mod, "_ORDER_BATCH_FRAMES", cap)
    sig, rpm, t, params, _hop, _n = _time_order_scene(
        nfft=64, n_frames=n_frames, time_res=0.01,
    )
    sizes = _spy_completed_batches(monkeypatch)
    calls = []

    def cb(cur, tot):
        calls.append((int(cur), int(tot)))

    OrderAnalyzer.compute_time_order_result(sig, rpm, t, params, progress_callback=cb)
    assert sizes == [4, 4, 2]
    assert calls[0] == (4, n_frames)
    assert (8, n_frames) in calls
    assert calls[-1][0] == calls[-1][1] == n_frames
    assert len(sizes) == 3
