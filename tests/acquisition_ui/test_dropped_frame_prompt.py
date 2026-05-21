"""Dropped-frames prompt — Stage 5 wiring.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§State Machine `Recording`.

Stage 4 only proved the prompt shows when ``dropped_frames > 100``.
Stage 5 wires both branches:

- ``继续录制`` dismisses the prompt and keeps the cockpit in
  ``CockpitState.RECORDING``.
- ``停止并复盘`` runs the same stop/flush/finalize flow as the toolbar
  Stop button (advances to ``REVIEW_MODAL``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
)
from mf4_analyzer.acquisition_ui.main_window import (
    DROPPED_FRAMES_PROMPT_TEXT,
    CockpitMainWindow,
)
from mf4_analyzer.acquisition_ui.review_modal import ReviewModal
from mf4_analyzer.acquisition_ui.state import (
    CockpitState,
    HealthyPredicateResult,
)


def _walk_to_recording(window: CockpitMainWindow) -> None:
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    window.state_machine.request_start_recording()


def _arm_dropped_prompt(window: CockpitMainWindow) -> None:
    """Force the prompt to show by tripping the dropped-frames counter."""
    window._ring._dropped_frames = thresholds.DROPPED_FRAMES_PROMPT_TOTAL + 1
    window._poll_live()


def _make_controller(tmp_path: Path) -> CaptureController:
    mf4_path = tmp_path / "drop.mf4"
    selected = (
        SelectedMeasurement(name="EngSpd"),
        SelectedMeasurement(name="Throttle"),
    )
    cfg = SessionConfig(output_mf4=mf4_path, selected=selected)
    backend = FakeRecorderBackend(samples_per_second=10.0)
    ctrl = CaptureController(cfg, backend)
    ctrl.start()
    for _ in range(3):
        ctrl.poll_step()
    return ctrl


# ---------------------------------------------------------------------------
# Prompt visibility — Stage 4 regression
# ---------------------------------------------------------------------------


def test_prompt_text_matches_spec(qapp):
    window = CockpitMainWindow()
    try:
        _walk_to_recording(window)
        _arm_dropped_prompt(window)
        prompt = window._dropped_prompt
        assert prompt is not None
        assert prompt.text() == DROPPED_FRAMES_PROMPT_TEXT
        # Two action buttons: 继续录制 and 停止并复盘.
        button_labels = [
            btn.text() for btn in prompt.buttons()
        ]
        assert "继续录制" in button_labels
        assert "停止并复盘" in button_labels
        prompt.done(0)
        qapp.processEvents()
    finally:
        window.close()


def test_prompt_hidden_window_does_not_open_message_box(qapp, monkeypatch):
    """Hidden/offscreen tests can inspect the prompt without painting it."""

    opened: list[object] = []

    def _fake_open(box) -> None:
        opened.append(box)

    monkeypatch.setattr("mf4_analyzer.acquisition_ui.main_window.QMessageBox.open", _fake_open)
    window = CockpitMainWindow()
    try:
        assert window.isVisible() is False
        _walk_to_recording(window)
        _arm_dropped_prompt(window)

        assert window._dropped_prompt is not None
        assert opened == []
    finally:
        window.close()


# ---------------------------------------------------------------------------
# Branch 1: 继续录制 — dismiss, stay in Recording
# ---------------------------------------------------------------------------


def test_continue_button_dismisses_and_keeps_recording(qapp):
    window = CockpitMainWindow()
    try:
        _walk_to_recording(window)
        _arm_dropped_prompt(window)
        prompt = window._dropped_prompt
        assert prompt is not None
        # Click 继续录制. Qt routes through buttonClicked → our slot which
        # does nothing for the continue branch. Then we call done(0) to
        # close the prompt (in production the QMessageBox auto-closes on
        # click; in tests we drive it manually).
        cont_btn = window._dropped_prompt_continue_btn
        prompt.buttonClicked.emit(cont_btn)
        prompt.done(0)
        qapp.processEvents()
        # State unchanged.
        assert window.state_machine.state == CockpitState.RECORDING
        # No review modal opened.
        assert window.review_modal is None
    finally:
        window.close()


# ---------------------------------------------------------------------------
# Branch 2: 停止并复盘 — same flow as toolbar Stop
# ---------------------------------------------------------------------------


def test_stop_button_runs_stop_flush_finalize_flow(qapp, tmp_path):
    """Clicking 停止并复盘 runs the same stop/flush/finalize flow as the
    toolbar Stop button — controller.stop() is called, the seven-step
    order is recorded, and the real ReviewModal opens."""
    window = CockpitMainWindow()
    try:
        ctrl = _make_controller(tmp_path)
        window.set_capture_controller(ctrl)
        _walk_to_recording(window)
        _arm_dropped_prompt(window)
        prompt = window._dropped_prompt
        assert prompt is not None
        stop_btn = window._dropped_prompt_stop_btn
        # Click 停止并复盘 — this invokes our slot which calls
        # request_stop_and_review.
        prompt.buttonClicked.emit(stop_btn)
        qapp.processEvents()
        # State advanced to ReviewModal via the stop/flush/finalize flow.
        assert window.state_machine.state == CockpitState.REVIEW_MODAL
        # Real ReviewModal (not the placeholder).
        assert isinstance(window.review_modal, ReviewModal)
        # Stop order trace captured.
        assert window.last_stop_result is not None
        assert window.last_stop_result.order[0] == "stop_backend"
        assert "post_record_diagnostics" in window.last_stop_result.order
        # Cleanup.
        window.review_modal.done(0)
        qapp.processEvents()
    finally:
        window.close()


def test_stop_button_without_controller_uses_placeholder(qapp):
    """Stage 4 demo path: no controller attached — placeholder modal."""
    from mf4_analyzer.acquisition_ui.main_window import _PlaceholderReviewModal

    window = CockpitMainWindow()
    try:
        _walk_to_recording(window)
        _arm_dropped_prompt(window)
        prompt = window._dropped_prompt
        assert prompt is not None
        stop_btn = window._dropped_prompt_stop_btn
        prompt.buttonClicked.emit(stop_btn)
        qapp.processEvents()
        # Still advances to ReviewModal, but the placeholder modal is open.
        assert window.state_machine.state == CockpitState.REVIEW_MODAL
        assert isinstance(window.review_modal, _PlaceholderReviewModal)
        window.review_modal.done(0)
        qapp.processEvents()
    finally:
        window.close()
