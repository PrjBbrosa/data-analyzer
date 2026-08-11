"""Load-progress sampling and heavy-load confirmation."""
from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.io.blf_format import (
    _estimate_byte_progress,
    _sample_reader_byte_progress,
)


def test_estimate_byte_progress_is_monotonic_and_leaves_headroom():
    total = 10_000
    positions = [
        _estimate_byte_progress(i, total, bytes_per_frame_hint=100)
        for i in (0, 1, 50, 99, 100, 500)
    ]
    assert positions[0] == 0
    assert positions[1] > 0
    assert positions == sorted(positions)
    assert positions[-1] < total


def test_sample_reader_falls_back_when_tell_disabled():
    class _BrokenTell:
        def tell(self):
            raise OSError("telling position disabled by next() call")

    class _Reader:
        file = _BrokenTell()

    seen = []
    last = 0
    for frame_index in (1, 512, 1024):
        last = _sample_reader_byte_progress(
            _Reader(),
            frame_index,
            10_000,
            last,
            lambda current, total: seen.append((current, total)),
            bytes_per_frame_hint=100,
        )
    assert len(seen) >= 2
    assert seen[0][0] < seen[-1][0] < seen[-1][1]


def test_asc_read_progress_advances_before_completion(tmp_path):
    pytest.importorskip("can", reason="python-can not installed (win32-gated)")
    from mf4_analyzer.io.asc_can_format import _read_asc_frames

    path = tmp_path / "busy.asc"
    lines = [
        "date Mon Jan 01 12:00:00 PM 2024",
        "base hex timestamps absolute",
        "no internal events logged",
        "Begin Triggerblock Mon Jan 01 12:00:00 PM 2024",
    ]
    for i in range(2500):
        lines.append(
            f"   {1.0 + i * 0.01:.6f} 1  123             Rx   d 8  "
            "00 00 00 00 00 00 00 00"
        )
    lines.append("End TriggerBlock")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")

    progress = []
    frames = _read_asc_frames(
        path,
        progress_callback=lambda current, total: progress.append((current, total)),
    )
    assert len(frames) == 2500
    assert progress[0][0] == 0
    assert progress[-1][0] == progress[-1][1]
    mid = [current for current, total in progress[1:-1] if 0 < current < total]
    assert mid, "expected mid-read progress while ASC tell() is disabled"


def test_should_confirm_heavy_load_thresholds():
    from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin

    host = ProjectIOMixin.__new__(ProjectIOMixin)
    assert host._should_confirm_heavy_load([100]) is False
    assert host._should_confirm_heavy_load([150 * 1024 * 1024]) is True
    assert host._should_confirm_heavy_load([300 * 1024 * 1024]) is True
    assert host._should_confirm_heavy_load([20 * 1024 * 1024] * 5) is True
    assert host._should_confirm_heavy_load([10 * 1024 * 1024] * 4) is False


def test_format_byte_size_and_estimate_helpers():
    from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin

    host = ProjectIOMixin.__new__(ProjectIOMixin)
    assert "MB" in host._format_byte_size(400 * 1024 * 1024)
    assert "GB" in host._format_byte_size(4 * 1024 ** 3)
    # 10 × 400 MB at 25 MB/s ≈ 160 s → about 3 minutes
    assert host._estimate_heavy_load_seconds(10 * 400 * 1024 * 1024) >= 150


def test_open_data_paths_cancels_when_heavy_load_declined(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    huge = tmp_path / "huge.csv"
    huge.write_bytes(b"0" * (160 * 1024 * 1024))

    mw = MainWindow()
    monkeypatch.setattr(mw, "_confirm_heavy_load", lambda *_a, **_k: False)
    called = []
    monkeypatch.setattr(
        mw,
        "_load_one",
        lambda *a, **k: called.append(True),
    )
    mw._open_data_paths([str(huge)])
    assert called == []
    assert len(mw.files) == 0


def test_open_data_paths_marks_indeterminate_for_csv(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    path = tmp_path / "small.csv"
    path.write_text("Time,sig\n0,1\n0.1,2\n", encoding="utf-8")

    mw = MainWindow()
    updates = []

    def capture(current, total, label=None, token=None, **kwargs):
        updates.append((current, total, label, kwargs.get("flush_events")))

    monkeypatch.setattr(mw, "_update_compute_progress", capture)
    monkeypatch.setattr(mw, "_should_confirm_heavy_load", lambda *_a, **_k: False)
    mw._open_data_paths([str(path)])

    busy = [u for u in updates if u[1] == 0 and u[2] and "读取表格" in u[2]]
    assert busy, updates
    assert any(u[3] is True for u in updates)
