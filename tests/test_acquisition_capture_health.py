"""Tests for the health snapshot dataclasses and level helpers.

Two load-bearing assertions:
- Watchdog rule: ``last_rx_age_s >= 2.0`` ⇒ ``level_rec == 'red'``.
- ``HwHealth`` macOS stub returns ``ok=False, error='non-windows host'``.
"""

from __future__ import annotations

import sys
import time

import pytest

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    ChannelHealth,
    DaqHealth,
    HealthAggregator,
    HwHealth,
    RecHealth,
    XcpHealth,
    level_can,
    level_channel,
    level_daq,
    level_hw,
    level_rec,
    level_xcp,
    probe_hw_macos_stub,
)
from mf4_analyzer.acquisition_capture.session import SessionConfig, SelectedMeasurement


# ---------------------------------------------------------------------------
# Health poll cadence — caller-driven, constant binding pinned here.
# ---------------------------------------------------------------------------


def test_health_poll_interval_constant_binding(tmp_path):
    """Spec §Health Snapshot Model Contract: cadence lives in thresholds.

    ``HealthAggregator`` is deliberately caller-driven — it exposes
    ``poll_once()`` and does NOT own a timer. Stage 4's Cockpit
    QTimer (and the CLI main loop) drive invocations at
    ``thresholds.HEALTH_POLL_INTERVAL_S`` = 0.5 s. This test pins the
    constant binding: a regression that hard-codes 0.5 somewhere else
    (or drifts the default off the thresholds module) will fail here.
    """
    # 1) The constant itself is 0.5 s.
    assert thresholds.HEALTH_POLL_INTERVAL_S == 0.5
    # 2) ``SessionConfig.poll_interval_s`` default resolves to the
    #    thresholds-module constant, not to a duplicated literal.
    config = SessionConfig(
        output_mf4=tmp_path / "binding.mf4",
        selected=(SelectedMeasurement(name="X"),),
    )
    assert config.poll_interval_s == thresholds.HEALTH_POLL_INTERVAL_S


# ---------------------------------------------------------------------------
# HwHealth — stub on non-Windows.
# ---------------------------------------------------------------------------


def test_hw_macos_stub_returns_expected_shape():
    snap = probe_hw_macos_stub()
    assert snap.ok is False
    assert snap.error == "non-windows host"
    assert snap.channel_count == 0
    assert snap.driver_version is None
    # last_probe_ts populated by monotonic clock.
    assert snap.last_probe_ts > 0


def test_hw_macos_stub_levels_to_red():
    snap = probe_hw_macos_stub()
    assert level_hw(snap) == "red"


def test_hw_ok_no_error_levels_to_green():
    snap = HwHealth(ok=True, driver_version="x.y", channel_count=2, last_probe_ts=time.monotonic())
    assert level_hw(snap) == "green"


def test_hw_stale_probe_levels_to_off():
    """last_probe_ts older than 2 * poll_interval ⇒ off."""
    old = time.monotonic() - 5.0 * thresholds.HEALTH_POLL_INTERVAL_S
    snap = HwHealth(ok=True, driver_version="x", channel_count=1, last_probe_ts=old)
    assert level_hw(snap) == "off"


# ---------------------------------------------------------------------------
# CanHealth.
# ---------------------------------------------------------------------------


def test_can_levels_by_bus_load():
    assert level_can(CanHealth(bus_load_pct=None)) == "off"
    assert level_can(CanHealth(bus_load_pct=10.0)) == "green"
    assert level_can(CanHealth(bus_load_pct=60.0)) == "yellow"
    assert level_can(CanHealth(bus_load_pct=79.9)) == "yellow"
    assert level_can(CanHealth(bus_load_pct=80.0)) == "red"


def test_can_red_channel_propagates_to_aggregate():
    err = ChannelHealth(channel_id="ch1", bus_load_pct=10.0, error="bus off")
    snap = CanHealth(bus_load_pct=10.0, channels=(err,))
    assert level_can(snap) == "red"
    assert level_channel(err) == "red"


# ---------------------------------------------------------------------------
# XcpHealth.
# ---------------------------------------------------------------------------


def test_xcp_levels_by_timeouts():
    assert level_xcp(XcpHealth(connected=False)) == "red"
    assert level_xcp(XcpHealth(connected=True, consecutive_timeouts=0)) == "green"
    assert level_xcp(XcpHealth(connected=True, consecutive_timeouts=1)) == "yellow"
    assert level_xcp(XcpHealth(connected=True, consecutive_timeouts=2)) == "yellow"
    assert level_xcp(XcpHealth(connected=True, consecutive_timeouts=3)) == "red"


