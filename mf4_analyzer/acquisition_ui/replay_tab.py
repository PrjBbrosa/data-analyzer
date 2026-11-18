"""Read-only MF4 replay tab for the Acquisition Cockpit.

The replay path is intentionally tab-local: it owns its
``ReplayRecorderBackend``, ``LiveCardGrid``, and ``RightPanel`` instances
and never creates a ``CaptureController`` writer session.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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
        self._retained_source: ReplaySource | None = None
        self._backend: ReplayRecorderBackend | None = None
        self._state: ReplayState = "idle"
        self._speed_multiplier = 1.0
        self._last_position_s = 0.0
        self._segment_start_s = 0.0
        self._filling_segments = False

        self._timer = QTimer(self)
        self._timer.setInterval(int(poll_interval_ms))
        self._timer.timeout.connect(self.drain_once)

        self._build_ui()
        from mf4_analyzer.ui.main_window.import_coordinator import ImportCoordinator
        self._imports = ImportCoordinator(self)
        self._imports.drained.connect(self._resume_close_after_import)
        if parent is not None:
            parent.window().installEventFilter(self)
        self._live_cards.set_placeholder_copy(
            title="未加载 MF4",
            body="回放会在这里显示信号趋势与当前值。",
            action="使用左上「选择 MF4」打开录制文件",
        )
        self._right_panel.setVisible(False)
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

        self._alignment_warning = QLabel("", self)
        self._alignment_warning.setObjectName("replayAlignmentWarning")
        self._alignment_warning.setWordWrap(True)
        self._alignment_warning.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._alignment_warning.setVisible(False)
        outer.addWidget(self._alignment_warning)

        segment_row = QHBoxLayout()
        self._segment_label = QLabel("回放段", self)
        self._segment_label.setObjectName("replaySegmentLabel")
        self._segment_label.setVisible(False)
        segment_row.addWidget(self._segment_label)
        self._segment_combo = QComboBox(self)
        self._segment_combo.setObjectName("replaySegmentCombo")
        self._segment_combo.setVisible(False)
        self._segment_combo.currentIndexChanged.connect(self._on_segment_chosen)
        segment_row.addWidget(self._segment_combo, stretch=1)
        outer.addLayout(segment_row)

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

    def _apply_source_warning(self, source: ReplaySource) -> None:
        """Show loader alignment text before transport is enabled."""
        mode = str(getattr(source, "replay_mode", "legacy_table") or "legacy_table")
        if mode != "legacy_table":
            details = tuple(getattr(source, "notices", ()) or ())
            if not details:
                self._alignment_warning.clear()
                self._alignment_warning.setVisible(False)
                return
            self._alignment_warning.setText("\n".join(str(item) for item in details))
            self._alignment_warning.setVisible(True)
            return
        details = tuple(source.warnings or ())
        if not details:
            self._alignment_warning.clear()
            self._alignment_warning.setVisible(False)
            return
        lines = ["已按公共时间轴对齐，可能包含非原始测量值", *details]
        self._alignment_warning.setText("\n".join(lines))
        self._alignment_warning.setVisible(True)

    def load_file(self, path: str | Path) -> None:
        """Schedule a supervised parse and background ReplaySource conversion."""
        from mf4_analyzer.ui.main_window.import_coordinator import ImportCall
        self._imports.invalidate_session()
        self.stop()
        self._set_transport_enabled(False)

        def workflow(request):
            from mf4_analyzer.ui_kit.import_progress_dialog import ImportProgressDialog
            dialog = ImportProgressDialog(self, title="读取回放文件")
            dialog.cancel_requested.connect(self._imports.on_progress_cancel)
            self._imports.open_progress(
                request,
                dialog,
                title="读取回放文件",
                file_count=1,
                path=str(path),
                phase="读取回放文件",
            )
            dialog.show()
            try:
                source = yield ImportCall(
                    "load_mf4_native", str(path),
                    transform=ReplayRecorderBackend.source_from_loaded,
                )
                self._adopt_source(source)
                request.loaded_files += 1
            finally:
                from PyQt5 import sip
                if not sip.isdeleted(self) and not self._imports.closing:
                    self._set_transport_enabled(self._source is not None)

        self._imports.submit(workflow, on_done=self._on_import_done)

    def _on_import_done(self, status, value):
        if status != "failed":
            return
        if getattr(value, "resource_dialog_presented", False):
            return
        from mf4_analyzer.io.import_limits import resource_user_text

        text = str(value)
        if getattr(value, "code", "") == "resource_limit":
            text = resource_user_text(value)
        QMessageBox.critical(self, "无法加载回放文件", text)

    def eventFilter(self, watched, event):
        # Parent close does not deliver closeEvent to every child. Hold its
        # teardown until our supervised process has been cancelled and reaped.
        if event.type() == QEvent.Close and watched is self.window():
            if not self._imports.shutdown():
                event.ignore()
                return True
            self.stop()
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        if not self._imports.shutdown():
            event.ignore()
            return
        self.stop()
        super().closeEvent(event)

    def _resume_close_after_import(self):
        if self._imports.closing and not self._imports.busy:
            self.window().close()

    def _adopt_source(self, source: ReplaySource) -> None:
        self._source = source
        self._apply_source_warning(source)
        self._right_panel.setVisible(True)
        self._path_label.setText(str(source.path))
        self._last_position_s = 0.0
        self._position_slider.setMaximum(max(0, int(source.duration_s * 1000)))
        self._position_slider.setValue(0)
        self._position_label.setText(self._format_position(0.0))
        self._retained_source = source
        self._release_backend()
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
        self._fill_segment_choices(source)
        self._arm_position(source)
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
        if not self._playback_ready():
            return
        if self._state == "paused" and self._backend is not None:
            self._backend.resume()
        else:
            self._arm_position(self._source)
            self._backend = ReplayRecorderBackend(
                source_samples=list(self._source.source_samples),
                speed_multiplier=self._speed_multiplier,
                time_origin=self._segment_start_s,
            )
            self._backend.start(self._source.selected)
            self._last_position_s = self._segment_start_s
            self._position_slider.setValue(self._position_ms(self._segment_start_s))
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
        self._last_position_s = self._segment_start_s
        self._position_slider.setValue(self._position_ms(self._segment_start_s))
        self._position_label.setText(self._format_position(self._segment_start_s))
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
            self._live_cards.refresh_all()
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
        self._play_btn.setEnabled(self._playback_ready() and state != "playing")
        self._pause_btn.setEnabled(state == "playing")
        self._stop_btn.setEnabled(self._source is not None and state in {"playing", "paused"})

    def _set_transport_enabled(self, enabled: bool) -> None:
        if not enabled:
            self._play_btn.setEnabled(False)
            self._pause_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
            return
        self._play_btn.setEnabled(self._playback_ready() and self._state != "playing")
        self._pause_btn.setEnabled(self._state == "playing")
        self._stop_btn.setEnabled(
            self._source is not None and self._state in {"playing", "paused"}
        )

    def _playback_ready(self) -> bool:
        source = self._source
        if source is None or source.replay_mode == "segment_required":
            return False
        return bool(source.source_samples)

    def _release_backend(self) -> None:
        self._timer.stop()
        if self._backend is not None:
            self._backend.stop()
            self._backend = None
        self._live_cards.set_recording(False, None)

    def _clear_card_buffers(self) -> None:
        for card in self._live_cards.cards.values():
            card.reset_buffer()

    @staticmethod
    def _position_ms(seconds: float) -> int:
        return int(round(float(seconds) * 1000.0))

    def _sample_bounds(self, source: ReplaySource) -> tuple[float, float]:
        stamps = []
        for _channel, stamp, _value in source.source_samples:
            try:
                value = float(stamp)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                stamps.append(value)
        if not stamps:
            return 0.0, float(source.duration_s or 0.0)
        return min(stamps), max(stamps)

    def _arm_position(self, source: ReplaySource) -> None:
        start, end = self._sample_bounds(source)
        self._segment_start_s = start
        self._last_position_s = start
        self._position_slider.setMinimum(self._position_ms(start))
        self._position_slider.setMaximum(self._position_ms(end))
        self._position_slider.setValue(self._position_ms(start))
        self._position_label.setText(self._format_position(start))

    def _fill_segment_choices(self, source: ReplaySource) -> None:
        show = (
            source.replay_mode == "segment_required"
            and ReplayRecorderBackend.segment_block_reason(source) is None
        )
        options = ReplayRecorderBackend.segment_options(source) if show else ()
        self._filling_segments = True
        self._segment_combo.blockSignals(True)
        try:
            self._segment_combo.clear()
            if not options:
                self._segment_combo.setVisible(False)
                self._segment_label.setVisible(False)
                return
            self._segment_combo.addItem("请选择回放段", None)
            for option in options:
                self._segment_combo.addItem(str(option["text"]), int(option["segment"]))
            self._segment_combo.setCurrentIndex(0)
            self._segment_combo.setVisible(True)
            self._segment_label.setVisible(True)
        finally:
            self._segment_combo.blockSignals(False)
            self._filling_segments = False

    def _on_segment_chosen(self, index: int) -> None:
        if self._filling_segments or self._retained_source is None:
            return
        if index < 0:
            return
        was_playing = self._state == "playing"
        data = self._segment_combo.itemData(index)
        self._release_backend()
        self._clear_card_buffers()
        if data is None:
            self._source = self._retained_source
            self._apply_source_warning(self._source)
            self._arm_position(self._source)
            self._apply_state("stopped")
            return
        try:
            chosen = ReplayRecorderBackend.select_retained_segment(
                self._retained_source, int(data),
            )
        except ValueError as exc:
            self._source = self._retained_source
            self._alignment_warning.setText(str(exc))
            self._alignment_warning.setVisible(True)
            self._arm_position(self._source)
            self._apply_state("stopped")
            return
        self._source = chosen
        self._apply_source_warning(chosen)
        self._arm_position(chosen)
        if was_playing and self._playback_ready():
            self.play()
            return
        self._apply_state("stopped")

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
