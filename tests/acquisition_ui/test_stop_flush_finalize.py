"""Stop / flush / finalize sequencing — Stage 5.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§State Machine Contract `Recording → ReviewModal`.

Plan: Stage 5 stop/flush/finalize sequence — assert ordering of every
step:

1. stop backend
2. drain writer
3. close file handles
4. write session summary
5. compute SHA if archiving
6. run post-record diagnostics
7. open review modal

The unit under test is :func:`run_stop_flush_finalize` plus the cockpit's
``request_stop_and_review`` driver — we spy on a controller / writer /
summary stub so the test stays Qt-friendly and offscreen-safe.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
    SessionSummary,
)
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.review_modal import (
    ReviewModal,
    run_stop_flush_finalize,
)
from mf4_analyzer.acquisition_ui.state import (
    CockpitState,
    CockpitStateMachine,
    HealthyPredicateResult,
)


# ---------------------------------------------------------------------------
# Pure-Python ordering of run_stop_flush_finalize
# ---------------------------------------------------------------------------


def _run_one_second_fake(tmp_path: Path) -> CaptureController:
    """Start + drive a 1-second fake recording, return the controller
    pre-stop so the test can call ``run_stop_flush_finalize`` itself."""
    mf4_path = tmp_path / "spy.mf4"
    selected = (
        SelectedMeasurement(name="EngSpd"),
        SelectedMeasurement(name="Throttle"),
        SelectedMeasurement(name="Steering"),
    )
    cfg = SessionConfig(output_mf4=mf4_path, selected=selected)
    backend = FakeRecorderBackend(samples_per_second=10.0)
    ctrl = CaptureController(cfg, backend)
    ctrl.start()
    # Drive a small number of poll steps to put a few samples through.
    for _ in range(5):
        ctrl.poll_step()
    return ctrl


def test_run_stop_flush_finalize_ordering(tmp_path):
    """The seven-step ordering must match spec §State Machine Contract."""
    ctrl = _run_one_second_fake(tmp_path)
    result = run_stop_flush_finalize(
        controller=ctrl,
        expected_channels=("EngSpd", "Throttle", "Steering"),
        compute_sha=True,
    )
    # Order matches spec §State Machine Contract `Recording → ReviewModal`.
    assert result.order == [
        "stop_backend",
        "drain_writer",
        "close_handles",
        "write_session_summary",
        "compute_sha256",
        "post_record_diagnostics",
    ]
    # Step 4: session_summary.json sidecar exists.
    assert result.sidecar_path.exists()
    assert result.sidecar_path.name.endswith(".session_summary.json")
    # Step 5: SHA-256 was computed (64 hex chars).
    assert result.sha256 is not None
    assert len(result.sha256) == 64
    # Step 6: preflight sidecar exists and is non-empty JSON.
    assert result.preflight_sidecar_path.exists()
    pf_text = result.preflight_sidecar_path.read_text(encoding="utf-8")
    assert pf_text.strip().startswith("{")
    # Preflight saw all three channels.
    assert result.preflight.missing_channels == ()


def test_run_stop_flush_finalize_skips_sha_when_not_archiving(tmp_path):
    """``compute_sha=False`` removes the compute_sha256 step from order."""
    ctrl = _run_one_second_fake(tmp_path)
    result = run_stop_flush_finalize(
        controller=ctrl,
        expected_channels=("EngSpd",),
        compute_sha=False,
    )
    assert "compute_sha256" not in result.order
    assert result.sha256 is None
    # Other steps still ran in order.
    assert result.order == [
        "stop_backend",
        "drain_writer",
        "close_handles",
        "write_session_summary",
        "post_record_diagnostics",
    ]


def test_run_stop_flush_finalize_writes_preflight_sidecar_next_to_mf4(tmp_path):
    """Preflight sidecar lives next to the MF4 with .preflight.json suffix."""
    ctrl = _run_one_second_fake(tmp_path)
    result = run_stop_flush_finalize(
        controller=ctrl,
        expected_channels=("EngSpd",),
    )
    expected = ctrl.config.output_mf4.with_suffix(".preflight.json")
    assert result.preflight_sidecar_path == expected
    assert expected.exists()


# ---------------------------------------------------------------------------
# Cockpit-level integration — request_stop_and_review hooks into the
# state machine and opens the real ReviewModal.
# ---------------------------------------------------------------------------


def _walk_to_recording(window: CockpitMainWindow) -> None:
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    window.state_machine.request_start_recording()
    assert window.state_machine.state == CockpitState.RECORDING


def test_cockpit_request_stop_and_review_runs_sequence_and_opens_modal(
    qapp, tmp_path
):
    """End-to-end Stage 5 path: cockpit stops via the new entry point,
    runs stop/flush/finalize, opens the real :class:`ReviewModal`."""
    window = CockpitMainWindow()
    try:
        ctrl = _run_one_second_fake(tmp_path)
        window.set_capture_controller(ctrl)
        _walk_to_recording(window)
        window.request_stop_and_review()
        assert window.state_machine.state == CockpitState.REVIEW_MODAL
        # The real ReviewModal is open (not the placeholder).
        assert isinstance(window.review_modal, ReviewModal)
        # Order trace captured on the cockpit.
        assert window.last_stop_result is not None
        order = window.last_stop_result.order
        assert order[:4] == [
            "stop_backend",
            "drain_writer",
            "close_handles",
            "write_session_summary",
        ]
        assert "post_record_diagnostics" in order
        # Clean shutdown.
        window.review_modal.done(0)
        qapp.processEvents()
    finally:
        window.close()


def test_cockpit_request_stop_and_review_falls_back_when_no_controller(
    qapp,
):
    """Stage 4 demo path (no controller) — placeholder modal opens."""
    from mf4_analyzer.acquisition_ui.main_window import _PlaceholderReviewModal

    window = CockpitMainWindow()
    try:
        _walk_to_recording(window)
        window.request_stop_and_review()
        assert window.state_machine.state == CockpitState.REVIEW_MODAL
        # Placeholder modal (not the real ReviewModal).
        assert isinstance(window.review_modal, _PlaceholderReviewModal)
        # No stop_result because no controller stop ran.
        assert window.last_stop_result is None
        window.review_modal.done(0)
        qapp.processEvents()
    finally:
        window.close()


def test_cockpit_review_close_returns_to_idle(qapp, tmp_path):
    """Closing the modal returns to ConnectedIdle (spec §ReviewModal)."""
    window = CockpitMainWindow()
    try:
        ctrl = _run_one_second_fake(tmp_path)
        window.set_capture_controller(ctrl)
        _walk_to_recording(window)
        window.request_stop_and_review()
        modal = window.review_modal
        assert modal is not None
        modal.done(0)
        qapp.processEvents()
        assert window.state_machine.state == CockpitState.CONNECTED_IDLE
    finally:
        window.close()


def test_request_stop_and_review_is_noop_outside_recording(qapp):
    """``request_stop_and_review`` from a non-Recording state is a noop."""
    window = CockpitMainWindow()
    try:
        assert window.state_machine.state == CockpitState.DISCONNECTED
        window.request_stop_and_review()
        assert window.state_machine.state == CockpitState.DISCONNECTED
    finally:
        window.close()
