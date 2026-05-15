"""Right-panel binding tests (Stage 4, CR2 fix #2).

Pins:

- ``IdlePreflightPage.apply`` delegates DAQ slot percent to the pure
  function ``mf4_analyzer.acquisition_capture.preflight_estimates.daq_slot_usage``.
- Disk-remaining and total sample-events / second rows delegate to
  ``band_disk_remaining`` and ``band_sample_events_per_s`` (S3 helpers).

These are spec §Preflight Computation Contract bindings — no widget-
local copy of the formulas. The DAQ percent fallback used to live in
``right_panel.py`` lines 252-276; that path now routes through the
pure helper.
"""

from __future__ import annotations

from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    DaqHealth,
    HealthSnapshot,
    HwHealth,
    RecHealth,
    XcpHealth,
)
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_ui.widgets import right_panel as rp_module
from mf4_analyzer.acquisition_ui.widgets.right_panel import RightPanel


def _make_selection(events: list[str | None]) -> list[SelectedMeasurement]:
    return [
        SelectedMeasurement(
            name=f"sig{i}",
            unit="",
            event=ev,
            event_rate_hz=100.0,
            payload_bytes=4,
        )
        for i, ev in enumerate(events)
    ]


def _snapshot(*, can_load: float | None = 42.0) -> HealthSnapshot:
    return HealthSnapshot(
        hw=HwHealth(
            ok=True,
            driver_version="test",
            channel_count=1,
            last_probe_ts=1.0,
        ),
        can=CanHealth(bus_load_pct=can_load),
        xcp=XcpHealth(connected=True),
        daq=DaqHealth(),
        rec=RecHealth(
            state="recording",
            ring_buffer_fill_pct=71.0,
            dropped_frames=3,
            write_rate_bps=2048.0,
            last_rx_age_s=1.25,
            writer_thread_alive=True,
        ),
        captured_at=1.0,
    )


def test_idle_page_delegates_daq_slot_usage(qapp, monkeypatch):
    """The DAQ slot row must call into ``daq_slot_usage`` for every
    distinct event in the selection."""
    panel = RightPanel()
    selection = _make_selection(["event_10ms", "event_10ms", "event_100ms"])
    event_capacity = {"event_10ms": 8, "event_100ms": 4}

    call_log: list[tuple[str, tuple, dict]] = []

    def spy_daq(event_name, selected, capacity):
        call_log.append((event_name, tuple(selected), dict(capacity)))
        # Return a deterministic value distinct per event so the worst
        # is identifiable.
        return 90.0 if event_name == "event_10ms" else 25.0

    monkeypatch.setattr(rp_module, "daq_slot_usage", spy_daq)

    panel.show_idle(
        selection=selection,
        event_capacity=event_capacity,
        disk_free_bytes=10 * 1024 ** 3,
    )

    # Spy was invoked once per unique event (two events).
    event_names = sorted({call[0] for call in call_log})
    assert event_names == ["event_100ms", "event_10ms"]
    assert len(call_log) == 2

    # And the selection / capacity passed through verbatim.
    for event_name, selected, capacity in call_log:
        assert capacity == event_capacity
        assert tuple(selected) == tuple(selection)

    # Worst percent (90.0) drives the rendered chip — sanity check the
    # rendered label contains "90.0%".
    rendered = panel.idle_page._row_daq.text()
    assert "90.0%" in rendered
    panel.close()


def test_idle_page_delegates_can_daq_and_duration_band_helpers(qapp, monkeypatch):
    """CAN, DAQ, and record-duration band colors come from shared helpers."""
    panel = RightPanel()
    selection = _make_selection(["event_10ms", "event_10ms"])
    event_capacity = {"event_10ms": 4}

    can_calls: list[float] = []
    daq_calls: list[float] = []
    duration_calls: list[float] = []

    monkeypatch.setattr(rp_module, "estimate_can_bus_load", lambda *args: 61.0)
    monkeypatch.setattr(rp_module, "daq_slot_usage", lambda *args: 80.0)
    monkeypatch.setattr(rp_module, "estimate_throughput_bps", lambda *args: 2.0)

    def spy_can(pct):
        can_calls.append(pct)
        return "yellow"

    def spy_daq(pct):
        daq_calls.append(pct)
        return "red"

    def spy_duration(seconds):
        duration_calls.append(seconds)
        return "green"

    monkeypatch.setattr(rp_module, "band_can_load", spy_can)
    monkeypatch.setattr(rp_module, "band_daq_slot", spy_daq)
    monkeypatch.setattr(rp_module, "band_record_duration_s", spy_duration)

    panel.show_idle(
        selection=selection,
        event_capacity=event_capacity,
        disk_free_bytes=120,
    )

    assert can_calls == [61.0]
    assert daq_calls == [80.0]
    assert duration_calls == [60.0]
    assert "61.0%" in panel.idle_page._row_can.text()
    assert "80.0%" in panel.idle_page._row_daq.text()
    assert "1.0 min" in panel.idle_page._row_duration.text()
    panel.close()


