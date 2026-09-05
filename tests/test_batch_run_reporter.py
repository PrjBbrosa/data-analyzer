"""Behaviour of ``batch._RunReporter`` -- the single funnel for progress
emission and manifest recording inside ``BatchRunner.run``.

Progress events and manifest entries used to be emitted twice, once down the
grouped path and once down the non-grouped one.  These tests pin the funnel
itself so the two paths cannot drift apart again.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer import batch as batch_module
from mf4_analyzer.batch import (
    AnalysisPreset,
    BatchItemResult,
    BatchOutput,
    BatchProgressEvent,
    BatchRunner,
)
from mf4_analyzer.io import FileData


def _make_fd(tmp_path, name="rep", channels=("sig",), idx=0, fs=1024.0):
    n = 256
    t = np.arange(n, dtype=float) / fs
    cols = {"Time": t}
    for channel in channels:
        cols[channel] = np.sin(2 * np.pi * 50 * t)
    df = pd.DataFrame(cols)
    path = tmp_path / f"{name}.csv"
    df.to_csv(path, index=False)
    return FileData(path, df, list(df.columns), {}, idx=idx)


def _preset(**outputs):
    settings = dict(export_data=True, export_image=False)
    settings.update(outputs)
    return AnalysisPreset.free_config(
        name="reporter",
        method="fft",
        target_signals=("sig",),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(**settings),
    )


def _item(status="failed", **kwargs):
    fields = dict(
        method="fft",
        file_id=0,
        file_name="rep.csv",
        signal="sig",
        status=status,
        task_id="task-1",
        message="",
    )
    fields.update(kwargs)
    return BatchItemResult(**fields)


def _reporter(tmp_path, *, on_event=None, progress_callback=None,
              recorder=None, requested_params=None):
    reporter = batch_module._RunReporter(
        BatchRunner({0: _make_fd(tmp_path)}),
        _preset(),
        on_event=on_event,
        progress_callback=progress_callback,
    )
    reporter.bind_recipe(requested_params or {"nfft": 64})
    reporter.bind_recorder(recorder)
    return reporter


class _StubRecorder:
    """Minimal stand-in for ``BatchManifestRecorder``."""

    def __init__(self, error=None):
        self.entries = []
        self.error = error

    def record(self, entry):
        if self.error is not None:
            raise self.error
        self.entries.append(entry)


# ---------------------------------------------------------------- emit ----

def test_emit_forwards_every_event_in_order(tmp_path):
    seen = []
    reporter = _reporter(tmp_path, on_event=seen.append)
    events = [
        BatchProgressEvent(kind="task_started", task_index=1, total=2),
        BatchProgressEvent(kind="task_done", task_index=1, total=2),
        BatchProgressEvent(kind="run_finished", final_status="done"),
    ]

    for event in events:
        reporter.emit(event)

    assert seen == events
    assert [event.kind for event in seen] == [
        "task_started", "task_done", "run_finished",
    ]


def test_emit_is_a_noop_without_a_listener(tmp_path):
    reporter = _reporter(tmp_path, on_event=None)

    reporter.emit(BatchProgressEvent(kind="run_finished", final_status="done"))


def test_emit_progress_keeps_the_legacy_int_int_shim(tmp_path):
    calls = []
    reporter = _reporter(tmp_path, progress_callback=lambda i, t: calls.append((i, t)))

    reporter.emit_progress(_item(status="done"), 3, 7)

    assert calls == [(3, 7)]


@pytest.mark.parametrize(
    "status", ("failed", "cancelled", "skipped", "resumed"),
)
def test_emit_progress_only_counts_done_items(tmp_path, status):
    calls = []
    reporter = _reporter(tmp_path, progress_callback=lambda i, t: calls.append((i, t)))

    reporter.emit_progress(_item(status=status), 1, 4)

    assert calls == []


def test_emit_progress_without_a_callback_is_a_noop(tmp_path):
    reporter = _reporter(tmp_path, progress_callback=None)

    reporter.emit_progress(_item(status="done"), 1, 1)


def test_emit_cancelled_range_emits_one_event_per_remaining_task(tmp_path):
    seen = []
    recorder = _StubRecorder()
    reporter = _reporter(tmp_path, on_event=seen.append, recorder=recorder)
    tasks = [(0, "sig"), (0, "aux"), (1, "sig")]
    items = []
    reporter.bind_plan(
        tasks=tasks,
        total=len(tasks),
        items=items,
        cancelled_item=lambda key, signal, message: _item(
            status="cancelled",
            signal=signal,
            message=message,
            task_id=f"task-{key}-{signal}",
        ),
    )

    reporter.emit_cancelled_range(2)

    assert [(event.kind, event.task_index, event.signal) for event in seen] == [
        ("task_cancelled", 2, "aux"),
        ("task_cancelled", 3, "sig"),
    ]
    assert [event.total for event in seen] == [3, 3]
    assert [event.message for event in seen] == ["batch cancelled"] * 2
    assert [item.status for item in items] == ["cancelled", "cancelled"]
    assert [entry["task_id"] for entry in recorder.entries] == [
        "task-0-aux", "task-1-sig",
    ]


def test_emit_cancelled_range_honours_a_custom_message(tmp_path):
    seen = []
    reporter = _reporter(tmp_path, on_event=seen.append)
    tasks = [(0, "sig")]
    reporter.bind_plan(
        tasks=tasks,
        total=1,
        items=[],
        cancelled_item=lambda key, signal, message: _item(
            status="cancelled", signal=signal, message=message,
        ),
    )

    reporter.emit_cancelled_range(1, message="cancelled during resume checksum")

    assert [event.message for event in seen] == [
        "cancelled during resume checksum",
    ]


# -------------------------------------------------------------- record ----

def test_record_forwards_a_manifest_entry(tmp_path):
    recorder = _StubRecorder()
    reporter = _reporter(
        tmp_path, recorder=recorder, requested_params={"nfft": 64},
    )

    reporter.record(_item(status="failed", message="boom"), 0)

    assert len(recorder.entries) == 1
    entry = recorder.entries[0]
    assert entry["task_id"] == "task-1"
    assert entry["source_id"] == 0
    assert entry["channel"] == "sig"
    assert entry["status"] == "failed"
    assert entry["message"] == "boom"
    assert entry["requested_params"] == {"nfft": 64}


def test_record_adds_frf_pair_channels_and_units(tmp_path):
    fd = _make_fd(tmp_path, channels=("command", "response"))
    fd.channel_units.update({"command": "V", "response": "N"})
    runner = BatchRunner({0: fd})
    recorder = _StubRecorder()
    reporter = batch_module._RunReporter(runner, _preset())
    reporter.bind_recipe({"estimator": "h1"})
    reporter.bind_recorder(recorder)
    item = BatchItemResult(
        method="frf",
        file_id=0,
        file_name=fd.filename,
        signal="response / command",
        input_signal="command",
        output_signal="response",
        status="failed",
        task_id="frf-task",
    )

    reporter.record(item, 0, fd)

    assert recorder.entries[0]["channel"] == "response / command"
    assert recorder.entries[0]["channel_unit"] == "N"
    assert recorder.entries[0]["frf_pair"] == {
        "input": {"channel": "command", "unit": "V"},
        "output": {"channel": "response", "unit": "N"},
    }


def test_record_without_a_recorder_is_a_noop(tmp_path):
    reporter = _reporter(tmp_path, recorder=None)

    reporter.record(_item(), 0)

    assert reporter.manifest_errors == []


def test_record_failure_is_counted_and_logged(tmp_path, caplog):
    recorder = _StubRecorder(error=RuntimeError("manifest disk full"))
    reporter = _reporter(tmp_path, recorder=recorder)

    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.batch"):
        reporter.record(_item(), 0)

    assert reporter.manifest_errors == [
        "cannot update batch manifest: manifest disk full",
    ]
    warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    assert warnings, "a failed manifest record must not stay silent"
    assert any("manifest" in record.getMessage() for record in warnings)
    assert any(record.exc_info for record in warnings), (
        "the traceback must be attached via exc_info"
    )


def test_record_failure_reaches_the_run_result(tmp_path, monkeypatch, caplog):
    """The reporter's error list is the one ``BatchRunResult`` carries."""
    fd = _make_fd(tmp_path, "endtoend")

    def boom(self, entry):
        raise RuntimeError("manifest disk full")

    monkeypatch.setattr(
        batch_module.BatchManifestRecorder, "record", boom, raising=True,
    )

    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.batch"):
        result = BatchRunner({0: fd}).run(_preset(), tmp_path / "out")

    assert result.status == "partial"
    assert any(
        "cannot update batch manifest" in reason for reason in result.blocked
    )
    assert any(record.exc_info for record in caplog.records)


