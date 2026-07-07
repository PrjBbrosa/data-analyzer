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
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
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
from mf4_analyzer.acquisition_capture import thresholds


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


def _humanize_duration_s(seconds: float) -> str:
    if seconds == float("inf"):
        return "∞"
    if seconds < 90 * 60:
        return f"{seconds / 60:.1f} min"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 86400:.1f} d"


def _new_value_label(parent: QWidget, object_name: str = "") -> QLabel:
    label = QLabel("—", parent)
    if object_name:
        label.setObjectName(object_name)
    label.setTextFormat(Qt.RichText)
    label.setWordWrap(True)
    return label


def _add_header_row(
    outer: QVBoxLayout,
    parent: QWidget,
    title: str,
    *,
    substatus: QLabel | None = None,
) -> QLabel:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    header = QLabel(title, parent)
    header.setObjectName("paneHeader")
    row.addWidget(header)
    row.addStretch(1)
    if substatus is not None:
        row.addWidget(substatus)
    outer.addLayout(row)
    return header


def _add_section(
    outer: QVBoxLayout,
    parent: QWidget,
    title: str,
) -> tuple[QFrame, QVBoxLayout]:
    section = QFrame(parent)
    section.setObjectName("rightMetricSection")
    layout = QVBoxLayout(section)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(4)
    title_label = QLabel(title, section)
    title_label.setObjectName("rightMetricTitle")
    layout.addWidget(title_label)
    outer.addWidget(section)
    return section, layout


def _add_metric_section(
    outer: QVBoxLayout,
    parent: QWidget,
    title: str,
    *,
    value_object_name: str = "",
) -> QLabel:
    section, layout = _add_section(outer, parent, title)
    value = _new_value_label(section, value_object_name)
    layout.addWidget(value)
    return value


def _add_value_row(
    layout: QVBoxLayout,
    parent: QWidget,
    title: str,
    value: QLabel,
) -> None:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    caption = QLabel(title, parent)
    caption.setObjectName("rightMetricCaption")
    row.addWidget(caption)
    row.addStretch(1)
    row.addWidget(value)
    layout.addLayout(row)


def _add_verdict_banner(
    outer: QVBoxLayout,
    parent: QWidget,
    *,
    value_object_name: str = "",
) -> tuple[QFrame, QLabel]:
    banner = QFrame(parent)
    banner.setObjectName("rightVerdictBanner")
    layout = QVBoxLayout(banner)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(4)
    label = _new_value_label(banner, value_object_name)
    layout.addWidget(label)
    outer.addWidget(banner)
    return banner, label


# ---------------------------------------------------------------------------
# Variant widgets
# ---------------------------------------------------------------------------


class _BasePanelPage(QFrame):
    """Base page frame: wraps its body in a scroll area with cap+left-anchor.

    Layout topology (per the cap-and-left-anchor pattern from
    ``pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md``):

    ``self``  (QFrame, page frame)
      └── ``_page_layout`` (QVBoxLayout, zero margins)
            └── ``_scroll`` (QScrollArea, widgetResizable=True,
                             vScroll=AsNeeded, hScroll=AlwaysOff)
                  └── ``_scroll_body`` (QWidget, setMaximumWidth(340))
                        └── ``_body_host`` (QVBoxLayout, hosts content
                                             + trailing ``addStretch(1)``)
                              └── ``_outer`` (QVBoxLayout, the layout
                                              subclasses populate;
                                              kept as ``self._outer``
                                              so existing subclass code
                                              is byte-identical)

    Subclasses continue to call ``self._outer.addWidget(...)`` /
    ``self._outer.addStretch(...)`` exactly as before.
    """

    _SCROLL_BODY_MAX_WIDTH = 340
    _SCROLL_OBJECT_NAME = "rightPanelScroll"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rightPanelPage")

        # Outer page-frame layout: zero-margin host for the scroll area.
        self._page_layout = QVBoxLayout(self)
        self._page_layout.setContentsMargins(0, 0, 0, 0)
        self._page_layout.setSpacing(0)

        # Scroll area — never grows horizontally; vertical AsNeeded.
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName(self._SCROLL_OBJECT_NAME)
        self._scroll.setWidgetResizable(True)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._page_layout.addWidget(self._scroll)

        # Capped scroll body — keeps Expanding children from re-stretching
        # the pane when the splitter is dragged wide.
        self._scroll_body = QWidget()
        self._scroll_body.setObjectName("rightPanelScrollBody")
        self._scroll_body.setMaximumWidth(self._SCROLL_BODY_MAX_WIDTH)

        # Host layout inside the scroll body left-anchors the body
        # widget with a trailing ``addStretch(1)``. The body widget
        # itself owns ``self._outer`` so subclasses keep using
        # ``self._outer.addWidget(...)``.
        self._body_host = QVBoxLayout(self._scroll_body)
        self._body_host.setContentsMargins(12, 12, 12, 12)
        self._body_host.setSpacing(0)

        self._body = QWidget(self._scroll_body)
        self._outer = QVBoxLayout(self._body)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(8)

        self._body_host.addWidget(self._body)
        self._body_host.addStretch(1)

        self._scroll.setWidget(self._scroll_body)


