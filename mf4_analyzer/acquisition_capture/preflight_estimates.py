"""Pure-function preflight estimates for the right pane.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Preflight Computation Contract.

All five estimators and the band helpers are pure and Qt-free. They
are bound to the right-pane preflight rows whose green/yellow/red bands
live in ``mf4_analyzer.acquisition_capture.thresholds`` (spec §Threshold
Contract). The widget reads numbers from here and colors them via band
helpers (or the existing percent thresholds); no widget-local computation.

Edge cases pinned by spec:

- A ``SelectedMeasurement`` with ``event is None`` is excluded from
  ``estimate_can_bus_load``, ``estimate_throughput_bps``, and
  ``estimate_sample_events_per_s``. The right pane shows "—" for those
  rows rather than a green 0%.
- ``daq_slot_usage`` returns ``100.0`` (red) when capacity is 0 (or the
  event is unknown) — anything beyond zero selections cannot fit, and
  zero selections on a missing event still has no headroom.
- ``estimate_record_duration_s`` returns ``float('inf')`` when
  throughput is 0 so the UI can show "∞" rather than divide by zero.
- Band helpers use strict ``>`` for the green-side cut and strict ``<``
  for the red-side cut, matching the spec table; boundary values
  (e.g. exactly 5 GB or exactly 30 000 events/s) land in the
  inclusive yellow band.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement


def estimate_can_bus_load(
    selected: Sequence[SelectedMeasurement],
    bitrate_bps: int,
) -> float:
    """Return XCP-only CAN bus load estimate as 0..100 percent.

    Formula (spec §Preflight Computation Contract):

        sum(event_rate_hz * odt_bytes) * 8 / bitrate_bps * 100

    Measurements with ``event is None`` are excluded.
    """
    if bitrate_bps <= 0:
        return 0.0
    total_bytes_per_s = 0.0
    for m in selected:
        if m.event is None:
            continue
        total_bytes_per_s += float(m.event_rate_hz) * float(m.payload_bytes)
    return total_bytes_per_s * 8.0 / float(bitrate_bps) * 100.0


def daq_slot_usage(
    event_name: str,
    selected: Sequence[SelectedMeasurement],
    event_capacity: Mapping[str, int],
) -> float:
    """Return DAQ slot usage for ``event_name`` as 0..100 percent.

    Formula (spec): ``len([m for m in selected if m.event == event_name])
    / capacity * 100``. Capacity 0 (or missing event in the capacity
    map) returns ``100.0`` — red — because nothing fits.
    """
    capacity = event_capacity.get(event_name, 0)
    if capacity <= 0:
        return 100.0
    selected_on_event = sum(1 for m in selected if m.event == event_name)
    return selected_on_event / float(capacity) * 100.0


def estimate_throughput_bps(
    selected: Sequence[SelectedMeasurement],
) -> float:
    """Return MF4-write throughput in bytes per second.

    Formula (spec): ``sum(event_rate_hz * payload_bytes)``. No compression.
    Measurements with ``event is None`` are excluded — they cannot stream
    over an unconfigured DAQ event.
    """
    total = 0.0
    for m in selected:
        if m.event is None:
            continue
        total += float(m.event_rate_hz) * float(m.payload_bytes)
    return total


def estimate_record_duration_s(
    throughput_bps: float,
    disk_free_bytes: int,
) -> float:
    """Return estimated record duration in seconds.

    Formula (spec): ``disk_free_bytes / throughput_bps``. When throughput
    is 0 (no selection or all selections excluded), return ``float('inf')``
    so the UI shows "∞" rather than dividing by zero.
    """
    if throughput_bps <= 0:
        return float("inf")
    return float(disk_free_bytes) / float(throughput_bps)


def estimate_sample_events_per_s(
    selected: Sequence[SelectedMeasurement],
) -> float:
    """Return total sample events per second across the selection.

    Formula (spec): ``sum(event_rate_hz for m in selected if m.event is not None)``.
    Measurements with ``event is None`` are excluded — without a DAQ event
    they cannot contribute sample events to the bus.
    """
    total = 0.0
    for m in selected:
        if m.event is None:
            continue
        total += float(m.event_rate_hz)
    return total


def band_disk_remaining(disk_free_bytes: int) -> str:
    """Return ``'green' | 'yellow' | 'red'`` for disk-remaining row.

    Spec §Threshold Contract:
        ``> 5 GB`` -> green, ``1..5 GB`` -> yellow, ``< 1 GB`` -> red.

    Boundary semantics: green uses strict ``>``, red uses strict ``<``;
    exactly 5 GB and exactly 1 GB land in the inclusive yellow band.
    """
    if disk_free_bytes > thresholds.DISK_FREE_GREEN_MIN_BYTES:
        return "green"
    if disk_free_bytes < thresholds.DISK_FREE_YELLOW_MIN_BYTES:
        return "red"
    return "yellow"


def band_can_load(pct: float) -> str:
    """Return ``'green' | 'yellow' | 'red'`` for CAN bus load.

    Spec §Threshold Contract:
        ``< 60%`` -> green, ``60..80%`` -> yellow, ``>= 80%`` -> red.
    """
    if pct < thresholds.CAN_LOAD_GREEN_MAX_PCT:
        return "green"
    if pct >= thresholds.CAN_LOAD_YELLOW_MAX_PCT:
        return "red"
    return "yellow"


def band_daq_slot(pct: float) -> str:
    """Return ``'green' | 'yellow' | 'red'`` for DAQ slot usage.

    Spec §Threshold Contract:
        ``< 75%`` -> green, ``75..95%`` -> yellow, ``> 95%`` -> red.

    ``daq_slot_usage`` returns ``100.0`` for missing/zero capacity, so
    that case naturally lands in red.
    """
    if pct < thresholds.DAQ_SLOT_GREEN_MAX_PCT:
        return "green"
    if pct > thresholds.DAQ_SLOT_YELLOW_MAX_PCT:
        return "red"
    return "yellow"


def band_record_duration_s(seconds: float) -> str:
    """Return ``'green' | 'yellow' | 'red'`` for estimated record duration.

    Spec §Threshold Contract:
        ``> 4 h`` -> green, ``30 min..4 h`` -> yellow, ``< 30 min`` -> red.
    """
    if seconds > thresholds.RECORD_DURATION_GREEN_MIN_S:
        return "green"
    if seconds < thresholds.RECORD_DURATION_YELLOW_MIN_S:
        return "red"
    return "yellow"


def band_ring_buffer(pct: float) -> str:
    """Return ``'green' | 'yellow' | 'red'`` for ring-buffer fill.

    Spec §Threshold Contract:
        ``0..50%`` -> green, ``50..70%`` -> yellow, ``>= 70%`` -> red.
    """
    if pct < thresholds.RING_BUFFER_GREEN_MAX_PCT:
        return "green"
    if pct < thresholds.RING_BUFFER_YELLOW_LOW_MAX_PCT:
        return "yellow"
    return "red"


def band_dropped_frames(count: int) -> str:
    """Return ``'green' | 'yellow' | 'red'`` for dropped-frame count.

    Spec §Threshold Contract:
        ``0`` -> green, ``1..10`` -> yellow, ``> 10`` -> red.
    """
    if count <= 0:
        return "green"
    if count <= thresholds.DROPPED_FRAMES_YELLOW_MAX_PER_WINDOW:
        return "yellow"
    return "red"


def band_rec_last_rx_age_s(age_s: float) -> str:
    """Return ``'green' | 'yellow' | 'red'`` for REC last-rx age.

    Spec §Health Snapshot Model Contract:
        ``< 1 s`` -> green, ``1..2 s`` -> yellow, ``>= 2 s`` -> red.
    """
    if age_s >= thresholds.REC_LAST_RX_RED_MIN_S:
        return "red"
    if age_s >= thresholds.REC_LAST_RX_YELLOW_MIN_S:
        return "yellow"
    return "green"


def band_sample_events_per_s(events_per_s: float) -> str:
    """Return ``'green' | 'yellow' | 'red'`` for sample-events row.

    Spec §Threshold Contract:
        ``< 30 k`` -> green, ``30..80 k`` -> yellow, ``> 80 k`` -> red.

    Boundary semantics: green uses strict ``<``, red uses strict ``>``;
    exactly 30 000 and exactly 80 000 land in the inclusive yellow band.
    """
    if events_per_s < thresholds.SAMPLE_EVENTS_GREEN_MAX_PER_S:
        return "green"
    if events_per_s > thresholds.SAMPLE_EVENTS_YELLOW_MAX_PER_S:
        return "red"
    return "yellow"
