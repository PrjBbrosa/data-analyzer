"""Qt-free UltraView presentation, filter, and axis facts.

Wave 5 Task 5.3 family 4. Status/filter/axis facts are derived from already
captured records; they do not write Board state. Presentation digest and
canonical JSON hashing live in ``mf4_analyzer.ultraview_core.serialization``.
This module must not import Qt, ``mf4_analyzer.ui``, chart_stack,
MainWindow, compositor, or Card Fit.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

from .model import (
    COMPARE_FILTER_ALL,
    SECTION_AXIS_KIND,
    SECTION_LABELS_EN,
    SECTION_LABELS_ZH,
    STATUS_FRESH,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    AxisConsistencyFacts,
)

RANGE_ABS_TOL = 1e-9
RANGE_REL_TOL = 1e-6


def derive_preview_status(
    ref_exists: bool,
    image_valid: bool,
    captured_digest: str | None,
    current_digest: str | None,
) -> str:
    """Derive card status. A missing current digest must never be fresh."""
    if not ref_exists:
        return STATUS_ORPHANED
    if not image_valid:
        return STATUS_MISSING
    if current_digest and captured_digest and current_digest == captured_digest:
        return STATUS_FRESH
    return STATUS_STALE


def normalize_unit(unit: str | None) -> str:
    if unit is None:
        return ""
    return str(unit).strip()


def ranges_close(
    left: Sequence[float] | None, right: Sequence[float] | None
) -> bool:
    if left is None or right is None:
        return True
    if len(left) != 2 or len(right) != 2:
        return False
    for a, b in zip(left, right):
        try:
            fa = float(a)
            fb = float(b)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(fa) or not math.isfinite(fb):
            return False
        if abs(fa - fb) > RANGE_ABS_TOL + RANGE_REL_TOL * max(abs(fa), abs(fb)):
            return False
    return True


def axis_consistency_facts(records: Iterable[Mapping[str, Any]]) -> AxisConsistencyFacts:
    """Structured unit/range warnings. Never parse human title strings."""
    by_kind: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        kind = record.get("axis_kind")
        if kind not in SECTION_AXIS_KIND.values():
            continue
        by_kind.setdefault(kind, []).append(record)

    unit_inconsistent: list[str] = []
    range_inconsistent: list[str] = []
    for kind, group in by_kind.items():
        units = []
        for record in group:
            unit = normalize_unit(record.get("x_unit"))
            if unit:
                units.append(unit)
        unique_units = tuple(dict.fromkeys(units))
        if len(unique_units) > 1:
            unit_inconsistent.append(kind)
            continue
        if not unique_units:
            continue
        ranges = [
            record.get("x_range")
            for record in group
            if record.get("x_range") is not None
        ]
        finite_ranges = []
        for item in ranges:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            try:
                lo, hi = float(item[0]), float(item[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(lo) and math.isfinite(hi):
                finite_ranges.append((lo, hi))
        if len(finite_ranges) >= 2:
            first = finite_ranges[0]
            if any(not ranges_close(first, other) for other in finite_ranges[1:]):
                range_inconsistent.append(kind)
    return AxisConsistencyFacts(
        unit_inconsistent_kinds=tuple(unit_inconsistent),
        range_inconsistent_kinds=tuple(range_inconsistent),
    )


def card_matches_compare_filter(axis_kind: str | None, filter_id: str) -> bool:
    if filter_id == COMPARE_FILTER_ALL:
        return True
    return axis_kind == filter_id


def section_search_haystack(section: str, name: str, source_summary: str) -> str:
    parts = [
        section,
        SECTION_LABELS_ZH.get(section, ""),
        SECTION_LABELS_EN.get(section, ""),
        name,
        source_summary,
    ]
    return " ".join(part for part in parts if part).lower()
