"""Batch DSP compute helpers, module-level (no runner state).

These were ``BatchRunner`` static/class methods (all but ``_rpm_values``,
which stays on the runner -- it is the one method in this family that reads
cross-source lookup state). Moved out verbatim so the DSP surface can be
depended on -- and tested -- without pulling in the runner's orchestration
code.

Byte output (``_write_dataframe`` / ``_write_workbook`` / ``_write_image``)
is deliberately NOT here: it belongs to ``batch_output`` (design D3).

``BatchRunner`` keeps a class-level ``staticmethod(...)`` alias for every
name below (see the "compatibility aliases" block in ``batch.py``); new code
should import this module directly instead of going through those aliases.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
import logging

import numpy as np
import pandas as pd

from . import db_reference
from .batch_types import _BatchCancelled
from .signal import resolve_nfft, resolve_order_nfft
from .signal.fft import FFTAnalyzer
from .signal.frf import (
    FrfParams,
    FrfRequestValidationError,
    FrfResult,
    compute_frf,
    magnitude_db,
    magnitude_linear,
    plan_frf_request,
    phase_unwrapped_deg,
    phase_wrapped_deg,
)


logger = logging.getLogger(__name__)


FRF_EXPORT_COLUMNS = (
    "frequency_hz",
    "transfer_real",
    "transfer_imag",
    "magnitude_linear",
    "magnitude_db",
    "phase_deg_wrapped",
    "phase_deg_unwrapped",
    "coherence",
    "pxx",
    "pyy",
    "pxy_real",
    "pxy_imag",
)


class BatchFrfDataError(ValueError):
    """Expected FRF recipe/source/sample failure safe to record as an item."""


@dataclass(frozen=True)
class PreparedBatchFrf:
    """Fully loaded, data-preflighted FRF inputs; no artifact is reserved."""

    input_channel: str
    output_channel: str
    input_values: np.ndarray
    output_values: np.ndarray
    input_time: np.ndarray
    output_time: np.ndarray
    fs: float
    params: FrfParams
    input_unit: str = ""
    output_unit: str = ""


@dataclass(frozen=True)
class BatchFrfComputeResult:
    """Numeric export table plus the raw complex result for later rendering."""

    dataframe: pd.DataFrame
    result: FrfResult
    input_channel: str
    output_channel: str
    input_unit: str = ""
    output_unit: str = ""


def _frf_numeric_vector(values, label: str) -> np.ndarray:
    """Validate only vector shape/dtype before any time-range selection."""

    try:
        array = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise BatchFrfDataError(
            f"{label} must contain real numeric values"
        ) from exc
    if array.ndim != 1:
        raise BatchFrfDataError(f"{label} must be one-dimensional")
    if array.size == 0:
        raise BatchFrfDataError(f"{label} is empty")
    if np.issubdtype(array.dtype, np.bool_) or np.iscomplexobj(array):
        raise BatchFrfDataError(f"{label} must contain real numeric values")
    if not np.issubdtype(array.dtype, np.number):
        raise BatchFrfDataError(f"{label} must contain real numeric values")
    return array.astype(np.float64, copy=False)


def _frf_require_finite(values: np.ndarray, label: str) -> None:
    if not np.all(np.isfinite(values)):
        raise BatchFrfDataError(f"{label} contains non-finite samples")


def _frf_channel_unit(fd, channel: str) -> str:
    metadata = (getattr(fd, "channel_metadata", None) or {}).get(channel) or {}
    return str(
        metadata.get("unit")
        or (getattr(fd, "channel_units", None) or {}).get(channel, "")
        or ""
    )


def prepare_frf_task(fd, input_channel: str, output_channel: str, params) -> PreparedBatchFrf:
    """Load-neutral-to-compute seam for one directional FRF pair.

    The caller must supply one fully loaded logical ``FileData``.  This step
    deliberately rejects generated or absent time axes and never truncates,
    rebuilds, or estimates an axis/sample rate.
    """

    if fd is None:
        raise BatchFrfDataError("FRF requires a loaded logical source")
    input_channel = str(input_channel or "").strip()
    output_channel = str(output_channel or "").strip()
    if not input_channel or not output_channel:
        raise BatchFrfDataError("FRF input and output channels are required")
    if input_channel == output_channel:
        raise BatchFrfDataError("FRF input and output channels must differ")
    data = getattr(fd, "data", None)
    if data is None or input_channel not in data or output_channel not in data:
        raise BatchFrfDataError(
            "FRF input and output channels must exist in the same logical source"
        )

    input_values = _frf_numeric_vector(
        data[input_channel].to_numpy(copy=False), "input",
    ).copy()
    output_values = _frf_numeric_vector(
        data[output_channel].to_numpy(copy=False), "output",
    ).copy()
    if input_values.size != output_values.size:
        raise BatchFrfDataError("input and output must have the same length")

    time_source = str(getattr(fd, "_time_source", "") or "").strip().lower()
    time_values = getattr(fd, "time_array", None)
    if time_values is None or time_source == "generated":
        raise BatchFrfDataError(
            "FRF 需要真实时间轴，不能使用缺失或自动生成的时间轴"
        )
    time = _frf_numeric_vector(time_values, "time").copy()
    if time.size != input_values.size:
        raise BatchFrfDataError(
            "time and both FRF signals must have the same length（等长）"
        )

    raw_fs = params.get("fs", getattr(fd, "fs", None))
    if isinstance(raw_fs, (bool, np.bool_)):
        raise BatchFrfDataError("FRF fs must be finite and > 0")
    try:
        fs = float(raw_fs)
    except (TypeError, ValueError) as exc:
        raise BatchFrfDataError("FRF fs must be finite and > 0") from exc
    if not np.isfinite(fs) or fs <= 0.0:
        raise BatchFrfDataError("FRF fs must be finite and > 0")

    # Build exactly one mask from the unmodified physical time array, then
    # apply it to t/x/y together. Finiteness, monotonicity and uniformity are
    # selected-range facts: an excluded numeric glitch must not poison the
    # requested interval, while a selected glitch must fail closed.
    time_range = params.get("time_range")
    if time_range is not None:
        if (
            not isinstance(time_range, (tuple, list, np.ndarray))
            or isinstance(time_range, (str, bytes))
            or len(time_range) != 2
        ):
            raise BatchFrfDataError("time_range requires [start, end]")
        try:
            lo, hi = float(time_range[0]), float(time_range[1])
        except (TypeError, ValueError) as exc:
            raise BatchFrfDataError(
                "time_range start/end must be finite"
            ) from exc
        if not (np.isfinite(lo) and np.isfinite(hi) and lo < hi):
            raise BatchFrfDataError(
                "time_range requires finite start < end"
            )
        mask = (time >= lo) & (time <= hi)
        time = time[mask]
        input_values = input_values[mask]
        output_values = output_values[mask]

    _frf_require_finite(time, "time")
    _frf_require_finite(input_values, "input")
    _frf_require_finite(output_values, "output")
    if time.size < 2 or np.any(np.diff(time) <= 0.0):
        raise BatchFrfDataError("FRF time must be strictly increasing")

    from .signal.spectrogram import DEFAULT_TIME_JITTER_TOLERANCE

    nominal_dt = 1.0 / fs
    relative_jitter = float(
        np.max(np.abs(np.diff(time) - nominal_dt)) / nominal_dt
    )
    if relative_jitter > DEFAULT_TIME_JITTER_TOLERANCE:
        raise BatchFrfDataError(
            "FRF time is non-uniform: relative_jitter="
            f"{relative_jitter:.6g} exceeds tolerance="
            f"{DEFAULT_TIME_JITTER_TOLERANCE:.6g}"
        )

    try:
        frf_params = FrfParams(
            estimator=str(params.get("estimator", "h1") or "").strip().lower(),
            t_win_s=params.get("t_win_s", 2.0),
            overlap=params.get("overlap", 0.5),
            nfft_mode=str(params.get("nfft_mode", "auto") or "").strip().lower(),
            nfft=params.get("nfft"),
            window=str(params.get("window", "hanning") or "").strip().lower(),
            periodic_window=params.get("periodic_window", True),
            detrend=str(params.get("detrend", "constant") or "").strip().lower(),
        )
    except ValueError as exc:
        raise BatchFrfDataError(str(exc)) from exc
    try:
        plan_frf_request(
            n_samples=int(input_values.size),
            fs=fs,
            params=frf_params,
        )
    except FrfRequestValidationError as exc:
        raise BatchFrfDataError(str(exc)) from exc

    time.setflags(write=False)
    input_values.setflags(write=False)
    output_values.setflags(write=False)
    return PreparedBatchFrf(
        input_channel=input_channel,
        output_channel=output_channel,
        input_values=input_values,
        output_values=output_values,
        input_time=time,
        output_time=time,
        fs=fs,
        params=frf_params,
        input_unit=_frf_channel_unit(fd, input_channel),
        output_unit=_frf_channel_unit(fd, output_channel),
    )


def compute_prepared_frf(
    prepared: PreparedBatchFrf,
    *,
    cancel_token=None,
    progress=None,
) -> BatchFrfComputeResult:
    """Call the sole NumPy FRF implementation and build the fixed table."""

    try:
        result = compute_frf(
            prepared.input_values,
            prepared.output_values,
            fs=prepared.fs,
            params=prepared.params,
            input_time=prepared.input_time,
            output_time=prepared.output_time,
            cancel_check=(
                None if cancel_token is None else cancel_token.is_set
            ),
            progress=progress,
        )
    except RuntimeError as exc:
        if str(exc) == "FRF computation cancelled":
            raise _BatchCancelled("cancelled during FRF computation") from exc
        raise
    except ValueError as exc:
        if str(exc) == "spectral accumulation overflow; rescale the input signals":
            raise BatchFrfDataError(str(exc)) from exc
        raise
    transfer = result.transfer
    pxy = result.pxy
    frame = pd.DataFrame({
        "frequency_hz": result.frequencies,
        "transfer_real": transfer.real,
        "transfer_imag": transfer.imag,
        "magnitude_linear": magnitude_linear(transfer),
        "magnitude_db": magnitude_db(transfer),
        "phase_deg_wrapped": phase_wrapped_deg(transfer),
        "phase_deg_unwrapped": phase_unwrapped_deg(transfer),
        "coherence": result.coherence,
        "pxx": result.pxx,
        "pyy": result.pyy,
        "pxy_real": pxy.real,
        "pxy_imag": pxy.imag,
    }, columns=FRF_EXPORT_COLUMNS)
    return BatchFrfComputeResult(
        dataframe=frame,
        result=result,
        input_channel=prepared.input_channel,
        output_channel=prepared.output_channel,
        input_unit=prepared.input_unit,
        output_unit=prepared.output_unit,
    )


def channel_reference_facts(fd, ch):
    """Build a :class:`db_reference.ChannelReferenceFacts` for one batch
    task's ``(FileData, signal_name)`` target (plan Task 9 Step 9.3),
    reading ONLY ``FileData`` metadata -- never a sample array (mirrors
    ``MainWindow._channel_reference_facts``; duplicated here rather than
    imported because ``batch.py`` must never import ``mf4_analyzer.ui.*``).
    """
    if fd is None or ch is None:
        return db_reference.ChannelReferenceFacts(quantity='', unit='')
    ch_meta = (getattr(fd, 'channel_metadata', None) or {}).get(ch) or {}
    unit = (
        ch_meta.get('unit')
        or (getattr(fd, 'channel_units', None) or {}).get(ch, '')
        or ''
    )
    # Mirror MainWindow._channel_reference_facts: reverse toolchain unit
    # encoding (U_ prefix, Y for /) at the facts boundary so batch export's
    # dB labels/refs match the interactive path (U_Nm -> Nm, mYs2 -> m/s2).
    unit = db_reference.canonicalize_source_unit(unit)
    quantity = ch_meta.get('quantity') or ''
    metadata_reference = ch_meta.get('db_reference')
    is_audio_source_fn = getattr(fd, 'is_audio_source', None)
    try:
        is_audio = bool(is_audio_source_fn()) if callable(is_audio_source_fn) else False
    except Exception as exc:
        logger.warning(
            "channel_reference_facts: is_audio_source() failed for channel "
            "%s: %s",
            ch, exc, exc_info=True,
        )
        is_audio = False
    return db_reference.ChannelReferenceFacts(
        quantity=str(quantity),
        unit=str(unit),
        metadata_reference=metadata_reference,
        is_audio_source=is_audio,
    )


def batch_output_scale(kind, params):
    """Return ``(render_db, output_scale)`` -- the amp-mode resolution
    shared by ``_run_one`` (records ``colorbar_label`` on
    ``BatchItemResult``) and ``_build_export_scene`` (actually draws the
    image), so the two can never drift on which scale a preset's
    ``amplitude_mode``/``amp_y`` selects."""
    default_amp_mode = 'amplitude_db' if kind == 'fft_time' else 'amplitude'
    amp_mode = str(params.get('amplitude_mode', default_amp_mode)).lower()
    amp_y = str(params.get('amp_y', '')).lower()
    render_db = 'db' in amp_mode or amp_y == 'db'
    return render_db, ('db' if render_db else 'linear')


def image_reference_resolution(params):
    """The effective dB-reference resolution for a batch image render.

    ``_run_one`` (Task 9 Step 9.3) always pre-attaches an already-
    resolved ``db_reference_resolution`` -- built from the task's real
    ``(FileData, signal_name)`` facts and the injected catalog snapshot
    -- onto its OUTPUT param copy before calling ``BatchRunner._write_image``; this
    just returns that unchanged. Direct calls to ``_build_export_scene``/
    ``BatchRunner._write_image`` that bypass ``_run_one`` (existing unit tests call
    these ``@staticmethod``s directly with a bare params dict, no file
    context -- 2026-06-20 static-image-writer-test-api-wider-than-plan)
    resolve against EMPTY facts and the immutable factory catalog
    instead, through the exact same ``db_reference.resolve_db_reference``
    priority chain, so both paths share ONE formatting/validation rule
    and neither ever silently coerces an invalid reference via
    ``max(ref, 1e-12)`` (spec §7 R3 / plan Task 9 Step 9.4)."""
    existing = params.get('db_reference_resolution')
    if isinstance(existing, db_reference.DbReferenceResolution):
        return existing
    migrated = db_reference.migrate_legacy_reference_params(params)
    return db_reference.resolve_db_reference(
        mode=migrated.get('db_reference_mode', 'auto'),
        manual_value=migrated.get('db_reference'),
        facts=db_reference.ChannelReferenceFacts(quantity='', unit=''),
        user_catalog=(),
        system_catalog=db_reference.FACTORY_CATALOG_V1,
        prefer_channel_metadata=True,
    )


def check_cancel(cancel_token, stage):
    if cancel_token is not None and cancel_token.is_set():
        raise _BatchCancelled(f"cancelled during {stage}")


def apply_time_range(sig, time, params, rpm=None):
    time_range = params.get('time_range')
    if not time_range or time is None:
        return sig, time, rpm
    lo, hi = time_range
    mask = (time >= float(lo)) & (time <= float(hi))
    sig = sig[mask]
    time = time[mask]
    if rpm is not None:
        rpm = rpm[mask]
    return sig, time, rpm


def suggest_fs_from_time_axis(time, fallback_fs):
    arr = np.asarray(time, dtype=float)
    if arr.size < 2:
        return float(fallback_fs)
    dt = np.diff(arr)
    positive = dt[dt > 0]
    if positive.size == 0:
        return float(fallback_fs)
    median_dt = float(np.median(positive))
    if not np.isfinite(median_dt) or median_dt <= 0:
        return float(fallback_fs)
    return 1.0 / median_dt


def uniform_time_axis_for_spectrogram(time, fs, length):
    """Return a spectrogram-safe time axis and matching Fs.

    Batch FFT-vs-Time mirrors the single-file UX: jittered MF4
    timestamps are rebuilt to ``arange(n) / suggested_fs`` using the
    median-dt estimate instead of failing every task with the raw
    ``non-uniform time axis`` validator error.
    """
    fs = float(fs)
    if time is None:
        return np.arange(int(length), dtype=float) / fs, fs
    time_arr = np.asarray(time, dtype=float)
    if time_arr.size < 2:
        return time_arr, fs

    from .signal.spectrogram import (
        DEFAULT_TIME_JITTER_TOLERANCE,
        SpectrogramAnalyzer,
    )

    try:
        SpectrogramAnalyzer._validate_time_axis(
            time_arr, fs, DEFAULT_TIME_JITTER_TOLERANCE,
        )
        return time_arr, fs
    except ValueError as exc:
        if 'non-uniform time axis' not in str(exc):
            raise

    suggested = suggest_fs_from_time_axis(time_arr, fs)
    if not (np.isfinite(suggested) and suggested > 0):
        suggested = fs
    return np.arange(len(time_arr), dtype=float) / float(suggested), float(suggested)


def time_axis_or_fallback(time, fs, n_samples):
    if time is not None:
        arr = np.asarray(time, dtype=float)
        if arr.size == int(n_samples):
            return arr
    fs = float(fs)
    if not np.isfinite(fs) or fs <= 0:
        raise ValueError("缺少有效采样率")
    return np.arange(int(n_samples), dtype=float) / fs


def filter_state(params):
    state = params.get("filter") or {}
    return state if isinstance(state, dict) else {}


def filter_enabled(params):
    return bool(filter_state(params).get("enabled", False))


def filter_spec_from_params(params):
    if not filter_enabled(params):
        return None
    from .signal.filters import FilterSpec

    return FilterSpec.from_dict(filter_state(params).get("spec") or {})


def apply_filter_if_enabled(sig, fs, params):
    spec = filter_spec_from_params(params)
    if spec is None:
        return np.asarray(sig, dtype=float), None
    from .signal import filters as _filters

    guarded, _msg = _filters.nyquist_guard(spec, fs)
    return _filters.apply(sig, guarded, fs), guarded


def compute_time_dataframe(sig, time, fs, params):
    x = time_axis_or_fallback(time, fs, len(sig))
    filter_state_ = filter_state(params)
    if not filter_enabled(params):
        return pd.DataFrame({
            "time_s": x,
            "series": ["original"] * len(sig),
            "value": np.asarray(sig, dtype=float),
        })

    show_original = bool(filter_state_.get("show_original", True))
    show_filtered = bool(filter_state_.get("show_filtered", True))
    if not show_original and not show_filtered:
        raise ValueError("时域导出至少需要原始或滤波后一项")

    frames = []
    if show_original:
        frames.append(pd.DataFrame({
            "time_s": x,
            "series": ["original"] * len(sig),
            "value": np.asarray(sig, dtype=float),
        }))
    if show_filtered:
        filtered, _spec = apply_filter_if_enabled(sig, fs, params)
        frames.append(pd.DataFrame({
            "time_s": x,
            "series": ["filtered"] * len(filtered),
            "value": filtered,
        }))
    return pd.concat(frames, ignore_index=True)


def compute_preprocessed_time_dataframe(
    pre_filter_signal, filtered_signal, time, fs, params,
):
    """Build TimeDomain rows from the canonical preprocessing outputs."""

    x = time_axis_or_fallback(time, fs, len(filtered_signal))
    filter_state_ = filter_state(params)
    if not filter_enabled(params):
        return pd.DataFrame({
            "time_s": x,
            "series": ["original"] * len(filtered_signal),
            "value": np.asarray(filtered_signal, dtype=float),
        })

    show_original = bool(filter_state_.get("show_original", True))
    show_filtered = bool(filter_state_.get("show_filtered", True))
    if not show_original and not show_filtered:
        raise ValueError("时域导出至少需要原始或滤波后一项")

    frames = []
    if show_original:
        frames.append(pd.DataFrame({
            "time_s": x,
            "series": ["original"] * len(pre_filter_signal),
            "value": np.asarray(pre_filter_signal, dtype=float),
        }))
    if show_filtered:
        frames.append(pd.DataFrame({
            "time_s": x,
            "series": ["filtered"] * len(filtered_signal),
            "value": np.asarray(filtered_signal, dtype=float),
        }))
    return pd.concat(frames, ignore_index=True)


def compute_fft_dataframe(sig, fs, params):
    sig, _spec = apply_filter_if_enabled(sig, fs, params)
    nfft = resolve_fft_nfft(len(sig), fs, params)
    win = params.get('window', params.get('win', 'hanning'))
    weighting = str(params.get('weighting', 'None'))
    avg_mode = str(params.get('avg_mode', '单帧'))
    avg_overlap = avg_overlap_fraction(params)
    if avg_mode == '线性平均':
        freq, amp, _psd = FFTAnalyzer.compute_averaged_fft(
            sig, fs, win, int(nfft), avg_overlap, weighting=weighting,
        )
    elif avg_mode == '峰值保持':
        freq, amp = FFTAnalyzer.compute_peak_hold_fft(
            sig, fs, win=win, nfft=int(nfft), overlap=avg_overlap,
            weighting=weighting,
        )
    else:
        freq, amp = FFTAnalyzer.compute_fft(
            sig,
            fs,
            win=win,
            nfft=nfft,
            weighting=weighting,
        )
    amp = convert_fft_amplitude_definition(
        amp,
        avg_mode=avg_mode,
        requested=params.get('amplitude_definition', 'native'),
    )
    return pd.DataFrame({'frequency_hz': freq, 'amplitude': amp})


def convert_fft_amplitude_definition(amp, *, avg_mode, requested):
    """Convert an FFT mode's native linear amplitude to peak or RMS."""

    requested = str(requested or 'native').strip().lower()
    native = 'rms' if str(avg_mode) == '线性平均' else 'peak'
    values = np.asarray(amp, dtype=float)
    if requested == 'native' or requested == native:
        return values
    if native == 'rms' and requested == 'peak':
        return values * np.sqrt(2.0)
    if native == 'peak' and requested == 'rms':
        return values / np.sqrt(2.0)
    # Runner preflight owns the user-facing field error. Keep this helper
    # fail-closed for direct test/caller use that bypasses run().
    raise ValueError(
        "amplitude_definition must be native, peak, or rms"
    )


