"""Right pane — three variants (disconnected, idle, recording).

Spec §Right Pane:

- Disconnected: connection checklist (A2L parsed / HW available / current
  selection feasible). Each row's truth value comes from the matching
  ``*Health`` snapshot field.
- Connected idle: record preflight/readiness — the 5 numbers in the
  Threshold Contract table, each one computed by the matching pure
  function in :mod:`mf4_analyzer.acquisition_capture.preflight_estimates`.
- Recording: live quality monitor — rows sourced from ``RecHealth.*``,
  ``CanHealth.bus_load_pct``, and the controller-supplied
  ``disk_free_bytes``. UI MUST NOT read free-form status strings.

The widget binds to ``HealthSnapshot`` exclusively for snapshot-derived
rows, and to ``Sequence[SelectedMeasurement]`` for preflight rows. No
threshold literals appear in this file — bands import from
``mf4_analyzer.acquisition_capture.thresholds``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.acquisition_capture.health import HealthSnapshot
from mf4_analyzer.acquisition_capture.preflight_estimates import (
    band_can_load,
    band_daq_slot,
    band_disk_remaining,
    band_dropped_frames,
    band_rec_last_rx_age_s,
    band_record_duration_s,
    band_ring_buffer,
    band_sample_events_per_s,
    daq_slot_usage,
    estimate_can_bus_load,
    estimate_record_duration_s,
    estimate_sample_events_per_s,
    estimate_throughput_bps,
)
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture.thresholds import DEFAULT_CAN_BITRATE_BPS


# Display tokens. Color tokens stay in this file because they are
# strictly band-derived from threshold constants — no free numeric
# literal lives here.
_LEVEL_COLOR = {
    "green": "#16a34a",
    "yellow": "#d97706",
    "red": "#dc2626",
    "off": "#94a3b8",
}


def _format_band_value(level: str, text: str) -> str:
    color = _LEVEL_COLOR.get(level, _LEVEL_COLOR["off"])
    return f'<span style="color:{color}; font-weight:600;">{text}</span>'


# ---------------------------------------------------------------------------
# Variant widgets
# ---------------------------------------------------------------------------


class _BasePanelPage(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rightPanelPage")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(12, 12, 12, 12)
        self._outer.setSpacing(8)


class DisconnectedPage(_BasePanelPage):
    """Connection checklist + first-failure surface."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        header = QLabel("连接检查")
        header.setObjectName("paneHeader")
        self._outer.addWidget(header)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        self._row_hw = QLabel("…", self)
        self._row_xcp = QLabel("…", self)
        self._row_frame = QLabel("…", self)
        self._row_selection = QLabel("0 项已选", self)
        form.addRow("HW 可用", self._row_hw)
        form.addRow("XCP 已连接", self._row_xcp)
        form.addRow("首帧已收", self._row_frame)
        form.addRow("已选信号", self._row_selection)
        self._outer.addLayout(form)

        self._failure = QLabel(self)
        self._failure.setObjectName("rightPanelFailure")
        self._failure.setWordWrap(True)
        self._outer.addWidget(self._failure)
        self._outer.addStretch(1)

    def apply(
        self,
        *,
        snapshot: HealthSnapshot | None,
        first_frame_received: bool,
        first_failure: str | None,
        selection_count: int,
    ) -> None:
        if snapshot is None:
            self._row_hw.setText(_format_band_value("off", "—"))
            self._row_xcp.setText(_format_band_value("off", "—"))
        else:
            hw_ok = snapshot.hw.ok
            self._row_hw.setText(
                _format_band_value(
                    "green" if hw_ok else "red",
                    "ok" if hw_ok else (snapshot.hw.error or "未连接"),
                )
            )
            self._row_xcp.setText(
                _format_band_value(
                    "green" if snapshot.xcp.connected else "red",
                    "connected" if snapshot.xcp.connected else "断开",
                )
            )
        self._row_frame.setText(
            _format_band_value(
                "green" if first_frame_received else "off",
                "received" if first_frame_received else "等待中",
            )
        )
        self._row_selection.setText(f"{selection_count} 项已选")

        if first_failure:
            self._failure.setText(
                f'<span style="color:#dc2626; font-weight:600;">'
                f"首个未通过: {first_failure}</span>"
            )
        else:
            self._failure.setText("")


