"""Read-only MF4 replay tab for the Acquisition Cockpit.

The replay path is intentionally tab-local: it owns its
``ReplayRecorderBackend``, ``LiveCardGrid``, and ``RightPanel`` instances
and never creates a ``CaptureController`` writer session.
"""

from __future__ import annotations

import time
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.acquisition_capture.backends import (
    ReplayRecorderBackend,
    ReplaySource,
)
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    DaqHealth,
    HealthSnapshot,
    HwHealth,
    RecHealth,
    XcpHealth,
)
from mf4_analyzer.acquisition_ui.widgets.live_cards import LiveCardGrid
from mf4_analyzer.acquisition_ui.widgets.right_panel import RightPanel


ReplayState = str
SPEED_OPTIONS = (0.25, 0.5, 1.0, 2.0, 4.0)


class ReplayTab(QWidget):
    """Standalone read-only replay controller for one MF4 file."""

    state_changed = pyqtSignal(str)

    def __init__(
        self,
        *,
        poll_interval_ms: int = 33,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ReplayTab")
        self._source: ReplaySource | None = None
        self._backend: ReplayRecorderBackend | None = None
        self._state: ReplayState = "idle"
        self._speed_multiplier = 1.0
        self._last_position_s = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(int(poll_interval_ms))
        self._timer.timeout.connect(self.drain_once)

        self._build_ui()
        self._set_transport_enabled(False)
        self._apply_state("idle")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        transport = QFrame(self)
        transport.setObjectName("replayTransport")
        row = QHBoxLayout(transport)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._file_btn = QPushButton("选择 MF4", self)
        self._file_btn.setObjectName("replayPickFileButton")
        self._file_btn.clicked.connect(self._pick_file)
        row.addWidget(self._file_btn)

        self._path_label = QLabel("未选择文件", self)
        self._path_label.setObjectName("replayPathLabel")
        row.addWidget(self._path_label, stretch=1)

        self._speed_group = QButtonGroup(self)
        self._speed_group.setExclusive(True)
        for speed in SPEED_OPTIONS:
            btn = QPushButton(f"{speed:g}×", self)
            btn.setObjectName(f"replaySpeed{speed:g}x")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, s=speed: self.set_speed_multiplier(s))
            self._speed_group.addButton(btn)
            row.addWidget(btn)
            if speed == 1.0:
                btn.setChecked(True)

        self._play_btn = QPushButton("▶ Play", self)
        self._play_btn.setObjectName("replayPlayButton")
        self._play_btn.clicked.connect(self.play)
        row.addWidget(self._play_btn)

        self._pause_btn = QPushButton("⏸ Pause", self)
        self._pause_btn.setObjectName("replayPauseButton")
        self._pause_btn.clicked.connect(self.pause)
        row.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("⏹ Stop", self)
        self._stop_btn.setObjectName("replayStopButton")
        self._stop_btn.clicked.connect(self.stop)
        row.addWidget(self._stop_btn)

        outer.addWidget(transport)

        progress_row = QHBoxLayout()
        self._position_label = QLabel("00:00.000", self)
        self._position_label.setObjectName("replayPositionLabel")
        progress_row.addWidget(self._position_label)
        self._position_slider = QSlider(Qt.Horizontal, self)
        self._position_slider.setObjectName("replayPositionSlider")
        self._position_slider.setEnabled(False)
        self._position_slider.setMinimum(0)
        self._position_slider.setMaximum(0)
        progress_row.addWidget(self._position_slider, stretch=1)
        outer.addLayout(progress_row)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setObjectName("replaySplitter")
        splitter.setChildrenCollapsible(False)
        self._live_cards = LiveCardGrid(splitter)
        self._right_panel = RightPanel(splitter)
        splitter.addWidget(self._live_cards)
        splitter.addWidget(self._right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        outer.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------------
    # File and speed controls
    # ------------------------------------------------------------------

    def _pick_file(self) -> None:
        file_name, _filter = QFileDialog.getOpenFileName(
            self,
            "选择回放 MF4",
            "",
            "MF4 files (*.mf4 *.MF4);;All files (*)",
        )
        if file_name:
            self.load_file(file_name)

    def load_file(self, path: str | Path) -> None:
        source = ReplayRecorderBackend.source_from_mf4(path)
        self.stop()
        self._source = source
        self._path_label.setText(str(source.path))
        self._last_position_s = 0.0
        self._position_slider.setMaximum(max(0, int(source.duration_s * 1000)))
        self._position_slider.setValue(0)
        self._position_label.setText(self._format_position(0.0))
        self._live_cards.set_signals(
            [(m.name, m.unit, None) for m in source.selected]
        )
        for card in self._live_cards.cards.values():
            card.reset_buffer()
        self._right_panel.show_idle(
            selection=source.selected,
            event_capacity={},
            disk_free_bytes=10 * 1024 * 1024 * 1024,
        )
        self._set_transport_enabled(True)
        self._apply_state("idle")

    def set_speed_multiplier(self, speed: float) -> None:
        speed = float(speed)
        if speed <= 0:
            raise ValueError("speed must be positive")
        self._speed_multiplier = speed
        if self._backend is not None:
            self._backend.speed_multiplier = speed
        for button in self._speed_group.buttons():
            button.setChecked(button.text() == f"{speed:g}×")

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def play(self) -> None:
        if self._source is None:
            raise RuntimeError("load an MF4 before replaying")
        if self._state == "paused" and self._backend is not None:
            self._backend.resume()
        else:
            self._backend = ReplayRecorderBackend(
                source_samples=list(self._source.source_samples),
                speed_multiplier=self._speed_multiplier,
            )
            self._backend.start(self._source.selected)
            self._last_position_s = 0.0
            self._position_slider.setValue(0)
            for card in self._live_cards.cards.values():
                card.reset_buffer()
        self._live_cards.set_recording(True, 0.0)
        self._timer.start()
        self._apply_state("playing")
        self._refresh_right_panel()

    def pause(self) -> None:
        if self._state != "playing":
            return
        self._timer.stop()
        if self._backend is not None:
            self._backend.pause()
        self._apply_state("paused")
        self._refresh_right_panel()

    def stop(self) -> None:
        self._timer.stop()
        if self._backend is not None:
            self._backend.stop()
        self._live_cards.set_recording(False, None)
        self._last_position_s = 0.0
        self._position_slider.setValue(0)
        self._position_label.setText(self._format_position(0.0))
        if self._source is None:
            self._apply_state("idle")
        else:
            self._apply_state("stopped")
            self._refresh_right_panel()

    def drain_once(self) -> None:
        if self._backend is None or self._state != "playing":
            return
        samples = self._backend.poll()
        for channel, ts, value in samples:
            self._live_cards.push_sample(channel, ts, value)
            if ts >= self._last_position_s:
                self._last_position_s = ts
        if samples:
            self._live_cards.refresh_all(now_ts=self._last_position_s)
            self._position_slider.setValue(int(self._last_position_s * 1000))
            self._position_label.setText(self._format_position(self._last_position_s))
        self._refresh_right_panel()
        if self._backend.finished:
            self.stop()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_state(self, state: ReplayState) -> None:
        if self._state != state:
            self._state = state
            self.state_changed.emit(state)
        else:
            self._state = state
        self._play_btn.setEnabled(self._source is not None and state != "playing")
        self._pause_btn.setEnabled(state == "playing")
        self._stop_btn.setEnabled(self._source is not None and state in {"playing", "paused"})

    def _set_transport_enabled(self, enabled: bool) -> None:
        self._play_btn.setEnabled(enabled)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)

    def _refresh_right_panel(self) -> None:
        self._right_panel.show_recording(
            snapshot=self._snapshot_for_replay(),
            disk_free_bytes=10 * 1024 * 1024 * 1024,
        )

    def _snapshot_for_replay(self) -> HealthSnapshot:
        now = time.monotonic()
        status = self._backend.status() if self._backend is not None else None
        rec_state = "recording" if self._state == "playing" else "off"
        return HealthSnapshot(
            hw=HwHealth(
                ok=True,
                driver_version=None,
                channel_count=0,
                last_probe_ts=now,
                error=None,
            ),
            can=CanHealth(bus_load_pct=None),
            xcp=XcpHealth(connected=True),
            daq=DaqHealth(),
            rec=RecHealth(
                state=rec_state,
                ring_buffer_fill_pct=0.0,
                dropped_frames=status.queue_overflow_count if status else 0,
                write_rate_bps=0.0,
                last_rx_age_s=0.0,
                writer_thread_alive=True,
            ),
            captured_at=now,
        )

    @staticmethod
    def _format_position(seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        mins = int(seconds // 60)
        whole = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        return f"{mins:02d}:{whole:02d}.{millis:03d}"

    # ------------------------------------------------------------------
    # Test/coordinator accessors
    # ------------------------------------------------------------------

    @property
    def source_path(self) -> Path | None:
        return self._source.path if self._source is not None else None

    @property
    def state(self) -> str:
        return self._state

    @property
    def speed_multiplier(self) -> float:
        return self._speed_multiplier

    @property
    def backend(self) -> ReplayRecorderBackend | None:
        return self._backend

    @property
    def live_cards(self) -> LiveCardGrid:
        return self._live_cards

    @property
    def right_panel(self) -> RightPanel:
        return self._right_panel

    @property
    def position_slider(self) -> QSlider:
        return self._position_slider