def test_idle_page_delegates_disk_and_sample_band_helpers(qapp, monkeypatch):
    """Disk-remaining and sample-events rows route through the S3 band
    helpers — not a widget-local band ladder."""
    panel = RightPanel()
    selection = _make_selection(["event_10ms", "event_10ms"])
    event_capacity = {"event_10ms": 8}

    disk_calls: list[int] = []
    sample_calls: list[float] = []

    def spy_disk(bytes_free):
        disk_calls.append(bytes_free)
        return "yellow"

    def spy_sample(events_per_s):
        sample_calls.append(events_per_s)
        return "red"

    monkeypatch.setattr(rp_module, "band_disk_remaining", spy_disk)
    monkeypatch.setattr(rp_module, "band_sample_events_per_s", spy_sample)

    panel.show_idle(
        selection=selection,
        event_capacity=event_capacity,
        disk_free_bytes=2 * 1024 ** 3,
    )

    # Disk helper called with the byte count we passed in.
    assert disk_calls == [2 * 1024 ** 3]
    # Sample helper called with the summed event_rate_hz for events != None.
    # Two measurements × 100 Hz each = 200.0.
    assert sample_calls == [200.0]
    panel.close()


def test_recording_page_delegates_quality_band_helpers(qapp, monkeypatch):
    """Recording-quality color rows use shared band helpers."""
    panel = RightPanel()
    snap = _snapshot(can_load=64.0)

    ring_calls: list[float] = []
    dropped_calls: list[int] = []
    can_calls: list[float] = []
    rx_calls: list[float] = []
    disk_calls: list[int] = []

    def spy_ring(pct):
        ring_calls.append(pct)
        return "yellow"

    def spy_dropped(count):
        dropped_calls.append(count)
        return "red"

    def spy_can(pct):
        can_calls.append(pct)
        return "yellow"

    def spy_rx(age_s):
        rx_calls.append(age_s)
        return "yellow"

    def spy_disk(bytes_free):
        disk_calls.append(bytes_free)
        return "green"

    monkeypatch.setattr(rp_module, "band_ring_buffer", spy_ring)
    monkeypatch.setattr(rp_module, "band_dropped_frames", spy_dropped)
    monkeypatch.setattr(rp_module, "band_can_load", spy_can)
    monkeypatch.setattr(rp_module, "band_rec_last_rx_age_s", spy_rx)
    monkeypatch.setattr(rp_module, "band_disk_remaining", spy_disk)

    panel.show_recording(snapshot=snap, disk_free_bytes=7 * 1024 ** 3)

    assert ring_calls == [71.0]
    assert dropped_calls == [3]
    assert can_calls == [64.0]
    assert rx_calls == [1.25]
    assert disk_calls == [7 * 1024 ** 3]
    assert "71.0%" in panel.recording_page._row_ring.text()
    assert "3" in panel.recording_page._row_dropped.text()
    assert "64.0%" in panel.recording_page._row_can.text()
    assert "1.25 s" in panel.recording_page._row_rx_age.text()
    panel.close()


def test_idle_page_delegates_sample_events_estimator(qapp, monkeypatch):
    """The total sample-events estimator must come from the pure
    function, not a widget-local sum-comprehension."""
    panel = RightPanel()
    selection = _make_selection(["event_10ms", None, "event_50ms"])
    event_capacity = {"event_10ms": 8, "event_50ms": 4}

    sample_calls: list[tuple] = []

    def spy_estimator(selected):
        sample_calls.append(tuple(selected))
        return 12345.0

    monkeypatch.setattr(rp_module, "estimate_sample_events_per_s", spy_estimator)

    panel.show_idle(
        selection=selection,
        event_capacity=event_capacity,
        disk_free_bytes=10 * 1024 ** 3,
    )

    # Spy called exactly once with the full selection.
    assert len(sample_calls) == 1
    assert sample_calls[0] == tuple(selection)
    # The rendered label quotes 12345 (no decimals — format string is
    # ``{events_per_s:.0f}``).
    rendered = panel.idle_page._row_samples.text()
    assert "12345" in rendered
    panel.close()


def test_idle_page_handles_empty_selection(qapp):
    """No selection → all five rows show off-band em dashes; preflight
    helpers are not invoked."""
    panel = RightPanel()
    panel.show_idle(
        selection=[],
        event_capacity={},
        disk_free_bytes=10 * 1024 ** 3,
    )
    note_text = panel.idle_page._note.text()
    assert "尚未选择测量" in note_text
    # Daq row reads "—" (off color).
    assert "—" in panel.idle_page._row_daq.text()
    panel.close()


def test_idle_page_zero_capacity_event_renders_red_100(qapp):
    """Unknown/zero-capacity event drives the DAQ row to 100% (red) —
    this is the ``daq_slot_usage`` contract, exercised end-to-end through
    the widget without monkeypatching."""
    panel = RightPanel()
    # Event present in selection but absent from capacity map.
    selection = _make_selection(["mystery_event"])
    panel.show_idle(
        selection=selection,
        event_capacity={},  # zero capacity for "mystery_event"
        disk_free_bytes=10 * 1024 ** 3,
    )
    rendered = panel.idle_page._row_daq.text()
    assert "100.0%" in rendered
    # Red color token per ``_LEVEL_COLOR``.
    assert rp_module._LEVEL_COLOR["red"] in rendered
    panel.close()
