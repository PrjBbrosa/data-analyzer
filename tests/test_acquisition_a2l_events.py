"""Tests for ``mf4_analyzer.acquisition_capture.a2l_events``.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Search And Filter Contract, ``build_event_intersection``.

These tests are pure unit tests — no real A2L is required. We construct
small in-test ``MeasurementSummary`` fixtures so the helper can be
exercised on macOS CI.
"""

from __future__ import annotations

import pytest

from can_logger.p0.a2l_probe import MeasurementSummary, _fill_ifdata_events
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


def test_fill_ifdata_events_mounts_per_measurement_events_from_raw_text():
    raw_text = """
    /begin PROJECT P ""
      /begin MODULE M ""
        /begin MEASUREMENT EngineSpeed ""
          UWORD NO_COMPU_METHOD 0 0 0 65535
          ECU_ADDRESS 0x1000
          /begin IF_DATA XCP
            /begin DAQ_EVENT FIXED_EVENT_LIST
              EVENT 0
            /end DAQ_EVENT
          /end IF_DATA
        /end MEASUREMENT
        /begin IF_DATA XCP
          /begin PROTOCOL_LAYER
            0x0100 0x0100 0 0 0 0 0 0 8 8 BYTE_ORDER_MSB_LAST ADDRESS_GRANULARITY_BYTE
          /end PROTOCOL_LAYER
          /begin XCP_ON_CAN
            CAN_ID_MASTER 0x500
            CAN_ID_SLAVE 0x501
          /end XCP_ON_CAN
          /begin DAQ
            /begin EVENT "event_10ms" "" 0 DAQ 8 10 6 0
            /end EVENT
          /end DAQ
        /end IF_DATA
      /end MODULE
    /end PROJECT
    """
    measurements = [_make_measurement("EngineSpeed")]

    updated, event_capacity, measurement_events, has_daq = _fill_ifdata_events(
        raw_text,
        measurements,
    )

    assert has_daq is True
    assert event_capacity == {"event_10ms": 8}
    assert measurement_events == {"EngineSpeed": ("event_10ms",)}
    assert updated[0].available_events == ("event_10ms",)
