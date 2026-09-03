"""UI-neutral Custom-X major-path analysis.

Identify physical out-and-back legs on a channel-backed X series. The
calibrated order is: finite acquisition segments, a data-only turn policy
from the complete segment span, raw legs, short-leg merge, then range clip
and major-contribution filtering. Callers must not pass A/B selection into
the turn policy, and must not classify direction from Y, pixels, or a
decimated envelope.

This module is numpy-only. It must not import Qt, ``mf4_analyzer.ui``, or
the batch renderer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Sequence

import numpy as np


REASON_UNIQUE_PAIR = ""
REASON_EMPTY = "empty"
REASON_INCOMPATIBLE_SHAPE = "incompatible_shape"
REASON_SHORT_SEQUENCE = "short_sequence"
REASON_UNIDIRECTIONAL = "unidirectional"
REASON_SAME_DIRECTION = "same_direction"
REASON_MULTIPLE_PATHS = "multiple_paths"


@dataclass(frozen=True)
class PathContribution:
    """One clipped in-range visit of a major or candidate leg."""

    x: np.ndarray
    y: np.ndarray
    indices: np.ndarray
    direction: int
    _minimum_support: int | None = field(default=None, repr=False, compare=False)
    x_min: float = field(init=False)
    x_max: float = field(init=False)
    is_monotonic_oriented: bool = field(init=False)

    def __post_init__(self) -> None:
        x = np.asarray(self.x, dtype=float)
        y = np.asarray(self.y, dtype=float)
        indices = np.asarray(self.indices, dtype=int)
        if x.ndim != 1 or y.ndim != 1 or indices.ndim != 1:
            raise ValueError("path contribution arrays must be one-dimensional")
        if not (x.size == y.size == indices.size):
            raise ValueError("path contribution X/Y/indices must be aligned")
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", y)
        object.__setattr__(self, "indices", indices)
        if x.size:
            x_min = float(np.min(x))
            x_max = float(np.max(x))
        else:
            x_min = math.nan
            x_max = math.nan
        direction = int(self.direction)
        if direction not in (-1, 1) and x.size >= 2:
            delta = float(x[-1]) - float(x[0])
            direction = 1 if delta > 0.0 else -1 if delta < 0.0 else 0
        x_oriented = x[::-1] if direction < 0 else x
        is_monotonic_oriented = bool(
            x_oriented.size >= 2 and not np.any(np.diff(x_oriented) < 0.0)
        )
        object.__setattr__(self, "x_min", x_min)
        object.__setattr__(self, "x_max", x_max)
        object.__setattr__(self, "is_monotonic_oriented", is_monotonic_oriented)

    @property
    def sample_count(self) -> int:
        return int(self.x.size)


@dataclass(frozen=True)
class SeriesPathResult:
    """Per-series Custom-X path plan: accepted majors plus fallback samples."""

    accepted: tuple[PathContribution, ...]
    contributions: tuple[PathContribution, ...]
    reason: str = REASON_UNIQUE_PAIR

    @property
    def unique_pair(self) -> bool:
        return (
            len(self.accepted) == 2
            and self.accepted[0].direction * self.accepted[1].direction < 0
        )


@dataclass(frozen=True)
class CursorBranchValue:
    """The sampled value on one reliably classified physical X branch."""

    direction: int
    value: float


@dataclass(frozen=True)
class CustomXCursorResult:
    """UI-neutral Custom-X single-cursor samples and their diagnostic."""

    values: tuple[CursorBranchValue, ...]
    reason: str


@dataclass(frozen=True)
class _IndexSpan:
    start: int
    stop: int


@dataclass(frozen=True)
class _TurnPolicy:
    turn_distance: float
    min_support: int


@dataclass(frozen=True)
class _MajorLeg:
    start: int
    end: int
    direction: int
    policy: _TurnPolicy | None


@dataclass(frozen=True)
class _RangeContribution:
    x: np.ndarray
    y: np.ndarray
    indices: np.ndarray
    direction: int
    policy: _TurnPolicy | None

    @property
    def sample_count(self) -> int:
        return int(self.x.size)

    @property
    def travel(self) -> float:
        return float(np.ptp(self.x)) if self.x.size else 0.0


def _acquisition_segments(x: np.ndarray, y: np.ndarray) -> tuple[_IndexSpan, ...]:
    """Split finite samples without joining across acquisition gaps."""
    finite = np.isfinite(x) & np.isfinite(y)
    spans: list[_IndexSpan] = []
    start: int | None = None
    for index, present in enumerate(finite):
        if present and start is None:
            start = index
        elif not present and start is not None:
            spans.append(_IndexSpan(start, index))
            start = None
    if start is not None:
        spans.append(_IndexSpan(start, int(x.size)))
    return tuple(spans)


def _turn_policy(x: np.ndarray) -> _TurnPolicy | None:
    """Derive a reversal threshold from the complete acquisition segment.

    The threshold is a property of the segment's own data span. It must not
    take a statistics/cursor A/B range.
    """
    steps = np.abs(np.diff(x))
    steps = steps[np.isfinite(steps) & (steps > 0.0)]
    data_span = float(np.ptp(x)) if x.size else 0.0
    if not steps.size or not np.isfinite(data_span) or data_span <= 0.0:
        return None
    q50 = float(np.median(steps))
    q95 = float(np.percentile(steps, 95))
    turn_distance = min(
        max(4.0 * q95, 0.005 * data_span),
        0.10 * data_span,
    )
    min_support = int(min(64, max(3, math.ceil(turn_distance / max(q50, 1e-12)))))
    return _TurnPolicy(turn_distance=turn_distance, min_support=min_support)


def _raw_legs(x: np.ndarray, policy: _TurnPolicy) -> list[list[int]]:
    """Confirm turns from sustained displacement, not adjacent dx signs."""
    if not x.size:
        return []
    legs: list[list[int]] = []
    start = 0
    direction = 0
    extremum_index = 0
    extremum_value = float(x[0])
    reversal_samples = 0
    for index in range(1, int(x.size)):
        value = float(x[index])
        if direction == 0:
            if value != extremum_value:
                direction = 1 if value > extremum_value else -1
                extremum_index = index
                extremum_value = value
                reversal_samples = 0
            continue
        if direction * (value - extremum_value) > 0.0:
            extremum_index = index
            extremum_value = value
            reversal_samples = 0
            continue
        reversal_samples += 1
        if (
            direction * (extremum_value - value) >= policy.turn_distance
            and reversal_samples >= policy.min_support
        ):
            legs.append([start, extremum_index, direction])
            start = extremum_index
            direction = -direction
            extremum_index = index
            extremum_value = value
            reversal_samples = 0
    legs.append([start, int(x.size) - 1, direction])
    return legs


def _merge_short_legs(
    legs: list[list[int]], x: np.ndarray, policy: _TurnPolicy,
) -> tuple[_MajorLeg, ...]:
    """Iteratively absorb incomplete lead-in, tail, and turn residues."""
    changed = True
    while changed and len(legs) > 1:
        changed = False
        for index, (start, end, _direction) in enumerate(tuple(legs)):
            if abs(float(x[end]) - float(x[start])) >= policy.turn_distance:
                continue
            if (
                0 < index < len(legs) - 1
                and legs[index - 1][2] == legs[index + 1][2]
            ):
                legs[index - 1][1] = legs[index + 1][1]
                del legs[index:index + 2]
            elif index == 0:
                legs[1][0] = legs[0][0]
                del legs[0]
            else:
                legs[index - 1][1] = legs[index][1]
                del legs[index]
            changed = True
            break
    merged = []
    for start, end, _direction in legs:
        delta = float(x[end]) - float(x[start])
        direction = 1 if delta > 0.0 else -1 if delta < 0.0 else 0
        merged.append(_MajorLeg(start, end, direction, policy))
    return tuple(merged)


def _clip_major_leg(
    leg: _MajorLeg,
    x: np.ndarray,
    y: np.ndarray,
    lo: float | None,
    hi: float | None,
    *,
    index_offset: int = 0,
) -> _RangeContribution | None:
    sl = slice(leg.start, leg.end + 1)
    leg_x = x[sl]
    leg_y = y[sl]
    indices = np.arange(leg.start, leg.end + 1, dtype=int) + int(index_offset)
    if lo is not None and hi is not None:
        selected = (leg_x >= lo) & (leg_x <= hi)
        leg_x, leg_y, indices = leg_x[selected], leg_y[selected], indices[selected]
    if not leg_x.size:
        return None
    return _RangeContribution(leg_x, leg_y, indices, leg.direction, leg.policy)


def _major_contributions(
    contributions: Sequence[_RangeContribution],
) -> tuple[_RangeContribution, ...]:
    """Keep only range visits that have enough support to be physical paths."""
    if not contributions:
        return ()
    maximum_travel = max(item.travel for item in contributions)
    travel_floor = 0.5 * maximum_travel
    return tuple(
        item for item in contributions
        if (
            item.policy is not None
            and item.sample_count >= item.policy.min_support
            and item.travel >= travel_floor
        )
    )


def _public_contribution(item: _RangeContribution) -> PathContribution:
    return PathContribution(
        x=item.x,
        y=item.y,
        indices=item.indices,
        direction=item.direction,
        _minimum_support=(
            None if item.policy is None else int(item.policy.min_support)
        ),
    )


def _classify_reason(accepted: tuple[PathContribution, ...], has_fallback: bool) -> str:
    if len(accepted) == 2 and accepted[0].direction * accepted[1].direction < 0:
        return REASON_UNIQUE_PAIR
    if len(accepted) >= 3:
        return REASON_MULTIPLE_PATHS
    if len(accepted) == 2:
        return REASON_SAME_DIRECTION
    if len(accepted) == 1:
        return REASON_UNIDIRECTIONAL
    if has_fallback:
        return REASON_SHORT_SEQUENCE
    return REASON_EMPTY


def _selection_bounds(
    x_range: tuple[float, float] | None,
) -> tuple[float | None, float | None]:
    if x_range is None:
        return None, None
    lo, hi = x_range
    return float(lo), float(hi)


def _clip_path_contribution(
    contribution: PathContribution,
    lo: float,
    hi: float,
) -> PathContribution | None:
    selected = (contribution.x >= lo) & (contribution.x <= hi)
    if not np.any(selected):
        return None
    return PathContribution(
        x=contribution.x[selected],
        y=contribution.y[selected],
        indices=contribution.indices[selected],
        direction=contribution.direction,
        _minimum_support=contribution._minimum_support,
    )


def _public_major_contributions(
    contributions: Sequence[PathContribution],
) -> tuple[PathContribution, ...]:
    """Apply the analysis-time major-leg policy after range clipping."""
    if not contributions:
        return ()
    maximum_travel = max(item.x_max - item.x_min for item in contributions)
    travel_floor = 0.5 * maximum_travel
    return tuple(
        item for item in contributions
        if (
            item._minimum_support is not None
            and item.sample_count >= item._minimum_support
            and item.x_max - item.x_min >= travel_floor
        )
    )


def clip_paths(
    paths: SeriesPathResult,
    x_range: tuple[float, float] | None,
) -> SeriesPathResult:
    """Clip an already-analyzed Custom-X plan without reclassifying its legs.

    Leg recognition and its turn policy are properties of the full finite
    acquisition segments.  Only contribution membership and the existing
    major-leg threshold vary with the cursor A/B range.
    """
    lo, hi = _selection_bounds(x_range)
    if lo is None or hi is None:
        return paths
    contributions = tuple(
        clipped
        for item in paths.contributions
        if (clipped := _clip_path_contribution(item, lo, hi)) is not None
    )
    accepted = _public_major_contributions(contributions)
    return SeriesPathResult(
        accepted=accepted,
        contributions=contributions,
        reason=_classify_reason(accepted, bool(contributions)),
    )


def analyze_custom_x_paths(
    x,
    y,
    x_range: tuple[float, float] | None = None,
) -> SeriesPathResult:
    """Plan Custom-X major paths for one aligned ``(x, y)`` series.

    ``x_range`` clips contributions after legs are confirmed on the complete
    finite acquisition segments. It is never used to derive the turn policy.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size:
        raise ValueError("custom-X path X/Y must be aligned one-dimensional arrays")
    contributions: list[_RangeContribution] = []
    for segment in _acquisition_segments(x, y):
        segment_x = x[segment.start:segment.stop]
        segment_y = y[segment.start:segment.stop]
        policy = _turn_policy(segment_x)
        if policy is None:
            legs = (_MajorLeg(0, int(segment_x.size) - 1, 0, None),)
        else:
            legs = _merge_short_legs(_raw_legs(segment_x, policy), segment_x, policy)
        for leg in legs:
            clipped = _clip_major_leg(
                leg, segment_x, segment_y, None, None,
                index_offset=segment.start,
            )
            if clipped is not None:
                contributions.append(clipped)
    major = _major_contributions(contributions)
    public_contributions = tuple(_public_contribution(item) for item in contributions)
    accepted = tuple(_public_contribution(item) for item in major)
    paths = SeriesPathResult(
        accepted=accepted,
        contributions=public_contributions,
        reason=_classify_reason(accepted, bool(public_contributions)),
    )
    return clip_paths(paths, x_range)


