"""Real MainWindow import path for MF4 shared-axis diagnostics."""
from __future__ import annotations

import pytest

from tests._helpers.mf4_factory import write_signal_groups_mf4


def _window(qtbot):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window


def _capture(monkeypatch, window):
    notices = []

    def capture_notice(message, level="info"):
        notices.append((message, level))

    monkeypatch.setattr(window, "toast", capture_notice)
    return notices


def test_load_mf4_warns_on_alignment(qapp, qtbot, tmp_path, monkeypatch):
    path = write_signal_groups_mf4(tmp_path / "coverage.mf4", [
        [("fast", [0, 1, 2, 3, 4], [0, 0.25, 0.5, 0.75, 1])],
        [("slow", [10, 20, 30], [0, 5, 10])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert any(
        level == "warning" and "时间范围" in message
        for message, level in notices
    )


def test_load_mf4_warns_when_duplicate_times_are_collapsed(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = write_signal_groups_mf4(tmp_path / "ties.mf4", [
        [("long", [1, 1, 1, 1], [0, 0.01, 0.02, 0.03])],
        [("short", [0, 1, 5, 9], [0, 0.01, 0.01, 0.03])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert any(
        level == "warning" and "最后值" in message
        for message, level in notices
    )
    assert any(level == "success" for _message, level in notices)


def test_load_mf4_warns_when_a_clock_regresses(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = write_signal_groups_mf4(tmp_path / "reset.mf4", [
        [("clock", [0, 0, 0, 0], [0, 1, 2, 3])],
        [("wound", [1, 4, 2, 3], [0, 3, 1, 2])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert any(
        level == "warning" and "时间回退" in message
        for message, level in notices
    )
    assert window.files


def test_load_mf4_disagreed_single_points_do_not_open_a_file(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = write_signal_groups_mf4(tmp_path / "split.mf4", [
        [("a", [1.0], [0.0])],
        [("b", [2.0], [10.0])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    errors = []
    monkeypatch.setattr(
        "mf4_analyzer.ui.main_window._project_io_mixin.QMessageBox.critical",
        lambda *args, **kwargs: errors.append(args),
    )
    before = set(window.files)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert errors
    assert "单点" in str(errors[-1])
    assert set(window.files) == before
    assert not any(level == "success" for _message, level in notices)


def test_load_mf4_alignment_warnings_stay_bounded(
    qapp, qtbot, tmp_path, monkeypatch,
):
    path = write_signal_groups_mf4(tmp_path / "many.mf4", [
        [("fast", [0, 1, 2, 3, 4], [0, 0.25, 0.5, 0.75, 1])],
        [("slow", [10, 20, 30], [0, 5, 10])],
        [("tied", [1, 1, 2], [0, 0, 1])],
        [("wound", [1, 2, 3], [0, 2, 1])],
    ])
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    warnings = [message for message, level in notices if level == "warning"]
    alignment = [
        message for message in warnings
        if message.startswith(("时间整理", "已按公共", "无法对齐"))
        or "时间范围" in message
        or "端点填充" in message
    ]
    assert len(alignment) <= 3
    assert len(alignment) == len(set(alignment))


def test_load_mf4_time_named_signal_is_selectable(qapp, qtbot, tmp_path):
    path = write_signal_groups_mf4(tmp_path / "time-sig.mf4", [[
        ("Time", [10.0, 20.0, 30.0, 40.0], [0.0, 0.1, 0.2, 0.3], "Nm"),
        ("sig", [1.0, 2.0, 3.0, 4.0], [0.0, 0.1, 0.2, 0.3], "V"),
    ]])
    window = _window(qtbot)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    fid, fd = next(iter(window.files.items()))
    assert fd.time_array.tolist() == [0.0, 0.1, 0.2, 0.3]
    assert fd.fs == pytest.approx(10.0)
    assert fd.get_signal_channels() == ["Time [0:1]", "sig"]
    window.navigator.set_checked_channels([(fid, "Time [0:1]"), (fid, "sig")])
    checked = {
        (item[0], item[1]) for item in window.navigator.get_checked_channels()
    }
    assert checked == {(fid, "Time [0:1]"), (fid, "sig")}


def test_resource_limited_mf4_stays_closed_and_hides_shared_axis_labels(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from PyQt5.QtWidgets import QMessageBox
    from mf4_analyzer.io.import_limits import parse_resource_envelope, resource_user_text
    from mf4_analyzer.io.import_process import ImportProcessError
    from mf4_analyzer.ui_kit.message_dialog import AppMessageDialog

    label = "MDF shared-axis conversion/alignment/frame"
    exc = ImportProcessError(
        "resource_limit",
        "导入资源超过预算",
        stage="admission",
        detail="worker detail",
        resource=parse_resource_envelope({
            "schema": 1,
            "resource_kind": "memory_estimate",
            "unit": "bytes",
            "requested": 638_976_000,
            "limit": 498_988_944,
            "phase": "admission",
            "estimate_basis": "test",
            "label": label,
            "components": [{"name": label, "amount": 638_976_000, "unit": "bytes"}],
        }),
        request_id="req-mf4-1",
    )
    path = tmp_path / "rejected.mf4"
    path.write_bytes(b"not-opened")
    shown = []

    def drive(self):
        shown.append(self._text_label.text())
        self.button("close").click()
        return 0

    monkeypatch.setattr(AppMessageDialog, "exec_", drive)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: shown.append("critical"))
    window = _window(qtbot)
    notices = _capture(monkeypatch, window)

    def broker(*args, **kwargs):
        raise exc

    window._imports.broker = broker
    before = set(window.files)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert shown == [resource_user_text(exc)]
    assert label not in shown[0]
    assert "约609 MiB" in shown[0]
    assert set(window.files) == before
    assert not any(level == "success" for _message, level in notices)


@pytest.fixture(autouse=True)
def _local_import_broker(monkeypatch):
    """Exercise GUI continuations with existing loader fakes; broker has its own gates."""
    from mf4_analyzer.io import DataLoader
    from mf4_analyzer.ui.main_window import import_coordinator

    def run(method, path, *, kwargs=None, cancel_check=None, progress_callback=None, limits=None):
        options = dict(kwargs or {})
        if method in {"load_blf_frames", "probe_blf_dbc_frames"}:
            path = options.pop("frames")
        if progress_callback:
            progress_callback(-1.0, "读取表格" if method == "load_csv" else "读取数据")
        return getattr(DataLoader, method)(path, **options)

    monkeypatch.setattr(import_coordinator, "run_import", run)
