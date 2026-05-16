"""Token-aware measurement search for the Cockpit Left Pane.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Search And Filter Contract.

Three modes are auto-detected from the query:

- ``address``: query starts with ``0x`` or is hex-heavy.
- ``unit``: query looks unit-like (matched against measurement
  ``phys_unit`` with the normalization rules below).
- ``name``: anything else; tokenized and scored.

Name search score bands:

    1000  exact
     800  prefix
     700  all tokens in order
     600  all tokens any order
     500  all tokens are substrings
     200  Levenshtein distance <= 2 fuzzy

Unit-mode normalization:

- both query and unit are lower-cased, stripped, whitespace-collapsed.
- ``°`` → ``deg`` on both sides.
- ``^`` is dropped.
- ``/`` is kept.
- A measurement with empty ``phys_unit`` is INVISIBLE in unit mode.

Returns up to ``MAX_RESULTS`` hits sorted by score descending.

This module is pure-Python and Qt-free.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from can_logger.p0.a2l_probe import MeasurementSummary

MAX_RESULTS = 50

# Score bands (spec §Search And Filter Contract).
SCORE_EXACT = 1000
SCORE_PREFIX = 800
SCORE_TOKENS_IN_ORDER = 700
SCORE_TOKENS_ANY_ORDER = 600
SCORE_TOKENS_SUBSTRINGS = 500
SCORE_FUZZY = 200

# Levenshtein cutoff for fuzzy bin.
FUZZY_MAX_EDITS = 2

# Address-mode detection heuristic — explicit ``0x`` prefix only.
# Bare hex without the prefix is too easily confused with a name token
# like ``EAD`` or ``CAFE``, so we require the prefix to keep address
# mode unambiguous. Names beginning with ``0x`` are vanishingly rare in
# A2L.
_ADDRESS_PREFIX = re.compile(r"^\s*0x[0-9a-fA-F]+\s*$", re.IGNORECASE)

# Unit-mode heuristic: looks unit-like if it contains a unit-shaped
# token (degree symbol, slash, caret, or a known unit suffix). The
# trigger is intentionally permissive — wrong classification just routes
# the query through one extra empty match.
_UNIT_HINT = re.compile(r"[°/^]|^(rpm|km/h|nm|degc|deg|hz|khz|mhz|pa|kpa|mpa|bar|m/s|g|kg|w|kw|hp|v|a|ma)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public dataclass.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchHit:
    """One search result.

    ``match_spans`` is a list of half-open ``(start, end)`` character
    ranges into ``measurement.name`` (or the empty list for unit/address
    matches that don't need name highlighting). The UI renders blue
    highlights directly from these spans — no re-matching.
    """

    measurement: MeasurementSummary
    score: int
    match_spans: list[tuple[int, int]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Mode detection.
# ---------------------------------------------------------------------------


SearchMode = Literal["address", "unit", "name"]


def _detect_mode(query: str) -> SearchMode:
    if _ADDRESS_PREFIX.match(query):
        return "address"
    # Heuristic for unit: contains a unit-shape character (°, /, ^) OR
    # the whole token matches a known unit suffix. This keeps single
    # ASCII tokens like "Eng" or "Spd" in name mode.
    if _UNIT_HINT.search(query):
        return "unit"
    return "name"


# ---------------------------------------------------------------------------
# Unit normalization.
# ---------------------------------------------------------------------------


def _normalize_unit(s: str) -> str:
    """Spec rules: lower, strip, collapse whitespace, ``°→deg``, drop ``^``."""
    s = s.lower().strip()
    s = s.replace("°", "deg")
    s = s.replace("^", "")
    s = re.sub(r"\s+", "", s)
    return s


# ---------------------------------------------------------------------------
# Levenshtein.
# ---------------------------------------------------------------------------


def _levenshtein(a: str, b: str) -> int:
    """Iterative DP, O(len(a) * len(b))."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(
                cur[j - 1] + 1,           # insertion
                prev[j] + 1,              # deletion
                prev[j - 1] + cost,       # substitution
            )
        prev = cur
    return prev[-1]


# ---------------------------------------------------------------------------
# Token utilities.
# ---------------------------------------------------------------------------


_TOKEN_SPLIT = re.compile(r"[\s_/\-]+")


def _tokenize(query: str) -> list[str]:
    """Lower-cased token list. CamelCase is NOT split — the name search
    matches against the case-folded full name, so "EngSpd" / "engspd"
    are equivalent. Whitespace, underscore, slash, hyphen split tokens.
    """
    return [t for t in _TOKEN_SPLIT.split(query.lower().strip()) if t]


def _find_token_span(haystack_lower: str, token: str, start: int = 0) -> tuple[int, int] | None:
    """Return half-open span of the first occurrence at-or-after ``start``."""
    idx = haystack_lower.find(token, start)
    if idx < 0:
        return None
    return (idx, idx + len(token))


def _all_tokens_in_order_spans(name_lower: str, tokens: list[str]) -> list[tuple[int, int]] | None:
    """Return spans if every token appears in the name in left-to-right
    non-overlapping order, else None."""
    cursor = 0
    spans: list[tuple[int, int]] = []
    for tok in tokens:
        span = _find_token_span(name_lower, tok, cursor)
        if span is None:
            return None
        spans.append(span)
        cursor = span[1]
    return spans