def avg_overlap_fraction(params):
    try:
        value = float(params.get('avg_overlap', 50))
    except (TypeError, ValueError):
        value = 50.0
    if value > 1.0:
        value /= 100.0
    return max(0.0, min(0.95, value))


def resolve_fft_nfft(n_samples, fs, params):
    nfft_raw = params.get('nfft')
    avg_mode = str(params.get('avg_mode', '单帧'))
    if isinstance(nfft_raw, str):
        nfft = None if nfft_raw.strip() in ('', '自动', 'auto') else int(nfft_raw)
    elif nfft_raw is None or nfft_raw <= 0:
        nfft = None
    else:
        nfft = int(nfft_raw)
    if nfft is None and avg_mode in {'线性平均', '峰值保持'}:
        t_win_s = float(params.get('t_win_s', 1.5))
        return int(resolve_nfft(
            float(fs), int(n_samples), t_win_s,
            avg_overlap_fraction(params),
        ))
    return nfft


def resolve_effective_nfft(method, n_samples, fs, params):
    raw = params.get('nfft')
    auto = raw is None or raw == ''
    if isinstance(raw, str):
        auto = raw.strip().lower() in {'auto', '自动'}
    elif isinstance(raw, (int, float, np.integer, np.floating)):
        auto = float(raw) <= 0
    if not auto:
        return int(raw)
    if method == 'fft':
        resolved = resolve_fft_nfft(n_samples, fs, params)
        return int(n_samples if resolved is None else resolved)
    if method == 'order_time':
        return int(resolve_order_nfft(
            float(params.get('samples_per_rev', 256)),
            float(params.get('order_res', 0.1)),
            int(n_samples),
        ))
    return int(resolve_nfft(
        float(fs),
        int(n_samples),
        float(params.get('t_win_s', 1.0)),
        float(params.get('overlap', 0.5)),
    ))


