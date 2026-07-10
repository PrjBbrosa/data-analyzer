"""Escalation ladder tests (Spec §B5+B6 / plan Task B-3).

Pure view-model (:func:`escalation_state` / :func:`effective_chip_levels`)
plus the :class:`EscalationBar` overlay and the health-strip red pulse.

Severity is delegated to the existing band helpers (``band_dropped_frames``
1..10 yellow / >10 red, ``band_disk_remaining``, ``band_ring_buffer``) — no
new thresholds live here. Disk context is passed explicitly; the frozen
``HealthSnapshot`` gains no disk field.
"""

from __future__ import annotations

import time

from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    DaqHealth,
    HealthSnapshot,
    HwHealth,
    RecHealth,
    XcpHealth,
)
from mf4_analyzer.acquisition_ui.widgets.escalation_bar import (
    EscalationBar,
    EscalationState,
    effective_chip_levels,
    escalation_state,
)
from mf4_analyzer.acquisition_ui.widgets.health_strip import HealthStrip

GB = 1024 ** 3
MB = 1024 ** 2


def make_snapshot(*, dropped: int = 0, ring: float = 10.0, last_rx: float = 0.1) -> HealthSnapshot:
    """A green baseline snapshot with overridable REC-relevant fields."""
    return HealthSnapshot(
        hw=HwHealth(
            ok=True,
            driver_version="test",
            channel_count=1,
            last_probe_ts=time.monotonic(),
            error=None,
        ),
        can=CanHealth(bus_load_pct=10.0),
        xcp=XcpHealth(connected=True, slave_id=0x55),
        daq=DaqHealth(event_capacity={"event_10ms": 32}, event_used={"event_10ms": 1}),
        rec=RecHealth(
            state="recording",
            ring_buffer_fill_pct=ring,
            dropped_frames=dropped,
            write_rate_bps=0.0,
            last_rx_age_s=last_rx,
            writer_thread_alive=True,
        ),
        captured_at=time.monotonic(),
    )


def green_state() -> EscalationState:
    return escalation_state(make_snapshot(), disk_free_bytes=10 * GB)


def red_state(reason: str) -> EscalationState:
    if reason == "disk":
        return escalation_state(make_snapshot(), disk_free_bytes=512 * MB)
    if reason == "dropped":
        return escalation_state(make_snapshot(dropped=12), disk_free_bytes=10 * GB)
    if reason == "ring":
        return escalation_state(make_snapshot(ring=90.0), disk_free_bytes=10 * GB)
    raise ValueError(reason)


def make_escalation_widgets(qtbot):
    """A wired strip+bar: applying the bar drives the strip's pulse/summary.

    This mirrors the production wiring in ``CockpitMainWindow._build_ui``
    (``bar.applied`` → ``strip.apply_escalation``) so ``bar.apply(state)`` is
    a single entry point.
    """
    strip = HealthStrip()
    bar = EscalationBar()
    qtbot.addWidget(strip)
    qtbot.addWidget(bar)
    strip.resize(760, 42)
    strip.show()
    strip.apply_snapshot(make_snapshot())
    bar.applied.connect(strip.apply_escalation)
    bar.details_requested.connect(strip.open_chip_detail)
    return strip, bar


# ---------------------------------------------------------------------------
# Pure view-model (plan Step 1: five escalation assertions)
# ---------------------------------------------------------------------------


def test_dropped_frames_escalates_to_yellow():
    state = escalation_state(make_snapshot(dropped=3, ring=68.0), disk_free_bytes=10 * GB)
    assert state.level == "yellow"
    assert {issue.source_chip for issue in state.issues} == {"REC"}


def test_dropped_over_ten_is_red():
    assert escalation_state(
        make_snapshot(dropped=12, ring=10.0), disk_free_bytes=10 * GB
    ).level == "red"


def test_low_disk_escalates_to_red():
    state = escalation_state(make_snapshot(), disk_free_bytes=512 * MB)
    assert state.level == "red" and any("磁盘" in i.message for i in state.issues)
    assert effective_chip_levels(make_snapshot(), state)["REC"] == "red"


