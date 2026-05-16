"""Tests for ``mf4_analyzer.acquisition_capture.preflight_estimates``.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Preflight Computation Contract.

All four functions are pure and Qt-free. Each must exercise the
green/yellow/red bands from §Threshold Contract and the documented edge
cases (empty selection, capacity=0, throughput=0, event is None).
"""

from __future__ import annotations

import math

import pytest

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.preflight_estimates import (
    band_can_load,
    band_daq_slot,
    band_disk_remaining,
    band_record_duration_s,
    band_sample_events_per_s,
    daq_slot_usage,
    estimate_can_bus_load,
    estimate_record_duration_s,
    estimate_sample_events_per_s,
    estimate_throughput_bps,
)


def _measurement(
    name: str,
    *,
    event: str | None = "event_10ms",
    rate_hz: float = 100.0,
    payload_bytes: int = 4,
) -> SelectedMeasurement:
    return SelectedMeasurement(
        name=name,
        event=event,
        event_rate_hz=rate_hz,
        payload_bytes=payload_bytes,
    )


# ---------------------------------------------------------------------------
# estimate_can_bus_load — XCP-only model.
# Formula: sum(event_rate_hz * odt_bytes) * 8 / bitrate_bps * 100
# Spec bands: <60 green, 60-80 yellow, >=80 red.
# ---------------------------------------------------------------------------


def test_can_bus_load_empty_selection_is_zero():
    assert estimate_can_bus_load([], bitrate_bps=500_000) == 0.0


def test_can_bus_load_green_band():
    # rate=100Hz, payload=4 -> 100*4=400 bytes/s -> 3200 bits/s
    # at 500k bitrate -> 0.64% (green)
    selected = [_measurement("A")]
    load = estimate_can_bus_load(selected, bitrate_bps=500_000)
    assert 0 < load < thresholds.CAN_LOAD_GREEN_MAX_PCT


def test_can_bus_load_yellow_band():
    # 60% load at 500k bps -> bits/s = 300_000 -> bytes/s = 37_500
    # rate=1000Hz * payload=38 -> bytes/s=38000 -> 38000*8/500000=60.8% (yellow)
    selected = [_measurement("A", rate_hz=1000.0, payload_bytes=38)]
    load = estimate_can_bus_load(selected, bitrate_bps=500_000)
    assert thresholds.CAN_LOAD_GREEN_MAX_PCT <= load < thresholds.CAN_LOAD_YELLOW_MAX_PCT


def test_can_bus_load_red_band():
    # rate=1000Hz, payload=60 -> bytes/s=60000 -> 60000*8/500000=96% (red)
    selected = [_measurement("A", rate_hz=1000.0, payload_bytes=60)]
    load = estimate_can_bus_load(selected, bitrate_bps=500_000)
    assert load >= thresholds.CAN_LOAD_YELLOW_MAX_PCT


def test_can_bus_load_excludes_measurements_without_event():
    """Measurements with ``event is None`` are excluded from estimate."""
    excluded = _measurement("NoEvent", event=None, rate_hz=10_000.0, payload_bytes=100)
    included = _measurement("HasEvent", rate_hz=100.0, payload_bytes=4)
    only_excluded = estimate_can_bus_load([excluded], bitrate_bps=500_000)
    assert only_excluded == 0.0
    mixed = estimate_can_bus_load([excluded, included], bitrate_bps=500_000)
    only_included = estimate_can_bus_load([included], bitrate_bps=500_000)
    assert mixed == pytest.approx(only_included)


def test_can_bus_load_sums_multiple_measurements():
    a = _measurement("A", rate_hz=100.0, payload_bytes=4)
    b = _measurement("B", rate_hz=200.0, payload_bytes=8)
    expected = ((100.0 * 4) + (200.0 * 8)) * 8 / 500_000 * 100
    load = estimate_can_bus_load([a, b], bitrate_bps=500_000)
    assert load == pytest.approx(expected)


# ---------------------------------------------------------------------------
# daq_slot_usage — len(selected on event) / capacity * 100.
# Bands: <75 green, 75-95 yellow, =100 red.
# ---------------------------------------------------------------------------


def test_daq_slot_usage_green_band():
    selected = [_measurement(f"S{i}", event="event_10ms") for i in range(5)]
    usage = daq_slot_usage("event_10ms", selected, {"event_10ms": 10})
    assert usage == 50.0
    assert usage < thresholds.DAQ_SLOT_GREEN_MAX_PCT


def test_daq_slot_usage_yellow_band():
    selected = [_measurement(f"S{i}", event="event_10ms") for i in range(8)]
    usage = daq_slot_usage("event_10ms", selected, {"event_10ms": 10})
    assert usage == 80.0
    assert thresholds.DAQ_SLOT_GREEN_MAX_PCT <= usage < thresholds.DAQ_SLOT_YELLOW_MAX_PCT


def test_daq_slot_usage_red_at_100():
    selected = [_measurement(f"S{i}", event="event_10ms") for i in range(10)]
    usage = daq_slot_usage("event_10ms", selected, {"event_10ms": 10})
    assert usage == 100.0


