"""Adaptive defaults for signal-analysis parameters."""
from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral

import numpy as np

from .analysis_defaults import (
    AUTO_4096_MAX_WINDOW_S,
    AUTO_FFT_SEGMENTED_MAX,
    AUTO_FFT_TIME_MAX,
    AUTO_FFT_TIME_MIN_FRAMES,
    AUTO_MIN_NFFT,
    AUTO_NFFT_PREFERRED,
    AUTO_NOTICE_FRAMES,
    OVERLAP_FRACTION_MAX,
)


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
    """Resolve an FFT length from sample rate, data length, and target window.

    Legacy compatibility helper. Segmented FFT and FFT-vs-Time Auto now use
    :func:`resolve_auto_nfft`. This function keeps the historical 24-frame /
    15%-window policy and default ``ceil=8192``; do not copy the practical
    4096-preference rules into it. Order analysis still routes through
    :func:`resolve_order_nfft`, which calls this helper.
    """
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


_AUTO_NFFT_PURPOSES = ("fft_segmented", "fft_time")
_AUTO_NFFT_REASON_ORDER = (
    "preferred_4096",
    "duration_target",
    "low_fs_duration_guard",
    "minimum_nfft_floor",
    "short_record_clamp",
    "fft_time_frame_guard",
    "limited_statistics",
    "limited_time_frames",
    "auto_ceiling",
    "insufficient_samples",
    "insufficient_time_frames",
)
_SEGMENTED_MIN_WARNING_FRAMES = 4


@dataclass(frozen=True)
class AutoNfftDecision:
    """Frozen Auto-NFFT decision for segmented FFT or FFT-vs-Time.

    Single-frame Auto and Fixed NFFT stay on the analyzer / facts builders;
    they are not a third purpose of this object.
    """

    purpose: str
    preferred_nfft: int
    duration_target_nfft: int
    requested_nfft: int
    effective_nfft: int | None
    fs: float
    n_samples: int
    overlap: float
    df_hz: float | None
    window_s: float | None
    frames: int
    degraded: bool | None
    status: str
    reasons: tuple[str, ...]


def segmented_analysis_hop(nfft, overlap):
    """Integer hop used by averaged / peak-hold 1D FFT (no tail frame)."""
    length = int(nfft)
    hop = int(length * (1.0 - float(overlap)))
    if hop <= 0:
        hop = length // 2
    if hop <= 0:
        hop = 1
    return hop


def spectrogram_analysis_hop(nfft, overlap):
    """Integer hop used by ``SpectrogramAnalyzer`` (raises if hop is not positive)."""
    hop = int(int(nfft) * (1.0 - float(overlap)))
    if hop <= 0:
        raise ValueError("overlap leaves no positive hop size")
    return hop


def non_tail_frame_count(n_samples, nfft, overlap):
    """Complete non-tail frames for averaged / peak-hold FFT. O(1)."""
    n = int(n_samples)
    length = int(nfft)
    if n < length or length <= 0:
        return 0
    hop = segmented_analysis_hop(length, overlap)
    return (n - length) // hop + 1


def spectrogram_frame_count_from_hop(n_samples, nfft, hop):
    """O(1) spectrogram frame count for a concrete integer hop, including tail."""
    n = int(n_samples)
    length = int(nfft)
    step = int(hop)
    if n < length or length <= 0 or step <= 0:
        return 0
    span = n - length
    n_regular = span // step + 1
    last_regular = (n_regular - 1) * step
    if last_regular != span:
        return n_regular + 1
    return n_regular


def spectrogram_frame_starts_from_hop(n_samples, nfft, hop):
    """Frame starts for a concrete hop, appending a non-duplicate tail start."""
    n = int(n_samples)
    length = int(nfft)
    step = int(hop)
    if n < length or length <= 0 or step <= 0:
        return np.array([], dtype=int)
    starts = np.arange(0, n - length + 1, step, dtype=int)
    tail_start = n - length
    if starts.size and int(starts[-1]) != tail_start:
        starts = np.append(starts, tail_start)
    return starts


