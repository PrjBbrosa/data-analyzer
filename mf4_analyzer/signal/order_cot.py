"""Computed Order Tracking (COT) — angle-domain order analysis.

Pipeline:
    1. abs_rpm = |RPM(t)|; omega(t) = abs_rpm * 2*pi / 60      (rad/s)
    2. theta(t) = integral of omega(t) dt                      (cumulative angle, rad)
    3. resample s(t) onto uniform-d_theta grid s(theta)        (np.interp)
    4. windowed FFT of s(theta) per-frame -> orders direct
       (bin k -> k * samples_per_rev / nfft)

Edge cases:
    - RPM=0 segments collapse theta -> degenerate interp. We zero out frames
      whose mean |RPM| < min_rpm_floor.
    - Forward/reverse rotation aliased onto same orders by |RPM|.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .fft import get_analysis_window


@dataclass(frozen=True)
class COTParams:
    samples_per_rev: int = 256
    nfft: int = 1024
    window: str = 'hanning'
    max_order: float = 20.0
    order_res: float = 0.05
    time_res: float = 0.05      # in seconds, hop in time domain (mapped to angle)
    fs: float = 0.0             # source sample rate; carried through for batch-preset capture
    min_rpm_floor: float = 10.0  # frames whose mean |rpm| below this are zeroed

    def __post_init__(self):
        if self.samples_per_rev <= 0:
            raise ValueError("samples_per_rev must be > 0")
        if self.nfft <= 0:
            raise ValueError("nfft must be > 0")
        if self.max_order <= 0:
            raise ValueError("max_order must be > 0")
        if self.order_res <= 0:
            raise ValueError("order_res must be > 0")


@dataclass
class COTResult:
    times: np.ndarray             # frame center times in seconds
    orders: np.ndarray            # order axis (interpolated to user grid)
    amplitude: np.ndarray         # shape (frames, orders)
    params: COTParams
    metadata: dict = field(default_factory=dict)


class COTOrderAnalyzer:
    @staticmethod
    def _validate(sig, rpm, t):
        sig = np.asarray(sig, dtype=float)
        rpm = np.asarray(rpm, dtype=float)
        t = np.asarray(t, dtype=float)
        if sig.ndim != 1 or rpm.ndim != 1 or t.ndim != 1:
            raise ValueError("sig, rpm, t must be 1-D")
        if not (len(sig) == len(rpm) == len(t)):
            raise ValueError(
                f"length mismatch: sig={len(sig)} rpm={len(rpm)} t={len(t)}"
            )
        if len(sig) < 16:
            raise ValueError("signal too short")
        if np.any(np.diff(t) <= 0):
            raise ValueError("time vector must be strictly monotonically increasing")
        return sig, rpm, t

    @staticmethod
    def compute(sig, rpm, t, params: COTParams,
                progress_callback=None, cancel_token=None) -> COTResult:
        sig, rpm, t = COTOrderAnalyzer._validate(sig, rpm, t)

        abs_rpm = np.abs(rpm)
        omega = abs_rpm * 2.0 * np.pi / 60.0           # rad/s
        # cumulative angle via trapezoidal integration
        dt = np.diff(t)
        # midpoint-trapezoid: theta_i = theta_{i-1} + (omega_{i-1} + omega_i)/2 * dt_{i-1}
        theta = np.zeros_like(t)
        theta[1:] = np.cumsum(0.5 * (omega[:-1] + omega[1:]) * dt)
        theta_max = float(theta[-1])

        if theta_max <= 0:
            raise ValueError(
                "RPM is zero throughout the signal — COT cannot resolve orders"
            )

        # uniform angle grid
        dtheta = 2.0 * np.pi / params.samples_per_rev
        theta_uniform = np.arange(0.0, theta_max, dtheta)
        if len(theta_uniform) < params.nfft:
            raise ValueError(
                f"signal covers only {theta_max / (2*np.pi):.2f} revolutions; "
                f"need at least {params.nfft / params.samples_per_rev:.2f} "
                f"for nfft={params.nfft}"
            )

        # angle-domain signal
        s_theta = np.interp(theta_uniform, theta, sig)

        # angle-domain time map: t_uniform = interp(theta_uniform, theta, t)
        t_uniform = np.interp(theta_uniform, theta, t)
        rpm_uniform = np.interp(theta_uniform, theta, abs_rpm)

        # frame layout in angle domain
        nfft = int(params.nfft)
        # hop in samples = time_res * (samples_per_rev * mean_rps) seconds-equivalent
        # but in angle domain we just hop by a fixed fraction of nfft.
        hop_angle = max(int(nfft * 0.25), 1)            # 75% overlap default
        starts = np.arange(0, len(s_theta) - nfft + 1, hop_angle)
        n_frames = len(starts)
        if n_frames == 0:
            raise ValueError("not enough angle-domain samples for one frame")

        w = get_analysis_window(params.window, nfft)
        w_sum = float(np.sum(w))

        # raw bin-orders: bin k -> k * samples_per_rev / nfft
        raw_orders = np.arange(nfft // 2 + 1) * (params.samples_per_rev / nfft)

        # user-facing order grid (dropping below first raw order, capped at max_order)
        out_orders = np.arange(params.order_res,
                               params.max_order + params.order_res * 0.5,
                               params.order_res)
        amp_matrix = np.zeros((n_frames, len(out_orders)), dtype=float)
        times_arr = np.zeros(n_frames, dtype=float)

        def _check_cancel():
            if cancel_token is not None and cancel_token():
                raise RuntimeError("COT cancelled")

        for idx, start in enumerate(starts):
            _check_cancel()
            frame = s_theta[start:start + nfft]
            mean_rpm_frame = float(np.mean(rpm_uniform[start:start + nfft]))
            times_arr[idx] = float(t_uniform[start + nfft // 2])

            if mean_rpm_frame < params.min_rpm_floor:
                # zero-out low-RPM frames; angle integration unreliable
                continue

            spec = np.fft.rfft((frame - frame.mean()) * w)
            amp_raw = np.abs(spec) / w_sum * 2.0
            amp_raw[0] /= 2.0
            if (nfft % 2) == 0:
                amp_raw[-1] /= 2.0

            # interpolate raw_orders -> out_orders
            amp_matrix[idx, :] = np.interp(out_orders, raw_orders, amp_raw,
                                           left=0.0, right=0.0)

            if progress_callback is not None:
                progress_callback(idx + 1, n_frames)

        if progress_callback is not None:
            progress_callback(n_frames, n_frames)

        return COTResult(
            times=times_arr,
            orders=out_orders,
            amplitude=amp_matrix,
            params=params,
            metadata={
                'frames': n_frames,
                'samples_per_rev': params.samples_per_rev,
                'theta_max_rev': theta_max / (2 * np.pi),
                'angle_samples': len(s_theta),
            },
        )