class IdlePreflightPage(_BasePanelPage):
    """Five preflight numbers (Threshold Contract table)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        header = QLabel("录制准备")
        header.setObjectName("paneHeader")
        self._outer.addWidget(header)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        self._row_can = QLabel("—", self)
        self._row_daq = QLabel("—", self)
        self._row_disk = QLabel("—", self)
        self._row_duration = QLabel("—", self)
        self._row_samples = QLabel("—", self)
        for r in (
            self._row_can,
            self._row_daq,
            self._row_disk,
            self._row_duration,
            self._row_samples,
        ):
            r.setTextFormat(Qt.RichText)
        form.addRow("CAN 负载", self._row_can)
        form.addRow("DAQ 槽位", self._row_daq)
        form.addRow("磁盘剩余", self._row_disk)
        form.addRow("估算时长", self._row_duration)
        form.addRow("样本/秒", self._row_samples)
        self._outer.addLayout(form)

        self._note = QLabel(self)
        self._note.setWordWrap(True)
        self._note.setObjectName("rightPanelNote")
        self._outer.addWidget(self._note)
        self._outer.addStretch(1)

    def apply(
        self,
        *,
        selection: Sequence[SelectedMeasurement],
        event_capacity: Mapping[str, int],
        disk_free_bytes: int,
        bitrate_bps: int = DEFAULT_CAN_BITRATE_BPS,
    ) -> None:
        if not selection:
            for r in (
                self._row_can,
                self._row_daq,
                self._row_disk,
                self._row_duration,
                self._row_samples,
            ):
                r.setText(_format_band_value("off", "—"))
            self._note.setText("尚未选择测量")
            return

        can_pct = estimate_can_bus_load(selection, bitrate_bps)
        self._row_can.setText(
            _format_band_value(band_can_load(can_pct), f"{can_pct:.1f}%")
        )

        # DAQ slot uses each event's own capacity. We surface the
        # max-of-events here so a single number drives the chip; per-event
        # detail is in the recording quality monitor. The actual usage
        # calculation goes through the pure ``daq_slot_usage`` helper so
        # the formula stays in one place (spec §Preflight Computation
        # Contract).
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
            self._row_daq.setText(_format_band_value("off", "—"))
        else:
            self._row_daq.setText(
                _format_band_value(band_daq_slot(worst_pct), f"{worst_pct:.1f}%")
            )

        # Disk-remaining row delegates band selection to the pure helper.
        self._row_disk.setText(
            _format_band_value(
                band_disk_remaining(disk_free_bytes),
                f"{disk_free_bytes / (1024 ** 3):.2f} GB",
            )
        )

        throughput = estimate_throughput_bps(selection)
        duration_s = estimate_record_duration_s(throughput, disk_free_bytes)
        if duration_s == float("inf"):
            self._row_duration.setText(_format_band_value("off", "∞"))
        else:
            self._row_duration.setText(
                _format_band_value(
                    band_record_duration_s(duration_s),
                    f"{duration_s / 60:.1f} min",
                )
            )

        # Total sample events / second flows through the pure estimator
        # plus its matching band helper — both live in
        # ``preflight_estimates``.
        events_per_s = estimate_sample_events_per_s(selection)
        self._row_samples.setText(
            _format_band_value(
                band_sample_events_per_s(events_per_s), f"{events_per_s:.0f}"
            )
        )

        self._note.setText("数字仅供参考 · 实际录制按真实样本累计")


class RecordingQualityPage(_BasePanelPage):
    """Live quality monitor sourced from RecHealth + CanHealth + disk."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        header = QLabel("录制质量监控")
        header.setObjectName("paneHeader")
        self._outer.addWidget(header)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        self._row_ring = QLabel("—", self)
        self._row_write = QLabel("—", self)
        self._row_dropped = QLabel("—", self)
        self._row_can = QLabel("—", self)
        self._row_rx_age = QLabel("—", self)
        self._row_disk = QLabel("—", self)
        for r in (
            self._row_ring,
            self._row_write,
            self._row_dropped,
            self._row_can,
            self._row_rx_age,
            self._row_disk,
        ):
            r.setTextFormat(Qt.RichText)
        form.addRow("Ring 缓冲", self._row_ring)
        form.addRow("写入速率", self._row_write)
        form.addRow("丢帧", self._row_dropped)
        form.addRow("CAN 负载", self._row_can)
        form.addRow("最后帧延迟", self._row_rx_age)
        form.addRow("磁盘剩余", self._row_disk)
        self._outer.addLayout(form)
        self._outer.addStretch(1)

    def apply(
        self,
        *,
        snapshot: HealthSnapshot,
        disk_free_bytes: int,
    ) -> None:
        rec = snapshot.rec
        self._row_ring.setText(
            _format_band_value(
                band_ring_buffer(rec.ring_buffer_fill_pct),
                f"{rec.ring_buffer_fill_pct:.1f}%",
            )
        )
        self._row_write.setText(
            _format_band_value("green", f"{rec.write_rate_bps / 1024:.1f} kB/s")
        )
        self._row_dropped.setText(
            _format_band_value(
                band_dropped_frames(rec.dropped_frames),
                str(rec.dropped_frames),
            )
        )
        can = snapshot.can
        if can.bus_load_pct is None:
            self._row_can.setText(_format_band_value("off", "—"))
        else:
            self._row_can.setText(
                _format_band_value(
                    band_can_load(can.bus_load_pct),
                    f"{can.bus_load_pct:.1f}%",
                )
            )
        self._row_rx_age.setText(
            _format_band_value(
                band_rec_last_rx_age_s(rec.last_rx_age_s),
                f"{rec.last_rx_age_s:.2f} s",
            )
        )
        self._row_disk.setText(
            _format_band_value(
                band_disk_remaining(disk_free_bytes),
                f"{disk_free_bytes / (1024 ** 3):.2f} GB",
            )
        )