def compute_order_time_spectro(sig, rpm, time, fs, params) -> "_Spectro2D":
    """Compute time-order spectrogram via COT and return a ``_Spectro2D``.

    ``matrix`` is x-major ``(len(times), len(orders))`` so that
    ``to_long_dataframe()`` round-trips through ``_matrix_to_long_dataframe``
    without any transpose. The transpose needed for ``imshow`` (rows=y) is
    applied in ``BatchRunner._write_image``.
    """
    from .signal.order_cot import COTOrderAnalyzer, COTParams

    sig, _spec = apply_filter_if_enabled(sig, fs, params)

    # Defensive: COT requires strictly monotonic t. Even microsecond
    # jitter in MF4 timestamps would raise ValueError. If not strict,
    # rebuild a uniform fallback from len + fs.
    time_arr = np.asarray(time, dtype=float)
    if len(time_arr) < 2 or np.any(np.diff(time_arr) <= 0):
        time_arr = np.arange(len(time_arr), dtype=float) / float(fs)

    cot_params = COTParams(
        samples_per_rev=int(params.get('samples_per_rev', 256)),
        nfft=int(params.get('nfft', 1024)),
        window=str(params.get('window', 'hanning')),
        max_order=float(params.get('max_order', params.get('max_ord', 20))),
        order_res=float(params.get('order_res', 0.1)),
        time_res=float(params.get('time_res', 0.05)),
        fs=float(fs),
        weighting=str(params.get('weighting', 'None')),
    )
    result = COTOrderAnalyzer.compute(sig, rpm, time_arr, cot_params)
    return _Spectro2D(
        x=np.asarray(result.times, dtype=float),
        y=np.asarray(result.orders, dtype=float),
        matrix=np.asarray(result.amplitude, dtype=float),
        x_name='time_s',
        y_name='order',
        metadata=dict(getattr(result, 'metadata', {}) or {}),
    )


