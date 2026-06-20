"""Frequency weighting helpers for relative spectrum amplitudes.

The A-weighting functions here return relative multipliers for spectral
amplitudes and relative dBFS(A)-style displays. They do not convert to
sound-pressure level and do not imply any dB SPL calibration.
"""
from __future__ import annotations

import numpy as np


_F1 = 20.598997
_F2 = 107.65265
_F3 = 737.86223
_F4 = 12194.217


def _ra_positive(freqs: np.ndarray) -> np.ndarray:
    f2 = freqs * freqs
    numerator = (_F4 ** 2) * (f2 ** 2)
    denominator = (
        (f2 + _F1 ** 2)
        * np.sqrt((f2 + _F2 ** 2) * (f2 + _F3 ** 2))
        * (f2 + _F4 ** 2)
    )
    return numerator / denominator


_RA_1000 = float(_ra_positive(np.array([1000.0], dtype=float))[0])


def a_weighting_gain_linear(freqs):
    """Return the IEC 61672-1 A-weighting linear amplitude gain.

    The gain is normalized as ``R_A(f) / R_A(1000 Hz)`` so 1 kHz is
    exactly 1. Frequencies ``<= 0`` return 0. Scalar and array inputs
    return NumPy values with matching shape.
    """
    arr = np.asarray(freqs, dtype=float)
    out = np.zeros(arr.shape, dtype=float)
    mask = arr > 0.0
    if np.any(mask):
        out[mask] = _ra_positive(arr[mask]) / _RA_1000
    return out


def a_weighting_gain_db(freqs):
    """Return A-weighting gain in dB, normalized to 0 dB at 1 kHz."""
    linear = a_weighting_gain_linear(freqs)
    out = np.full(linear.shape, -np.inf, dtype=float)
    mask = linear > 0.0
    if np.any(mask):
        out[mask] = 20.0 * np.log10(linear[mask])
    return out


def _validate_weighting(weighting: str) -> str:
    if weighting not in ('None', 'A'):
        raise ValueError("weighting must be 'None' or 'A'")
    return weighting


__all__ = [
    'a_weighting_gain_db',
    'a_weighting_gain_linear',
]
