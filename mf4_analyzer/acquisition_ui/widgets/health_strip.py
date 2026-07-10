"""Five-chip health strip (HW · CAN · XCP · DAQ · REC).

Spec §Health Strip — each chip MUST be driven by the matching
``*Health`` snapshot. UI never computes chip color from free-form
strings; mapping ``snapshot → level`` lives in
``mf4_analyzer.acquisition_capture.health`` (level helpers) and the
combined level dict ships from ``HealthSnapshot.levels()``.

This widget is a pure view of the snapshot: ``apply_snapshot()``
is the only mutation entry point. The Cockpit ``MainWindow`` polls
``HealthAggregator.poll_once()`` on a ``QTimer`` at
``thresholds.HEALTH_POLL_INTERVAL_S`` and feeds each result into
``apply_snapshot``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Mapping

from PyQt5.QtCore import QEvent, QPropertyAnimation, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from mf4_analyzer.acquisition_capture.health import (
    HealthLevel,
    HealthSnapshot,
)
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_ui.preflight_view_data import (
    build_preflight_rows,
    worst_preflight_level,
)
from mf4_analyzer.acquisition_ui.widgets.escalation_bar import (
    EscalationState,
    _SEVERITY,
    effective_chip_levels,
)
from mf4_analyzer.acquisition_ui.widgets.health_popover import HealthPopover


# Spec §Health Strip: tooltip MUST quote one field from the backing
# snapshot. None-shaped snapshots show ``no evidence yet`` and the
# chip stays ``off`` — handled in :meth:`_tooltip_for`.
_NO_EVIDENCE = "no evidence yet"


# Visual color per chip level. Kept on the widget rather than QSS so
# the chip background is driven by the dataclass-derived level, not a
# string property + global stylesheet rule. The chip frame itself
# carries an objectName for QSS hooks if the design needs to add a
# hairline border later.
_LEVEL_BG = {
    "green": "#16a34a",
    "yellow": "#d97706",
    "red": "#dc2626",
    "off": "#94a3b8",
}


class HealthChip(QFrame):
    """One labeled LED + value chip (e.g. ``● HW VN1610``).

    The chip is a small colored circle next to the chip label and value. The
    ``level`` argument is one of ``"green" | "yellow" | "red" | "off"``
    — the exact set returned by the snapshot ``level_*`` helpers.

    Clicking the chip emits :attr:`clicked` with the chip name; the owning
    :class:`HealthStrip` uses that to pop a detail popover (Spec §B1).
    """

    #: Emitted on a left-button press, carrying this chip's name.
    clicked = pyqtSignal(str)

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("healthChip")
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self._name = name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)
        self._led = QLabel(self)
        self._led.setObjectName("healthChipLed")
        self._led.setFixedSize(8, 8)
        self._led.setAlignment(Qt.AlignCenter)
        self._label = QLabel(name, self)
        self._label.setObjectName("healthChipLabel")
        self._value = QLabel("--", self)
        self._value.setObjectName("healthChipValue")
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._led)
        layout.addWidget(self._label)
        layout.addWidget(self._value)

        # Red-escalation entry pulse (Spec §B6): fade the LED 3 loops, then
        # rest solid. The animation object is created up-front so the level is
        # always introspectable (loopCount == 3) even before it runs.
        self._led_opacity = QGraphicsOpacityEffect(self._led)
        self._led_opacity.setOpacity(1.0)
        self._led.setGraphicsEffect(self._led_opacity)
        self.pulse_animation = QPropertyAnimation(self._led_opacity, b"opacity", self)
        self.pulse_animation.setDuration(560)
        self.pulse_animation.setKeyValueAt(0.0, 1.0)
        self.pulse_animation.setKeyValueAt(0.5, 0.2)
        self.pulse_animation.setKeyValueAt(1.0, 1.0)
        self.pulse_animation.setLoopCount(3)
        self.pulse_animation.finished.connect(
            lambda: self._led_opacity.setOpacity(1.0)
        )

        self.set_level("off")

    @property
    def name(self) -> str:
        return self._name

    def pulse(self) -> None:
        """Restart the 3-loop entry pulse on the LED."""
        self.pulse_animation.stop()
        self._led_opacity.setOpacity(1.0)
        self.pulse_animation.start()

    def stop_pulse(self) -> None:
        """Stop pulsing and rest the LED solid."""
        self.pulse_animation.stop()
        self._led_opacity.setOpacity(1.0)

    def set_level(self, level: HealthLevel) -> None:
        """Repaint the LED for the given level. The chip label is invariant."""
        bg = _LEVEL_BG.get(level, _LEVEL_BG["off"])
        self._led.setStyleSheet(
            f"background-color: {bg}; border-radius: 5px;"
        )
        # Stamp the level as a dynamic property so tests can introspect
        # without scraping the stylesheet string.
        self.setProperty("level", level)
        self._led.setProperty("level", level)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_value(self, text: str) -> None:
        self._value.setText(text if text else "--")

    def set_tooltip(self, text: str) -> None:
        self.setToolTip(text)
        self._led.setToolTip(text)
        self._label.setToolTip(text)
        self._value.setToolTip(text)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._name)
            event.accept()
            return
        super().mousePressEvent(event)


class PreflightPill(QFrame):
    """Record-preflight readiness pill (Spec §B2).

    Independent of the five fixed health chips: it is NOT a member of
    ``HealthStrip.CHIP_NAMES``. Its LED shows the WORST band across the five
    preflight rows (red > yellow > green > off) computed by the shared
    :func:`mf4_analyzer.acquisition_ui.preflight_view_data.build_preflight_rows`,
    so the pill and the right-pane ``IdlePreflightPage`` can never diverge.

    State-gated visibility (driven by :class:`HealthStrip.apply_preflight`):

    - ``idle`` — visible, enabled, clickable; LED = worst band.
    - ``disconnected`` — visible but disabled, off LED, ``连接后可用``.
    - ``recording`` — hidden (never reflows the body: the strip is a
      fixed-height row above the splitter).

    Clicking (only in idle) emits :attr:`clicked`; the owning strip then
    reuses its single :class:`HealthPopover` via ``open_popover``.
    """

    #: Popover title / anchor name. Kept out of ``CHIP_NAMES`` on purpose.
    NAME = "录制预检"

    #: Emitted on a left-button press while the pill is openable (idle only).
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("preflightPill")
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)
        self._led = QLabel(self)
        self._led.setObjectName("preflightPillLed")
        self._led.setFixedSize(8, 8)
        self._label = QLabel(self.NAME, self)
        self._label.setObjectName("preflightPillLabel")
        layout.addWidget(self._led)
        layout.addWidget(self._label)

        self._rows: list[tuple[str, str, HealthLevel]] = []
        self._openable = False
        self._set_led("off")

    # ------------------------------------------------------------------
    # State binding
    # ------------------------------------------------------------------

    def apply(
        self,
        selection: Sequence[SelectedMeasurement],
        event_capacity: Mapping[str, int],
        disk_free_bytes: int,
        *,
        state: str,
        bitrate_bps: int | None = None,
    ) -> None:
        """Rebuild the pill for the current cockpit ``state``.

        ``state`` is ``"idle" | "disconnected" | "recording"``.
        """
        if state == "recording":
            self._openable = False
            self.setVisible(False)
            return

        self.setVisible(True)
        if state == "disconnected":
            self._rows = []
            self._openable = False
            self._set_led("off")
            self._label.setText("连接后可用")
            self.setEnabled(False)
            self.setCursor(Qt.ArrowCursor)
            return

        # Connected-idle: compute the five rows and light the worst band.
        rows = build_preflight_rows(
            selection,
            event_capacity,
            disk_free_bytes,
            bitrate_bps=bitrate_bps,
        )
        self._rows = list(rows)
        self._openable = True
        self._set_led(worst_preflight_level(rows))
        self._label.setText(self.NAME)
        self.setEnabled(True)
        self.setCursor(Qt.PointingHandCursor)

    def current_rows(self) -> list[tuple[str, str, HealthLevel]]:
        return list(self._rows)

    def is_openable(self) -> bool:
        return self._openable

    def level(self) -> HealthLevel:
        return self.property("level") or "off"

    def label_text(self) -> str:
        return self._label.text()

    def _set_led(self, level: HealthLevel) -> None:
        bg = _LEVEL_BG.get(level, _LEVEL_BG["off"])
        self._led.setStyleSheet(f"background-color: {bg}; border-radius: 5px;")
        self.setProperty("level", level)
        self._led.setProperty("level", level)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.LeftButton and self._openable:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class HealthStrip(QFrame):
    """The five-chip horizontal strip.

    Layout: ``[HW] [CAN] [XCP] [DAQ] [REC]`` left-to-right. Target
    height is 32 px per spec.

    Public API:

    - :meth:`apply_snapshot` — supply a fresh ``HealthSnapshot`` from
      ``HealthAggregator.poll_once()``. The widget reads
      ``snapshot.levels()`` for chip colors and pulls a single
      backing-field tooltip per spec.
    - ``levels_changed(dict)`` Qt signal — fires when any chip color
      changes between consecutive ``apply_snapshot`` calls. The
      Cockpit ``MainWindow`` uses this to update the toolbar REC
      indicator and the record-button enabled state.
    """

    levels_changed = pyqtSignal(dict)

    CHIP_NAMES = ("HW", "CAN", "XCP", "DAQ", "REC")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("healthStrip")
        self.setFixedHeight(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)
        self._chips: dict[str, HealthChip] = {}
        for name in self.CHIP_NAMES:
            chip = HealthChip(name, self)
            chip.clicked.connect(self._on_chip_clicked)
            self._chips[name] = chip
            layout.addWidget(chip)
        # Preflight readiness pill — sibling of the chips, not a chip.
        self._preflight_pill = PreflightPill(self)
        self._preflight_pill.clicked.connect(self._on_preflight_clicked)
        self._preflight_pill.setVisible(False)
        layout.addWidget(self._preflight_pill)
        layout.addStretch(1)
        self._summary = QLabel("--", self)
        self._summary.setObjectName("healthSummary")
        self._summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._summary.setVisible(False)
        layout.addWidget(self._summary)
        self._last_levels: dict[str, HealthLevel] = {n: "off" for n in self.CHIP_NAMES}
        self._base_levels: dict[str, HealthLevel] = dict(self._last_levels)
        self._last_snapshot: HealthSnapshot | None = None
        # Escalation ladder (Spec §B6): latch the current red reason so the
        # entry pulse fires only on entry / reason change, not every poll.
        self._esc_reason: str | None = None
        self._escalation_state = EscalationState("green", ())

        # Single-popover state (Spec §B1): at most one popover is open;
        # ``_anchor_name`` names the widget it is currently anchored to
        # (a chip name, or a pill name once B2 reuses ``open_popover``).
        self._popover: HealthPopover | None = None
        self._anchor_name: str | None = None
        self._anchor_widget: QWidget | None = None
        self._filter_installed = False

    # ------------------------------------------------------------------
    # Snapshot binding
    # ------------------------------------------------------------------

    def apply_snapshot(self, snapshot: HealthSnapshot) -> None:
        """Repaint chips for the given snapshot and emit ``levels_changed``."""
        self._last_snapshot = snapshot
        self._base_levels = snapshot.levels()
        new_levels = self._effective_levels()
        for name in self.CHIP_NAMES:
            level = new_levels.get(name, "off")
            chip = self._chips[name]
            chip.set_level(level)
            chip.set_value(self._value_for(name, snapshot, level))
            chip.set_tooltip(self._tooltip_for(name, snapshot))
        self._set_summary(self._summary_for(new_levels, self._escalation_state))
        # Keep an open chip popover live with the freshest snapshot fields.
        if (
            self._popover_open()
            and self._anchor_name in self.CHIP_NAMES
        ):
            self._popover.set_rows(self.detail_for(self._anchor_name, snapshot))
        self._set_current_levels(new_levels)

    def chip(self, name: str) -> HealthChip:
        """Return the chip widget for a given name (test introspection)."""
        return self._chips[name]

    def current_levels(self) -> Mapping[str, HealthLevel]:
        return dict(self._last_levels)

    @property
    def last_snapshot(self) -> HealthSnapshot | None:
        return self._last_snapshot

    def summary_text(self) -> str:
        """Current right-aligned summary text (base health or escalation)."""
        return self._summary.text()

    # ------------------------------------------------------------------
    # Escalation ladder (Spec §B6)
    # ------------------------------------------------------------------

    def apply_escalation(self, state: EscalationState) -> None:
        """Fold an escalation state onto the chips + summary + red pulse.

        Wired from ``EscalationBar.applied`` so a single ``bar.apply(state)``
        drives both the banner and the strip. Chips are only ever *escalated*
        (worst wins); the base color comes from :meth:`apply_snapshot`.
        """
        self._escalation_state = state
        levels = self._effective_levels()
        for name in self.CHIP_NAMES:
            level = levels.get(name, "off")
            chip = self._chips[name]
            chip.set_level(level)
            if self._last_snapshot is not None:
                chip.set_value(self._value_for(name, self._last_snapshot, level))
        self._set_current_levels(levels)
        self._set_summary(self._summary_for(levels, state))

        if state.level == "green":
            # Recovery restores the base levels rendered above, hides a clean
            # summary, and arms the next red entry pulse.
            for chip in self._chips.values():
                chip.stop_pulse()
            self._esc_reason = None
            return

        reason = state.reason_key
        if state.level == "red" and reason != self._esc_reason:
            # Pulse the worst red chip on entry / reason change only.
            worst = next(
                (i for i in state.top_issues(1) if i.level == "red"), None
            )
            if worst is not None:
                chip = self._chips.get(worst.source_chip)
                if chip is not None:
                    chip.pulse()
        self._esc_reason = reason

    def _effective_levels(self) -> dict[str, HealthLevel]:
        """Base chip levels upgraded by the current escalation state."""
        if self._last_snapshot is not None:
            return effective_chip_levels(self._last_snapshot, self._escalation_state)
        levels = dict(self._base_levels)
        for issue in self._escalation_state.issues:
            current = levels.get(issue.source_chip, "off")
            if _SEVERITY.get(issue.level, 0) > _SEVERITY.get(current, 0):
                levels[issue.source_chip] = issue.level
        return levels

    def _set_current_levels(self, levels: Mapping[str, HealthLevel]) -> None:
        """Publish effective levels only when they actually changed."""
        normalized = {name: levels.get(name, "off") for name in self.CHIP_NAMES}
        if normalized != self._last_levels:
            self._last_levels = normalized
            self.levels_changed.emit(dict(normalized))

    def _set_summary(self, text: str) -> None:
        self._summary.setText(text)
        self._summary.setVisible(bool(text))

    @staticmethod
    def _summary_for(
        levels: Mapping[str, HealthLevel], state: EscalationState
    ) -> str:
        """Chinese summary: quiet when green, issue-counted when escalated."""
        if state.level in ("yellow", "red"):
            count = sum(1 for issue in state.issues if issue.level == state.level)
            if count:
                label = "严重" if state.level == "red" else "需注意"
                return f"{count} 项{label}"

        counts = {
            level: sum(1 for value in levels.values() if value == level)
            for level in ("red", "yellow", "off")
        }
        if counts["red"]:
            return f"{counts['red']} 项严重"
        if counts["yellow"]:
            return f"{counts['yellow']} 项需注意"
        if counts["off"]:
            return f"{counts['off']} 项无证据"
        return ""

    # ------------------------------------------------------------------
    # Detail popover (Spec §B1)
    # ------------------------------------------------------------------

    @property
    def detail_popover(self) -> HealthPopover | None:
        """The single popover instance (``None`` until first opened)."""
        return self._popover

    @property
    def preflight_pill(self) -> PreflightPill:
        """The record-preflight readiness pill (Spec §B2)."""
        return self._preflight_pill

    def active_chip(self) -> str | None:
        """Name of the chip/pill the popover is anchored to, or ``None``."""
        return self._anchor_name

    # ------------------------------------------------------------------
    # Preflight pill binding (Spec §B2)
    # ------------------------------------------------------------------

    def apply_preflight(
        self,
        *,
        selection: Sequence[SelectedMeasurement] | None = None,
        event_capacity: Mapping[str, int] | None = None,
        disk_free_bytes: int = 0,
        state: str,
        bitrate_bps: int | None = None,
    ) -> None:
        """Feed the preflight pill and keep an open preflight popover in sync.

        ``state`` is ``"idle" | "disconnected" | "recording"``. When the pill
        leaves the openable ``idle`` state while its popover is open, the
        popover is dismissed (the pill is no longer a valid anchor).
        """
        self._preflight_pill.apply(
            selection if selection is not None else [],
            event_capacity if event_capacity is not None else {},
            disk_free_bytes,
            state=state,
            bitrate_bps=bitrate_bps,
        )
        if self._anchor_name == PreflightPill.NAME and self._popover_open():
            if self._preflight_pill.is_openable():
                self._popover.set_rows(self._preflight_pill.current_rows())
                self._popover.show_at(self._preflight_pill)
            else:
                self._dismiss_popover()

    def _on_preflight_clicked(self) -> None:
        # Toggle: clicking the pill while its popover is open closes it.
        if (
            self._anchor_name == PreflightPill.NAME
            and self._popover is not None
            and self._popover.isVisible()
        ):
            self._dismiss_popover()
            return
        self.open_popover(
            self._preflight_pill,
            PreflightPill.NAME,
            self._preflight_pill.current_rows(),
        )

    def _ensure_popover(self) -> HealthPopover:
        """Lazily create the single popover, parented to the host window so
        it can overlay the body below the strip (not clipped to 42 px)."""
        host = self.window() or self
        if self._popover is None:
            self._popover = HealthPopover(host)
        elif self._popover.parentWidget() is not host:
            self._popover.setParent(host)
        return self._popover

    def _on_chip_clicked(self, name: str) -> None:
        # Toggle: clicking the currently-anchored chip closes the popover.
        if self._anchor_name == name and self._popover is not None and self._popover.isVisible():
            self._dismiss_popover()
            return
        rows = self.detail_for(name, self._last_snapshot)
        self.open_popover(self._chips.get(name), name, rows)

    def open_chip_detail(self, name: str) -> None:
        """Open one chip's detail without applying the click-toggle rule."""
        anchor = self._chips.get(name)
        if anchor is None:
            return
        self.open_popover(anchor, name, self.detail_for(name, self._last_snapshot))

    def open_popover(
        self,
        anchor: QWidget | None,
        name: str,
        rows: list[tuple[str, str, HealthLevel]],
    ) -> None:
        """Open (or switch) the single popover at ``anchor`` with ``rows``.

        Public so the B2 preflight pill can reuse the same single instance.
        """
        popover = self._ensure_popover()
        popover.set_title(name)
        popover.set_rows(rows)
        popover.show_at(anchor)
        self._anchor_name = name
        self._anchor_widget = anchor
        self._install_filter()

    def _dismiss_popover(self) -> None:
        if self._popover is not None:
            self._popover.dismiss()
        self._anchor_name = None
        self._anchor_widget = None
        self._remove_filter()

    def _install_filter(self) -> None:
        if self._filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
            self._filter_installed = True

    def _remove_filter(self) -> None:
        if not self._filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._filter_installed = False

    def _popover_open(self) -> bool:
        return self._popover is not None and self._popover.isVisible()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        """Application-level close rules while the popover is open.

        Only a press that is OUTSIDE both the popover and the current anchor
        counts as an outside click — otherwise a filter-triggered close would
        race the anchor chip's own ``clicked`` handler and re-open it.
        """
        if not self._popover_open():
            return False
        etype = event.type()
        if etype == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self._dismiss_popover()
            return True
        if etype == QEvent.MouseButtonPress:
            gpos = event.globalPos()
            if not self._point_in_popover(gpos) and not self._point_in_anchor(gpos):
                self._dismiss_popover()
            return False
        if etype in (QEvent.WindowDeactivate, QEvent.ApplicationDeactivate):
            self._dismiss_popover()
            return False
        return False

    def _point_in_popover(self, gpos) -> bool:
        pop = self._popover
        if pop is None or not pop.isVisible():
            return False
        return pop.rect().contains(pop.mapFromGlobal(gpos))

    def _point_in_anchor(self, gpos) -> bool:
        anchor = self._anchor_widget
        if anchor is None:
            return False
        return anchor.rect().contains(anchor.mapFromGlobal(gpos))

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        # Re-anchor the popover to its chip after the strip (and window) resize.
        if self._popover_open() and self._anchor_widget is not None:
            self._popover.show_at(self._anchor_widget)

    # ------------------------------------------------------------------
    # Detail-row builders (backing snapshot fields only — no free text)
    # ------------------------------------------------------------------

    def detail_for(
        self,
        name: str,
        snap: HealthSnapshot | None,
    ) -> list[tuple[str, str, HealthLevel]]:
        """Rows for a chip's popover, sourced from snapshot fields only.

        Each row is ``(key, value, level)``. Row severity uses the chip's
        overall level from ``snapshot.levels()`` (existing band helpers) so
        this method never introduces new threshold judgments.
        """
        if snap is None:
            return [("状态", "no evidence yet", "off")]
        level: HealthLevel = snap.levels().get(name, "off")
        if name == "HW":
            return [
                ("驱动", snap.hw.driver_version or "—", level),
                ("通道数", str(snap.hw.channel_count), level),
            ] + ([("错误", snap.hw.error, "red")] if snap.hw.error else [])
        if name == "CAN":
            load = (
                f"{snap.can.bus_load_pct:.1f}%"
                if snap.can.bus_load_pct is not None
                else "—"
            )
            rows: list[tuple[str, str, HealthLevel]] = [("总线负载", load, level)]
            if snap.can.channels:
                rows.append(("在线通道", f"{len(snap.can.channels)}", level))
            if snap.can.bus_error_count:
                rows.append(("总线错误", str(snap.can.bus_error_count), level))
            return rows
        if name == "XCP":
            slave = (
                f"0x{snap.xcp.slave_id:X}"
                if snap.xcp.slave_id is not None
                else ("connected" if snap.xcp.connected else "—")
            )
            return [
                ("Slave ID", slave, level),
                ("连续超时", str(snap.xcp.consecutive_timeouts), level),
            ]
        if name == "DAQ":
            if not snap.daq.event_capacity:
                return [("事件槽", "no evidence yet", "off")]
            rows = []
            for event_name, cap in snap.daq.event_capacity.items():
                used = int(snap.daq.event_used.get(event_name, 0))
                rows.append((event_name, f"{used}/{int(cap)}", level))
            return rows
        if name == "REC":
            return [
                ("缓冲占用", f"{snap.rec.ring_buffer_fill_pct:.1f}%", level),
                ("丢帧", str(snap.rec.dropped_frames), level),
                ("写入速率", f"{snap.rec.write_rate_bps:.0f} /s", level),
                ("最近帧延迟", f"{snap.rec.last_rx_age_s:.2f}s", level),
            ]
        return [("状态", "no evidence yet", "off")]

    # ------------------------------------------------------------------
    # Value wiring
    # ------------------------------------------------------------------

    @staticmethod
    def _value_for(
        chip_name: str,
        snap: HealthSnapshot,
        level: HealthLevel,
    ) -> str:
        if chip_name == "HW":
            if snap.hw.ok and snap.hw.driver_version:
                return snap.hw.driver_version
            if snap.hw.ok:
                return "online"
            return "offline" if snap.hw.error else "--"
        if chip_name == "CAN":
            if snap.can.channels:
                return f"{len(snap.can.channels)} ch online"
            if snap.can.bus_load_pct is not None:
                return f"{snap.can.bus_load_pct:.0f}% load"
            return "--"
        if chip_name == "XCP":
            if snap.xcp.connected and snap.xcp.slave_id is not None:
                return f"slave 0x{snap.xcp.slave_id:X}"
            if snap.xcp.connected:
                return "connected"
            return "--"
        if chip_name == "DAQ":
            if snap.daq.event_capacity:
                used_total = sum(int(v) for v in snap.daq.event_used.values())
                event_count = len(snap.daq.event_capacity)
                return f"{used_total} sig / {event_count} evt"
            return "--"
        if chip_name == "REC":
            if snap.rec.state == "recording":
                return "recording" if level == "green" else "warn"
            if snap.rec.state == "off":
                return "ready" if level == "green" else "--"
            if snap.rec.state in {"auto_stopped", "error"}:
                return "warn"
            return "--"
        return "--"

    # ------------------------------------------------------------------
    # Tooltip wiring
    # ------------------------------------------------------------------

    @staticmethod
    def _tooltip_for(chip_name: str, snap: HealthSnapshot) -> str:
        """Return one backing-field string per spec §Health Strip.

        A field that is ``None``/unknown ⇒ ``"no evidence yet"``.
        """
        if chip_name == "HW":
            if snap.hw.driver_version is None and not snap.hw.ok:
                return _NO_EVIDENCE if snap.hw.error is None else f"HW · {snap.hw.error}"
            if snap.hw.driver_version is None:
                return _NO_EVIDENCE
            return f"driver {snap.hw.driver_version} · {snap.hw.channel_count} channel(s)"
        if chip_name == "CAN":
            if snap.can.bus_load_pct is None:
                return _NO_EVIDENCE
            return f"bus load {snap.can.bus_load_pct:.1f}%"
        if chip_name == "XCP":
            if snap.xcp.slave_id is None:
                return _NO_EVIDENCE if not snap.xcp.connected else "connected · slave id unknown"
            return f"slave id {snap.xcp.slave_id} · timeouts {snap.xcp.consecutive_timeouts}"
        if chip_name == "DAQ":
            if not snap.daq.event_capacity:
                return _NO_EVIDENCE
            cap_total = sum(int(v) for v in snap.daq.event_capacity.values())
            used_total = sum(int(v) for v in snap.daq.event_used.values())
            return f"capacity {used_total}/{cap_total}"
        if chip_name == "REC":
            return (
                f"ring buffer {snap.rec.ring_buffer_fill_pct:.1f}% · "
                f"state {snap.rec.state}"
            )
        return ""