def compute_order_time_dataframe(sig, rpm, time, fs, params):
    """Thin wrapper — delegates to ``compute_order_time_spectro``.

    As of 2026-04-28 the legacy frequency-domain path
    (``OrderAnalyzer`` time-order result builder) is no longer invoked
    here; COT handles all RPM regimes (sweep, coast-down, steady-state)
    without smearing. ``samples_per_rev`` defaults to 256 when absent from
    preset params; the COT pipeline requires ``time`` to be strictly
    monotonically increasing.
    """
    return compute_order_time_spectro(sig, rpm, time, fs, params).to_long_dataframe()


def compute_fft_time_spectro(sig, time, fs, params, *,
                              channel_name='') -> "_Spectro2D":
    """Compute one-sided FFT-vs-time spectrogram and return a ``_Spectro2D``.

    ``SpectrogramAnalyzer.compute`` returns ``amplitude`` with shape
    ``(freq_bins, frames)``. ``_Spectro2D.matrix`` is x-major
    ``(len(times), len(frequencies))``, so we store ``amplitude.T``
    (``(frames, freq_bins)``). The exported dataframe stays in linear
    amplitude — the dB conversion is a display-only choice in
    ``BatchRunner._write_image``.
    """
    from .signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams
    sig, _spec = apply_filter_if_enabled(sig, fs, params)
    time, fs = uniform_time_axis_for_spectrogram(time, fs, len(sig))
    sp = SpectrogramParams(
        fs=float(fs),
        nfft=int(params.get('nfft', 1024)),
        window=str(params.get('window', 'hanning')),
        overlap=float(params.get('overlap', 0.5)),
        remove_mean=bool(params.get('remove_mean', True)),
        weighting=str(params.get('weighting', 'None')),
    )
    result = SpectrogramAnalyzer.compute(
        signal=sig, time=time, params=sp,
        channel_name=channel_name or 'signal',
    )
    return _Spectro2D(
        x=np.asarray(result.times, dtype=float),
        y=np.asarray(result.frequencies, dtype=float),
        matrix=np.asarray(result.amplitude.T, dtype=float),
        x_name='time_s',
        y_name='frequency_hz',
        metadata=dict(getattr(result, 'metadata', {}) or {}),
    )


