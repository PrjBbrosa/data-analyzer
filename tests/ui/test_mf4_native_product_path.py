"""Explicit native product path: adapter, broker, transport, then GUI registration.

The default method table stays ``load_mf4``. These tests never call the reader
in the parent process. A direct ``DataLoader.load_mf4_native`` call is a failure.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread

import numpy as np
import pytest

FIXED_MEMORY = 498_988_944
FIXED_OUTPUT = 249_494_472
SHARED_AXIS_REQUEST = 638_740_162
LEDGER_CYCLES = 471_652
LEDGER_DATA_CHANNELS = 52
LEDGER_RECORD = 36_601_314
LEDGER_CATALOG = 2_197_504


def _fixed_limits(**overrides):
    from mf4_analyzer.io.import_limits import ImportLimits

    values = dict(max_memory_bytes=FIXED_MEMORY, max_output_bytes=FIXED_OUTPUT)
    values.update(overrides)
    return ImportLimits(**values)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_pair(path):
    from asammdf import MDF, Signal

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    time_axis = np.array([0.10, 0.11, 0.12], dtype="<f8")
    burst = np.array([0.0, 100.0, 0.0], dtype="<f8")
    other_t = np.array([0.0, 1.0, 1.0, 2.0], dtype="<f8")
    other = np.array([1.0, 2.0, 9.0, 4.0], dtype="<f8")
    wide_t = np.array([0.0, 1.0, 2.0], dtype="<f8")
    wide = np.array([1, 2**53 + 3, 5], dtype="<i8")
    mdf = MDF(version="4.10")
    mdf.append([
        Signal(burst, time_axis, name="burst", unit="Nm"),
        Signal(np.array([1.0, 1.0, 1.0]), time_axis, name="grid", unit="Nm"),
    ])
    mdf.append([Signal(other, other_t, name="dup", unit="Nm")])
    mdf.append([Signal(wide, wide_t, name="wide", unit="count")])
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def _oracle(path, group, index):
    from asammdf import MDF

    with MDF(str(path)) as src:
        signal = src.get(
            group=group, index=index, raw=True, ignore_invalidation_bits=True,
        )
        return (
            np.array(signal.samples, copy=True),
            np.array(signal.timestamps, copy=True),
        )


def _method_table_text():
    mixin = Path("mf4_analyzer/ui/main_window/_project_io_mixin.py").read_text(encoding="utf-8")
    return mixin.split("methods = {", 1)[1].split("}", 1)[0]


def _rss_bytes(pid):
    try:
        result = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True, text=True, timeout=1, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.strip()
    if result.returncode != 0 or not text:
        return None
    try:
        return int(text) * 1024
    except ValueError:
        return None


def _silence_dialogs(monkeypatch):
    from PyQt5.QtWidgets import QMessageBox
    from mf4_analyzer.ui_kit.message_dialog import AppMessageDialog

    monkeypatch.setattr(AppMessageDialog, "exec_", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "exec_", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)


def _window(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "toast", lambda *args, **kwargs: None)
    return window


def _forbid_parent_reader(monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError("parent called the MF4 reader and bypassed transport")

    monkeypatch.setattr("mf4_analyzer.io.loader.DataLoader.load_mf4", forbid)
    monkeypatch.setattr("mf4_analyzer.io.loader.DataLoader.load_mf4_native", forbid)
    monkeypatch.setattr("mf4_analyzer.io.mdf_reader.load_native_mdf", forbid)


def _track_workers(monkeypatch):
    import mf4_analyzer.io.import_process as process

    pids = []
    real_popen = process.subprocess.Popen

    def tracking(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        command = args[0] if args else kwargs.get("args")
        rendered = command if isinstance(command, str) else " ".join(str(part) for part in command)
        if "import_worker" in rendered or "import-worker" in rendered:
            pids.append(proc.pid)
        return proc

    monkeypatch.setattr(process.subprocess, "Popen", tracking)
    return pids


def _watch_rss(parent_pid, worker_pids, stop):
    samples = []

    def loop():
        while not stop.is_set():
            workers = {pid: _rss_bytes(pid) for pid in list(worker_pids)}
            samples.append({
                "t": time.time(),
                "parent_rss": _rss_bytes(parent_pid),
                "worker_rss": workers,
            })
            stop.wait(0.02)

    thread = Thread(target=loop, daemon=True)
    thread.start()
    return samples, thread


def _peak(samples, key):
    values = [item[key] for item in samples if item.get(key)]
    if key == "parent_rss":
        numbers = [item["parent_rss"] for item in samples if isinstance(item.get("parent_rss"), int)]
        return max(numbers) if numbers else None
    best = None
    best_pid = None
    for item in samples:
        for pid, rss in (item.get("worker_rss") or {}).items():
            if isinstance(rss, int) and (best is None or rss > best):
                best = rss
                best_pid = pid
    return best, best_pid


def test_default_method_table_is_still_load_mf4():
    table = _method_table_text()
    assert '".mf4": "load_mf4"' in table
    assert '".mdf": "load_mf4"' in table
    assert "load_mf4_native" not in table
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry

    adapter = SourceAdapterRegistry.default().adapter_for("sample.mf4")
    assert adapter.loader_name == "load_mf4"
    assert adapter.explicit_native_method() == "load_mf4_native"
    assert adapter.loader_name == "load_mf4"


def test_anonymous_shared_axis_still_refuses_fixed_budget():
    from types import SimpleNamespace

    from asammdf.blocks import v4_constants as c

    from mf4_analyzer.io.import_limits import ImportBudget, ImportResourceError
    from mf4_analyzer.io.mdf_reader import _reserve_native_output, _reserve_shared_output

    def channel(*, master):
        return SimpleNamespace(
            data_type=c.DATA_TYPE_REAL_INTEL,
            bit_count=64,
            channel_type=c.CHANNEL_TYPE_MASTER if master else c.CHANNEL_TYPE_VALUE,
            sync_type=c.SYNC_TYPE_TIME if master else c.SYNC_TYPE_NONE,
            conversion=None,
            flags=0,
            name="time" if master else "sig",
        )

    count = LEDGER_DATA_CHANNELS + 1
    group = SimpleNamespace(
        channels=[channel(master=True), *[channel(master=False) for _ in range(LEDGER_DATA_CHANNELS)]],
        channel_dependencies=[None] * count,
        channel_group=SimpleNamespace(cycles_nr=LEDGER_CYCLES),
    )
    mdf = SimpleNamespace(groups=[group], version="4.10", masters_db={0: 0})
    limits = _fixed_limits()
    shared = ImportBudget(limits)
    shared.reserve(LEDGER_RECORD, label="MDF record buffers")
    shared.reserve(LEDGER_CATALOG, label="MDF channel metadata/array expansion")
    with pytest.raises(ImportResourceError) as caught:
        _reserve_shared_output(SimpleNamespace(groups=[group]), shared)
    assert caught.value.requested_bytes == SHARED_AXIS_REQUEST
    assert shared.used_bytes == LEDGER_RECORD + LEDGER_CATALOG
    native = ImportBudget(limits)
    native.reserve(LEDGER_RECORD, label="MDF record buffers")
    native.reserve(LEDGER_CATALOG, label="MDF channel metadata/array expansion")
    _reserve_native_output(mdf, native)
    assert native.used_bytes < FIXED_MEMORY
    assert native.used_bytes != SHARED_AXIS_REQUEST
    labels = [name for name, _amount, _unit in native._components]
    assert "MDF shared-axis conversion/alignment/frame" not in labels


def test_explicit_native_formal_path_registers_under_fixed_budget(qtbot, monkeypatch, tmp_path):
    path = _write_pair(tmp_path / "测量 数据" / "扭矩 peak.mf4")
    digest = _sha256(path)
    _silence_dialogs(monkeypatch)
    _forbid_parent_reader(monkeypatch)
    window = _window(qtbot, monkeypatch)
    worker_pids = _track_workers(monkeypatch)
    seen = []
    real_broker = window._imports.broker

    def broker(method, file_path, **kwargs):
        seen.append((method, kwargs.get("limits")))
        return real_broker(method, file_path, **kwargs)

    window._imports.broker = broker
    from mf4_analyzer.io.source_adapters import SourceAdapter

    native_calls = []
    real_method = SourceAdapter.explicit_native_method

    def spy_method(self):
        native_calls.append(self.loader_name)
        return real_method(self)

    monkeypatch.setattr(SourceAdapter, "explicit_native_method", spy_method)
    stop = Event()
    samples, watcher = _watch_rss(os.getpid(), worker_pids, stop)
    limits = _fixed_limits()
    window.request_explicit_native_import(path, limits=limits)
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=30000)
    stop.set()
    watcher.join(timeout=1)
    assert seen and seen[0][0] == "load_mf4_native"
    assert seen[0][1] is not None
    assert seen[0][1].max_memory_bytes == FIXED_MEMORY
    assert seen[0][1].max_output_bytes <= FIXED_OUTPUT
    assert native_calls == ["load_mf4"]
    assert worker_pids, "explicit native import did not start a transport worker"
    assert _sha256(path) == digest
    assert len(window.files) == 1
    fid, fd = next(iter(window.files.items()))
    assert fd.is_native is True
    assert fid in window.navigator.ordered_file_fids()
    assert "burst" in fd.get_signal_channels()
    from mf4_analyzer.io.signal_access import read_signal

    series = read_signal(fd, "burst", representation="raw")
    samples_raw, timestamps = _oracle(path, 0, 1)
    assert np.array_equal(np.asarray(series.values), samples_raw)
    assert np.array_equal(np.asarray(series.time), timestamps)
    grid = read_signal(fd, "grid", representation="raw")
    assert np.shares_memory(np.asarray(series.time), np.asarray(grid.time))
    wide = read_signal(fd, "wide", representation="raw")
    assert int(np.asarray(wide.values)[1]) == 2**53 + 3
    assert np.asarray(wide.values).dtype == np.dtype("<i8")
    parent_peak = _peak(samples, "parent_rss")
    worker_peak, worker_pid = _peak(samples, "worker_rss")
    print(
        "M6_PEAKS",
        {
            "parent_rss": parent_peak,
            "worker_rss": worker_peak,
            "worker_pid": worker_pid,
            "worker_pids": list(worker_pids),
            "sample_count": len(samples),
        },
    )


def test_low_native_budget_fails_then_old_mf4_path_opens(qtbot, monkeypatch, tmp_path):
    native_path = _write_pair(tmp_path / "tight.mf4")
    legacy_path = _write_pair(tmp_path / "legacy.mf4")
    _silence_dialogs(monkeypatch)
    _forbid_parent_reader(monkeypatch)
    window = _window(qtbot, monkeypatch)
    seen = []
    real_broker = window._imports.broker

    def broker(method, file_path, **kwargs):
        seen.append(method)
        return real_broker(method, file_path, **kwargs)

    window._imports.broker = broker
    tiny = _fixed_limits(max_memory_bytes=4096, max_output_bytes=2048)
    window.request_explicit_native_import(native_path, limits=tiny)
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=30000)
    assert seen == ["load_mf4_native"]
    assert not window.files
    assert window._imports.failures
    assert window._imports.failures[-1]["code"] == "resource_limit"
    window._load_one(str(legacy_path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=30000)
    assert seen == ["load_mf4_native", "load_mf4"]
    assert len(window.files) == 1
    fd = next(iter(window.files.values()))
    assert fd.is_native is False
    assert Path(fd.filepath).name == "legacy.mf4"
    assert str(native_path) not in {str(item.filepath) for item in window.files.values()}


def _sleep_worker(_request):
    return [sys.executable, "-c", "import time; time.sleep(30)"]


def test_cancel_does_not_register_a_native_import(qtbot, monkeypatch, tmp_path):
    import mf4_analyzer.io.import_process as process

    _silence_dialogs(monkeypatch)
    window = _window(qtbot, monkeypatch)
    statuses = []
    window._imports.finished.connect(lambda *_args: statuses.append(_args[1]))
    monkeypatch.setattr(process, "_worker_command", _sleep_worker)
    path = _write_pair(tmp_path / "cancel.mf4")
    window.request_explicit_native_import(path, limits=_fixed_limits(cancel_grace_seconds=0.2))
    qtbot.waitUntil(lambda: window._imports._thread is not None, timeout=10000)
    window._imports.cancel()
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert statuses == ["cancelled"]
    assert not window.files


def test_source_change_does_not_register_a_finished_native_read(qtbot, monkeypatch, tmp_path):
    import mf4_analyzer.io.import_process as process

    _silence_dialogs(monkeypatch)
    _forbid_parent_reader(monkeypatch)
    window = _window(qtbot, monkeypatch)
    worker_pids = _track_workers(monkeypatch)
    statuses = []
    window._imports.finished.connect(lambda *_args: statuses.append(_args[1]))
    real_snapshot = process.source_snapshot
    calls = {"n": 0}

    def changed(path):
        calls["n"] += 1
        snap = list(real_snapshot(path))
        if calls["n"] >= 3:
            snap[2] = int(snap[2]) + 1
        return snap

    monkeypatch.setattr(process, "source_snapshot", changed)
    path = _write_pair(tmp_path / "source.mf4")
    digest = _sha256(path)
    window.request_explicit_native_import(path, limits=_fixed_limits())
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=30000)
    assert worker_pids
    assert _sha256(path) == digest
    assert not window.files
    assert window._imports.failures[-1]["code"] == "data_error"
    assert statuses[-1] == "failed"


def test_target_change_does_not_register_a_native_import(qtbot, monkeypatch, tmp_path):
    import mf4_analyzer.io.import_process as process

    _silence_dialogs(monkeypatch)
    window = _window(qtbot, monkeypatch)
    statuses = []
    window._imports.finished.connect(lambda *_args: statuses.append(_args[1]))
    monkeypatch.setattr(process, "_worker_command", _sleep_worker)
    path = _write_pair(tmp_path / "target.mf4")
    window.request_explicit_native_import(path, limits=_fixed_limits(cancel_grace_seconds=0.2))
    qtbot.waitUntil(lambda: window._imports._thread is not None, timeout=10000)
    window.view_manager.views = [window.view_manager._make(0)]
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert statuses[-1] == "cancelled"
    assert not window.files
