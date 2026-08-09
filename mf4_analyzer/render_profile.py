"""Pure raw-signal profiling for time-domain display strategy selection."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, List, Tuple
import zlib

import numpy as np


DENSE_DISCRETE_BUCKET_BUDGET = 350
DENSE_DISCRETE_INTERACTIVE_BUCKET_BUDGET = 250

LOG_FREQUENCY_MIN_TICKS = 2
_LOG_TICK_MANTISSAS_125 = (1.0, 2.0, 5.0)
_LOG_TICK_MANTISSAS_FULL = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
_LOG_TICK_LINEAR_DIVISIONS = 3.0

_PROFILE_SAMPLE_LIMIT = 8192
_PROFILE_SAMPLE_BLOCKS = 8
_REVISION_PROBE_PAIRS = 32
_SMALL_DISCRETE_DOMAIN_MAX = 512
_DENSE_TRANSITION_FRACTION = 0.50


@dataclass(frozen=True)
class RenderProfile:
    """Stable display facts derived once from a channel's raw arrays."""

    source_revision: Any
    source_length: int
    finite_count: int
    monotonic_time: bool
    approx_unique_count: int
    transition_fraction: float
    normalized_step_quantiles: Tuple[float, float, float]
    discrete_small_domain: bool
    strategy: str