def compute_fft_time_dataframe(sig, time, fs, params, *, channel_name=''):
    """Thin wrapper — delegates to ``compute_fft_time_spectro``.

    ``SpectrogramAnalyzer.compute`` returns ``amplitude`` with shape
    ``(freq_bins, frames)``. ``_matrix_to_long_dataframe`` requires
    ``matrix.shape == (len(x_values), len(y_values))`` (x-major), so we
    transpose to ``(frames, freq_bins)`` before flattening. The exported
    dataframe stays in linear amplitude — the dB conversion is a
    display-only choice in ``BatchRunner._write_image``.
    """
    return compute_fft_time_spectro(
        sig, time, fs, params, channel_name=channel_name,
    ).to_long_dataframe()


def strict_finite_time_axis(values, expected_length: int) -> bool:
    try:
        axis = np.asarray(values, dtype=float)
    except (TypeError, ValueError):
        return False
    return bool(
        axis.ndim == 1
        and len(axis) == int(expected_length)
        and len(axis) >= 2
        and np.all(np.isfinite(axis))
        and np.all(np.diff(axis) > 0.0)
    )


def _guess_rpm_channel(fd):
    for ch in fd.get_signal_channels():
        low = ch.lower()
        if 'rpm' in low or 'speed' in low or 'tach' in low:
            return ch
    return ''