# --------------------------------------------------------------- wiring ----

def test_run_routes_every_event_through_the_reporter(tmp_path, monkeypatch):
    """No emission site may bypass the funnel."""
    fd = _make_fd(tmp_path, "funnel", channels=("sig", "aux"))
    funnelled = []
    original = batch_module._RunReporter.emit

    def spy(self, event):
        funnelled.append(event)
        return original(self, event)

    monkeypatch.setattr(batch_module._RunReporter, "emit", spy)

    seen = []
    preset = AnalysisPreset.free_config(
        name="funnel",
        method="fft",
        target_signals=("sig", "aux"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({0: fd}).run(
        preset, tmp_path / "out", on_event=seen.append,
    )

    assert result.status == "done"
    assert [event.kind for event in seen] == [
        "task_started", "task_done",
        "task_started", "task_done",
        "run_finished",
    ]
    assert seen == funnelled


def test_run_routes_the_legacy_progress_callback_through_the_reporter(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "legacy", channels=("sig", "aux"))
    funnelled = []
    original = batch_module._RunReporter.emit_progress

    def spy(self, item, task_index, total):
        funnelled.append((item.status, task_index, total))
        return original(self, item, task_index, total)

    monkeypatch.setattr(batch_module._RunReporter, "emit_progress", spy)

    progress = []
    preset = AnalysisPreset.free_config(
        name="legacy progress",
        method="fft",
        target_signals=("sig", "aux"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    BatchRunner({0: fd}).run(
        preset,
        tmp_path / "out",
        lambda index, total: progress.append((index, total)),
    )

    assert progress == [(1, 2), (2, 2)]
    assert funnelled == [("done", 1, 2), ("done", 2, 2)]


def test_blocked_auto_nfft_is_recorded_only_through_the_reporter(
    tmp_path, monkeypatch,
):
    n = 32
    fs = 1000.0
    t = np.arange(n, dtype=float) / fs
    df = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 40.0 * t)})
    path = tmp_path / "blocked.csv"
    df.to_csv(path, index=False)
    fd = FileData(path, df, list(df.columns), {}, idx=0, fs=fs)

    emitted = []
    recorded = []
    original_emit = batch_module._RunReporter.emit
    original_record = batch_module._RunReporter.record

    def spy_emit(self, event):
        emitted.append(event)
        return original_emit(self, event)

    def spy_record(self, item, source_key, fd=None):
        recorded.append(item)
        return original_record(self, item, source_key, fd)

    monkeypatch.setattr(batch_module._RunReporter, "emit", spy_emit)
    monkeypatch.setattr(batch_module._RunReporter, "record", spy_record)

    seen = []
    preset = AnalysisPreset.from_current_single(
        name="blocked auto",
        method="fft",
        signal=(0, "sig"),
        params={
            "fs": fs,
            "nfft": None,
            "nfft_mode": "auto",
            "avg_mode": "线性平均",
            "avg_overlap": 50,
            "t_win_s": 1.5,
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({0: fd}).run(
        preset, tmp_path / "out", on_event=seen.append,
    )

    assert result.items[0].status == "failed"
    assert "insufficient_samples" in result.items[0].message
    assert [item.status for item in recorded] == ["failed"]
    assert any(event.kind == "task_failed" for event in emitted)
    assert seen == emitted
    assert not any(
        event.kind == "task_failed" and event not in emitted
        for event in seen
    )


def test_reporter_stays_private_to_the_batch_module():
    assert "_RunReporter" not in getattr(batch_module, "__all__", ())

    package = Path(batch_module.__file__).parent
    leaks = sorted(
        str(path.relative_to(package))
        for path in package.rglob("*.py")
        if path.name != "batch.py" and "_RunReporter" in path.read_text(
            encoding="utf-8",
        )
    )
    assert leaks == []
