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

# Target segment duration (seconds) fed to ``resolve_nfft`` when a spectral
# analysis runs in auto-NFFT mode and no explicit ``t_win_s`` was stored.
# Product default for both FFT (averaged / peak-hold) and FFT-vs-Time; the
# batch FFT-vs-Time resolver previously carried a stray 1.0 here, which made
# batch and GUI resolve different NFFTs for the same recording.
DEFAULT_FFT_T_WIN_S = 1.5

# Frame overlap fraction for FFT-vs-Time when a recipe omits ``overlap``.
# Matches the inspector's first-open 80% (contextual_fft_time.spin_overlap).
# The batch form always emits ``overlap`` and ``normalize_batch_params``
# introduces no defaults, so this fallback is only reachable from hand-made /
# imported recipes and direct API use — aligning it costs nothing for recipes
# that store the field explicitly (their value is preserved verbatim).
DEFAULT_FFT_TIME_OVERLAP = 0.8

# Order resolution (orders/bin) used when a preset omits ``order_res``.
# Matches the single-analysis inspector's shipped spin-box value
# (contextual_order.spin_order_res). Note this is only the OMITTED-key
# fallback: the batch form's own spin box still ships 0.05, and any recipe
# that stores order_res explicitly keeps its value untouched.
DEFAULT_ORDER_RES = 0.1

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
    "DEFAULT_FFT_TIME_OVERLAP",
    "DEFAULT_FFT_T_WIN_S",
    "DEFAULT_ORDER_RES",
    "OVERLAP_FRACTION_MAX",
    "normalize_overlap_fraction",
]