# ---------------------------------------------------------------------------
# Top-level stacked container
# ---------------------------------------------------------------------------


class RightPanel(QStackedWidget):
    """Stacked container that swaps page by Cockpit state.

    Public API:

    - :meth:`show_disconnected` / :meth:`show_idle` / :meth:`show_recording`
      switch pages and reapply data.
    """

    PAGE_DISCONNECTED = 0
    PAGE_IDLE = 1
    PAGE_RECORDING = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rightPanel")
        self.setFixedWidth(300)
        self._disconnected = DisconnectedPage(self)
        self._idle = IdlePreflightPage(self)
        self._recording = RecordingQualityPage(self)
        self.addWidget(self._disconnected)
        self.addWidget(self._idle)
        self.addWidget(self._recording)
        self.setCurrentIndex(self.PAGE_DISCONNECTED)

    def show_disconnected(
        self,
        *,
        snapshot: HealthSnapshot | None,
        first_frame_received: bool,
        first_failure: str | None,
        selection_count: int,
    ) -> None:
        self._disconnected.apply(
            snapshot=snapshot,
            first_frame_received=first_frame_received,
            first_failure=first_failure,
            selection_count=selection_count,
        )
        self.setCurrentIndex(self.PAGE_DISCONNECTED)

    def show_idle(
        self,
        *,
        selection: Sequence[SelectedMeasurement],
        event_capacity: Mapping[str, int],
        disk_free_bytes: int,
    ) -> None:
        self._idle.apply(
            selection=selection,
            event_capacity=event_capacity,
            disk_free_bytes=disk_free_bytes,
        )
        self.setCurrentIndex(self.PAGE_IDLE)

    def show_recording(
        self,
        *,
        snapshot: HealthSnapshot,
        disk_free_bytes: int,
    ) -> None:
        self._recording.apply(
            snapshot=snapshot,
            disk_free_bytes=disk_free_bytes,
        )
        self.setCurrentIndex(self.PAGE_RECORDING)

    # Test introspection helpers.
    @property
    def disconnected_page(self) -> DisconnectedPage:
        return self._disconnected

    @property
    def idle_page(self) -> IdlePreflightPage:
        return self._idle

    @property
    def recording_page(self) -> RecordingQualityPage:
        return self._recording