class DisconnectedPage(_BasePanelPage):
    """Connection checklist + first-failure surface."""

    _SCROLL_OBJECT_NAME = "rightPanelScrollDisconnected"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _add_header_row(self._outer, self, "连接前检查")

        self._row_a2l = _add_metric_section(self._outer, self, "A2L")

        section, layout = _add_section(self._outer, self, "硬件")
        self._row_hw = _new_value_label(section)
        self._row_xcp = _new_value_label(section)
        self._row_frame = _new_value_label(section)
        _add_value_row(layout, section, "HW 可用", self._row_hw)
        _add_value_row(layout, section, "XCP 已连接", self._row_xcp)
        _add_value_row(layout, section, "首帧已收", self._row_frame)

        self._row_selection = _add_metric_section(self._outer, self, "当前选择")

        _, self._failure = _add_verdict_banner(self._outer, self)
        self._failure.setObjectName("rightPanelFailure")
        self._outer.addStretch(1)

    def apply(
        self,
        *,
        snapshot: HealthSnapshot | None,
        first_frame_received: bool,
        first_failure: str | None,
        selection_count: int,
    ) -> None:
        self._row_a2l.setText(_format_band_value("off", "--"))
        if snapshot is None:
            self._row_hw.setText(_format_band_value("off", "--"))
            self._row_xcp.setText(_format_band_value("off", "--"))
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
            self._failure.setText("等待连接条件")


class IdlePreflightPage(_BasePanelPage):
    """Five preflight numbers (Threshold Contract table)."""

    _SCROLL_OBJECT_NAME = "rightPanelScrollIdle"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._substatus = QLabel("等待选择", self)
        self._substatus.setObjectName("idleSubstatusLabel")
        _add_header_row(self._outer, self, "录制预检", substatus=self._substatus)

        self._row_can = _add_metric_section(
            self._outer,
            self,
            "CAN 总线负载",
            value_object_name="idleCanValue",
        )
        self._row_daq = _add_metric_section(
            self._outer,
            self,
            "DAQ slot · ECU 端容量",
            value_object_name="idleDaqValue",
        )
        self._row_disk = _add_metric_section(
            self._outer,
            self,
            "磁盘剩余",
            value_object_name="idleDiskValue",
        )
        self._row_samples = _add_metric_section(
            self._outer,
            self,
            "采样事件 / 秒",
            value_object_name="idleSamplesValue",
        )
        self._row_duration = _add_metric_section(
            self._outer,
            self,
            "预计可录时长",
            value_object_name="idleOutputValue",
        )

        _, self._note = _add_verdict_banner(
            self._outer,
            self,
            value_object_name="idleVerdictBanner",
        )
        self._outer.addStretch(1)

    def apply(
        self,
        *,
        selection: Sequence[SelectedMeasurement],
        event_capacity: Mapping[str, int],
        disk_free_bytes: int,
        bitrate_bps: int | None = None,
    ) -> None:
        if bitrate_bps is None:
            bitrate_bps = thresholds.DEFAULT_CAN_BITRATE_BPS
        if not selection:
            for r in (
                self._row_can,
                self._row_daq,
                self._row_disk,
                self._row_duration,
                self._row_samples,
            ):
                r.setText(_format_band_value("off", "—"))
            self._substatus.setText("等待选择")
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
                    _humanize_duration_s(duration_s),
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

        self._substatus.setText("预检完成")
        self._note.setText("数字仅供参考 · 实际录制按真实样本累计")


class RecordingQualityPage(_BasePanelPage):
    """Live quality monitor sourced from RecHealth + CanHealth + disk."""

    _SCROLL_OBJECT_NAME = "rightPanelScrollRecording"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _add_header_row(self._outer, self, "实时质量监控")

        self._row_ring = _add_metric_section(self._outer, self, "ring buffer")
        self._row_write = _add_metric_section(self._outer, self, "write rate")
        self._row_dropped = _add_metric_section(self._outer, self, "dropped frames")
        self._row_can = _add_metric_section(self._outer, self, "CAN load")
        self._row_rx_age = _add_metric_section(self._outer, self, "last frame delay")
        self._row_disk = _add_metric_section(self._outer, self, "disk remaining")
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
        # Replace ``setFixedWidth(300)`` with a min/max band so the
        # splitter can hand the pane some slack for longer translated
        # labels and wider numeric values. The cap-and-left-anchor in
        # ``_BasePanelPage`` keeps the form column visually anchored at
        # 340 px even when the splitter slot grows past it.
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)
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
