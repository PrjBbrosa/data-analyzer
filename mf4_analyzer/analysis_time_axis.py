"""UI-neutral, non-mutating time preparation for analysis inputs.

This retains the existing index-based reconstruction policy, not interpolation.
Callers crop using original timestamps first and keep signal values unchanged.
Empty/single-point vectors pass through; malformed/non-finite time is rejected.
The returned float64 grid preserves length and the selection's physical origin.
With materialize=False, the original axis accompanies the planned rate/facts so
cache lookup and FFT-only callers need not allocate a grid they never consume.
"""
from __future__ import annotations

import numpy as np

from .io.file_data import build_time_axis_provenance, time_axis_spacing_stats
from .signal.spectrogram import DEFAULT_TIME_JITTER_TOLERANCE


def prepare_analysis_time_axis(time, fs, *, target_fs=None, time_source='column', materialize=True):
    axis = np.asarray(time, dtype=float)
    if axis.ndim != 1 or not np.all(np.isfinite(axis)):
        raise ValueError('分析时间轴必须是一维有限数值')
    fs = float(fs)
    if not np.isfinite(fs) or fs <= 0:
        raise ValueError('分析采样率必须为正有限数值')
    if target_fs is not None:
        target_fs = float(target_fs)
        if not np.isfinite(target_fs) or target_fs <= 0:
            raise ValueError('分析采样率必须为正有限数值')
    stats = time_axis_spacing_stats(axis, fs)
    nonuniform = stats is not None and (
        stats[1] <= 0 or stats[0] > DEFAULT_TIME_JITTER_TOLERANCE
    )
    if target_fs is None and not nonuniform:
        return axis, fs, None
    if target_fs is None:
        dt = np.diff(axis)
        positive = dt[dt > 0]
        target_fs = 1.0 / float(np.median(positive)) if positive.size else fs
        reason = 'auto_nonuniform'
    else:
        reason = 'manual'
    provenance = build_time_axis_provenance(
        axis, fs, target_fs, reason=reason, original_time_source=time_source,
    ).to_dict()
    provenance['scope'] = 'analysis'
    provenance['method'] = 'specified_fs' if reason == 'manual' else 'median_dt'
    origin = float(axis[0]) if axis.size else 0.0
    rebuilt = origin + np.arange(axis.size, dtype=float) / target_fs if materialize else axis
    return rebuilt, target_fs, provenance
