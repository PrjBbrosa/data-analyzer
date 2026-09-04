"""FFTAnalyzer: windowed FFT with amplitude normalization.

Module-level helpers (``get_analysis_window`` and ``one_sided_amplitude``)
are the single source of truth for window construction and one-sided
amplitude scaling so ``FFTAnalyzer`` and the new
``mf4_analyzer.signal.spectrogram.SpectrogramAnalyzer`` cannot drift.

Window generation uses numpy built-ins plus a hand-written ``_flattop``
implementation (scipy's ``general_cosine`` with standard coefficients,
symmetric branch). The app keeps ownership of:

  * alias normalization (``hann`` -> ``hanning``);
  * the ``kaiser`` ``beta=14`` default;
  * the symmetric vs FFT-periodic policy.

One-sided amplitude correctly doubles only the *interior* bins. DC
(``amp[0]``) and, for even ``nfft``, Nyquist (``amp[-1]``) are NOT
doubled — the legacy 2x-everywhere scaling double-counted those bins.
The audit recorded in
``docs/superpowers/reports/2026-04-25-fft-vs-time-T1-signal-layer.md``
shows that no existing FFT amplitude test inspects ``amp[0]`` or
``amp[-1]``, so the correction is safe with respect to the existing
test suite.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from .weighting import _validate_weighting, a_weighting_gain_linear


# App-owned alias normalization. Keeps "hann" and "hanning" pointing at
# the same definition so callers can use either spelling.
_WINDOW_ALIASES = {
    'hann': 'hanning',
}


def _flattop(n):
    """Symmetric flat-top window of length ``n``.

    Equivalent to ``scipy.signal.windows.flattop(n, sym=True)`` — uses the
    same 5-term cosine-sum coefficients and the same symmetric spacing
    (``np.linspace(-pi, pi, n)``).
    """
    if n < 1:
        return np.array([], dtype=float)
    if n == 1:
        return np.ones(1, dtype=float)
    a = [0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368]
    fac = np.linspace(-np.pi, np.pi, n)
    w = np.zeros(n, dtype=float)
    for k in range(len(a)):
        w += a[k] * np.cos(k * fac)
    return w


_NUMPY_WINDOWS = {
    'hanning': np.hanning,
    'hamming': np.hamming,
    'blackman': np.blackman,
    'bartlett': np.bartlett,
}


def get_analysis_window(name, n):
    """Return the app's symmetric analysis window of length ``n``.

    Single source of truth for FFT and spectrogram code so both paths
    use identical amplitude normalization. Implementation uses numpy
    built-ins and a hand-written ``_flattop`` (no scipy dependency).
    App keeps ownership of:

      * alias resolution (``hann`` -> ``hanning``);
      * the ``kaiser`` ``beta`` default (14);
      * the symmetric (``fftbins=False``-equivalent) policy.

    Parameters
    ----------
    name : str
        Window name. Accepted: ``hanning``/``hann``, ``hamming``,
        ``blackman``, ``bartlett``, ``kaiser``, ``flattop``.
        Unrecognised names raise ``ValueError``.
    n : int
        Window length in samples.

    Returns
    -------
    numpy.ndarray
        Float64 array of length ``n``.
    """
    key = (name or 'hanning').lower()
    key = _WINDOW_ALIASES.get(key, key)
    if key == 'kaiser':
        return np.kaiser(n, 14).astype(float, copy=False)
    if key == 'flattop':
        return _flattop(n).astype(float, copy=False)
    fn = _NUMPY_WINDOWS.get(key)
    if fn is None:
        raise ValueError(f"unknown window: {name!r}")
    return fn(n).astype(float, copy=False)


def one_sided_amplitude(frame, fs, win='hanning', nfft=None, remove_mean=True):
    """One-sided amplitude spectrum with coherent-gain correction.

    The returned ``amp`` array has the mathematically correct one-sided
    amplitude scaling: interior bins are doubled, but DC (``amp[0]``)
    and — when ``nfft`` is even — Nyquist (``amp[-1]``) are NOT doubled.
    For odd ``nfft`` the last bin is interior and IS doubled.

    Parameters
    ----------
    frame : array_like
        Time-domain samples.
    fs : float
        Sampling frequency in Hz.
    win : str, optional
        Window name (see :func:`get_analysis_window`). Default ``hanning``.
    nfft : int, optional
        FFT length. If ``None`` or ``<= 0``, defaults to ``len(frame)``.
        Larger values zero-pad; smaller values truncate.
    remove_mean : bool, optional
        If ``True`` (default), the per-frame mean is subtracted before
        windowing so a DC offset does not leak into the spectrum.

    Returns
    -------
    freq : numpy.ndarray
        ``rfftfreq(nfft, 1/fs)``, shape ``(nfft//2 + 1,)``.
    amp : numpy.ndarray
        One-sided amplitude, same shape as ``freq``.
    """
    frame = np.asarray(frame, dtype=float)
    n = len(frame)
    if nfft is None or nfft <= 0:
        nfft = n
    nfft = int(nfft)
    if nfft < n:
        work = frame[:nfft].copy()
        n = nfft
    else:
        work = frame.copy()
    if remove_mean:
        work = work - np.mean(work)
    w = get_analysis_window(win, n)
    padded = np.zeros(nfft, dtype=float)
    padded[:n] = work[:n] * w
    fft_r = np.fft.rfft(padded)
    freq = np.fft.rfftfreq(nfft, 1.0 / fs)
    amp = np.abs(fft_r) / n / np.mean(w)
    if amp.size > 2:
        # Double interior bins. For even nfft the last bin is Nyquist
        # and stays single; for odd nfft the last bin is interior and
        # should be doubled.
        if nfft % 2 == 0:
            amp[1:-1] *= 2.0
        else:
            amp[1:] *= 2.0
    elif amp.size == 2:
        # nfft == 1 yields a single bin (DC only); nfft == 2 yields DC
        # and Nyquist — neither is interior, so leave both single.
        pass
    return freq, amp


def infer_nfft_from_freq(freq, *, rfft: bool = False):
    """Recover the FFT length from a computed frequency axis.

    ``compute_fft`` / ``compute_averaged_fft`` return ``nfft // 2`` bins
    (first half of ``fftfreq``). Peak-hold uses :func:`one_sided_amplitude`
    which returns ``rfftfreq`` (``nfft // 2 + 1``). Empty axes yield
    ``None`` — callers must not invent an NFFT.
    """
    n = int(np.asarray(freq).shape[0]) if freq is not None else 0
    if n <= 0:
        return None
    if rfft:
        return int(2 * (n - 1)) if n >= 2 else None
    return int(2 * n)


def _finite_positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number) or number <= 0:
        return None
    return number


def unconstrained_window_nfft(fs, t_win_s, *, floor=64, ceil=8192):
    """NFFT implied by ``fs × t_win_s`` before min-frames / length shrink.

    Used as the "requested" side of the facts card. Returns ``None`` when
    ``fs`` or ``t_win_s`` is missing or non-finite so callers cannot invent
    a sampling rate.
    """
    fs_val = _finite_positive(fs)
    t_win = _finite_positive(t_win_s)
    if fs_val is None or t_win is None:
        return None
    from .adaptive import ceil_pow2

    try:
        nfft = ceil_pow2(fs_val * t_win)
    except ValueError:
        return None
    floor = int(floor)
    ceil = int(ceil)
    return int(min(max(nfft, floor), ceil))


def _fft_frame_count(n_samples, nfft, overlap, avg_mode):
    mode = str(avg_mode or "单帧")
    if mode == "单帧":
        return 1
    n = int(n_samples)
    length = int(nfft)
    if n <= 0 or length <= 0:
        return 1
    hop = int(length * (1.0 - float(overlap)))
    if hop <= 0:
        hop = length // 2
    if hop <= 0:
        hop = 1
    if n < length:
        return 1
    return max((n - length) // hop + 1, 1)


def build_fft_effective_facts(
    sig,
    fs,
    *,
    window,
    nfft,
    avg_mode="单帧",
    overlap=0.0,
    weighting="None",
    nfft_requested=None,
    freq=None,
    time=None,
    min_frames=None,
    nan_count=0,
    is_constant=False,
    time_axis=None,
    fs_conflict=False,
):
    """Construct :class:`FftEffectiveFacts` from a completed compute.

    Does not re-run DSP. ``nfft`` is the value ``compute_*`` actually used
    (pass ``infer_nfft_from_freq(freq)`` when the caller has the axis).
    Empty or non-finite ``fs`` returns ``None`` rather than inventing a
    sampling rate.
    """
    n_samples = int(np.asarray(sig).shape[0]) if sig is not None else 0
    if n_samples <= 0:
        return None
    fs_val = _finite_positive(fs)
    if fs_val is None:
        return None
    mode = str(avg_mode or "单帧")
    inferred = None
    if freq is not None and mode != "单帧":
        inferred = infer_nfft_from_freq(freq, rfft=mode == "峰值保持")
    if inferred is not None:
        nfft_actual = int(inferred)
    elif nfft is None or int(nfft) <= 0:
        nfft_actual = n_samples
    else:
        nfft_actual = int(nfft)
        if mode == "线性平均":
            nfft_actual = min(nfft_actual, n_samples)
    if nfft_actual <= 0:
        return None
    if nfft_requested is None:
        requested = nfft_actual
    else:
        try:
            requested = int(nfft_requested)
        except (TypeError, ValueError):
            requested = nfft_actual
        if requested <= 0:
            requested = nfft_actual
    frames = _fft_frame_count(n_samples, nfft_actual, overlap, avg_mode)
    shortened = nfft_actual < requested
    if (
        min_frames is not None
        and str(avg_mode or "单帧") != "单帧"
        and int(frames) < int(min_frames)
    ):
        shortened = True
    time_start = time_end = None
    if time is not None:
        t_arr = np.asarray(time, dtype=float).reshape(-1)
        finite_t = t_arr[np.isfinite(t_arr)]
        if finite_t.size:
            time_start = float(finite_t[0])
            time_end = float(finite_t[-1])
    return FftEffectiveFacts(
        fs=fs_val,
        nfft_requested=requested,
        nfft=nfft_actual,
        df=fs_val / float(nfft_actual),
        window=str(window or "hanning"),
        window_s=float(nfft_actual) / fs_val,
        frames=int(frames),
        overlap=float(overlap or 0.0),
        n_samples=n_samples,
        weighting=str(weighting or "None"),
        shortened=bool(shortened),
        time_start=time_start,
        time_end=time_end,
        nan_count=int(nan_count or 0),
        is_constant=bool(is_constant),
        time_axis=time_axis,
        fs_conflict=bool(fs_conflict),
    )


@dataclass(frozen=True)
class FftEffectiveFacts:
    """Numerical parameters and measured facts for one completed FFT run."""

    fs: float
    nfft_requested: int
    nfft: int
    df: float
    window: str
    window_s: float
    frames: int
    overlap: float
    n_samples: int
    weighting: str
    shortened: bool
    time_start: float | None = None
    time_end: float | None = None
    nan_count: int = 0
    is_constant: bool = False
    time_axis: dict | None = None
    fs_conflict: bool = False


class FFTAnalyzer:
    """Static methods for FFT, PSD, and averaged-FFT (Welch) computations on time-domain signals.

    Provides ``compute_fft``, ``compute_psd``, ``compute_averaged_fft``,
    and ``get_window`` for spectral analysis. Window construction and
    amplitude normalization are delegated to the module-level
    :func:`get_analysis_window` and :func:`one_sided_amplitude` helpers
    so this class and ``SpectrogramAnalyzer`` cannot drift.
    """

    @staticmethod
    def get_window(name, n):
        """Return the symmetric analysis window — see :func:`get_analysis_window`."""
        return get_analysis_window(name, n)

    @staticmethod
    def compute_fft(sig, fs, win='hanning', nfft=None, weighting='None'):
        """Windowed one-sided FFT amplitude spectrum.

        Preserves the historical contract of returning ``nfft//2`` bins
        (the first half of ``np.fft.fftfreq`` output, dropping the
        Nyquist sample for even ``nfft``). Internally delegates to
        :func:`one_sided_amplitude` so DC/Nyquist scaling matches the
        spectrogram path; the returned slice excludes Nyquist for even
        ``nfft`` regardless.
        """
        sig = np.asarray(sig, dtype=float)
        n = len(sig)
        if nfft is None or nfft <= 0:
            nfft = n
        nfft = int(nfft)
        freq, amp = one_sided_amplitude(sig, fs, win=win, nfft=nfft, remove_mean=True)
        nh = nfft // 2
        freq_out = freq[:nh]
        amp_out = amp[:nh]
        if _validate_weighting(weighting) == 'A':
            amp_out = amp_out * a_weighting_gain_linear(freq_out)
        return freq_out, amp_out

    @staticmethod
    def compute_psd(sig, fs, win='hanning', nfft=None, weighting='None'):
        f, a = FFTAnalyzer.compute_fft(
            sig, fs, win=win, nfft=nfft, weighting=weighting,
        )
        return f, a ** 2

    @staticmethod
    def compute_averaged_fft(
        sig, fs, win='hanning', nfft=1024, overlap=0.5, weighting='None',
    ):
        """Welch-style averaged amplitude spectrum.

        Window construction routes through :func:`get_analysis_window`
        so the shared helper actually owns window construction across
        the module.

        When the signal is shorter than ``nfft`` the effective segment
        length is clamped to ``len(sig)`` (``effective_nfft = min(nfft,
        n)``), matching ``scipy.signal.welch``'s ``nperseg`` behaviour,
        so at least one segment covers the whole signal. The window,
        ``w_sum``, frequency axis, and accumulator are ALL rebuilt from
        ``effective_nfft`` so the returned ``freq``/``amp`` arrays stay
        the same length and self-consistent. A ``UserWarning`` is emitted
        when this clamp changes the requested frequency resolution. For
        ``n >= nfft`` the clamp is a no-op (``effective_nfft == nfft``)
        and the numerical result is byte-for-byte unchanged.
        """
        weighting = _validate_weighting(weighting)
        n = len(sig)
        if n == 0:
            empty = np.array([], dtype=float)
            return empty, empty, empty

        # Clamp the segment length to the signal length so a short signal
        # (n < nfft) still yields a real, covering segment instead of an
        # all-zero spectrum. No-op when n >= nfft.
        effective_nfft = min(nfft, n)
        if effective_nfft < nfft:
            warnings.warn(
                f"signal length {n} < nfft {nfft}; frequency resolution "
                f"clamped to fs/{effective_nfft} (matches scipy.signal.welch).",
                UserWarning,
                stacklevel=2,
            )
        hop = int(effective_nfft * (1 - overlap))
        if hop <= 0:
            hop = effective_nfft // 2
        if hop <= 0:
            hop = 1
        n_segments = max((n - effective_nfft) // hop + 1, 1)

        w = get_analysis_window(win, effective_nfft)
        w_sum = float(np.sum(w))

        half = effective_nfft // 2
        freq = np.fft.fftfreq(effective_nfft, 1 / fs)[:half]
        if half == 0 or w_sum <= 0.0:
            zeros = np.zeros(half, dtype=float)
            return freq, zeros, zeros

        psd_sum = np.zeros(half)

        for i in range(n_segments):
            start = i * hop
            end = start + effective_nfft
            if end > n:
                break
            seg = sig[start:end] - np.mean(sig[start:end])
            fft_r = np.fft.fft(seg * w)
            psd_sum += np.abs(fft_r[:half]) ** 2

        psd = psd_sum / n_segments / (w_sum ** 2) * 2
        amp = np.sqrt(psd)
        if weighting == 'A':
            amp = amp * a_weighting_gain_linear(freq)
            psd = amp ** 2
        return freq, amp, psd

    @staticmethod
    def compute_peak_hold_fft(
        sig, fs, win='hanning', nfft=1024, overlap=0.5, weighting='None',
    ):
        """Per-frequency max amplitude across overlapping FFT segments.

        Wraps :func:`one_sided_amplitude` with a sliding window of length
        ``nfft`` and overlap fraction ``overlap`` (clamped to [0, 0.95)),
        taking the per-bin maximum across segments. Used by the FFT 1D
        ``峰值保持`` averaging mode to preserve transient bursts that a
        Welch (linear-average) view would smooth out.

        When the signal is shorter than ``nfft`` the function falls back
        to a single-frame :func:`one_sided_amplitude` over the whole
        signal so the caller still receives a usable spectrum.

        Naming note (disambiguation from the *other* "peak hold" on the
        rendering side): this is the **compute layer** — it aggregates
        across FFT segments and changes the data itself, producing a
        different (smaller) frequency series than any single segment
        would. Contrast with :func:`mf4_analyzer.signal.envelope.
        build_peak_trace`, the **render layer** peak-hold, which only
        picks one max sample per pixel bucket for display and never
        changes the underlying data. See
        ``docs/lessons-learned/codex-fft-spectrum-peak-hold.md`` for the
        full compute-vs-render writeup.
        """
        weighting = _validate_weighting(weighting)
        sig = np.asarray(sig, dtype=float)
        n = len(sig)
        hop = max(int(nfft * (1 - overlap)), 1)
        n_seg = max((n - nfft) // hop + 1, 1)
        peak = None
        freq = None
        for i in range(n_seg):
            s = i * hop
            if s + nfft > n:
                break
            f, a = one_sided_amplitude(
                sig[s:s + nfft], fs, win=win, nfft=nfft,
            )
            if peak is None:
                peak = a.copy()
                freq = f
            else:
                np.maximum(peak, a, out=peak)
        if peak is None:
            freq, peak = one_sided_amplitude(sig, fs, win=win, nfft=nfft)
        if weighting == 'A':
            peak = peak * a_weighting_gain_linear(freq)
        return freq, peak
