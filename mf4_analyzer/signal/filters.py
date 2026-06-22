"""Pure-numpy FFT-domain filtering (low/high/band/bandstop), zero-phase, no
scipy. See docs/superpowers/specs/2026-06-22-timedomain-filter-overlay-design.md.

Why FFT-domain not IIR: pure-numpy sosfilt over 1M+ samples × many channels is
seconds-slow; FFT-domain is O(N log N) C-backed (numpy.fft) → ms, numerically
robust (no poles/stability), and zero-phase by construction (real even mask).
"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class FilterSpec:
    kind: str            # 'low' | 'high' | 'band' | 'bandstop'
    order: int = 4
    cutoff: float = 0.0       # low/high (Hz)
    cutoff_lo: float = 0.0    # band/bandstop (Hz)
    cutoff_hi: float = 0.0    # band/bandstop (Hz)


def _lp_mag(f, fc, n):
    if fc <= 0:
        return np.zeros_like(f)
    return 1.0 / np.sqrt(1.0 + (f / fc) ** (2 * n))


def _hp_mag(f, fc, n):
    m = np.zeros_like(f)
    pos = f > 0
    m[pos] = 1.0 / np.sqrt(1.0 + (fc / f[pos]) ** (2 * n))
    return m


def butter_magnitude(freqs, spec):
    """Real, non-negative Butterworth-shaped magnitude mask. `freqs` in Hz."""
    f = np.abs(np.asarray(freqs, dtype=float))
    n = int(spec.order)
    if spec.kind == 'low':
        return _lp_mag(f, float(spec.cutoff), n)
    if spec.kind == 'high':
        return _hp_mag(f, float(spec.cutoff), n)
    if spec.kind == 'band':
        return _hp_mag(f, float(spec.cutoff_lo), n) * _lp_mag(f, float(spec.cutoff_hi), n)
    if spec.kind == 'bandstop':
        band = _hp_mag(f, float(spec.cutoff_lo), n) * _lp_mag(f, float(spec.cutoff_hi), n)
        return 1.0 - band
    raise ValueError(f"unknown filter kind: {spec.kind!r}")


def nyquist_guard(spec, fs):
    """Clamp cutoffs into (0, nyquist). Returns (clamped_spec, message|None).
    Raises ValueError if band lo >= hi."""
    nyq = 0.5 * float(fs)
    eps = nyq * 1e-3

    def clamp(v):
        return min(max(float(v), eps), nyq - eps)

    if spec.kind in ('low', 'high'):
        c = clamp(spec.cutoff)
        msg = None if c == spec.cutoff else f"截止频率超出范围，已钳制到 {c:.3g} Hz"
        return FilterSpec(spec.kind, spec.order, cutoff=c), msg

    if float(spec.cutoff_lo) >= float(spec.cutoff_hi):
        raise ValueError("带通/带阻：下限必须小于上限")
    lo, hi = clamp(spec.cutoff_lo), clamp(spec.cutoff_hi)
    msg = (None if (lo, hi) == (spec.cutoff_lo, spec.cutoff_hi)
           else f"截止频率超出范围，已钳制到 {lo:.3g}–{hi:.3g} Hz")
    return FilterSpec(spec.kind, spec.order, cutoff_lo=lo, cutoff_hi=hi), msg


def apply(sig, spec, fs):
    """Zero-phase FFT-domain filter. Output same length as `sig`. NaN positions
    in the input are interpolated for filtering, then restored as NaN."""
    x = np.asarray(sig, dtype=float)
    n0 = x.size
    if n0 < 4 or float(fs) <= 0:
        return x.copy()

    nan_mask = ~np.isfinite(x)
    if nan_mask.all():
        return x.copy()
    xf = x.copy()
    if nan_mask.any():
        idx = np.arange(n0)
        xf[nan_mask] = np.interp(idx[nan_mask], idx[~nan_mask], x[~nan_mask])

    # odd-reflection pad to soften circular-convolution edge wrap
    pad = min(n0 - 1, max(16, n0 // 10))
    left = 2 * xf[0] - xf[pad:0:-1]
    right = 2 * xf[-1] - xf[-2:-pad - 2:-1]
    xp = np.concatenate([left, xf, right])
    N = xp.size

    freqs = np.fft.rfftfreq(N, d=1.0 / float(fs))
    mask = butter_magnitude(freqs, spec)
    yp = np.fft.irfft(np.fft.rfft(xp) * mask, n=N)
    y = yp[pad:pad + n0]

    if nan_mask.any():
        y[nan_mask] = np.nan
    return y