def test_daq_slot_usage_excludes_other_events():
    selected = [
        _measurement("A", event="event_10ms"),
        _measurement("B", event="event_100ms"),
        _measurement("C", event="event_10ms"),
    ]
    usage = daq_slot_usage("event_10ms", selected, {"event_10ms": 4})
    assert usage == 50.0


def test_daq_slot_usage_capacity_zero_returns_red_100():
    """Capacity 0 cannot fit anything — spec says return 100.0 (red)."""
    selected = [_measurement("A", event="event_10ms")]
    usage = daq_slot_usage("event_10ms", selected, {"event_10ms": 0})
    assert usage == 100.0


def test_daq_slot_usage_unknown_event_treats_as_zero_capacity():
    """If the event is not in capacity map, capacity = 0 -> 100.0 (red)."""
    selected = [_measurement("A", event="event_10ms")]
    usage = daq_slot_usage("event_unknown", selected, {"event_10ms": 10})
    # No measurements selected on event_unknown, but capacity is unknown.
    # Spec says capacity 0 returns 100.0; missing entry behaves like 0.
    assert usage == 100.0


def test_daq_slot_usage_empty_selection_zero_when_capacity_positive():
    usage = daq_slot_usage("event_10ms", [], {"event_10ms": 10})
    assert usage == 0.0


# ---------------------------------------------------------------------------
# estimate_throughput_bps — sum(event_rate_hz * payload_bytes), no compression.
# ---------------------------------------------------------------------------


def test_throughput_bps_empty_selection_is_zero():
    assert estimate_throughput_bps([]) == 0.0


def test_throughput_bps_single_measurement():
    m = _measurement("A", rate_hz=100.0, payload_bytes=4)
    assert estimate_throughput_bps([m]) == 400.0


def test_throughput_bps_sums_correctly():
    a = _measurement("A", rate_hz=100.0, payload_bytes=4)
    b = _measurement("B", rate_hz=200.0, payload_bytes=8)
    assert estimate_throughput_bps([a, b]) == 400.0 + 1600.0


def test_throughput_bps_excludes_event_none():
    """Edge case spec: ``event is None`` excluded from throughput too."""
    excluded = _measurement("X", event=None, rate_hz=1000.0, payload_bytes=100)
    included = _measurement("Y", rate_hz=100.0, payload_bytes=4)
    only_excluded = estimate_throughput_bps([excluded])
    assert only_excluded == 0.0
    assert estimate_throughput_bps([excluded, included]) == 400.0


# ---------------------------------------------------------------------------
# estimate_record_duration_s — disk_free / throughput; inf when 0.
# Bands: >4h green, 30min-4h yellow, <30min red.
# ---------------------------------------------------------------------------


def test_record_duration_zero_throughput_returns_inf():
    duration = estimate_record_duration_s(throughput_bps=0.0, disk_free_bytes=10**9)
    assert duration == float("inf")


def test_record_duration_green_band_over_4h():
    # 1 byte/s, 1 day of disk -> hours = 86400/3600 = 24h
    duration = estimate_record_duration_s(throughput_bps=1.0, disk_free_bytes=86400)
    assert duration > thresholds.RECORD_DURATION_GREEN_MIN_S


def test_record_duration_yellow_band_1h():
    # throughput=1 MB/s, disk=3.6 GB -> 3600 s (1h) -> yellow
    duration = estimate_record_duration_s(
        throughput_bps=1_000_000.0, disk_free_bytes=3_600_000_000
    )
    assert (
        thresholds.RECORD_DURATION_YELLOW_MIN_S
        <= duration
        < thresholds.RECORD_DURATION_GREEN_MIN_S
    )


def test_record_duration_red_band_under_30min():
    # throughput=1 MB/s, disk=600 MB -> 600 s (10 min) -> red
    duration = estimate_record_duration_s(
        throughput_bps=1_000_000.0, disk_free_bytes=600_000_000
    )
    assert duration < thresholds.RECORD_DURATION_YELLOW_MIN_S


def test_record_duration_basic_division():
    duration = estimate_record_duration_s(throughput_bps=10.0, disk_free_bytes=1000)
    assert duration == 100.0


# ---------------------------------------------------------------------------
# estimate_sample_events_per_s — sum(event_rate_hz); event=None excluded.
# Bands: <30k green, 30-80k yellow, >80k red (covered by band helper below).
# ---------------------------------------------------------------------------


def test_estimate_sample_events_per_s_empty_selection_is_zero():
    assert estimate_sample_events_per_s([]) == 0.0


def test_estimate_sample_events_per_s_single_measurement():
    m = _measurement("A", rate_hz=100.0)
    assert estimate_sample_events_per_s([m]) == 100.0


def test_estimate_sample_events_per_s_sums_mixed_selection():
    a = _measurement("A", rate_hz=100.0)
    b = _measurement("B", rate_hz=250.5)
    c = _measurement("C", rate_hz=1000.0)
    assert estimate_sample_events_per_s([a, b, c]) == pytest.approx(1350.5)