def _all_tokens_any_order_spans(name_lower: str, tokens: list[str]) -> list[tuple[int, int]] | None:
    """Return spans (in ascending start order) if every token is a
    substring of the name, regardless of order; spans must be non-
    overlapping. None when any token is missing or when greedy
    assignment can't avoid overlap.
    """
    used: list[tuple[int, int]] = []
    for tok in tokens:
        # Find first non-overlapping occurrence.
        start = 0
        while True:
            span = _find_token_span(name_lower, tok, start)
            if span is None:
                return None
            if not any(_overlaps(span, u) for u in used):
                used.append(span)
                break
            start = span[0] + 1
    used.sort()
    return used


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return not (a[1] <= b[0] or b[1] <= a[0])


# ---------------------------------------------------------------------------
# Scoring for a single measurement (name mode).
# ---------------------------------------------------------------------------


def _score_name(query: str, measurement: MeasurementSummary) -> tuple[int, list[tuple[int, int]]] | None:
    name = measurement.name
    name_lower = name.lower()
    q_lower = query.lower().strip()

    if not q_lower:
        return None

    if q_lower == name_lower:
        return SCORE_EXACT, [(0, len(name))]

    if name_lower.startswith(q_lower):
        return SCORE_PREFIX, [(0, len(q_lower))]

    tokens = _tokenize(query)
    if tokens:
        ordered = _all_tokens_in_order_spans(name_lower, tokens)
        if ordered is not None:
            return SCORE_TOKENS_IN_ORDER, ordered

        any_order = _all_tokens_any_order_spans(name_lower, tokens)
        if any_order is not None:
            # Distinguish "any order but distinct overlapping-free" from
            # "merely substrings" by spec band. The any-order check
            # already enforces non-overlap; if all tokens fit, score is
            # 600. If any-order also fails because tokens collide, fall
            # to 500 by checking substring presence ignoring overlap.
            return SCORE_TOKENS_ANY_ORDER, any_order

        # SCORE_TOKENS_SUBSTRINGS — every token is a substring (overlap
        # allowed). Build spans by taking the FIRST occurrence of each
        # token, deduped.
        substring_spans: list[tuple[int, int]] = []
        for tok in tokens:
            span = _find_token_span(name_lower, tok, 0)
            if span is None:
                substring_spans = []
                break
            substring_spans.append(span)
        if substring_spans:
            substring_spans = _dedup_sorted(substring_spans)
            return SCORE_TOKENS_SUBSTRINGS, substring_spans

    # Fuzzy fallback: single-token Levenshtein against case-folded name.
    if len(tokens) == 1:
        edits = _levenshtein(q_lower, name_lower)
        if edits <= FUZZY_MAX_EDITS:
            return SCORE_FUZZY, []  # no precise spans for fuzzy
    return None


def _dedup_sorted(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and merge identical spans; preserve all distinct spans."""
    return sorted(set(spans))


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def search_measurements(
    query: str,
    pool: Iterable[MeasurementSummary],
    *,
    max_results: int = MAX_RESULTS,
) -> list[SearchHit]:
    """Return the top ``max_results`` hits for ``query`` against ``pool``.

    The empty query returns an empty list (UI should show "type to
    search" rather than spamming a full list).
    """
    query = query.strip()
    if not query:
        return []

    pool_list = list(pool)
    mode = _detect_mode(query)

    hits: list[SearchHit] = []

    if mode == "address":
        hits.extend(_search_address(query, pool_list))
    elif mode == "unit":
        hits.extend(_search_unit(query, pool_list))
    else:
        hits.extend(_search_name(query, pool_list))

    # Stable sort by descending score then ascending name (so ties are
    # deterministic for tests).
    hits.sort(key=lambda h: (-h.score, h.measurement.name))
    return hits[:max_results]


# ---------------------------------------------------------------------------
# Per-mode implementations.
# ---------------------------------------------------------------------------


def _search_name(query: str, pool: Sequence[MeasurementSummary]) -> list[SearchHit]:
    out: list[SearchHit] = []
    for m in pool:
        result = _score_name(query, m)
        if result is None:
            continue
        score, spans = result
        out.append(SearchHit(measurement=m, score=score, match_spans=spans))
    return out


def _search_address(query: str, pool: Sequence[MeasurementSummary]) -> list[SearchHit]:
    q = query.strip().lower()
    if q.startswith("0x"):
        digits = q[2:]
    else:
        digits = q
    if not digits:
        return []
    out: list[SearchHit] = []
    for m in pool:
        addr_hex = f"{m.address:08x}"
        if addr_hex == digits:
            out.append(SearchHit(measurement=m, score=SCORE_EXACT, match_spans=[]))
        elif addr_hex.startswith(digits):
            out.append(SearchHit(measurement=m, score=SCORE_PREFIX, match_spans=[]))
    return out


def _search_unit(query: str, pool: Sequence[MeasurementSummary]) -> list[SearchHit]:
    q_norm = _normalize_unit(query)
    if not q_norm:
        return []
    out: list[SearchHit] = []
    for m in pool:
        if not m.unit:
            # Spec: measurements with empty phys_unit are INVISIBLE in
            # unit mode (rather than matching empty string).
            continue
        u_norm = _normalize_unit(m.unit)
        if u_norm == q_norm:
            # Unit mode is exact-after-normalization; no fuzzy.
            out.append(SearchHit(measurement=m, score=SCORE_EXACT, match_spans=[]))
    return out