def _leg_search_direction(contribution: PathContribution) -> int:
    """Return +1 / -1 for search order, or 0 when the leg has no span."""
    direction = int(contribution.direction)
    if direction in (-1, 1):
        return direction
    x = contribution.x
    if x.size < 2:
        return 0
    delta = float(x[-1]) - float(x[0])
    if delta > 0.0:
        return 1
    if delta < 0.0:
        return -1
    return 0


def _interpolate_sorted_neighbors(
    x_mono: np.ndarray,
    y_mono: np.ndarray,
    x_value: float,
) -> float | None:
    """Linear interpolate ``x_value`` on a non-decreasing ``x_mono``."""
    idx = int(np.searchsorted(x_mono, x_value, side="left"))
    if idx <= 0 or idx >= int(x_mono.size):
        return None
    left_x = float(x_mono[idx - 1])
    right_x = float(x_mono[idx])
    if left_x == right_x:
        return None
    fraction = (x_value - left_x) / (right_x - left_x)
    value = float(y_mono[idx - 1]) + fraction * (
        float(y_mono[idx]) - float(y_mono[idx - 1])
    )
    return value if math.isfinite(value) else None


def _interpolate_first_bracket(
    x: np.ndarray,
    y: np.ndarray,
    x_value: float,
) -> float | None:
    """First containing segment in acquisition order (old-loop equivalent)."""
    left_x = x[:-1]
    right_x = x[1:]
    lo = np.minimum(left_x, right_x)
    hi = np.maximum(left_x, right_x)
    hit = (left_x != right_x) & (lo <= x_value) & (x_value <= hi)
    indices = np.flatnonzero(hit)
    if not indices.size:
        return None
    index = int(indices[0])
    lx = float(left_x[index])
    rx = float(right_x[index])
    fraction = (x_value - lx) / (rx - lx)
    value = float(y[index]) + fraction * (float(y[index + 1]) - float(y[index]))
    return value if math.isfinite(value) else None


