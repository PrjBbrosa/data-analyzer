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

from typing import Mapping

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from mf4_analyzer.acquisition_capture.health import (
    HealthLevel,
    HealthSnapshot,
)


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
    """

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("healthChip")
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
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
        self.set_level("off")

    @property
    def name(self) -> str:
        return self._name

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
            self._chips[name] = chip
            layout.addWidget(chip)
        layout.addStretch(1)
        self._summary = QLabel("--", self)
        self._summary.setObjectName("healthSummary")
        self._summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._summary)
        self._last_levels: dict[str, HealthLevel] = {n: "off" for n in self.CHIP_NAMES}
        self._last_snapshot: HealthSnapshot | None = None

    # ------------------------------------------------------------------
    # Snapshot binding
    # ------------------------------------------------------------------

    def apply_snapshot(self, snapshot: HealthSnapshot) -> None:
        """Repaint chips for the given snapshot and emit ``levels_changed``."""
        self._last_snapshot = snapshot
        new_levels: dict[str, HealthLevel] = snapshot.levels()
        for name in self.CHIP_NAMES:
            level = new_levels.get(name, "off")
            chip = self._chips[name]
            chip.set_level(level)
            chip.set_value(self._value_for(name, snapshot, level))
            chip.set_tooltip(self._tooltip_for(name, snapshot))
        self._summary.setText(self._summary_for(new_levels))
        if new_levels != self._last_levels:
            self._last_levels = dict(new_levels)
            self.levels_changed.emit(dict(new_levels))

    def chip(self, name: str) -> HealthChip:
        """Return the chip widget for a given name (test introspection)."""
        return self._chips[name]

    def current_levels(self) -> Mapping[str, HealthLevel]:
        return dict(self._last_levels)

    @property
    def last_snapshot(self) -> HealthSnapshot | None:
        return self._last_snapshot

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

    @staticmethod
    def _summary_for(levels: Mapping[str, HealthLevel]) -> str:
        ordered_levels: tuple[HealthLevel, ...] = ("red", "yellow", "off", "green")
        counts = {
            level: sum(1 for value in levels.values() if value == level)
            for level in ordered_levels
        }
        if counts["red"]:
            return f"{counts['red']} red"
        if counts["yellow"]:
            return f"{counts['yellow']} yellow"
        if counts["off"]:
            return f"{counts['off']} off"
        return f"{counts['green']}/{len(levels)} green"

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
