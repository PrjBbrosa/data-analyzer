"""Health-strip tests (Stage 4).

Spec §Health Snapshot Model Contract requires the REC chip turns
red when ``last_rx_age_s >= 2.0`` even with an empty ring buffer.
This file pins that contract on the widget side; the dataclass
helper is already pinned in
``tests/test_acquisition_capture_health.py``.
"""

from __future__ import annotations

import time

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    DaqHealth,
    HealthSnapshot,
    HwHealth,
    RecHealth,
    XcpHealth,
)
from mf4_analyzer.acquisition_ui.widgets.health_strip import HealthStrip


def _snap(**overrides) -> HealthSnapshot:
    base = dict(
        hw=HwHealth(
            ok=True,
            driver_version="test",
            channel_count=1,
            last_probe_ts=time.monotonic(),
            error=None,
        ),
        can=CanHealth(bus_load_pct=10.0, channels=(), bus_error_count=0),
        xcp=XcpHealth(connected=True, slave_id=0x55),
        daq=DaqHealth(event_capacity={"event_10ms": 32}, event_used={"event_10ms": 1}),
        rec=RecHealth(
            state="recording",
            ring_buffer_fill_pct=10.0,
            dropped_frames=0,
            write_rate_bps=0.0,
            last_rx_age_s=0.1,
            writer_thread_alive=True,
        ),
        captured_at=time.monotonic(),
    )
    base.update(overrides)
    return HealthSnapshot(**base)


def test_strip_all_green(qapp):
    strip = HealthStrip()
    strip.apply_snapshot(_snap())
    levels = strip.current_levels()
    assert levels == {
        "HW": "green",
        "CAN": "green",
        "XCP": "green",
        "DAQ": "green",
        "REC": "green",
    }


def test_strip_rec_red_on_stale_rx(qapp):
    """Spec watchdog rule: last_rx_age_s ≥ 2.0 ⇒ REC red.

    Also verifies the ring fill is irrelevant for this transition.
    """
    strip = HealthStrip()
    snap = _snap(
        rec=RecHealth(
            state="recording",
            ring_buffer_fill_pct=0.0,  # empty
            dropped_frames=0,
            write_rate_bps=0.0,
            last_rx_age_s=2.5,  # well past the red threshold
            writer_thread_alive=True,
        )
    )
    strip.apply_snapshot(snap)
    assert strip.current_levels()["REC"] == "red"


def test_strip_emits_levels_changed_on_transition(qapp):
    strip = HealthStrip()
    fired = []
    strip.levels_changed.connect(lambda d: fired.append(d))
    strip.apply_snapshot(_snap())
    assert len(fired) == 1
    # Re-applying the same snapshot does NOT re-emit.
    strip.apply_snapshot(_snap())
    assert len(fired) == 1
    # Changing one chip emits again.
    strip.apply_snapshot(
        _snap(can=CanHealth(bus_load_pct=85.0))
    )
    assert len(fired) == 2
    assert fired[-1]["CAN"] == "red"


def test_strip_tooltip_quotes_backing_field(qapp):
    strip = HealthStrip()
    strip.apply_snapshot(_snap())
    # HW tooltip quotes driver_version + channel_count.
    hw_chip = strip.chip("HW")
    assert "driver test" in hw_chip.toolTip()
    # CAN tooltip quotes bus_load_pct.
    can_chip = strip.chip("CAN")
    assert "bus load" in can_chip.toolTip()


def test_strip_off_chip_when_no_evidence(qapp):
    strip = HealthStrip()
    snap = _snap(
        can=CanHealth(bus_load_pct=None),
    )
    strip.apply_snapshot(snap)
    assert strip.current_levels()["CAN"] == "off"
    assert "no evidence yet" in strip.chip("CAN").toolTip()


def test_threshold_constants_drive_band_boundaries():
    """Belt-and-braces: the band edges in the dataclass helpers are
    the same constants the strip relies on. Failing this test means
    a refactor moved a literal somewhere the widget reads.
    """
    assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0
    assert thresholds.CAN_LOAD_YELLOW_MAX_PCT == 80.0
    assert thresholds.REC_LAST_RX_RED_MIN_S == 2.0
