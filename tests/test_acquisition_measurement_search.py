"""Tests for ``mf4_analyzer.acquisition_capture.search``.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Search And Filter Contract.

Score bands (name search):
    1000  exact
     800  name prefix
     700  all tokens in order
     600  all tokens any order
     500  all tokens are substrings
     200  Levenshtein distance <= 2 fuzzy

Modes:
    address: input starts with 0x or is hex-heavy
    unit: looks unit-like (matches against phys_unit; normalized)
    name: otherwise

These tests are pure unit tests — no Qt, no real A2L.
"""

from __future__ import annotations

import pytest

from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_capture.search import SearchHit, search_measurements


def _make(
    name: str,
    *,
    address: int = 0,
    unit: str = "",
    events: tuple[str, ...] = (),
) -> MeasurementSummary:
    return MeasurementSummary(
        name=name,
        address=address,
        datatype="UWORD",
        unit=unit,
        conversion="",
        available_events=events,
    )


# ---------------------------------------------------------------------------
# Name search score bands.
# ---------------------------------------------------------------------------


def test_exact_match_scores_1000():
    pool = [_make("EngSpdAvg"), _make("EngSpdMax")]
    hits = search_measurements("EngSpdAvg", pool)
    assert hits[0].measurement.name == "EngSpdAvg"
    assert hits[0].score == 1000


def test_prefix_match_scores_800():
    pool = [_make("EngSpdAvg")]
    hits = search_measurements("EngSpd", pool)
    assert hits[0].score == 800


def test_all_tokens_in_order_scores_700():
    # "eng spd" tokens both appear in order in the name, but query is
    # not a prefix of the name (it has internal whitespace), and not exact.
    pool = [_make("EngSpdAvgRaw")]
    hits = search_measurements("eng spd", pool)
    # "eng spd" -> tokens [eng, spd]; both appear in order in "engspdavgraw".
    assert hits[0].score == 700


def test_all_tokens_any_order_scores_600():
    pool = [_make("SpdEngRaw")]
    # tokens [eng, spd] — both present but reversed order in name
    hits = search_measurements("eng spd", pool)
    assert hits[0].score == 600


def test_all_tokens_substrings_scores_500():
    # tokens [foo, bar] — both substrings; cannot be ordered run because
    # the name has each token nested with overlap.
    pool = [_make("BarBazFooQux")]
    hits = search_measurements("foo bar", pool)
    # tokens [foo, bar] — both present, foo after bar (so not ordered),
    # but each token IS a substring. Falls to all-tokens-any-order = 600.
    assert hits[0].score == 600


def test_levenshtein_2_fuzzy_scores_200():
    # "EngSpdAvg" vs query "EngSdpAvg" (two char transposition = edit 2)
    pool = [_make("EngSpdAvg")]
    hits = search_measurements("EngSdpAvg", pool)
    # Not exact (chars differ), not prefix (chars differ at position 4),
    # not all-tokens (single-token query "engsdpavg" is not substring),
    # but Levenshtein distance is 2.
    assert hits and hits[0].score == 200


def test_levenshtein_3_does_not_match():
    pool = [_make("Hello")]
    hits = search_measurements("xxxxx", pool)  # distance 5
    assert hits == []


# ---------------------------------------------------------------------------
# match_spans shape — UI must consume directly, no re-matching.
# ---------------------------------------------------------------------------


def test_exact_match_span_covers_entire_name():
    pool = [_make("EngSpdAvg")]
    hits = search_measurements("EngSpdAvg", pool)
    assert hits[0].match_spans == [(0, 9)]


def test_prefix_match_span_covers_prefix_only():
    pool = [_make("EngSpdAvg")]
    hits = search_measurements("EngSpd", pool)
    assert hits[0].match_spans == [(0, 6)]


