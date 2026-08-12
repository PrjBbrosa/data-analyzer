"""NumPy-only SISO frequency-response estimation.

The module owns the numerical FRF contract only. Source/channel identity,
engineering units, time-range selection, and display state are assembled by
the GUI and Batch adapters. Runtime imports stay GUI- and SciPy-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import Callable, Literal

import numpy as np

from .spectrogram import DEFAULT_TIME_JITTER_TOLERANCE


_WINDOW_ALIASES = {"hann": "hanning"}
_WINDOW_NAMES = {"hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop"}
_MAX_COMPLEX_TEMPORARY_BYTES = 64 * 1024 * 1024

# A bin is numerically unexcited only relative to the strongest finite bin of
# the same spectrum. There is deliberately no absolute ``max(reference, 1)``
# floor: that would make validity depend on engineering-unit scale.
RELATIVE_DENOMINATOR_EPS_FACTOR = 64.0


def _canonical_window_name(name: str) -> str:
    key = str(name or "hanning").lower()
    key = _WINDOW_ALIASES.get(key, key)
    if key not in _WINDOW_NAMES:
        raise ValueError(f"unknown window: {name!r}")
    return key


def _flattop_symmetric(n: int) -> np.ndarray:
    """Return the existing five-term symmetric flat-top definition."""
    if n == 1:
        return np.ones(1, dtype=np.float64)
    coefficients = (0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368)
    phase = np.linspace(-np.pi, np.pi, n)
    window = np.zeros(n, dtype=np.float64)
    for order, coefficient in enumerate(coefficients):
        window += coefficient * np.cos(order * phase)
    return window


def get_frf_window(name: str, n: int, periodic: bool = True) -> np.ndarray:
    """Return an explicit FRF window of length ``n``.

    Periodic windows use the common ``symmetric(n + 1)[:-1]`` rule, except
    that every single-point window is exactly ``[1.]``. This matches SciPy
    ``get_window(..., fftbins=True)`` while keeping SciPy out of the runtime
    dependency graph.
    """
    if isinstance(n, (bool, np.bool_)) or not isinstance(n, Integral) or int(n) < 1:
        raise ValueError("window length must be a positive integer")
    if not isinstance(periodic, (bool, np.bool_)):
        raise ValueError("periodic must be bool")
    key = _canonical_window_name(name)
    requested = int(n)
    if requested == 1:
        return np.ones(1, dtype=np.float64)
    generated = requested + 1 if bool(periodic) else requested
    if key == "kaiser":
        window = np.kaiser(generated, 14.0)
    elif key == "flattop":
        window = _flattop_symmetric(generated)
    else:
        generator = {
            "hanning": np.hanning,
            "hamming": np.hamming,
            "blackman": np.blackman,
            "bartlett": np.bartlett,
        }[key]
        window = generator(generated)
    if periodic:
        window = window[:-1]
    return np.asarray(window, dtype=np.float64)


@dataclass(frozen=True)
class FrfParams:
    """Compute-only FRF parameters; display fields do not belong here."""

    estimator: Literal["h1", "h2"] = "h1"
    t_win_s: float = 2.0
    overlap: float = 0.5
    nfft_mode: Literal["auto", "manual"] = "auto"
    nfft: int | None = None
    window: str = "hanning"
    periodic_window: bool = True
    detrend: Literal["constant", "none"] = "constant"

    def __post_init__(self) -> None:
        if self.estimator not in {"h1", "h2"}:
            raise ValueError("estimator must be 'h1' or 'h2'")
        if isinstance(self.t_win_s, (bool, np.bool_)):
            raise ValueError("t_win_s must be finite and > 0")
        try:
            duration = float(self.t_win_s)
        except (TypeError, ValueError) as exc:
            raise ValueError("t_win_s must be finite and > 0") from exc
        if not np.isfinite(duration) or duration <= 0:
            raise ValueError("t_win_s must be finite and > 0")
        object.__setattr__(self, "t_win_s", duration)

        if isinstance(self.overlap, (bool, np.bool_)):
            raise ValueError("overlap must be finite and satisfy 0 <= overlap < 1")
        try:
            overlap = float(self.overlap)
        except (TypeError, ValueError) as exc:
            raise ValueError("overlap must be finite and satisfy 0 <= overlap < 1") from exc
        if not np.isfinite(overlap) or not 0 <= overlap < 1:
            raise ValueError("overlap must be finite and satisfy 0 <= overlap < 1")
        object.__setattr__(self, "overlap", overlap)

        if self.nfft_mode not in {"auto", "manual"}:
            raise ValueError("nfft_mode must be 'auto' or 'manual'")
        if self.nfft_mode == "auto":
            if self.nfft is not None:
                raise ValueError("nfft must be None when nfft_mode is 'auto'")
        elif (
            isinstance(self.nfft, (bool, np.bool_))
            or not isinstance(self.nfft, Integral)
            or int(self.nfft) < 1
        ):
            raise ValueError("nfft must be a positive integer in manual mode")
        elif self.nfft is not None:
            object.__setattr__(self, "nfft", int(self.nfft))

        if not isinstance(self.periodic_window, (bool, np.bool_)):
            raise ValueError("periodic_window must be bool")
        object.__setattr__(self, "periodic_window", bool(self.periodic_window))
        object.__setattr__(self, "window", _canonical_window_name(self.window))
        if self.detrend not in {"constant", "none"}:
            raise ValueError("detrend must be 'constant' or 'none'")


class FrfRequestValidationError(ValueError):
    """Expected invalid FRF request shape or resource requirement."""


class FrfCancelled(RuntimeError):
    """Cancel token fired during spectral accumulation.

    Structured identity for adapters (Batch / GUI): catch the type, never
    sniff ``str(exc)``. Message kept stable for logs and older matchers.
    """

    MESSAGE = "FRF computation cancelled"

    def __init__(self, message: str = MESSAGE):
        super().__init__(message)


class FrfSpectralOverflow(ValueError):
    """Spectral sums overflowed float64; rescale the input signals.

    Structured identity for adapters: catch the type, never sniff
    ``str(exc)``. Message kept stable for logs and older matchers.
    """

    MESSAGE = "spectral accumulation overflow; rescale the input signals"

    def __init__(self, message: str = MESSAGE):
        super().__init__(message)


@dataclass(frozen=True)
class FrfRequestPlan:
    """Validated segment/FFT shape before any spectral allocation."""

    requested_nperseg: int
    nperseg: int
    noverlap: int
    hop: int
    nfft: int
    frequency_bins: int
    segments: int
    complex_temporary_bytes: int


def plan_frf_request(*, n_samples: int, fs, params: FrfParams) -> FrfRequestPlan:
    """Validate and plan one FRF request without allocating FFT buffers."""

    if not isinstance(params, FrfParams):
        raise FrfRequestValidationError("params must be FrfParams")
    if (
        isinstance(n_samples, (bool, np.bool_))
        or not isinstance(n_samples, Integral)
        or int(n_samples) < 0
    ):
        raise FrfRequestValidationError(
            "n_samples must be a non-negative integer"
        )
    sample_count = int(n_samples)
    try:
        sample_rate = _validate_fs(fs)
    except ValueError as exc:
        raise FrfRequestValidationError(str(exc)) from exc

    requested_samples_float = sample_rate * params.t_win_s
    if not np.isfinite(requested_samples_float):
        raise FrfRequestValidationError("fs * t_win_s is too large")
    requested_nperseg = int(round(requested_samples_float))
    if requested_nperseg < 2:
        raise FrfRequestValidationError(
            "segment length must be at least 2 samples"
        )
    nperseg = requested_nperseg
    noverlap = int(np.floor(params.overlap * nperseg))
    hop = nperseg - noverlap
    nfft = nperseg if params.nfft_mode == "auto" else int(params.nfft)
    if nfft < nperseg:
        raise FrfRequestValidationError(
            "nfft must be greater than or equal to segment length"
        )

    frequency_bins = nfft // 2 + 1
    # Peak expression evaluation holds X, Y, conj(X), and conj(X)*Y at once.
    complex_temporary_bytes = (
        4 * frequency_bins * np.dtype(np.complex128).itemsize
    )
    if complex_temporary_bytes > _MAX_COMPLEX_TEMPORARY_BYTES:
        raise FrfRequestValidationError(
            "temporary complex-array memory exceeds the 64 MiB ceiling; reduce nfft"
        )

    segments = (
        0
        if sample_count < nperseg
        else 1 + (sample_count - nperseg) // hop
    )
    if segments < 2:
        raise FrfRequestValidationError(
            "FRF averaging requires at least 2 complete segments; "
            "shorten the window or enlarge the time range"
        )
    return FrfRequestPlan(
        requested_nperseg=requested_nperseg,
        nperseg=nperseg,
        noverlap=noverlap,
        hop=hop,
        nfft=nfft,
        frequency_bins=frequency_bins,
        segments=segments,
        complex_temporary_bytes=complex_temporary_bytes,
    )


@dataclass(frozen=True)
class FrfEffectiveFacts:
    """Numerical parameters and measured facts for one completed run."""

    requested_t_win_s: float
    requested_nperseg: int
    nperseg: int
    nfft: int
    noverlap: int
    hop: int
    segments: int
    fs: float
    df: float
    n_samples: int
    time_start: float
    time_end: float
    window: str
    periodic_window: bool
    detrend: str
    max_time_jitter: float
    max_time_difference: float
    invalid_bins: int


@dataclass(frozen=True)
class FrfResult:
    """Raw FRF spectra and transfer estimate."""

    frequencies: np.ndarray
    transfer: np.ndarray
    pxx: np.ndarray
    pyy: np.ndarray
    pxy: np.ndarray
    coherence: np.ndarray
    effective: FrfEffectiveFacts
    warnings: tuple[str, ...] = ()


def _validate_real_vector(values, label: str) -> np.ndarray:
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(f"{label} must be one-dimensional")
    if array.size == 0:
        raise ValueError(f"{label} is empty")
    if np.issubdtype(array.dtype, np.bool_):
        raise ValueError(f"{label} must not be bool")
    if np.iscomplexobj(array):
        raise ValueError(f"{label} must be real, not complex")
    if not np.issubdtype(array.dtype, np.number):
        raise ValueError(f"{label} must contain real numeric values")
    result = array.astype(np.float64, copy=False)
    finite = np.isfinite(result)
    if not np.all(finite):
        raise ValueError(
            f"{label} contains {int(result.size - np.count_nonzero(finite))} non-finite samples"
        )
    return result


def _validate_fs(fs) -> float:
    if isinstance(fs, (bool, np.bool_)):
        raise ValueError("fs must be finite and > 0")
    try:
        value = float(fs)
    except (TypeError, ValueError) as exc:
        raise ValueError("fs must be finite and > 0") from exc
    if not np.isfinite(value) or value <= 0:
        raise ValueError("fs must be finite and > 0")
    return value


def _validate_time_axis(
    values,
    *,
    label: str,
    expected_size: int,
    fs: float,
    tolerance: float,
) -> tuple[np.ndarray, float]:
    time = _validate_real_vector(values, label)
    if time.size != expected_size:
        raise ValueError(f"{label} and its signal must have the same length")
    if time.size < 2:
        raise ValueError(f"{label} must contain at least 2 samples")
    differences = np.diff(time)
    if np.any(differences <= 0):
        raise ValueError(f"{label} must be strictly increasing")
    nominal_dt = 1.0 / fs
    relative_jitter = float(np.max(np.abs(differences - nominal_dt)) / nominal_dt)
    if relative_jitter > tolerance:
        raise ValueError(
            f"{label} is non-uniform: relative_jitter={relative_jitter:.6g} "
            f"exceeds tolerance={tolerance:.6g}"
        )
    return time, relative_jitter


def _readonly(array, dtype) -> np.ndarray:
    result = np.asarray(array, dtype=dtype)
    result.setflags(write=False)
    return result


def _finite_reference(values: np.ndarray) -> float:
    finite = np.isfinite(values)
    if not np.any(finite):
        return 0.0
    return float(np.max(np.abs(values[finite])))


def magnitude_linear(transfer) -> np.ndarray:
    """Return ``abs(H)`` without changing the raw transfer array."""
    return np.asarray(np.abs(np.asarray(transfer, dtype=np.complex128)), dtype=np.float64)


def magnitude_db(transfer) -> np.ndarray:
    """Return transfer magnitude in dB re one ratio unit."""
    magnitude = magnitude_linear(transfer)
    return 20.0 * np.log10(np.maximum(magnitude, np.finfo(np.float64).tiny))


def phase_wrapped_deg(transfer) -> np.ndarray:
    """Return wrapped phase in degrees."""
    values = np.asarray(transfer, dtype=np.complex128)
    return np.asarray(np.angle(values, deg=True), dtype=np.float64)


def phase_unwrapped_deg(transfer) -> np.ndarray:
    """Unwrap phase independently on each contiguous finite run."""
    values = np.asarray(transfer, dtype=np.complex128)
    if values.ndim != 1:
        raise ValueError("transfer must be one-dimensional")
    output = np.full(values.shape, np.nan, dtype=np.float64)
    finite = np.isfinite(values.real) & np.isfinite(values.imag)
    indices = np.flatnonzero(finite)
    if not indices.size:
        return output
    boundaries = np.flatnonzero(np.diff(indices) != 1) + 1
    for run in np.split(indices, boundaries):
        radians = np.angle(values[run])
        output[run] = np.rad2deg(np.unwrap(radians))
    return output


def compute_frf(
    input_values,
    output_values,
    *,
    fs,
    params: FrfParams,
    input_time=None,
    output_time=None,
    cancel_check: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> FrfResult:
    """Compute a Welch H1/H2 FRF using full, uniformly spaced segments."""
    if not isinstance(params, FrfParams):
        raise ValueError("params must be FrfParams")
    sample_rate = _validate_fs(fs)
    input_signal = _validate_real_vector(input_values, "input")
    output_signal = _validate_real_vector(output_values, "output")
    if input_signal.size != output_signal.size:
        raise ValueError("input and output must have the same length")

    if (input_time is None) != (output_time is None):
        raise ValueError("input_time and output_time must be supplied together")
    max_time_jitter = 0.0
    max_time_difference = 0.0
    if input_time is None:
        time_start = 0.0
        time_end = float((input_signal.size - 1) / sample_rate)
    else:
        input_axis, input_jitter = _validate_time_axis(
            input_time,
            label="input_time",
            expected_size=input_signal.size,
            fs=sample_rate,
            tolerance=DEFAULT_TIME_JITTER_TOLERANCE,
        )
        output_axis, output_jitter = _validate_time_axis(
            output_time,
            label="output_time",
            expected_size=output_signal.size,
            fs=sample_rate,
            tolerance=DEFAULT_TIME_JITTER_TOLERANCE,
        )
        max_time_jitter = max(input_jitter, output_jitter)
        max_time_difference = float(np.max(np.abs(input_axis - output_axis)))
        alignment_tolerance = DEFAULT_TIME_JITTER_TOLERANCE / sample_rate
        if max_time_difference > alignment_tolerance:
            raise ValueError(
                "input and output time axes differ: maximum difference="
                f"{max_time_difference:.6g}s exceeds tolerance={alignment_tolerance:.6g}s"
            )
        time_start = float(input_axis[0])
        time_end = float(input_axis[-1])

    request_plan = plan_frf_request(
        n_samples=int(input_signal.size),
        fs=sample_rate,
        params=params,
    )
    requested_nperseg = request_plan.requested_nperseg
    nperseg = request_plan.nperseg
    noverlap = request_plan.noverlap
    hop = request_plan.hop
    nfft = request_plan.nfft
    frequency_bins = request_plan.frequency_bins
    segments = request_plan.segments
    starts = np.arange(0, input_signal.size - nperseg + 1, hop, dtype=np.int64)

    window = get_frf_window(
        params.window,
        nperseg,
        periodic=params.periodic_window,
    )
    window_energy = float(np.sum(window * window, dtype=np.float64))
    if not np.isfinite(window_energy) or window_energy <= 0:
        raise ValueError("window energy must be finite and > 0")

    sum_xx = np.zeros(frequency_bins, dtype=np.float64)
    sum_yy = np.zeros(frequency_bins, dtype=np.float64)
    sum_xy = np.zeros(frequency_bins, dtype=np.complex128)
    progress_step = max(1, int(np.ceil(segments / 50.0)))
    with np.errstate(over="ignore", invalid="ignore"):
        for index, start_value in enumerate(starts):
            if cancel_check is not None and cancel_check():
                raise FrfCancelled()
            start = int(start_value)
            x_work = input_signal[start : start + nperseg].copy()
            y_work = output_signal[start : start + nperseg].copy()
            if params.detrend == "constant":
                x_work -= np.mean(x_work)
                y_work -= np.mean(y_work)
            x_work *= window
            y_work *= window
            x_spectrum = np.fft.rfft(x_work, n=nfft)
            y_spectrum = np.fft.rfft(y_work, n=nfft)
            sum_xx += x_spectrum.real * x_spectrum.real + x_spectrum.imag * x_spectrum.imag
            sum_yy += y_spectrum.real * y_spectrum.real + y_spectrum.imag * y_spectrum.imag
            sum_xy += np.conjugate(x_spectrum) * y_spectrum
            processed = index + 1
            if progress is not None and (
                processed % progress_step == 0 or processed == segments
            ):
                progress(processed, segments)

    density_scale = 1.0 / (sample_rate * window_energy * segments)
    with np.errstate(over="ignore", invalid="ignore"):
        pxx = sum_xx * density_scale
        pyy = sum_yy * density_scale
        pxy = sum_xy * density_scale
        if frequency_bins > 1:
            if nfft % 2 == 0:
                interior = slice(1, -1)
            else:
                interior = slice(1, None)
            pxx[interior] *= 2.0
            pyy[interior] *= 2.0
            pxy[interior] *= 2.0

    if not (
        np.isfinite(pxx).all()
        and np.isfinite(pyy).all()
        and np.isfinite(pxy.real).all()
        and np.isfinite(pxy.imag).all()
    ):
        raise FrfSpectralOverflow()
    pxx = np.maximum(pxx.real, 0.0)
    pyy = np.maximum(pyy.real, 0.0)

    relative_floor = RELATIVE_DENOMINATOR_EPS_FACTOR * np.finfo(np.float64).eps
    pxx_reference = _finite_reference(pxx)
    pyy_reference = _finite_reference(pyy)
    pxy_reference = _finite_reference(pxy)
    transfer_valid = np.zeros(frequency_bins, dtype=bool)
    if params.estimator == "h1":
        if pxx_reference > 0:
            transfer_valid = np.isfinite(pxx) & (pxx > relative_floor * pxx_reference)
        denominator = pxx
    else:
        if pxy_reference > 0:
            transfer_valid = (
                np.isfinite(pxy.real)
                & np.isfinite(pxy.imag)
                & (np.abs(pxy) > relative_floor * pxy_reference)
            )
        denominator = np.conjugate(pxy)

    transfer = np.full(frequency_bins, np.nan + 1j * np.nan, dtype=np.complex128)
    numerator = pxy if params.estimator == "h1" else pyy
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        np.divide(numerator, denominator, out=transfer, where=transfer_valid)
    transfer_overflow_mask = transfer_valid & ~(
        np.isfinite(transfer.real) & np.isfinite(transfer.imag)
    )
    transfer_overflow_bins = int(np.count_nonzero(transfer_overflow_mask))
    if transfer_overflow_bins:
        transfer[transfer_overflow_mask] = np.nan + 1j * np.nan
        transfer_valid[transfer_overflow_mask] = False

    coherence = np.full(frequency_bins, np.nan, dtype=np.float64)
    coherence_valid = np.zeros(frequency_bins, dtype=bool)
    raw_coherence = np.full(frequency_bins, np.nan, dtype=np.float64)
    if pxx_reference > 0 and pyy_reference > 0:
        pxx_normalized = pxx / pxx_reference
        pyy_normalized = pyy / pyy_reference
        coherence_denominator = pxx_normalized * pyy_normalized
        coherence_valid = (
            np.isfinite(coherence_denominator)
            & (pxx_normalized > relative_floor)
            & (pyy_normalized > relative_floor)
        )
        cross_normalized = pxy / np.sqrt(pxx_reference) / np.sqrt(pyy_reference)
        numerator_normalized = np.abs(cross_normalized) ** 2
        np.divide(
            numerator_normalized,
            coherence_denominator,
            out=raw_coherence,
            where=coherence_valid,
        )
        coherence[coherence_valid] = np.clip(raw_coherence[coherence_valid], 0.0, 1.0)

    invalid_mask = ~transfer_valid | ~coherence_valid
    invalid_bins = int(np.count_nonzero(invalid_mask))
    warnings: list[str] = []
    if segments <= 3:
        warnings.append(
            f"statistical stability is low: only {segments} complete segments"
        )
    coherence_tolerance = 256.0 * np.finfo(np.float64).eps
    if np.any(
        coherence_valid
        & ((raw_coherence < -coherence_tolerance) | (raw_coherence > 1.0 + coherence_tolerance))
    ):
        warnings.append("coherence exceeded [0, 1] beyond round-off tolerance and was clipped")
    if transfer_overflow_bins:
        warnings.append(
            f"{transfer_overflow_bins} transfer overflow bins were marked invalid"
        )
    if invalid_bins:
        warnings.append(f"{invalid_bins} frequency bins are invalid due to near-zero excitation")

    effective = FrfEffectiveFacts(
        requested_t_win_s=params.t_win_s,
        requested_nperseg=requested_nperseg,
        nperseg=nperseg,
        nfft=nfft,
        noverlap=noverlap,
        hop=hop,
        segments=segments,
        fs=sample_rate,
        df=sample_rate / nfft,
        n_samples=int(input_signal.size),
        time_start=time_start,
        time_end=time_end,
        window=params.window,
        periodic_window=params.periodic_window,
        detrend=params.detrend,
        max_time_jitter=max_time_jitter,
        max_time_difference=max_time_difference,
        invalid_bins=invalid_bins,
    )
    return FrfResult(
        frequencies=_readonly(np.fft.rfftfreq(nfft, d=1.0 / sample_rate), np.float64),
        transfer=_readonly(transfer, np.complex128),
        pxx=_readonly(pxx, np.float64),
        pyy=_readonly(pyy, np.float64),
        pxy=_readonly(pxy, np.complex128),
        coherence=_readonly(coherence, np.float64),
        effective=effective,
        warnings=tuple(warnings),
    )


__all__ = [
    "FrfCancelled",
    "FrfEffectiveFacts",
    "FrfParams",
    "FrfRequestPlan",
    "FrfRequestValidationError",
    "FrfResult",
    "FrfSpectralOverflow",
    "RELATIVE_DENOMINATOR_EPS_FACTOR",
    "compute_frf",
    "get_frf_window",
    "magnitude_db",
    "magnitude_linear",
    "plan_frf_request",
    "phase_unwrapped_deg",
    "phase_wrapped_deg",
]
