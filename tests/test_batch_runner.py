from __future__ import annotations

import builtins
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
from mf4_analyzer.batch_recipe import normalize_batch_params
from mf4_analyzer.io import FileData


def _make_file(tmp_path, fs=1024.0):
    n = 2048
    t = np.arange(n, dtype=float) / fs
    rpm = np.full(n, 3072.0)
    sig = np.sin(2 * np.pi * 102.4 * t)
    df = pd.DataFrame({"Time": t, "sig": sig, "rpm": rpm})
    path = tmp_path / "sample.csv"
    df.to_csv(path, index=False)
    return FileData(path, df, list(df.columns), {}, idx=0)


def test_batch_supported_methods_include_time():
    assert "time" in BatchRunner.SUPPORTED_METHODS


def test_batch_time_dataframe_exports_original_series(tmp_path):
    t = np.arange(5, dtype=float) / 10.0
    df = pd.DataFrame({
        "Time": t,
        "sig": np.array([0.0, 1.0, 0.0, -1.0, 0.0]),
    })
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0, fs=10.0)
    preset = AnalysisPreset.from_current_single(
        name="time",
        method="time",
        signal=(0, "sig"),
        params={},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    out = pd.read_csv(result.items[0].data_path)
    assert list(out.columns) == ["time_s", "series", "value"]
    assert out["series"].tolist() == ["original"] * 5
    np.testing.assert_allclose(out["time_s"].to_numpy(), t)
    np.testing.assert_allclose(out["value"].to_numpy(), df["sig"].to_numpy())


def test_batch_time_dataframe_exports_original_and_filtered_series(tmp_path):
    fs = 200.0
    t = np.arange(400, dtype=float) / fs
    low = np.sin(2 * np.pi * 5 * t)
    sig = low + 0.5 * np.sin(2 * np.pi * 60 * t)
    df = pd.DataFrame({"Time": t, "sig": sig})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0, fs=fs)
    preset = AnalysisPreset.from_current_single(
        name="time filtered",
        method="time",
        signal=(0, "sig"),
        params={
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 20.0},
                "show_original": True,
                "show_filtered": True,
            }
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    out = pd.read_csv(result.items[0].data_path)
    assert set(out["series"]) == {"original", "filtered"}
    original = out[out["series"] == "original"]["value"].to_numpy()
    filtered = out[out["series"] == "filtered"]["value"].to_numpy()
    assert len(original) == len(filtered) == len(sig)
    assert np.std(filtered - low) < np.std(original - low)


def test_batch_time_blocks_when_filter_hides_both_series(tmp_path):
    t = np.arange(8, dtype=float) / 10.0
    df = pd.DataFrame({"Time": t, "sig": np.ones_like(t)})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0, fs=10.0)
    preset = AnalysisPreset.from_current_single(
        name="hidden",
        method="time",
        signal=(0, "sig"),
        params={
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 3.0},
                "show_original": False,
                "show_filtered": False,
            }
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert "至少需要原始或滤波后一项" in result.blocked[0]


def test_batch_fft_uses_filtered_signal_when_filter_enabled(monkeypatch):
    captured = {}

    def fake_compute_fft(sig, fs, win="hanning", nfft=None, weighting="None"):
        captured["std"] = float(np.std(sig))
        return np.array([0.0]), np.array([1.0])

    monkeypatch.setattr(
        "mf4_analyzer.batch.FFTAnalyzer.compute_fft",
        fake_compute_fft,
    )
    fs = 200.0
    t = np.arange(400, dtype=float) / fs
    low = np.sin(2 * np.pi * 5 * t)
    sig = low + 0.5 * np.sin(2 * np.pi * 60 * t)

    BatchRunner._compute_fft_dataframe(
        sig,
        fs,
        {
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 20.0},
            }
        },
    )

    assert captured["std"] < float(np.std(sig))


def test_batch_fft_time_uses_filtered_signal_when_filter_enabled(monkeypatch):
    captured = {}

    def fake_compute(signal, time, params, channel_name="signal"):
        captured["std"] = float(np.std(signal))
        return type("SpectroResult", (), {
            "times": np.array([0.0]),
            "frequencies": np.array([1.0]),
            "amplitude": np.array([[1.0]]),
        })()

    monkeypatch.setattr(
        "mf4_analyzer.signal.spectrogram.SpectrogramAnalyzer.compute",
        fake_compute,
    )
    fs = 200.0
    t = np.arange(400, dtype=float) / fs
    low = np.sin(2 * np.pi * 5 * t)
    sig = low + 0.5 * np.sin(2 * np.pi * 60 * t)

    BatchRunner._compute_fft_time_spectro(
        sig,
        t,
        fs,
        {
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 20.0},
            },
            "nfft": 64,
        },
    )

    assert captured["std"] < float(np.std(sig))


def test_batch_order_time_filters_signal_but_not_rpm(monkeypatch):
    captured = {}

    def fake_compute(sig, rpm, time, params):
        captured["sig_std"] = float(np.std(sig))
        captured["rpm"] = np.asarray(rpm, dtype=float).copy()
        return type("OrderResult", (), {
            "times": np.array([0.0]),
            "orders": np.array([1.0]),
            "amplitude": np.array([[1.0]]),
        })()

    monkeypatch.setattr(
        "mf4_analyzer.signal.order_cot.COTOrderAnalyzer.compute",
        fake_compute,
    )
    fs = 200.0
    t = np.arange(400, dtype=float) / fs
    low = np.sin(2 * np.pi * 5 * t)
    sig = low + 0.5 * np.sin(2 * np.pi * 60 * t)
    rpm = 1000.0 + 10.0 * np.sin(2 * np.pi * 30 * t)

    BatchRunner._compute_order_time_spectro(
        sig,
        rpm,
        t,
        fs,
        {
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 20.0},
            },
            "nfft": 64,
        },
    )

    assert captured["sig_std"] < float(np.std(sig))
    np.testing.assert_allclose(captured["rpm"], rpm)


