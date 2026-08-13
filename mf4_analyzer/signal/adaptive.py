"""Adaptive defaults for signal-analysis parameters."""
from __future__ import annotations

import math

import numpy as np


def ceil_pow2(x):
    """Return the smallest power of two greater than or equal to ``x``."""
    value = float(x)
    if value <= 0.0 or not math.isfinite(value):
        raise ValueError("x must be positive")
    return int(2 ** math.ceil(math.log2(value)))


def resolve_nfft(
    fs,
    n_samples,
    t_win_s,
    overlap,
    *,
    floor=64,
    ceil=8192,
    min_frames=24,
    max_window_frac=0.15,
):
    """Resolve an FFT length from sample rate, data length, and target window."""
    fs = float(fs)
    t_win_s = float(t_win_s)
    n_samples = int(n_samples)
    floor = int(floor)
    ceil = int(ceil)
    if fs <= 0.0 or not math.isfinite(fs):
        raise ValueError("fs must be positive")
    if t_win_s <= 0.0 or not math.isfinite(t_win_s):
        raise ValueError("t_win_s must be positive")
    if n_samples <= 0:
        raise ValueError("n_samples must be positive")
    if floor <= 0 or ceil <= 0 or floor > ceil:
        raise ValueError("floor and ceil must be positive with floor <= ceil")

    overlap = float(overlap)
    if not math.isfinite(overlap) or not (0.0 <= overlap < 1.0):
        raise ValueError("overlap must be finite and in [0, 1)")
    nfft = ceil_pow2(fs * t_win_s)

    def _frames(candidate):
        hop = max(int(candidate * (1.0 - overlap)), 1)
        return max(0, (n_samples - candidate) // hop + 1)

    while nfft > 1 and _frames(nfft) < int(min_frames):
        nfft //= 2

    max_window = float(max_window_frac) * float(n_samples)
    while nfft > 1 and nfft > max_window:
        nfft //= 2

    return int(min(max(nfft, floor), ceil))


def resolve_order_nfft(
    samples_per_rev,
    order_res,
    n_angle_samples,
    *,
    overlap=0.75,
    floor=256,
    ceil=16384,
    min_frames=8,
    max_window_frac=0.5,
):
    """Resolve COT FFT length from angle-domain samples and order resolution."""
    samples_per_rev = float(samples_per_rev)
    order_res = float(order_res)
    if samples_per_rev <= 0.0 or not math.isfinite(samples_per_rev):
        raise ValueError("samples_per_rev must be positive")
    if order_res <= 0.0 or not math.isfinite(order_res):
        raise ValueError("order_res must be positive")
    return resolve_nfft(
        samples_per_rev,
        n_angle_samples,
        1.0 / order_res,
        overlap,
        floor=floor,
        ceil=ceil,
        min_frames=min_frames,
        max_window_frac=max_window_frac,
    )


def revolutions_from_rpm(rpm, t):
    """Total revolutions over ``t`` = ∫|rpm|/60 dt (trapezoid).

    Returns ``0.0`` for degenerate input (fewer than two usable samples,
    non-finite samples, or a non-increasing time axis).  Single source of
    truth for the angle-domain record length: the GUI order path
    (``OrderMixin``) and the batch auto-NFFT resolver
    (``batch_compute.resolve_effective_nfft``) both route through it, so the
    two sides cannot drift into different NFFTs for the same data.

    Non-finite ``rpm``/``t`` samples are dropped pairwise before integration
    and ``dt <= 0`` steps are skipped, mirroring the historical GUI behaviour
    this function was extracted from.
    """
    rpm_arr = np.asarray(rpm, dtype=float).reshape(-1)
    t_arr = np.asarray(t, dtype=float).reshape(-1)
    n = min(rpm_arr.size, t_arr.size)
    if n < 2:
        return 0.0
    rpm_arr = rpm_arr[:n]
    t_arr = t_arr[:n]
    finite = np.isfinite(rpm_arr) & np.isfinite(t_arr)
    rpm_arr = rpm_arr[finite]
    t_arr = t_arr[finite]
    if rpm_arr.size < 2:
        return 0.0
    dt = np.diff(t_arr)
    valid_dt = np.isfinite(dt) & (dt > 0.0)
    if not np.any(valid_dt):
        return 0.0
    abs_rpm = np.abs(rpm_arr)
    revs = np.sum(
        0.5
        * (abs_rpm[:-1][valid_dt] + abs_rpm[1:][valid_dt])
        / 60.0
        * dt[valid_dt]
    )
    if not np.isfinite(revs) or revs <= 0.0:
        return 0.0
    return float(revs)


def order_angle_sample_count(samples_per_rev, rpm, t):
    """Angle-domain sample count COT resampling yields for ``rpm`` over ``t``.

    ``1`` for degenerate speed (see :func:`revolutions_from_rpm`) so callers
    can hand the value straight to :func:`resolve_order_nfft`, which then
    resolves down to its floor instead of raising.
    """
    revs = revolutions_from_rpm(rpm, t)
    if revs <= 0.0:
        return 1
    return max(1, int(round(float(samples_per_rev) * revs)))


def _nice_ceil_125(value):
    if value <= 0.0 or not math.isfinite(value):
        return 0.0
    exponent = math.floor(math.log10(value))
    scale = 10.0 ** exponent
    mantissa = value / scale
    if mantissa <= 1.0:
        nice = 1.0
    elif mantissa <= 2.0:
        nice = 2.0
    elif mantissa <= 5.0:
        nice = 5.0
    else:
        nice = 10.0
    return nice * scale


def energy_band_fmax(freq, amp, *, p=0.98, headroom=4.0, floor_hz=2.0):
    """Return a display fmax that covers most non-DC energy with headroom."""
    p = float(p)
    headroom = float(headroom)
    floor_hz = float(floor_hz)
    if not math.isfinite(p) or not (0.0 < p <= 1.0):
        raise ValueError("p must be finite and in (0, 1]")
    if not math.isfinite(headroom) or headroom <= 0.0:
        raise ValueError("headroom must be finite and positive")
    if not math.isfinite(floor_hz) or floor_hz < 0.0:
        raise ValueError("floor_hz must be finite and non-negative")

    freq_arr = np.asarray(freq, dtype=float).reshape(-1)
    amp_arr = np.asarray(amp, dtype=float).reshape(-1)
    if freq_arr.size == 0 or amp_arr.size == 0:
        return floor_hz

    n = min(freq_arr.size, amp_arr.size)
    freq_arr = freq_arr[:n]
    amp_arr = amp_arr[:n]

    finite_nonnegative = freq_arr[np.isfinite(freq_arr) & (freq_arr >= 0.0)]
    nyquist = float(np.max(finite_nonnegative)) if finite_nonnegative.size else floor_hz

    fallback = float(min(nyquist, floor_hz))
    mask = np.isfinite(freq_arr) & (freq_arr > 0.0) & np.isfinite(amp_arr)
    if not np.any(mask):
        return fallback

    pos_freq = freq_arr[mask]
    energy = np.square(amp_arr[mask])
    order = np.argsort(pos_freq)
    pos_freq = pos_freq[order]
    energy = energy[order]

    total = float(np.sum(energy))
    if total <= 0.0 or not math.isfinite(total):
        return fallback

    threshold = p * total
    cumulative = np.cumsum(energy)
    idx = int(np.searchsorted(cumulative, threshold, side="left"))
    idx = min(idx, pos_freq.size - 1)
    raw = max(float(pos_freq[idx]) * headroom, floor_hz)
    return float(min(nyquist, _nice_ceil_125(raw)))


def assess_speed_for_order(rpm):
    """Return whether an RPM trace is suitable for order analysis."""
    rpm_arr = np.asarray(rpm, dtype=float).reshape(-1)
    rpm_arr = rpm_arr[np.isfinite(rpm_arr)]
    message = (
        "\u8f6c\u901f\u63a5\u8fd1\u96f6\u6216\u5b58\u5728\u591a\u6b21\u53cd\u5411"
        "\uff0c\u9636\u6b21\u5206\u6790\u7ed3\u679c\u53ef\u80fd\u4e0d\u9002\u7528"
    )
    if rpm_arr.size < 2:
        return False, message

    abs_rpm = np.abs(rpm_arr)
    peak = float(np.max(abs_rpm))
    threshold = max(50.0, 0.05 * peak)
    near_zero = float(np.mean(abs_rpm < threshold))

    signs = np.sign(rpm_arr)
    signs = signs[signs != 0.0]
    flips = int(np.count_nonzero(signs[1:] != signs[:-1])) if signs.size > 1 else 0

    if flips > 3 or near_zero > 0.2:
        return False, message
    return True, ""