def _bounded_blocks(values: np.ndarray):
    """Return dispersed contiguous blocks without phase-aliasing transitions."""
    if values.size <= _PROFILE_SAMPLE_LIMIT:
        return (values,)
    block_size = max(2, _PROFILE_SAMPLE_LIMIT // _PROFILE_SAMPLE_BLOCKS)
    starts = np.linspace(
        0,
        values.size - block_size,
        num=_PROFILE_SAMPLE_BLOCKS,
        dtype=np.int64,
    )
    return tuple(values[int(start):int(start) + block_size] for start in starts)


def _probe_crc32(values) -> int:
    """Fingerprint a few adjacent pairs so in-place changes are observable."""
    arr = np.asarray(values).reshape(-1)
    if arr.size == 0:
        return 0
    if arr.size == 1:
        indices = np.array([0], dtype=np.int64)
    else:
        anchors = np.linspace(
            0,
            arr.size - 2,
            num=min(_REVISION_PROBE_PAIRS, arr.size - 1),
            dtype=np.int64,
        )
        indices = np.unique(np.concatenate((anchors, anchors + 1)))
    try:
        probe = np.ascontiguousarray(arr[indices], dtype=np.float64)
        payload = probe.view(np.uint8)
    except (TypeError, ValueError):
        payload = repr(arr[indices].tolist()).encode("utf-8", errors="replace")
    return int(zlib.crc32(payload))


def source_revision_for(t, values, explicit_revision=None):
    """Return an explicit revision or a low-cost mutation-sensitive fallback."""
    if explicit_revision is not None:
        return ("explicit", explicit_revision)
    t_array = np.asarray(t)
    values_array = np.asarray(values)
    raw_t = t_array.reshape(-1)
    raw_values = values_array.reshape(-1)
    return (
        "probed",
        id(t_array),
        id(values_array),
        int(raw_t.size),
        int(raw_values.size),
        str(raw_t.dtype),
        str(raw_values.dtype),
        _probe_crc32(raw_t),
        _probe_crc32(raw_values),
    )


def classify_render_profile(t, values, source_revision) -> RenderProfile:
    """Classify a channel from raw samples, independently of its label/view."""
    raw_t = np.asarray(t).reshape(-1)
    raw_values = np.asarray(values).reshape(-1)
    source_length = int(raw_values.size)

    if raw_t.size < 2:
        monotonic_time = True
    else:
        try:
            time_values = np.asarray(raw_t, dtype=np.float64)
            monotonic_time = bool(
                np.all(np.isfinite(time_values))
                and np.all(np.diff(time_values) >= 0.0)
            )
        except (TypeError, ValueError):
            monotonic_time = False

    try:
        finite_count = int(np.count_nonzero(np.isfinite(raw_values)))
        numeric_blocks = tuple(
            np.asarray(block, dtype=np.float64)
            for block in _bounded_blocks(raw_values)
        )
    except (TypeError, ValueError):
        finite_count = 0
        numeric_blocks = (np.empty(0, dtype=np.float64),)
    sampled = np.concatenate(numeric_blocks)
    finite = sampled[np.isfinite(sampled)]

    if finite.size:
        approx_unique_count = int(np.unique(finite).size)
        scale = float(np.max(finite) - np.min(finite))
        integer_like = bool(np.all(np.isclose(
            finite, np.rint(finite), rtol=0.0, atol=1e-9,
        )))
    else:
        approx_unique_count = 0
        scale = 0.0
        integer_like = False

    discrete_small_domain = bool(
        integer_like and 1 < approx_unique_count <= _SMALL_DISCRETE_DOMAIN_MAX
    )
    step_blocks = []
    for block in numeric_blocks:
        if block.size < 2:
            continue
        block_finite = np.isfinite(block)
        adjacent_finite = block_finite[:-1] & block_finite[1:]
        step_blocks.append(np.abs(np.diff(block))[adjacent_finite])
    steps = np.concatenate(step_blocks) if step_blocks else np.empty(0, dtype=np.float64)
    if steps.size and scale > 0.0 and np.isfinite(scale):
        normalized = steps / scale
        transition_fraction = float(np.mean(steps > max(scale * 1e-12, 1e-12)))
        quantiles = tuple(float(v) for v in np.quantile(normalized, (0.50, 0.75, 0.90)))
    else:
        transition_fraction = 0.0
        quantiles = (0.0, 0.0, 0.0)

    strategy = (
        "dense_discrete"
        if monotonic_time
        and discrete_small_domain
        and transition_fraction >= _DENSE_TRANSITION_FRACTION
        else "general"
    )
    return RenderProfile(
        source_revision=source_revision,
        source_length=source_length,
        finite_count=finite_count,
        monotonic_time=monotonic_time,
        approx_unique_count=approx_unique_count,
        transition_fraction=transition_fraction,
        normalized_step_quantiles=quantiles,
        discrete_small_domain=discrete_small_domain,
        strategy=strategy,
    )


def bucket_width_for(
    profile: RenderProfile,
    mode: str,
    pixel_width: int,
    interactive: bool,
) -> int:
    """Choose bucket width before envelope generation for one render state."""
    del mode
    try:
        width = max(1, int(pixel_width))
    except (TypeError, ValueError):
        width = 1
    if profile.strategy == "dense_discrete":
        budget = (
            DENSE_DISCRETE_INTERACTIVE_BUCKET_BUDGET
            if interactive else DENSE_DISCRETE_BUCKET_BUDGET
        )
        return min(width, budget)
    return width


def envelope_ink_dev_px(env_s, *, y_span, row_height_px, dpr) -> float:
    """Return the device-pixel vertical "ink" an envelope will paint this
    frame::

        ink_dev_px = Σ min(|Δy_i|, y_span) / y_span × row_height_px × dpr

    ``Δy`` is the pairwise diff of adjacent samples in ``env_s`` (the
    min/max-pair envelope output). A pair is skipped — contributing 0, not
    NaN — when either side is non-finite, so one NaN break in the trace
    never contaminates its finite neighbors. Each step's magnitude is
    clipped to ``y_span`` before summing: a single full-height vertical
    stroke can only ever contribute ``row_height_px × dpr`` of ink, never
    whatever part of it would have fallen outside the visible row.

    ``y_span`` is a defensive sentinel (mirrors the retired
    ``_is_y_overflow_wall`` guard's degenerate-input policy): non-finite or
    ``<= 0`` returns ``0.0`` rather than dividing by a collapsed/garbage
    window. Vectorized (masked diff + clip + sum) — no Python-level loop.
    """
    try:
        ys = float(y_span)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(ys) or ys <= 0.0:
        return 0.0
    arr = np.asarray(env_s, dtype=np.float64).reshape(-1)
    if arr.size < 2:
        return 0.0
    finite = np.isfinite(arr)
    pair_finite = finite[:-1] & finite[1:]
    deltas = np.where(pair_finite, np.abs(np.diff(arr)), 0.0)
    clipped = np.minimum(deltas, ys)
    total = float(np.sum(clipped))
    return total / ys * float(row_height_px) * float(dpr)


def _hz_tick_label(value: float) -> str:
    return f"{value:g}"


def _mantissa_ticks(
    lo_log: float, hi_log: float, mantissas: Tuple[float, ...],
) -> List[Tuple[float, str]]:
    """Return ``mantissa × 10**power`` rungs whose log10 falls in the window.

    The decade sweep is widened by one on both ends so a rung sitting exactly
    on a boundary is never lost to floating-point drift in ``floor``/``ceil``.
    """
    ticks: List[Tuple[float, str]] = []
    first_power = int(math.floor(lo_log)) - 1
    last_power = int(math.ceil(hi_log)) + 1
    for power in range(first_power, last_power + 1):
        decade = 10.0 ** power
        for mantissa in mantissas:
            value = mantissa * decade
            if value <= 0.0 or not math.isfinite(value):
                continue
            coordinate = math.log10(value)
            if lo_log <= coordinate <= hi_log:
                ticks.append((coordinate, _hz_tick_label(value)))
    ticks.sort(key=lambda item: item[0])
    return ticks


def _nice_step_at_or_below(value: float) -> float:
    """Largest ``{1, 2, 5} × 10**k`` step not exceeding ``value``."""
    if not math.isfinite(value) or value <= 0.0:
        return 0.0
    base = 10.0 ** math.floor(math.log10(value))
    for mantissa in (5.0, 2.0, 1.0):
        if mantissa * base <= value:
            return mantissa * base
    # log10 rounding put ``base`` above ``value``; drop a decade rather than
    # returning a step the caller cannot subdivide with.
    return base / 10.0


def _linear_hz_ticks(lo_log: float, hi_log: float) -> List[Tuple[float, str]]:
    """Nice round Hz values for a window narrower than one mantissa rung."""
    lo_hz, hi_hz = 10.0 ** lo_log, 10.0 ** hi_log
    span = hi_hz - lo_hz
    if not math.isfinite(span) or span <= 0.0:
        return []
    step = _nice_step_at_or_below(span / _LOG_TICK_LINEAR_DIVISIONS)
    if step <= 0.0:
        return []
    first_index = math.ceil(lo_hz / step)
    last_index = math.floor(hi_hz / step)
    ticks: List[Tuple[float, str]] = []
    for index in range(int(first_index), int(last_index) + 1):
        value = index * step
        if value <= 0.0:
            continue
        ticks.append((math.log10(value), _hz_tick_label(value)))
    return ticks


def log_frequency_tick_levels(
    lo_log: float, hi_log: float,
) -> List[Tuple[float, str]]:
    """Return major ticks for a log10 frequency axis as ``(coord, Hz label)``.

    ``lo_log``/``hi_log`` are the *view range in log10 space* (pyqtgraph's
    coordinate system once ``setLogMode(x=True)`` is on); the labels are the
    physical Hz values those coordinates stand for, which is the product
    contract on both the interactive canvas and the batch report.

    Pinning decade powers alone — the original rule — returns nothing at all
    once the view sits between two integer powers of ten (a 20..80 Hz zoom, or
    a narrow-band export), which drew a frequency axis with no labels. The
    ladder therefore degrades in three steps:

    1. two or more decade integers in view -> decade powers only, keeping the
       deliberately sparse ``10 / 100 / 1000`` row;
    2. fewer than two -> ``1-2-5`` mantissa rungs (``…10, 20, 50, 100…``);
    3. still fewer than two -> full ``1..9`` mantissa rungs, and finally nice
       round Hz values on a linear step for windows narrower than one rung.

    Any finite window with ``hi_log > lo_log`` therefore yields at least
    ``LOG_FREQUENCY_MIN_TICKS`` ticks. Degenerate input (non-finite, or an
    empty/inverted range) returns ``[]`` so the caller can keep the axis's
    existing ticks instead of aborting a paint.

    Density is intentionally *not* pixel-aware: ``setTicks`` is a hard
    specification that pyqtgraph will not thin, so the ladder is capped by
    construction — a sub-decade window yields at most five or six labels.
    """
    try:
        lo = float(lo_log)
        hi = float(hi_log)
    except (TypeError, ValueError):
        return []
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return []

    decades = range(math.ceil(lo), math.floor(hi) + 1)
    decade_ticks = [
        (float(power), _hz_tick_label(10.0 ** power)) for power in decades
    ]
    if len(decade_ticks) >= LOG_FREQUENCY_MIN_TICKS:
        return decade_ticks

    for mantissas in (_LOG_TICK_MANTISSAS_125, _LOG_TICK_MANTISSAS_FULL):
        ticks = _mantissa_ticks(lo, hi, mantissas)
        if len(ticks) >= LOG_FREQUENCY_MIN_TICKS:
            return ticks

    ticks = _linear_hz_ticks(lo, hi)
    if len(ticks) >= LOG_FREQUENCY_MIN_TICKS:
        return ticks
    # Sub-resolution window: label the edges rather than hand back a blank
    # axis. Unreachable for any range a user can actually zoom to.
    return [
        (lo, _hz_tick_label(10.0 ** lo)),
        (hi, _hz_tick_label(10.0 ** hi)),
    ]


def log_frequency_minor_tick_levels(
    lo_log: float, hi_log: float, major_coords=(),
) -> List[float]:
    """Return unlabelled 2..9 log-decade ticks within a log10 view range.

    The caller supplies the already-selected major coordinates so a narrow
    view's fallback labels (for example 20 and 50 Hz) never get duplicated as
    minor marks. Returned values are pyqtgraph log-space coordinates, not Hz.
    """
    try:
        lo = float(lo_log)
        hi = float(hi_log)
    except (TypeError, ValueError):
        return []
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return []
    major = set()
    for item in major_coords or ():
        value = item[0] if isinstance(item, (tuple, list)) else item
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            major.add(round(value, 12))
    ticks = []
    for power in range(int(math.floor(lo)) - 1, int(math.ceil(hi)) + 2):
        for mantissa in range(2, 10):
            coord = math.log10(float(mantissa)) + power
            if lo <= coord <= hi and round(coord, 12) not in major:
                ticks.append(coord)
    return ticks


__all__ = [
    "DENSE_DISCRETE_BUCKET_BUDGET",
    "DENSE_DISCRETE_INTERACTIVE_BUCKET_BUDGET",
    "LOG_FREQUENCY_MIN_TICKS",
    "RenderProfile",
    "bucket_width_for",
    "classify_render_profile",
    "envelope_ink_dev_px",
    "log_frequency_tick_levels",
    "log_frequency_minor_tick_levels",
    "source_revision_for",
]
