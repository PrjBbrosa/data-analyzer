"""Tests for ``CaptureController`` start/poll/stop/flush + summary."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture.backends import (
    FakeRecorderBackend,
    ReplayRecorderBackend,
)
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
)


THREE = (
    SelectedMeasurement(name="A", unit="rpm"),
    SelectedMeasurement(name="B", unit="Nm"),
    SelectedMeasurement(name="C", unit="km/h"),
)


class _NoopWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.write_count = 0
        self.is_closed = False

    def append_batch(self, samples) -> None:
        self.write_count += len(list(samples))

    def finalize(self) -> Path:
        self.path.write_text("fake mf4", encoding="utf-8")
        self.is_closed = True
        return self.path


def _config(tmp_path: Path, duration_s: float | None = 1.0) -> SessionConfig:
    return SessionConfig(
        output_mf4=tmp_path / "out.mf4",
        selected=THREE,
        duration_s=duration_s,
    )


def test_controller_start_stop_writes_finalized_mf4(tmp_path):
    config = _config(tmp_path, duration_s=0.3)
    backend = FakeRecorderBackend(samples_per_second=200.0)
    controller = CaptureController(config, backend)
    controller.start()
    assert controller.running
    deadline = time.monotonic() + 0.5
    while controller.running and time.monotonic() < deadline:
        controller.poll_step()
        time.sleep(0.01)
    summary = controller.stop()
    assert summary.output_mf4 == str(config.output_mf4)
    assert config.output_mf4.exists()
    assert summary.duration_s > 0
    assert summary.rx_count > 0
    assert summary.write_count > 0


def test_controller_summary_includes_counters(tmp_path):
    config = _config(tmp_path, duration_s=0.2)
    backend = FakeRecorderBackend(samples_per_second=100.0)
    ctrl = CaptureController(config, backend)
    ctrl.start()
    deadline = time.monotonic() + 0.4
    while ctrl.running and time.monotonic() < deadline:
        ctrl.poll_step()
        time.sleep(0.02)
    summary = ctrl.stop()
    # All these spec-pinned keys must be populated.
    for key in [
        "duration_s",
        "rx_count",
        "write_count",
        "queue_overflow_count",
        "bus_error_count",
        "dropped_frames",
        "max_queue_depth",
        "segments",
        "output_mf4",
    ]:
        assert hasattr(summary, key)


def test_controller_double_start_raises(tmp_path):
    config = _config(tmp_path)
    ctrl = CaptureController(config, FakeRecorderBackend())
    ctrl.start()
    with pytest.raises(RuntimeError, match="already running"):
        ctrl.start()
    ctrl.stop()


def test_controller_stop_idempotent_after_first_call(tmp_path):
    config = _config(tmp_path, duration_s=0.1)
    ctrl = CaptureController(config, FakeRecorderBackend())
    ctrl.start()
    time.sleep(0.15)
    ctrl.poll_step()  # triggers duration-cap stop
    summary1 = ctrl.stop()
    summary2 = ctrl.stop()
    # Same output_mf4; counters frozen after first stop.
    assert summary1.output_mf4 == summary2.output_mf4
    assert summary2.rx_count == summary1.rx_count


def test_controller_uses_replay_backend(tmp_path):
    """Capture loop works against the replay backend with no Vector deps."""
    config = SessionConfig(
        output_mf4=tmp_path / "replay.mf4",
        selected=THREE,
        duration_s=0.3,
        backend="replay",
    )
    backend = ReplayRecorderBackend(synth_duration_s=0.3, synth_rate_hz=50.0)
    ctrl = CaptureController(config, backend)
    ctrl.start()
    deadline = time.monotonic() + 0.5
    while ctrl.running and time.monotonic() < deadline:
        ctrl.poll_step()
        time.sleep(0.01)
    summary = ctrl.stop()
    assert (tmp_path / "replay.mf4").exists()
    assert summary.write_count > 0


def test_controller_drains_ring_to_writer(tmp_path):
    """Samples land in the writer, not stuck in the ring buffer."""
    config = _config(tmp_path, duration_s=0.2)
    backend = FakeRecorderBackend(samples_per_second=100.0)
    ctrl = CaptureController(config, backend)
    ctrl.start()
    deadline = time.monotonic() + 0.3
    while ctrl.running and time.monotonic() < deadline:
        ctrl.poll_step()
        time.sleep(0.01)
    summary = ctrl.stop()
    # After stop the ring is empty (controller drained on stop).
    assert ctrl.ring.level_pct == 0.0
    # All received samples got into the writer.
    assert summary.write_count == summary.rx_count


def test_sample_tap_receives_raw_backend_batches(tmp_path):
    seen = []
    config = SessionConfig(
        output_mf4=tmp_path / "tap.mf4",
        selected=(SelectedMeasurement(name="EngSpd"),),
    )
    ctrl = CaptureController(config, FakeRecorderBackend(), sample_tap=seen.append)
    ctrl.start()
    deadline = time.monotonic() + 2.0
    while not seen and time.monotonic() < deadline:
        ctrl.poll_step()
        time.sleep(0.02)
    ctrl.stop()
    assert seen, "tap never fired"
    channel, ts, value = seen[0][0]
    assert channel == "EngSpd"
    assert isinstance(ts, float)
    assert isinstance(value, float)


def test_sample_tap_exception_does_not_kill_capture(tmp_path):
    def _boom(_batch):
        raise RuntimeError("live view died")

    config = SessionConfig(
        output_mf4=tmp_path / "tap_exception.mf4",
        selected=(SelectedMeasurement(name="EngSpd"),),
    )
    ctrl = CaptureController(config, FakeRecorderBackend(), sample_tap=_boom)
    ctrl.start()
    deadline = time.monotonic() + 2.0
    while ctrl.writer.write_count == 0 and time.monotonic() < deadline:
        ctrl.poll_step()
        time.sleep(0.02)
    summary = ctrl.stop()
    assert summary.write_count > 0, "capture must survive a raising tap"


def test_controller_records_segment_when_configured(tmp_path):
    config = SessionConfig(
        output_mf4=tmp_path / "seg.mf4",
        selected=THREE,
        duration_s=0.4,
        segment_seconds=0.1,
    )
    ctrl = CaptureController(config, FakeRecorderBackend(samples_per_second=100.0))
    ctrl.start()
    deadline = time.monotonic() + 0.5
    while ctrl.running and time.monotonic() < deadline:
        ctrl.poll_step()
        time.sleep(0.01)
    summary = ctrl.stop()
    # Expect at least one segment recorded.
    assert summary.segments, f"no segments recorded: {summary.to_dict()}"


def test_mark_segment_appends_to_summary(tmp_path):
    now = [100.0]
    config = _config(tmp_path, duration_s=None)
    ctrl = CaptureController(
        config,
        FakeRecorderBackend(samples_per_second=1.0),
        writer=_NoopWriter(config.output_mf4),
        clock=lambda: now[0],
    )
    ctrl.start()

    now[0] = 102.5
    ctrl.mark_segment("launch")
    now[0] = 107.0
    summary = ctrl.stop()

    assert summary.segments == [
        {"start_ts": 0.0, "end_ts": 2.5},
        {"start_ts": 2.5, "end_ts": 7.0, "label": "launch"},
    ]
    assert set(summary.to_dict()) == {
        "version",
        "duration_s",
        "rx_count",
        "write_count",
        "queue_overflow_count",
        "bus_error_count",
        "dropped_frames",
        "max_queue_depth",
        "segments",
        "output_mf4",
        "auto_stop",
        "warnings",
    }
