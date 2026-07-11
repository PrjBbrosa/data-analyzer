"""Capture-session lifecycle for CockpitMainWindow.

Sample shape contract everywhere: ``(channel_name, timestamp, value)``
matches recorder backends and ``Mf4Writer.append_batch``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

from mf4_analyzer.acquisition_capture.backends import ReplayRecorderBackend
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
)
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from mf4_analyzer.acquisition_ui.state import CockpitState

logger = logging.getLogger(__name__)


class CaptureSessionMixin:
    """Domain mixin: capture-session lifecycle."""

    def _next_output_path(self) -> Path:
        out_dir = Path(self._output_dir_label).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = out_dir / f"capture_{stamp}.mf4"
        seq = 1
        while candidate.exists():
            candidate = out_dir / f"capture_{stamp}_{seq}.mf4"
            seq += 1
        return candidate

    def _capture_backend_kind(self) -> str:
        if self._owns_vector_backend:
            return "vector"
        if isinstance(self._backend, ReplayRecorderBackend):
            return "replay"
        return "fake"

    def _build_session_config(self) -> SessionConfig:
        selection = (
            tuple(self._left_pane.current_selection())
            if hasattr(self, "_left_pane")
            else ()
        )
        if not selection and self._allow_fake_backend:
            selection = (SelectedMeasurement(name="DemoSignal"),)
        return SessionConfig(
            output_mf4=self._next_output_path(),
            selected=selection,
            backend=self._capture_backend_kind(),
            transport=self._transport_config or TransportConfig(),
        )

    def _begin_capture_session(self) -> bool:
        """Construct and start a real CaptureController for recording."""
        if self._capture_controller is not None:
            return True
        try:
            config = self._build_session_config()
        except ValueError as exc:
            self._status.showMessage(f"无法开始录制: {exc}")
            return False

        backend_started = bool(self._backend.status().started)
        if not backend_started:
            self._stop_backend_best_effort(self._backend)
        self._ring.drain()
        controller = CaptureController(
            config,
            self._backend,
            ring=self._ring,
            sample_tap=self._on_capture_samples,
        )
        try:
            if backend_started:
                controller.start_attached()
            else:
                controller.start()
        except Exception as exc:  # noqa: BLE001 - surface, stay idle
            logger.exception("capture session start failed")
            self._status.showMessage(f"无法开始录制: {exc}")
            self._resume_idle_stream()
            return False
        self.set_capture_controller(controller)
        self._status.showMessage(f"录制中 -> {config.output_mf4}")
        return True

    def _on_capture_samples(self, samples: list[tuple[str, float, float]]) -> None:
        """Feed live cards and health counters from controller sample_tap."""
        now = time.monotonic()
        if samples:
            if self._first_frame_ts is None:
                self._first_frame_ts = now
            self._fake_last_rx_monotonic = now
            self._cumulative_rx_count += len(samples)
        for channel, ts, value in samples:
            self._center.push_sample(channel, ts, value)

    def _teardown_capture_session(self) -> None:
        self.set_capture_controller(None)
        self._fake_rec_state = "off"
        self._update_backend_badge()

    def _restart_idle_stream_for_selection(self) -> None:
        """Debounced idle-stream restart after a selection edit."""
        if getattr(self, "_idle_restart_timer", None) is not None:
            self._idle_restart_timer.stop()
        if self._state_machine.state != CockpitState.CONNECTED_IDLE:
            return
        if self._capture_controller is not None:
            return
        if self._invalidate_vector_for_selection_change():
            return
        selection = list(self._left_pane.current_selection())
        if not selection:
            selection = [SelectedMeasurement(name="DemoSignal")]
        try:
            self._backend.start(selection)
        except Exception as exc:  # noqa: BLE001 - best-effort restart
            logger.warning("idle stream restart failed: %s", exc)
            self._status.showMessage(f"实时流重启失败: {exc}")
            return
        self._center.reset_buffers()
        self._stream_start_ts = time.monotonic()
        self._cumulative_rx_count = 0

    def _invalidate_vector_for_selection_change(self) -> bool:
        """Drop an owned Vector session whose programmed DAQ is now stale."""

        if self._state_machine.state != CockpitState.CONNECTED_IDLE:
            return False
        if not self._owns_vector_backend:
            return False
        timer = getattr(self, "_idle_restart_timer", None)
        if timer is not None:
            timer.stop()
        return self._disconnect_owned_vector_for_configuration_change(
            "Vector/XCP measurement 或 event 已改变：已断开，请重新连接以应用"
        )

    def _resume_idle_stream(self) -> None:
        """Best-effort restart of the idle live stream after review close."""
        if self._backend.status().started:
            return
        selection = (
            list(self._left_pane.current_selection())
            if hasattr(self, "_left_pane")
            else []
        )
        if not selection:
            selection = [SelectedMeasurement(name="DemoSignal")]
        try:
            self._backend.start(selection)
        except Exception as exc:  # noqa: BLE001 - best-effort resume
            logger.warning("idle stream resume failed: %s", exc)
            self._status.showMessage(f"实时流恢复失败: {exc}")
            return
        self._center.reset_buffers()
        self._stream_start_ts = time.monotonic()
        self._cumulative_rx_count = 0