def test_estimate_sample_events_per_s_excludes_event_none():
    """Measurements with ``event is None`` are excluded (spec edge case)."""
    excluded = _measurement("X", event=None, rate_hz=999.0)
    included = _measurement("Y", rate_hz=100.0)
    assert estimate_sample_events_per_s([excluded]) == 0.0
    assert estimate_sample_events_per_s([excluded, included]) == pytest.approx(100.0)


def test_estimate_sample_events_per_s_payload_independent():
    """Result depends only on event_rate_hz, not on payload_bytes."""
    a = _measurement("A", rate_hz=200.0, payload_bytes=1)
    b = _measurement("B", rate_hz=200.0, payload_bytes=64)
    assert estimate_sample_events_per_s([a]) == estimate_sample_events_per_s([b])


# ---------------------------------------------------------------------------
# band_disk_remaining — Threshold Contract:
#   > 5 GB -> green, 1..5 GB -> yellow, < 1 GB -> red.
# Boundary semantics: exactly 5 GB and exactly 1 GB fall inside the inclusive
# yellow band (green strict >, red strict <).
# ---------------------------------------------------------------------------


def test_band_disk_remaining_green_above_5gb():
    assert band_disk_remaining(thresholds.DISK_FREE_GREEN_MIN_BYTES + 1) == "green"
    assert band_disk_remaining(10 * 1024 ** 3) == "green"


def test_band_disk_remaining_yellow_between_1_and_5gb():
    midpoint = (
        thresholds.DISK_FREE_YELLOW_MIN_BYTES + thresholds.DISK_FREE_GREEN_MIN_BYTES
    ) // 2
    assert band_disk_remaining(midpoint) == "yellow"


def test_band_disk_remaining_red_below_1gb():
    assert band_disk_remaining(thresholds.DISK_FREE_YELLOW_MIN_BYTES - 1) == "red"
    assert band_disk_remaining(0) == "red"


def test_band_disk_remaining_boundary_5gb_is_yellow():
    """Spec band is `> 5 GB` -> green; exactly 5 GB falls into `1-5 GB` yellow."""
    assert band_disk_remaining(thresholds.DISK_FREE_GREEN_MIN_BYTES) == "yellow"


def test_band_disk_remaining_boundary_1gb_is_yellow():
    """Spec band is `< 1 GB` -> red; exactly 1 GB falls into `1-5 GB` yellow."""
    assert band_disk_remaining(thresholds.DISK_FREE_YELLOW_MIN_BYTES) == "yellow"


# ---------------------------------------------------------------------------
# band_sample_events_per_s — Threshold Contract:
#   < 30 k -> green, 30..80 k -> yellow, > 80 k -> red.
# Boundary semantics: exactly 30_000 and exactly 80_000 fall inside the
# inclusive yellow band (green strict <, red strict >).
# ---------------------------------------------------------------------------


def test_band_sample_events_per_s_green_below_30k():
    assert band_sample_events_per_s(0.0) == "green"
    assert band_sample_events_per_s(
        thresholds.SAMPLE_EVENTS_GREEN_MAX_PER_S - 1.0
    ) == "green"


def test_band_sample_events_per_s_yellow_between_30k_and_80k():
    midpoint = (
        thresholds.SAMPLE_EVENTS_GREEN_MAX_PER_S
        + thresholds.SAMPLE_EVENTS_YELLOW_MAX_PER_S
    ) / 2.0
    assert band_sample_events_per_s(midpoint) == "yellow"


def test_band_sample_events_per_s_red_above_80k():
    assert band_sample_events_per_s(
        thresholds.SAMPLE_EVENTS_YELLOW_MAX_PER_S + 1.0
    ) == "red"
    assert band_sample_events_per_s(1_000_000.0) == "red"


def test_band_sample_events_per_s_boundary_30k_is_yellow():
    """Spec band is `< 30 k` -> green; exactly 30 000 falls into `30-80 k` yellow."""
    assert (
        band_sample_events_per_s(thresholds.SAMPLE_EVENTS_GREEN_MAX_PER_S) == "yellow"
    )


def test_band_sample_events_per_s_boundary_80k_is_yellow():
    """Spec band is `> 80 k` -> red; exactly 80 000 falls into `30-80 k` yellow."""
    assert (
        band_sample_events_per_s(thresholds.SAMPLE_EVENTS_YELLOW_MAX_PER_S) == "yellow"
    )


def test_new_band_helpers_classify_preflight_estimator_outputs():
    """Smoke-test the Stage 1 helper API against real estimator outputs."""
    selected = [
        _measurement("A", event="event_10ms", rate_hz=1000.0, payload_bytes=60),
        _measurement("B", event="event_10ms", rate_hz=1000.0, payload_bytes=60),
    ]

    can_pct = estimate_can_bus_load(selected, bitrate_bps=500_000)
    daq_pct = daq_slot_usage("event_10ms", selected, {"event_10ms": 2})
    duration_s = estimate_record_duration_s(
        throughput_bps=1_000_000.0,
        disk_free_bytes=3_600_000_000,
    )

    assert band_can_load(can_pct) == "red"
    assert band_daq_slot(daq_pct) == "red"
    assert band_record_duration_s(duration_s) == "yellow"
