"""Pure raw-signal profiling for time-domain display strategy selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple
import zlib

import numpy as np


DENSE_DISCRETE_BUCKET_BUDGET = 350
DENSE_DISCRETE_INTERACTIVE_BUCKET_BUDGET = 250

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
    """Classify a channel from raw samples, independently of its label/view.

    The bounded scan is exact for the real 5,727-sample EPS_CRC1 shape and
    keeps profiling cost bounded for large acquisition channels.  A dense
    discrete signal must have a small integer-valued domain and transition on
    at least half of adjacent finite samples; smooth and continuous-noise
    signals therefore stay on the general strategy.
    """
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
    finite_mask = np.isfinite(sampled)
    finite = sampled[finite_mask]

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
        integer_like
        and 1 < approx_unique_count <= _SMALL_DISCRETE_DOMAIN_MAX
    )

    step_blocks = []
    for block in numeric_blocks:
        if block.size < 2:
            continue
        block_finite = np.isfinite(block)
        adjacent_finite = block_finite[:-1] & block_finite[1:]
        step_blocks.append(np.abs(np.diff(block))[adjacent_finite])
    steps = (
        np.concatenate(step_blocks)
        if step_blocks else np.empty(0, dtype=np.float64)
    )
    if steps.size and scale > 0.0 and np.isfinite(scale):
        normalized = steps / scale
        transition_fraction = float(np.mean(steps > max(scale * 1e-12, 1e-12)))
        quantiles = tuple(float(v) for v in np.quantile(
            normalized, (0.50, 0.75, 0.90),
        ))
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
    del mode  # Reserved for mode-specific quality budgets.
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
