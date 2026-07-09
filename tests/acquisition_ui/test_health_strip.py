"""Health-strip tests (Stage 4).

Spec §Health Snapshot Model Contract requires the REC chip turns
red when ``last_rx_age_s >= 2.0`` even with an empty ring buffer.
This file pins that contract on the widget side; the dataclass
helper is already pinned in
``tests/test_acquisition_capture_health.py``.
"""

from __future__ import annotations

import time

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QKeyEvent, QMouseEvent
from PyQt5.QtWidgets import QLabel

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    ChannelHealth,
    DaqHealth,
    HealthSnapshot,
    HwHealth,
    RecHealth,
    XcpHealth,
)
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.widgets.health_popover import HealthPopover
from mf4_analyzer.acquisition_ui.widgets.health_strip import HealthChip, HealthStrip


def _chip_value(strip: HealthStrip, name: str) -> str:
    value = strip.chip(name).findChild(QLabel, "healthChipValue")
    assert value is not None
    return value.text()


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
    for name in strip.CHIP_NAMES:
        chip = strip.chip(name)
        assert chip.objectName() == "healthChip"
        assert chip.findChild(QLabel, "healthChipLed") is not None
        assert chip.findChild(QLabel, "healthChipLabel") is not None
        assert _chip_value(strip, name).strip()
    summary = strip.findChild(QLabel, "healthSummary")
    assert summary is not None
    assert summary.text().strip()


def test_strip_chip_values_come_from_snapshot_fields(qapp):
    strip = HealthStrip()
    strip.apply_snapshot(
        _snap(
            hw=HwHealth(
                ok=True,
                driver_version="VN1610",
                channel_count=2,
                last_probe_ts=time.monotonic(),
                error=None,
            ),
            can=CanHealth(
                bus_load_pct=22.0,
                channels=(
                    ChannelHealth(channel_id="CAN1", bus_load_pct=21.0),
                    ChannelHealth(channel_id="CAN2", bus_load_pct=22.0),
                ),
                bus_error_count=0,
            ),
            xcp=XcpHealth(connected=True, slave_id=0x55),
            daq=DaqHealth(
                event_capacity={"event_10ms": 32, "event_100ms": 16},
                event_used={"event_10ms": 7, "event_100ms": 5},
            ),
            rec=RecHealth(
                state="recording",
                ring_buffer_fill_pct=10.0,
                dropped_frames=0,
                write_rate_bps=0.0,
                last_rx_age_s=0.1,
                writer_thread_alive=True,
            ),
        )
    )

    assert _chip_value(strip, "HW") == "VN1610"
    assert _chip_value(strip, "CAN") == "2 ch online"
    assert "0x55" in _chip_value(strip, "XCP")
    assert "sig" in _chip_value(strip, "DAQ") or "/" in _chip_value(strip, "DAQ")
    assert (
        "recording" in _chip_value(strip, "REC")
        or "ready" in _chip_value(strip, "REC")
    )


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