def _sample_path_contribution(
    contribution: PathContribution,
    x_value: float,
) -> float | None:
    """Interpolate one physical leg with ``searchsorted`` on a monotonic view.

    Descending legs are reversed first so the search runs on non-decreasing
    X. Exact ``x == x_value`` still returns the first acquired Y. Out of
    range, empty, and non-finite interpolated Y still return ``None``.
    Quantisation chatter can make a directional leg non-monotonic; those
    visits keep the acquisition-order first-bracket rule so sampling stays
    pointwise equivalent to the retired Python loop.
    """
    x = contribution.x
    y = contribution.y
    if not x.size or x_value < contribution.x_min or x_value > contribution.x_max:
        return None
    exact = np.flatnonzero(x == x_value)
    if exact.size:
        return float(y[int(exact[0])])
    direction = _leg_search_direction(contribution)
    if direction < 0:
        x_mono = x[::-1]
        y_mono = y[::-1]
    else:
        x_mono = x
        y_mono = y
    if contribution.is_monotonic_oriented:
        return _interpolate_sorted_neighbors(x_mono, y_mono, x_value)
    return _interpolate_first_bracket(x, y, x_value)


def sample_custom_x_cursor_from_paths(
    paths: SeriesPathResult,
    x_value,
) -> CustomXCursorResult:
    """Sample a selected X on already-analyzed major paths.

    Callers that cache ``analyze_custom_x_paths`` should use this instead of
    re-running the one-shot ``sample_custom_x_cursor`` on every cursor move.
    """
    try:
        selected_x = float(x_value)
    except (TypeError, ValueError):
        return CustomXCursorResult((), REASON_EMPTY)
    if not math.isfinite(selected_x):
        return CustomXCursorResult((), REASON_EMPTY)
    if paths.reason not in (REASON_UNIQUE_PAIR, REASON_UNIDIRECTIONAL):
        return CustomXCursorResult((), paths.reason)

    accepted = tuple(sorted(
        paths.accepted,
        key=lambda item: 0 if item.direction > 0 else 1,
    ))
    values = tuple(
        CursorBranchValue(direction=item.direction, value=value)
        for item in accepted
        if (value := _sample_path_contribution(item, selected_x)) is not None
    )
    if not values:
        return CustomXCursorResult((), REASON_EMPTY)
    return CustomXCursorResult(values, paths.reason)


