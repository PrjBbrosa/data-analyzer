"""Shared analysis default constants and param coercion (no GUI imports).

Product defaults for window candidates, coherence threshold, and overlap
fraction coercion live here so GUI inspectors, batch forms, and DSP helpers
reference one symbol each. Values are frozen declarations only — changing a
number requires an explicit product decision, not a drive-by edit.
"""
from __future__ import annotations

# Majority-order candidate list (flattop at index 5). FFT-vs-Time previously
# listed flattop second; converge to this order so presets/index restore stay
# consistent across sections.
DEFAULT_ANALYSIS_WINDOW = "hanning"
ANALYSIS_WINDOW_CANDIDATES: tuple[str, ...] = (
    "hanning",
    "hamming",
    "blackman",
    "bartlett",
    "kaiser",
    "flattop",
)

DEFAULT_COHERENCE_THRESHOLD = 0.8

# Overlap fraction ceiling shared by Welch / spectrogram / FRF consumers.
OVERLAP_FRACTION_MAX = 0.95


def normalize_overlap_fraction(value, *, default=0.0):
    """Normalize overlap from percent-or-fraction to a fraction in ``[0, 0.95]``.

    Values ``> 1`` are treated as percent (``value / 100``). Call sites that
    persist both ``avg_overlap`` (often percent) and ``overlap`` (often
    fraction) keep those key names for serialization compatibility — this
    helper only unifies the numeric coercion.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        try:
            value = float(default)
        except (TypeError, ValueError):
            value = 0.0
    if value > 1.0:
        value /= 100.0
    return max(0.0, min(OVERLAP_FRACTION_MAX, value))


__all__ = [
    "ANALYSIS_WINDOW_CANDIDATES",
    "DEFAULT_ANALYSIS_WINDOW",
    "DEFAULT_COHERENCE_THRESHOLD",
    "OVERLAP_FRACTION_MAX",
    "normalize_overlap_fraction",
]