def test_current_single_fft_preset_exports_data(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.from_current_single(
        name="current fft",
        method="fft",
        signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert len(result.items) == 1
    assert result.items[0].data_path is not None
    data = pd.read_csv(result.items[0].data_path)
    assert list(data.columns) == ["frequency_hz", "amplitude"]


def test_current_single_fft_preset_exports_image(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.from_current_single(
        name="current fft image",
        method="fft",
        signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
        outputs=BatchOutput(export_data=False, export_image=True),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.items[0].image_path is not None
    assert result.items[0].image_path.endswith(".png")


def test_current_single_fft_preset_handles_auto_nfft(tmp_path):
    """preset 中 nfft='自动' 应被当作 None 处理（与 inspector 控件一致）。"""
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.from_current_single(
        name="auto nfft",
        method="fft",
        signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": "自动"},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    assert result.items[0].data_path is not None


def test_matrix_to_long_dataframe_vectorize_shape(tmp_path):
    from mf4_analyzer.batch import _matrix_to_long_dataframe
    x = np.arange(5, dtype=float)
    y = np.arange(3, dtype=float) * 0.1
    matrix = np.arange(15, dtype=float).reshape(5, 3)
    df = _matrix_to_long_dataframe(x, y, matrix, x_name='time', y_name='order')
    assert len(df) == 15
    assert list(df.columns) == ['time', 'order', 'amplitude']
    # 前三行：x=0, y∈{0, 0.1, 0.2}
    assert df.iloc[0]['time'] == 0.0
    assert df.iloc[2]['amplitude'] == 2.0
    # 第 4 行：x=1, y=0
    assert df.iloc[3]['time'] == 1.0
    assert df.iloc[3]['amplitude'] == 3.0


def test_analysis_preset_replace_after_frozen_removed(tmp_path):
    """`AnalysisPreset` 去 frozen 后，`dataclasses.replace` 必须继续工作
    （`BatchSheet.get_preset` 依赖此行为）。"""
    from dataclasses import replace
    fd = _make_file(tmp_path)
    p = AnalysisPreset.from_current_single(
        name="orig", method="fft", signal=(1, "sig"),
        params={"fs": 1024.0, "nfft": 1024},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    p2 = replace(p, outputs=BatchOutput(export_data=False, export_image=True))
    assert p2.outputs.export_image is True
    assert p2.outputs.export_data is False
    assert p2.name == "orig"
    assert p.outputs.export_data is True   # 原 preset 不被修改


def test_batch_order_time_csv_shape(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.free_config(
        name="order time batch",
        method="order_time",
        signal_pattern="sig",
        rpm_channel="rpm",
        params={"fs": 1024.0, "nfft": 512, "max_order": 5.0,
                "order_res": 0.5, "time_res": 0.05},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    df = pd.read_csv(result.items[0].data_path)
    assert list(df.columns) == ["time_s", "order", "amplitude"]
    assert len(df) > 0


def test_write_image_exports_nonempty_png_with_fixed_size(tmp_path):
    from PyQt5.QtGui import QImage, QImageReader

    df = pd.DataFrame({"frequency_hz": [0.0, 1.0], "amplitude": [0.0, 1.0]})
    out = BatchRunner._write_image(("fft", df), tmp_path / "fft.png")
    image = QImage(str(out))

    assert out.exists()
    assert out.stat().st_size > 0
    assert not image.isNull()
    assert bytes(QImageReader.imageFormat(str(out))).lower() == b"png"
    assert (image.width(), image.height()) == (1920, 1080)


def test_write_heatmap_image_exports_nonempty_png_with_fixed_size(tmp_path):
    from PyQt5.QtGui import QImage, QImageReader

    df = pd.DataFrame({
        "time_s": [0.0, 1.0, 0.0, 1.0],
        "frequency_hz": [10.0, 10.0, 20.0, 20.0],
        "amplitude": [0.25, 0.5, 1.0, 2.0],
    })
    out = BatchRunner._write_image(("fft_time", df), tmp_path / "heatmap.png")
    image = QImage(str(out))

    assert out.exists()
    assert out.stat().st_size > 0
    assert not image.isNull()
    assert bytes(QImageReader.imageFormat(str(out))).lower() == b"png"
    assert (image.width(), image.height()) == (1920, 1080)


# ---------------------------------------------------------------------------
# Wave 2: BatchProgressEvent + cancellation + loader injection (verbatim from
# plan §Wave 2 Step 1 / spec §3.2, §4.3, §4.4, §4.5, §7, §8).
# ---------------------------------------------------------------------------

import threading
import pandas as pd
import numpy as np
import pytest
from dataclasses import replace

from mf4_analyzer.batch import (
    AnalysisPreset, BatchOutput, BatchRunner,
    BatchProgressEvent, BatchRunResult,
)
from mf4_analyzer.io import FileData


def _make_fd(tmp_path, name="a", channels=("sig", "rpm"), idx=0, fs=1024.0):
    n = 2048
    t = np.arange(n, dtype=float) / fs
    cols = {"Time": t}
    for c in channels:
        cols[c] = np.sin(2 * np.pi * 50 * t) if c == "sig" else np.full(n, 3000.0)
    df = pd.DataFrame(cols)
    p = tmp_path / f"{name}.csv"
    df.to_csv(p, index=False)
    return FileData(p, df, list(df.columns), {}, idx=idx)


def test_event_kinds_emitted_in_order(tmp_path):
    fd = _make_fd(tmp_path, "a")
    preset = AnalysisPreset.free_config(
        name="ev", method="fft",
        target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0,))
    events = []
    BatchRunner({0: fd}).run(
        preset, tmp_path / "out",
        on_event=events.append,
    )
    kinds = [e.kind for e in events]
    assert kinds[0] == "task_started"
    assert "task_done" in kinds
    assert kinds[-1] == "run_finished"
    finish = events[-1]
    assert finish.final_status == "done"


def test_cancel_token_stops_after_current_task(tmp_path):
    fds = {0: _make_fd(tmp_path, "a", idx=0),
           1: _make_fd(tmp_path, "b", idx=1),
           2: _make_fd(tmp_path, "c", idx=2)}
    preset = AnalysisPreset.free_config(
        name="cn", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1, 2))

    token = threading.Event()
    seen = []

    def on_event(e):
        seen.append(e)
        if e.kind == "task_done" and e.task_index == 1:
            token.set()  # cancel after first done

    result = BatchRunner(fds).run(
        preset, tmp_path / "out",
        on_event=on_event, cancel_token=token,
    )
    assert result.status == "cancelled"
    cancelled = [e for e in seen if e.kind == "task_cancelled"]
    assert len(cancelled) >= 1   # at least one remaining task cancelled
    assert seen[-1].kind == "run_finished"
    assert seen[-1].final_status == "cancelled"


def test_loader_injection_for_disk_paths(tmp_path):
    fd_disk = _make_fd(tmp_path, "disk", idx=99)
    calls = []
    def fake_loader(path):
        calls.append(path)
        return fd_disk

    preset = AnalysisPreset.free_config(
        name="lp", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_paths=("/fake/path/x.mf4",))

    runner = BatchRunner({}, loader=fake_loader)
    result = runner.run(preset, tmp_path / "out")
    assert calls == ["/fake/path/x.mf4"]
    assert result.status == "done"


def test_loader_failure_marks_files_tasks_failed(tmp_path):
    fd_ok = _make_fd(tmp_path, "ok", idx=0)
    def loader(path):
        if "bad" in path:
            raise IOError("simulated bad mf4")
        return fd_ok  # pragma: no cover

    preset = AnalysisPreset.free_config(
        name="lf", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0,), file_paths=("/fake/bad.mf4",))

    events = []
    runner = BatchRunner({0: fd_ok}, loader=loader)
    result = runner.run(preset, tmp_path / "out", on_event=events.append)

    failed = [e for e in events if e.kind == "task_failed"]
    done = [e for e in events if e.kind == "task_done"]
    assert any("simulated bad mf4" in (e.error or "") for e in failed)
    assert len(done) >= 1   # the OK file still ran
    assert result.status == "partial"


def test_target_signals_all_missing_returns_blocked(tmp_path):
    fd = _make_fd(tmp_path, "x", idx=0)
    preset = AnalysisPreset.free_config(
        name="m", method="fft", target_signals=("nonexistent",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0,))
    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    assert result.status == "blocked"
    assert result.blocked == ["no matching batch tasks"]


def test_available_per_source_skips_missing_combinations(tmp_path):
    fd_a = _make_fd(tmp_path, "a", channels=("sig",), idx=0)
    fd_b = _make_fd(tmp_path, "b", channels=("other",), idx=1)
    preset = AnalysisPreset.free_config(
        name="pm", method="fft", target_signals=("sig",),
        target_policy="available_per_source",
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1))
    events = []
    result = BatchRunner({0: fd_a, 1: fd_b}).run(
        preset, tmp_path / "out", on_event=events.append,
    )
    done = [e for e in events if e.kind == "task_done"]
    failed = [e for e in events if e.kind == "task_failed"]
    assert len(done) == 1
    assert failed == []
    assert result.status == "done"


def test_available_per_source_skips_missing_custom_x_combinations(tmp_path):
    t = np.arange(8, dtype=float) / 8.0
    fd_with_x = FileData(
        tmp_path / "with_x.csv",
        pd.DataFrame({
            "Time": t,
            "sig": np.linspace(0.0, 1.0, len(t)),
            "angle": np.linspace(0.0, 180.0, len(t)),
        }),
        ["Time", "sig", "angle"],
        {"angle": "deg"},
        idx=0,
        fs=8.0,
    )
    fd_without_x = FileData(
        tmp_path / "without_x.csv",
        pd.DataFrame({
            "Time": t,
            "sig": np.linspace(1.0, 2.0, len(t)),
        }),
        ["Time", "sig"],
        {},
        idx=1,
        fs=8.0,
    )
    preset = AnalysisPreset.free_config(
        name="per-source custom X",
        method="time",
        target_signals=("sig",),
        target_policy="available_per_source",
        params={"x_source": "channel", "x_channel": "angle"},
        outputs=BatchOutput(
            export_data=True,
            export_image=False,
            write_manifest=False,
        ),
    )
    preset = replace(preset, file_ids=(0, 1))

    result = BatchRunner({0: fd_with_x, 1: fd_without_x}).run(
        preset, tmp_path / "out",
    )

    assert result.status == "done"
    assert [(item.file_id, item.signal) for item in result.items] == [(0, "sig")]


def test_legacy_progress_callback_still_works(tmp_path):
    fd = _make_fd(tmp_path, "a", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="cs", method="fft", signal=(0, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    calls = []
    BatchRunner({0: fd}).run(
        preset, tmp_path / "out",
        progress_callback=lambda i, n: calls.append((i, n)),
    )
    assert calls == [(1, 1)]


def test_progress_callback_count_excludes_failed_tasks(tmp_path):
    """Legacy contract: progress_callback fires once per task_done, never on
    task_failed (per spec §4.4 / §8)."""
    fd_ok = _make_fd(tmp_path, "ok", channels=("sig",), idx=0)
    fd_bad = _make_fd(tmp_path, "bad", channels=("other",), idx=1)
    preset = AnalysisPreset.free_config(
        name="pf", method="fft", target_signals=("sig",),
        target_policy="exact_pairs",
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(
        preset,
        file_ids=(0, 1),
        target_pairs=((0, "sig"), (1, "sig")),
    )
    calls = []
    result = BatchRunner({0: fd_ok, 1: fd_bad}).run(
        preset, tmp_path / "out",
        progress_callback=lambda i, n: calls.append((i, n)),
    )
    # 2 tasks total: 1 done (fd_ok), 1 failed (fd_bad missing 'sig')
    assert result.status == "partial"
    assert len(calls) == 1   # only the completed task bumped progress


def test_all_disk_files_failed_yields_per_task_failures(tmp_path):
    """If every file in selection fails to load, runner emits task_failed for
    each (not a blanket blocked) — spec §3.2, §7."""
    def loader(path):
        raise IOError(f"corrupt: {path}")
    preset = AnalysisPreset.free_config(
        name="adf", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_paths=("/fake/a.mf4", "/fake/b.mf4"))
    events = []
    result = BatchRunner({}, loader=loader).run(
        preset, tmp_path / "out", on_event=events.append,
    )
    failed = [e for e in events if e.kind == "task_failed"]
    assert len(failed) == 2
    assert result.status == "blocked"  # all-failed maps to blocked
    # but events still document each failure
    assert all("corrupt" in (e.error or "") for e in failed)


def test_target_signals_multi_signal_expansion(tmp_path):
    """N files × M target_signals → N*M task_done events (spec §8)."""
    fd_a = _make_fd(tmp_path, "a", channels=("vib_x", "vib_y"), idx=0)
    fd_b = _make_fd(tmp_path, "b", channels=("vib_x", "vib_y"), idx=1)
    preset = AnalysisPreset.free_config(
        name="mm", method="fft", target_signals=("vib_x", "vib_y"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1))
    events = []
    result = BatchRunner({0: fd_a, 1: fd_b}).run(
        preset, tmp_path / "out", on_event=events.append,
    )
    done = [e for e in events if e.kind == "task_done"]
    assert len(done) == 4   # 2 files × 2 signals
    assert result.status == "done"


def test_cancel_no_half_written_files(tmp_path):
    """Cancellation happens at task BOUNDARIES; the in-flight task must finish
    its file write before cancel takes effect (spec §4.5)."""
    fds = {0: _make_fd(tmp_path, "a", idx=0),
           1: _make_fd(tmp_path, "b", idx=1)}
    preset = AnalysisPreset.free_config(
        name="cw", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1))
    token = threading.Event()
    def on_event(e):
        if e.kind == "task_done" and e.task_index == 1:
            token.set()
    BatchRunner(fds).run(preset, tmp_path / "out",
                          on_event=on_event, cancel_token=token)
    out = tmp_path / "out"
    csvs = list(out.glob("*.csv"))
    # The first task's file must exist and be complete (parseable)
    assert any(p.name.startswith("a__sig__fft__") for p in csvs)
    for p in csvs:
        # No partial writes — file is complete CSV
        text = p.read_text()
        assert text.endswith("\n") or len(text) > 50


def test_dual_callback_ordering(tmp_path):
    fd = _make_fd(tmp_path, "a", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="dc", method="fft", signal=(0, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    log = []
    BatchRunner({0: fd}).run(
        preset, tmp_path / "out",
        progress_callback=lambda i, n: log.append("pc"),
        on_event=lambda e: log.append(f"ev:{e.kind}"),
    )
    # task_done 事件先，progress_callback 后
    assert "ev:task_done" in log
    assert "pc" in log
    assert log.index("ev:task_done") < log.index("pc")


def test_output_dir_create_failure_returns_blocked(tmp_path):
    """如果 output_dir 创建失败（如父路径是文件而非目录），blocked + run_finished(blocked)。"""
    fd = _make_fd(tmp_path, "a", idx=0)
    bad_parent = tmp_path / "is_a_file"
    bad_parent.write_text("not a dir")
    preset = AnalysisPreset.from_current_single(
        name="b", method="fft", signal=(0, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    events = []
    result = BatchRunner({0: fd}).run(
        preset, bad_parent / "sub",
        on_event=events.append,
    )
    assert result.status == "blocked"
    assert events[-1].kind == "run_finished"
    assert events[-1].final_status == "blocked"


def test_supported_methods_excludes_removed_order_rpm_and_order_track():
    """``order_rpm`` was permanently removed (commit cfb301b) and
    ``order_track`` was removed 2026-04-28 — neither has a handler in
    ``_run_one`` any more. Keeping a removed value in
    ``SUPPORTED_METHODS`` lets a stray preset pass ``_expand_tasks`` and
    fall through to the ``unsupported method`` raise (silent /
    undefined). This regression test pins the strict-subset invariant so
    later plans can't silently re-introduce a ghost handler (per
    ``signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md``).
        """
    assert BatchRunner.SUPPORTED_METHODS == {
        "time", "fft", "frf", "order_time", "fft_time",
    }
    assert "order_rpm" not in BatchRunner.SUPPORTED_METHODS
    assert "order_track" not in BatchRunner.SUPPORTED_METHODS


def test_legacy_order_track_preset_silently_skipped(tmp_path):
    """A v1 preset whose ``method`` is no longer in ``SUPPORTED_METHODS``
    (e.g. ``order_track``, removed 2026-04-28) must be skipped at load
    time, not raise — so import handlers can surface a friendly toast
    instead of crashing ``_run_one``'s ``else: raise``.
    """
    import json
    from mf4_analyzer.batch_preset_io import load_preset_from_json

    payload = {
        "schema_version": 1,
        "name": "legacy track",
        "method": "order_track",
        "target_signals": ["sig"],
        "rpm_channel": "rpm",
        "params": {"fs": 1024.0, "target_order": 2.0, "nfft": 1024},
        "outputs": {
            "export_data": True, "export_image": False, "data_format": "csv",
        },
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    # Must not raise. Returning None signals "skip"; the import handler
    # can render a friendly toast.
    result = load_preset_from_json(path)
    assert result is None


# ---------------------------------------------------------------------------
# Wave 3a (Phase 5): fft_time backend dispatch + dataframe + image + ceiling
# ---------------------------------------------------------------------------


def test_fft_time_method_supported(tmp_path):
    from mf4_analyzer.batch import BatchRunner
    assert "fft_time" in BatchRunner.SUPPORTED_METHODS


def test_fft_time_exports_long_format_dataframe(tmp_path):
    fd = _make_file(tmp_path, fs=1024.0)
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    preset = AnalysisPreset.free_config(
        name="batch fft_time",
        method="fft_time",
        target_signals=("sig",),
        params={
            "fs": 1024.0, "window": "hanning", "nfft": 256,
            "overlap": 0.5, "remove_mean": True,
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    import dataclasses
    preset = dataclasses.replace(preset, file_ids=(1,))
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    assert len(result.items) == 1
    df = pd.read_csv(result.items[0].data_path)
    assert list(df.columns) == ["time_s", "frequency_hz", "amplitude"]
    # Frame count must be > 1 with the synthetic 2048-sample input,
    # nfft=256, overlap=0.5 -> hop=128 -> at least 14 frames.
    assert df["time_s"].nunique() > 1
    assert df["frequency_hz"].nunique() == 256 // 2 + 1  # one-sided bins


def test_fft_time_batch_auto_rebuilds_nonuniform_time_axis(tmp_path):
    """Batch FFT-vs-Time should not block on jittered MF4 timestamps.

    A6: rebuild must leave an audit warning and write the rebuilt Fs into
    ``effective_params`` / the manifest so recorded facts match the compute.
    """
    from mf4_analyzer.batch_compute import suggest_fs_from_time_axis
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fs = 500.0
    n = 2048
    nominal_dt = 1.0 / fs
    dts = np.resize(np.array([1.2 * nominal_dt, 0.8 * nominal_dt]), n - 1)
    t = np.concatenate(([0.0], np.cumsum(dts)))
    sig = np.sin(2 * np.pi * 40.0 * (np.arange(n, dtype=float) / fs))
    df = pd.DataFrame({"Time": t, "sig": sig})
    fd = FileData(tmp_path / "jittered.mf4", df, list(df.columns), {}, idx=0)
    assert fd.is_time_axis_uniform() is False
    rebuilt_fs = float(suggest_fs_from_time_axis(t, fs))

    preset = AnalysisPreset.free_config(
        name="batch fft_time jittered",
        method="fft_time",
        target_signals=("sig",),
        params={
            "fs": fd.fs, "window": "hanning", "nfft": 256,
            "overlap": 0.5, "remove_mean": True,
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    import dataclasses
    preset = dataclasses.replace(preset, file_ids=(1,))

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.blocked == []
    item = result.items[0]
    data = pd.read_csv(item.data_path)
    assert list(data.columns) == ["time_s", "frequency_hz", "amplitude"]
    assert data["time_s"].nunique() > 1
    assert any("自动重建" in warning for warning in item.warnings)
    assert any("relative_jitter=" in warning for warning in item.warnings)
    assert any("自动重建" in warning for warning in result.warnings)
    assert item.effective_params["fs"] == pytest.approx(rebuilt_fs)
    assert item.effective_params["fs"] != pytest.approx(fs)
    manifest = load_batch_manifest(result.manifest_path)
    entry = next(
        row for row in manifest["entries"]
        if row.get("task_id") == item.task_id
    )
    assert any("自动重建" in warning for warning in entry["warnings"])
    assert entry["effective_facts"]["fs"] == pytest.approx(rebuilt_fs)


def test_fft_time_exports_image(tmp_path):
    fd = _make_file(tmp_path, fs=1024.0)
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    preset = AnalysisPreset.free_config(
        name="batch fft_time img",
        method="fft_time",
        target_signals=("sig",),
        params={
            "fs": 1024.0, "window": "hanning", "nfft": 256,
            "overlap": 0.5, "remove_mean": True,
        },
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    import dataclasses
    preset = dataclasses.replace(preset, file_ids=(1,))
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status == "done"
    assert result.items[0].image_path is not None
    assert result.items[0].image_path.endswith(".png")


def test_non_time_heatmap_invalid_cmap_adds_runner_warning(tmp_path):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_file(tmp_path, fs=1024.0)
    preset = AnalysisPreset.free_config(
        name="batch fft_time invalid cmap compatibility",
        method="fft_time",
        target_signals=("sig",),
        params={
            "fs": 1024.0,
            "window": "hanning",
            "nfft": 256,
            "overlap": 0.5,
            "remove_mean": True,
            "cmap": "not-a-colormap",
        },
        outputs=BatchOutput(
            export_data=False,
            export_image=True,
            write_manifest=True,
        ),
    )
    preset = replace(preset, file_ids=(1,))

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert Path(result.items[0].image_path).is_file()
    assert "Invalid colormap 'not-a-colormap'; using 'gnuplot2'." in (
        result.items[0].warnings
    )
    entry = load_batch_manifest(result.manifest_path)["entries"][0]
    assert "Invalid colormap 'not-a-colormap'; using 'gnuplot2'." in (
        entry["warnings"]
    )


@pytest.mark.parametrize(
    ("method", "params"),
    (
        ("fft", {"fs": 1024.0, "nfft": 64}),
        (
            "fft_time",
            {
                "fs": 1024.0,
                "window": "hanning",
                "nfft": 256,
                "overlap": 0.5,
            },
        ),
        (
            "order_time",
            {
                "fs": 1024.0,
                "nfft": 256,
                "max_order": 5.0,
                "order_res": 0.5,
                "time_res": 0.05,
                "samples_per_rev": 64,
            },
        ),
    ),
)
def test_non_time_renderer_warning_reaches_item_and_manifest(
    tmp_path, monkeypatch, method, params,
):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_file(tmp_path, fs=1024.0)
    warning = f"{method}-renderer-warning"

    def render_with_warning(
        payload, path, params=None, *, options=None, context=None,
        warnings_out=None,
    ):
        warnings_out.append(warning)
        Path(path).write_bytes(b"image")
        return Path(path)

    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(render_with_warning),
    )
    preset = AnalysisPreset.free_config(
        name=f"{method} warning",
        method=method,
        target_signals=("sig",),
        params=params,
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    preset = replace(preset, file_ids=(1,))

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    expected_warnings = [warning]
    if method == "order_time":
        expected_warnings.insert(
            0,
            "未指定转速通道，已按名称匹配使用 rpm —— 请确认",
        )
    assert result.items[0].warnings == expected_warnings
    entry = load_batch_manifest(result.manifest_path)["entries"][0]
    assert entry["warnings"] == expected_warnings


def test_fft_time_amplitude_ceiling_emits_failed_item(tmp_path, monkeypatch):
    """If the spectrogram analyzer rejects huge inputs (ValueError on
    >64 MB amplitude matrix), batch must surface that as a per-item
    failure rather than aborting the whole run."""
    fd = _make_file(tmp_path, fs=1024.0)
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    from mf4_analyzer.signal import spectrogram as sp_mod

    def boom(*args, **kwargs):
        raise ValueError("spectrogram amplitude matrix exceeds 64 MB")

    monkeypatch.setattr(sp_mod.SpectrogramAnalyzer, "compute", boom)

    preset = AnalysisPreset.free_config(
        name="boom",
        method="fft_time",
        target_signals=("sig",),
        params={"fs": 1024.0, "nfft": 256, "overlap": 0.5},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    import dataclasses
    preset = dataclasses.replace(preset, file_ids=(1,))
    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")
    assert result.status in ("partial", "blocked")
    assert any("64 MB" in (b or "") for b in result.blocked)


# ---------------------------------------------------------------------------
# Wave 1 (2026-04-28): batch order_time must route through COTOrderAnalyzer
# rather than the legacy frequency-domain OrderAnalyzer.compute_time_order_result.
# ---------------------------------------------------------------------------


def test_compute_order_time_dataframe_uses_cot(monkeypatch):
    """_compute_order_time_dataframe must route through COTOrderAnalyzer.compute,
    not OrderAnalyzer.compute_time_order_result.

    Spy both call sites; only the COT spy may be invoked.
    """
    from mf4_analyzer import batch as batch_mod
    from mf4_analyzer.signal import order as order_mod
    from mf4_analyzer.signal import order_cot as cot_mod

    cot_calls = []
    legacy_calls = []

    real_cot = cot_mod.COTOrderAnalyzer.compute
    real_legacy = order_mod.OrderAnalyzer.compute_time_order_result

    def spy_cot(sig, rpm, t, params, **kw):
        cot_calls.append(('cot', len(sig)))
        return real_cot(sig, rpm, t, params, **kw)

    def spy_legacy(*a, **kw):
        legacy_calls.append(('legacy',))
        return real_legacy(*a, **kw)

    monkeypatch.setattr(cot_mod.COTOrderAnalyzer, 'compute', staticmethod(spy_cot))
    monkeypatch.setattr(order_mod.OrderAnalyzer, 'compute_time_order_result',
                        staticmethod(spy_legacy))

    # Synthetic 4 s signal at 1 kHz with constant 1200 RPM, second-order tone
    import numpy as np
    fs = 1000.0
    t = np.arange(0.0, 4.0, 1.0 / fs)
    rpm_const = 1200.0
    target_order = 2.0
    f = target_order * rpm_const / 60.0
    sig = np.sin(2 * np.pi * f * t)
    rpm = np.full_like(t, rpm_const)

    params = {
        'fs': fs, 'nfft': 1024, 'window': 'hanning',
        'max_order': 5.0, 'order_res': 0.1, 'time_res': 0.05,
        # samples_per_rev not specified → default 256
    }

    df = batch_mod.BatchRunner._compute_order_time_dataframe(
        sig, rpm, t, fs, params)

    assert cot_calls, 'COT path must be invoked'
    assert not legacy_calls, 'Legacy frequency-domain path must NOT be invoked'
    assert {'time_s', 'order', 'amplitude'} <= set(df.columns)


def test_legacy_preset_with_algorithm_silently_ignored(tmp_path):
    """A preset emitted before 2026-04-28 may contain {algorithm: 'frequency'}
    and {dynamic: '30 dB'}. load_preset_from_json must accept it without
    raising and translate to the new field set."""
    import json
    from mf4_analyzer.batch_preset_io import load_preset_from_json

    # W6: schema actually uses target_signals / rpm_channel; the old
    # 'signal' / 'rpm_signal' top-level keys are silently ignored by
    # load_preset_from_json. Use the real schema for fixture clarity.
    legacy = {
        "method": "order_time",
        "name": "legacy",
        "target_signals": ["ch1"],
        "rpm_channel": "rpm",
        "params": {
            "fs": 1000.0, "nfft": 1024, "max_order": 20,
            "order_res": 0.1, "time_res": 0.05,
            "algorithm": "frequency",   # legacy
            "dynamic": "30 dB",          # legacy
            "amplitude_mode": "Amplitude dB",
        },
    }
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(legacy), encoding='utf-8')

    preset = load_preset_from_json(str(p))
    assert preset is not None  # not silently dropped (method is supported)
    # 'algorithm' migrated away
    assert 'algorithm' not in preset.params
    # 'dynamic' translated
    assert preset.params.get('z_auto') is False
    assert preset.params.get('z_floor') == -30.0
    assert preset.params.get('z_ceiling') == 0.0


def test_batch_fft_dataframe_uses_linear_average_mode(monkeypatch):
    from mf4_analyzer.signal.fft import FFTAnalyzer

    captured = {}

    def fake_averaged(sig, fs, win, nfft, overlap, weighting="None"):
        captured.update(
            fs=fs, win=win, nfft=nfft, overlap=overlap, weighting=weighting,
        )
        return np.array([0.0, 1.0]), np.array([2.0, 3.0]), np.array([4.0, 9.0])

    monkeypatch.setattr(
        FFTAnalyzer, "compute_averaged_fft", staticmethod(fake_averaged)
    )

    df = BatchRunner._compute_fft_dataframe(
        np.ones(4096),
        1000.0,
        {
            "window": "blackman",
            "nfft": 512,
            "avg_mode": "线性平均",
            "avg_overlap": 75,
            "weighting": "A",
        },
    )

    assert captured == {
        "fs": 1000.0,
        "win": "blackman",
        "nfft": 512,
        "overlap": 0.75,
        "weighting": "A",
    }
    np.testing.assert_allclose(df["amplitude"].to_numpy(), np.array([2.0, 3.0]))


def test_batch_fft_dataframe_uses_peak_hold_mode(monkeypatch):
    from mf4_analyzer.signal.fft import FFTAnalyzer

    captured = {}

    def fake_peak(sig, fs, *, win, nfft, overlap, weighting="None"):
        captured.update(
            fs=fs, win=win, nfft=nfft, overlap=overlap, weighting=weighting,
        )
        return np.array([0.0, 1.0]), np.array([5.0, 6.0])

    monkeypatch.setattr(
        FFTAnalyzer, "compute_peak_hold_fft", staticmethod(fake_peak)
    )

    df = BatchRunner._compute_fft_dataframe(
        np.ones(4096),
        1000.0,
        {
            "window": "hamming",
            "nfft": 1024,
            "avg_mode": "峰值保持",
            "avg_overlap": 25,
            "weighting": "A",
        },
    )

    assert captured == {
        "fs": 1000.0,
        "win": "hamming",
        "nfft": 1024,
        "overlap": 0.25,
        "weighting": "A",
    }
    np.testing.assert_allclose(df["amplitude"].to_numpy(), np.array([5.0, 6.0]))


@pytest.mark.parametrize(
    ("avg_mode", "native_definition"),
    (
        ("单帧", "peak"),
        ("线性平均", "rms"),
        ("峰值保持", "peak"),
    ),
)
@pytest.mark.parametrize("requested_definition", ("native", "peak", "rms"))
def test_batch_fft_amplitude_definition_converts_from_mode_native_semantics(
    monkeypatch, avg_mode, native_definition, requested_definition,
):
    from mf4_analyzer.signal.fft import FFTAnalyzer

    native_amplitude = np.array([2.0, 4.0])
    frequencies = np.array([0.0, 1.0])
    monkeypatch.setattr(
        FFTAnalyzer,
        "compute_fft",
        staticmethod(lambda *args, **kwargs: (frequencies, native_amplitude.copy())),
    )
    monkeypatch.setattr(
        FFTAnalyzer,
        "compute_averaged_fft",
        staticmethod(lambda *args, **kwargs: (
            frequencies,
            native_amplitude.copy(),
            native_amplitude ** 2,
        )),
    )
    monkeypatch.setattr(
        FFTAnalyzer,
        "compute_peak_hold_fft",
        staticmethod(lambda *args, **kwargs: (frequencies, native_amplitude.copy())),
    )

    frame = BatchRunner._compute_fft_dataframe(
        np.ones(16),
        16.0,
        {
            "nfft": 8,
            "avg_mode": avg_mode,
            "amplitude_definition": requested_definition,
        },
    )

    expected = native_amplitude.copy()
    if requested_definition != "native" and requested_definition != native_definition:
        expected = (
            expected * np.sqrt(2.0)
            if native_definition == "rms"
            else expected / np.sqrt(2.0)
        )
    np.testing.assert_allclose(frame["amplitude"].to_numpy(), expected)


@pytest.mark.parametrize("avg_mode", ("单帧", "线性平均", "峰值保持"))
def test_batch_fft_missing_amplitude_definition_is_native(monkeypatch, avg_mode):
    from mf4_analyzer.signal.fft import FFTAnalyzer

    frequencies = np.array([0.0])
    amplitude = np.array([3.0])
    monkeypatch.setattr(
        FFTAnalyzer,
        "compute_fft",
        staticmethod(lambda *args, **kwargs: (frequencies, amplitude.copy())),
    )
    monkeypatch.setattr(
        FFTAnalyzer,
        "compute_averaged_fft",
        staticmethod(lambda *args, **kwargs: (
            frequencies, amplitude.copy(), amplitude ** 2,
        )),
    )
    monkeypatch.setattr(
        FFTAnalyzer,
        "compute_peak_hold_fft",
        staticmethod(lambda *args, **kwargs: (frequencies, amplitude.copy())),
    )

    implicit = BatchRunner._compute_fft_dataframe(
        np.ones(16), 16.0, {"nfft": 8, "avg_mode": avg_mode},
    )
    explicit = BatchRunner._compute_fft_dataframe(
        np.ones(16),
        16.0,
        {
            "nfft": 8,
            "avg_mode": avg_mode,
            "amplitude_definition": "native",
        },
    )

    pd.testing.assert_frame_equal(implicit, explicit)


def test_batch_fft_amplitude_definition_stays_linear_when_display_is_db(monkeypatch):
    from mf4_analyzer.signal.fft import FFTAnalyzer

    monkeypatch.setattr(
        FFTAnalyzer,
        "compute_fft",
        staticmethod(lambda *args, **kwargs: (
            np.array([10.0]), np.array([2.0]),
        )),
    )

    frame = BatchRunner._compute_fft_dataframe(
        np.ones(16),
        16.0,
        {
            "nfft": 8,
            "avg_mode": "单帧",
            "amplitude_definition": "rms",
            "amp_y": "dB",
        },
    )

    np.testing.assert_allclose(frame["amplitude"], [2.0 / np.sqrt(2.0)])


def test_batch_fft_dataframe_resolves_auto_nfft_for_average_mode(monkeypatch):
    from mf4_analyzer.signal.fft import FFTAnalyzer

    captured = {}

    def fake_averaged(sig, fs, win, nfft, overlap, weighting="None"):
        captured["nfft"] = nfft
        return np.array([0.0]), np.array([1.0]), np.array([1.0])

    monkeypatch.setattr(
        FFTAnalyzer, "compute_averaged_fft", staticmethod(fake_averaged)
    )

    BatchRunner._compute_fft_dataframe(
        np.ones(5002),
        96.0,
        {
            "window": "hanning",
            "nfft": None,
            "nfft_mode": "auto",
            "t_win_s": 1.5,
            "avg_mode": "线性平均",
            "avg_overlap": 75,
        },
    )

    assert captured["nfft"] == 256


# ---------------------------------------------------------------------------
# Task 1: _Spectro2D + pivot-round-trip elimination (TDD-first)
# ---------------------------------------------------------------------------


def test_order_time_spectro_matrix_matches_long_dataframe():
    import numpy as np
    from mf4_analyzer.batch import BatchRunner, _Spectro2D
    rng = np.random.default_rng(0)
    n = 4096
    fs = 1000.0
    t = np.arange(n) / fs
    sig = np.sin(2 * np.pi * 5 * t)
    rpm = np.linspace(600, 1800, n)
    params = {'samples_per_rev': 64, 'nfft': 256, 'max_order': 10,
              'order_res': 0.5, 'time_res': 0.1}
    spectro = BatchRunner._compute_order_time_spectro(sig, rpm, t, fs, params)
    assert isinstance(spectro, _Spectro2D)
    assert spectro.matrix.shape == (len(spectro.x), len(spectro.y))
    df_new = spectro.to_long_dataframe()
    df_old = BatchRunner._compute_order_time_dataframe(sig, rpm, t, fs, params)
    pd.testing.assert_frame_equal(df_new, df_old)


def test_heatmap_producer_matrix_matches_legacy_long_pivot_orientation(tmp_path):
    import numpy as np
    from mf4_analyzer.batch import BatchRunner, _Spectro2D
    x = np.array([0.0, 1.0, 2.0])           # time
    y = np.array([1.0, 2.0])                 # order
    matrix = np.array([[1., 2.], [3., 4.], [5., 6.]])  # (len(x), len(y))
    spectro = _Spectro2D(x, y, matrix, 'time_s', 'order')
    # Qt ImageItem receives ``matrix.T`` (rows=y, cols=x); pin the producer
    # orientation here while renderer corner mapping lives in Qt parity tests.
    df = spectro.to_long_dataframe()
    pivot = df.pivot(index='order', columns='time_s', values='amplitude')
    np.testing.assert_allclose(pivot.to_numpy(), matrix.T)


def test_image_only_export_skips_long_dataframe(tmp_path, monkeypatch):
    import numpy as np
    from mf4_analyzer.batch import BatchRunner, _Spectro2D
    calls = {'n': 0}
    orig = _Spectro2D.to_long_dataframe

    def spy(self):
        calls['n'] += 1
        return orig(self)

    monkeypatch.setattr(_Spectro2D, 'to_long_dataframe', spy)
    x = np.array([0., 1.])
    y = np.array([1., 2.])
    sp = _Spectro2D(x, y, np.array([[1., 2.], [3., 4.]]), 'time_s', 'order')
    BatchRunner._write_image(('order_time', sp), tmp_path / 'i.png',
                             params={'z_auto': True})
    assert calls['n'] == 0  # image render must not trigger long-table construction


def test_heatmap_long_dataframe_is_released_before_image_render(
    tmp_path, monkeypatch,
):
    import gc
    import weakref
    from mf4_analyzer.batch import _Spectro2D

    fd = _make_file(tmp_path)
    references = {}

    class TrackedSpectro(_Spectro2D):
        def to_long_dataframe(self):
            frame = super().to_long_dataframe()
            references["long"] = weakref.ref(frame)
            return frame

    spectro = TrackedSpectro(
        x=np.array([0.0, 1.0]),
        y=np.array([10.0, 20.0]),
        matrix=np.array([[1.0, 2.0], [3.0, 4.0]]),
        x_name="time_s",
        y_name="frequency_hz",
    )

    def fake_compute(*args, **kwargs):
        return spectro

    def write_data(frame, path):
        Path(path).write_text("data", encoding="utf-8")

    def render_after_data_release(payload, path, params=None, *, options=None,
                                  context=None, warnings_out=None):
        gc.collect()
        assert references["long"]() is None
        Path(path).write_bytes(b"image")
        return Path(path)

    monkeypatch.setattr(
        BatchRunner, "_compute_fft_time_spectro", staticmethod(fake_compute),
    )
    monkeypatch.setattr(
        BatchRunner, "_write_dataframe", staticmethod(write_data),
    )
    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(render_after_data_release),
    )
    preset = AnalysisPreset.from_current_single(
        name="bounded heatmap intermediates",
        method="fft_time",
        signal=(1, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=True),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"


# ---------------------------------------------------------------------------
# Task 2: lazy per-task file load + single-file disk eviction (TDD-first)
# ---------------------------------------------------------------------------


def test_file_paths_loaded_lazily_and_evicted(tmp_path):
    """Loader must be called once per disk path, in task order (not upfront),
    and _disk_cache must hold at most 1 disk file at a time."""
    import numpy as np
    import pandas as pd
    import dataclasses
    from mf4_analyzer.batch import BatchRunner, AnalysisPreset, BatchOutput
    from mf4_analyzer.io import FileData

    load_order = []
    peak = {'max': 0}

    def spy_loader(path):
        load_order.append(path)
        df = pd.DataFrame({'sig': np.zeros(8), 'rpm': np.linspace(1, 2, 8)})
        return FileData(path, df, list(df.columns), {}, idx=-1)

    runner = BatchRunner(files={}, loader=spy_loader)

    # Wrap _disk_cache to observe peak simultaneous resident count.
    class WatchDict(dict):
        def __setitem__(self, k, v):
            super().__setitem__(k, v)
            peak['max'] = max(peak['max'], len(self))

    runner._disk_cache = WatchDict()

    preset = AnalysisPreset.free_config(
        name='t', method='fft', target_signals=('sig',),
        outputs=BatchOutput(export_data=True, export_image=False,
                            data_format='csv'),
        params={'fs': 1.0, 'window': 'hanning', 'nfft': 8},
    )
    preset = dataclasses.replace(preset, file_paths=('a.mf4', 'b.mf4', 'c.mf4'))

    result = runner.run(preset, tmp_path)

    assert result.status == 'done'
    assert load_order == ['a.mf4', 'b.mf4', 'c.mf4']  # loaded in task order
    assert peak['max'] == 1  # at most 1 disk file resident at a time


def test_target_signals_none_match_loaded_files_blocks(tmp_path):
    """All-loaded files with no matching target_signals → blocked (preserved semantic)."""
    import numpy as np
    import pandas as pd
    import dataclasses
    from mf4_analyzer.batch import BatchRunner, AnalysisPreset
    from mf4_analyzer.io import FileData

    df = pd.DataFrame({'foo': np.zeros(8)})
    fd = FileData('f.mf4', df, list(df.columns), {}, idx=0)
    runner = BatchRunner(files={'f0': fd})

    preset = AnalysisPreset.free_config(name='t', method='fft',
                                        target_signals=('nope',),
                                        params={'fs': 1.0})
    preset = dataclasses.replace(preset, file_ids=('f0',))

    result = runner.run(preset, tmp_path)
    assert result.status == 'blocked'
    assert result.blocked == ['no matching batch tasks']


# ---------------------------------------------------------------------------
# dB-reference-defaults Task 9 (spec §13 S4 / §15 C4, plan Step 9.1):
# Batch Auto resolution + image label parity with the interactive canvas.
# ---------------------------------------------------------------------------

def _make_multi_unit_file(tmp_path, fs=1024.0):
    """One file, two channels: 'acc' resolves via CHANNEL METADATA
    (quantity+unit), 'velo' resolves via the plain ``channel_units`` map
    alone (no metadata entry) -- exercising BOTH Auto-resolution inputs."""
    n = 512
    t = np.arange(n, dtype=float) / fs
    df = pd.DataFrame({
        "Time": t,
        "acc": np.sin(2 * np.pi * 50 * t),
        "velo": np.sin(2 * np.pi * 80 * t),
    })
    path = tmp_path / "multi_unit.csv"
    df.to_csv(path, index=False)
    units = {"velo": "m/s"}
    channel_metadata = {"acc": {"quantity": "acceleration", "unit": "m/s²"}}
    return FileData(path, df, list(df.columns), units, idx=0,
                    channel_metadata=channel_metadata)


def test_batch_runner_auto_resolves_each_target_channel_metadata_or_unit(tmp_path):
    fd = _make_multi_unit_file(tmp_path)
    preset = AnalysisPreset.free_config(
        name="auto ref", method="fft",
        target_signals=("acc", "velo"),
        params={"window": "hanning", "nfft": 64, "amp_y": "dB"},
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    preset = replace(preset, file_ids=(0,))

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    by_signal = {item.signal: item for item in result.items}
    # 'acc' resolves via channel_metadata (quantity+unit) -> acceleration.si
    assert by_signal["acc"].db_reference_value == pytest.approx(1e-6)
    assert by_signal["acc"].db_reference_source == "system"
    # 'velo' resolves via channel_units alone (no metadata entry) -> velocity.si
    assert by_signal["velo"].db_reference_value == pytest.approx(1e-9)
    assert by_signal["velo"].db_reference_source == "system"


def test_batch_runner_accepts_immutable_catalog_snapshot_without_qsettings(tmp_path):
    """Batch/worker code must never import/read global QSettings directly --
    the catalog snapshot injected via ``db_reference_catalog=`` is plain,
    duck-typed data (spec Global Constraints / plan Step 9.2). Batch DOES
    legitimately use PyQt5/pyqtgraph for PNG image rendering (pre-existing,
    unrelated to this constraint) -- only ``QSettings`` (the settings-
    persistence layer the catalog store is built on) is forbidden.

    Checked via the AST import graph (not a raw substring search) so a
    docstring/comment that merely NAMES the forbidden type (to explain why
    it is absent) cannot false-positive this guard -- only an actual
    ``import``/``from ... import`` statement counts.
    """
    import ast
    import inspect
    from types import SimpleNamespace

    from mf4_analyzer import batch as batch_mod
    from mf4_analyzer.db_reference import DbReferenceEntry

    tree = ast.parse(inspect.getsource(batch_mod))
    forbidden_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            forbidden_modules.extend(
                alias.name for alias in node.names if alias.name == "QSettings"
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            forbidden_modules.extend(
                alias.name for alias in node.names if alias.name == "QSettings"
            )
    assert not forbidden_modules, (
        f"batch.py must never import QSettings directly -- the catalog "
        f"snapshot must be plain data injected from outside; found: "
        f"{forbidden_modules}"
    )

    fd = _make_file(tmp_path)
    fd.channel_metadata["sig"] = {"quantity": "torque", "unit": "Nm"}
    custom_entry = DbReferenceEntry(
        id="user.custom_torque", quantity="torque", label="Custom torque",
        unit="Nm", aliases=("Nm",), reference=3.0, builtin_id=None,
    )
    snapshot = SimpleNamespace(
        system_catalog=(),
        user_catalog=(custom_entry,),
        prefer_channel_metadata=True,
        revision=1,
    )
    preset = AnalysisPreset.from_current_single(
        name="snapshot", method="fft", signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 64, "amp_y": "dB"},
        outputs=BatchOutput(export_data=False, export_image=True),
    )

    runner = BatchRunner({1: fd}, db_reference_catalog=snapshot)
    result = runner.run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.items[0].db_reference_value == pytest.approx(3.0)
    assert result.items[0].db_reference_source == "user"


def test_batch_legacy_value_without_mode_is_manual(tmp_path):
    """Spec S4: a preset with a bare ``db_reference`` value and NO
    ``db_reference_mode`` key migrates to Manual (the old value WAS the
    authoritative display reference), overriding any metadata/catalog
    match for that target."""
    fd = _make_file(tmp_path)
    fd.channel_metadata["sig"] = {"quantity": "acceleration", "unit": "m/s²"}
    preset = AnalysisPreset.from_current_single(
        name="legacy manual", method="fft", signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 64,
                "amp_y": "dB", "db_reference": 5.0},
        outputs=BatchOutput(export_data=False, export_image=True),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.items[0].db_reference_source == "manual"
    assert result.items[0].db_reference_value == pytest.approx(5.0)


def test_batch_fft_image_label_contains_exact_db_reference(tmp_path):
    fd = _make_file(tmp_path)
    fd.channel_metadata["sig"] = {"quantity": "acceleration", "unit": "m/s²"}
    preset = AnalysisPreset.from_current_single(
        name="fft label", method="fft", signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 64, "amp_y": "dB"},
        outputs=BatchOutput(export_data=False, export_image=True),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.items[0].colorbar_label == "Amplitude (dB re 1×10⁻⁶ m/s²)"


def test_batch_a_weighted_image_uses_dba_reference(tmp_path):
    fd = _make_file(tmp_path)
    fd.channel_metadata["sig"] = {"quantity": "acceleration", "unit": "m/s²"}
    preset = AnalysisPreset.from_current_single(
        name="dba label", method="fft", signal=(1, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 64,
                "amp_y": "dB", "weighting": "A"},
        outputs=BatchOutput(export_data=False, export_image=True),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.items[0].colorbar_label == "Amplitude (dBA re 1×10⁻⁶ m/s²)"


def test_batch_heatmap_image_colorbar_uses_shared_label_formatter(tmp_path):
    fd = _make_file(tmp_path, fs=1024.0)
    fd.channel_metadata["sig"] = {"quantity": "sound pressure", "unit": "Pa"}
    fd.source_metadata["source_kind"] = "audio"
    preset = AnalysisPreset.free_config(
        name="heatmap label", method="fft_time",
        target_signals=("sig",),
        params={"fs": 1024.0, "nfft": 64, "overlap": 0.5, "remove_mean": True},
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    preset = replace(preset, file_ids=(1,))

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    # Same shared formatter the interactive FFT-vs-Time canvas uses (spec
    # §14.1's canonical Pa/audio example) -- not a batch-local hard-code.
    assert result.items[0].colorbar_label == "Sound pressure (dB re 20 µPa)"


def test_batch_csv_values_are_identical_across_reference_changes(tmp_path):
    """Spec §15 C4: CSV/DataFrame export stays linear regardless of the
    resolved dB reference -- only the IMAGE label/levels are affected."""
    fd = _make_file(tmp_path)
    fd.channel_metadata["sig"] = {"quantity": "acceleration", "unit": "m/s²"}
    base_params = {"fs": 1024.0, "window": "hanning", "nfft": 64, "amp_y": "dB"}

    preset_a = AnalysisPreset.from_current_single(
        name="ref A", method="fft", signal=(1, "sig"),
        params=dict(base_params, db_reference=1.0),
        outputs=BatchOutput(export_data=True, export_image=True),
    )
    preset_b = AnalysisPreset.from_current_single(
        name="ref B", method="fft", signal=(1, "sig"),
        params=dict(base_params, db_reference=1e6),
        outputs=BatchOutput(export_data=True, export_image=True),
    )

    result_a = BatchRunner({1: fd}).run(preset_a, tmp_path / "out_a")
    result_b = BatchRunner({1: fd}).run(preset_b, tmp_path / "out_b")

    assert result_a.status == "done" and result_b.status == "done"
    # The resolved reference (and its label) legitimately differ...
    assert (result_a.items[0].db_reference_value
            != result_b.items[0].db_reference_value)
    assert result_a.items[0].colorbar_label != result_b.items[0].colorbar_label
    # ...but the exported linear CSV values must be BYTE identical.
    df_a = pd.read_csv(result_a.items[0].data_path)
    df_b = pd.read_csv(result_b.items[0].data_path)
    pd.testing.assert_frame_equal(df_a, df_b)


# ---------------------------------------------------------------------------
# Phase 1 correctness / reproducibility integration
# ---------------------------------------------------------------------------


def test_target_pairs_take_precedence_over_legacy_cartesian_expansion(tmp_path):
    fd_a = _make_fd(tmp_path, "pair_a", channels=("left", "right"), idx=0)
    fd_b = _make_fd(tmp_path, "pair_b", channels=("left", "right"), idx=1)
    preset = AnalysisPreset.free_config(
        name="pairs",
        method="fft",
        target_signals=("left", "right"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=False, export_image=False),
    )
    preset = replace(
        preset,
        file_ids=(0, 1),
        target_pairs=((0, "left"), (1, "right")),
    )

    tasks = list(BatchRunner({0: fd_a, 1: fd_b})._expand_tasks(preset))

    assert tasks == [(0, "left"), (1, "right")]


def test_runner_records_stable_identity_and_separates_same_basename_sources(tmp_path):
    n = 128
    t = np.arange(n, dtype=float) / 128.0
    frame = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 5 * t)})
    first = FileData(
        tmp_path / "first" / "同名.csv", frame.copy(), list(frame.columns), {},
        idx=0, fs=128.0,
    )
    second = FileData(
        tmp_path / "second" / "同名.csv", frame.copy(), list(frame.columns), {},
        idx=1, fs=128.0,
    )
    preset = AnalysisPreset.free_config(
        name="identity",
        method="fft",
        target_signals=("sig",),
        params={"fs": 128.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    preset = replace(
        preset,
        file_ids=(0, 1),
        target_pairs=((0, "sig"), (1, "sig")),
    )

    result = BatchRunner({0: first, 1: second}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert len({item.task_id for item in result.items}) == 2
    assert len({item.data_path for item in result.items}) == 2
    assert all(item.group_identity == "default" for item in result.items)
    # The fallback group stays in the identity but never in the filename.
    assert all(
        Path(item.data_path).name == f"同名__sig__fft__{item.task_id[:8]}.csv"
        for item in result.items
    )
    assert all(item.source_identity and item.effective_params["fs"] == 128.0
               for item in result.items)
    assert all(Path(item.data_path).exists() for item in result.items)


def test_runner_default_collision_policy_auto_numbers_instead_of_overwriting(tmp_path):
    fd = _make_fd(tmp_path, "collision", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="collision",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    runner = BatchRunner({0: fd})

    first = runner.run(preset, tmp_path / "out")
    second = runner.run(preset, tmp_path / "out")

    assert first.status == second.status == "done"
    assert first.items[0].data_path != second.items[0].data_path
    assert Path(first.items[0].data_path).exists()
    assert Path(second.items[0].data_path).exists()


def test_runner_retries_once_when_output_appears_after_path_selection(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "race", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="race",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    import mf4_analyzer.batch as batch_module
    from mf4_analyzer.batch_output import OutputPublishRace

    original = batch_module.atomic_write_set
    calls = {"count": 0}

    def collide_once(reservation, writers):
        calls["count"] += 1
        if calls["count"] == 1:
            reservation.paths["csv"].write_text("racer", encoding="utf-8")
            raise OutputPublishRace("simulated output race")
        return original(reservation, writers)

    monkeypatch.setattr(batch_module, "atomic_write_set", collide_once)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert Path(result.items[0].data_path).name.endswith("__2.csv")
    assert (tmp_path / "out" / Path(result.items[0].data_path).name).exists()


@pytest.mark.parametrize(
    ("policy", "expected_run_status", "expected_task_status", "event_kind"),
    (
        ("error", "blocked", "failed", "task_failed"),
        ("skip", "partial", "skipped", "task_skipped"),
    ),
)
def test_runner_error_and_skip_conflicts_stop_before_compute(
    tmp_path, monkeypatch, policy, expected_run_status, expected_task_status,
    event_kind,
):
    fd = _make_fd(tmp_path, f"conflict_{policy}", idx=0)
    base_outputs = BatchOutput(
        export_data=True, export_image=False, write_manifest=False,
    )
    preset = AnalysisPreset.from_current_single(
        name="conflict",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=base_outputs,
    )
    first = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    old_bytes = Path(first.items[0].data_path).read_bytes()
    conflicted = replace(
        preset,
        outputs=replace(base_outputs, conflict_policy=policy),
    )

    def fail_if_computed(*args, **kwargs):
        pytest.fail("conflict policy must resolve before compute")

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)
    events = []

    result = BatchRunner({0: fd}).run(
        conflicted, tmp_path / "out", on_event=events.append,
    )

    assert result.status == expected_run_status
    assert result.items[0].status == expected_task_status
    assert event_kind in [event.kind for event in events]
    assert Path(first.items[0].data_path).read_bytes() == old_bytes
    if policy == "skip":
        assert "manifest" in result.items[0].warnings[0]
        assert result.blocked


def test_skip_partial_artifact_conflict_is_explicit_and_never_writes_sibling(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "skip_partial", idx=0)
    data_only = AnalysisPreset.from_current_single(
        name="skip partial",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(
            export_data=True, export_image=False, write_manifest=False,
        ),
    )
    first = BatchRunner({0: fd}).run(data_only, tmp_path / "out")
    request_set = replace(
        data_only,
        outputs=replace(
            data_only.outputs,
            export_image=True,
            conflict_policy="skip",
        ),
    )

    def fail_if_computed(*args, **kwargs):
        pytest.fail("partial skip conflict must stop before compute")

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)

    result = BatchRunner({0: fd}).run(request_set, tmp_path / "out")

    assert result.status == "partial"
    assert result.items[0].status == "skipped"
    assert result.items[0].data_path == first.items[0].data_path
    assert result.items[0].image_path is None
    assert result.summary["skipped"] == 1
    assert result.blocked and "missing=png" in result.blocked[0]
    assert not list((tmp_path / "out").glob("*.png"))


def test_runner_overwrite_writer_failure_preserves_old_artifact_set(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "overwrite_set", idx=0)

    def render_ok(payload, path, params=None, *, options=None, context=None,
                  warnings_out=None):
        Path(path).write_bytes(b"old-image")
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(render_ok))
    outputs = BatchOutput(
        export_data=True,
        export_image=True,
        conflict_policy="overwrite",
        write_manifest=False,
    )
    preset = AnalysisPreset.from_current_single(
        name="overwrite",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=outputs,
    )
    first = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    data_path = Path(first.items[0].data_path)
    image_path = Path(first.items[0].image_path)
    old_data = data_path.read_bytes()
    old_image = image_path.read_bytes()

    def render_fail(payload, path, params=None, *, options=None, context=None,
                    warnings_out=None):
        Path(path).write_bytes(b"partial-new-image")
        raise RuntimeError("render failed")

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(render_fail))
    second = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert second.status == "blocked"
    assert second.items[0].status == "failed"
    assert data_path.read_bytes() == old_data
    assert image_path.read_bytes() == old_image


def _raise_batch_render_import(name, globals=None, locals=None, fromlist=(), level=0):
    if str(name).endswith("batch_render"):
        raise ModuleNotFoundError(
            "simulated missing Qt batch render backend",
            name="mf4_analyzer.batch_render",
        )
    return _REAL_IMPORT(name, globals, locals, fromlist, level)


_REAL_IMPORT = builtins.__import__
_DEGRADED_REASON = "图片/PDF 导出后端不可用，本次仅导出数据文件"


def test_runner_degrades_data_and_png_before_reservation_when_backend_import_fails(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch as batch_module
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(tmp_path, "backend_missing", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="degraded PNG",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(
            export_data=True,
            export_image=True,
            image_format="png",
        ),
    )
    reservations = []
    original_reserve = batch_module.reserve_output_paths

    def capture_reservation(directory, stem, extensions, *, conflict_policy):
        reservations.append(tuple(extensions))
        return original_reserve(
            directory, stem, extensions, conflict_policy=conflict_policy,
        )

    monkeypatch.setattr(batch_module, "reserve_output_paths", capture_reservation)
    monkeypatch.setattr(builtins, "__import__", _raise_batch_render_import)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "partial"
    assert result.degraded_count == 1
    assert result.warnings == [_DEGRADED_REASON]
    assert result.blocked == []
    item = result.items[0]
    assert item.status == "done"
    assert item.degraded_reason == _DEGRADED_REASON
    assert item.warnings == [_DEGRADED_REASON]
    assert item.requested_outputs == {"data": "csv", "image": "png"}
    assert item.effective_outputs == {"data": "csv"}
    assert reservations == [("csv",)]
    assert Path(item.data_path).is_file()
    assert item.image_path is None

    output_dir = tmp_path / "out"
    assert not list(output_dir.glob("*.png"))
    assert not list(output_dir.glob("*.partial.json"))
    assert not list(output_dir.glob(".*.batch-reserve"))
    assert not list(output_dir.glob(".*.batch-stage.*"))

    manifest = load_batch_manifest(result.manifest_path)
    assert manifest["run_status"] == "partial"
    entry = manifest["entries"][0]
    assert entry["status"] == "done"
    assert entry["requested_outputs"] == {"data": "csv", "image": "png"}
    assert entry["effective_outputs"] == {"data": "csv"}
    assert entry["degraded_reason"] == _DEGRADED_REASON
    assert set(entry["artifacts"]) == {"data"}


def test_runner_degraded_skip_conflict_reads_only_effective_output_paths(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "degraded_skip", idx=0)
    data_only = AnalysisPreset.from_current_single(
        name="degraded skip",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(
            export_data=True,
            export_image=False,
            write_manifest=False,
        ),
    )
    first = BatchRunner({0: fd}).run(data_only, tmp_path / "out")
    requested = replace(
        data_only,
        outputs=replace(
            data_only.outputs,
            export_image=True,
            image_format="png",
            conflict_policy="skip",
        ),
    )
    monkeypatch.setattr(builtins, "__import__", _raise_batch_render_import)

    result = BatchRunner({0: fd}).run(requested, tmp_path / "out")

    assert result.status == "partial"
    assert result.degraded_count == 1
    assert result.items[0].status == "skipped"
    assert result.items[0].data_path == first.items[0].data_path
    assert result.items[0].image_path is None
    assert result.items[0].effective_outputs == {"data": "csv"}
    assert "existing=csv; missing=none" in result.items[0].warnings
    assert not any("'png'" in reason for reason in result.blocked)
    assert not list((tmp_path / "out").glob("*.png"))


def test_runner_image_only_fails_cleanly_when_backend_import_is_unavailable(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "image_only_backend_missing", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="image only",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    monkeypatch.setattr(builtins, "__import__", _raise_batch_render_import)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert result.degraded_count == 0
    assert result.items[0].status == "failed"
    assert "图片/PDF 导出后端不可用" in result.items[0].message
    assert result.items[0].requested_outputs == {"image": "png"}
    assert result.items[0].effective_outputs == {}
    assert not list((tmp_path / "out").glob("*.png"))
    assert not list((tmp_path / "out").glob(".*.batch-reserve"))


def test_runner_data_only_never_imports_batch_render(tmp_path, monkeypatch):
    fd = _make_fd(tmp_path, "data_only_no_probe", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="data only",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    monkeypatch.setattr(builtins, "__import__", _raise_batch_render_import)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert Path(result.items[0].data_path).is_file()


def test_runner_writer_import_error_rolls_back_data_and_image_set(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "writer_import_error", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="writer import error",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(
            export_data=True,
            export_image=True,
            image_format="png",
            write_manifest=False,
        ),
    )

    def fail_writer(*_args, **_kwargs):
        raise ModuleNotFoundError("writer-time import failure")

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(fail_writer))

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert result.items[0].status == "failed"
    assert result.degraded_count == 0
    assert not list((tmp_path / "out").glob("*.csv"))
    assert not list((tmp_path / "out").glob("*.png"))
    assert not list((tmp_path / "out").glob(".*.batch-stage.*"))
    assert not list((tmp_path / "out").glob(".*.batch-reserve"))


def test_runner_maps_phase3_image_output_to_renderer_options_and_context(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "png", idx=0)
    captured = {}

    def capture_render(payload, path, params=None, *, options=None, context=None,
                       warnings_out=None):
        captured["path"] = Path(path)
        captured["options"] = options
        captured["context"] = context
        Path(path).write_bytes(b"png")
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(capture_render))
    preset = AnalysisPreset.from_current_single(
        name="png",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(
            export_data=False,
            export_image=True,
            image_format="png",
            image_size="custom",
            image_width=2304,
            image_height=1296,
            image_dpi=192,
            image_background="transparent",
            image_line_width=1.5,
            write_manifest=False,
        ),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert Path(result.items[0].image_path).suffix == ".png"
    image_facts = result.items[0].artifact_facts["image"]
    assert image_facts["format"] == "png"
    assert (image_facts["width"], image_facts["height"], image_facts["dpi"]) == (
        2304, 1296, 192,
    )
    options = captured["options"]
    assert (
        options.width_px,
        options.height_px,
        options.dpi,
        options.format,
        options.background,
        options.line_width,
    ) == (
        2304, 1296, 192, "png", "transparent", 1.5,
    )
    context = captured["context"]
    assert context.channel == "sig"
    assert context.method == "fft"
    assert context.task_id == result.items[0].task_id
    assert context.effective_facts["nfft_effective"] == 64


@pytest.mark.parametrize("illegal_format", ("pdf", "svg"))
def test_runner_rejects_new_vector_image_request_before_task_execution(
    tmp_path, illegal_format,
):
    fd = _make_fd(tmp_path, f"illegal_{illegal_format}", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="illegal vector",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(image_format=illegal_format),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert result.items == []
    assert any("image_format must be png" in reason for reason in result.blocked)
    assert not list((tmp_path / "out").glob(f"*.{illegal_format}"))


def test_runner_manifest_records_artifact_checksum_and_effective_facts(tmp_path):
    import hashlib
    import json

    fd = _make_fd(tmp_path, "manifest", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="manifest run",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.manifest_path is not None
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["summary"]["done"] == 1
    assert result.summary == manifest["summary"]
    entry = manifest["entries"][0]
    assert entry["task_id"] == result.items[0].task_id
    assert entry["source"]["identity"] == result.items[0].source_identity
    assert entry["channel"] == "sig"
    assert entry["requested_params"]["nfft"] == 64
    assert entry["effective_facts"]["nfft_effective"] == 64
    artifact = entry["artifacts"]["data"]
    data_path = Path(result.items[0].data_path)
    assert artifact["size"] == data_path.stat().st_size
    assert artifact["sha256"] == hashlib.sha256(data_path.read_bytes()).hexdigest()


def test_runner_manifest_proven_resume_skips_load_compute_and_render(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "resume", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="resume",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    first = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    stale_token = (
        Path(first.items[0].data_path).parent
        / f".{Path(first.items[0].data_path).stem}.batch-reserve"
    )
    stale_token.write_text("simulated crashed writer", encoding="utf-8")
    resume_preset = replace(
        preset,
        outputs=replace(preset.outputs, resume_policy="manifest"),
    )

    def fail_if_computed(*args, **kwargs):
        pytest.fail("manifest-proven task must not compute")

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)
    events = []
    resumed = BatchRunner({0: fd}).run(
        resume_preset,
        tmp_path / "out",
        resume_manifest=first.manifest_path,
        on_event=events.append,
    )

    assert resumed.status == "done"
    assert resumed.items[0].status == "resumed"
    assert resumed.items[0].data_path == first.items[0].data_path
    assert resumed.summary["resumed"] == 1
    assert "task_resumed" in [event.kind for event in events]
    assert "task_started" not in [event.kind for event in events]


def test_runner_auto_resume_prefers_run_store_and_accepts_legacy_root(
    tmp_path, monkeypatch,
):
    """The hidden run store is primary, but old root manifests remain usable."""
    fd = _make_fd(tmp_path, "auto-resume", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="auto resume",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(
            export_data=True, export_image=False, resume_policy="manifest",
        ),
    )
    run_store_dir = tmp_path / "run-store"
    first = BatchRunner({0: fd}).run(preset, run_store_dir)
    assert Path(first.manifest_path).parent == run_store_dir / ".tracelab" / "runs"

    def fail_if_computed(*_args, **_kwargs):
        pytest.fail("auto-resume must use the run-store manifest")

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)
    resumed = BatchRunner({0: fd}).run(preset, run_store_dir)
    assert resumed.items[0].status == "resumed"

    monkeypatch.undo()
    legacy_dir = tmp_path / "legacy-root"
    legacy_first = BatchRunner({0: fd}).run(preset, legacy_dir)
    legacy_manifest = legacy_dir / Path(legacy_first.manifest_path).name
    Path(legacy_first.manifest_path).rename(legacy_manifest)
    assert legacy_manifest.is_file()

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)
    legacy_resumed = BatchRunner({0: fd}).run(preset, legacy_dir)
    assert legacy_resumed.items[0].status == "resumed"


def test_runner_writer_exception_still_finalizes_terminal_manifest(
    tmp_path, monkeypatch,
):
    import json

    fd = _make_fd(tmp_path, "writer_exception", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="writer exception",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    def fail_writer(frame, path):
        raise RuntimeError("simulated writer exception")

    monkeypatch.setattr(
        BatchRunner, "_write_dataframe", staticmethod(fail_writer),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert result.items[0].status == "failed"
    assert result.manifest_path is not None
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["run_status"] == "blocked"
    assert manifest["summary"]["failed"] == 1
    assert not list((tmp_path / "out").glob("*.partial.json"))
    assert not list((tmp_path / "out").glob(".*.batch-stage.*"))


def test_cancel_after_last_writer_finishes_never_publishes_final_artifact(
    tmp_path, monkeypatch,
):
    import json

    fd = _make_fd(tmp_path, "writer_cancel", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="writer cancel",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    token = threading.Event()
    original_write = BatchRunner._write_dataframe

    def write_then_cancel(frame, path):
        result = original_write(frame, path)
        token.set()
        return result

    monkeypatch.setattr(
        BatchRunner, "_write_dataframe", staticmethod(write_then_cancel),
    )

    result = BatchRunner({0: fd}).run(
        preset, tmp_path / "out", cancel_token=token,
    )

    assert result.status == "cancelled"
    assert result.items[0].status == "cancelled"
    assert not list((tmp_path / "out").glob("*.csv"))
    assert not list((tmp_path / "out").glob(".*.batch-stage.*"))
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["run_status"] == "cancelled"
    assert manifest["summary"]["cancelled"] == 1


def test_cancel_during_artifact_checksum_cannot_leave_item_done(
    tmp_path, monkeypatch,
):
    import json
    import mf4_analyzer.batch as batch_module

    fd = _make_fd(tmp_path, "checksum_cancel", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="checksum cancel",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    token = threading.Event()
    original_facts = batch_module.artifact_facts

    def cancel_then_checksum(*args, **kwargs):
        token.set()
        return original_facts(*args, **kwargs)

    monkeypatch.setattr(batch_module, "artifact_facts", cancel_then_checksum)

    result = BatchRunner({0: fd}).run(
        preset, tmp_path / "out", cancel_token=token,
    )

    assert result.status == "cancelled"
    assert result.items[0].status == "cancelled"
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    artifact = manifest["entries"][0]["artifacts"]["data"]
    assert artifact["checksum_status"] == "cancelled"
    assert artifact["sha256"] is None
    assert manifest["summary"]["done"] == 0
    assert manifest["summary"]["cancelled"] == 1


def test_cancel_during_resume_checksum_stops_before_load_or_compute(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch_manifest as manifest_module

    fd = _make_fd(tmp_path, "resume_checksum_cancel", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="resume checksum cancel",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    first = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    resume_preset = replace(
        preset,
        outputs=replace(preset.outputs, resume_policy="manifest"),
    )
    token = threading.Event()
    original_sha256 = manifest_module.sha256_file
    seen_tokens = []

    def cancel_resume_checksum(path, *, cancel_token=None, chunk_size=1024 * 1024):
        seen_tokens.append(cancel_token)
        if cancel_token is token:
            token.set()
            return None
        return original_sha256(
            path, cancel_token=cancel_token, chunk_size=chunk_size,
        )

    def fail_if_computed(*args, **kwargs):
        pytest.fail("cancelled resume checksum must not compute")

    monkeypatch.setattr(manifest_module, "sha256_file", cancel_resume_checksum)
    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)

    result = BatchRunner({0: fd}).run(
        resume_preset,
        tmp_path / "out",
        resume_manifest=first.manifest_path,
        cancel_token=token,
    )

    assert seen_tokens and seen_tokens[0] is token
    assert result.status == "cancelled"
    assert result.items[0].status == "cancelled"


def test_runner_corrupt_resume_artifact_is_recomputed(tmp_path, monkeypatch):
    fd = _make_fd(tmp_path, "resume_corrupt", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="resume corrupt",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    first = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    Path(first.items[0].data_path).write_text("corrupt", encoding="utf-8")
    resume_preset = replace(
        preset,
        outputs=replace(preset.outputs, resume_policy="manifest"),
    )
    calls = {"compute": 0}
    original = BatchRunner._compute_fft_dataframe

    def count_compute(*args, **kwargs):
        calls["compute"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        BatchRunner, "_compute_fft_dataframe", staticmethod(count_compute),
    )

    result = BatchRunner({0: fd}).run(
        resume_preset, tmp_path / "out", resume_manifest=first.manifest_path,
    )

    assert result.status == "done"
    assert result.items[0].status == "done"
    assert calls["compute"] == 1
    assert result.items[0].data_path != first.items[0].data_path


def test_runner_retry_failed_manifest_scopes_only_failed_and_cancelled_tasks(tmp_path):
    fd_done = _make_fd(tmp_path, "retry_done", channels=("sig",), idx=0)
    fd_failed = _make_fd(tmp_path, "retry_failed", channels=("other",), idx=1)
    preset = AnalysisPreset.free_config(
        name="retry failed",
        method="fft",
        target_signals=("sig",),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    preset = replace(
        preset,
        file_ids=(0, 1),
        target_pairs=((0, "sig"), (1, "sig")),
    )
    first = BatchRunner({0: fd_done, 1: fd_failed}).run(
        preset, tmp_path / "out",
    )
    events = []

    retried = BatchRunner({0: fd_done, 1: fd_failed}).run(
        preset,
        tmp_path / "out",
        retry_failed_manifest=first.manifest_path,
        on_event=events.append,
    )

    assert retried.status == "blocked"
    assert [(item.file_id, item.status) for item in retried.items] == [
        (1, "failed"),
    ]
    started = [event for event in events if event.kind == "task_started"]
    assert [(event.file_name, event.signal) for event in started] == [
        (str(fd_failed.filename), "sig"),
    ]


def test_runner_retry_manifest_recipe_change_is_blocked_before_compute(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "retry_recipe", channels=("other",), idx=0)
    preset = AnalysisPreset.from_current_single(
        name="retry recipe",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    first = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    changed = replace(preset, params={"fs": 1024.0, "nfft": 128})

    def fail_if_computed(*args, **kwargs):
        pytest.fail("recipe mismatch must block before compute")

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)
    result = BatchRunner({0: fd}).run(
        changed,
        tmp_path / "out",
        retry_failed_manifest=first.manifest_path,
    )

    assert result.status == "blocked"
    assert "recipe fingerprint" in result.blocked[0]
    assert result.items == []


def test_public_output_preview_reports_counts_without_loading_sources(tmp_path):
    fd = _make_fd(tmp_path, "preview", channels=("sig",), idx=0)
    preset = AnalysisPreset.from_current_single(
        name="preview",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=True),
    )
    runner = BatchRunner({0: fd})

    preview = runner.preview_outputs(preset, tmp_path / "out")

    assert preview.task_count == 1
    assert preview.artifact_count == 2
    assert preview.conflict_count == 0
    assert preview.group_count == 0
    assert preview.data_artifact_count == 1
    assert preview.image_artifact_count == 1
    assert preview.data_conflict_count == 0
    assert preview.image_conflict_count == 0
    assert preview.image_format == "png"
    assert preview.image_width == 1920
    assert preview.image_height == 1080
    assert preview.image_dpi == 144
    assert preview.conflict_policy == "auto_number"


def _two_source_two_channel_preview(
    tmp_path, *, group_by="none", export_data=True, export_image=True,
):
    files = {
        0: _make_fd(tmp_path, "preview_a", channels=("sig", "aux"), idx=0),
        1: _make_fd(tmp_path, "preview_b", channels=("sig", "aux"), idx=1),
    }
    params = (
        {} if group_by == "none"
        else {"render_group_by": group_by, "render_layout": "subplot"}
    )
    preset = AnalysisPreset.free_config(
        name="group preview",
        method="time",
        target_signals=("sig", "aux"),
        params=params,
        outputs=BatchOutput(
            export_data=export_data,
            export_image=export_image,
        ),
    )
    preset = replace(preset, file_ids=(0, 1))
    return BatchRunner(files), preset


@pytest.mark.parametrize(
    (
        "group_by", "export_data", "export_image", "group_count",
        "data_count", "image_count", "artifact_count",
    ),
    (
        ("none", True, True, 0, 4, 4, 8),
        ("source", True, True, 2, 4, 2, 6),
        ("channel", True, True, 2, 4, 2, 6),
        ("source", True, False, 0, 4, 0, 4),
    ),
)
def test_group_aware_preview_reports_exact_artifact_counts(
    tmp_path,
    group_by,
    export_data,
    export_image,
    group_count,
    data_count,
    image_count,
    artifact_count,
):
    runner, preset = _two_source_two_channel_preview(
        tmp_path,
        group_by=group_by,
        export_data=export_data,
        export_image=export_image,
    )

    preview = runner.preview_outputs(preset, tmp_path / "out")

    assert preview.task_count == 4
    assert preview.group_count == group_count
    assert preview.data_artifact_count == data_count
    assert preview.image_artifact_count == image_count
    assert preview.artifact_count == artifact_count
    assert preview.data_conflict_count == 0
    assert preview.image_conflict_count == 0
    assert preview.conflict_count == 0


def test_grouped_preview_uses_task_data_stems_and_group_image_stems(tmp_path):
    from mf4_analyzer.batch_grouping import RenderTask, group_render_tasks

    runner, preset = _two_source_two_channel_preview(
        tmp_path, group_by="source",
    )
    params = normalize_batch_params(preset.params, preset.method)
    tasks = tuple(
        RenderTask(
            source_key,
            channel,
            runner._build_task_identity(
                runner._known_file_data(source_key),
                file_id=source_key,
                channel=channel,
                method=preset.method,
                params=params,
            ),
        )
        for source_key, channel in runner._expand_tasks(
            preset, allow_source_load=False,
        )
    )
    groups = group_render_tasks(tasks, params)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    task_stem = tasks[0].identity.stem
    group_stem = groups[0].identity.stem
    assert task_stem != group_stem

    (output_dir / f"{group_stem}.csv").touch()
    (output_dir / f"{task_stem}.png").touch()
    wrong_stem_preview = runner.preview_outputs(preset, output_dir)

    assert wrong_stem_preview.data_conflict_count == 0
    assert wrong_stem_preview.image_conflict_count == 0
    assert wrong_stem_preview.conflict_count == 0

    (output_dir / f"{task_stem}.csv").touch()
    (output_dir / f"{group_stem}.png").touch()
    correct_stem_preview = runner.preview_outputs(preset, output_dir)

    assert correct_stem_preview.data_conflict_count == 1
    assert correct_stem_preview.image_conflict_count == 1
    assert correct_stem_preview.conflict_count == 2


def test_default_preview_conflicts_remain_task_set_compatible(tmp_path):
    runner, preset = _two_source_two_channel_preview(tmp_path, group_by="none")
    params = normalize_batch_params(preset.params, preset.method)
    source_key, channel = next(
        iter(runner._expand_tasks(preset, allow_source_load=False))
    )
    identity = runner._build_task_identity(
        runner._known_file_data(source_key),
        file_id=source_key,
        channel=channel,
        method=preset.method,
        params=params,
    )
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / f"{identity.stem}.csv").touch()
    (output_dir / f"{identity.stem}.png").touch()

    preview = runner.preview_outputs(preset, output_dir)

    assert preview.data_conflict_count == 1
    assert preview.image_conflict_count == 1
    assert preview.conflict_count == 1


def test_group_preview_never_loads_probes_or_reserves_unresolved_sources(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch as batch_module

    def forbidden(*args, **kwargs):
        pytest.fail("preview must only use unresolved metadata")

    paths = (tmp_path / "a.mf4", tmp_path / "b.mf4")
    preset = AnalysisPreset.free_config(
        name="unresolved preview",
        method="time",
        target_signals=("sig", "aux"),
        params={"render_group_by": "source"},
        outputs=BatchOutput(export_data=True, export_image=True),
    )
    preset = replace(preset, source_paths=paths)
    runner = BatchRunner({}, loader=forbidden)
    monkeypatch.setattr(runner, "_probe_image_backend", forbidden)
    monkeypatch.setattr(batch_module, "reserve_output_paths", forbidden)

    preview = runner.preview_outputs(preset, tmp_path / "out")

    assert preview.task_count == 4
    assert preview.group_count == 2
    assert preview.data_artifact_count == 4
    assert preview.image_artifact_count == 2


@pytest.mark.parametrize(
    "time_range",
    ((1.0, 0.0), (float("nan"), 1.0)),
)
def test_runner_validation_blocks_invalid_time_range_with_field(tmp_path, time_range):
    fd = _make_fd(tmp_path, "invalid_range", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="invalid range",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64, "time_range": time_range},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert "time_range" in result.blocked[0]
    assert not list((tmp_path / "out").glob("*.csv"))


def test_runner_preflight_blocks_when_no_output_is_selected(tmp_path, monkeypatch):
    fd = _make_fd(tmp_path, "no_outputs", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="no outputs",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=False, export_image=False),
    )

    def fail_if_computed(*args, **kwargs):
        pytest.fail("compute must not start after preflight failure")

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert "outputs" in result.blocked[0]
    assert result.manifest_path is not None
    assert Path(result.manifest_path).parent == tmp_path / "out" / ".tracelab" / "runs"
    assert not list((tmp_path / "out").glob("batch-manifest__*.json"))


def test_runner_preflight_blocks_unsupported_data_format(tmp_path, monkeypatch):
    fd = _make_fd(tmp_path, "bad_data_format", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="bad data format",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(
            export_data=True,
            export_image=False,
            data_format="parquet",
        ),
    )

    def fail_if_computed(*args, **kwargs):
        pytest.fail("compute must not start after preflight failure")

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert "data_format" in result.blocked[0]
    assert result.manifest_path is not None
    assert Path(result.manifest_path).parent == tmp_path / "out" / ".tracelab" / "runs"
    assert not list((tmp_path / "out").glob("batch-manifest__*.json"))


def test_runner_preflight_blocks_unknown_window(tmp_path, monkeypatch):
    fd = _make_fd(tmp_path, "bad_window", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="bad window",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64, "window": "rectangular"},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    def fail_if_computed(*args, **kwargs):
        pytest.fail("compute must not start after preflight failure")

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert "window" in result.blocked[0]
    assert result.manifest_path is not None
    assert Path(result.manifest_path).parent == tmp_path / "out" / ".tracelab" / "runs"
    assert not list((tmp_path / "out").glob("batch-manifest__*.json"))


def test_runner_preflight_blocks_invalid_amplitude_definition(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "bad_amplitude_definition", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="bad amplitude definition",
        method="fft",
        signal=(0, "sig"),
        params={
            "fs": 1024.0,
            "nfft": 64,
            "amplitude_definition": "peak-to-peak",
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    def fail_if_computed(*args, **kwargs):
        pytest.fail("compute must not start after preflight failure")

    monkeypatch.setattr(BatchRunner, "_compute_fft_dataframe", fail_if_computed)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert "amplitude_definition" in result.blocked[0]
    assert result.manifest_path is not None
    assert Path(result.manifest_path).parent == tmp_path / "out" / ".tracelab" / "runs"
    assert not list((tmp_path / "out").glob("batch-manifest__*.json"))


def test_runner_records_effective_filter_clamp_warning(tmp_path):
    fd = _make_fd(tmp_path, "filter_warning", idx=0, fs=1000.0)
    preset = AnalysisPreset.from_current_single(
        name="filter warning",
        method="fft",
        signal=(0, "sig"),
        params={
            "fs": 1000.0,
            "nfft": 64,
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 900.0},
            },
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    item = result.items[0]
    assert item.warnings and "钳制" in item.warnings[0]
    assert item.effective_params["filter"]["spec"]["cutoff"] < 500.0


def test_order_time_without_rpm_channel_fails_with_required_error(tmp_path):
    """Manual RPM is removed (design 2026-08-03 D-C1): batch order analysis
    always needs an RPM channel/signal now. No new validation was added for
    this -- the pre-existing ``_rpm_values`` "rpm channel is required" runtime
    check is the backstop, surfacing as a per-item failure."""
    fd = _make_fd(tmp_path, "no_rpm_channel", channels=("sig",), idx=0)
    preset = AnalysisPreset.from_current_single(
        name="no rpm channel",
        method="order_time",
        signal=(0, "sig"),
        params={
            "fs": 1024.0,
            "nfft": 64,
            "samples_per_rev": 64,
            "max_order": 5.0,
            "order_res": 0.5,
            "time_res": 0.1,
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert result.items[0].status == "failed"
    assert "rpm channel is required" in result.items[0].message


def test_order_time_guessed_rpm_channel_is_named_in_item_warning(tmp_path):
    guessed_channel = "MotorSpeedRPM"
    fd = _make_fd(
        tmp_path,
        "guessed_rpm_channel",
        channels=("sig", guessed_channel),
        idx=0,
    )
    preset = AnalysisPreset.from_current_single(
        name="guessed rpm channel",
        method="order_time",
        signal=(0, "sig"),
        params={
            "fs": 1024.0,
            "nfft": 64,
            "samples_per_rev": 64,
            "max_order": 5.0,
            "order_res": 0.5,
            "time_res": 0.1,
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert (
        f"未指定转速通道，已按名称匹配使用 {guessed_channel} —— 请确认"
        in result.items[0].warnings
    )


def test_legacy_manual_rpm_preset_no_longer_bypasses_rpm_channel_requirement(
    tmp_path,
):
    """A recipe saved before manual RPM was removed may still carry raw
    ``rpm_mode="manual"``/``manual_rpm`` in ``preset.params`` (e.g. loaded
    from an old JSON preset without going through normalization first). The
    runner must treat it exactly like a channel-mode preset with no RPM
    source configured, not silently honor the retired manual value."""
    fd = _make_fd(tmp_path, "legacy_manual_rpm", channels=("sig",), idx=0)
    preset = AnalysisPreset.from_current_single(
        name="legacy manual rpm",
        method="order_time",
        signal=(0, "sig"),
        params={
            "fs": 1024.0,
            "nfft": 64,
            "samples_per_rev": 64,
            "max_order": 5.0,
            "order_res": 0.5,
            "time_res": 0.1,
            "rpm_mode": "manual",
            "manual_rpm": 3000.0,
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert result.items[0].status == "failed"
    assert "rpm channel is required" in result.items[0].message


def test_slice_workbook_clamp_warning_uses_finite_coordinate_bounds(
    tmp_path,
):
    from mf4_analyzer.batch import _Spectro2D

    fd = _make_fd(tmp_path, "slice_nan_bounds", channels=("sig",), idx=0)
    spectro = _Spectro2D(
        x=np.asarray([10.0, np.nan, 40.0]),
        y=np.asarray([1.0, 4.0]),
        matrix=np.asarray([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]),
        x_name="time_s",
        y_name="frequency_hz",
    )
    params = {
        "amplitude_mode": "amplitude",
        "slice": {"enabled": True, "axis": "time", "positions": [400.0]},
    }
    warnings_out = []

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        factory = BatchRunner({0: fd})._slice_workbook_factory(
            spectro,
            method="fft_time",
            params=params,
            fact_params={},
            data_extension="xlsx",
            resolution=None,
            fd=fd,
            signal_name="sig",
            unit="",
            warnings_out=warnings_out,
            owns_clamp_warning=True,
        )

    assert factory is not None
    assert not any(item.category is RuntimeWarning for item in caught)
    assert len(warnings_out) == 1
    message = warnings_out[0]
    assert "[10.000, 40.000]" in message
    assert "nan" not in message.casefold()


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_runner_resolves_auto_nfft_only_at_execution(tmp_path, method):
    channels = ("sig",) if method == "fft_time" else ("sig", "rpm")
    fd = _make_fd(tmp_path, f"auto_{method}", channels=channels, idx=0)
    params = {
        "fs": 1024.0,
        "nfft": None,
        "nfft_mode": "auto",
        "t_win_s": 0.25,
        "overlap": 0.5,
    }
    if method == "order_time":
        params.update({
            "samples_per_rev": 64,
            "max_order": 5.0,
            "order_res": 0.5,
            "time_res": 0.1,
        })
    preset = AnalysisPreset.from_current_single(
        name=f"auto {method}",
        method=method,
        signal=(0, "sig"),
        rpm_channel="rpm" if method == "order_time" else "",
        params=params,
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert params["nfft"] is None
    assert result.items[0].effective_params["nfft_effective"] >= 2


def test_runner_uses_preprocessed_signal_fs_and_disables_compute_filter(
    tmp_path, monkeypatch,
):
    fs = 200.0
    t = np.arange(400, dtype=float) / fs
    frame = pd.DataFrame({
        "Time": t,
        "sig": 3.0 + np.sin(2 * np.pi * 10.0 * t),
    })
    fd = FileData(tmp_path / "preprocess.csv", frame, list(frame.columns), {})
    captured = {}

    def capture_fft(signal, effective_fs, params):
        captured["signal"] = np.asarray(signal).copy()
        captured["fs"] = effective_fs
        captured["params"] = params
        return pd.DataFrame({"frequency_hz": [0.0], "amplitude": [1.0]})

    monkeypatch.setattr(
        BatchRunner,
        "_compute_fft_dataframe",
        staticmethod(capture_fft),
    )
    preset = AnalysisPreset.from_current_single(
        name="preprocess integration",
        method="fft",
        signal=(0, "sig"),
        params={
            "nfft": 64,
            "time_preprocess": {
                "scale": 2.0,
                "offset": 5.0,
                "remove_mean": True,
                "sample_mode": "decimate",
                "decimation_factor": 2,
            },
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 9999.0},
            },
        },
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert captured["fs"] == pytest.approx(100.0)
    assert captured["params"]["filter"]["enabled"] is False
    assert abs(float(np.mean(captured["signal"]))) < 1e-2
    effective = result.items[0].effective_params
    assert effective["fs"] == pytest.approx(100.0)
    assert effective["preprocess"]["sampling"]["decimation_factor"] == 2
    assert any("钳制" in warning for warning in result.items[0].warnings)


def test_time_export_uses_pre_filter_and_filtered_preprocess_series(tmp_path):
    from mf4_analyzer.batch_preprocess import preprocess_batch_signal

    fs = 200.0
    t = np.arange(400, dtype=float) / fs
    signal = 3.0 + np.sin(2 * np.pi * 10.0 * t) + 0.3 * np.sin(
        2 * np.pi * 60.0 * t
    )
    frame = pd.DataFrame({"Time": t, "sig": signal})
    fd = FileData(tmp_path / "time_preprocess.csv", frame, list(frame.columns), {})
    params = {
        "time_preprocess": {
            "scale": 2.0,
            "offset": 5.0,
            "remove_mean": True,
            "sample_mode": "decimate",
            "decimation_factor": 2,
        },
        "filter": {
            "enabled": True,
            "spec": {"kind": "low", "order": 4, "cutoff": 20.0},
            "show_original": True,
            "show_filtered": True,
        },
    }
    expected = preprocess_batch_signal(signal, t, fs, params)
    preset = AnalysisPreset.from_current_single(
        name="time preprocess",
        method="time",
        signal=(0, "sig"),
        params=params,
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    exported = pd.read_csv(result.items[0].data_path)
    original = exported[exported["series"] == "original"]["value"].to_numpy()
    filtered = exported[exported["series"] == "filtered"]["value"].to_numpy()
    np.testing.assert_allclose(original, expected.pre_filter_signal, atol=1e-12)
    np.testing.assert_allclose(filtered, expected.signal, atol=1e-12)


def test_time_series_adapter_marks_original_and_filtered_lines_distinctly(tmp_path):
    from mf4_analyzer.batch_preprocess import preprocess_batch_signal

    fs = 100.0
    time = np.arange(100, dtype=float) / fs
    signal = np.sin(2 * np.pi * 5.0 * time)
    frame = pd.DataFrame({"Time": time, "sig": signal})
    fd = FileData(
        tmp_path / "source.csv",
        frame,
        list(frame.columns),
        {"sig": "m/s2"},
    )
    params = {
        "filter": {
            "enabled": True,
            "spec": {"kind": "low", "order": 4, "cutoff": 10.0},
            "show_original": True,
            "show_filtered": True,
        }
    }
    preprocessed = preprocess_batch_signal(signal, time, fs, params)

    series = BatchRunner({0: fd})._build_time_series(
        fd=fd,
        signal_name="sig",
        preprocessed=preprocessed,
        source_label="source.csv",
        params=params,
        panel=0,
    )

    assert [item.linestyle for item in series] == ["-", "--"]
    assert [item.unit for item in series] == ["m/s2", "m/s2"]
    assert all("source.csv" in item.label and "sig" in item.label for item in series)
    assert "original" in series[0].label
    assert "filtered" in series[1].label
    np.testing.assert_allclose(series[0].y, preprocessed.pre_filter_signal)
    np.testing.assert_allclose(series[1].y, preprocessed.signal)


def test_time_channel_x_uses_aligned_values_label_unit_and_absolute_origin(
    tmp_path, monkeypatch,
):
    captured = {}
    fs = 20.0
    time = np.arange(20, dtype=float) / fs
    x_values = 30.0 + np.arange(20, dtype=float) * 0.25
    frame = pd.DataFrame({"Time": time, "angle": x_values, "sig": time**2})
    fd = FileData(
        tmp_path / "channel-x.csv",
        frame,
        list(frame.columns),
        {"angle": "deg", "sig": "V"},
    )

    def capture_image(
        payload, path, params=None, *, options=None, context=None,
        warnings_out=None,
    ):
        captured["payload"] = payload
        Path(path).write_bytes(b"image")
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(capture_image))
    preset = AnalysisPreset.from_current_single(
        name="channel x",
        method="time",
        signal=(0, "sig"),
        params={"x_source": "channel", "x_channel": "angle"},
        outputs=BatchOutput(
            export_data=False,
            export_image=True,
            write_manifest=False,
        ),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    from mf4_analyzer.batch_render import BatchTimeFigureSpec

    assert result.status == "done"
    kind, spec = captured["payload"]
    assert kind == "time" and isinstance(spec, BatchTimeFigureSpec)
    assert spec.x_source == "channel"
    assert spec.x_origin == "absolute"
    assert spec.x_label == "angle (deg)"
    assert spec.series[0].x_unit == "deg"
    np.testing.assert_allclose(spec.series[0].x, x_values)


def test_time_statistics_diagnostic_is_a_nonblocking_group_warning(
    tmp_path, monkeypatch,
):
    """An ambiguous path still exports the PNG and records its exact reason."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    x_values = np.array([0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 2, 1, 0], dtype=float)
    frame = pd.DataFrame({
        "Time": np.arange(x_values.size, dtype=float) / 10.0,
        "angle": x_values,
        "sig": np.linspace(-1.0, 1.0, x_values.size),
    })
    fd = FileData(
        tmp_path / "statistics-diagnostic.csv", frame, list(frame.columns),
        {"angle": "deg", "sig": "V"},
    )
    captured = {}

    def write_image(payload, path, params=None, *, options=None, context=None,
                    warnings_out=None):
        captured["spec"] = payload[1]
        Path(path).write_bytes(b"png")
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(write_image))
    preset = AnalysisPreset.from_current_single(
        name="statistics diagnostic", method="time", signal=(0, "sig"),
        params={
            "render_group_by": "source", "x_source": "channel",
            "x_channel": "angle",
            "chart_statistics": {
                "enabled": True, "range_mode": "full",
                "x_min": None, "x_max": None, "metrics": ["max", "min"],
            },
        },
        outputs=BatchOutput(export_data=True, export_image=True),
    )

    runner = BatchRunner({0: fd})
    preview_plan = runner.preview_outputs(preset, tmp_path / "formal")
    preview = runner.preview_group(
        preset, preview_plan.representative_group.group_id, tmp_path / "preview",
    )
    result = runner.run(preset, tmp_path / "out")

    manifest = load_batch_manifest(result.manifest_path)
    group = manifest["render_groups"][0]
    assert result.status == "done"
    assert result.items[0].status == "done"
    assert Path(result.items[0].data_path).is_file()
    diagnostic = captured["spec"].diagnostics[0]
    expected_warning = f"{diagnostic.message} {diagnostic.suggestion}".strip()
    assert preview.status == "done"
    assert preview.warnings == (expected_warning,)
    assert not list((tmp_path / "preview").glob("batch-manifest__*.json"))
    assert not (tmp_path / "preview" / ".tracelab").exists()
    assert diagnostic.code == "chart_statistics.multiple_x_reversals"
    assert diagnostic.suggestion
    assert group["status"] == "done"
    assert group["warnings"] == [expected_warning]
    assert group["effective_facts"]["chart_statistics"] == {
        "config": {
            "enabled": True, "range_mode": "full",
            "x_min": None, "x_max": None, "metrics": ["max", "min"],
        },
        "row_count": 0,
        "rows": [],
        "diagnostics": [{
            "code": "chart_statistics.multiple_x_reversals", "panel": 0,
            "message": "当前统计区间识别到 4 条有效 X 路径，无法确定唯一升程/回程。",
            "suggestion": "请缩小统计区间或拆分数据后重新运行。",
        }],
    }
    assert expected_warning in result.warnings


def test_run_result_warnings_include_render_group_diagnostics_without_item_copy():
    """F5: run-level aggregation must scan render_groups, not only item.warnings."""
    from mf4_analyzer.batch import BatchItemResult, RenderGroupResult

    class _Reporter:
        def __init__(self):
            self.manifest_errors = []

        def emit(self, event):
            return None

    diagnostic = (
        "当前统计区间识别到 4 条有效 X 路径，无法确定唯一升程/回程。 "
        "请缩小统计区间或拆分数据后重新运行。"
    )
    result = BatchRunner({})._finish_result(
        "done",
        reporter=_Reporter(),
        recorder=None,
        run_migration_warnings=(),
        items=[
            BatchItemResult(
                method="time", file_id=0, file_name="a.csv", signal="sig",
                status="done",
            ),
        ],
        render_groups=[
            RenderGroupResult(
                group_id="g1", status="done", warnings=[diagnostic],
            ),
        ],
    )
    assert diagnostic in result.warnings


def test_time_statistics_manifest_summarizes_normal_rows(tmp_path, monkeypatch):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    x_values = np.arange(5, dtype=float)
    frame = pd.DataFrame({
        "Time": x_values / 10.0,
        "angle": x_values,
        "sig": np.array([2.0, -1.0, 4.0, 0.0, 1.0]),
    })
    fd = FileData(
        tmp_path / "statistics-rows.csv", frame, list(frame.columns),
        {"angle": "deg", "sig": "V"},
    )
    monkeypatch.setattr(
        BatchRunner, "_write_image",
        staticmethod(lambda _payload, path, **_kwargs: Path(path).write_bytes(b"png")),
    )
    preset = AnalysisPreset.from_current_single(
        name="statistics rows", method="time", signal=(0, "sig"),
        params={
            "render_group_by": "source", "x_source": "channel",
            "x_channel": "angle",
            "chart_statistics": {
                "enabled": True, "range_mode": "custom",
                "x_min": 1.0, "x_max": 3.0, "metrics": ["mean", "max"],
            },
        },
        outputs=BatchOutput(export_data=False, export_image=True),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    facts = load_batch_manifest(result.manifest_path)["render_groups"][0][
        "effective_facts"
    ]["chart_statistics"]
    assert result.status == "done"
    assert facts["diagnostics"] == []
    assert facts["config"]["metrics"] == ["max", "mean"]
    assert facts["rows"] == [{
        "series_key": result.items[0].task_id + ":value",
        "panel": 0, "branch": "全程", "sample_count": 3,
        "minimum": -1.0, "maximum": 4.0, "mean": 1.0,
    }]


def test_noisy_custom_x_statistics_match_between_preview_run_and_manifest(
    tmp_path, monkeypatch,
):
    """The shared producer keeps a noisy physical cycle out of the ERROR path."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    forward = np.linspace(-83.0, 83.0, 2001)
    backward = np.linspace(83.0, -83.0, 2001)[1:]
    x_values = np.concatenate((forward, backward))
    x_values += np.resize(
        np.asarray((0.20, 0.10, 0.0, -0.10, -0.20, -0.10, 0.0, 0.10)),
        x_values.size,
    )
    frame = pd.DataFrame({
        "Time": np.arange(x_values.size, dtype=float) / 10.0,
        "angle": x_values,
        "sig": np.arange(x_values.size, dtype=float),
    })
    fd = FileData(
        tmp_path / "statistics-noisy-cycle.csv", frame, list(frame.columns),
        {"angle": "deg", "sig": "V"},
    )
    captured = []

    def write_image(payload, path, **_kwargs):
        captured.append(payload[1])
        Path(path).write_bytes(b"png")
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(write_image))
    preset = AnalysisPreset.from_current_single(
        name="statistics noisy cycle", method="time", signal=(0, "sig"),
        params={
            "render_group_by": "source", "x_source": "channel", "x_channel": "angle",
            "chart_statistics": {
                "enabled": True, "range_mode": "custom",
                "x_min": -20.0, "x_max": 20.0, "metrics": ["max", "min"],
            },
        },
        outputs=BatchOutput(export_data=False, export_image=True),
    )

    runner = BatchRunner({0: fd})
    preview_plan = runner.preview_outputs(preset, tmp_path / "formal")
    preview = runner.preview_group(
        preset, preview_plan.representative_group.group_id, tmp_path / "preview",
    )
    result = runner.run(preset, tmp_path / "out")

    facts = load_batch_manifest(result.manifest_path)["render_groups"][0][
        "effective_facts"
    ]["chart_statistics"]
    assert preview.status == result.status == "done"
    assert preview.warnings == ()
    assert len(captured) == 2
    assert [row.direction for row in captured[0].statistics] == ["X↑", "X↓"]
    assert [row.direction for row in captured[1].statistics] == ["X↑", "X↓"]
    assert facts["diagnostics"] == []
    assert [row["branch"] for row in facts["rows"]] == ["路径 1 · X↑", "路径 2 · X↓"]


def test_statistics_diagnostic_does_not_stop_the_next_render_group(
    tmp_path, monkeypatch,
):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    def make_file(name, angle):
        frame = pd.DataFrame({
            "Time": np.arange(len(angle), dtype=float) / 10.0,
            "angle": angle,
            "sig": np.linspace(-1.0, 1.0, len(angle)),
        })
        return FileData(
            tmp_path / f"{name}.csv", frame, list(frame.columns),
            {"angle": "deg", "sig": "V"},
        )

    ambiguous = make_file(
        "ambiguous",
        np.array([0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 2, 1, 0], dtype=float),
    )
    monotonic = make_file("monotonic", np.arange(8, dtype=float))
    monkeypatch.setattr(
        BatchRunner, "_write_image",
        staticmethod(lambda _payload, path, **_kwargs: Path(path).write_bytes(b"png")),
    )
    preset = AnalysisPreset.free_config(
        name="statistics continue", method="time", target_signals=("sig",),
        params={
            "render_group_by": "source", "x_source": "channel",
            "x_channel": "angle",
            "chart_statistics": {
                "enabled": True, "range_mode": "full",
                "x_min": None, "x_max": None, "metrics": ["max", "min"],
            },
        },
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    preset = replace(preset, file_ids=(0, 1))

    result = BatchRunner({0: ambiguous, 1: monotonic}).run(
        preset, tmp_path / "out",
    )

    groups = load_batch_manifest(result.manifest_path)["render_groups"]
    diagnostic = next(group for group in groups if group["warnings"])
    normal = next(group for group in groups if not group["warnings"])
    assert result.status == "done"
    assert len(list((tmp_path / "out").glob("*.png"))) == 2
    assert diagnostic["status"] == normal["status"] == "done"
    assert len(diagnostic["warnings"]) == 1
    assert "有效 X 路径" in diagnostic["warnings"][0]
    assert "缩小统计区间" in diagnostic["warnings"][0]
    assert "chart_statistics.multiple_x_reversals" not in diagnostic["warnings"]
    assert normal["effective_facts"]["chart_statistics"]["row_count"] == 1


def test_time_channel_x_missing_from_source_fails_task_without_publication(tmp_path):
    fd = _make_fd(tmp_path, "missing_x", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="missing x",
        method="time",
        signal=(0, "sig"),
        params={"x_source": "channel", "x_channel": "absent"},
        outputs=BatchOutput(
            export_data=True,
            export_image=True,
            write_manifest=False,
        ),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert result.items[0].status == "failed"
    assert "missing X channel: absent" in result.items[0].message
    assert not list((tmp_path / "out").glob("*"))


def test_default_time_image_uses_single_task_figure_spec(tmp_path, monkeypatch):
    captured = {}
    fd = _make_fd(tmp_path, "default_spec", idx=0)
    fd.channel_units["sig"] = "V"

    def capture_image(
        payload, path, params=None, *, options=None, context=None,
        warnings_out=None,
    ):
        captured["payload"] = payload
        Path(path).write_bytes(b"image")
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(capture_image))
    preset = AnalysisPreset.from_current_single(
        name="default spec",
        method="time",
        signal=(0, "sig"),
        params={},
        outputs=BatchOutput(
            export_data=True,
            export_image=True,
            write_manifest=False,
        ),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    from mf4_analyzer.batch_render import BatchTimeFigureSpec

    assert result.status == "done"
    kind, spec = captured["payload"]
    assert kind == "time" and isinstance(spec, BatchTimeFigureSpec)
    assert spec.layout == "overlay"
    assert spec.x_source == "time"
    assert spec.x_origin == "zero"
    assert spec.x_label == "Time (s)"
    assert spec.panel_titles == (fd.filename,)
    assert len(spec.series) == 1
    assert spec.series[0].label.endswith("sig")
    assert spec.series[0].unit == "V"
    assert spec.series[0].linestyle == "-"


def test_time_render_retry_discards_failed_attempt_warnings(tmp_path, monkeypatch):
    import mf4_analyzer.batch as batch_module
    from mf4_analyzer.batch_output import OutputPublishRace

    fd = _make_fd(tmp_path, "warning_retry", idx=0)
    attempts = {"render": 0, "publish": 0}
    real_atomic_write_set = batch_module.atomic_write_set

    def render_with_attempt_warning(
        payload, path, params=None, *, options=None, context=None,
        warnings_out=None,
    ):
        attempts["render"] += 1
        warnings_out.append(f"render-attempt-{attempts['render']}")
        Path(path).write_bytes(b"image")
        return Path(path)

    def collide_after_first_render(reservation, writers):
        attempts["publish"] += 1
        if attempts["publish"] == 1:
            for extension, writer in writers.items():
                writer(tmp_path / f"failed-attempt.{extension}")
            raise OutputPublishRace("simulated race after render")
        return real_atomic_write_set(reservation, writers)

    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(render_with_attempt_warning),
    )
    monkeypatch.setattr(batch_module, "atomic_write_set", collide_after_first_render)
    preset = AnalysisPreset.from_current_single(
        name="retry warnings",
        method="time",
        signal=(0, "sig"),
        params={},
        outputs=BatchOutput(
            export_data=False,
            export_image=True,
            write_manifest=False,
        ),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert attempts == {"render": 2, "publish": 2}
    assert "render-attempt-1" not in result.items[0].warnings
    assert result.items[0].warnings.count("render-attempt-2") == 1


def test_cancel_after_compute_emits_one_terminal_and_writes_nothing(
    tmp_path, monkeypatch,
):
    fd = _make_fd(tmp_path, "cancel_compute", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="cancel compute",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(export_data=True, export_image=True),
    )
    token = threading.Event()
    original = BatchRunner._compute_fft_dataframe

    def compute_then_cancel(sig, fs, params):
        result = original(sig, fs, params)
        token.set()
        return result

    monkeypatch.setattr(
        BatchRunner, "_compute_fft_dataframe", staticmethod(compute_then_cancel),
    )
    events = []

    result = BatchRunner({0: fd}).run(
        preset, tmp_path / "out", on_event=events.append, cancel_token=token,
    )

    terminals = [event.kind for event in events if event.kind in {
        "task_done", "task_failed", "task_cancelled",
    }]
    assert result.status == "cancelled"
    assert terminals == ["task_cancelled"]
    assert [event.kind for event in events].count("task_started") == 1
    assert [event.kind for event in events].count("run_finished") == 1
    assert result.manifest_path is not None
    assert Path(result.manifest_path).parent == tmp_path / "out" / ".tracelab" / "runs"
    assert not list((tmp_path / "out").glob("*.png"))
    assert not list((tmp_path / "out").glob("*.csv"))
    assert result.summary["cancelled"] == 1


def _task6_grouped_time_preset(
    *, group_by="source", layout="overlay", export_data=True,
    export_image=True, write_manifest=True,
):
    return AnalysisPreset.free_config(
        name="task 6 grouped time",
        method="time",
        target_signals=("sig", "aux"),
        params={"render_group_by": group_by, "render_layout": layout},
        outputs=BatchOutput(
            export_data=export_data,
            export_image=export_image,
            write_manifest=write_manifest,
        ),
    )


def _task6_fake_image(
    payload, path, params=None, *, options=None, context=None,
    warnings_out=None,
):
    Path(path).write_bytes(b"group-image")
    return Path(path)


def _capture_group_qt_image(
    captured, payload, path, params=None, *, options=None, context=None,
    warnings_out=None,
):
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene
    from mf4_analyzer.batch_render_qt._export import render_scene_image, save_png
    from mf4_analyzer.batch_render_qt._page import render_metadata

    captured.update(
        payload=payload, params=params, options=options, context=context,
    )
    scene = build_batch_scene(
        payload, params=params, options=options, context=context,
        warnings_out=warnings_out,
    )
    try:
        captured["scene_text"] = "\n".join(scene.texts())
        image = render_scene_image(
            scene, metadata=render_metadata(context),
        )
        return save_png(image, path)
    finally:
        scene.close()


def _assert_group_qt_text_and_metadata(
    captured, target: Path, *, absent: tuple[str, ...], present: tuple[str, ...] = (),
):
    from PyQt5.QtGui import QImage

    loaded = QImage(str(target))
    assert not loaded.isNull()
    scene_text = captured["scene_text"]
    metadata_title = loaded.text("Title")
    for token in absent:
        assert token not in scene_text
        assert token not in metadata_title
    for token in present:
        assert token in scene_text
        assert token in metadata_title


def test_source_group_producer_uses_safe_display_name_and_channel_panels(
    qapp, tmp_path, monkeypatch,
):
    captured = {}
    fd = _make_fd(
        tmp_path, "source_group_display", channels=("sig", "aux"), idx=0,
    )
    preset = _task6_grouped_time_preset(
        group_by="source", layout="subplot", export_data=False,
    )

    def capture(payload, path, params=None, *, options=None, context=None,
                warnings_out=None):
        return _capture_group_qt_image(
            captured, payload, path, params=params, options=options,
            context=context, warnings_out=warnings_out,
        )

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(capture))

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    _kind, spec = captured["payload"]
    context = captured["context"]
    assert spec.panel_titles == ("aux", "sig")
    assert context.source_display_name == Path(fd.filepath).name
    assert context.group == ""
    assert context.channel == ""
    assert str(Path(fd.filepath).parent) not in context.source_display_name
    assert not context.source_display_name.startswith("[")
    from mf4_analyzer.batch_grouping import _source_group_key

    item = result.items[0]
    raw_group_key = _source_group_key(
        item.source_identity, item.group_identity,
    )
    from mf4_analyzer.batch_manifest import load_batch_manifest

    image_path = Path(
        load_batch_manifest(result.manifest_path)["render_groups"][0]
        ["artifact"]["path"]
    )
    _assert_group_qt_text_and_metadata(
        captured,
        image_path,
        absent=(
            raw_group_key,
            str(Path(fd.filepath).resolve()),
            str(Path(fd.filepath).parent.resolve()),
        ),
    )


def test_channel_group_producer_preserves_channel_and_uses_file_panels(
    qapp, tmp_path, monkeypatch,
):
    captured = {}
    channel = 'acc[front]"raw'
    first = _make_fd(tmp_path, "first_channel", channels=(channel,), idx=0)
    second = _make_fd(tmp_path, "second_channel", channels=(channel,), idx=1)
    preset = AnalysisPreset.free_config(
        name="channel display",
        method="time",
        target_signals=(channel,),
        params={"render_group_by": "channel", "render_layout": "subplot"},
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    preset = replace(preset, file_ids=(0, 1))

    def capture(payload, path, params=None, *, options=None, context=None,
                warnings_out=None):
        return _capture_group_qt_image(
            captured, payload, path, params=params, options=options,
            context=context, warnings_out=warnings_out,
        )

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(capture))

    result = BatchRunner({0: first, 1: second}).run(preset, tmp_path / "out")

    assert result.status == "done"
    _kind, spec = captured["payload"]
    context = captured["context"]
    assert spec.panel_titles == (first.filename, second.filename)
    assert context.source_display_name == channel
    assert context.group == ""
    assert context.channel == ""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    image_path = Path(
        load_batch_manifest(result.manifest_path)["render_groups"][0]
        ["artifact"]["path"]
    )
    _assert_group_qt_text_and_metadata(
        captured,
        image_path,
        absent=(
            str(Path(first.filepath).resolve()),
            str(Path(second.filepath).resolve()),
            str(Path(first.filepath).parent.resolve()),
        ),
        present=(channel,),
    )


def test_lazy_logical_groups_use_descriptor_identity_for_preview_and_run(
    tmp_path, monkeypatch,
):
    """Catch unresolved planning diverging from loaded logical-group identity."""
    from mf4_analyzer.batch_grouping import RenderTask, group_render_tasks
    from mf4_analyzer.batch_manifest import load_batch_manifest
    from mf4_analyzer.io.source_adapters import LoadedSource, SourceDescriptor

    physical_path = tmp_path / "logical-groups.hdf"
    physical_path.write_bytes(b"logical container")
    sources = []
    for index, (source_id, group_id) in enumerate((
        ("logical:left", "raster:left"),
        ("logical:right", "raster:right"),
    )):
        time = np.arange(32, dtype=float) / 32.0
        frame = pd.DataFrame({
            "Time": time,
            "sig": np.sin(2.0 * np.pi * (index + 1) * time),
        })
        file_data = FileData(
            physical_path,
            frame,
            list(frame.columns),
            {},
            idx=index,
            fs=32.0,
            label_suffix="same-display-suffix",
        )
        file_data.source_metadata.update({
            "source_id": source_id,
            "group_id": group_id,
        })
        sources.append(LoadedSource(
            source_id=source_id,
            source_path=str(physical_path),
            group_id=group_id,
            display_name=f"logical-{index}",
            file_data=file_data,
            metadata={"group_id": group_id},
        ))

    class Registry:
        probe_cost = "metadata"

        def __init__(self):
            self.probe_calls = []
            self.load_calls = []

        def probe_sources(self, path, *, context=None):
            self.probe_calls.append(str(path))
            return tuple(SourceDescriptor(
                source_id=source.source_id,
                source_path=str(path),
                group_id=source.group_id,
                display_name=source.display_name,
                channel_names=("sig",),
                units={},
                fs=32.0,
                metadata={"probe_cost": "metadata"},
            ) for source in sources)

        def load_sources(self, path, *, context=None):
            self.load_calls.append(str(path))
            return tuple(sources)

    preset = AnalysisPreset.free_config(
        name="logical descriptor groups",
        method="time",
        target_signals=("sig",),
        params={"render_group_by": "source", "render_layout": "overlay"},
        outputs=BatchOutput(export_data=True, export_image=True),
    )
    preset = replace(
        preset,
        source_ids=tuple(source.source_id for source in sources),
        source_paths=(str(physical_path), str(physical_path)),
    )
    preview_registry = Registry()
    preview_runner = BatchRunner({}, source_registry=preview_registry)
    params = normalize_batch_params(preset.params, preset.method)
    expected_tasks = tuple(RenderTask(
        source.source_id,
        "sig",
        preview_runner._build_task_identity(
            source.file_data,
            file_id=source.source_id,
            channel="sig",
            method="time",
            params=params,
        ),
    ) for source in sources)
    expected_groups = group_render_tasks(expected_tasks, params)
    subset_registry = Registry()
    subset_runner = BatchRunner({}, source_registry=subset_registry)
    left_preset = replace(
        preset,
        source_ids=(sources[0].source_id,),
        source_paths=(str(physical_path),),
    )
    subset_runner.preview_outputs(left_preset, tmp_path / "left-preview")
    right_preview_dir = tmp_path / "right-preview"
    right_preview_dir.mkdir()
    (right_preview_dir / f"{expected_tasks[1].identity.stem}.csv").touch()
    (right_preview_dir / f"{expected_groups[1].identity.stem}.png").touch()
    right_preset = replace(
        preset,
        source_ids=(sources[1].source_id,),
        source_paths=(str(physical_path),),
    )

    right_preview = subset_runner.preview_outputs(
        right_preset, right_preview_dir,
    )

    assert subset_registry.load_calls == []
    assert subset_registry.probe_calls == [str(physical_path)]
    assert right_preview.data_conflict_count == 1
    assert right_preview.image_conflict_count == 1
    preview_dir = tmp_path / "preview"
    preview_dir.mkdir()
    for task in expected_tasks:
        (preview_dir / f"{task.identity.stem}.csv").touch()
    for group in expected_groups:
        (preview_dir / f"{group.identity.stem}.png").touch()

    preview = preview_runner.preview_outputs(preset, preview_dir)

    assert preview_registry.load_calls == []
    assert preview_registry.probe_calls == [str(physical_path)]
    assert preview.data_conflict_count == 2
    assert preview.image_conflict_count == 2
    assert preview.conflict_count == 4
    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(_task6_fake_image),
    )

    run_registry = Registry()
    result = BatchRunner({}, source_registry=run_registry).run(
        preset, tmp_path / "run",
    )

    manifest = load_batch_manifest(result.manifest_path)
    expected_task_ids = {
        task.source_key: task.identity.task_id for task in expected_tasks
    }
    entry_task_ids = {
        entry["source_id"]: entry["task_id"] for entry in manifest["entries"]
    }
    member_task_ids = {
        member["task_id"]
        for group in manifest["render_groups"]
        for member in group["members"]
    }
    assert result.status == "done"
    assert run_registry.probe_calls == [str(physical_path)]
    assert run_registry.load_calls == [str(physical_path)]
    assert {item.group_identity for item in result.items} == {
        "raster:left", "raster:right",
    }
    assert entry_task_ids == expected_task_ids
    assert member_task_ids == set(entry_task_ids.values())
    assert {
        group["group_id"] for group in manifest["render_groups"]
    } == {group.identity.group_id for group in expected_groups}


def test_full_cost_hdf_preview_never_loads_and_run_keeps_unresolved_identity(
    tmp_path, monkeypatch,
):
    """Catch UI preview decoding a full-cost production source."""
    from types import SimpleNamespace

    from mf4_analyzer.batch_grouping import RenderTask, group_render_tasks
    from mf4_analyzer.batch_manifest import load_batch_manifest
    from mf4_analyzer.batch_output import build_task_output_identity
    from mf4_analyzer.io.loader import DataLoader
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry

    physical_path = tmp_path / "full-cost-groups.hdf"
    physical_path.write_bytes(b"full-cost container")
    groups = []
    for index, factor in enumerate((1, 2)):
        time = np.arange(32, dtype=float) / 32.0 + index
        frame = pd.DataFrame({
            "Time": time,
            "sig": np.sin(2.0 * np.pi * factor * time),
        })
        groups.append({
            "data": frame,
            "channels": ["Time", "sig"],
            "units": {"sig": "V"},
            "channel_metadata": {
                "sig": {"unit": "V", "raster_factor": factor},
            },
            "source_metadata": {"source_kind": "hdf"},
            "label_suffix": "same-display-suffix",
        })
    load_calls = []

    def load_hdf(path):
        load_calls.append(str(path))
        return groups

    monkeypatch.setattr(DataLoader, "load_hdf", staticmethod(load_hdf))
    registry = SourceAdapterRegistry.default()
    loaded = registry.load_sources(physical_path)
    load_calls.clear()
    preset = AnalysisPreset.free_config(
        name="full-cost unresolved groups",
        method="time",
        target_signals=("sig",),
        params={"render_group_by": "source", "render_layout": "overlay"},
        outputs=BatchOutput(export_data=True, export_image=True),
    )
    preset = replace(
        preset,
        source_ids=tuple(source.source_id for source in loaded),
        source_paths=(str(physical_path), str(physical_path)),
    )
    params = normalize_batch_params(preset.params, preset.method)
    expected_tasks = tuple(RenderTask(
        source.source_id,
        "sig",
        build_task_output_identity(
            SimpleNamespace(
                filepath=physical_path,
                label_suffix=f"unresolved-source:{source.source_id}",
                source_metadata={},
            ),
            file_id=source.source_id,
            channel="sig",
            method="time",
            params=params,
        ),
    ) for source in loaded)
    expected_groups = group_render_tasks(expected_tasks, params)
    preview_dir = tmp_path / "full-cost-preview"
    preview_dir.mkdir()
    for task in expected_tasks:
        (preview_dir / f"{task.identity.stem}.csv").touch()
    for group in expected_groups:
        (preview_dir / f"{group.identity.stem}.png").touch()

    preview = BatchRunner({}, source_registry=registry).preview_outputs(
        preset, preview_dir,
    )

    assert load_calls == []
    assert preview.data_conflict_count == 2
    assert preview.image_conflict_count == 2
    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(_task6_fake_image),
    )

    result = BatchRunner({}, source_registry=registry).run(
        preset, tmp_path / "full-cost-run",
    )

    manifest = load_batch_manifest(result.manifest_path)
    entry_ids = {entry["task_id"] for entry in manifest["entries"]}
    member_ids = {
        member["task_id"]
        for group in manifest["render_groups"]
        for member in group["members"]
    }
    assert result.status == "done"
    assert load_calls == [str(physical_path)]
    assert {item.group_identity for item in result.items} == {
        f"unresolved-source:{source.source_id}" for source in loaded
    }
    assert {item.task_id for item in result.items} == {
        task.identity.task_id for task in expected_tasks
    }
    assert member_ids == entry_ids


def test_representative_preview_renders_only_first_group_to_private_png(
    qapp, tmp_path,
):
    """Preview must use formal rendering without publishing run artifacts."""
    fd = _make_fd(tmp_path, "representative", channels=("sig", "aux"), idx=0)
    preset = AnalysisPreset.free_config(
        name="representative preview",
        method="time",
        target_signals=("sig", "aux"),
        params={"render_group_by": "none"},
        outputs=BatchOutput(
            export_data=True, export_image=True,
            image_width=960, image_height=540, image_dpi=144,
        ),
    )
    preset = replace(preset, file_ids=(0,))
    runner = BatchRunner({0: fd})
    formal_dir = tmp_path / "formal-output"
    plan = runner.preview_outputs(preset, formal_dir)
    group = plan.representative_group

    assert group is not None
    assert group.ordinal == 1
    assert group.total_groups == 2
    assert group.member_count == 1
    assert group.required_source_count == 1
    assert not formal_dir.exists()

    private_dir = tmp_path / "private-preview"
    result = runner.preview_group(preset, group.group_id, private_dir)

    assert result.status == "done"
    assert result.group_id == group.group_id
    assert Path(result.image_path).name == f"{group.planned_stem}.png"
    assert Path(result.image_path).is_file()
    assert not list(private_dir.glob("*.csv"))
    assert not list(private_dir.glob("*.xlsx"))
    assert not list(private_dir.glob("batch-manifest__*.json"))
    assert not (private_dir / ".tracelab").exists()
    assert not formal_dir.exists()


@pytest.mark.parametrize("render_group_by", ("none", "source", "channel"))
def test_preview_group_resolves_image_path_for_every_group_mode(
    qapp, tmp_path, render_group_by,
):
    """Regression: grouped renders (source/channel) must resolve an image_path
    just like render_group_by="none" does.

    Before the fix, ``preview_group()`` only ever read ``image_path`` off
    ``result.items``, which grouped-render task results never populate (the
    group PNG path lives solely on ``RenderGroupResult``). That made the
    preview button silently fail for "source" and "channel" grouping even
    though the PNG was rendered to disk.
    """
    fd = _make_fd(tmp_path, "representative", channels=("sig", "aux"), idx=0)
    preset = AnalysisPreset.free_config(
        name="representative preview",
        method="time",
        target_signals=("sig", "aux"),
        params={"render_group_by": render_group_by},
        outputs=BatchOutput(
            export_data=False, export_image=True,
            image_width=960, image_height=540, image_dpi=144,
        ),
    )
    preset = replace(preset, file_ids=(0,))
    runner = BatchRunner({0: fd})
    formal_dir = tmp_path / "formal-output"
    plan = runner.preview_outputs(preset, formal_dir)
    group = plan.representative_group
    assert group is not None

    private_dir = tmp_path / f"private-preview-{render_group_by}"
    result = runner.preview_group(preset, group.group_id, private_dir)

    assert result.status == "done"
    assert result.group_id == group.group_id
    assert result.image_path
    assert Path(result.image_path).is_file()


def test_metadata_probe_unavailable_is_preview_only_fallback(
    tmp_path,
):
    """A disappearing metadata source must not escape the Qt preview path."""
    from mf4_analyzer.io.source_adapters import SourceUnavailableError

    physical_path = tmp_path / "missing-after-ui-probe.mf4"
    source_id = "mdf:missing:root"

    class Registry:
        probe_cost = "metadata"

        def __init__(self):
            self.probe_calls = []
            self.load_calls = []

        def probe_sources(self, path, *, context=None):
            self.probe_calls.append(str(path))
            raise SourceUnavailableError("metadata source disappeared")

        def load_sources(self, path, *, context=None):
            self.load_calls.append(str(path))
            raise OSError("source disappeared before execution")

    preset = AnalysisPreset.free_config(
        name="missing metadata source",
        method="time",
        target_signals=("sig",),
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    preset = replace(
        preset,
        source_ids=(source_id,),
        source_paths=(str(physical_path),),
    )
    registry = Registry()
    runner = BatchRunner({}, source_registry=registry)
    runner._register_source_locator(source_id, physical_path)
    params = normalize_batch_params(preset.params, preset.method)
    expected = runner._build_unresolved_task_identity(
        source_id,
        channel="sig",
        method="time",
        params=params,
    )
    preview_dir = tmp_path / "preview"
    preview_dir.mkdir()
    existing = preview_dir / f"{expected.stem}.csv"
    existing.write_text("existing", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in preview_dir.iterdir()}

    first = runner.preview_outputs(preset, preview_dir)
    second = runner.preview_outputs(preset, preview_dir)

    assert first == second
    assert first.task_count == 1
    assert first.data_conflict_count == 1
    assert {path.name: path.read_bytes() for path in preview_dir.iterdir()} == before
    assert registry.probe_calls == [str(physical_path)]
    assert runner._source_group_identity_hints.get(source_id) is None

    result = runner.run(preset, tmp_path / "run")

    assert registry.load_calls == [str(physical_path)]
    assert result.status == "blocked"
    assert len(result.items) == 1
    assert result.items[0].status == "failed"
    assert result.items[0].task_id == expected.task_id
    assert "source disappeared before execution" in result.items[0].message
    assert not list((tmp_path / "run").glob("*.csv"))


def test_metadata_probe_programming_error_is_not_hidden(tmp_path):
    class Registry:
        probe_cost = "metadata"

        @staticmethod
        def probe_sources(path, *, context=None):
            raise RuntimeError("descriptor implementation bug")

    preset = AnalysisPreset.free_config(
        name="broken metadata adapter",
        method="time",
        target_signals=("sig",),
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    preset = replace(
        preset,
        source_ids=("broken:root",),
        source_paths=(str(tmp_path / "broken.mf4"),),
    )

    with pytest.raises(RuntimeError, match="descriptor implementation bug"):
        BatchRunner({}, source_registry=Registry()).preview_outputs(
            preset, tmp_path / "preview",
        )


def _split_hdf_preview_fixture(tmp_path, *, source_count=4, exact_pairs=False):
    """One physical HDF that expanded into several logical sub-sources.

    This is the shape ``io.source_adapters._loaded_groups`` produces when an
    HDF splits by sample rate: several ``source_id`` values behind one path,
    none of them resolved at planning time because planning is no-load.  The
    runner therefore plans a group per sub-source without knowing which of
    them actually holds the selected channel.

    ``exact_pairs`` selects the 从当前单次同步 scope, where ``_expand_tasks``
    yields ``target_pairs`` verbatim and deliberately does *not* drop a pair
    whose source lacks the channel (``run`` reports those as per-task
    failures after lazy resolution).  That is the scope where
    ``_pick_representative_group`` still has to catch the gap: under
    ``target_signals`` the same channel map now narrows the expansion itself
    (see ``BatchRunner.seed_source_channels``), so no unrenderable group is
    planned in the first place.
    """

    physical_path = tmp_path / "eps-run.hdf"
    physical_path.write_bytes(b"hdf container")
    source_ids = tuple(f"hdf:eps-run:{index}" for index in range(source_count))
    preset = AnalysisPreset.free_config(
        name="multi sub-source",
        method="time",
        target_signals=("MotorSpeed",),
        params={"render_group_by": "source", "render_layout": "overlay"},
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    preset = replace(
        preset,
        source_ids=source_ids,
        source_paths=(str(physical_path),) * source_count,
        target_pairs=(
            tuple((source_id, "MotorSpeed") for source_id in source_ids)
            if exact_pairs else ()
        ),
    )
    runner = BatchRunner({})
    for source_id in source_ids:
        runner._register_source_locator(source_id, physical_path)
    return runner, preset, source_ids


def _planned_group_for(runner, preset, source_id, channel):
    """Independently rebuild the single-source group for *source_id*."""

    from mf4_analyzer.batch_grouping import RenderTask, group_render_tasks

    params = normalize_batch_params(preset.params, preset.method)
    identity = runner._build_unresolved_task_identity(
        source_id, channel=channel, method=preset.method, params=params,
    )
    return group_render_tasks(
        (RenderTask(source_id, channel, identity),), params,
    )[0]


def test_preview_representative_is_unchanged_without_a_channel_map(tmp_path):
    """The optional argument must not move the historical planning result."""

    runner, preset, source_ids = _split_hdf_preview_fixture(tmp_path)
    out = tmp_path / "out"

    implicit = runner.preview_outputs(preset, out)
    explicit_none = runner.preview_outputs(preset, out, source_channels=None)
    empty_map = runner.preview_outputs(preset, out, source_channels={})

    assert implicit == explicit_none == empty_map
    group = implicit.representative_group
    assert group is not None
    assert group.total_groups == 4
    assert group.ordinal == 1
    assert group.channel_available is True
    first = _planned_group_for(runner, preset, source_ids[0], "MotorSpeed")
    assert group.group_id == first.identity.group_id


def test_preview_representative_skips_sub_sources_without_the_channel(tmp_path):
    """Pick a group the user can actually see rendered, with its real ordinal.

    The acceptance failure: an HDF split into four sub-sources, the selected
    channel lived in only two, and the preview unconditionally took group one.
    """

    runner, preset, source_ids = _split_hdf_preview_fixture(
        tmp_path, exact_pairs=True,
    )
    source_channels = {
        source_ids[0]: frozenset({"Time", "SteeringTorque"}),
        source_ids[1]: frozenset({"Time", "SteeringTorque"}),
        source_ids[2]: frozenset({"Time", "MotorSpeed"}),
        source_ids[3]: frozenset({"Time", "MotorSpeed"}),
    }

    plan = runner.preview_outputs(
        preset, tmp_path / "out", source_channels=source_channels,
    )

    group = plan.representative_group
    expected = _planned_group_for(runner, preset, source_ids[2], "MotorSpeed")
    assert group.channel_available is True
    assert group.group_id == expected.identity.group_id
    assert group.planned_stem == expected.identity.stem
    # The real index, not the hardcoded 1 the dialog used to display.
    assert group.ordinal == 3
    assert group.total_groups == 4


def test_preview_representative_reports_when_no_sub_source_has_the_channel(
    tmp_path,
):
    """Fall back to group one, but say so rather than previewing silently."""

    runner, preset, source_ids = _split_hdf_preview_fixture(
        tmp_path, exact_pairs=True,
    )
    source_channels = {
        source_id: frozenset({"Time", "SteeringTorque"})
        for source_id in source_ids
    }

    plan = runner.preview_outputs(
        preset, tmp_path / "out", source_channels=source_channels,
    )

    group = plan.representative_group
    first = _planned_group_for(runner, preset, source_ids[0], "MotorSpeed")
    assert group.channel_available is False
    assert group.group_id == first.identity.group_id
    assert group.ordinal == 1


def test_preview_representative_ignores_sources_missing_from_the_channel_map(
    tmp_path,
):
    """An unlisted source is unknown, not empty — it must not disqualify."""

    runner, preset, source_ids = _split_hdf_preview_fixture(
        tmp_path, exact_pairs=True,
    )

    plan = runner.preview_outputs(
        preset,
        tmp_path / "out",
        source_channels={source_ids[1]: frozenset({"SteeringTorque"})},
    )

    group = plan.representative_group
    first = _planned_group_for(runner, preset, source_ids[0], "MotorSpeed")
    assert group.channel_available is True
    assert group.ordinal == 1
    assert group.group_id == first.identity.group_id


def _seeded_split_fixture(tmp_path, *, policy="available_per_source"):
    """Split sources where only the last two hold the target channel.

    Mirrors the WWT that reported ``Weg`` over a longer span than
    ``Rack Force``: one physical file, logical sources with disjoint channel
    sets, and a target that lives in only some of them.
    """

    runner, preset, source_ids = _split_hdf_preview_fixture(tmp_path)
    preset = replace(preset, target_policy=policy)
    channels = {
        source_ids[0]: frozenset({"Time", "Weg"}),
        source_ids[1]: frozenset({"Time", "Weg"}),
        source_ids[2]: frozenset({"Time", "MotorSpeed"}),
        source_ids[3]: frozenset({"Time", "MotorSpeed"}),
    }
    return runner, preset, source_ids, channels


def test_seeded_channels_drop_sources_that_cannot_hold_the_target(tmp_path):
    """No-load planning must not plan a channel into a source that lacks it.

    Without the seed the planner treats every unresolved source as *unknown*
    and keeps it, so a split file lands tasks on sub-sources that never had
    the channel -- the phantom ``missing signal`` failure in a Run.
    """

    runner, preset, source_ids, channels = _seeded_split_fixture(tmp_path)

    before = list(runner._expand_tasks(preset, allow_source_load=False))
    assert [key for key, _channel in before] == list(source_ids)

    runner.seed_source_channels(channels)
    after = list(runner._expand_tasks(preset, allow_source_load=False))

    assert after == [
        (source_ids[2], "MotorSpeed"), (source_ids[3], "MotorSpeed"),
    ]


def test_preview_channel_map_narrows_the_planned_groups(tmp_path):
    """The map preview already receives must reach the expansion, not just
    the representative pick.

    The acceptance failure: 5 logical sources, the target in 4 of them, and
    Preview refused outright ("代表分组 ... 不含所选通道") because the single
    planned group carried a member that could never render.
    """

    runner, preset, source_ids, channels = _seeded_split_fixture(tmp_path)

    plan = runner.preview_outputs(
        preset, tmp_path / "out", source_channels=channels,
    )

    group = plan.representative_group
    assert plan.task_count == 2
    assert group.total_groups == 2
    assert group.channel_available is True
    expected = _planned_group_for(runner, preset, source_ids[2], "MotorSpeed")
    assert group.group_id == expected.identity.group_id


def test_seeded_channels_leave_unlisted_sources_planned(tmp_path):
    """A source absent from the seed is unknown, not empty."""

    runner, preset, source_ids, channels = _seeded_split_fixture(tmp_path)
    runner.seed_source_channels({source_ids[0]: channels[source_ids[0]]})

    planned = [
        key for key, _channel
        in runner._expand_tasks(preset, allow_source_load=False)
    ]

    assert planned == list(source_ids[1:])


def test_seeded_channels_are_overwritten_by_a_real_load(tmp_path):
    """A stale hint must self-correct rather than outlive the loaded truth."""

    runner, preset, source_ids, _channels = _seeded_split_fixture(tmp_path)
    runner.seed_source_channels({source_ids[0]: frozenset({"Weg"})})
    assert runner._source_channel_cache[source_ids[0]] == frozenset({"Weg"})

    t = np.arange(8, dtype=float) / 100.0
    df = pd.DataFrame({"Time": t, "MotorSpeed": np.zeros(8)})
    fd = FileData(
        tmp_path / "eps-run.hdf", df, list(df.columns), {}, idx=0,
    )
    runner._normalize_loaded_sources(
        (fd,),
        physical_key=str(tmp_path / "eps-run.hdf"),
        expected_source_id=source_ids[0],
    )

    assert "MotorSpeed" in runner._source_channel_cache[source_ids[0]]


def test_group_checksum_cancellation_marks_run_and_manifest_cancelled(
    tmp_path, monkeypatch,
):
    """Catch a cancelled group checksum being journaled as done."""
    import mf4_analyzer.batch as batch_module
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(
        tmp_path, "group_checksum_cancel", channels=("sig", "aux"), idx=0,
    )
    preset = _task6_grouped_time_preset(export_data=False)
    token = threading.Event()
    events = []
    original_facts = batch_module.artifact_facts

    def cancel_then_checksum(*args, **kwargs):
        token.set()
        return original_facts(*args, **kwargs)

    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(_task6_fake_image),
    )
    monkeypatch.setattr(batch_module, "artifact_facts", cancel_then_checksum)

    result = BatchRunner({0: fd}).run(
        preset, tmp_path / "out", cancel_token=token, on_event=events.append,
    )

    manifest = load_batch_manifest(result.manifest_path)
    group = manifest["render_groups"][0]
    assert result.status == "cancelled"
    assert {item.status for item in result.items} == {"cancelled"}
    assert manifest["run_status"] == "cancelled"
    assert {entry["status"] for entry in manifest["entries"]} == {
        "cancelled",
    }
    assert group["status"] == "cancelled"
    assert group["artifact"]["checksum_status"] == "cancelled"
    assert group["artifact"]["sha256"] is None
    assert [
        event.kind for event in events
        if event.kind in {"task_done", "task_cancelled"}
    ] == ["task_cancelled", "task_cancelled"]


def test_channel_group_terminals_and_progress_flush_in_original_task_order(
    tmp_path, monkeypatch,
):
    """Catch group-order completion making progress reach 100% then regress."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    files = {
        0: _make_fd(
            tmp_path, "ordered_a", channels=("sig", "aux"), idx=0,
        ),
        1: _make_fd(
            tmp_path, "ordered_b", channels=("sig", "aux"), idx=1,
        ),
    }
    preset = replace(
        _task6_grouped_time_preset(group_by="channel"),
        file_ids=(0, 1),
    )
    events = []
    progress = []
    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(_task6_fake_image),
    )

    result = BatchRunner(files).run(
        preset,
        tmp_path / "out",
        on_event=events.append,
        progress_callback=lambda index, total: progress.append((index, total)),
    )

    manifest = load_batch_manifest(result.manifest_path)
    image_by_task_id = {
        member["task_id"]: group["artifact"]["path"]
        for group in manifest["render_groups"]
        for member in group["members"]
    }
    terminals = [
        event for event in events
        if event.kind in {"task_done", "task_resumed", "task_cancelled"}
    ]
    assert result.status == "done"
    assert [event.kind for event in terminals] == ["task_done"] * 4
    assert [event.task_index for event in terminals] == [1, 2, 3, 4]
    assert progress == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert [Path(event.image_path).resolve() for event in terminals] == [
        Path(image_by_task_id[event.task_id]).resolve() for event in terminals
    ]


def test_grouped_runner_probes_once_before_any_output_reservation(
    tmp_path, monkeypatch,
):
    """Catch per-task probes or any reservation that precedes the run probe."""
    import mf4_analyzer.batch as batch_module

    fd = _make_fd(tmp_path, "probe_order", channels=("sig", "aux"), idx=0)
    preset = _task6_grouped_time_preset(write_manifest=False)
    events = []
    original_probe = BatchRunner._probe_image_backend
    original_reserve = batch_module.reserve_output_paths

    def capture_probe():
        events.append("probe")
        return original_probe()

    def capture_reserve(*args, **kwargs):
        events.append("reserve")
        return original_reserve(*args, **kwargs)

    monkeypatch.setattr(BatchRunner, "_probe_image_backend", staticmethod(capture_probe))
    monkeypatch.setattr(batch_module, "reserve_output_paths", capture_reserve)
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert events.count("probe") == 1
    assert events[0] == "probe"


def test_grouped_backend_missing_degrades_data_image_before_reservation(
    tmp_path, monkeypatch,
):
    """Catch image reservations or absent degraded group journal state."""
    import mf4_analyzer.batch as batch_module
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(tmp_path, "group_degraded", channels=("sig", "aux"), idx=0)
    preset = _task6_grouped_time_preset()
    reservations = []
    original_reserve = batch_module.reserve_output_paths

    def capture_reserve(directory, stem, extensions, *, conflict_policy):
        reservations.append(tuple(extensions))
        return original_reserve(
            directory, stem, extensions, conflict_policy=conflict_policy,
        )

    def missing_backend():
        raise ModuleNotFoundError("renderer unavailable", name="pyqtgraph")

    monkeypatch.setattr(BatchRunner, "_probe_image_backend", staticmethod(missing_backend))
    monkeypatch.setattr(batch_module, "reserve_output_paths", capture_reserve)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "partial"
    assert [item.status for item in result.items] == ["done", "done"]
    assert all(item.degraded_reason == _DEGRADED_REASON for item in result.items)
    assert reservations == [("csv",), ("csv",)]
    assert len(list((tmp_path / "out").glob("*.csv"))) == 2
    assert not list((tmp_path / "out").glob("*.png"))
    groups = load_batch_manifest(result.manifest_path)["render_groups"]
    assert len(groups) == 1
    assert groups[0]["status"] == "degraded"
    assert groups[0]["effective_outputs"] == {"data": "csv"}


def test_grouped_image_only_missing_backend_fails_before_compute_or_reserve(
    tmp_path, monkeypatch,
):
    """Catch image-only runs that load/compute or reserve after probe failure."""
    import mf4_analyzer.batch as batch_module
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(tmp_path, "group_image_only", channels=("sig", "aux"), idx=0)
    preset = _task6_grouped_time_preset(export_data=False)

    def missing_backend():
        raise ImportError("renderer unavailable", name="pyqtgraph")

    def forbidden(*args, **kwargs):
        pytest.fail("image-only missing backend must fail before compute/reserve")

    monkeypatch.setattr(BatchRunner, "_probe_image_backend", staticmethod(missing_backend))
    monkeypatch.setattr(BatchRunner, "_compute_preprocessed_time_dataframe", forbidden)
    monkeypatch.setattr(batch_module, "reserve_output_paths", forbidden)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert [item.status for item in result.items] == ["failed", "failed"]
    assert all(item.effective_outputs == {} for item in result.items)
    groups = load_batch_manifest(result.manifest_path)["render_groups"]
    assert [group["status"] for group in groups] == ["failed"]


def test_default_time_keeps_one_task_reservation_and_atomic_artifact_set(
    tmp_path, monkeypatch,
):
    """Catch accidental splitting of the legacy none-mode data/image set."""
    import mf4_analyzer.batch as batch_module

    fd = _make_fd(tmp_path, "default_atomic", channels=("sig",), idx=0)
    preset = AnalysisPreset.from_current_single(
        name="default atomic",
        method="time",
        signal=(0, "sig"),
        params={},
        outputs=BatchOutput(export_data=True, export_image=True, write_manifest=False),
    )
    counts = {"reserve": 0, "atomic": 0}
    original_reserve = batch_module.reserve_output_paths
    original_atomic = batch_module.atomic_write_set

    def capture_reserve(*args, **kwargs):
        counts["reserve"] += 1
        return original_reserve(*args, **kwargs)

    def capture_atomic(*args, **kwargs):
        counts["atomic"] += 1
        return original_atomic(*args, **kwargs)

    monkeypatch.setattr(batch_module, "reserve_output_paths", capture_reserve)
    monkeypatch.setattr(batch_module, "atomic_write_set", capture_atomic)
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert counts == {"reserve": 1, "atomic": 1}
    assert result.items[0].data_path and result.items[0].image_path


def test_explicit_singleton_uses_task_data_stem_and_distinct_group_image_stem(
    tmp_path, monkeypatch,
):
    """Catch singleton groups incorrectly reusing legacy cross-artifact stem."""
    fd = _make_fd(tmp_path, "singleton_group", channels=("sig",), idx=0)
    preset = AnalysisPreset.from_current_single(
        name="singleton explicit",
        method="time",
        signal=(0, "sig"),
        params={"render_group_by": "source"},
        outputs=BatchOutput(export_data=True, export_image=True),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    from mf4_analyzer.batch_manifest import load_batch_manifest

    manifest = load_batch_manifest(result.manifest_path)
    group = manifest["render_groups"][0]
    assert result.status == "done"
    assert Path(result.items[0].data_path).stem != Path(group["artifact"]["path"]).stem
    assert result.items[0].image_path is None


@pytest.mark.parametrize("failure_type", [RuntimeError, ModuleNotFoundError])
def test_group_writer_failure_preserves_task_csv_and_never_degrades(
    tmp_path, monkeypatch, failure_type,
):
    """Catch cross-transaction rollback or writer-time import degradation."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(tmp_path, "group_writer_fail", channels=("sig", "aux"), idx=0)
    preset = _task6_grouped_time_preset()

    def fail_image(*args, **kwargs):
        raise failure_type("writer-time render failure")

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(fail_image))

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "partial"
    assert [item.status for item in result.items] == ["done", "done"]
    assert all(not item.degraded_reason for item in result.items)
    assert len(list((tmp_path / "out").glob("*.csv"))) == 2
    assert not list((tmp_path / "out").glob("*.png"))
    manifest = load_batch_manifest(result.manifest_path)
    assert [entry["status"] for entry in manifest["entries"]] == ["done", "done"]
    assert manifest["render_groups"][0]["status"] == "failed"
    assert manifest["render_groups"][0]["degraded_reason"] == ""


@pytest.mark.parametrize(
    ("group_by", "expected_images"), (("source", 2), ("channel", 2)),
)
def test_grouped_runner_publishes_task_data_and_exact_group_images(
    tmp_path, group_by, expected_images,
):
    """Catch task-image publication or missing explicit group images."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    files = {
        0: _make_fd(tmp_path, "group_a", channels=("sig", "aux"), idx=0),
        1: _make_fd(tmp_path, "group_b", channels=("sig", "aux"), idx=1),
    }
    preset = _task6_grouped_time_preset(group_by=group_by)
    preset = replace(preset, file_ids=(0, 1))

    result = BatchRunner(files).run(preset, tmp_path / "out")

    manifest = load_batch_manifest(result.manifest_path)
    assert result.status == "done"
    assert len(result.items) == 4
    assert all(item.status == "done" and item.image_path is None for item in result.items)
    assert len(list((tmp_path / "out").glob("*.csv"))) == 4
    assert len(list((tmp_path / "out").glob("*.png"))) == expected_images
    assert len(manifest["render_groups"]) == expected_images
    assert {group["status"] for group in manifest["render_groups"]} == {"done"}


@pytest.mark.parametrize(
    ("available", "expected_status", "expected_members", "image_count"),
    (
        (("sig",), "partial", "1/2", 1),
        ((), "failed", None, 0),
    ),
)
def test_grouped_runner_renders_only_successful_payloads_and_records_outcome(
    tmp_path, monkeypatch, available, expected_status, expected_members,
    image_count,
):
    """Catch failed members entering a partial image or empty-group render."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(tmp_path, "partial_group", channels=available, idx=0)
    preset = _task6_grouped_time_preset()
    preset = replace(
        preset,
        file_ids=(0,),
        target_pairs=((0, "sig"), (0, "missing")),
    )
    captured = {}

    def capture_image(
        payload, path, params=None, *, options=None, context=None,
        warnings_out=None,
    ):
        captured["series"] = len(payload[1].series)
        captured["members"] = context.effective_facts.get("members")
        return _task6_fake_image(
            payload, path, params, options=options, context=context,
            warnings_out=warnings_out,
        )

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(capture_image))

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    group = load_batch_manifest(result.manifest_path)["render_groups"][0]
    assert group["status"] == expected_status
    assert len(list((tmp_path / "out").glob("*.png"))) == image_count
    if image_count:
        assert captured == {"series": 1, "members": expected_members}
    else:
        assert captured == {}


@pytest.mark.parametrize(
    ("member_count", "layout", "message_fragment"),
    ((33, "overlay", "members"), (9, "subplot", "panels")),
)
def test_grouped_runner_blocks_member_and_panel_guards_but_keeps_data(
    tmp_path, monkeypatch, member_count, layout, message_fragment,
):
    """Catch late guard enforcement that writes a prohibited group image."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    channels = tuple(f"sig_{index}" for index in range(member_count))
    fd = _make_fd(tmp_path, "guarded_group", channels=channels, idx=0)
    preset = AnalysisPreset.free_config(
        name="guarded group",
        method="time",
        target_signals=channels,
        params={"render_group_by": "source", "render_layout": layout},
        outputs=BatchOutput(export_data=True, export_image=True),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("blocked group must never render")

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(forbidden))
    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    group = load_batch_manifest(result.manifest_path)["render_groups"][0]
    assert len(list((tmp_path / "out").glob("*.csv"))) == member_count
    assert not list((tmp_path / "out").glob("*.png"))
    assert group["status"] == "blocked"
    assert message_fragment in group["message"]


def test_group_payload_limit_is_checked_before_spool_write_and_data_continues(
    tmp_path, monkeypatch,
):
    """Catch payload writes performed before the 128 MiB group guard."""
    import mf4_analyzer.batch_series_spool as spool_module
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(tmp_path, "group_bytes", channels=("sig", "aux"), idx=0)
    preset = _task6_grouped_time_preset()
    monkeypatch.setattr(spool_module, "_MAX_GROUP_PAYLOAD_BYTES", 1)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    group = load_batch_manifest(result.manifest_path)["render_groups"][0]
    assert [item.status for item in result.items] == ["done", "done"]
    assert len(list((tmp_path / "out").glob("*.csv"))) == 2
    assert group["status"] == "blocked"
    assert "group payload" in group["message"]


def test_run_spool_limit_blocks_every_incomplete_group_and_data_continues(
    tmp_path, monkeypatch,
):
    """Catch continued spooling after the 2 GiB all-run guard fires."""
    import mf4_analyzer.batch_series_spool as spool_module
    from mf4_analyzer.batch_manifest import load_batch_manifest

    files = {
        0: _make_fd(tmp_path, "spool_a", channels=("sig", "aux"), idx=0),
        1: _make_fd(tmp_path, "spool_b", channels=("sig", "aux"), idx=1),
    }
    preset = _task6_grouped_time_preset(group_by="channel")
    preset = replace(preset, file_ids=(0, 1))
    one_payload_bytes = 2 * files[0].data.shape[0] * np.dtype(float).itemsize
    monkeypatch.setattr(spool_module, "_MAX_SPOOL_BYTES", one_payload_bytes * 2)

    result = BatchRunner(files).run(preset, tmp_path / "out")

    groups = load_batch_manifest(result.manifest_path)["render_groups"]
    assert len(list((tmp_path / "out").glob("*.csv"))) == 4
    assert not list((tmp_path / "out").glob("*.png"))
    assert {group["status"] for group in groups} == {"blocked"}
    assert all("run spool" in group["message"] for group in groups)


def test_grouped_cancellation_closes_and_removes_spool_directory(
    tmp_path, monkeypatch,
):
    """Catch cancellation paths that bypass the spool context manager."""
    import mf4_analyzer.batch_series_spool as spool_module

    fd = _make_fd(tmp_path, "cancel_spool", channels=("sig", "aux"), idx=0)
    preset = _task6_grouped_time_preset(write_manifest=False)
    token = threading.Event()
    spool_dirs = []
    real_mkdtemp = spool_module.tempfile.mkdtemp
    original_compute = BatchRunner._compute_preprocessed_time_dataframe

    def tracked_mkdtemp(*args, **kwargs):
        kwargs["dir"] = tmp_path
        path = real_mkdtemp(*args, **kwargs)
        spool_dirs.append(Path(path))
        return path

    def compute_then_cancel(*args, **kwargs):
        frame = original_compute(*args, **kwargs)
        token.set()
        return frame

    monkeypatch.setattr(spool_module.tempfile, "mkdtemp", tracked_mkdtemp)
    monkeypatch.setattr(
        BatchRunner,
        "_compute_preprocessed_time_dataframe",
        staticmethod(compute_then_cancel),
    )

    result = BatchRunner({0: fd}).run(
        preset, tmp_path / "out", cancel_token=token,
    )

    assert result.status == "cancelled"
    assert len(spool_dirs) == 1
    assert not spool_dirs[0].exists()


def test_group_render_warnings_are_deduplicated_and_mirrored_to_successes(
    tmp_path, monkeypatch,
):
    """Catch warning loss, duplication, or mirroring onto failed members."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(tmp_path, "warning_group", channels=("sig",), idx=0)
    preset = _task6_grouped_time_preset()
    preset = replace(
        preset,
        file_ids=(0,),
        target_pairs=((0, "sig"), (0, "missing")),
    )

    def warning_image(
        payload, path, params=None, *, options=None, context=None,
        warnings_out=None,
    ):
        warnings_out.extend(["shared warning", "shared warning"])
        return _task6_fake_image(
            payload, path, params, options=options, context=context,
            warnings_out=warnings_out,
        )

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(warning_image))
    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    successful, failed = result.items
    group = load_batch_manifest(result.manifest_path)["render_groups"][0]
    assert successful.warnings.count("shared warning") == 1
    assert "shared warning" not in failed.warnings
    assert group["warnings"] == ["shared warning"]


def test_migrated_pdf_request_runs_as_png_and_preserves_audit_warning(
    tmp_path, monkeypatch,
):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    warning = "旧预设图像格式 PDF 已迁移为 PNG；本次仅输出 PNG。"
    fd = _make_fd(tmp_path, "migrated_pdf", channels=("sig",), idx=0)
    preset = AnalysisPreset.from_current_single(
        name="migrated PDF",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 1024.0, "nfft": 64},
        outputs=BatchOutput(
            image_format="png",
            requested_image_format="pdf",
            migration_warnings=(warning,),
        ),
    )
    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(_task6_fake_image),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.warnings == [warning]
    assert result.items[0].requested_outputs["image"] == "pdf"
    assert result.items[0].effective_outputs["image"] == "png"
    assert result.items[0].warnings == [warning]
    assert Path(result.items[0].image_path).suffix == ".png"
    manifest = load_batch_manifest(result.manifest_path)
    entry = manifest["entries"][0]
    assert entry["requested_outputs"]["image"] == "pdf"
    assert entry["effective_outputs"]["image"] == "png"
    assert entry["warnings"] == [warning]
    assert entry["degraded_reason"] == ""
    assert manifest["requested_output_settings"]["image_format"] == "png"
    assert manifest["requested_output_settings"]["requested_image_format"] == "pdf"


def test_migration_warning_propagates_to_group_and_each_successful_member(
    tmp_path, monkeypatch,
):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    warning = "旧预设图像格式 SVG 已迁移为 PNG；本次仅输出 PNG。"
    fd = _make_fd(
        tmp_path, "migrated_group", channels=("sig", "aux"), idx=0,
    )
    preset = _task6_grouped_time_preset(export_data=False)
    preset = replace(
        preset,
        outputs=replace(
            preset.outputs,
            requested_image_format="svg",
            migration_warnings=(warning,),
        ),
    )
    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(_task6_fake_image),
    )

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert result.warnings == [warning]
    assert all(item.warnings == [warning] for item in result.items)
    manifest = load_batch_manifest(result.manifest_path)
    assert all(entry["warnings"] == [warning] for entry in manifest["entries"])
    group = manifest["render_groups"][0]
    assert group["requested_outputs"]["image"] == "svg"
    assert group["effective_outputs"]["image"] == "png"
    assert group["warnings"] == [warning]
    assert group["degraded_reason"] == ""


def test_group_resume_uses_current_png_when_prior_requested_format_was_pdf(
    tmp_path, monkeypatch,
):
    import json

    fd = _make_fd(tmp_path, "legacy_resume", channels=("sig", "aux"), idx=0)
    preset = _task6_grouped_time_preset(
        export_data=False, export_image=True,
    )
    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(_task6_fake_image),
    )
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(preset, output_dir)
    prior = Path(first.manifest_path)
    payload = json.loads(prior.read_text(encoding="utf-8"))
    payload["render_groups"][0]["requested_outputs"]["image"] = "pdf"
    legacy_manifest = tmp_path / "legacy-requested-pdf.json"
    legacy_manifest.write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )

    def unexpected_render(*_args, **_kwargs):
        raise AssertionError("valid canonical PNG group should have resumed")

    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(unexpected_render),
    )
    second = BatchRunner({0: fd}).run(
        replace(
            preset,
            outputs=replace(preset.outputs, resume_policy="manifest"),
        ),
        output_dir,
        resume_manifest=legacy_manifest,
    )

    assert second.status == "done"
    assert {item.status for item in second.items} == {"done"}
    second_manifest = json.loads(
        Path(second.manifest_path).read_text(encoding="utf-8")
    )
    assert second_manifest["render_groups"][0]["message"] == (
        "manifest-proven group resume"
    )


def test_explicit_group_data_only_writes_no_render_group_journal(tmp_path):
    """Catch render_groups leaking into a data-only manifest."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(tmp_path, "data_only_group", channels=("sig", "aux"), idx=0)
    preset = _task6_grouped_time_preset(export_image=False)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    manifest = load_batch_manifest(result.manifest_path)
    assert result.status == "done"
    assert "render_groups" not in manifest


def test_grouped_channel_execution_loads_each_physical_source_once(
    tmp_path, monkeypatch,
):
    """Catch task-major reloads at the real injected loader boundary."""
    files_by_path = {}
    for index in range(4):
        fd = _make_fd(
            tmp_path, f"physical_{index}", channels=("sig", "aux"), idx=index,
        )
        files_by_path[str(fd.filepath)] = fd
    load_counts = {path: 0 for path in files_by_path}

    def loader(path):
        key = str(path)
        load_counts[key] += 1
        return files_by_path[key]

    preset = _task6_grouped_time_preset(group_by="channel")
    preset = replace(preset, source_paths=tuple(files_by_path))
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))

    result = BatchRunner({}, loader=loader).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert load_counts == {path: 1 for path in files_by_path}
    assert len(result.items) == 8
    assert len(list((tmp_path / "out").glob("*.csv"))) == 8
    assert len(list((tmp_path / "out").glob("*.png"))) == 2
    from mf4_analyzer.batch_manifest import load_batch_manifest

    manifest = load_batch_manifest(result.manifest_path)
    task_ids = {entry["task_id"] for entry in manifest["entries"]}
    member_task_ids = {
        member["task_id"]
        for group in manifest["render_groups"]
        for member in group["members"]
    }
    assert member_task_ids == task_ids


def test_default_lazy_image_only_missing_backend_probes_before_source_load(
    tmp_path, monkeypatch,
):
    """Catch default task enumeration loading a lazy source before probe."""
    import mf4_analyzer.batch as batch_module

    source = tmp_path / "lazy-default.csv"
    events = []

    def loader(_path):
        events.append("load")
        pytest.fail("missing image backend must stop before source load")

    def missing_backend():
        events.append("probe")
        raise ModuleNotFoundError("renderer unavailable", name="pyqtgraph")

    def forbidden_reserve(*_args, **_kwargs):
        events.append("reserve")
        pytest.fail("missing image backend must stop before reservation")

    preset = AnalysisPreset.free_config(
        name="lazy default image only",
        method="time",
        target_signals=("sig",),
        params={},
        outputs=BatchOutput(
            export_data=False,
            export_image=True,
            write_manifest=False,
        ),
    )
    preset = replace(preset, source_paths=(source,))
    runner = BatchRunner({}, loader=loader)
    monkeypatch.setattr(
        runner, "_probe_image_backend", staticmethod(missing_backend),
    )
    monkeypatch.setattr(batch_module, "reserve_output_paths", forbidden_reserve)

    result = runner.run(preset, tmp_path / "out")

    assert result.status == "blocked"
    assert len(result.items) == 1
    assert result.items[0].status == "failed"
    assert events == ["probe"]


@pytest.mark.parametrize(
    ("group_by", "expected_group_count", "expected_image_count"),
    [("source", 1, 1), ("channel", 2, 2)],
)
def test_lazy_legacy_pattern_rebuilds_group_plan_after_probe(
    tmp_path, monkeypatch, group_by, expected_group_count,
    expected_image_count,
):
    """Catch post-probe pattern expansion retaining the empty group plan."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(
        tmp_path,
        f"lazy_legacy_{group_by}",
        channels=("sig", "aux", "ignored"),
        idx=0,
    )
    source_path = str(fd.filepath)
    loader_calls = 0

    def loader(path):
        nonlocal loader_calls
        assert str(path) == source_path
        loader_calls += 1
        return fd

    preset = AnalysisPreset.free_config(
        name=f"lazy legacy pattern by {group_by}",
        method="time",
        signal_pattern=r"^(sig|aux)$",
        params={"render_group_by": group_by, "render_layout": "overlay"},
        outputs=BatchOutput(export_data=True, export_image=True),
    )
    preset = replace(preset, source_paths=(source_path,))
    monkeypatch.setattr(
        BatchRunner, "_write_image", staticmethod(_task6_fake_image),
    )

    result = BatchRunner({}, loader=loader).run(preset, tmp_path / "out")

    manifest = load_batch_manifest(result.manifest_path)
    groups = manifest.get("render_groups", [])
    task_ids = {entry["task_id"] for entry in manifest["entries"]}
    member_task_ids = {
        member["task_id"]
        for group in groups
        for member in group["members"]
    }
    assert result.status == "done"
    assert len(task_ids) == 2
    assert (
        loader_calls,
        len(result.items),
        len(groups),
        len(list((tmp_path / "out").glob("*.png"))),
    ) == (1, 2, expected_group_count, expected_image_count)
    assert {item.task_id for item in result.items} == task_ids
    assert member_task_ids == task_ids


def test_grouped_interleaved_pairs_regroup_by_canonical_physical_source(
    tmp_path, monkeypatch,
):
    """Catch A/B/A task order evicting and reloading physical source A."""
    from mf4_analyzer.batch_manifest import load_batch_manifest

    source_a = _make_fd(
        tmp_path, "interleaved_a", channels=("sig", "aux"), idx=0,
    )
    source_b = _make_fd(
        tmp_path, "interleaved_b", channels=("sig", "aux"), idx=1,
    )
    files = {
        str(source_a.filepath): source_a,
        str(source_b.filepath): source_b,
    }

    def run_pairs(pairs, output_name):
        calls = {path: 0 for path in files}

        def loader(path):
            key = str(path)
            calls[key] += 1
            return files[key]

        preset = _task6_grouped_time_preset(group_by="channel")
        preset = replace(
            preset,
            target_pairs=tuple(pairs),
            source_paths=tuple(files),
        )
        result = BatchRunner({}, loader=loader).run(
            preset, tmp_path / output_name,
        )
        manifest = load_batch_manifest(result.manifest_path)
        groups = tuple(
            (
                group["group_id"],
                tuple(member["task_id"] for member in group["members"]),
            )
            for group in manifest["render_groups"]
        )
        return result, calls, groups

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    interleaved = (
        (str(source_a.filepath), "sig"),
        (str(source_b.filepath), "sig"),
        (str(source_a.filepath), "aux"),
    )
    canonical = (
        (str(source_a.filepath), "sig"),
        (str(source_a.filepath), "aux"),
        (str(source_b.filepath), "sig"),
    )

    first, first_calls, first_groups = run_pairs(interleaved, "interleaved")
    second, second_calls, second_groups = run_pairs(canonical, "canonical")

    assert first.status == second.status == "done"
    assert first_calls == second_calls == {path: 1 for path in files}
    assert first_groups == second_groups


@pytest.mark.parametrize("error_type", [OSError, RuntimeError])
def test_group_spool_append_failure_after_csv_commit_keeps_task_done(
    tmp_path, monkeypatch, error_type,
):
    """Catch a post-commit spool failure rewriting a healthy task as failed."""
    import mf4_analyzer.batch_series_spool as spool_module
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_fd(tmp_path, "append_failure", channels=("sig",), idx=0)
    preset = AnalysisPreset.from_current_single(
        name="append failure after commit",
        method="time",
        signal=(0, "sig"),
        params={"render_group_by": "source"},
        outputs=BatchOutput(export_data=True, export_image=True),
    )

    def fail_append(*_args, **_kwargs):
        raise error_type("spool append failed after csv commit")

    monkeypatch.setattr(spool_module.BatchSeriesSpool, "append", fail_append)

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    manifest = load_batch_manifest(result.manifest_path)
    item = result.items[0]
    entry = manifest["entries"][0]
    group = manifest["render_groups"][0]
    assert result.status == "partial"
    assert item.status == entry["status"] == "done"
    assert item.data_path and Path(item.data_path).is_file()
    assert set(entry["artifacts"]) == {"data"}
    assert group["status"] == "failed"
    assert "spool append failed after csv commit" in group["message"]


def test_group_load_failure_releases_partial_mmaps_before_next_group(
    tmp_path, monkeypatch,
):
    """Catch one failed group retaining mmap handles into the next render."""
    import mf4_analyzer.batch_series_spool as spool_module
    from mf4_analyzer.batch_manifest import load_batch_manifest

    files = {
        0: _make_fd(tmp_path, "mmap_a", channels=("sig",), idx=0),
        1: _make_fd(tmp_path, "mmap_b", channels=("sig",), idx=1),
    }
    preset = AnalysisPreset.free_config(
        name="transactional mmap groups",
        method="time",
        target_signals=("sig",),
        params={"render_group_by": "source"},
        outputs=BatchOutput(export_data=True, export_image=True),
    )
    preset = replace(preset, file_ids=(0, 1))
    real_load = spool_module.np.load
    mappings = []
    load_calls = 0
    render_calls = 0

    def fail_second_load(*args, **kwargs):
        nonlocal load_calls
        load_calls += 1
        if load_calls == 2:
            raise OSError("first group y mmap failed")
        array = real_load(*args, **kwargs)
        mappings.append(array)
        return array

    def render_second_group(
        payload, path, params=None, *, options=None, context=None,
        warnings_out=None,
    ):
        nonlocal render_calls
        render_calls += 1
        assert mappings[0]._mmap.closed
        return _task6_fake_image(
            payload, path, params, options=options, context=context,
            warnings_out=warnings_out,
        )

    monkeypatch.setattr(spool_module.np, "load", fail_second_load)
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(render_second_group))

    result = BatchRunner(files).run(preset, tmp_path / "out")

    groups = load_batch_manifest(result.manifest_path)["render_groups"]
    assert result.status == "partial"
    assert [group["status"] for group in groups] == ["failed", "done"]
    assert render_calls == 1
    assert mappings and all(array._mmap.closed for array in mappings)


def test_successful_group_releases_mmaps_before_loading_next_group(
    tmp_path, monkeypatch,
):
    """Catch successful group mappings accumulating until whole-run close."""
    import mf4_analyzer.batch_series_spool as spool_module

    files = {
        0: _make_fd(tmp_path, "release_a", channels=("sig",), idx=0),
        1: _make_fd(tmp_path, "release_b", channels=("sig",), idx=1),
    }
    preset = AnalysisPreset.free_config(
        name="release mappings per group",
        method="time",
        target_signals=("sig",),
        params={"render_group_by": "source"},
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    preset = replace(preset, file_ids=(0, 1))
    real_load = spool_module.np.load
    mappings = []
    render_calls = 0

    def recording_load(*args, **kwargs):
        array = real_load(*args, **kwargs)
        mappings.append(array)
        return array

    def render_group(
        payload, path, params=None, *, options=None, context=None,
        warnings_out=None,
    ):
        nonlocal render_calls
        render_calls += 1
        if render_calls == 2:
            assert all(array._mmap.closed for array in mappings[:2])
        return _task6_fake_image(
            payload, path, params, options=options, context=context,
            warnings_out=warnings_out,
        )

    monkeypatch.setattr(spool_module.np, "load", recording_load)
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(render_group))

    result = BatchRunner(files).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert render_calls == 2
    assert all(array._mmap.closed for array in mappings)


def _task7_artifact_snapshot(path):
    path = Path(path)
    return path.read_bytes(), path.stat().st_mtime_ns


def _task7_touch_with_bytes(path, payload, *, mtime_ns=1_000_000_000):
    path = Path(path)
    path.write_bytes(payload)
    import os
    os.utime(path, ns=(mtime_ns, mtime_ns))


def _task7_set_mtime(path, mtime_ns):
    import os

    os.utime(path, ns=(mtime_ns, mtime_ns))


def _task7_resume_preset(*, group_by="source", signals=("sig", "aux")):
    preset = AnalysisPreset.free_config(
        name="task 7 grouped recovery",
        method="time",
        target_signals=signals,
        params={"render_group_by": group_by, "render_layout": "overlay"},
        outputs=BatchOutput(
            export_data=True,
            export_image=True,
            conflict_policy="auto_number",
            resume_policy="manifest",
        ),
    )
    return preset


def _task7_manifest(path):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    return load_batch_manifest(path)


@pytest.mark.parametrize(
    ("invalid_data_indexes", "image_valid"),
    (((), True), ((0,), True), ((), False), ((0,), False)),
    ids=(
        "all-data-valid-image-valid",
        "partial-data-invalid-image-valid",
        "all-data-valid-image-invalid",
        "partial-data-invalid-image-invalid",
    ),
)
def test_grouped_resume_fixed_design_matrix_preserves_ineligible_artifacts(
    tmp_path, monkeypatch, invalid_data_indexes, image_valid,
):
    """Catch payload demand accidentally granting permission to rewrite CSVs."""
    fd = _make_fd(tmp_path, "resume_matrix", channels=("sig", "aux"), idx=0)
    preset = replace(_task7_resume_preset(), file_ids=(0,))
    render_calls = 0

    def versioned_image(payload, path, **kwargs):
        nonlocal render_calls
        render_calls += 1
        Path(path).write_bytes(f"group-image-{render_calls}".encode())
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(versioned_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(preset, output_dir)
    first_manifest = _task7_manifest(first.manifest_path)
    data_paths = [Path(item.data_path) for item in first.items]
    image_path = Path(first_manifest["render_groups"][0]["artifact"]["path"])

    for index in invalid_data_indexes:
        _task7_touch_with_bytes(
            data_paths[index],
            f"invalid-{index}".encode(),
            mtime_ns=1_000_000_000 + index,
        )
    if not image_valid:
        _task7_touch_with_bytes(
            image_path, b"invalid-image", mtime_ns=2_000_000_000,
        )
    for index, path in enumerate(data_paths):
        if index not in invalid_data_indexes:
            _task7_set_mtime(path, 3_000_000_000 + index)
    if image_valid:
        _task7_set_mtime(image_path, 4_000_000_000)
    before_data = [_task7_artifact_snapshot(path) for path in data_paths]
    before_image = _task7_artifact_snapshot(image_path)

    second = BatchRunner({0: fd}).run(
        preset, output_dir, resume_manifest=first.manifest_path,
    )

    after_data = [_task7_artifact_snapshot(path) for path in data_paths]
    after_image = _task7_artifact_snapshot(image_path)
    for index in range(len(data_paths)):
        if index in invalid_data_indexes:
            assert after_data[index][0] != before_data[index][0]
            assert after_data[index][1] != before_data[index][1]
        else:
            assert after_data[index][0] == before_data[index][0]
            assert after_data[index][1] == before_data[index][1]
    if image_valid:
        assert after_image[0] == before_image[0]
        assert after_image[1] == before_image[1]
    else:
        assert after_image[0] != before_image[0]
        assert after_image[1] != before_image[1]
    assert render_calls == (1 if image_valid else 2)
    assert len(list(output_dir.glob("*.csv"))) == 2
    assert len(list(output_dir.glob("*.png"))) == 1
    assert [item.status for item in second.items] == [
        "done" if index in invalid_data_indexes else "resumed"
        for index in range(2)
    ]


def _task7_lazy_pattern_preset(
    *, group_by="source", pattern=r"^(sig|aux)$",
):
    preset = AnalysisPreset.free_config(
        name="task 7 lazy legacy recovery",
        method="time",
        signal_pattern=pattern,
        params={"render_group_by": group_by, "render_layout": "overlay"},
        outputs=BatchOutput(
            export_data=True,
            export_image=True,
            conflict_policy="auto_number",
            resume_policy="manifest",
        ),
    )
    return preset


def _task7_assert_group_member_linkage(manifest):
    task_ids = {entry["task_id"] for entry in manifest["entries"]}
    member_ids = {
        member["task_id"]
        for group in manifest["render_groups"]
        for member in group["members"]
    }
    assert member_ids == task_ids
    assert len(manifest["render_groups"]) == len({
        group["artifact"]["path"]
        for group in manifest["render_groups"]
    })


def test_lazy_pattern_complete_group_resume_never_calls_real_loader(
    tmp_path, monkeypatch,
):
    """Catch fallback task discovery loading a source before recovery planning."""
    fd = _make_fd(tmp_path, "lazy_resume", channels=("sig", "aux"), idx=0)
    source_path = str(fd.filepath)
    calls = 0

    def loader(path):
        nonlocal calls
        assert str(path) == source_path
        calls += 1
        return fd

    preset = replace(
        _task7_lazy_pattern_preset(), source_paths=(source_path,),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({}, loader=loader).run(preset, output_dir)
    first_manifest = _task7_manifest(first.manifest_path)
    expected_path = str(Path(source_path).resolve(strict=False))
    assert first_manifest["normalized_recipe"].get("execution_scope") == {
        "mode": "lazy_pattern",
        "source_paths": [expected_path],
        "signal_pattern": r"^(sig|aux)$",
    }
    data_before = {
        item.task_id: _task7_artifact_snapshot(item.data_path)
        for item in first.items
    }
    image_path = first_manifest["render_groups"][0]["artifact"]["path"]
    image_before = _task7_artifact_snapshot(image_path)
    calls = 0

    second = BatchRunner({}, loader=loader).run(
        preset, output_dir, resume_manifest=first.manifest_path,
    )

    assert calls == 0
    assert [item.status for item in second.items] == ["resumed", "resumed"]
    assert {
        item.task_id: _task7_artifact_snapshot(item.data_path)
        for item in second.items
    } == data_before
    second_group = _task7_manifest(second.manifest_path)["render_groups"][0]
    assert _task7_artifact_snapshot(image_path) == image_before
    assert [
        member["task_id"] for member in second_group["members"]
    ] == [
        member["task_id"]
        for member in first_manifest["render_groups"][0]["members"]
    ]


def test_lazy_pattern_added_source_path_forces_complete_fresh_expansion(
    tmp_path, monkeypatch,
):
    """Catch a prior one-path task subset impersonating a two-path scope."""
    first_fd = _make_fd(tmp_path, "scope_path_a", channels=("sig",), idx=0)
    second_fd = _make_fd(tmp_path, "scope_path_b", channels=("sig",), idx=1)
    files = {
        str(first_fd.filepath): first_fd,
        str(second_fd.filepath): second_fd,
    }
    calls = {path: 0 for path in files}

    def loader(path):
        key = str(path)
        calls[key] += 1
        return files[key]

    first_preset = replace(
        _task7_lazy_pattern_preset(pattern=r"^sig$"),
        source_paths=(str(first_fd.filepath),),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({}, loader=loader).run(first_preset, output_dir)
    first_manifest = _task7_manifest(first.manifest_path)
    first_data_before = _task7_artifact_snapshot(first.items[0].data_path)
    first_group_path = Path(
        first_manifest["render_groups"][0]["artifact"]["path"]
    )
    first_group_before = _task7_artifact_snapshot(first_group_path)
    calls = {path: 0 for path in files}
    expanded_preset = replace(
        first_preset, source_paths=tuple(files),
    )

    second = BatchRunner({}, loader=loader).run(
        expanded_preset, output_dir, resume_manifest=first.manifest_path,
    )
    second_manifest = _task7_manifest(second.manifest_path)

    assert calls == {path: 1 for path in files}
    assert len(second.items) == 2
    assert len(second_manifest["render_groups"]) == 2
    assert len(list(output_dir.glob("*.png"))) == 2
    retained = next(
        item for item in second.items
        if item.file_id == str(first_fd.filepath)
    )
    assert retained.status == "resumed"
    assert _task7_artifact_snapshot(retained.data_path) == first_data_before
    assert _task7_artifact_snapshot(first_group_path) == first_group_before
    assert first_group_path in {
        Path(group["artifact"]["path"])
        for group in second_manifest["render_groups"]
    }
    _task7_assert_group_member_linkage(second_manifest)
    assert (
        second_manifest["recipe_fingerprint"]
        == first_manifest["recipe_fingerprint"]
    )


def test_lazy_pattern_removed_source_path_forces_current_scope_expansion(
    tmp_path, monkeypatch,
):
    """Catch removed paths surviving through prior manifest task entries."""
    files = {}
    for index, name in enumerate(("scope_remove_a", "scope_remove_b")):
        fd = _make_fd(tmp_path, name, channels=("sig",), idx=index)
        files[str(fd.filepath)] = fd
    calls = {path: 0 for path in files}

    def loader(path):
        key = str(path)
        calls[key] += 1
        return files[key]

    first_preset = replace(
        _task7_lazy_pattern_preset(pattern=r"^sig$"),
        source_paths=tuple(files),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({}, loader=loader).run(first_preset, output_dir)
    retained_path = tuple(files)[0]
    calls = {path: 0 for path in files}
    reduced_preset = replace(first_preset, source_paths=(retained_path,))

    second = BatchRunner({}, loader=loader).run(
        reduced_preset, output_dir, resume_manifest=first.manifest_path,
    )
    second_manifest = _task7_manifest(second.manifest_path)

    assert calls == {
        retained_path: 1,
        tuple(files)[1]: 0,
    }
    assert len(second.items) == 1
    assert len(second_manifest["render_groups"]) == 1
    _task7_assert_group_member_linkage(second_manifest)


def test_lazy_pattern_expansion_forces_load_and_discovers_new_channel(
    tmp_path, monkeypatch,
):
    """Catch an old narrower pattern silently defining the current task scope."""
    fd = _make_fd(tmp_path, "scope_pattern", channels=("sig", "aux"), idx=0)
    source_path = str(fd.filepath)
    calls = 0

    def loader(path):
        nonlocal calls
        calls += 1
        assert str(path) == source_path
        return fd

    first_preset = replace(
        _task7_lazy_pattern_preset(pattern=r"^sig$"),
        source_paths=(source_path,),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({}, loader=loader).run(first_preset, output_dir)
    first_manifest = _task7_manifest(first.manifest_path)
    calls = 0
    expanded_preset = replace(
        first_preset, signal_pattern=r"^(sig|aux)$",
    )

    second = BatchRunner({}, loader=loader).run(
        expanded_preset, output_dir, resume_manifest=first.manifest_path,
    )
    second_manifest = _task7_manifest(second.manifest_path)

    assert calls == 1
    assert {item.signal for item in second.items} == {"sig", "aux"}
    assert len(second_manifest["render_groups"]) == 1
    assert len(second_manifest["render_groups"][0]["members"]) == 2
    _task7_assert_group_member_linkage(second_manifest)
    assert (
        second_manifest["recipe_fingerprint"]
        == first_manifest["recipe_fingerprint"]
    )


def test_lazy_pattern_changed_stat_reloads_and_discovers_new_matching_channel(
    tmp_path, monkeypatch,
):
    """Catch changed-source recovery retaining an obsolete prior task subset."""
    initial = _make_fd(tmp_path, "scope_changed", channels=("sig",), idx=0)
    source_path = str(initial.filepath)
    current = initial
    calls = 0

    def loader(path):
        nonlocal calls
        calls += 1
        assert str(path) == source_path
        return current

    preset = replace(
        _task7_lazy_pattern_preset(pattern=r"^sig"),
        source_paths=(source_path,),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({}, loader=loader).run(preset, output_dir)
    first_manifest = _task7_manifest(first.manifest_path)
    old_data_path = Path(first.items[0].data_path)
    old_data_before = _task7_artifact_snapshot(old_data_path)
    current = _make_fd(
        tmp_path, "scope_changed", channels=("sig", "sig_new"), idx=0,
    )
    _task7_set_mtime(current.filepath, 9_000_000_000)
    calls = 0

    second = BatchRunner({}, loader=loader).run(
        preset, output_dir, resume_manifest=first.manifest_path,
    )
    second_manifest = _task7_manifest(second.manifest_path)

    assert calls == 1
    assert {item.signal for item in second.items} == {"sig", "sig_new"}
    assert _task7_artifact_snapshot(old_data_path) != old_data_before
    assert len(second_manifest["render_groups"]) == 1
    assert len(second_manifest["render_groups"][0]["members"]) == 2
    _task7_assert_group_member_linkage(second_manifest)


def test_lazy_pattern_old_manifest_without_scope_proof_fails_closed_to_load(
    tmp_path, monkeypatch,
):
    """Catch pre-proof manifests being trusted as a complete task universe."""
    fd = _make_fd(tmp_path, "scope_old_manifest", channels=("sig",), idx=0)
    source_path = str(fd.filepath)
    calls = 0

    def loader(path):
        nonlocal calls
        calls += 1
        assert str(path) == source_path
        return fd

    preset = replace(
        _task7_lazy_pattern_preset(pattern=r"^sig$"),
        source_paths=(source_path,),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({}, loader=loader).run(preset, output_dir)

    def remove_scope(payload):
        payload["normalized_recipe"].pop("execution_scope", None)

    old_manifest = _task7_rewrite_manifest(first.manifest_path, remove_scope)
    calls = 0
    second = BatchRunner({}, loader=loader).run(
        preset, output_dir, resume_manifest=old_manifest,
    )

    assert calls == 1
    assert len(second.items) == 1
    _task7_assert_group_member_linkage(_task7_manifest(second.manifest_path))


def test_lazy_pattern_manifest_missing_current_path_tasks_falls_back_to_load(
    tmp_path, monkeypatch,
):
    """Catch complete scope metadata masking omitted task/source facts."""
    files = {}
    for index, name in enumerate(("scope_omit_a", "scope_omit_b")):
        fd = _make_fd(tmp_path, name, channels=("sig",), idx=index)
        files[str(fd.filepath)] = fd
    calls = {path: 0 for path in files}

    def loader(path):
        key = str(path)
        calls[key] += 1
        return files[key]

    preset = replace(
        _task7_lazy_pattern_preset(pattern=r"^sig$"),
        source_paths=tuple(files),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({}, loader=loader).run(preset, output_dir)

    def omit_second_path(payload):
        omitted_source_id = payload["entries"][1]["source_id"]
        payload["entries"] = [
            entry for entry in payload["entries"]
            if entry["source_id"] != omitted_source_id
        ]

    incomplete = _task7_rewrite_manifest(first.manifest_path, omit_second_path)
    calls = {path: 0 for path in files}
    second = BatchRunner({}, loader=loader).run(
        preset, output_dir, resume_manifest=incomplete,
    )
    second_manifest = _task7_manifest(second.manifest_path)

    assert calls == {path: 1 for path in files}
    assert len(second.items) == 2
    assert len(second_manifest["render_groups"]) == 2
    _task7_assert_group_member_linkage(second_manifest)


def test_lazy_pattern_missing_group_image_loads_once_and_keeps_prior_group_plan(
    tmp_path, monkeypatch,
):
    """Catch deleted-image recovery rediscovering or changing legacy scope."""
    fd = _make_fd(tmp_path, "lazy_missing_image", channels=("sig", "aux"), idx=0)
    source_path = str(fd.filepath)
    calls = 0

    def loader(path):
        nonlocal calls
        assert str(path) == source_path
        calls += 1
        return fd

    preset = replace(
        _task7_lazy_pattern_preset(), source_paths=(source_path,),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({}, loader=loader).run(preset, output_dir)
    first_manifest = _task7_manifest(first.manifest_path)
    data_before = {
        item.task_id: _task7_artifact_snapshot(item.data_path)
        for item in first.items
    }
    image_path = Path(first_manifest["render_groups"][0]["artifact"]["path"])
    image_path.unlink()
    calls = 0

    second = BatchRunner({}, loader=loader).run(
        preset, output_dir, resume_manifest=first.manifest_path,
    )

    assert calls == 1
    assert {
        item.task_id: _task7_artifact_snapshot(item.data_path)
        for item in second.items
    } == data_before
    second_group = _task7_manifest(second.manifest_path)["render_groups"][0]
    assert [
        member["task_id"] for member in second_group["members"]
    ] == [
        member["task_id"]
        for member in first_manifest["render_groups"][0]["members"]
    ]
    assert image_path.read_bytes() == b"group-image"


def test_lazy_pattern_changed_member_loads_group_and_preserves_healthy_data(
    tmp_path, monkeypatch,
):
    """Catch changed-source recovery losing the prior channel-group scope."""
    files = {
        str(fd.filepath): fd
        for fd in (
            _make_fd(tmp_path, "lazy_changed_a", channels=("sig",), idx=0),
            _make_fd(tmp_path, "lazy_changed_b", channels=("sig",), idx=1),
        )
    }
    calls = {path: 0 for path in files}

    def loader(path):
        key = str(path)
        calls[key] += 1
        return files[key]

    preset = replace(
        _task7_lazy_pattern_preset(group_by="channel"),
        source_paths=tuple(files),
    )
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({}, loader=loader).run(preset, output_dir)
    first_manifest = _task7_manifest(first.manifest_path)
    data_paths = {item.file_id: Path(item.data_path) for item in first.items}
    data_before = {
        source_id: _task7_artifact_snapshot(path)
        for source_id, path in data_paths.items()
    }
    changed_source = tuple(files)[0]
    _task7_touch_with_bytes(
        changed_source,
        Path(changed_source).read_bytes() + b"\n",
        mtime_ns=7_000_000_000,
    )
    calls = {path: 0 for path in files}

    second = BatchRunner({}, loader=loader).run(
        preset, output_dir, resume_manifest=first.manifest_path,
    )

    assert calls == {path: 1 for path in files}
    data_after = {
        item.file_id: _task7_artifact_snapshot(item.data_path)
        for item in second.items
    }
    assert data_after[changed_source] != data_before[changed_source]
    healthy_source = tuple(files)[1]
    assert data_after[healthy_source] == data_before[healthy_source]
    second_group = _task7_manifest(second.manifest_path)["render_groups"][0]
    assert [
        member["task_id"] for member in second_group["members"]
    ] == [
        member["task_id"]
        for member in first_manifest["render_groups"][0]["members"]
    ]


@pytest.mark.parametrize("field", ("size", "mtime_ns"))
@pytest.mark.parametrize("invalid_value", (True, 1.5, "1"))
def test_grouped_data_resume_rejects_noncanonical_source_stat_types(
    tmp_path, monkeypatch, field, invalid_value,
):
    """Catch bool or scalar coercion turning malformed source facts valid."""
    fd = _make_fd(tmp_path, "malformed_source", channels=("sig",), idx=0)
    if field == "size":
        Path(fd.filepath).write_bytes(b"x")
    else:
        _task7_set_mtime(fd.filepath, 1)
    preset = replace(_task7_resume_preset(signals=("sig",)), file_ids=(0,))
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(preset, output_dir)
    data_path = Path(first.items[0].data_path)
    _task7_set_mtime(data_path, 8_000_000_000)
    before = _task7_artifact_snapshot(data_path)

    def mutate(payload):
        payload["entries"][0]["source"][field] = invalid_value

    malformed = _task7_rewrite_manifest(first.manifest_path, mutate)
    second = BatchRunner({0: fd}).run(
        preset, output_dir, resume_manifest=malformed,
    )

    after = _task7_artifact_snapshot(data_path)
    assert second.items[0].status == "done"
    assert after[0] == before[0]
    assert after[1] != before[1]


@pytest.mark.parametrize("invalid_kind", ("bad_path", "bad_checksum"))
@pytest.mark.parametrize("invalid_first", (True, False))
def test_duplicate_task_id_resume_binds_the_checksum_matched_candidate(
    tmp_path, monkeypatch, invalid_kind, invalid_first,
):
    """Catch a valid duplicate scan returning a different candidate's artifact."""
    import copy

    fd = _make_fd(tmp_path, "duplicate_candidate", channels=("sig",), idx=0)
    preset = replace(_task7_resume_preset(signals=("sig",)), file_ids=(0,))
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(preset, output_dir)
    valid_path = str(Path(first.items[0].data_path).resolve(strict=False))

    def mutate(payload):
        valid = payload["entries"][0]
        invalid = copy.deepcopy(valid)
        invalid_artifact = invalid["artifacts"]["data"]
        if invalid_kind == "bad_path":
            invalid_artifact["path"] = str(
                (output_dir / "missing-duplicate.csv").resolve(strict=False)
            )
        else:
            bad_copy = output_dir / "bad-checksum-duplicate.csv"
            bad_copy.write_bytes(Path(valid_path).read_bytes())
            invalid_artifact["path"] = str(bad_copy.resolve(strict=False))
            invalid_artifact["sha256"] = "0" * 64
        payload["entries"] = (
            [invalid, valid] if invalid_first else [valid, invalid]
        )

    duplicate_manifest = _task7_rewrite_manifest(first.manifest_path, mutate)
    second = BatchRunner({0: fd}).run(
        preset, output_dir, resume_manifest=duplicate_manifest,
    )

    assert second.items[0].status == "resumed"
    assert str(Path(second.items[0].data_path).resolve(strict=False)) == valid_path


def test_grouped_resume_missing_image_rerenders_group_without_touching_csvs(
    tmp_path, monkeypatch,
):
    """Catch a missing group image causing healthy task data rewrites."""
    fd = _make_fd(tmp_path, "missing_group_image", channels=("sig", "aux"), idx=0)
    preset = replace(_task7_resume_preset(), file_ids=(0,))
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(preset, output_dir)
    manifest = _task7_manifest(first.manifest_path)
    data_paths = [Path(item.data_path) for item in first.items]
    before_data = [_task7_artifact_snapshot(path) for path in data_paths]
    image_path = Path(manifest["render_groups"][0]["artifact"]["path"])
    image_path.unlink()

    second = BatchRunner({0: fd}).run(
        preset, output_dir, resume_manifest=first.manifest_path,
    )

    assert [_task7_artifact_snapshot(path) for path in data_paths] == before_data
    assert image_path.read_bytes() == b"group-image"
    assert [item.status for item in second.items] == ["resumed", "resumed"]


def test_grouped_resume_one_changed_source_rewrites_only_its_data_and_group_image(
    tmp_path, monkeypatch,
):
    """Catch member source invalidation leaking onto a healthy member's CSV."""
    files = {
        0: _make_fd(tmp_path, "changed_a", channels=("sig",), idx=0),
        1: _make_fd(tmp_path, "changed_b", channels=("sig",), idx=1),
    }
    preset = replace(
        _task7_resume_preset(group_by="channel", signals=("sig",)),
        file_ids=(0, 1),
    )
    calls = 0

    def image(payload, path, **kwargs):
        nonlocal calls
        calls += 1
        Path(path).write_bytes(f"image-{calls}".encode())
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(image))
    output_dir = tmp_path / "out"
    first = BatchRunner(files).run(preset, output_dir)
    manifest = _task7_manifest(first.manifest_path)
    data_paths = [Path(item.data_path) for item in first.items]
    image_path = Path(manifest["render_groups"][0]["artifact"]["path"])
    before_data = [_task7_artifact_snapshot(path) for path in data_paths]
    before_image = _task7_artifact_snapshot(image_path)
    source_path = Path(files[0].filepath)
    _task7_touch_with_bytes(source_path, source_path.read_bytes() + b"\n")

    second = BatchRunner(files).run(
        preset, output_dir, resume_manifest=first.manifest_path,
    )

    after_data = [_task7_artifact_snapshot(path) for path in data_paths]
    assert after_data[0] != before_data[0]
    assert after_data[1] == before_data[1]
    assert _task7_artifact_snapshot(image_path) != before_image
    assert [item.status for item in second.items] == ["done", "resumed"]


def _task7_rewrite_manifest(path, mutate):
    import json
    from mf4_analyzer.batch_manifest import derive_summary

    payload = _task7_manifest(path)
    mutate(payload)
    payload["summary"] = derive_summary(payload["entries"])
    rewritten = Path(path).with_name(f"retry-{Path(path).name}")
    rewritten.write_text(json.dumps(payload), encoding="utf-8")
    return rewritten


def test_grouped_retry_failed_member_expands_payload_but_preserves_healthy_csv(
    tmp_path, monkeypatch,
):
    """Catch retry group expansion rewriting a healthy member's task data."""
    fd = _make_fd(tmp_path, "retry_member", channels=("sig", "aux"), idx=0)
    preset = replace(_task7_resume_preset(), file_ids=(0,))
    render_calls = 0

    def image(payload, path, **kwargs):
        nonlocal render_calls
        render_calls += 1
        Path(path).write_bytes(f"retry-image-{render_calls}".encode())
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(image))
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(preset, output_dir)
    paths = [Path(item.data_path) for item in first.items]
    before_healthy = _task7_artifact_snapshot(paths[1])
    _task7_touch_with_bytes(paths[0], b"failed-data")

    def mark_failed(payload):
        payload["entries"][0]["status"] = "failed"
        payload["render_groups"][0]["status"] = "partial"

    retry_manifest = _task7_rewrite_manifest(first.manifest_path, mark_failed)
    second = BatchRunner({0: fd}).run(
        preset, output_dir, retry_failed_manifest=retry_manifest,
    )

    assert _task7_artifact_snapshot(paths[1]) == before_healthy
    assert paths[0].read_bytes() != b"failed-data"
    assert [item.status for item in second.items] == ["done", "resumed"]
    assert render_calls == 2


@pytest.mark.parametrize("group_status", ("failed", "partial", "blocked", "cancelled"))
def test_grouped_retry_scope_includes_terminal_group_with_done_members(
    tmp_path, monkeypatch, group_status,
):
    """Catch group-only retry scope being discarded as an empty task scope."""
    fd = _make_fd(tmp_path, f"retry_group_{group_status}", channels=("sig",), idx=0)
    preset = replace(
        _task7_resume_preset(signals=("sig",)), file_ids=(0,),
    )
    calls = 0

    def image(payload, path, **kwargs):
        nonlocal calls
        calls += 1
        Path(path).write_bytes(f"group-status-{calls}".encode())
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(image))
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(preset, output_dir)
    data_path = Path(first.items[0].data_path)
    before_data = _task7_artifact_snapshot(data_path)

    def mutate(payload):
        payload["render_groups"][0]["status"] = group_status

    retry_manifest = _task7_rewrite_manifest(first.manifest_path, mutate)
    second = BatchRunner({0: fd}).run(
        preset, output_dir, retry_failed_manifest=retry_manifest,
    )

    assert second.status == "done"
    assert second.items[0].status == "resumed"
    assert _task7_artifact_snapshot(data_path) == before_data
    assert calls == 2


@pytest.mark.parametrize(
    ("group_status", "degraded_reason"),
    (("partial", ""), ("degraded", "renderer missing")),
)
def test_partial_and_degraded_groups_are_never_complete_resume_hits(
    tmp_path, monkeypatch, group_status, degraded_reason,
):
    """Catch non-complete group provenance suppressing required rerendering."""
    fd = _make_fd(tmp_path, f"noncomplete_{group_status}", channels=("sig",), idx=0)
    preset = replace(_task7_resume_preset(signals=("sig",)), file_ids=(0,))
    calls = 0

    def image(payload, path, **kwargs):
        nonlocal calls
        calls += 1
        Path(path).write_bytes(f"noncomplete-{calls}".encode())
        return Path(path)

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(image))
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(preset, output_dir)
    first_manifest = _task7_manifest(first.manifest_path)
    data_path = Path(first.items[0].data_path)
    image_path = Path(first_manifest["render_groups"][0]["artifact"]["path"])
    before_data = _task7_artifact_snapshot(data_path)
    before_image = _task7_artifact_snapshot(image_path)

    def mutate(payload):
        group = payload["render_groups"][0]
        group["status"] = group_status
        group["degraded_reason"] = degraded_reason

    resume_manifest = _task7_rewrite_manifest(first.manifest_path, mutate)
    second = BatchRunner({0: fd}).run(
        preset, output_dir, resume_manifest=resume_manifest,
    )

    assert second.status == "done"
    assert second.items[0].status == "resumed"
    assert _task7_artifact_snapshot(data_path) == before_data
    assert _task7_artifact_snapshot(image_path) != before_image
    assert calls == 2


@pytest.mark.parametrize(
    ("policy", "task_status", "same_path"),
    (("error", "failed", False), ("skip", "skipped", False),
     ("overwrite", "done", True), ("auto_number", "done", False)),
)
def test_grouped_task_data_conflict_policy_is_independent_from_group_image(
    tmp_path, monkeypatch, policy, task_status, same_path,
):
    """Catch data conflict status suppressing an otherwise complete payload."""
    fd = _make_fd(tmp_path, f"data_conflict_{policy}", channels=("sig",), idx=0)
    seed = replace(_task7_resume_preset(signals=("sig",)), file_ids=(0,))
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(seed, output_dir)
    old_data = Path(first.items[0].data_path)
    before_data = _task7_artifact_snapshot(old_data)
    old_image = Path(_task7_manifest(first.manifest_path)["render_groups"][0]["artifact"]["path"])
    old_image.unlink()
    preset = replace(
        seed,
        outputs=replace(
            seed.outputs, conflict_policy=policy, resume_policy="none",
        ),
    )

    second = BatchRunner({0: fd}).run(preset, output_dir)
    group = _task7_manifest(second.manifest_path)["render_groups"][0]

    assert second.items[0].status == task_status
    assert group["status"] == "done"
    assert Path(group["artifact"]["path"]).is_file()
    if task_status == "done":
        assert (Path(second.items[0].data_path) == old_data) is same_path
        if same_path:
            assert _task7_artifact_snapshot(old_data) != before_data
        else:
            assert _task7_artifact_snapshot(old_data) == before_data
    else:
        assert second.items[0].data_path is None
        assert second.items[0].artifact_facts == {}
        assert _task7_artifact_snapshot(old_data) == before_data


def test_grouped_data_only_error_conflict_stops_before_analysis(tmp_path, monkeypatch):
    """Catch a data-only conflict loading and analyzing a source needlessly."""
    fd = _make_fd(tmp_path, "data_only_error", channels=("sig",), idx=0)
    seed = AnalysisPreset.from_current_single(
        name="seed data conflict", method="time", signal=(0, "sig"),
        params={"render_group_by": "source"},
        outputs=BatchOutput(export_data=True, export_image=False),
    )
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(seed, output_dir)
    preset = replace(seed, outputs=replace(seed.outputs, conflict_policy="error"))

    def forbidden(*args, **kwargs):
        pytest.fail("data-only error conflict must stop before analysis")

    monkeypatch.setattr(BatchRunner, "_compute_preprocessed_time_dataframe", forbidden)
    second = BatchRunner({0: fd}).run(preset, output_dir)

    assert first.items[0].data_path
    assert second.items[0].status == "failed"


@pytest.mark.parametrize(
    ("policy", "group_status", "same_path"),
    (("error", "failed", False), ("skip", "skipped", False),
     ("overwrite", "done", True), ("auto_number", "done", False)),
)
def test_grouped_image_conflict_policy_runs_after_task_data_transaction(
    tmp_path, monkeypatch, policy, group_status, same_path,
):
    """Catch group-image conflicts rolling back or impersonating task data."""
    fd = _make_fd(tmp_path, f"image_conflict_{policy}", channels=("sig",), idx=0)
    seed = replace(_task7_resume_preset(signals=("sig",)), file_ids=(0,))
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(seed, output_dir)
    first_manifest = _task7_manifest(first.manifest_path)
    old_image = Path(first_manifest["render_groups"][0]["artifact"]["path"])
    before_image = _task7_artifact_snapshot(old_image)
    Path(first.items[0].data_path).unlink()
    preset = replace(
        seed,
        outputs=replace(
            seed.outputs, conflict_policy=policy, resume_policy="none",
        ),
    )

    second = BatchRunner({0: fd}).run(preset, output_dir)
    group = _task7_manifest(second.manifest_path)["render_groups"][0]

    assert second.items[0].status == "done"
    assert Path(second.items[0].data_path).is_file()
    assert group["status"] == group_status
    if group_status == "done":
        assert (Path(group["artifact"]["path"]) == old_image) is same_path
        if same_path:
            assert _task7_artifact_snapshot(old_image) != before_image
        else:
            assert _task7_artifact_snapshot(old_image) == before_image
    else:
        assert group["artifact"] is None
        assert _task7_artifact_snapshot(old_image) == before_image


@pytest.mark.parametrize(
    (
        "limit_name", "limit_value", "member_count", "layout",
        "expected_group_status", "expected_save_calls",
    ),
    (
        ("_MAX_GROUP_MEMBERS", 1, 2, "overlay", "blocked", 0),
        ("_MAX_SUBPLOT_PANELS", 1, 2, "subplot", "blocked", 0),
        ("_MAX_GROUP_MEMBERS", 33, 33, "overlay", "done", 66),
        ("_MAX_SUBPLOT_PANELS", 9, 9, "subplot", "done", 18),
    ),
)
def test_runner_group_precheck_uses_spool_limit_authority_before_first_save(
    tmp_path,
    monkeypatch,
    limit_name,
    limit_value,
    member_count,
    layout,
    expected_group_status,
    expected_save_calls,
):
    """Catch duplicated runner literals diverging from patched spool limits."""
    import mf4_analyzer.batch_series_spool as spool_module
    from mf4_analyzer.batch_manifest import load_batch_manifest

    channels = tuple(f"limit_sig_{index}" for index in range(member_count))
    fd = _make_fd(tmp_path, "limit_authority", channels=channels, idx=0)
    preset = AnalysisPreset.free_config(
        name="spool limit authority",
        method="time",
        target_signals=channels,
        params={"render_group_by": "source", "render_layout": layout},
        outputs=BatchOutput(export_data=False, export_image=True),
    )
    save_calls = []
    real_save = spool_module.np.save

    def recording_save(*args, **kwargs):
        save_calls.append(Path(args[0]))
        return real_save(*args, **kwargs)

    monkeypatch.setattr(spool_module, limit_name, limit_value)
    monkeypatch.setattr(spool_module.np, "save", recording_save)
    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(_task6_fake_image))

    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")

    group = load_batch_manifest(result.manifest_path)["render_groups"][0]
    assert group["status"] == expected_group_status
    assert len(save_calls) == expected_save_calls


def test_batch_runner_module_has_no_gui_render_dependencies():
    import inspect
    import mf4_analyzer.batch as batch_module

    source = inspect.getsource(batch_module)
    for forbidden in ("PyQt", "pyqtgraph", "QApplication"):
        assert forbidden not in source


def _make_frf_fd(
    tmp_path,
    name="frf",
    *,
    gain=2.0,
    fs=100.0,
    samples=400,
    output_channels=("response",),
):
    t = np.arange(samples, dtype=float) / fs
    command = np.sin(2.0 * np.pi * 5.0 * t)
    values = {"Time": t, "command": command}
    units = {"command": "V"}
    for index, channel in enumerate(output_channels, start=1):
        values[channel] = gain * index * command
        units[channel] = "N"
    frame = pd.DataFrame(values)
    return FileData(
        tmp_path / f"{name}.csv",
        frame,
        list(frame.columns),
        units,
        idx=0,
    )


def _frf_preset(
    *,
    export_data=True,
    export_image=False,
    output_channels=("response",),
    param_updates=None,
):
    from mf4_analyzer.batch_types import FrfPairRule

    return AnalysisPreset.free_config(
        name="FRF batch",
        method="frf",
        frf_pair_rules=(FrfPairRule("command", tuple(output_channels)),),
        params={
            "estimator": "h1",
            "window": "hanning",
            "periodic_window": True,
            "t_win_s": 0.5,
            "overlap": 0.5,
            "nfft_mode": "auto",
            "detrend": "none",
            **dict(param_updates or {}),
        },
        outputs=BatchOutput(
            export_data=export_data,
            export_image=export_image,
        ),
    )


def test_batch_supported_methods_include_frf():
    assert "frf" in BatchRunner.SUPPORTED_METHODS


def test_batch_frf_data_only_runs_directional_pair_and_fixed_export(tmp_path):
    from mf4_analyzer.batch_compute import FRF_EXPORT_COLUMNS
    from mf4_analyzer.batch_manifest import load_batch_manifest

    result = BatchRunner({0: _make_frf_fd(tmp_path)}).run(
        _frf_preset(), tmp_path / "out",
    )

    assert result.status == "done"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.status == "done"
    assert item.signal == "response / command"
    assert (item.input_signal, item.output_signal) == ("command", "response")
    exported = pd.read_csv(item.data_path)
    assert tuple(exported.columns) == FRF_EXPORT_COLUMNS
    manifest = load_batch_manifest(result.manifest_path)
    assert manifest["entries"][0]["frf_pair"] == {
        "input": {"channel": "command", "unit": "V"},
        "output": {"channel": "response", "unit": "N"},
    }


def test_batch_frf_xlsx_preserves_the_same_fixed_column_contract(tmp_path):
    from dataclasses import replace
    from mf4_analyzer.batch_compute import FRF_EXPORT_COLUMNS

    preset = _frf_preset()
    preset = replace(
        preset,
        outputs=replace(preset.outputs, data_format="xlsx"),
    )

    result = BatchRunner({0: _make_frf_fd(tmp_path)}).run(
        preset, tmp_path / "out",
    )

    assert result.status == "done"
    assert Path(result.items[0].data_path).suffix == ".xlsx"
    assert tuple(pd.read_excel(result.items[0].data_path).columns) == (
        FRF_EXPORT_COLUMNS
    )


def test_batch_frf_resume_uses_hashed_identity_not_readable_pair_label(tmp_path):
    from copy import deepcopy
    from dataclasses import replace
    from mf4_analyzer.batch_manifest import load_batch_manifest

    fd = _make_frf_fd(tmp_path)
    output_dir = tmp_path / "out"
    first = BatchRunner({0: fd}).run(_frf_preset(), output_dir)
    manifest = deepcopy(load_batch_manifest(first.manifest_path))
    manifest["entries"][0]["channel"] = "display label intentionally changed"
    preset = _frf_preset()
    preset = replace(
        preset,
        outputs=replace(preset.outputs, resume_policy="manifest"),
    )

    resumed = BatchRunner({0: fd}).run(
        preset, output_dir, resume_manifest=manifest,
    )

    assert resumed.status == "done"
    assert resumed.items[0].status == "resumed"
    assert resumed.items[0].task_id == first.items[0].task_id


def test_batch_frf_full_preflight_precedes_first_artifact_reservation(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch as batch_module

    trace = []
    real_prepare = batch_module.batch_compute.prepare_frf_task
    real_reserve = batch_module.reserve_output_paths

    def prepare(*args, **kwargs):
        trace.append("preflight")
        return real_prepare(*args, **kwargs)

    def reserve(*args, **kwargs):
        trace.append("reserve")
        return real_reserve(*args, **kwargs)

    monkeypatch.setattr(batch_module.batch_compute, "prepare_frf_task", prepare)
    monkeypatch.setattr(batch_module, "reserve_output_paths", reserve)
    result = BatchRunner({
        0: _make_frf_fd(tmp_path, "a"),
        1: _make_frf_fd(tmp_path, "b"),
    }).run(_frf_preset(), tmp_path / "out")

    assert result.status == "done"
    assert trace == ["preflight", "preflight", "reserve", "reserve"]


@pytest.mark.parametrize(
    ("error_type", "message"),
    [
        (ValueError, "programming reservation contract defect"),
        (ImportError, "unexpected reservation import defect"),
    ],
)
def test_batch_frf_second_reservation_programming_error_releases_first_token(
    tmp_path, monkeypatch, error_type, message,
):
    import mf4_analyzer.batch as batch_module

    real_reserve = batch_module.reserve_output_paths
    reservation_calls = []

    def reserve(*args, **kwargs):
        reservation_calls.append((args, kwargs))
        if len(reservation_calls) == 2:
            raise error_type(message)
        return real_reserve(*args, **kwargs)

    monkeypatch.setattr(batch_module, "reserve_output_paths", reserve)
    output_dir = tmp_path / "out"

    with pytest.raises(error_type, match=message):
        BatchRunner({
            0: _make_frf_fd(tmp_path, "a"),
            1: _make_frf_fd(tmp_path, "b"),
        }).run(_frf_preset(), output_dir)

    assert len(reservation_calls) == 2
    assert list(output_dir.glob(".*.batch-reserve")) == []
    assert list(output_dir.glob("*.csv")) == []


def test_batch_frf_oversized_manual_nfft_fails_before_any_reservation(
    tmp_path, monkeypatch,
):
    from dataclasses import replace
    import mf4_analyzer.batch as batch_module

    preset = _frf_preset()
    preset = replace(
        preset,
        params={
            **preset.params,
            "nfft_mode": "manual",
            "nfft": 4_194_304,
        },
    )
    reservation_calls = []

    def forbidden_reserve(*args, **kwargs):
        reservation_calls.append((args, kwargs))
        pytest.fail("oversized FRF request must fail before reservation")

    monkeypatch.setattr(batch_module, "reserve_output_paths", forbidden_reserve)
    output_dir = tmp_path / "out"

    result = BatchRunner({0: _make_frf_fd(tmp_path)}).run(preset, output_dir)

    assert result.status == "blocked"
    assert [item.status for item in result.items] == ["failed"]
    assert "temporary complex" in result.items[0].message
    assert "64 MiB" in result.items[0].message
    assert reservation_calls == []
    assert list(output_dir.glob(".*.batch-reserve")) == []
    assert list(output_dir.glob("*.csv")) == []


def test_batch_frf_each_task_has_exactly_one_started_and_terminal_event(tmp_path):
    events = []
    result = BatchRunner({
        0: _make_frf_fd(tmp_path, "a"),
        1: _make_frf_fd(tmp_path, "b"),
    }).run(_frf_preset(), tmp_path / "out", on_event=events.append)

    assert result.status == "done"
    task_events = [event for event in events if event.task_index is not None]
    assert [(event.task_index, event.kind) for event in task_events] == [
        (1, "task_started"), (1, "task_done"),
        (2, "task_started"), (2, "task_done"),
    ]


def test_batch_frf_data_plus_image_publishes_one_coordinated_artifact_set(
    qapp, tmp_path,
):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    result = BatchRunner({0: _make_frf_fd(tmp_path)}).run(
        _frf_preset(export_data=True, export_image=True), tmp_path / "out",
    )

    assert result.status == "done"
    assert Path(result.items[0].data_path).is_file()
    assert Path(result.items[0].image_path).is_file()
    assert result.items[0].degraded_reason == ""
    assert Path(result.items[0].data_path).stem == Path(
        result.items[0].image_path
    ).stem
    entry = load_batch_manifest(result.manifest_path)["entries"][0]
    assert set(entry["artifacts"]) == {"data", "image"}
    assert all(
        artifact["checksum_status"] == "complete"
        for artifact in entry["artifacts"].values()
    )


def test_batch_frf_image_only_publishes_png(qapp, tmp_path):
    events = []
    result = BatchRunner({0: _make_frf_fd(tmp_path)}).run(
        _frf_preset(export_data=False, export_image=True),
        tmp_path / "out",
        on_event=events.append,
    )

    assert result.status == "done"
    assert result.items[0].data_path is None
    assert Path(result.items[0].image_path).is_file()
    assert Path(result.items[0].image_path).read_bytes().startswith(b"\x89PNG")
    assert [event.kind for event in events if event.task_index is not None] == [
        "task_started", "task_done",
    ]


def test_batch_frf_source_group_renders_one_input_three_outputs(qapp, tmp_path):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    outputs = ("response-a", "response-b", "response-c")
    preset = _frf_preset(
        export_data=True,
        export_image=True,
        output_channels=outputs,
        param_updates={"render_group_by": "source"},
    )
    events = []
    result = BatchRunner({
        0: _make_frf_fd(tmp_path, output_channels=outputs),
    }).run(preset, tmp_path / "out", on_event=events.append)

    assert result.status == "done"
    assert [item.output_signal for item in result.items] == list(outputs)
    assert all(Path(item.data_path).is_file() for item in result.items)
    assert all(item.image_path is None for item in result.items)
    assert len(result.render_groups) == 1
    assert result.render_groups[0].status == "done"
    assert Path(result.render_groups[0].image_path).is_file()
    manifest_group = load_batch_manifest(result.manifest_path)["render_groups"][0]
    assert manifest_group["group_by"] == "source"
    assert len(manifest_group["members"]) == 3
    assert manifest_group["artifact"]["checksum_status"] == "complete"
    task_events = [event for event in events if event.task_index is not None]
    assert [(event.task_index, event.kind) for event in task_events] == [
        (1, "task_started"),
        (2, "task_started"),
        (3, "task_started"),
        (1, "task_done"),
        (2, "task_done"),
        (3, "task_done"),
    ]
    assert all(
        Path(event.image_path) == Path(result.render_groups[0].image_path)
        for event in task_events if event.kind == "task_done"
    )


def test_batch_frf_channel_group_renders_same_pair_across_three_sources(
    qapp, tmp_path,
):
    from mf4_analyzer.batch_manifest import load_batch_manifest

    preset = _frf_preset(
        export_data=False,
        export_image=True,
        param_updates={"render_group_by": "channel"},
    )
    result = BatchRunner({
        index: _make_frf_fd(tmp_path, f"source-{index}", gain=index + 1.0)
        for index in range(3)
    }).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert len(result.items) == 3
    assert len(result.render_groups) == 1
    assert Path(result.render_groups[0].image_path).is_file()
    group = load_batch_manifest(result.manifest_path)["render_groups"][0]
    assert group["group_by"] == "channel"
    assert len(group["members"]) == 3


def test_batch_frf_group_preview_and_run_share_identity_members_and_png_bytes(
    qapp, tmp_path,
):
    outputs = ("response-a", "response-b", "response-c")
    preset = _frf_preset(
        export_data=False,
        export_image=True,
        output_channels=outputs,
        param_updates={"render_group_by": "source"},
    )
    runner = BatchRunner({
        0: _make_frf_fd(tmp_path, output_channels=outputs),
    })
    output_preview = runner.preview_outputs(preset, tmp_path / "out")

    preview = runner.preview_group(
        preset,
        output_preview.representative_group.group_id,
        tmp_path / "preview",
    )
    result = runner.run(preset, tmp_path / "out")

    assert preview.status == "done"
    assert preview.group_id == result.render_groups[0].group_id
    assert Path(preview.image_path).read_bytes() == Path(
        result.render_groups[0].image_path
    ).read_bytes()


def test_batch_frf_group_cancellation_releases_pre_reserved_image(
    qapp, tmp_path, monkeypatch,
):
    import threading
    import mf4_analyzer.batch as batch_module

    outputs = ("response-a", "response-b", "response-c")
    preset = _frf_preset(
        export_data=True,
        export_image=True,
        output_channels=outputs,
        param_updates={"render_group_by": "source"},
    )
    token = threading.Event()
    real_compute = batch_module.batch_compute.compute_prepared_frf
    real_reserve = batch_module.reserve_output_paths
    reservations = []

    def cancel_after_first(*args, **kwargs):
        computed = real_compute(*args, **kwargs)
        token.set()
        return computed

    def reserve(*args, **kwargs):
        reservations.append(tuple(args[2]))
        return real_reserve(*args, **kwargs)

    monkeypatch.setattr(
        batch_module.batch_compute, "compute_prepared_frf", cancel_after_first,
    )
    monkeypatch.setattr(batch_module, "reserve_output_paths", reserve)
    output_dir = tmp_path / "out"

    result = BatchRunner({
        0: _make_frf_fd(tmp_path, output_channels=outputs),
    }).run(preset, output_dir, cancel_token=token)

    assert result.status == "cancelled"
    assert ("png",) in reservations
    assert list(output_dir.glob(".*.batch-reserve")) == []
    assert list(output_dir.glob("*.png")) == []


def test_batch_frf_unexpected_renderer_probe_import_error_propagates_before_reserve(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch as batch_module

    def broken_probe():
        raise ImportError(
            "internal FRF renderer contract defect",
            name="mf4_analyzer.ui.plot_helpers",
        )

    def forbidden_reserve(*args, **kwargs):
        pytest.fail("programming renderer probe errors must precede reservation")

    monkeypatch.setattr(
        BatchRunner, "_probe_image_backend", staticmethod(broken_probe),
    )
    monkeypatch.setattr(
        batch_module, "reserve_output_paths", forbidden_reserve,
    )

    with pytest.raises(ImportError, match="internal FRF renderer"):
        BatchRunner({0: _make_frf_fd(tmp_path)}).run(
            _frf_preset(export_data=True, export_image=True),
            tmp_path / "out",
        )


def test_batch_frf_optional_renderer_absence_degrades_only_requested_image(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch as batch_module

    real_reserve = batch_module.reserve_output_paths
    reservations = []

    def missing_backend():
        raise ModuleNotFoundError("renderer unavailable", name="pyqtgraph")

    def reserve(*args, **kwargs):
        reservations.append(tuple(args[2]))
        return real_reserve(*args, **kwargs)

    monkeypatch.setattr(
        BatchRunner, "_probe_image_backend", staticmethod(missing_backend),
    )
    monkeypatch.setattr(batch_module, "reserve_output_paths", reserve)

    result = BatchRunner({0: _make_frf_fd(tmp_path)}).run(
        _frf_preset(export_data=True, export_image=True), tmp_path / "out",
    )

    assert result.status == "partial"
    assert Path(result.items[0].data_path).is_file()
    assert result.items[0].image_path is None
    assert result.items[0].degraded_reason
    assert reservations == [("csv",)]


def test_batch_frf_image_only_optional_renderer_absence_never_reserves_or_computes(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch as batch_module

    def missing_backend():
        raise ModuleNotFoundError("renderer unavailable", name="pyqtgraph")

    def forbidden(*args, **kwargs):
        pytest.fail("missing image-only backend must not reserve or compute")

    monkeypatch.setattr(
        BatchRunner, "_probe_image_backend", staticmethod(missing_backend),
    )
    monkeypatch.setattr(batch_module, "reserve_output_paths", forbidden)
    monkeypatch.setattr(
        batch_module.batch_compute, "compute_prepared_frf", forbidden,
    )

    result = BatchRunner({0: _make_frf_fd(tmp_path)}).run(
        _frf_preset(export_data=False, export_image=True), tmp_path / "out",
    )

    assert result.status == "blocked"
    assert [item.status for item in result.items] == ["failed"]


def test_batch_frf_renderer_programming_value_error_propagates_and_rolls_back_set(
    qapp, tmp_path, monkeypatch,
):
    def defect(*args, **kwargs):
        raise ValueError("unexpected FRF renderer payload defect")

    monkeypatch.setattr(BatchRunner, "_write_image", staticmethod(defect))
    output_dir = tmp_path / "out"

    with pytest.raises(ValueError, match="renderer payload defect"):
        BatchRunner({0: _make_frf_fd(tmp_path)}).run(
            _frf_preset(export_data=True, export_image=True), output_dir,
        )

    assert list(output_dir.glob(".*.batch-reserve")) == []
    assert list(output_dir.glob("*.csv")) == []
    assert list(output_dir.glob("*.png")) == []


def test_batch_frf_none_data_image_resume_reuses_coordinated_artifacts(
    qapp, tmp_path, monkeypatch,
):
    from dataclasses import replace
    import mf4_analyzer.batch as batch_module

    output_dir = tmp_path / "out"
    first = BatchRunner({0: _make_frf_fd(tmp_path)}).run(
        _frf_preset(export_data=True, export_image=True), output_dir,
    )
    preset = _frf_preset(export_data=True, export_image=True)
    preset = replace(
        preset,
        outputs=replace(preset.outputs, resume_policy="manifest"),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("checksum-proven FRF artifacts must not recompute")

    monkeypatch.setattr(
        batch_module.batch_compute, "compute_prepared_frf", forbidden,
    )
    second = BatchRunner({0: _make_frf_fd(tmp_path)}).run(
        preset, output_dir, resume_manifest=first.manifest_path,
    )

    assert second.status == "done"
    assert [item.status for item in second.items] == ["resumed"]
    assert second.items[0].data_path == first.items[0].data_path
    assert second.items[0].image_path == first.items[0].image_path


def test_batch_frf_group_image_resume_reuses_group_without_compute(
    qapp, tmp_path, monkeypatch,
):
    from dataclasses import replace
    import mf4_analyzer.batch as batch_module

    outputs = ("response-a", "response-b", "response-c")
    base = _frf_preset(
        export_data=False,
        export_image=True,
        output_channels=outputs,
        param_updates={"render_group_by": "source"},
    )
    files = {0: _make_frf_fd(tmp_path, output_channels=outputs)}
    output_dir = tmp_path / "out"
    first = BatchRunner(files).run(base, output_dir)
    preset = replace(
        base,
        outputs=replace(base.outputs, resume_policy="manifest"),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("checksum-proven FRF group must not recompute")

    monkeypatch.setattr(
        batch_module.batch_compute, "compute_prepared_frf", forbidden,
    )
    second = BatchRunner(files).run(
        preset, output_dir, resume_manifest=first.manifest_path,
    )

    assert second.status == "done"
    assert [item.status for item in second.items] == ["resumed"] * 3
    assert len(second.render_groups) == 1
    assert second.render_groups[0].message == "manifest-proven group resume"
    assert second.render_groups[0].image_path == first.render_groups[0].image_path


def test_batch_frf_none_conflict_error_keeps_coordinated_set_unchanged(
    qapp, tmp_path,
):
    from dataclasses import replace

    preset = _frf_preset(export_data=True, export_image=True)
    preset = replace(
        preset,
        outputs=replace(preset.outputs, conflict_policy="error"),
    )
    output_dir = tmp_path / "out"
    first = BatchRunner({0: _make_frf_fd(tmp_path)}).run(preset, output_dir)
    original_data = Path(first.items[0].data_path).read_bytes()
    original_image = Path(first.items[0].image_path).read_bytes()

    second = BatchRunner({0: _make_frf_fd(tmp_path)}).run(preset, output_dir)

    assert second.status == "blocked"
    assert [item.status for item in second.items] == ["failed"]
    assert Path(first.items[0].data_path).read_bytes() == original_data
    assert Path(first.items[0].image_path).read_bytes() == original_image
    assert list(output_dir.glob(".*.batch-reserve")) == []


def test_batch_frf_preview_is_metadata_only_and_estimated(tmp_path):
    from dataclasses import replace

    source_path = str(tmp_path / "lazy.csv")
    load_calls = []

    def loader(path):
        load_calls.append(path)
        return _make_frf_fd(tmp_path, "loaded")

    preset = replace(
        _frf_preset(export_data=True, export_image=True),
        file_paths=(source_path,),
    )
    preview = BatchRunner({}, loader=loader).preview_outputs(
        preset,
        tmp_path / "out",
        source_channels={source_path: ("command", "response")},
    )

    assert preview.estimated is True
    assert preview.task_count == 1
    assert preview.artifact_count == 2
    assert load_calls == []


def test_batch_frf_representative_preview_loads_only_selected_group_and_computes(
    tmp_path,
):
    from dataclasses import replace

    source_paths = (str(tmp_path / "a.csv"), str(tmp_path / "b.csv"))
    load_calls = []

    def loader(path):
        load_calls.append(str(path))
        return _make_frf_fd(tmp_path, f"loaded-{len(load_calls)}")

    preset = replace(
        _frf_preset(export_data=True, export_image=True),
        file_paths=source_paths,
    )
    runner = BatchRunner({}, loader=loader)
    preview = runner.preview_outputs(
        preset,
        tmp_path / "out",
        source_channels={
            path: ("command", "response") for path in source_paths
        },
    )

    result = runner.preview_group(
        preset, preview.representative_group.group_id, tmp_path / "preview",
    )

    assert len(load_calls) == 1
    assert result.loaded_source_count == 1
    assert result.status == "done"
    assert Path(result.image_path).is_file()


def test_batch_frf_data_preflight_failure_writes_no_task_artifact(tmp_path):
    fd = _make_frf_fd(tmp_path)
    fd._time_source = "generated"

    result = BatchRunner({0: fd}).run(_frf_preset(), tmp_path / "out")

    assert result.status == "blocked"
    assert result.items[0].status == "failed"
    assert result.items[0].data_path is None
    assert list((tmp_path / "out").glob("*.csv")) == []


def test_batch_frf_unexpected_import_error_propagates_and_releases_reservation(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch as batch_module

    def programming_error(*args, **kwargs):
        raise ImportError("unexpected FRF adapter defect")

    monkeypatch.setattr(
        batch_module.batch_compute,
        "compute_prepared_frf",
        programming_error,
    )
    output_dir = tmp_path / "out"

    with pytest.raises(ImportError, match="unexpected FRF adapter defect"):
        BatchRunner({0: _make_frf_fd(tmp_path)}).run(
            _frf_preset(), output_dir,
        )

    assert list(output_dir.glob(".*.batch-reserve")) == []
    assert list(output_dir.glob("*.csv")) == []


def test_batch_frf_programming_value_error_propagates_and_releases_reservation(
    tmp_path, monkeypatch,
):
    import mf4_analyzer.batch as batch_module

    def programming_error(*args, **kwargs):
        raise ValueError("programming dataframe contract defect")

    monkeypatch.setattr(
        batch_module.batch_compute,
        "compute_prepared_frf",
        programming_error,
    )
    output_dir = tmp_path / "out"

    with pytest.raises(ValueError, match="programming dataframe contract defect"):
        BatchRunner({0: _make_frf_fd(tmp_path)}).run(
            _frf_preset(), output_dir,
        )

    assert list(output_dir.glob(".*.batch-reserve")) == []
    assert list(output_dir.glob("*.csv")) == []


def test_batch_frf_cancellation_releases_all_pre_reserved_artifacts(
    tmp_path, monkeypatch,
):
    import threading
    import mf4_analyzer.batch as batch_module

    token = threading.Event()
    events = []
    real_compute = batch_module.batch_compute.compute_prepared_frf

    def cancel_first(prepared, **kwargs):
        token.set()
        return real_compute(prepared, **kwargs)

    monkeypatch.setattr(
        batch_module.batch_compute, "compute_prepared_frf", cancel_first,
    )
    output_dir = tmp_path / "out"
    result = BatchRunner({
        0: _make_frf_fd(tmp_path, "a"),
        1: _make_frf_fd(tmp_path, "b"),
    }).run(
        _frf_preset(), output_dir, cancel_token=token, on_event=events.append,
    )

    assert result.status == "cancelled"
    assert [item.status for item in result.items] == ["cancelled", "cancelled"]
    assert [event.kind for event in events if event.task_index is not None] == [
        "task_started", "task_cancelled",
        "task_started", "task_cancelled",
    ]
    assert list(output_dir.glob(".*.batch-reserve")) == []
    assert list(output_dir.glob("*.csv")) == []


def test_batch_frf_cancellation_between_stage2_tasks_never_reserves_or_writes(
    tmp_path, monkeypatch,
):
    import threading
    import mf4_analyzer.batch as batch_module

    token = threading.Event()
    trace = []
    real_prepare = batch_module.batch_compute.prepare_frf_task
    real_reserve = batch_module.reserve_output_paths

    def cancel_after_first_preflight(*args, **kwargs):
        trace.append("preflight")
        prepared = real_prepare(*args, **kwargs)
        token.set()
        return prepared

    def reserve(*args, **kwargs):
        trace.append("reserve")
        return real_reserve(*args, **kwargs)

    monkeypatch.setattr(
        batch_module.batch_compute,
        "prepare_frf_task",
        cancel_after_first_preflight,
    )
    monkeypatch.setattr(batch_module, "reserve_output_paths", reserve)
    output_dir = tmp_path / "out"

    result = BatchRunner({
        0: _make_frf_fd(tmp_path, "a"),
        1: _make_frf_fd(tmp_path, "b"),
    }).run(_frf_preset(), output_dir, cancel_token=token)

    assert result.status == "cancelled"
    assert trace == ["preflight"]
    assert [item.status for item in result.items] == ["cancelled", "cancelled"]
    assert list(output_dir.glob(".*.batch-reserve")) == []
    assert list(output_dir.glob("*.csv")) == []


def test_batch_frf_available_policy_records_one_skipped_candidate_and_continues(
    tmp_path,
):
    from dataclasses import replace
    from mf4_analyzer.batch_manifest import load_batch_manifest

    missing = _make_frf_fd(tmp_path, "missing")
    missing.data = missing.data.drop(columns=["response"])
    missing.channels = ["Time", "command"]
    valid = _make_frf_fd(tmp_path, "valid")
    preset = replace(_frf_preset(), target_policy="available_per_source")

    events = []
    result = BatchRunner({0: missing, 1: valid}).run(
        preset, tmp_path / "out", on_event=events.append,
    )

    assert result.status == "done"
    assert [(item.file_id, item.status) for item in result.items] == [
        (0, "skipped"), (1, "done"),
    ]
    skipped_item, valid_item = result.items
    assert not any("does not contain" in warning for warning in valid_item.warnings)
    assert skipped_item.data_path is None
    assert all(token in skipped_item.message for token in (
        "0", "command", "response", "建议",
    ))
    assert [event.kind for event in events if event.task_index == 1] == [
        "task_started", "task_skipped",
    ]
    assert sum(event.kind == "task_skipped" for event in events) == 1
    assert any("does not contain" in warning for warning in result.warnings)
    manifest = load_batch_manifest(result.manifest_path)
    skipped_entries = [
        entry for entry in manifest["entries"]
        if entry["status"] == "skipped"
    ]
    assert len(skipped_entries) == 1
    assert skipped_entries[0]["frf_pair"]["input"]["channel"] == "command"
    assert skipped_entries[0]["frf_pair"]["output"]["channel"] == "response"


def test_batch_frf_unexpected_loader_import_error_propagates(tmp_path):
    from dataclasses import replace

    source_path = str(tmp_path / "lazy.csv")

    def loader(_path):
        raise ImportError("loader programming defect")

    preset = replace(_frf_preset(), file_paths=(source_path,))

    with pytest.raises(ImportError, match="loader programming defect"):
        BatchRunner({}, loader=loader).run(preset, tmp_path / "out")
