"""OrderAnalyzer: order tracking against a tach/RPM reference.

The public legacy helpers still return tuples consumed by ``MainWindow``,
but the implementation now routes through result objects and the shared
FFT amplitude helper from ``mf4_analyzer.signal.fft``. This keeps order
analysis aligned with the FFT and FFT-vs-Time paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .fft import one_sided_amplitude


@dataclass(frozen=True)
class OrderAnalysisParams:
    fs: float
    nfft: int = 1024
    window: str = 'hanning'
    max_order: float = 20.0
    order_res: float = 0.1
    time_res: float = 0.05
    rpm_res: float = 10.0
    target_order: float = 1.0


@dataclass
class OrderTimeResult:
    times: np.ndarray
    orders: np.ndarray
    amplitude: np.ndarray  # shape (frames, orders)
    params: OrderAnalysisParams
    metadata: dict = field(default_factory=dict)


@dataclass
class OrderRpmResult:
    orders: np.ndarray
    rpm_bins: np.ndarray
    amplitude: np.ndarray  # shape (rpm_bins, orders)
    counts: np.ndarray
    params: OrderAnalysisParams
    metadata: dict = field(default_factory=dict)


@dataclass
class OrderTrackResult:
    rpm: np.ndarray
    amplitude: np.ndarray
    params: OrderAnalysisParams
    metadata: dict = field(default_factory=dict)


class OrderAnalyzer:
    @staticmethod
    def _as_float_vector(name, values):
        arr = np.asarray(values, dtype=float)
        if arr.ndim != 1:
            arr = arr.reshape(-1)
        if arr.size == 0:
            raise ValueError(f"{name} is empty")
        return arr

    @staticmethod
    def _validate_common(sig, rpm, fs, nfft):
        sig = OrderAnalyzer._as_float_vector('signal', sig)
        rpm = OrderAnalyzer._as_float_vector('rpm', rpm)
        if len(sig) != len(rpm):
            raise ValueError(f"signal and rpm length mismatch: {len(sig)} vs {len(rpm)}")
        fs = float(fs)
        if fs <= 0 or not np.isfinite(fs):
            raise ValueError("fs must be positive")
        nfft = int(nfft)
        if nfft <= 1:
            raise ValueError("nfft must be greater than 1")
        if len(sig) < nfft:
            raise ValueError(f"signal length {len(sig)} is shorter than nfft {nfft}")
        return sig, rpm, fs, nfft

    @staticmethod
    def _orders(max_order, order_res):
        max_order = float(max_order)
        order_res = float(order_res)
        if max_order <= 0:
            raise ValueError("max_order must be positive")
        if order_res <= 0:
            raise ValueError("order_res must be positive")
        return np.arange(order_res, max_order + order_res * 0.5, order_res)

    @staticmethod
    def _frame_starts(n, nfft, hop):
        hop = max(int(hop), 1)
        return list(range(0, n - nfft + 1, hop))

    @staticmethod
    def _order_amplitudes(frame, rpm_value, fs, orders, nfft, window):
        freq_per_order = abs(float(rpm_value)) / 60.0
        if freq_per_order <= 0 or not np.isfinite(freq_per_order):
            return np.zeros(len(orders), dtype=float)
        freq, amp = one_sided_amplitude(
            frame,
            fs,
            win=window,
            nfft=nfft,
            remove_mean=True,
        )
        order_freq = orders * freq_per_order
        valid = (order_freq > 0) & (order_freq <= freq[-1])
        values = np.zeros(len(orders), dtype=float)
        if np.any(valid):
            values[valid] = np.interp(order_freq[valid], freq, amp)
        return values

    @staticmethod
    def compute_time_order_result(sig, rpm, t, params, progress_callback=None, cancel_token=None):
        sig, rpm, fs, nfft = OrderAnalyzer._validate_common(sig, rpm, params.fs, params.nfft)
        orders = OrderAnalyzer._orders(params.max_order, params.order_res)
        hop = max(int(fs * float(params.time_res)), 1)
        starts = OrderAnalyzer._frame_starts(len(sig), nfft, hop)
        total = len(starts)
        if total == 0:
            raise ValueError("no complete order-analysis frames")

        t_arr = None if t is None else OrderAnalyzer._as_float_vector('time', t)
        if t_arr is not None and len(t_arr) != len(sig):
            raise ValueError(f"time and signal length mismatch: {len(t_arr)} vs {len(sig)}")

        times = np.zeros(total, dtype=float)
        matrix = np.zeros((total, len(orders)), dtype=float)
        for idx, start in enumerate(starts):
            if cancel_token is not None and cancel_token():
                raise RuntimeError("order computation cancelled")
            if progress_callback and idx % 20 == 0:
                progress_callback(idx, total)
            end = start + nfft
            frame = sig[start:end]
            rpm_frame = rpm[start:end]
            rpm_mean = float(np.nanmean(rpm_frame))
            if t_arr is not None:
                times[idx] = float(t_arr[start + nfft // 2])
            else:
                times[idx] = (start + nfft / 2.0) / fs
            matrix[idx] = OrderAnalyzer._order_amplitudes(
                frame,
                rpm_mean,
                fs,
                orders,
                nfft,
                params.window,
            )

        if progress_callback:
            progress_callback(total, total)
        return OrderTimeResult(
            times=times,
            orders=orders,
            amplitude=matrix,
            params=params,
            metadata={'frames': total, 'hop': hop},
        )

    @staticmethod
    def compute_rpm_order_result(sig, rpm, params, progress_callback=None, cancel_token=None):
        sig, rpm, fs, nfft = OrderAnalyzer._validate_common(sig, rpm, params.fs, params.nfft)
        orders = OrderAnalyzer._orders(params.max_order, params.order_res)
        rpm_res = float(params.rpm_res)
        if rpm_res <= 0:
            raise ValueError("rpm_res must be positive")
        rpm_min = float(np.nanmin(rpm))
        rpm_max = float(np.nanmax(rpm))
        rpm_bins = np.arange(rpm_min, rpm_max + rpm_res * 0.5, rpm_res)
        if rpm_bins.size == 0:
            raise ValueError("rpm bins are empty")

        hop = max(nfft // 4, 1)
        starts = OrderAnalyzer._frame_starts(len(sig), nfft, hop)
        total = len(starts)
        matrix = np.zeros((len(rpm_bins), len(orders)), dtype=float)
        counts = np.zeros_like(matrix)

        for idx, start in enumerate(starts):
            if cancel_token is not None and cancel_token():
                raise RuntimeError("order computation cancelled")
            if progress_callback and idx % 20 == 0:
                progress_callback(idx, total)
            end = start + nfft
            rpm_mean = float(np.nanmean(rpm[start:end]))
            ri = int(np.argmin(np.abs(rpm_bins - rpm_mean)))
            values = OrderAnalyzer._order_amplitudes(
                sig[start:end],
                rpm_mean,
                fs,
                orders,
                nfft,
                params.window,
            )
            matrix[ri] += values
            counts[ri] += values > 0

        if progress_callback:
            progress_callback(total, total)
        safe_counts = counts.copy()
        safe_counts[safe_counts == 0] = 1
        return OrderRpmResult(
            orders=orders,
            rpm_bins=rpm_bins,
            amplitude=matrix / safe_counts,
            counts=counts,
            params=params,
            metadata={'frames': total, 'hop': hop},
        )

    @staticmethod
    def extract_order_track_result(sig, rpm, params, progress_callback=None, cancel_token=None):
        sig, rpm, fs, nfft = OrderAnalyzer._validate_common(sig, rpm, params.fs, params.nfft)
        target = float(params.target_order)
        if target <= 0:
            raise ValueError("target_order must be positive")
        hop = max(nfft // 4, 1)
        starts = OrderAnalyzer._frame_starts(len(sig), nfft, hop)
        total = len(starts)
        rpm_values = np.zeros(total, dtype=float)
        amplitudes = np.zeros(total, dtype=float)
        target_arr = np.array([target], dtype=float)

        for idx, start in enumerate(starts):
            if cancel_token is not None and cancel_token():
                raise RuntimeError("order computation cancelled")
            if progress_callback and idx % 20 == 0:
                progress_callback(idx, total)
            end = start + nfft
            rpm_mean = float(np.nanmean(rpm[start:end]))
            rpm_values[idx] = rpm_mean
            amplitudes[idx] = OrderAnalyzer._order_amplitudes(
                sig[start:end],
                rpm_mean,
                fs,
                target_arr,
                nfft,
                params.window,
            )[0]

        if progress_callback:
            progress_callback(total, total)
        return OrderTrackResult(
            rpm=rpm_values,
            amplitude=amplitudes,
            params=params,
            metadata={'frames': total, 'hop': hop},
        )

    @staticmethod
    def compute_order_spectrum_time_based(sig, rpm, t, fs, max_ord=20, order_res=0.1, time_res=0.05, nfft=1024,
                                          progress_callback=None):
        """时间-阶次谱，返回 ``times, orders, amplitude[time, order]``."""
        params = OrderAnalysisParams(
            fs=fs,
            nfft=nfft,
            max_order=max_ord,
            order_res=order_res,
            time_res=time_res,
        )
        result = OrderAnalyzer.compute_time_order_result(
            sig, rpm, t, params, progress_callback=progress_callback
        )
        return result.times, result.orders, result.amplitude

    @staticmethod
    def compute_order_spectrum(sig, rpm, fs, max_ord=20, rpm_res=10, order_res=0.25, nfft=1024, progress_callback=None):
        """转速-阶次谱，返回 ``orders, rpm_bins, amplitude[rpm, order]``."""
        params = OrderAnalysisParams(
            fs=fs,
            nfft=nfft,
            max_order=max_ord,
            order_res=order_res,
            rpm_res=rpm_res,
        )
        result = OrderAnalyzer.compute_rpm_order_result(
            sig, rpm, params, progress_callback=progress_callback
        )
        return result.orders, result.rpm_bins, result.amplitude

    @staticmethod
    def extract_order_track(sig, rpm, fs, target, nfft=1024):
        """单阶次跟踪，返回 ``rpm, amplitude``."""
        params = OrderAnalysisParams(
            fs=fs,
            nfft=nfft,
            target_order=target,
        )
        result = OrderAnalyzer.extract_order_track_result(sig, rpm, params)
        return result.rpm, result.amplitude
