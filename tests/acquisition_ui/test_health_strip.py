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
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.preflight_view_data import (
    build_preflight_rows,
    worst_preflight_level,
)
from mf4_analyzer.acquisition_ui.state import HealthyPredicateResult
from mf4_analyzer.acquisition_ui.widgets.health_popover import HealthPopover
from mf4_analyzer.acquisition_ui.widgets.health_strip import (
    HealthChip,
    HealthStrip,
    PreflightPill,
)
from mf4_analyzer.acquisition_ui.widgets.right_panel import IdlePreflightPage, RightPanel


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
    assert summary.isHidden()


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
    assert strip.summary_text() == "1 项无证据"
    assert not strip._summary.isHidden()


def test_strip_base_yellow_summary_is_chinese_attention_count(qapp):
    strip = HealthStrip()
    strip.apply_snapshot(_snap(can=CanHealth(bus_load_pct=70.0)))
    assert strip.summary_text() == "1 项需注意"
    assert not strip._summary.isHidden()


def test_fresh_cockpit_shows_all_chips_off(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window._poll_health()
    levels = window.health_strip.current_levels()
    assert set(levels.values()) == {"off"}
    assert window.health_strip._summary.text() == "5 项无证据"
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


def test_mode_page_switch_dismisses_health_popover(qtbot):
    """B1: programmatic/keyboard mode switches do not rely on outside-click."""
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitExposed(window)

    strip = window.health_strip
    strip.chip("HW").clicked.emit("HW")
    assert strip.detail_popover is not None and strip.detail_popover.isVisible()
    assert strip._filter_installed

    window._mode_tabs.setCurrentIndex(1)  # Replay
    assert strip.active_chip() is None
    assert not strip.detail_popover.isVisible()
    assert not strip._filter_installed

    strip.chip("CAN").clicked.emit("CAN")
    assert strip.active_chip() == "CAN"
    window._mode_tabs.setCurrentIndex(2)  # History
    assert strip.active_chip() is None
    assert not strip.detail_popover.isVisible()
    window.close()


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


# ---------------------------------------------------------------------------
# B-2: preflight pill + aggregate popover (pure builder + widget)
# ---------------------------------------------------------------------------

GB = 1024 ** 3
MB = 1024 ** 2


def _sel(events, *, rate=100.0, payload=4):
    return [
        SelectedMeasurement(
            name=f"s{i}",
            unit="",
            event=ev,
            event_rate_hz=rate,
            payload_bytes=payload,
        )
        for i, ev in enumerate(events)
    ]


def test_build_preflight_rows_all_green_compresses_duration():
    rows = build_preflight_rows(
        _sel(["event_10ms"]),
        {"event_10ms": 32},
        10 * GB,
    )
    assert len(rows) == 5
    assert [level for _k, _v, level in rows] == ["green"] * 5
    # `预计可录时长` green → 充足 (no 232.7 天 style number).
    duration_key, duration_val, duration_level = rows[4]
    assert "预计可录时长" in duration_key
    assert duration_val == "充足" and duration_level == "green"
    assert worst_preflight_level(rows) == "green"


def test_build_preflight_rows_worst_band_is_yellow_on_low_disk():
    rows = build_preflight_rows(_sel(["event_10ms"]), {"event_10ms": 32}, 3 * GB)
    disk_key, _disk_val, disk_level = rows[2]
    assert "磁盘剩余" in disk_key and disk_level == "yellow"
    assert worst_preflight_level(rows) == "yellow"


def test_build_preflight_rows_worst_band_is_red_on_critical_disk():
    rows = build_preflight_rows(_sel(["event_10ms"]), {"event_10ms": 32}, 512 * MB)
    assert worst_preflight_level(rows) == "red"


def test_build_preflight_rows_empty_selection_all_off():
    rows = build_preflight_rows([], {}, 10 * GB)
    assert [level for _k, _v, level in rows] == ["off"] * 5
    assert all(v == "—" for _k, v, _l in rows)
    assert worst_preflight_level(rows) == "off"


def test_worst_preflight_level_ranking():
    assert worst_preflight_level([("a", "", "green"), ("b", "", "off")]) == "green"
    assert worst_preflight_level([("a", "", "green"), ("b", "", "yellow")]) == "yellow"
    assert worst_preflight_level([("a", "", "yellow"), ("b", "", "red")]) == "red"
    assert worst_preflight_level([]) == "off"


def test_preflight_pill_led_reflects_worst_band(qtbot):
    pill = PreflightPill()
    qtbot.addWidget(pill)
    pill.apply(_sel(["event_10ms"]), {"event_10ms": 32}, 10 * GB, state="idle")
    assert pill.level() == "green"
    pill.apply(_sel(["event_10ms"]), {"event_10ms": 32}, 3 * GB, state="idle")
    assert pill.level() == "yellow"
    pill.apply(_sel(["event_10ms"]), {"event_10ms": 32}, 512 * MB, state="idle")
    assert pill.level() == "red"


def test_preflight_pill_idle_is_openable_and_visible(qtbot):
    pill = PreflightPill()
    qtbot.addWidget(pill)
    pill.apply(_sel(["event_10ms"]), {"event_10ms": 32}, 10 * GB, state="idle")
    assert pill.isVisibleTo(pill) or pill.isVisible() or not pill.isHidden()
    assert pill.is_openable() is True
    rows = pill.current_rows()
    assert len(rows) == 5 and rows[4][1] == "充足"


def test_preflight_pill_disconnected_disabled_not_openable(qtbot):
    pill = PreflightPill()
    qtbot.addWidget(pill)
    pill.apply([], {}, 10 * GB, state="disconnected")
    assert pill.is_openable() is False
    assert not pill.isEnabled()
    assert "连接后可用" in pill.label_text()


def test_preflight_pill_recording_hidden(qtbot):
    pill = PreflightPill()
    qtbot.addWidget(pill)
    pill.setVisible(True)
    pill.apply(_sel(["event_10ms"]), {"event_10ms": 32}, 10 * GB, state="recording")
    assert pill.isHidden()
    assert pill.is_openable() is False


def _idle_strip(qtbot, disk=10 * GB):
    strip = HealthStrip()
    qtbot.addWidget(strip)
    strip.resize(900, 42)
    strip.show()
    strip.apply_snapshot(_snap())
    strip.apply_preflight(
        selection=_sel(["event_10ms"]),
        event_capacity={"event_10ms": 32},
        disk_free_bytes=disk,
        state="idle",
    )
    return strip


def test_preflight_pill_click_opens_aggregate_popover(qtbot):
    strip = _idle_strip(qtbot)
    strip.preflight_pill.clicked.emit()
    pop = strip.detail_popover
    assert pop is not None and pop.isVisible()
    assert strip.active_chip() == PreflightPill.NAME
    assert pop.row_count() == 5
    assert pop.title_text() == PreflightPill.NAME
    # Preflight anchor is NOT one of the five health chips.
    assert PreflightPill.NAME not in strip.CHIP_NAMES


def test_preflight_pill_click_toggles_closed(qtbot):
    strip = _idle_strip(qtbot)
    strip.preflight_pill.clicked.emit()
    assert strip.active_chip() == PreflightPill.NAME
    strip.preflight_pill.clicked.emit()
    assert strip.active_chip() is None
    assert not strip.detail_popover.isVisible()


def test_preflight_popover_survives_snapshot_refresh(qtbot):
    strip = _idle_strip(qtbot)
    strip.preflight_pill.clicked.emit()
    assert strip.active_chip() == PreflightPill.NAME
    # A fresh health snapshot must NOT clobber the preflight popover rows.
    strip.apply_snapshot(_snap(can=CanHealth(bus_load_pct=85.0)))
    assert strip.active_chip() == PreflightPill.NAME
    assert strip.detail_popover.row_count() == 5


def test_preflight_pill_rows_equal_idle_page_rows(qtbot):
    selection = _sel(["event_10ms", "event_10ms", "event_100ms"])
    capacity = {"event_10ms": 8, "event_100ms": 4}
    disk = 3 * GB

    pill = PreflightPill()
    qtbot.addWidget(pill)
    pill.apply(selection, capacity, disk, state="idle")

    page = IdlePreflightPage()
    qtbot.addWidget(page)
    page.apply(selection=selection, event_capacity=capacity, disk_free_bytes=disk)

    expected = build_preflight_rows(selection, capacity, disk)
    assert pill.current_rows() == expected
    assert page.last_preflight_rows() == expected


def test_preflight_pill_hidden_recording_keeps_center_geometry(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitExposed(window)
    # Walk to Connected-Idle so the pill is visible and laid out.
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    from PyQt5.QtWidgets import QApplication

    QApplication.processEvents()
    assert not window.health_strip.preflight_pill.isHidden()
    before = window._center.geometry()
    # Hiding the pill (recording state) must not reflow the body geometry.
    window.health_strip.apply_preflight(state="recording")
    QApplication.processEvents()
    assert window.health_strip.preflight_pill.isHidden()
    after = window._center.geometry()
    assert before == after
    window.close()
