"""Spectrum peak-trace reuse plan (revision / coverage / density).

The canvas owns Qt curves and PreparedLineRange queries. This module only
decides whether a stored coverage window can be reused for a new target.
"""
from __future__ import annotations

from dataclasses import dataclass


# First-round overscan: half a visible span on each side, then clip to data.
# Keep this small: extra drawn points feed the AA gate as-is.
OVERSCAN_FRACTION = 0.5


@dataclass(frozen=True)
class SpectrumCurveIndex:
    """Inclusive source slice, including adjacent peak/NaN legs."""

    first: int
    last: int
    fully_covered: bool
    break_key: tuple


@dataclass(frozen=True)
class SpectrumDisplayRequest:
    revision: int
    identities: tuple
    target_lo: float
    target_hi: float
    pixel_width: int
    curves: tuple
    data_lo: float | None
    data_hi: float | None


@dataclass(frozen=True)
class SpectrumTraceCache:
    """One current coverage window per canvas, not an LRU of viewports."""

    revision: int
    identities: tuple
    cover_lo: float
    cover_hi: float
    bucket_width: int
    pixel_width: int
    curves: tuple
    fully_covered: bool


@dataclass(frozen=True)
class SpectrumDisplayPlan:
    reuse: bool
    cover_lo: float
    cover_hi: float
    bucket_width: int
    reason: str


def _ascending(lo: float, hi: float) -> tuple[float, float]:
    lo = float(lo)
    hi = float(hi)
    if hi < lo:
        return hi, lo
    return lo, hi


def clip_overscan_cover(
    target_lo: float,
    target_hi: float,
    data_lo: float | None,
    data_hi: float | None,
    *,
    fraction: float = OVERSCAN_FRACTION,
) -> tuple[float, float]:
    lo, hi = _ascending(target_lo, target_hi)
    span = hi - lo
    if span > 0.0 and fraction > 0.0:
        pad = fraction * span
        lo -= pad
        hi += pad
    if data_lo is not None and lo < data_lo:
        lo = float(data_lo)
    if data_hi is not None and hi > data_hi:
        hi = float(data_hi)
    if hi < lo:
        return _ascending(target_lo, target_hi)
    return lo, hi


def bucket_width_for_cover(
    pixel_width: int,
    cover_lo: float,
    cover_hi: float,
    target_lo: float,
    target_hi: float,
) -> int:
    """Scale peak-trace buckets with cached span vs viewport.

    A ~2x cover must not be packed into one viewport of buckets.
    """
    width = max(1, int(pixel_width))
    cover_span = float(cover_hi) - float(cover_lo)
    view_span = float(target_hi) - float(target_lo)
    if cover_span <= 0.0 or view_span <= 0.0:
        return width
    scaled = int(round(width * cover_span / view_span))
    return max(width, scaled)


def rebuild_cover_plan(request: SpectrumDisplayRequest) -> tuple[float, float, int]:
    target_lo, target_hi = _ascending(request.target_lo, request.target_hi)
    cover_lo, cover_hi = clip_overscan_cover(
        target_lo, target_hi, request.data_lo, request.data_hi,
    )
    buckets = bucket_width_for_cover(
        request.pixel_width, cover_lo, cover_hi, target_lo, target_hi,
    )
    return cover_lo, cover_hi, buckets


def _slice_empty(index: SpectrumCurveIndex) -> bool:
    return int(index.last) < int(index.first)


def _coverage_contains(
    cache_curves: tuple,
    request_curves: tuple,
) -> bool:
    if len(cache_curves) != len(request_curves):
        return False
    for cached, needed in zip(cache_curves, request_curves):
        if _slice_empty(needed):
            continue
        if _slice_empty(cached):
            return False
        if int(needed.first) < int(cached.first) or int(needed.last) > int(cached.last):
            return False
        needed_breaks = needed.break_key
        if needed_breaks:
            cached_breaks = set(cached.break_key)
            if any(b not in cached_breaks for b in needed_breaks):
                return False
    return True


def density_is_sufficient(
    cache: SpectrumTraceCache,
    target_lo: float,
    target_hi: float,
    pixel_width: int,
) -> bool:
    target_lo, target_hi = _ascending(target_lo, target_hi)
    view_span = target_hi - target_lo
    cover_span = float(cache.cover_hi) - float(cache.cover_lo)
    width = max(1, int(pixel_width))
    if view_span <= 0.0 or cover_span <= 0.0:
        return False
    # Zoom-in / wider plot rect: more buckets per Hz required.
    return int(cache.bucket_width) * view_span >= width * cover_span


def build_spectrum_trace_cache(
    request: SpectrumDisplayRequest,
    plan: SpectrumDisplayPlan,
    cover_curves: tuple,
) -> SpectrumTraceCache:
    curves = tuple(cover_curves)
    return SpectrumTraceCache(
        revision=request.revision,
        identities=request.identities,
        cover_lo=plan.cover_lo,
        cover_hi=plan.cover_hi,
        bucket_width=plan.bucket_width,
        pixel_width=request.pixel_width,
        curves=curves,
        fully_covered=bool(curves) and all(c.fully_covered for c in curves),
    )


def plan_spectrum_display(
    request: SpectrumDisplayRequest,
    cache: SpectrumTraceCache | None,
) -> SpectrumDisplayPlan:
    cover_lo, cover_hi, buckets = rebuild_cover_plan(request)
    if cache is None:
        return SpectrumDisplayPlan(False, cover_lo, cover_hi, buckets, 'empty')
    if (
        cache.revision != request.revision
        or cache.identities != request.identities
    ):
        return SpectrumDisplayPlan(
            False, cover_lo, cover_hi, buckets, 'revision',
        )
    if not _coverage_contains(cache.curves, request.curves):
        return SpectrumDisplayPlan(
            False, cover_lo, cover_hi, buckets, 'coverage',
        )
    if not density_is_sufficient(
        cache, request.target_lo, request.target_hi, request.pixel_width,
    ):
        return SpectrumDisplayPlan(
            False, cover_lo, cover_hi, buckets, 'density',
        )
    return SpectrumDisplayPlan(
        True, cache.cover_lo, cache.cover_hi, cache.bucket_width, 'hit',
    )