@dataclass(frozen=True)
class _Spectro2D:
    """2-D analysis result kept matrix-first to avoid a long→wide pivot
    round-trip on export. ``matrix`` is x-major: shape (len(x), len(y)).

    ``metadata`` preserves analyzer-owned display coverage such as
    ``coverage_start`` / ``coverage_end``.  It is deliberately absent from
    :meth:`to_long_dataframe` so CSV values and column order stay unchanged.
    """
    x: np.ndarray
    y: np.ndarray
    matrix: np.ndarray
    x_name: str
    y_name: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_long_dataframe(self) -> pd.DataFrame:
        return _matrix_to_long_dataframe(
            self.x, self.y, self.matrix, self.x_name, self.y_name)

    def slice_curve(self, axis: str, index: int) -> np.ndarray:
        """Amplitudes along one slice pick, straight off the x-major matrix.

        ``matrix`` here is **x-major**, shape ``(len(x), len(y))`` -- the
        transpose of what the renderer's ``_extract_heatmap`` hands to
        ``_builder._slice_curve_values`` (it applies ``x_major.T``). So the
        indexing is mirrored: fixing a *time* takes a matrix **row** and the
        curve runs along ``y``; fixing a *frequency/order* takes a **column**
        and the curve runs along ``x``. ``tests/test_batch_slice_export.py``
        pins this against the rendered curves point by point, because getting
        it backwards yields a plausible-looking table of the wrong values.
        """
        matrix = np.asarray(self.matrix, dtype=float)
        if str(axis).strip().lower() == 'time':
            return matrix[int(index), :]
        return matrix[:, int(index)]

    def to_slice_sheets(
        self,
        plan,
        *,
        render_db: bool,
        reference: float | None = None,
        amplitude_label: str = '',
        facts: "Sequence[str]" = (),
        source: str = '',
        channel: str = '',
        unit: str = '',
        method: str = '',
    ) -> "dict[str, pd.DataFrame]":
        """``{"切片信息": df, "<时间|频率|阶次>切片": df}`` for one slice plan.

        One wide sheet with a position per column, so a reader can select a few
        columns in Excel and get the comparison chart the multi-position slice
        exists for (design D23), plus a key/value sheet that makes the file
        self-describing.

        Values are written in the **charted** caliber only -- dB when the page
        renders dB -- with the caliber and its reference recorded on the info
        sheet rather than doubling the column count with a parallel linear set
        (design D24).
        """
        # Deferred: the label lookups are batch.py runner-facing formatting
        # helpers, not DSP. Importing at call time (rather than module import
        # time) avoids a batch_compute <-> batch import cycle -- batch.py
        # imports this module at top level for the compat aliases.
        from .batch import _slice_axis_labels, _slice_fact_rows

        fixed_name = self.x_name if plan.axis == 'time' else self.y_name
        curve_name = self.y_name if plan.axis == 'time' else self.x_name
        curve_coords = np.asarray(
            self.y if plan.axis == 'time' else self.x, dtype=float
        )
        dimension, sheet_name, prefix, position_unit, decimals = (
            _slice_axis_labels(fixed_name)
        )

        columns: dict[str, np.ndarray] = {curve_name: curve_coords}
        for pick in plan.picks:
            values = self.slice_curve(plan.axis, pick.index)
            if render_db:
                from .signal.spectrogram import SpectrogramAnalyzer

                # Element-wise, so converting the picked line alone is
                # numerically identical to slicing the renderer's full
                # ``display_matrix``.
                values = np.asarray(
                    SpectrogramAnalyzer.amplitude_to_db(
                        values, reference=float(reference or 1.0)
                    ),
                    dtype=float,
                )
            name = f'{prefix}={pick.value:.{decimals}f}{position_unit}'
            suffix = 2
            while name in columns:
                name = (
                    f'{prefix}={pick.value:.{decimals}f}{position_unit}'
                    f'#{suffix}'
                )
                suffix += 1
            columns[name] = np.asarray(values, dtype=float)

        def _positions(attribute: str) -> str:
            # Four decimals, not the column headers' 1-2: the whole point of
            # printing request and landing side by side is that a reader can
            # see they differ (design D11), and 620.0 vs 615.2 Hz rounds to the
            # same header text more often than not.
            joined = ', '.join(
                f'{getattr(pick, attribute):.4f}' for pick in plan.picks
            )
            return f'{joined} {position_unit}'.strip()

        clamped = plan.clamped_picks
        notes = []
        if clamped:
            notes.append(
                '夹取到数据边界：'
                + ', '.join(f'{pick.value:.{decimals}f}' for pick in clamped)
            )
        if plan.merged:
            notes.append(
                f'{len(plan.picks) + plan.merged} 个位置夹取后合并为 '
                f'{len(plan.picks)} 个'
            )

        info: list[tuple[str, str]] = [
            ('来源文件', str(source)),
            ('通道', str(channel)),
            ('单位', str(unit)),
            ('方法', str(method)),
        ]
        info.extend(_slice_fact_rows(facts))
        info.append(('幅值口径', str(amplitude_label)))
        if render_db:
            info.append(('dB 参考值', f'{float(reference or 1.0):g}'))
        info.extend([
            ('切片维度', f'固定{dimension}'),
            ('切片位置 请求', _positions('requested')),
            ('切片位置 落点', _positions('value')),
            ('切片位置 备注', '；'.join(notes) if notes else '—'),
        ])
        return {
            # An em dash rather than an empty cell: a blank reads as "the
            # exporter forgot" and round-trips out of xlsx as NaN, while a
            # unit-less channel is a fact worth stating.
            '切片信息': pd.DataFrame(
                {'项目': [key for key, _ in info],
                 '值': [value if value else '—' for _, value in info]}
            ),
            sheet_name: pd.DataFrame(columns),
        }


def _matrix_to_long_dataframe(x_values, y_values, matrix, x_name, y_name):
    x_values = np.asarray(x_values, dtype=float)
    y_values = np.asarray(y_values, dtype=float)
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (len(x_values), len(y_values)):
        raise ValueError(
            f"matrix shape {matrix.shape} does not match "
            f"({len(x_values)}, {len(y_values)})"
        )
    xs = np.repeat(x_values, len(y_values))
    ys = np.tile(y_values, len(x_values))
    return pd.DataFrame({x_name: xs, y_name: ys, 'amplitude': matrix.reshape(-1)})