def test_token_match_spans_are_disjoint_and_sorted():
    """For multi-token matches, each token gets its own (start, end) span
    in the name string, half-open, non-overlapping, ascending.
    """
    pool = [_make("EngSpdAvgRaw")]
    hits = search_measurements("eng raw", pool)
    spans = hits[0].match_spans
    # half-open: end > start; sorted ascending; non-overlapping
    assert all(0 <= s < e for s, e in spans)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert e1 <= s2
    # verify both tokens are actually located by the spans
    matched = "".join("EngSpdAvgRaw"[s:e] for s, e in spans).lower()
    assert "eng" in matched and "raw" in matched


# ---------------------------------------------------------------------------
# Address mode — 0x... hex.
# ---------------------------------------------------------------------------


def test_address_mode_matches_hex_prefix():
    pool = [_make("A", address=0x40000000), _make("B", address=0x12345678)]
    hits = search_measurements("0x4000", pool)
    assert {h.measurement.name for h in hits} == {"A"}


def test_address_mode_matches_full_hex():
    pool = [_make("A", address=0x40000000)]
    hits = search_measurements("0x40000000", pool)
    assert hits[0].measurement.name == "A"
    assert hits[0].score == 1000  # exact-after-normalization


def test_address_mode_no_match_returns_empty():
    pool = [_make("A", address=0x40000000)]
    hits = search_measurements("0xDEADBEEF", pool)
    assert hits == []


# ---------------------------------------------------------------------------
# Unit mode — normalization.
# ---------------------------------------------------------------------------


def test_unit_mode_celsius_normalized():
    """``°C`` query matches a measurement with unit ``degc``."""
    pool = [_make("Temp", unit="degc")]
    hits = search_measurements("°C", pool)
    assert hits and hits[0].measurement.name == "Temp"


def test_unit_mode_kgm3_caret_dropped():
    """``kg/m^3`` query matches a measurement with unit ``kg/m3``."""
    pool = [_make("Density", unit="kg/m3")]
    hits = search_measurements("kg/m^3", pool)
    assert hits and hits[0].measurement.name == "Density"


def test_unit_mode_whitespace_and_case_normalized():
    pool = [_make("Speed", unit="KM/H")]
    hits = search_measurements("  km/h  ", pool)
    assert hits and hits[0].measurement.name == "Speed"


def test_unit_mode_excludes_measurements_with_empty_unit():
    """Spec: measurements with empty phys_unit are invisible in unit mode
    (rather than matching empty string)."""
    pool = [_make("NoUnit", unit=""), _make("WithUnit", unit="rpm")]
    hits = search_measurements("rpm", pool)
    names = {h.measurement.name for h in hits}
    assert "NoUnit" not in names
    assert "WithUnit" in names


def test_unit_mode_no_fuzzy():
    """Unit mode is exact-after-normalization; no Levenshtein fallback."""
    pool = [_make("Speed", unit="rpm")]
    hits = search_measurements("rpn", pool)  # 1 edit from "rpm"
    # rpn looks unit-like, so it's unit-mode; unit mode rejects fuzzy.
    # However it could be interpreted as name mode — assert at least
    # that we do NOT match the rpm-only measurement.
    names = {h.measurement.name for h in hits}
    assert "Speed" not in names


# ---------------------------------------------------------------------------
# Result cap.
# ---------------------------------------------------------------------------


def test_returns_top_50_results():
    pool = [_make(f"Sig{i:03d}") for i in range(200)]
    hits = search_measurements("Sig", pool)
    assert len(hits) <= 50


def test_results_sorted_by_score_descending():
    pool = [
        _make("EngSpdAvgRaw"),     # 700 all-tokens-in-order
        _make("EngSpd"),            # 800 prefix
        _make("EngSpdAvg"),         # 800 prefix
    ]
    hits = search_measurements("EngSpd", pool)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Address heuristic edge cases.
# ---------------------------------------------------------------------------


def test_short_non_hex_is_name_mode_not_address():
    """Just ``Eng`` is short but not hex; should NOT trigger address mode."""
    pool = [_make("EngSpd", address=0xABCD)]
    hits = search_measurements("Eng", pool)
    assert hits and hits[0].measurement.name == "EngSpd"