def test_level_no_evidence_maps_to_off():
    hw = HwHealth(
        ok=False,
        driver_version=None,
        channel_count=0,
        last_probe_ts=time.monotonic(),
        error="transport not configured",
        probed=False,
    )
    assert level_hw(hw) == "off"
    assert level_xcp(XcpHealth(connected=False, attempted=False)) == "off"
    assert level_xcp(XcpHealth(connected=False, attempted=True)) == "red"
    assert level_daq(DaqHealth()) == "off"
    rec = RecHealth(
        state="off",
        ring_buffer_fill_pct=0.0,
        dropped_frames=0,
        write_rate_bps=0.0,
        last_rx_age_s=0.0,
        writer_thread_alive=False,
        evidence=False,
    )
    assert level_rec(rec) == "off"


# ---------------------------------------------------------------------------
# DaqHealth.
# ---------------------------------------------------------------------------


def test_daq_green_unless_overflow():
    assert level_daq(DaqHealth(event_capacity={"event_10ms": 32})) == "green"
    assert level_daq(DaqHealth(overflow=("event_10ms",))) == "red"


# ---------------------------------------------------------------------------
# RecHealth — watchdog rule (load-bearing).
# ---------------------------------------------------------------------------


def test_rec_red_when_last_rx_age_at_or_above_2s():
    """Spec §Health Snapshot Model Contract: last_rx_age_s >= 2.0 ⇒ red."""
    snap = RecHealth(
        state="recording",
        ring_buffer_fill_pct=0.0,
        dropped_frames=0,
        write_rate_bps=0.0,
        last_rx_age_s=2.0,
        writer_thread_alive=True,
    )
    assert level_rec(snap) == "red"


def test_rec_yellow_when_last_rx_age_between_1_and_2():
    snap = RecHealth(
        state="recording",
        ring_buffer_fill_pct=0.0,
        dropped_frames=0,
        write_rate_bps=0.0,
        last_rx_age_s=1.5,
        writer_thread_alive=True,
    )
    assert level_rec(snap) == "yellow"


def test_rec_red_when_state_is_error():
    snap = RecHealth(
        state="error",
        ring_buffer_fill_pct=0.0,
        dropped_frames=0,
        write_rate_bps=0.0,
        last_rx_age_s=0.0,
        writer_thread_alive=True,
    )
    assert level_rec(snap) == "red"


def test_rec_red_when_ring_buffer_above_85():
    snap = RecHealth(
        state="recording",
        ring_buffer_fill_pct=86.0,
        dropped_frames=0,
        write_rate_bps=0.0,
        last_rx_age_s=0.0,
        writer_thread_alive=True,
    )
    assert level_rec(snap) == "red"


def test_rec_green_healthy_state():
    snap = RecHealth(
        state="recording",
        ring_buffer_fill_pct=30.0,
        dropped_frames=0,
        write_rate_bps=2000.0,
        last_rx_age_s=0.1,
        writer_thread_alive=True,
    )
    assert level_rec(snap) == "green"


# ---------------------------------------------------------------------------
# HealthAggregator.
# ---------------------------------------------------------------------------


def test_aggregator_default_probes_return_off_state():
    agg = HealthAggregator()
    snap = agg.poll_once()
    levels = snap.levels()
    # Hw on macOS returns ok=False (or vector probe not wired on Win) -> red.
    if sys.platform.startswith("win"):
        assert levels["HW"] == "red"
    else:
        assert levels["HW"] == "red"
    assert levels["CAN"] == "off"
    assert levels["XCP"] == "red"
    assert levels["DAQ"] == "off"
    assert levels["REC"] == "green"  # off-state with healthy defaults


def test_aggregator_subscriber_fires_on_level_change():
    snapshots: list[dict] = []
    agg = HealthAggregator()
    agg.subscribe(lambda snap: snapshots.append(snap.levels()))
    agg.poll_once()
    # No change between two consecutive polls of stable probes — no second fire.
    agg.poll_once()
    assert len(snapshots) == 1


def test_aggregator_subscriber_fires_on_xcp_transition():
    state = {"connected": False}

    def xcp_probe() -> XcpHealth:
        return XcpHealth(connected=state["connected"])

    snapshots: list[dict] = []
    agg = HealthAggregator(xcp_probe=xcp_probe)
    agg.subscribe(lambda snap: snapshots.append(snap.levels()))
    agg.poll_once()
    state["connected"] = True
    agg.poll_once()
    # Two level-transition emits (initial + xcp flip).
    assert len(snapshots) == 2
    assert snapshots[1]["XCP"] == "green"
