from __future__ import annotations

import numpy as np
import pandas as pd

from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
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


def test_free_config_order_track_preset_selects_matching_signals(tmp_path):
    fd = _make_file(tmp_path)
    preset = AnalysisPreset.free_config(
        name="track all sig",
        method="order_track",
        signal_pattern="sig",
        rpm_channel="rpm",
        params={"fs": 1024.0, "target_order": 2.0, "nfft": 1024},
        outputs=BatchOutput(export_data=True, export_image=False),
    )

    result = BatchRunner({1: fd}).run(preset, tmp_path / "out")

    assert result.status == "done"
    assert len(result.items) == 1
    data = pd.read_csv(result.items[0].data_path)
    assert list(data.columns) == ["rpm", "amplitude"]


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


def test_target_signals_partial_missing_yields_failed_rows(tmp_path):
    fd_a = _make_fd(tmp_path, "a", channels=("sig",), idx=0)
    fd_b = _make_fd(tmp_path, "b", channels=("other",), idx=1)
    preset = AnalysisPreset.free_config(
        name="pm", method="fft", target_signals=("sig",),
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
    assert len(failed) == 1
    assert "missing signal" in (failed[0].error or "").lower()
    assert result.status == "partial"


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
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1))
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
    assert any("a_sig_fft" in p.name for p in csvs)
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


def test_supported_methods_excludes_removed_order_rpm():
    """``order_rpm`` was permanently removed (commit cfb301b) — its handler
    in ``_run_one`` no longer exists. Keeping it in ``SUPPORTED_METHODS`` lets
    a stray preset pass ``_expand_tasks`` and fall through to the
    ``unsupported method`` raise (silent / undefined). Pin the W1 baseline.
    """
    assert BatchRunner.SUPPORTED_METHODS == {"fft", "order_time", "order_track"}
    assert "order_rpm" not in BatchRunner.SUPPORTED_METHODS