def canonical_spectrogram_frame_count(n_samples, nfft, overlap):
    """Canonical spectrogram frame count, including a tail frame. O(1)."""
    hop = spectrogram_analysis_hop(nfft, overlap)
    return spectrogram_frame_count_from_hop(n_samples, nfft, hop)


def canonical_spectrogram_frame_starts(n_samples, nfft, overlap):
    """Frame starts matching ``SpectrogramAnalyzer._frame_starts`` hop rules."""
    hop = spectrogram_analysis_hop(nfft, overlap)
    return spectrogram_frame_starts_from_hop(n_samples, nfft, hop)


def _largest_pow2_leq(n):
    n = int(n)
    if n < 1:
        return 0
    return 1 << (n.bit_length() - 1)


def _ordered_reasons(codes):
    wanted = set(codes)
    return tuple(code for code in _AUTO_NFFT_REASON_ORDER if code in wanted)


def _validate_auto_nfft_inputs(fs, n_samples, t_win_s, overlap, purpose):
    if purpose not in _AUTO_NFFT_PURPOSES:
        raise ValueError(
            "purpose must be 'fft_segmented' or 'fft_time'"
        )
    try:
        fs_val = float(fs)
    except (TypeError, ValueError) as exc:
        raise ValueError("fs must be finite and greater than 0") from exc
    if not math.isfinite(fs_val) or fs_val <= 0.0:
        raise ValueError("fs must be finite and greater than 0")
    if isinstance(n_samples, bool) or not isinstance(n_samples, Integral):
        raise ValueError("n_samples must be a non-bool integer greater than 0")
    n_val = int(n_samples)
    if n_val <= 0:
        raise ValueError("n_samples must be a non-bool integer greater than 0")
    try:
        t_win = float(t_win_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("t_win_s must be finite and greater than 0") from exc
    if not math.isfinite(t_win) or t_win <= 0.0:
        raise ValueError("t_win_s must be finite and greater than 0")
    product = fs_val * t_win
    if not math.isfinite(product) or product <= 0.0:
        raise ValueError("fs * t_win_s must be finite and greater than 0")
    try:
        overlap_val = float(overlap)
    except (TypeError, ValueError) as exc:
        raise ValueError("overlap must be finite and in [0, 0.95]") from exc
    if not math.isfinite(overlap_val) or not (
        0.0 <= overlap_val <= OVERLAP_FRACTION_MAX
    ):
        raise ValueError("overlap must be finite and in [0, 0.95]")
    return fs_val, n_val, t_win, overlap_val, product


def _blocked_auto_nfft(
    *,
    purpose,
    preferred,
    duration_target,
    requested,
    fs,
    n_samples,
    overlap,
    reasons,
):
    return AutoNfftDecision(
        purpose=purpose,
        preferred_nfft=int(preferred),
        duration_target_nfft=int(duration_target),
        requested_nfft=int(requested),
        effective_nfft=None,
        fs=float(fs),
        n_samples=int(n_samples),
        overlap=float(overlap),
        df_hz=None,
        window_s=None,
        frames=0,
        degraded=None,
        status="blocked",
        reasons=_ordered_reasons(reasons),
    )


def _success_auto_nfft(
    *,
    purpose,
    preferred,
    duration_target,
    requested,
    effective,
    fs,
    n_samples,
    overlap,
    frames,
    reasons,
    status,
):
    nfft = int(effective)
    return AutoNfftDecision(
        purpose=purpose,
        preferred_nfft=int(preferred),
        duration_target_nfft=int(duration_target),
        requested_nfft=int(requested),
        effective_nfft=nfft,
        fs=float(fs),
        n_samples=int(n_samples),
        overlap=float(overlap),
        df_hz=float(fs) / float(nfft),
        window_s=float(nfft) / float(fs),
        frames=int(frames),
        degraded=bool(nfft < int(requested)),
        status=status,
        reasons=_ordered_reasons(reasons),
    )


def requested_auto_nfft(fs, t_win_s, *, purpose):
    """Requested Auto-NFFT when the sample count is not yet known.

    Used by Inspector previews that must not invent an actual NFFT. Does not
    apply the real-sample clamp or FFT-vs-Time frame guard.
    """
    fs_val, _n_val, _t_win, _overlap, product = _validate_auto_nfft_inputs(
        fs, 64, t_win_s, 0.0, purpose,
    )
    duration_target = ceil_pow2(product)
    preferred = int(AUTO_NFFT_PREFERRED)
    baseline_enabled = (float(preferred) / fs_val) <= float(AUTO_4096_MAX_WINDOW_S)
    baseline = preferred if baseline_enabled else 0
    ceiling = (
        AUTO_FFT_SEGMENTED_MAX if purpose == "fft_segmented" else AUTO_FFT_TIME_MAX
    )
    raw_requested = max(duration_target, baseline, AUTO_MIN_NFFT)
    return min(raw_requested, int(ceiling))


def resolve_auto_nfft(fs, n_samples, t_win_s, overlap, *, purpose):
    """Resolve a practical Auto-NFFT decision for segmented FFT or FFT-vs-Time.

    Fail-closed on illegal inputs. Does not zero-pad to reach 4096. Order
    and FRF must not call this helper.
    """
    fs_val, n_val, t_win, overlap_val, product = _validate_auto_nfft_inputs(
        fs, n_samples, t_win_s, overlap, purpose,
    )
    duration_target = ceil_pow2(product)
    preferred = int(AUTO_NFFT_PREFERRED)
    baseline_enabled = (float(preferred) / fs_val) <= float(AUTO_4096_MAX_WINDOW_S)
    baseline = preferred if baseline_enabled else 0
    ceiling = (
        AUTO_FFT_SEGMENTED_MAX if purpose == "fft_segmented" else AUTO_FFT_TIME_MAX
    )
    reasons = []
    if baseline_enabled:
        if duration_target <= preferred:
            reasons.append("preferred_4096")
        else:
            reasons.append("duration_target")
    else:
        reasons.append("low_fs_duration_guard")
    if max(duration_target, baseline) < AUTO_MIN_NFFT:
        reasons.append("minimum_nfft_floor")
    raw_requested = max(duration_target, baseline, AUTO_MIN_NFFT)
    requested = min(raw_requested, int(ceiling))
    if raw_requested > int(ceiling):
        reasons.append("auto_ceiling")
    available = _largest_pow2_leq(n_val)
    candidate = min(requested, available)
    if candidate < requested:
        reasons.append("short_record_clamp")
    if candidate < AUTO_MIN_NFFT:
        reasons.append("insufficient_samples")
        return _blocked_auto_nfft(
            purpose=purpose,
            preferred=preferred,
            duration_target=duration_target,
            requested=requested,
            fs=fs_val,
            n_samples=n_val,
            overlap=overlap_val,
            reasons=reasons,
        )

    if purpose == "fft_segmented":
        frames = non_tail_frame_count(n_val, candidate, overlap_val)
        if frames <= 0:
            reasons.append("insufficient_samples")
            return _blocked_auto_nfft(
                purpose=purpose,
                preferred=preferred,
                duration_target=duration_target,
                requested=requested,
                fs=fs_val,
                n_samples=n_val,
                overlap=overlap_val,
                reasons=reasons,
            )
        if frames >= AUTO_NOTICE_FRAMES:
            status = "normal"
        elif frames >= _SEGMENTED_MIN_WARNING_FRAMES:
            status = "notice"
            reasons.append("limited_statistics")
        else:
            status = "warning"
            reasons.append("limited_statistics")
        return _success_auto_nfft(
            purpose=purpose,
            preferred=preferred,
            duration_target=duration_target,
            requested=requested,
            effective=candidate,
            fs=fs_val,
            n_samples=n_val,
            overlap=overlap_val,
            frames=frames,
            reasons=reasons,
            status=status,
        )

    reduced = False
    effective = None
    frames = 0
    while candidate >= AUTO_MIN_NFFT:
        frames = canonical_spectrogram_frame_count(n_val, candidate, overlap_val)
        if frames >= AUTO_FFT_TIME_MIN_FRAMES:
            effective = candidate
            break
        reduced = True
        candidate //= 2
    if effective is None:
        reasons.append("fft_time_frame_guard")
        reasons.append("insufficient_time_frames")
        return _blocked_auto_nfft(
            purpose=purpose,
            preferred=preferred,
            duration_target=duration_target,
            requested=requested,
            fs=fs_val,
            n_samples=n_val,
            overlap=overlap_val,
            reasons=reasons,
        )
    if reduced:
        reasons.append("fft_time_frame_guard")
    if frames >= AUTO_NOTICE_FRAMES:
        status = "normal"
    else:
        status = "notice"
        reasons.append("limited_time_frames")
    return _success_auto_nfft(
        purpose=purpose,
        preferred=preferred,
        duration_target=duration_target,
        requested=requested,
        effective=effective,
        fs=fs_val,
        n_samples=n_val,
        overlap=overlap_val,
        frames=frames,
        reasons=reasons,
        status=status,
    )


class AutoNfftBlockedError(ValueError):
    """User/data failure: Auto-NFFT cannot produce a computable segment."""

    def __init__(self, decision: AutoNfftDecision):
        self.decision = decision
        codes = ", ".join(decision.reasons) or "blocked"
        super().__init__(
            f"Auto-NFFT blocked ({decision.purpose}): {codes}"
        )


def raise_if_auto_nfft_blocked(decision: AutoNfftDecision) -> AutoNfftDecision:
    """Raise :class:`AutoNfftBlockedError` for a blocked decision; else return it."""
    if decision.status == "blocked":
        raise AutoNfftBlockedError(decision)
    return decision


def nfft_facts_signature(
    *,
    nfft_mode,
    policy_version=None,
    t_win_s=None,
    duration_target=None,
    requested_nfft=None,
    effective_nfft=None,
    n_samples=None,
    status=None,
    degraded=None,
    reasons=None,
):
    """Hashable cache identity for Auto/Fixed NFFT intent plus effective values.

    Localized warning text is not part of the signature. Single-frame and
    Fixed modes keep unrelated Auto policy fields as ``None``.
    """
    mode = None if nfft_mode is None else str(nfft_mode)
    auto = mode == "auto"
    version = None
    target = None
    window = None
    if auto:
        if policy_version is not None:
            version = int(policy_version)
        if duration_target is not None:
            target = int(duration_target)
        if t_win_s is not None:
            window_val = float(t_win_s)
            if not math.isfinite(window_val):
                raise ValueError("t_win_s must be finite")
            window = format(window_val, ".12g")
    reason_codes = tuple(str(code) for code in (reasons or ())) if auto else ()
    return (
        mode,
        version,
        window,
        target,
        None if requested_nfft is None else int(requested_nfft),
        None if effective_nfft is None else int(effective_nfft),
        None if n_samples is None else int(n_samples),
        None if status is None else str(status),
        None if degraded is None else bool(degraded),
        reason_codes,
    )


def nfft_facts_signature_from_decision(
    decision: AutoNfftDecision,
    *,
    t_win_s,
    nfft_mode="auto",
    policy_version,
):
    """Build :func:`nfft_facts_signature` from a segmented Auto decision.

    ``t_win_s`` is the caller's stored intent, not the effective window.
    """
    return nfft_facts_signature(
        nfft_mode=nfft_mode,
        policy_version=policy_version,
        t_win_s=t_win_s,
        duration_target=decision.duration_target_nfft,
        requested_nfft=decision.requested_nfft,
        effective_nfft=decision.effective_nfft,
        n_samples=decision.n_samples,
        status=decision.status,
        degraded=decision.degraded,
        reasons=decision.reasons,
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
