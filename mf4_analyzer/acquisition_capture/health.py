"""Health snapshot model for the Acquisition Cockpit.

Spec: §Health Snapshot Model Contract.

These dataclasses are populated by ``HealthAggregator`` (or by hand in
tests) and the level helpers return ``'green' | 'yellow' | 'red' | 'off'``.
The UI must NOT compute chip color from free-form strings; it consumes the
``level()`` helper here.

Note: ``HwHealth`` is a non-Windows-host stub by default on macOS — Vector
driver probing only works on Windows + python-can's Vector backend. The
``HealthAggregator`` factory below returns the stub on non-Windows hosts;
Stage 8 replaces it with a real probe.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Callable, Literal

from mf4_analyzer.acquisition_capture import thresholds

HealthLevel = Literal["green", "yellow", "red", "off"]


# ---------------------------------------------------------------------------
# Dataclasses (frozen — snapshots are value-objects).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChannelHealth:
    channel_id: str
    bus_load_pct: float | None
    error: str | None = None


@dataclass(frozen=True)
class HwHealth:
    ok: bool
    driver_version: str | None
    channel_count: int
    last_probe_ts: float  # monotonic seconds
    error: str | None = None


@dataclass(frozen=True)
class CanHealth:
    bus_load_pct: float | None
    channels: tuple[ChannelHealth, ...] = ()
    bus_error_count: int = 0


@dataclass(frozen=True)
class XcpHealth:
    connected: bool
    slave_id: int | None = None
    last_response_age_s: float | None = None
    consecutive_timeouts: int = 0


@dataclass(frozen=True)
class DaqHealth:
    event_capacity: Mapping[str, int] = field(default_factory=dict)
    event_used: Mapping[str, int] = field(default_factory=dict)
    overflow: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecHealth:
    state: Literal["off", "recording", "auto_stopped", "error"]
    ring_buffer_fill_pct: float
    dropped_frames: int
    write_rate_bps: float
    last_rx_age_s: float
    writer_thread_alive: bool


# ---------------------------------------------------------------------------
# Level helpers — every chip in the UI reads through these functions.
# ---------------------------------------------------------------------------


def level_hw(snap: HwHealth, *, now: float | None = None,
             poll_interval_s: float = thresholds.HEALTH_POLL_INTERVAL_S) -> HealthLevel:
    if snap.error is not None:
        return "red"
    if now is None:
        now = time.monotonic()
    if now - snap.last_probe_ts > thresholds.HEALTH_STALE_FACTOR * poll_interval_s:
        return "off"
    return "green" if snap.ok else "red"


def level_can(snap: CanHealth) -> HealthLevel:
    if snap.bus_load_pct is None:
        return "off"
    if any(level_channel(c) == "red" for c in snap.channels):
        return "red"
    if snap.bus_load_pct >= thresholds.CAN_LOAD_YELLOW_MAX_PCT:
        return "red"
    if snap.bus_load_pct >= thresholds.CAN_LOAD_GREEN_MAX_PCT:
        return "yellow"
    return "green"


def level_channel(ch: ChannelHealth) -> HealthLevel:
    if ch.error is not None:
        return "red"
    if ch.bus_load_pct is None:
        return "off"
    if ch.bus_load_pct >= thresholds.CAN_LOAD_YELLOW_MAX_PCT:
        return "red"
    if ch.bus_load_pct >= thresholds.CAN_LOAD_GREEN_MAX_PCT:
        return "yellow"
    return "green"


def level_xcp(snap: XcpHealth) -> HealthLevel:
    if not snap.connected:
        return "red"
    if snap.consecutive_timeouts >= thresholds.XCP_RED_TIMEOUTS:
        return "red"
    if snap.consecutive_timeouts >= thresholds.XCP_YELLOW_TIMEOUTS:
        return "yellow"
    return "green"


def level_daq(snap: DaqHealth) -> HealthLevel:
    return "red" if snap.overflow else "green"


def level_rec(snap: RecHealth) -> HealthLevel:
    if snap.state == "error":
        return "red"
    if snap.last_rx_age_s >= thresholds.REC_LAST_RX_RED_MIN_S:
        return "red"
    if snap.ring_buffer_fill_pct >= thresholds.RING_BUFFER_RED_MAX_PCT:
        return "red"
    if (snap.ring_buffer_fill_pct >= thresholds.RING_BUFFER_YELLOW_LOW_MAX_PCT
            or snap.last_rx_age_s >= thresholds.REC_LAST_RX_YELLOW_MIN_S):
        return "yellow"
    if not snap.writer_thread_alive and snap.state == "recording":
        return "red"
    return "green"


# ---------------------------------------------------------------------------
# Aggregated five-chip snapshot.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthSnapshot:
    hw: HwHealth
    can: CanHealth
    xcp: XcpHealth
    daq: DaqHealth
    rec: RecHealth
    captured_at: float

    def levels(self) -> dict[str, HealthLevel]:
        return {
            "HW": level_hw(self.hw),
            "CAN": level_can(self.can),
            "XCP": level_xcp(self.xcp),
            "DAQ": level_daq(self.daq),
            "REC": level_rec(self.rec),
        }


# ---------------------------------------------------------------------------
# Hw probe stub for non-Windows hosts.
# ---------------------------------------------------------------------------


def probe_hw_macos_stub() -> HwHealth:
    """Return the canonical macOS/Linux stub HwHealth.

    Spec §Tasks (Stage 2): "macOS-friendly stub that returns
    ``ok=False, error='non-windows host'``." Stage 8 replaces this on
    Windows.
    """
    return HwHealth(
        ok=False,
        driver_version=None,
        channel_count=0,
        last_probe_ts=time.monotonic(),
        error="non-windows host",
    )


def _default_hw_probe() -> HwHealth:
    if sys.platform.startswith("win"):
        # Stage 8 wires this through ``can_logger.p0.vector_probe`` once
        # the Windows hardware gate is open. Today we still return the
        # macOS stub shape for safety; Stage 8 swaps this implementation.
        return HwHealth(
            ok=False,
            driver_version=None,
            channel_count=0,
            last_probe_ts=time.monotonic(),
            error="vector probe not wired (Stage 8)",
        )
    return probe_hw_macos_stub()


# ---------------------------------------------------------------------------
# HealthAggregator — pulls snapshots on a fixed cadence.
# ---------------------------------------------------------------------------


HwProbe = Callable[[], HwHealth]
RecProbe = Callable[[], RecHealth]
CanProbe = Callable[[], CanHealth]
XcpProbe = Callable[[], XcpHealth]
DaqProbe = Callable[[], DaqHealth]


class HealthAggregator:
    """Polls each subsystem and exposes the latest ``HealthSnapshot``.

    The aggregator is deliberately synchronous: ``poll_once()`` is the
    canonical way to get a fresh snapshot, and the UI calls it from a
    QTimer (Stage 4) rather than running the aggregator on its own thread.
    This keeps the capture core Qt-free.

    Subscribers can attach ``on_change`` callbacks (any callable) that
    are invoked whenever the aggregated level-tuple changes between
    polls — this gives Stage 4 a simple bridge to wire into Qt signals
    without polluting the capture core with Qt imports.
    """

    def __init__(
        self,
        *,
        hw_probe: HwProbe | None = None,
        can_probe: CanProbe | None = None,
        xcp_probe: XcpProbe | None = None,
        daq_probe: DaqProbe | None = None,
        rec_probe: RecProbe | None = None,
    ) -> None:
        self._hw_probe = hw_probe or _default_hw_probe
        self._can_probe = can_probe or (lambda: CanHealth(bus_load_pct=None))
        self._xcp_probe = xcp_probe or (lambda: XcpHealth(connected=False))
        self._daq_probe = daq_probe or (lambda: DaqHealth())
        self._rec_probe = rec_probe or (
            lambda: RecHealth(
                state="off",
                ring_buffer_fill_pct=0.0,
                dropped_frames=0,
                write_rate_bps=0.0,
                last_rx_age_s=0.0,
                writer_thread_alive=False,
            )
        )
        self._last: HealthSnapshot | None = None
        self._subscribers: list[Callable[[HealthSnapshot], None]] = []

    def subscribe(self, callback: Callable[[HealthSnapshot], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    def poll_once(self) -> HealthSnapshot:
        snap = HealthSnapshot(
            hw=self._hw_probe(),
            can=self._can_probe(),
            xcp=self._xcp_probe(),
            daq=self._daq_probe(),
            rec=self._rec_probe(),
            captured_at=time.monotonic(),
        )
        previous_levels = None if self._last is None else self._last.levels()
        self._last = snap
        if previous_levels != snap.levels():
            for cb in list(self._subscribers):
                cb(snap)
        return snap

    @property
    def last(self) -> HealthSnapshot | None:
        return self._last
