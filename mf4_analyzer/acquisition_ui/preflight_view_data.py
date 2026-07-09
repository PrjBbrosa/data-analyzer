"""Pure view-model for the record-preflight rows (Spec §B2).

A single ``build_preflight_rows`` produces the five preflight rows as
``(key, value, level)`` tuples, reusing the existing pure estimators and
band helpers in :mod:`mf4_analyzer.acquisition_capture.preflight_estimates`
(no new threshold judgments live here). Both consumers read from this one
function so the numbers can never drift:

- ``IdlePreflightPage`` (right pane, shared with the Replay tab) renders the
  rows into its existing metric labels.
- ``PreflightPill`` (health strip) drives its LED from the worst band and
  shows the same rows in the shared health popover.

This module is Qt-free and imports only the pure capture-layer helpers, so
it sits cleanly below both the acquisition UI and the ``ui_kit`` layers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mf4_analyzer.acquisition_capture import thresholds
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
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement

__all__ = [
    "build_preflight_rows",
    "worst_preflight_level",
    "_humanize_duration_s",
    "PREFLIGHT_ROW_KEYS",
]

# Row keys — identical to the ``IdlePreflightPage`` section titles so the
# right-pane rows and the pill popover rows are byte-for-byte the same
# ``(key, value, level)`` tuples (Spec §B2 same-source contract).
PREFLIGHT_ROW_KEYS: tuple[str, ...] = (
    "CAN 总线负载",
    "DAQ slot · ECU 端容量",
    "磁盘剩余",
    "采样事件 / 秒",
    "预计可录时长",
)

# Severity ranking used to pick the worst band for the pill LED. ``off``
# (no evidence / not-applicable) is the least severe so a real green row
# always lights the pill; red dominates everything.
_SEVERITY: dict[str, int] = {"off": 0, "green": 1, "yellow": 2, "red": 3}


def _humanize_duration_s(seconds: float) -> str:
    """Render a record-duration estimate compactly (min / h / d / ∞)."""
    if seconds == float("inf"):
        return "∞"
    if seconds < 90 * 60:
        return f"{seconds / 60:.1f} min"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def build_preflight_rows(
    selection: Sequence[SelectedMeasurement],
    event_capacity: Mapping[str, int],
    disk_free_bytes: int,
    *,
    bitrate_bps: int | None = None,
) -> list[tuple[str, str, str]]:
    """Return the five preflight rows as ``[(key, value, level)]``.

    The values/bands come straight from the pure estimators + band helpers
    (spec §Preflight Computation Contract). ``level`` is one of
    ``"green" | "yellow" | "red" | "off"``.

    Honesty tweak (Spec §B2): when the record-duration band is green the
    value is compressed to ``充足`` rather than an uninformative huge number
    (e.g. ``232.7 d``). Empty selections return five ``off`` em-dash rows.
    """
    if bitrate_bps is None:
        bitrate_bps = thresholds.DEFAULT_CAN_BITRATE_BPS

    if not selection:
        return [(key, "—", "off") for key in PREFLIGHT_ROW_KEYS]

    # 1) CAN bus load.
    can_pct = estimate_can_bus_load(selection, bitrate_bps)
    can_row = (PREFLIGHT_ROW_KEYS[0], f"{can_pct:.1f}%", band_can_load(can_pct))

    # 2) DAQ slot usage — worst of each distinct event's own capacity.
    worst_pct = 0.0
    events_seen: set[str] = set()
    for m in selection:
        if m.event is None or m.event in events_seen:
            continue
        events_seen.add(m.event)
        worst_pct = max(
            worst_pct,
            daq_slot_usage(m.event, selection, event_capacity),
        )
    if not events_seen:
        daq_row = (PREFLIGHT_ROW_KEYS[1], "—", "off")
    else:
        daq_row = (
            PREFLIGHT_ROW_KEYS[1],
            f"{worst_pct:.1f}%",
            band_daq_slot(worst_pct),
        )

    # 3) Disk remaining.
    disk_row = (
        PREFLIGHT_ROW_KEYS[2],
        f"{disk_free_bytes / (1024 ** 3):.2f} GB",
        band_disk_remaining(disk_free_bytes),
    )

    # 4) Total sample events / second.
    events_per_s = estimate_sample_events_per_s(selection)
    samples_row = (
        PREFLIGHT_ROW_KEYS[3],
        f"{events_per_s:.0f}",
        band_sample_events_per_s(events_per_s),
    )

    # 5) Estimated record duration (green → 充足, else humanized).
    throughput = estimate_throughput_bps(selection)
    duration_s = estimate_record_duration_s(throughput, disk_free_bytes)
    if duration_s == float("inf"):
        duration_row = (PREFLIGHT_ROW_KEYS[4], "∞", "off")
    else:
        d_level = band_record_duration_s(duration_s)
        d_value = "充足" if d_level == "green" else _humanize_duration_s(duration_s)
        duration_row = (PREFLIGHT_ROW_KEYS[4], d_value, d_level)

    return [can_row, daq_row, disk_row, samples_row, duration_row]


def worst_preflight_level(rows: Sequence[tuple[str, str, str]]) -> str:
    """Return the most-severe band across ``rows`` (red > yellow > green > off).

    Empty ``rows`` (no preflight computed) return ``off``.
    """
    if not rows:
        return "off"
    return max((level for _key, _value, level in rows), key=lambda l: _SEVERITY.get(l, 0))
