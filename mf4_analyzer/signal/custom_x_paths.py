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

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np


REASON_UNIQUE_PAIR = ""
REASON_EMPTY = "empty"
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
        x=item.x, y=item.y, indices=item.indices, direction=item.direction,
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
    selected_lo, selected_hi = _selection_bounds(x_range)
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
                leg, segment_x, segment_y, selected_lo, selected_hi,
                index_offset=segment.start,
            )
            if clipped is not None:
                contributions.append(clipped)
    major = _major_contributions(contributions)
    public_contributions = tuple(_public_contribution(item) for item in contributions)
    accepted = tuple(_public_contribution(item) for item in major)
    return SeriesPathResult(
        accepted=accepted,
        contributions=public_contributions,
        reason=_classify_reason(accepted, bool(public_contributions)),
    )


__all__ = [
    "PathContribution",
    "REASON_EMPTY",
    "REASON_MULTIPLE_PATHS",
    "REASON_SAME_DIRECTION",
    "REASON_SHORT_SEQUENCE",
    "REASON_UNIDIRECTIONAL",
    "REASON_UNIQUE_PAIR",
    "SeriesPathResult",
    "analyze_custom_x_paths",
]