def test_fresh_cockpit_shows_all_chips_off(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window._poll_health()
    levels = window.health_strip.current_levels()
    assert set(levels.values()) == {"off"}
    assert window.health_strip._summary.text() == "5 off"
    window.close()


def test_threshold_constants_drive_band_boundaries():
    """Belt-and-braces: the band edges in the dataclass helpers are
    the same constants the strip relies on. Failing this test means
    a refactor moved a literal somewhere the widget reads.
    """
    assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0
    assert thresholds.CAN_LOAD_YELLOW_MAX_PCT == 80.0
    assert thresholds.REC_LAST_RX_RED_MIN_S == 2.0


# ---------------------------------------------------------------------------
# B-1: clickable chips + detail popover (interaction matrix)
# ---------------------------------------------------------------------------


def _press_at(global_pt) -> QMouseEvent:
    """A MouseButtonPress whose globalPos() is ``global_pt`` (QPoint)."""
    return QMouseEvent(
        QEvent.MouseButtonPress,
        QPointF(0.0, 0.0),
        QPointF(float(global_pt.x()), float(global_pt.y())),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )


def _shown_strip(qtbot) -> HealthStrip:
    strip = HealthStrip()
    qtbot.addWidget(strip)
    strip.resize(760, 42)
    strip.show()
    strip.apply_snapshot(_snap())
    return strip


def test_chip_has_clicked_signal_emitting_name(qtbot):
    chip = HealthChip("CAN")
    qtbot.addWidget(chip)
    fired: list[str] = []
    chip.clicked.connect(fired.append)
    chip.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(4.0, 4.0),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    assert fired == ["CAN"]


def test_click_chip_opens_popover_with_detail_rows(qtbot):
    strip = _shown_strip(qtbot)
    strip.chip("CAN").clicked.emit("CAN")
    pop = strip.detail_popover
    assert pop is not None and pop.isVisible()
    assert strip.active_chip() == "CAN"
    assert pop.row_count() >= 1


def test_click_same_chip_toggles_closed(qtbot):
    strip = _shown_strip(qtbot)
    strip.chip("CAN").clicked.emit("CAN")
    assert strip.active_chip() == "CAN"
    # Re-click the SAME chip. First the app filter sees a press INSIDE the
    # anchor chip (must NOT dismiss), then the chip re-emits clicked → toggle.
    anchor_center = strip.chip("CAN").mapToGlobal(strip.chip("CAN").rect().center())
    consumed = strip.eventFilter(strip, _press_at(anchor_center))
    assert consumed is False
    assert strip.active_chip() == "CAN"  # inside-anchor press did not close it
    strip.chip("CAN").clicked.emit("CAN")
    assert strip.active_chip() is None
    assert not strip.detail_popover.isVisible()


def test_switch_chip_replaces_content_single_instance(qtbot):
    strip = _shown_strip(qtbot)
    strip.chip("CAN").clicked.emit("CAN")
    first = strip.detail_popover
    strip.chip("REC").clicked.emit("REC")
    second = strip.detail_popover
    assert first is second  # exactly one popover instance, reused
    assert strip.active_chip() == "REC"
    assert second.isVisible()
    assert second.title_text() == "REC"


def test_outside_click_dismisses_and_unhooks_filter(qtbot):
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QApplication

    strip = _shown_strip(qtbot)
    strip.chip("CAN").clicked.emit("CAN")
    assert strip.active_chip() == "CAN"
    # A press far outside both the popover and the anchor chip.
    strip.eventFilter(strip, _press_at(QPoint(6000, 6000)))
    assert strip.active_chip() is None
    assert not strip.detail_popover.isVisible()
    # Filter must be uninstalled (no leak): re-running it is a no-op now.
    before = strip.active_chip()
    QApplication.instance().sendEvent(strip, QEvent(QEvent.Show))
    assert before == strip.active_chip()


def test_escape_dismisses(qtbot):
    strip = _shown_strip(qtbot)
    strip.chip("XCP").clicked.emit("XCP")
    assert strip.active_chip() == "XCP"
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    strip.eventFilter(strip, ev)
    assert strip.active_chip() is None
    assert not strip.detail_popover.isVisible()


def test_window_deactivate_dismisses(qtbot):
    strip = _shown_strip(qtbot)
    strip.chip("DAQ").clicked.emit("DAQ")
    assert strip.active_chip() == "DAQ"
    strip.eventFilter(strip.window(), QEvent(QEvent.WindowDeactivate))
    assert strip.active_chip() is None


def test_resize_reanchors_popover(qtbot):
    strip = _shown_strip(qtbot)
    strip.chip("HW").clicked.emit("HW")
    pop = strip.detail_popover
    assert pop.isVisible()
    strip.resize(1180, 42)
    strip.repaint()
    assert pop.isVisible()
    assert strip.active_chip() == "HW"
    # Popover stays anchored below the HW chip (left edges roughly aligned).
    chip = strip.chip("HW")
    host = pop.parentWidget()
    chip_left = host.mapFromGlobal(chip.mapToGlobal(chip.rect().bottomLeft())).x()
    assert abs(pop.x() - chip_left) <= 12


def test_popover_renders_rows_and_paints_opaque_light_center(qtbot):
    pop = HealthPopover()
    qtbot.addWidget(pop)
    pop.set_title("REC")
    pop.set_rows(
        [
            ("缓冲占用", "12.0%", "green"),
            ("丢帧", "0", "green"),
            ("写入速率", "48000 /s", "green"),
        ]
    )
    assert pop.row_count() == 3
    pop.resize(max(220, pop.sizeHint().width()), max(96, pop.sizeHint().height()))
    pop.show()
    img = pop.grab().toImage()
    center = img.pixelColor(img.width() // 2, img.height() // 2)
    # Not transparent (paintEvent ran) and not the default Qt gray:
    assert center.alpha() >= 200
    assert center.red() >= 235 and center.green() >= 235 and center.blue() >= 235


def test_detail_for_rec_quotes_backing_fields(qtbot):
    strip = _shown_strip(qtbot)
    snap = _snap(
        rec=RecHealth(
            state="recording",
            ring_buffer_fill_pct=42.0,
            dropped_frames=3,
            write_rate_bps=1200.0,
            last_rx_age_s=0.2,
            writer_thread_alive=True,
        )
    )
    rows = strip.detail_for("REC", snap)
    joined = " ".join(f"{k} {v}" for k, v, _ in rows)
    assert "42.0" in joined       # ring buffer fill
    assert "3" in joined          # dropped frames
    assert "1200" in joined       # write rate (samples/s)


def test_detail_for_handles_none_snapshot(qtbot):
    strip = HealthStrip()
    qtbot.addWidget(strip)
    # No snapshot applied yet: detail_for must not crash and returns rows.
    rows = strip.detail_for("CAN", None)
    assert isinstance(rows, list)
