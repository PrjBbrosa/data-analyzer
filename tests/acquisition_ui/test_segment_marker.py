"""Segment marker UI tests (Cockpit polish Stage 5)."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import QInputDialog

from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement, SessionConfig
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.state import HealthyPredicateResult


class _NoopWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.write_count = 0
        self.is_closed = False

    def append_batch(self, samples):
        self.write_count += len(list(samples))

    def finalize(self) -> Path:
        self.path.write_text("fake mf4", encoding="utf-8")
        self.is_closed = True
        return self.path


def _controller(tmp_path: Path, now) -> CaptureController:
    selected = (SelectedMeasurement(name="EngSpd"),)
    cfg = SessionConfig(output_mf4=tmp_path / "seg.mf4", selected=selected)
    ctrl = CaptureController(
        cfg,
        FakeRecorderBackend(samples_per_second=1.0),
        writer=_NoopWriter(cfg.output_mf4),
        clock=lambda: now[0],
    )
    ctrl.start()
    return ctrl


def _connect_and_record(window: CockpitMainWindow) -> None:
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    window.state_machine.request_start_recording()


def test_segment_button_only_visible_in_recording_state(qapp):
    window = CockpitMainWindow()
    try:
        assert window.segment_action.isVisible() is False
        window.state_machine.request_connect(
            HealthyPredicateResult.from_components(
                hw_ok=True, xcp_connected=True, first_frame_received=True
            )
        )
        assert window.segment_action.isVisible() is False
        window.state_machine.request_start_recording()
        assert window.segment_action.isVisible() is True
    finally:
        window.close()


def test_segment_label_dialog_records_label_in_summary(qapp, tmp_path, monkeypatch):
    now = [100.0]
    ctrl = _controller(tmp_path, now)
    window = CockpitMainWindow()
    try:
        window.set_capture_controller(ctrl)
        _connect_and_record(window)
        now[0] = 103.0
        monkeypatch.setattr(
            QInputDialog,
            "getText",
            lambda *args, **kwargs: ("launch", True),
        )

        window.segment_action.trigger()
        now[0] = 108.0
        summary = ctrl.stop()

        assert summary.segments == [
            {"start_ts": 0.0, "end_ts": 3.0},
            {"start_ts": 3.0, "end_ts": 8.0, "label": "launch"},
        ]
    finally:
        window.close()
