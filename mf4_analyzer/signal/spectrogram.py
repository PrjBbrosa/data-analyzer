"""2D FFT-vs-time spectrogram analysis without GUI dependencies.

This module is the GUI-free signal-processing core of the FFT vs Time
mode. It owns:

  * the ``SpectrogramParams`` cache key (fs, nfft, window, overlap,
    remove_mean, db_reference);
  * the ``SpectrogramResult`` payload returned to the canvas;
  * frame construction (uniform-time validation, hop computation,
    frame center times);
  * the 64 MB float32 amplitude memory ceiling;
  * the ``amplitude_to_db`` conversion helper.

Display-only state lives on the canvas, never on params or result —
``amplitude_mode`` (Amplitude vs Amplitude dB), ``cmap``, dynamic range,
and frequency range never trigger a recompute. ``time_jitter_tolerance``
is a kwarg on :meth:`SpectrogramAnalyzer.compute`, NOT a
``SpectrogramParams`` field, so the cache key stays stable across
UI-only display changes.

The dB matrix is NOT cached on the result. The canvas computes it
lazily through :meth:`SpectrogramAnalyzer.amplitude_to_db` and keeps
its own internal cache keyed by ``(id(result), db_reference)`` (Task 4
in the FFT-vs-Time plan; see lesson
``signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface``
for the consumer-side grep discipline). Adding caching here would
duplicate state and break the consumer-end contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from .fft import one_sided_amplitude


# Hard ceiling on the rendered float32 amplitude matrix size.
# 64 MB ~ 16 M cells, e.g. 4097-bin x 4096-frame.
_MAX_AMPLITUDE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class SpectrogramParams:
    """Compute-relevant parameters for ``SpectrogramAnalyzer.compute``.

    These fields form the cache key. Display-only knobs (amplitude
    mode, colormap, dynamic range, frequency range) are NOT here — they
    live on the canvas and never trigger a recompute.
    """

    fs: float
    nfft: int
    window: str = 'hanning'
    overlap: float = 0.5
    remove_mean: bool = True
    db_reference: float = 1.0


@dataclass
class SpectrogramResult:
    """Computed spectrogram payload returned by :meth:`SpectrogramAnalyzer.compute`.

    Attributes
    ----------
    times : numpy.ndarray
        Frame center times in seconds, shape ``(frames,)``.
    frequencies : numpy.ndarray
        One-sided FFT bin frequencies in Hz, shape ``(freq_bins,)``
        where ``freq_bins = nfft // 2 + 1``.
    amplitude : numpy.ndarray
        Linear amplitude matrix, ``float32``, shape
        ``(freq_bins, frames)``. dB conversion happens on the canvas
        via :meth:`SpectrogramAnalyzer.amplitude_to_db`.
    params : SpectrogramParams
        The compute-relevant parameter set used to produce this result.
    channel_name : str
        Source channel name for plot titles and exports.
    unit : str
        Source channel unit (``''`` if unknown).
    metadata : dict
        Implementation-defined extras, e.g. ``frames``, ``hop``,
        ``freq_bins``.
    """

    times: np.ndarray
    frequencies: np.ndarray
    amplitude: np.ndarray
    params: SpectrogramParams
    channel_name: str
    unit: str = ''
    metadata: dict = field(default_factory=dict)


class SpectrogramAnalyzer:
    """GUI-free analyzer for the FFT vs Time 2D mode.

    All public methods are static so the class can be imported and
    exercised without instantiation. ``compute`` does the heavy work;
    ``amplitude_to_db`` is the canvas-facing dB helper.
    """

    @staticmethod
    def amplitude_to_db(amplitude, reference: float = 1.0) -> np.ndarray:
        """Linear amplitude -> dB using ``20 * log10(max(amp, eps) / ref)``.

        Floors the input at ``np.finfo(float).tiny`` so log of zero
        does not appear in the result. The canvas-side dB cache (Task 4
        of the FFT-vs-Time plan) is the consumer of this helper —
        callers there are expected to memoize the returned matrix
        keyed by ``(id(result), reference)``.

        Parameters
        ----------
        amplitude : array_like
            Linear amplitude matrix or scalar.
        reference : float, optional
            dB reference (must be ``> 0``). Default ``1.0`` (the
            "dB re 1 unit" first-version reference).

        Returns
        -------
        numpy.ndarray
            ``float64`` dB values with the same shape as ``amplitude``.
        """
        ref = float(reference)
        if ref <= 0:
            raise ValueError('db_reference must be > 0')
        amp = np.asarray(amplitude, dtype=float)
        eps = np.finfo(float).tiny
        return 20.0 * np.log10(np.maximum(amp, eps) / ref)

    @staticmethod
    def _validate_time_axis(t, fs: float, tolerance: float) -> np.ndarray:
        arr = np.asarray(t, dtype=float)
        if arr.ndim != 1:
            raise ValueError('time axis must be one-dimensional')
        if arr.size < 2:
            raise ValueError('time axis is too short')
        nominal_dt = 1.0 / float(fs)
        dt = np.diff(arr)
        if np.any(dt <= 0):
            # A non-monotonic axis is the extreme case of non-uniform —
            # we surface it under the same "non-uniform" banner so the
            # UI can give one consistent rebuild-time-axis prompt.
            raise ValueError(
                'non-uniform time axis: time samples must be strictly '
                'increasing'
            )
        relative_jitter = float(np.max(np.abs(dt - nominal_dt)) / nominal_dt)
        if relative_jitter > tolerance:
            raise ValueError(
                f'non-uniform time axis: relative_jitter={relative_jitter:.3g} '
                f'exceeds tolerance={tolerance:.3g}'
            )
        return arr

    @staticmethod
    def compute(
        signal,
        time,
        params: SpectrogramParams,
        channel_name,
        unit: str = '',
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_token: Optional[Callable[[], bool]] = None,
        time_jitter_tolerance: float = 1e-3,
        max_amplitude_bytes: int = _MAX_AMPLITUDE_BYTES,
    ) -> SpectrogramResult:
        """Compute the 2D spectrogram for ``signal`` on uniform ``time``.

        Parameters
        ----------
        signal : array_like
            One-dimensional time-domain samples, length ``N``.
        time : array_like
            One-dimensional sample times in seconds, length ``N``.
            Must be strictly increasing and effectively uniform —
            ``max|dt - 1/fs| / (1/fs) <= time_jitter_tolerance``,
            otherwise the call rejects.
        params : SpectrogramParams
            Compute-relevant parameter set (cache key).
        channel_name : str
            Source channel name (for the result payload).
        unit : str, optional
            Source channel unit; ``''`` if unknown.
        progress_callback : callable, optional
            ``(current_frame, total_frames) -> None``. Throttled to
            ~50 emissions per run, plus the final
            ``(total, total)`` emission. Called from the worker thread
            in production; analyzer never touches Qt.
        cancel_token : callable, optional
            ``() -> bool``. Polled at the top of each frame; if it
            returns truthy, the call raises ``RuntimeError``. The
            FFT-vs-Time plan wires this through the worker but does
            NOT add a UI cancel button in Phase 1.
        time_jitter_tolerance : float, optional
            Maximum allowed relative jitter on the time axis. Default
            ``1e-3``. Kept as a kwarg (NOT a ``SpectrogramParams``
            field) so the cache key is stable across UI-only display
            changes.
        max_amplitude_bytes : int, optional
            Pre-flight ceiling on the float32 amplitude matrix size.
            Default 64 MB. Oversized requests raise ``ValueError``
            with frame count and MB estimate so the UI can suggest
            reducing nfft, overlap, or selected time range.

        Returns
        -------
        SpectrogramResult

        Raises
        ------
        ValueError
            For ``fs <= 0``, ``nfft <= 1``, invalid overlap, length
            mismatch, signal shorter than ``nfft``, non-positive hop,
            non-uniform time axis, or memory ceiling exceeded.
        RuntimeError
            If ``cancel_token`` returns truthy mid-compute.
        """
        fs = float(params.fs)
        if fs <= 0:
            raise ValueError('fs must be > 0')
        nfft = int(params.nfft)
        if nfft <= 1:
            raise ValueError('nfft must be > 1')
        if not (0 <= float(params.overlap) < 1):
            raise ValueError('overlap must be >= 0 and < 1')

        sig = np.asarray(signal, dtype=float)
        if sig.ndim != 1:
            raise ValueError('signal must be one-dimensional')
        t = SpectrogramAnalyzer._validate_time_axis(time, fs, time_jitter_tolerance)
        if sig.size != t.size:
            raise ValueError('signal and time must have the same length')
        if sig.size < nfft:
            raise ValueError('signal is shorter than nfft')

        hop = int(nfft * (1.0 - float(params.overlap)))
        if hop <= 0:
            raise ValueError('overlap leaves no positive hop size')
        starts = np.arange(0, sig.size - nfft + 1, hop, dtype=int)
        total = int(starts.size)
        if total <= 0:
            raise ValueError('no complete spectrogram frames')

        freq_bins = nfft // 2 + 1
        estimated_bytes = freq_bins * total * 4  # float32
        if estimated_bytes > int(max_amplitude_bytes):
            raise ValueError(
                f'memory ceiling exceeded: '
                f'{freq_bins} bins x {total} frames ~= '
                f'{estimated_bytes / (1024 * 1024):.1f} MB '
                f'(ceiling {int(max_amplitude_bytes) / (1024 * 1024):.0f} MB). '
                f'Reduce nfft, overlap, or selected time range.'
            )

        amplitude = np.empty((freq_bins, total), dtype=np.float32)
        times = np.empty(total, dtype=float)
        freq = None
        # Throttle progress callbacks to ~50 emissions over the run,
        # plus a final (total, total) emission for the worker UI.
        progress_step = max(1, total // 50)
        for i, start in enumerate(starts):
            if cancel_token is not None and cancel_token():
                raise RuntimeError('spectrogram computation cancelled')
            frame = sig[start:start + nfft]
            f, amp = one_sided_amplitude(
                frame,
                fs,
                win=params.window,
                nfft=nfft,
                remove_mean=params.remove_mean,
            )
            if freq is None:
                freq = f
            amplitude[:, i] = amp.astype(np.float32, copy=False)
            times[i] = t[start] + (nfft - 1) / (2.0 * fs)
            if progress_callback is not None and (
                (i + 1) % progress_step == 0 or (i + 1) == total
            ):
                progress_callback(i + 1, total)

        return SpectrogramResult(
            times=times,
            frequencies=np.asarray(freq, dtype=float),
            amplitude=amplitude,
            params=params,
            channel_name=str(channel_name),
            unit=str(unit or ''),
            metadata={'frames': total, 'hop': hop, 'freq_bins': freq_bins},
        )