def test_write_rate_never_treated_as_bytes():
    # A huge samples/s write-rate must not create a disk issue nor change the
    # escalation level: disk severity comes from band_disk_remaining(bytes),
    # never from write_rate_bps.
    snap = make_snapshot()
    hot = HealthSnapshot(
        hw=snap.hw,
        can=snap.can,
        xcp=snap.xcp,
        daq=snap.daq,
        rec=RecHealth(
            state="recording",
            ring_buffer_fill_pct=10.0,
            dropped_frames=0,
            write_rate_bps=999_999.0,  # samples/s, NOT bytes/s
            last_rx_age_s=0.1,
            writer_thread_alive=True,
        ),
        captured_at=time.monotonic(),
    )
    assert escalation_state(hot, disk_free_bytes=10 * GB).level == "green"


def test_effective_chip_levels_only_escalates_rec():
    # A green snapshot with a red disk context lights REC red but leaves the
    # other four chips at their snapshot level.
    snap = make_snapshot()
    state = escalation_state(snap, disk_free_bytes=512 * MB)
    eff = effective_chip_levels(snap, state)
    assert eff["REC"] == "red"
    assert eff["HW"] == "green" and eff["CAN"] == "green"
    assert eff["XCP"] == "green" and eff["DAQ"] == "green"


# ---------------------------------------------------------------------------
# EscalationBar overlay + ack/recovery/re-arm + red pulse
# ---------------------------------------------------------------------------


def test_ack_collapses_banner_but_recovery_rearms_it(qtbot):
    strip, bar = make_escalation_widgets(qtbot)
    bar.apply(red_state("disk"))
    bar.acknowledge()
    assert bar.is_collapsed and strip.summary_text() == "1 项严重"
    bar.apply(green_state())
    assert bar.isHidden()
    assert strip._summary.isHidden()
    bar.apply(red_state("disk"))
    assert not bar.is_collapsed


def test_ack_stays_collapsed_for_same_reason(qtbot):
    strip, bar = make_escalation_widgets(qtbot)
    bar.apply(red_state("disk"))
    bar.acknowledge()
    # Same reason keeps the banner collapsed (the user dismissed it).
    bar.apply(red_state("disk"))
    assert bar.is_collapsed and bar.isHidden()


def test_reason_change_rearms_collapsed_banner(qtbot):
    strip, bar = make_escalation_widgets(qtbot)
    bar.apply(red_state("disk"))
    bar.acknowledge()
    # A DIFFERENT red reason re-arms even without an intervening green.
    bar.apply(red_state("dropped"))
    assert not bar.is_collapsed and not bar.isHidden()


def test_red_pulse_runs_three_loops_then_stops(qtbot):
    strip, bar = make_escalation_widgets(qtbot)
    rec_chip = strip.chip("REC")
    bar.apply(red_state("disk"))
    assert rec_chip.pulse_animation.loopCount() == 3


def test_green_recovery_hides_bar_and_stops_pulse(qtbot):
    strip, bar = make_escalation_widgets(qtbot)
    rec_chip = strip.chip("REC")
    bar.apply(red_state("disk"))
    assert not bar.isHidden()
    bar.apply(green_state())
    assert bar.isHidden()
    assert strip._summary.isHidden()
    assert rec_chip.pulse_animation.state() == rec_chip.pulse_animation.Stopped


def test_yellow_overflow_is_counted_and_details_open_worst_chip(qtbot):
    """B6: third+ issue remains discoverable through ``另 N 项 · 查看``."""
    strip, bar = make_escalation_widgets(qtbot)
    state = escalation_state(
        make_snapshot(dropped=3, ring=60.0, last_rx=1.2),
        disk_free_bytes=10 * GB,
    )
    assert len(state.issues) == 3

    bar.apply(state)

    assert state.level == "yellow"
    assert strip.summary_text() == "3 项需注意"
    assert strip.chip("REC").property("level") == "yellow"
    assert "另 1 项" in bar.message_text()
    assert bar.details_button.isVisible()

    bar.details_button.click()
    assert strip.active_chip() == "REC"
    assert strip.detail_popover is not None
    assert strip.detail_popover.isVisible()
