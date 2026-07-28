"""GUI-free batch signal preprocessing with explicit effective facts.

The stage order is part of the public batch recipe contract::

    time range -> finite cleanup -> scale/offset -> remove mean
    -> anti-aliased sampling -> user filter

RPM values, when supplied, follow only the alignment stages (range, finite
cleanup, and sampling).  Target-signal gain, de-meaning, and the user filter
must never be applied to RPM.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np

from .signal.filters import FilterSpec, apply as apply_filter, nyquist_guard


_SAMPLE_MODES = frozenset({"original", "target_fs", "decimate"})
_ANTI_ALIAS_ORDER = 8
_ANTI_ALIAS_NYQUIST_FRACTION = 0.9


@dataclass(frozen=True)
class BatchPreprocessResult:
    """One aligned, fully preprocessed batch target.

    ``pre_filter_signal`` is the signal immediately before the final user
    filter.  TimeDomain export uses it to retain the existing
    original/filtered two-series presentation without applying the filter to
    RPM.  ``rpm`` is already aligned to ``time`` whenever sampling changed the
    target axis.
    """

    signal: np.ndarray
    time: np.ndarray
    effective_fs: float
    rpm: np.ndarray | None
    pre_filter_signal: np.ndarray
    requested: dict[str, Any]
    effective: dict[str, Any]
    warnings: tuple[str, ...]


def _as_vector(name: str, values) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError(f"{name} must be a 1-D array")
    return array


def _finite_number(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _positive_number(value: Any) -> bool:
    return _finite_number(value) and float(value) > 0.0


def _time_range_mask(time: np.ndarray, time_range) -> np.ndarray:
    if time_range is None:
        return np.ones(len(time), dtype=bool)
    valid_shape = (
        isinstance(time_range, (tuple, list, np.ndarray))
        and not isinstance(time_range, (str, bytes))
        and len(time_range) == 2
    )
    if not valid_shape:
        raise ValueError("time_range requires [start, end]")
    lo, hi = time_range
    if not (_finite_number(lo) and _finite_number(hi) and float(lo) < float(hi)):
        raise ValueError("time_range requires finite start < end")
    return (time >= float(lo)) & (time <= float(hi))


def _sampling_request(time_preprocess: Mapping[str, Any], fs: float):
    mode = str(time_preprocess.get("sample_mode", "original") or "original")
    mode = mode.strip().lower()
    if mode not in _SAMPLE_MODES:
        raise ValueError(
            "sample_mode must be one of original, target_fs, or decimate"
        )

    if mode == "original":
        return mode, fs, 1

    if mode == "target_fs":
        target_fs = time_preprocess.get("target_fs")
        if not _positive_number(target_fs):
            raise ValueError("target_fs must be finite and > 0")
        target_fs = float(target_fs)
        if target_fs > fs * (1.0 + 1e-12):
            raise ValueError(
                "upsampling is disabled; target_fs must not exceed source fs"
            )
        return mode, target_fs, 1

    factor = time_preprocess.get("decimation_factor", 1)
    if (
        isinstance(factor, (bool, np.bool_))
        or not isinstance(factor, (int, np.integer))
        or int(factor) < 1
    ):
        raise ValueError("decimation_factor must be a positive integer")
    factor = int(factor)
    return mode, fs / factor, factor


def _uniform_grid(start: float, stop: float, fs: float) -> np.ndarray:
    span = float(stop) - float(start)
    count = int(np.floor(span * float(fs) + 1e-9)) + 1
    if count < 2:
        raise ValueError("sampling leaves fewer than 2 output samples")
    return float(start) + np.arange(count, dtype=float) / float(fs)


def _regularize_for_antialias(
    time: np.ndarray,
    signal: np.ndarray,
    rpm: np.ndarray | None,
    fs: float,
):
    """Put aligned values on the declared source-Fs grid before filtering.

    Finite cleanup can remove individual rows and measurement timestamps can
    contain small jitter.  The FFT-domain anti-alias filter requires a uniform
    grid, so interpolate those gaps on the declared source time base first.
    This is not user-visible upsampling: the final grid is still no faster than
    the source Fs and is immediately reduced to the requested output rate.
    """

    expected_dt = 1.0 / float(fs)
    dt = np.diff(time)
    tolerance = max(1e-12, abs(expected_dt) * 1e-6)
    if len(dt) and np.all(np.abs(dt - expected_dt) <= tolerance):
        return time, signal, rpm, False

    regular_time = _uniform_grid(time[0], time[-1], fs)
    regular_signal = np.interp(regular_time, time, signal)
    regular_rpm = (
        None if rpm is None else np.interp(regular_time, time, rpm)
    )
    return regular_time, regular_signal, regular_rpm, True


def _anti_aliased_downsample(
    signal: np.ndarray,
    time: np.ndarray,
    fs: float,
    target_fs: float,
    rpm: np.ndarray | None,
):
    source_time, source_signal, source_rpm, regularized = (
        _regularize_for_antialias(time, signal, rpm, fs)
    )
    new_time = _uniform_grid(time[0], time[-1], target_fs)
    cutoff = (
        0.5 * float(target_fs) * _ANTI_ALIAS_NYQUIST_FRACTION
    )
    anti_alias_spec, message = nyquist_guard(
        FilterSpec("low", order=_ANTI_ALIAS_ORDER, cutoff=cutoff),
        fs,
    )
    filtered_signal = apply_filter(source_signal, anti_alias_spec, fs)
    sampled_signal = np.interp(new_time, source_time, filtered_signal)

    sampled_rpm = None
    if source_rpm is not None:
        # This filter is intrinsic to RPM's own sampling conversion.  It is
        # deliberately separate from the target signal's final user filter.
        filtered_rpm = apply_filter(source_rpm, anti_alias_spec, fs)
        sampled_rpm = np.interp(new_time, source_time, filtered_rpm)

    facts = {
        "enabled": True,
        "method": "fft_butterworth",
        "spec": anti_alias_spec.to_dict(),
        "regularized_input": bool(regularized),
    }
    warnings = [message] if message else []
    return sampled_signal, new_time, sampled_rpm, facts, warnings


def preprocess_batch_signal(
    signal,
    time,
    fs: float,
    params: Mapping[str, Any] | None,
    *,
    rpm=None,
) -> BatchPreprocessResult:
    """Apply the canonical batch preprocessing pipeline.

    Upsampling is intentionally rejected.  ``target_fs`` and ``decimate``
    both use the repository's zero-phase FFT-domain low-pass filter before
    interpolation onto a new uniform grid; neither path is a simple slice.
    """

    if not _positive_number(fs):
        raise ValueError("fs must be finite and > 0")
    fs = float(fs)
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        raise TypeError("params must be a mapping")

    signal_arr = _as_vector("signal", signal)
    if time is None:
        time_arr = np.arange(len(signal_arr), dtype=float) / fs
    else:
        time_arr = _as_vector("time", time)
    if len(signal_arr) != len(time_arr):
        raise ValueError(
            f"signal and time length mismatch: {len(signal_arr)} vs {len(time_arr)}"
        )

    rpm_arr = None
    if rpm is not None:
        rpm_arr = _as_vector("rpm", rpm)
        if len(rpm_arr) != len(signal_arr):
            raise ValueError(
                "signal, time, and rpm must have the same length before "
                "preprocessing"
            )

    time_preprocess_raw = params.get("time_preprocess") or {}
    if not isinstance(time_preprocess_raw, Mapping):
        raise TypeError("time_preprocess must be a mapping")
    time_preprocess = dict(time_preprocess_raw)
    filter_raw = params.get("filter") or {}
    if not isinstance(filter_raw, Mapping):
        raise TypeError("filter must be a mapping")
    requested_filter = deepcopy(dict(filter_raw))

    requested = {
        "time_range": deepcopy(params.get("time_range")),
        "time_preprocess": deepcopy(time_preprocess),
        "filter": requested_filter,
    }
    warnings: list[str] = []
    input_samples = len(signal_arr)

    # 1. Time range.
    range_mask = _time_range_mask(time_arr, params.get("time_range"))
    signal_arr = signal_arr[range_mask]
    time_arr = time_arr[range_mask]
    if rpm_arr is not None:
        rpm_arr = rpm_arr[range_mask]
    after_time_range_samples = len(signal_arr)

    # 2. Finite cleanup.  Include RPM in the same mask so COT never receives
    # arrays that refer to different physical rows.
    finite_mask = np.isfinite(time_arr) & np.isfinite(signal_arr)
    if rpm_arr is not None:
        finite_mask &= np.isfinite(rpm_arr)
    finite_samples_dropped = int(len(signal_arr) - np.count_nonzero(finite_mask))
    signal_arr = signal_arr[finite_mask]
    time_arr = time_arr[finite_mask]
    if rpm_arr is not None:
        rpm_arr = rpm_arr[finite_mask]
    if len(signal_arr) < 2:
        raise ValueError("fewer than 2 finite aligned samples remain")
    if finite_samples_dropped:
        warnings.append(
            f"removed {finite_samples_dropped} non-finite aligned sample(s)"
        )

    # 3. Scale/offset.
    scale = time_preprocess.get("scale", 1.0)
    offset = time_preprocess.get("offset", 0.0)
    if not _finite_number(scale):
        raise ValueError("time_preprocess.scale must be finite")
    if not _finite_number(offset):
        raise ValueError("time_preprocess.offset must be finite")
    scale = float(scale)
    offset = float(offset)
    signal_arr = signal_arr * scale + offset

    # 4. Remove mean, after gain and offset by contract.
    remove_mean = bool(time_preprocess.get("remove_mean", False))
    if remove_mean:
        signal_arr = signal_arr - float(np.mean(signal_arr))

    # 5. Sampling, including an independent RPM anti-alias path.
    mode, target_fs, decimation_factor = _sampling_request(time_preprocess, fs)
    if target_fs < fs * (1.0 - 1e-12):
        if np.any(np.diff(time_arr) <= 0.0):
            raise ValueError(
                "sampling requires a strictly increasing aligned time axis"
            )
        signal_arr, time_arr, rpm_arr, anti_alias, sampling_warnings = (
            _anti_aliased_downsample(
                signal_arr, time_arr, fs, target_fs, rpm_arr,
            )
        )
        warnings.extend(sampling_warnings)
    else:
        target_fs = fs
        anti_alias = {
            "enabled": False,
            "method": None,
            "spec": None,
            "regularized_input": False,
        }

    pre_filter_signal = np.asarray(signal_arr, dtype=float).copy()

    # 6. Final user filter.  It is guarded against the *effective* Nyquist.
    filter_state = deepcopy(dict(filter_raw))
    if bool(filter_state.get("enabled", False)):
        requested_spec = FilterSpec.from_dict(filter_state.get("spec") or {})
        effective_spec, message = nyquist_guard(requested_spec, target_fs)
        filter_state["spec"] = effective_spec.to_dict()
        signal_arr = apply_filter(signal_arr, effective_spec, target_fs)
        if message:
            warnings.append(message)
    else:
        filter_state["enabled"] = False

    sampling_facts = {
        "mode": mode,
        "source_fs": fs,
        "requested_target_fs": (
            float(time_preprocess.get("target_fs"))
            if mode == "target_fs" and _positive_number(
                time_preprocess.get("target_fs")
            )
            else None
        ),
        "decimation_factor": decimation_factor,
        "effective_fs": float(target_fs),
        "anti_alias": anti_alias,
    }
    effective = {
        "input_samples": input_samples,
        "after_time_range_samples": after_time_range_samples,
        "finite_samples_dropped": finite_samples_dropped,
        "output_samples": len(signal_arr),
        "scale": scale,
        "offset": offset,
        "remove_mean": remove_mean,
        "sampling": sampling_facts,
        "filter": filter_state,
        "effective_fs": float(target_fs),
    }

    return BatchPreprocessResult(
        signal=np.asarray(signal_arr, dtype=float),
        time=np.asarray(time_arr, dtype=float),
        effective_fs=float(target_fs),
        rpm=(None if rpm_arr is None else np.asarray(rpm_arr, dtype=float)),
        pre_filter_signal=pre_filter_signal,
        requested=requested,
        effective=effective,
        warnings=tuple(warnings),
    )


__all__ = ["BatchPreprocessResult", "preprocess_batch_signal"]
