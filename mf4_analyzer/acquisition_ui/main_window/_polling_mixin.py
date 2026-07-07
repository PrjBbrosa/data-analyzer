"""PollingMixin: health/live polling + auto-stop for CockpitMainWindow."""

from __future__ import annotations

import logging
import time

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.health import HealthSnapshot
from mf4_analyzer.acquisition_capture.ring_buffer import WatermarkLevel
from mf4_analyzer.acquisition_capture.session import SessionSummary
from mf4_analyzer.acquisition_ui.state import (
    CockpitState,
    HealthyPredicateResult,
)

logger = logging.getLogger(__name__)


class PollingMixin:
    """Domain mixin: health polling, live data polling, and auto-stop.

    All methods become CockpitMainWindow instance methods.
    They may only reference ``self.*`` attributes set in
    ``CockpitMainWindow.__init__``.
    """

    # ------------------------------------------------------------------
    # Health polling slot (QTimer)
    # ------------------------------------------------------------------

    def _poll_health(self) -> None:
        snapshot = self._health_aggregator.poll_once()
        self._health_strip.apply_snapshot(snapshot)
        self._update_record_button_enabled()
        # Disconnected → ConnectedIdle gate.
        if self._state_machine.state == CockpitState.DISCONNECTED:
            self._evaluate_connection_attempt(snapshot)
        elif self._state_machine.state == CockpitState.CONNECTED_IDLE:
            self._refresh_idle_right_panel()
        elif self._state_machine.state == CockpitState.RECORDING:
            self._refresh_recording_right_panel()
            self._check_recording_auto_stop()

    def _evaluate_connection_attempt(self, snapshot: HealthSnapshot) -> None:
        if self._connection_attempt_started is None:
            return
        elapsed = time.monotonic() - self._connection_attempt_started
        first_frame = self._first_frame_ts is not None
        verdict = HealthyPredicateResult.from_components(
            hw_ok=snapshot.hw.ok,
            xcp_connected=snapshot.xcp.connected,
            first_frame_received=first_frame,
        )
        if verdict.healthy:
            self._state_machine.request_connect(verdict)
            self._connection_attempt_started = None
            return
        # Timeout: connection_timeout_s without a frame returns to
        # Disconnected and surfaces the first failing predicate.
        if elapsed >= thresholds.CONNECTION_TIMEOUT_S:
            self._connection_attempt_started = None
            self._fake_xcp_connected = False
            # Stash the verdict so the right panel can quote the
            # failure even though the state stays Disconnected.
            self._state_machine.request_connect(verdict)
            # Tear down backend.
            try:
                self._backend.stop()
            except Exception:
                pass
            self._apply_state_to_ui(
                CockpitState.DISCONNECTED, CockpitState.DISCONNECTED
            )

    # ------------------------------------------------------------------
    # Live data poll
    # ------------------------------------------------------------------

    def _poll_live(self) -> None:
        controller = self._capture_controller
        if (
            controller is not None
            and self._state_machine.state == CockpitState.RECORDING
            and hasattr(controller, "poll_step")
        ):
            self._poll_live_recording(controller)
            return
        try:
            samples = self._backend.poll()
        except Exception:
            samples = []
        if samples:
            if self._first_frame_ts is None:
                self._first_frame_ts = time.monotonic()
            self._fake_last_rx_monotonic = time.monotonic()
        for channel, ts, value in samples:
            # Spec 2026-07-07 F2: ring is recording-path only; idle
            # streaming feeds cards directly.
            self._center.push_sample(channel, ts, value)
        # Repaint sparklines.
        self._center.refresh_all()
        # Update cumulative counters.
        self._cumulative_rx_count += len(samples)
        if self._state_machine.state == CockpitState.RECORDING:
            # Legacy non-controller recording path only; controller
            # recording is handled by _poll_live_recording().
            self._cumulative_dropped = self._ring.dropped_frames
        self._update_status_bar()
        if (
            self._state_machine.state == CockpitState.RECORDING
            and self._cumulative_dropped > thresholds.DROPPED_FRAMES_PROMPT_TOTAL
            and self._dropped_prompt_can_fire()
        ):
            self._show_dropped_frames_prompt()

    def _poll_live_recording(self, controller) -> None:
        """Recording path: controller owns backend -> ring -> writer."""
        try:
            controller.poll_step()
        except Exception as exc:  # noqa: BLE001 - surface, keep UI responsive
            logger.exception("controller poll_step failed")
            self._status.showMessage(f"录制轮询失败: {exc}")
        self._cumulative_dropped = self._ring.dropped_frames
        self._center.refresh_all()
        self._update_status_bar()
        if not controller.running:
            self.request_stop_and_review(
                auto_stop=bool(getattr(controller, "auto_stopped", False))
            )
            return
        if (
            self._cumulative_dropped > thresholds.DROPPED_FRAMES_PROMPT_TOTAL
            and self._dropped_prompt_can_fire()
        ):
            self._show_dropped_frames_prompt()

    # ------------------------------------------------------------------
    # Watermark wiring — spec §Threshold Contract Watermark wiring
    # ------------------------------------------------------------------

    def _on_ring_watermark_changed(self, level: WatermarkLevel) -> None:
        """Bridge from the non-Qt observer to Qt slots — FPS only.

        Auto-stop authority (2026-07-07 spec F2): recording ring >=95%
        for 5s is judged by CaptureController._check_auto_stop; disk
        space is judged by _check_recording_auto_stop. An instantaneous
        watermark level must not stop recording.
        """
        if level in ("green", "yellow_low"):
            self.set_target_fps(thresholds.LIVE_FPS_NORMAL)
        else:
            self.set_target_fps(thresholds.LIVE_FPS_DEGRADED)

    def set_target_fps(self, fps: int) -> None:
        """Spec §Threshold Contract Watermark wiring: 30→10 fps."""
        fps = int(fps)
        if fps <= 0:
            return
        self._target_fps = fps
        interval = max(1, int(1000 / fps))
        self._live_timer.setInterval(interval)

    def _on_auto_stop_request(self, reason: str) -> None:
        """Auto-stop entry point — RECORDING state only."""
        self.auto_stop_requested.emit(reason)
        self._status.showMessage(f"自动停止已请求 ({reason})")
        if self._state_machine.state != CockpitState.RECORDING:
            return
        self.request_stop_and_review(auto_stop=True)
        if self._last_session_summary is None:
            self._last_session_summary = SessionSummary(auto_stop=True)
        else:
            self._last_session_summary.auto_stop = True
        if (
            self._state_machine.state == CockpitState.RECORDING
            and self._capture_controller is not None
        ):
            # If stop/flush/finalize raised before flipping the state,
            # still terminate the four-state cycle.
            self._state_machine.request_stop_recording(finalized=True)