def sample_custom_x_cursor(
    x: np.ndarray,
    y: np.ndarray,
    x_value: float,
) -> CustomXCursorResult:
    """Sample a selected Custom-X coordinate on each reliable physical leg.

    The shared path analyzer owns finite segmentation, turn tolerance, and
    major-leg classification.  Sampling deliberately retains each accepted
    leg's acquisition order, so rising and falling visits are never merged or
    interpolated as one non-monotonic series.
    """
    try:
        x_array = np.asarray(x, dtype=float)
        y_array = np.asarray(y, dtype=float)
    except (TypeError, ValueError):
        return CustomXCursorResult((), REASON_INCOMPATIBLE_SHAPE)
    if x_array.ndim != 1 or y_array.ndim != 1 or x_array.size != y_array.size:
        return CustomXCursorResult((), REASON_INCOMPATIBLE_SHAPE)
    try:
        selected_x = float(x_value)
    except (TypeError, ValueError):
        return CustomXCursorResult((), REASON_EMPTY)
    if not math.isfinite(selected_x):
        return CustomXCursorResult((), REASON_EMPTY)

    paths = analyze_custom_x_paths(x_array, y_array)
    return sample_custom_x_cursor_from_paths(paths, selected_x)


def sample_custom_x_dual_delta_from_paths(
    paths: SeriesPathResult,
    x_a,
    x_b,
) -> tuple[tuple[int, float | None], ...]:
    """Per-accepted-leg Δ = Y(B) − Y(A) using the single-cursor interpolator.

    Each accepted physical stroke is sampled independently at A and at B.
    Either end outside that stroke, or a non-finite interpolated Y, yields
    ``None`` for that leg. Deltas are never computed across different legs.
    """
    a_result = sample_custom_x_cursor_from_paths(paths, x_a)
    b_result = sample_custom_x_cursor_from_paths(paths, x_b)
    a_by_dir = {item.direction: item.value for item in a_result.values}
    b_by_dir = {item.direction: item.value for item in b_result.values}
    deltas = []
    for contrib in paths.accepted:
        direction = int(contrib.direction)
        y_a = a_by_dir.get(direction)
        y_b = b_by_dir.get(direction)
        if y_a is None or y_b is None:
            deltas.append((direction, None))
            continue
        try:
            delta = float(y_b) - float(y_a)
        except (TypeError, ValueError):
            deltas.append((direction, None))
            continue
        deltas.append((direction, delta if math.isfinite(delta) else None))
    return tuple(deltas)


__all__ = [
    "CursorBranchValue",
    "CustomXCursorResult",
    "PathContribution",
    "REASON_EMPTY",
    "REASON_INCOMPATIBLE_SHAPE",
    "REASON_MULTIPLE_PATHS",
    "REASON_SAME_DIRECTION",
    "REASON_SHORT_SEQUENCE",
    "REASON_UNIDIRECTIONAL",
    "REASON_UNIQUE_PAIR",
    "SeriesPathResult",
    "analyze_custom_x_paths",
    "clip_paths",
    "sample_custom_x_cursor",
    "sample_custom_x_cursor_from_paths",
    "sample_custom_x_dual_delta_from_paths",
]
