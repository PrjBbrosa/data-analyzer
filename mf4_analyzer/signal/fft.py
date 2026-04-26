"""FFTAnalyzer: windowed FFT with amplitude normalization.

Module-level helpers (``get_analysis_window`` and ``one_sided_amplitude``)
are the single source of truth for window construction and one-sided
amplitude scaling so ``FFTAnalyzer`` and the new
``mf4_analyzer.signal.spectrogram.SpectrogramAnalyzer`` cannot drift.

Window generation delegates to ``scipy.signal.get_window`` with
``fftbins=False`` (symmetric). The app keeps ownership of:

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

import numpy as np
from scipy.signal import get_window as _scipy_get_window


# App-owned alias normalization. Keeps "hann" and "hanning" pointing at
# the same definition so callers can use either spelling.
_WINDOW_ALIASES = {
    'hann': 'hanning',
}


def get_analysis_window(name, n):
    """Return the app's symmetric analysis window of length ``n``.

    Single source of truth for FFT and spectrogram code so both paths
    use identical amplitude normalization. Implementation delegates to
    ``scipy.signal.get_window`` but keeps app ownership of:

      * alias resolution (``hann`` -> ``hanning``);
      * the ``kaiser`` ``beta`` default (14);
      * the symmetric (``fftbins=False``) policy.

    Parameters
    ----------
    name : str
        Window name. Accepted: ``hanning``/``hann``, ``hamming``,
        ``blackman``, ``bartlett``, ``kaiser``, ``flattop``. Any
        unrecognised name is forwarded to ``scipy.signal.get_window``;
        scipy will raise if it is unknown.
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
        spec = ('kaiser', 14)
    elif key == 'hanning':
        # scipy uses 'hann'; map our public 'hanning' to the scipy name.
        spec = 'hann'
    else:
        spec = key
    return _scipy_get_window(spec, n, fftbins=False).astype(float, copy=False)


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
    def compute_fft(sig, fs, win='hanning', nfft=None):
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
        return freq[:nh], amp[:nh]

    @staticmethod
    def compute_psd(sig, fs, win='hanning', nfft=None):
        f, a = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
        return f, a ** 2

    @staticmethod
    def compute_averaged_fft(sig, fs, win='hanning', nfft=1024, overlap=0.5):
        """Welch-style averaged amplitude spectrum.

        Window construction routes through :func:`get_analysis_window`
        so the shared helper actually owns window construction across
        the module.
        """
        n = len(sig)
        hop = int(nfft * (1 - overlap))
        if hop <= 0:
            hop = nfft // 2
        n_segments = max((n - nfft) // hop + 1, 1)

        w = get_analysis_window(win, nfft)
        w_sum = np.sum(w)

        freq = np.fft.fftfreq(nfft, 1 / fs)[:nfft // 2]
        psd_sum = np.zeros(nfft // 2)

        for i in range(n_segments):
            start = i * hop
            end = start + nfft
            if end > n:
                break
            seg = sig[start:end] - np.mean(sig[start:end])
            fft_r = np.fft.fft(seg * w)
            psd_sum += np.abs(fft_r[:nfft // 2]) ** 2

        psd = psd_sum / n_segments / (w_sum ** 2) * 2
        amp = np.sqrt(psd)
        return freq, amp, psd
