"""Tests for ``mf4_analyzer.acquisition_capture.a2l_events``.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Search And Filter Contract, ``build_event_intersection``.

These tests are pure unit tests — no real A2L is required. We construct
small in-test ``MeasurementSummary`` fixtures so the helper can be
exercised on macOS CI.
"""

from __future__ import annotations

import pytest

from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_capture.a2l_events import build_event_intersection


def _make_measurement(
    name: str,
    *,
    events: tuple[str, ...] = (),
    unit: str = "",
    address: int = 0,
) -> MeasurementSummary:
    return MeasurementSummary(
        name=name,
        address=address,
        datatype="UWORD",
        unit=unit,
        conversion="",
        available_events=events,
    )


def test_build_event_intersection_empty_selection_returns_empty_set():
    result = build_event_intersection([])
    assert result == set()


def test_build_event_intersection_single_measurement_returns_its_events():
    m = _make_measurement("EngSpdAvg", events=("event_10ms", "event_100ms"))
    result = build_event_intersection([m])
    assert result == {"event_10ms", "event_100ms"}


def test_build_event_intersection_shared_event_returns_intersection():
    a = _make_measurement("A", events=("event_10ms", "event_100ms"))
    b = _make_measurement("B", events=("event_10ms", "event_1s"))
    result = build_event_intersection([a, b])
    assert result == {"event_10ms"}


def test_build_event_intersection_no_common_event_returns_empty_set():
    a = _make_measurement("A", events=("event_10ms",))
    b = _make_measurement("B", events=("event_100ms",))
    result = build_event_intersection([a, b])
    assert result == set()


def test_build_event_intersection_measurement_without_events_collapses_intersection():
    """A measurement without any declared events cannot share any event;
    the intersection MUST collapse to the empty set, not silently skip it."""
    a = _make_measurement("A", events=("event_10ms",))
    b = _make_measurement("B", events=())
    result = build_event_intersection([a, b])
    assert result == set()


def test_build_event_intersection_three_way_shared():
    a = _make_measurement("A", events=("event_10ms", "event_100ms"))
    b = _make_measurement("B", events=("event_10ms", "event_100ms", "event_1s"))
    c = _make_measurement("C", events=("event_10ms",))
    result = build_event_intersection([a, b, c])
    assert result == {"event_10ms"}
