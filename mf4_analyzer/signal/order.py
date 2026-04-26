"""OrderAnalyzer: order tracking against a tach/RPM reference.

The public legacy helpers still return tuples consumed by ``MainWindow``,
but the implementation now routes through result objects and the shared
FFT amplitude helper from ``mf4_analyzer.signal.fft``. This keeps order
analysis aligned with the FFT and FFT-vs-Time paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .fft import get_analysis_window, one_sided_amplitude


# Chunk size for vectorized FFT batching. Bounded to keep
# peak frame-stack memory (BATCH * nfft * 8B) within ~32 MB at extreme nfft.
_ORDER_BATCH_FRAMES = 256


@dataclass(frozen=True)
class OrderAnalysisParams:
    fs: float
    nfft: int = 1024
    window: str = 'hanning'
    max_order: float = 20.0
    order_res: float = 0.1
    time_res: float = 0.05
    target_order: float = 1.0


@dataclass
class OrderTimeResult:
    times: np.ndarray
    orders: np.ndarray
    amplitude: np.ndarray  # shape (frames, orders)
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
        """Per-frame order amplitudes. RETAINED AS TEST BASELINE ONLY.

        Production paths now route through ``_order_amplitudes_batch``.
        This method is preserved unchanged so vectorized-vs-loop
        equivalence tests have an independent baseline that cannot share
        a bug with the batched implementation.
        """
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
    def _order_amplitudes_batch(frames, rpm_means, fs, orders, nfft, window_array):
        """Vectorized batched order amplitudes.

        Parameters
        ----------
        frames : ndarray of shape ``(N_frames, nfft)``
            Time-domain windows. NOT pre-demeaned; this function removes
            per-frame mean before windowing.
        rpm_means : ndarray of shape ``(N_frames,)``
            Mean RPM per frame.
        fs : float
            Sample rate in Hz.
        orders : ndarray of shape ``(N_orders,)``
            Order axis (multiples of rotation frequency).
        nfft : int
            FFT length.
        window_array : ndarray of shape ``(nfft,)``
            Pre-computed analysis window (hoisted by the caller).

        Returns
        -------
        ndarray of shape ``(N_frames, N_orders)``

        Notes
        -----
        Doubling is byte-for-byte aligned with
        :func:`mf4_analyzer.signal.fft.one_sided_amplitude`:

        * ``amps.shape[1] > 2`` and ``nfft`` even: ``amps[:, 1:-1] *= 2.0``
        * ``amps.shape[1] > 2`` and ``nfft`` odd:  ``amps[:, 1:]   *= 2.0``
        * ``amps.shape[1] == 2``: pass (no doubling)

        ``amps.shape[1] == 2`` corresponds to ``nfft in {2, 3}`` (rfft
        outputs ``nfft//2 + 1`` bins). Do NOT introduce an ``nfft == 3``
        special case — that would diverge from ``one_sided_amplitude``.

        Nyquist clipping is NOT performed here. Order columns whose
        target frequency exceeds Nyquist are zeroed via the per-frame
        ``valid`` mask so this function stays a pure numerical unit.
        Aggregate-level Nyquist metadata is set by the caller.
        """
        # In-place ops minimize transient chunk-sized buffers so peak
        # memory stays close to the chunk_frames upper bound (see
        # ``_ORDER_BATCH_FRAMES`` docstring). ``frames`` is freshly
        # stacked by the caller and not aliased elsewhere — mutating
        # it in place would also be safe, but we keep the demean as a
        # copy for clarity since ``work`` is used downstream.
        work = frames - frames.mean(axis=1, keepdims=True)
        work *= window_array  # in-place multiply: no second chunk-sized buffer
        spectra = np.fft.rfft(work, n=nfft, axis=1)
        del work  # release demeaned/windowed buffer before amps allocation
        win_mean = float(np.mean(window_array))
        amps = np.abs(spectra)
        del spectra  # release complex buffer (twice the size of float)
        amps /= nfft
        amps /= win_mean
        if amps.shape[1] > 2:
            if nfft % 2 == 0:
                amps[:, 1:-1] *= 2.0
            else:
                amps[:, 1:] *= 2.0
        elif amps.shape[1] == 2:
            # nfft in {2, 3}: DC + Nyquist (or 2-bin rfft); no interior bin.
            # Mirror one_sided_amplitude's amp.size == 2 branch (pass).
            pass

        freq = np.fft.rfftfreq(nfft, 1.0 / fs)
        freq_per_order = np.abs(rpm_means) / 60.0
        out = np.zeros((len(rpm_means), len(orders)), dtype=float)
        for i, fpo in enumerate(freq_per_order):
            if fpo <= 0 or not np.isfinite(fpo):
                continue
            order_freq = orders * fpo
            valid = (order_freq > 0) & (order_freq <= freq[-1])
            if np.any(valid):
                out[i, valid] = np.interp(order_freq[valid], freq, amps[i])
        return out

    @staticmethod
    def _nyquist_clipped_at_median_rpm(rpm, orders, fs):
        """Estimate how many order columns are above Nyquist at the
        dataset's median RPM.

        This is a statistical indicator only — variable-RPM datasets
        will see different clip counts per frame. The caller stamps it
        into result ``metadata`` under the key
        ``nyquist_clipped_at_median_rpm`` to flag this as an at-median
        estimate, not a frame-level fact.
        """
        median_rpm = float(np.nanmedian(rpm))
        median_fpo = abs(median_rpm) / 60.0
        nyq = fs * 0.5
        if median_fpo > 0 and np.isfinite(median_fpo):
            return int(np.sum(orders * median_fpo > nyq))
        return 0

    @staticmethod
    def compute_time_order_result(sig, rpm, t, params, progress_callback=None, cancel_token=None):
        sig, rpm, fs, nfft = OrderAnalyzer._validate_common(sig, rpm, params.fs, params.nfft)
        orders = OrderAnalyzer._orders(params.max_order, params.order_res)
        hop = max(int(fs * float(params.time_res)), 1)
        starts = OrderAnalyzer._frame_starts(len(sig), nfft, hop)
        total = len(starts)
        if total == 0:
            raise ValueError("no complete order-analysis frames")

        window_array = get_analysis_window(params.window, nfft)
        nyquist_clipped = OrderAnalyzer._nyquist_clipped_at_median_rpm(rpm, orders, fs)

        t_arr = None if t is None else OrderAnalyzer._as_float_vector('time', t)
        if t_arr is not None and len(t_arr) != len(sig):
            raise ValueError(f"time and signal length mismatch: {len(t_arr)} vs {len(sig)}")

        times = np.zeros(total, dtype=float)
        matrix = np.zeros((total, len(orders)), dtype=float)

        def _check_cancel():
            if cancel_token is not None and cancel_token():
                raise RuntimeError("order computation cancelled")

        for batch_start in range(0, total, _ORDER_BATCH_FRAMES):
            _check_cancel()  # cancel #1: chunk boundary
            batch_end = min(batch_start + _ORDER_BATCH_FRAMES, total)
            chunk_starts = starts[batch_start:batch_end]

            _check_cancel()  # cancel #2: before stack
            frames = np.stack([sig[s:s + nfft] for s in chunk_starts], axis=0)
            rpm_means = np.array(
                [float(np.nanmean(rpm[s:s + nfft])) for s in chunk_starts],
                dtype=float,
            )
            if t_arr is not None:
                times[batch_start:batch_end] = np.array(
                    [float(t_arr[s + nfft // 2]) for s in chunk_starts]
                )
            else:
                times[batch_start:batch_end] = np.array(
                    [(s + nfft / 2.0) / fs for s in chunk_starts]
                )

            _check_cancel()  # cancel #3: before FFT batch
            matrix[batch_start:batch_end] = OrderAnalyzer._order_amplitudes_batch(
                frames, rpm_means, fs, orders, nfft, window_array,
            )
            if progress_callback:
                progress_callback(batch_end, total)

        if progress_callback:
            progress_callback(total, total)

        return OrderTimeResult(
            times=times,
            orders=orders,
            amplitude=matrix,
            params=params,
            metadata={
                'frames': total,
                'hop': hop,
                'nyquist_clipped_at_median_rpm': nyquist_clipped,
            },
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

        window_array = get_analysis_window(params.window, nfft)
        # For the single-target track we still report the at-median Nyquist
        # estimate against the requested target order so the metadata
        # contract is consistent across all three result types.
        nyquist_clipped = OrderAnalyzer._nyquist_clipped_at_median_rpm(rpm, target_arr, fs)

        def _check_cancel():
            if cancel_token is not None and cancel_token():
                raise RuntimeError("order computation cancelled")

        for batch_start in range(0, total, _ORDER_BATCH_FRAMES):
            _check_cancel()  # cancel #1: chunk boundary
            batch_end = min(batch_start + _ORDER_BATCH_FRAMES, total)
            chunk_starts = starts[batch_start:batch_end]

            _check_cancel()  # cancel #2: before stack
            frames = np.stack([sig[s:s + nfft] for s in chunk_starts], axis=0)
            rpm_means = np.array(
                [float(np.nanmean(rpm[s:s + nfft])) for s in chunk_starts],
                dtype=float,
            )
            rpm_values[batch_start:batch_end] = rpm_means

            _check_cancel()  # cancel #3: before FFT batch
            chunk_amps = OrderAnalyzer._order_amplitudes_batch(
                frames, rpm_means, fs, target_arr, nfft, window_array,
            )
            amplitudes[batch_start:batch_end] = chunk_amps[:, 0]

            if progress_callback:
                progress_callback(batch_end, total)

        if progress_callback:
            progress_callback(total, total)
        return OrderTrackResult(
            rpm=rpm_values,
            amplitude=amplitudes,
            params=params,
            metadata={
                'frames': total,
                'hop': hop,
                'nyquist_clipped_at_median_rpm': nyquist_clipped,
            },
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
    def extract_order_track(sig, rpm, fs, target, nfft=1024):
        """单阶次跟踪，返回 ``rpm, amplitude``."""
        params = OrderAnalysisParams(
            fs=fs,
            nfft=nfft,
            target_order=target,
        )
        result = OrderAnalyzer.extract_order_track_result(sig, rpm, params)
        return result.rpm, result.amplitude
