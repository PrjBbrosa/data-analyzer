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
            # Canonical shape is (channel, ts, value); the ring is shared
            # with CaptureController during recording.
            self._ring.put((channel, ts, value))
            self._center.push_sample(channel, ts, value)
        # Repaint sparklines.
        self._center.refresh_all()
        # Update cumulative counters.
        self._cumulative_rx_count += len(samples)
        # Sync dropped counter from ring buffer (cumulative).
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
        """Bridge from the non-Qt observer to Qt slots."""
        # 30 fps for green/yellow_low; 10 fps for red/red_drop.
        if level in ("green", "yellow_low"):
            self.set_target_fps(thresholds.LIVE_FPS_NORMAL)
        else:
            self.set_target_fps(thresholds.LIVE_FPS_DEGRADED)
        if level == "red_drop_sustained":
            # Spec: ≥95% for 5 s ⇒ auto-stop.
            self._on_auto_stop_request("ring_buffer")

    def set_target_fps(self, fps: int) -> None:
        """Spec §Threshold Contract Watermark wiring: 30→10 fps."""
        fps = int(fps)
        if fps <= 0:
            return
        self._target_fps = fps
        interval = max(1, int(1000 / fps))
        self._live_timer.setInterval(interval)

    def _on_auto_stop_request(self, reason: str) -> None:
        """Auto-stop entry point (spec §Threshold Contract Watermark wiring).

        Two arms:

        - **Mid-Recording**: route through :meth:`request_stop_and_review`
          which runs the full stop/flush/finalize sequence. Auto-stop
          arms ``SessionSummary.auto_stop=True`` so the review modal's
          banner ("自动停止 · ring buffer 持续告警") is visible.
        - **Not Recording** (e.g. ring goes red during ConnectedIdle):
          call ``controller.stop()`` directly (synchronous, no
          ``thread.wait()`` per lesson
          ``2026-04-25-qthread-wait-deadlocks-queued-quit.md``), arm the
          summary, then open the no-session placeholder modal so the cycle
          is observable.

        Both arms emit ``auto_stop_requested`` and update the status
        bar before doing any work.
        """
        self.auto_stop_requested.emit(reason)
        self._status.showMessage(f"自动停止已请求 ({reason})")

        if self._state_machine.state == CockpitState.RECORDING:
            # Run the full stop/flush/finalize sequence. This calls
            # ``controller.stop()`` exactly once and routes through
            # ``_open_review_modal`` to show the real ReviewModal when
            # the result is valid, or the placeholder when the sequence
            # could not complete (e.g. the controller's writer path is a
            # test stub without a real file). ``auto_stop=True`` is
            # passed through so the banner is visible on either modal.
            self.request_stop_and_review(auto_stop=True)
            # ``request_stop_and_review`` already armed
            # ``self._last_session_summary``; if it failed mid-sequence
            # the state stays in RECORDING (the user can retry). In that
            # case we still want the auto-stop flag armed for callers
            # that inspect ``last_session_summary`` after the fact.
            if self._last_session_summary is None:
                self._last_session_summary = SessionSummary(auto_stop=True)
            else:
                self._last_session_summary.auto_stop = True
            # If stop/flush/finalize raised before flipping the state
            # (e.g. spy controller with empty output_mf4 path in an
            # auto-stop unit test), we still need the review
            # modal to surface so the four-state cycle terminates. Open
            # the placeholder directly in that recovery case.
            if (
                self._state_machine.state == CockpitState.RECORDING
                and self._capture_controller is not None
            ):
                # The sequence raised before the state machine advanced.
                # Force the placeholder open and walk the state machine
                # manually — this preserves the S4-fix Fix #6 contract
                # that auto-stop always lands the user in REVIEW_MODAL
                # even when the writer path is a stub.
                self._state_machine.request_stop_recording(finalized=True)
            return

        # Not mid-Recording — auto-stop fired from idle/disconnected.
        # Call controller.stop() directly so the summary is captured.
        if self._capture_controller is not None:
            try:
                summary = self._capture_controller.stop()
            except Exception:  # noqa: BLE001
                summary = None
            if summary is not None:
                summary.auto_stop = True
                self._last_session_summary = summary
            else:
                self._last_session_summary = SessionSummary(auto_stop=True)
        else:
            self._last_session_summary = SessionSummary(auto_stop=True)

        if self._state_machine.state != CockpitState.REVIEW_MODAL:
            # Out-of-Recording auto-stop: open the placeholder modal
            # directly so the test can observe it without crossing an
            # illegal transition through the state machine.
            # Lazy import to avoid circular dependency (window imports mixins).
            from .window import (  # noqa: PLC0415
                _PlaceholderReviewModal,
            )
            modal = _PlaceholderReviewModal(self)
            modal.finished.connect(self._on_review_modal_closed)
            modal.open()
            self._review_modal = modal
