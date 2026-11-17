"""BatchSheet reuses MainWindow BLF/DBC dialogs for disk/drop intake."""
from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.io.source_adapters import AdapterAvailability, SourceDescriptor
from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin


def _ready_if_dbc(path, context=None):
    ctx = dict(context or {})
    if ctx.get("dbc_paths"):
        return AdapterAvailability("ready", "")
    return AdapterAvailability(
        "limited",
        "CAN 日志（BLF/CANoe ASC）需要 DBC 解码上下文，raw CAN frame 不作为批处理信号来源",
        missing_context=("dbc_paths",),
    )


def _probe_ok(path, *, context=None):
    return (SourceDescriptor(
        source_id="blf-1",
        source_path=str(path),
        group_id="root",
        display_name=Path(path).name,
        channel_names=("MotorTorque",),
        units={"MotorTorque": "Nm"},
        fs=None,
        metadata={
            "adapter_key": "blf",
            "dbc_paths": list((context or {}).get("dbc_paths", ())),
        },
    ),)


def test_batch_disk_blf_resolves_dbc_via_parent_facade(qtbot, tmp_path, monkeypatch):
    blf = tmp_path / "capture.blf"
    blf.write_bytes(b"BLF")
    dbc = str(tmp_path / "bus.dbc")
    calls = []

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._blf_dbc_resolver = lambda paths: calls.append(list(paths)) or [dbc]

    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "availability_for",
        _ready_if_dbc,
    )
    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "probe_sources",
        _probe_ok,
    )

    sheet._add_disk_paths_with_blf_context([str(blf)])
    # The registry probe runs on the global QThreadPool; wait on the loaded
    # state instead of a fixed tick so a busy pool cannot flake the test.
    qtbot.waitUntil(
        lambda: sheet._input_panel._file_list.loaded_disk_paths() == (str(blf),),
        timeout=5000,
    )

    assert calls == [[str(blf)]]
    assert sheet._source_context.get("dbc_paths") == [dbc]
    assert sheet._make_runner()._source_context.get("dbc_paths") == [dbc]


def test_batch_blf_cancel_skips_blf_but_keeps_other_files(qtbot, tmp_path, monkeypatch):
    blf = tmp_path / "capture.blf"
    blf.write_bytes(b"BLF")
    other = tmp_path / "trace.csv"
    other.write_text("t,y\n0,1\n", encoding="utf-8")
    calls = []

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._blf_dbc_resolver = lambda paths: calls.append(list(paths)) or None

    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "availability_for",
        lambda path, context=None: AdapterAvailability("ready", ""),
    )
    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "probe_sources",
        lambda path, *, context=None: (SourceDescriptor(
            source_id=f"src-{Path(path).name}",
            source_path=str(path),
            group_id="root",
            display_name=Path(path).name,
            channel_names=("y",),
            units={},
            fs=1.0,
            metadata={},
        ),),
    )

    sheet._add_disk_paths_with_blf_context([str(blf), str(other)])
    qtbot.waitUntil(
        lambda: str(other) in sheet._input_panel._file_list.loaded_disk_paths(),
        timeout=5000,
    )

    assert calls == [[str(blf)]]
    assert "dbc_paths" not in sheet._source_context
    assert str(blf) not in sheet._input_panel._file_list.loaded_disk_paths()
    assert "已取消 CAN 日志的 DBC 选择" in sheet._last_toast_text


def test_batch_blf_reuses_existing_context_without_new_dialog(qtbot, tmp_path, monkeypatch):
    blf = tmp_path / "capture.blf"
    blf.write_bytes(b"BLF")
    dbc = "/tmp/already.dbc"
    calls = []

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._blf_dbc_resolver = lambda paths: calls.append(list(paths)) or []
    sheet._set_source_context({"dbc_paths": [dbc]})

    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "availability_for",
        _ready_if_dbc,
    )
    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "probe_sources",
        _probe_ok,
    )

    sheet._add_disk_paths_with_blf_context([str(blf)])
    qtbot.waitUntil(
        lambda: sheet._input_panel._file_list.loaded_disk_paths() == (str(blf),),
        timeout=5000,
    )

    assert calls == []
    assert sheet._source_context["dbc_paths"] == [dbc]


def test_resolve_blf_dbc_paths_for_batch_single_delegates_to_resolve():
    class Host(ProjectIOMixin):
        def __init__(self):
            self.calls = []

        def _resolve_blf_dbc_paths(self, path, *, frames=None, progress_callback=None):
            self.calls.append(str(path))
            return ["/x.dbc"]

        def _ask_blf_batch_dbc_action(self, paths):
            raise AssertionError("single BLF must not ask batch action")

    host = Host()
    assert host.resolve_blf_dbc_paths_for_batch(["/a.blf"]) == ["/x.dbc"]
    assert host.calls == ["/a.blf"]


def test_resolve_blf_dbc_paths_for_batch_multi_batch_action():
    class Host(ProjectIOMixin):
        def __init__(self):
            self.action = "batch"

        def _ask_blf_batch_dbc_action(self, paths):
            assert len(paths) == 2
            return self.action

        def _choose_blf_dbc_with_retry(self, path, *, frames=None, progress_callback=None):
            return ["/batch.dbc"]

        def _resolve_blf_dbc_paths(self, path, *, frames=None, progress_callback=None):
            return ["/one.dbc"]

    host = Host()
    assert host.resolve_blf_dbc_paths_for_batch(["/a.blf", "/b.blf"]) == ["/batch.dbc"]
    host.action = "individual"
    assert host.resolve_blf_dbc_paths_for_batch(["/a.blf", "/b.blf"]) == ["/one.dbc"]
    host.action = "cancel"
    assert host.resolve_blf_dbc_paths_for_batch(["/a.blf", "/b.blf"]) is None


def test_batch_disk_canoe_asc_resolves_dbc_via_parent_facade(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("can", reason="python-can not installed (win32-gated)")
    from tests._helpers.blf_factory import write_sample_asc

    asc = write_sample_asc(tmp_path / "capture.asc", n=2)
    dbc = str(tmp_path / "bus.dbc")
    calls = []

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._blf_dbc_resolver = lambda paths: calls.append(list(paths)) or [dbc]

    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "availability_for",
        _ready_if_dbc,
    )
    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "probe_sources",
        _probe_ok,
    )

    sheet._add_disk_paths_with_blf_context([str(asc)])
    qtbot.waitUntil(
        lambda: sheet._input_panel._file_list.loaded_disk_paths() == (str(asc),),
        timeout=5000,
    )

    assert calls == [[str(asc)]]
    assert sheet._source_context.get("dbc_paths") == [dbc]


def test_batch_mixed_blf_and_canoe_asc_resolves_dbc_once(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("can", reason="python-can not installed (win32-gated)")
    from tests._helpers.blf_factory import write_sample_asc, write_sample_blf

    blf = write_sample_blf(tmp_path / "a.blf", n=2)
    asc = write_sample_asc(tmp_path / "b.asc", n=2)
    dbc = str(tmp_path / "bus.dbc")
    calls = []

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._blf_dbc_resolver = lambda paths: calls.append(list(paths)) or [dbc]

    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "availability_for",
        _ready_if_dbc,
    )

    def probe_ok(path, *, context=None):
        return (SourceDescriptor(
            source_id=f"blf-{Path(path).name}",
            source_path=str(path),
            group_id="root",
            display_name=Path(path).name,
            channel_names=("MotorTorque",),
            units={"MotorTorque": "Nm"},
            fs=None,
            metadata={
                "adapter_key": "blf",
                "dbc_paths": list((context or {}).get("dbc_paths", ())),
            },
        ),)

    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "probe_sources",
        probe_ok,
    )

    sheet._add_disk_paths_with_blf_context([str(blf), str(asc)])
    qtbot.waitUntil(
        lambda: set(sheet._input_panel._file_list.loaded_disk_paths())
        == {str(blf), str(asc)},
        timeout=5000,
    )

    assert len(calls) == 1
    assert set(calls[0]) == {str(blf), str(asc)}
    assert sheet._source_context.get("dbc_paths") == [dbc]


def test_batch_canoe_asc_cancel_keeps_tabular_asc(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("can", reason="python-can not installed (win32-gated)")
    from tests._helpers.blf_factory import write_sample_asc

    canoe = write_sample_asc(tmp_path / "capture.asc", n=2)
    table = tmp_path / "table.asc"
    table.write_text("Time,sig\n0,1\n0.1,2\n", encoding="utf-8")
    calls = []

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._blf_dbc_resolver = lambda paths: calls.append(list(paths)) or None

    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "availability_for",
        lambda path, context=None: AdapterAvailability("ready", ""),
    )
    monkeypatch.setattr(
        sheet._input_panel._file_list._source_registry,
        "probe_sources",
        lambda path, *, context=None: (SourceDescriptor(
            source_id=f"src-{Path(path).name}",
            source_path=str(path),
            group_id="root",
            display_name=Path(path).name,
            channel_names=("sig",),
            units={"sig": ""},
            fs=None,
            metadata={"adapter_key": "ascii"},
        ),),
    )

    sheet._add_disk_paths_with_blf_context([str(canoe), str(table)])
    qtbot.waitUntil(
        lambda: str(table) in sheet._input_panel._file_list.loaded_disk_paths(),
        timeout=5000,
    )

    assert calls == [[str(canoe)]]
    assert str(canoe) not in sheet._input_panel._file_list.loaded_disk_paths()
    assert "已取消 CAN 日志的 DBC 选择" in sheet._last_toast_text


@pytest.mark.parametrize('entry', ['disk', 'files', 'sources'])
def test_real_parent_dbc_intake_resumes_after_supervisor(qtbot, tmp_path, monkeypatch, entry):
    from threading import Event
    from types import SimpleNamespace
    from PyQt5.QtCore import QThread, QTimer
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    sheet = BatchSheet(window, files={})
    qtbot.addWidget(sheet)
    path = tmp_path / 'slow.blf'
    path.write_bytes(b'BLF')
    dbc = str(tmp_path / 'bus.dbc')
    entered, release = Event(), Event()
    calls, ticks = [], []

    def broker(method, path, **kwargs):
        assert QThread.currentThread() is not window.thread()
        calls.append(method)
        if method == 'read_blf_frames':
            entered.set()
            assert release.wait(3)
            return []
        assert method == 'probe_blf_dbc_frames'
        return SimpleNamespace(is_match=True)

    sheet._dbc_imports.broker = broker
    monkeypatch.setattr(window, '_candidate_blf_dbc_paths', lambda _path: [[dbc]])
    monkeypatch.setattr(window, '_ask_blf_dbc_candidate_action', lambda *_args: 'use')
    monkeypatch.setattr(sheet._input_panel._file_list._source_registry, 'availability_for', _ready_if_dbc)
    monkeypatch.setattr(sheet._input_panel._file_list._source_registry, 'probe_sources', _probe_ok)
    timer = QTimer(sheet)
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        if entry == 'disk':
            sheet._add_disk_paths_with_blf_context([str(path)])
        elif entry == 'files':
            sheet.apply_files((), (str(path),))
        else:
            sheet.apply_sources((), (str(path),))
        qtbot.waitUntil(entered.is_set)
        qtbot.waitUntil(lambda: len(ticks) >= 3)
        assert sheet._dbc_imports.progress_dialog.isVisible()
        assert sheet._input_panel._file_list.loaded_disk_paths() == ()
        release.set()
        qtbot.waitUntil(lambda: not sheet._dbc_imports.busy)
        qtbot.waitUntil(lambda: sheet._input_panel._file_list.loaded_disk_paths() == (str(path),))
        assert calls == ['read_blf_frames', 'probe_blf_dbc_frames']
        assert sheet._source_context['dbc_paths'] == [dbc]
    finally:
        release.set()
        qtbot.waitUntil(lambda: not sheet._dbc_imports.busy)


@pytest.mark.parametrize('operation', ['cancel', 'close', 'reject'])
def test_batch_dbc_cancel_or_close_does_not_publish(qtbot, tmp_path, monkeypatch, operation):
    from threading import Event
    from PyQt5.QtWidgets import QPushButton
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    sheet = BatchSheet(window, files={})
    qtbot.addWidget(sheet)
    sheet.show()
    path = tmp_path / 'slow.blf'
    path.write_bytes(b'BLF')
    entered, release = Event(), Event()
    terminals = []

    def broker(method, path, *, cancel_check, **kwargs):
        entered.set()
        assert release.wait(3)
        assert cancel_check()
        return []

    sheet._dbc_imports.broker = broker
    sheet._dbc_imports.finished.connect(lambda *args: terminals.append(args))
    try:
        sheet._add_disk_paths_with_blf_context([str(path)])
        qtbot.waitUntil(entered.is_set)
        if operation == 'cancel':
            dialog = sheet._dbc_imports.progress_dialog
            button = dialog.findChild(QPushButton)
            assert button.isVisible()
            qtbot.mouseClick(button, Qt.LeftButton)
        else:
            getattr(sheet, operation)()
        release.set()
        qtbot.waitUntil(lambda: not sheet._dbc_imports.busy)
        assert len(terminals) == 1
        assert terminals[0][1] == 'cancelled'
        assert sheet._input_panel._file_list.loaded_disk_paths() == ()
        assert 'dbc_paths' not in sheet._source_context
    finally:
        release.set()
        qtbot.waitUntil(lambda: not sheet._dbc_imports.busy)


@pytest.mark.parametrize('prior_action', ['none', 'cancel', 'close', 'reject'])
def test_main_close_waits_for_sheet_dbc_drain_after_dirty_guard(qtbot, tmp_path, monkeypatch, prior_action):
    from threading import Event
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_batch()
    sheet = window._batch_sheet
    qtbot.addWidget(sheet)
    owner = sheet._dbc_imports
    entered, release = Event(), Event()
    prompts, terminals = [], []
    path = tmp_path / 'closing.blf'
    path.write_bytes(b'BLF')

    def broker(method, path, *, cancel_check, **kwargs):
        entered.set()
        assert release.wait(5)
        assert cancel_check()
        return []

    def discard():
        prompts.append('dirty_guard')
        assert not window._imports.closing
        return 'discard'

    owner.broker = broker
    owner.finished.connect(lambda *args: terminals.append(args))
    window._project_dirty.mark_user_mutation()
    monkeypatch.setattr(window, '_prompt_unsaved_project', discard)
    sheet._add_disk_paths_with_blf_context([str(path)])
    try:
        qtbot.waitUntil(entered.is_set)
        if prior_action == 'cancel':
            owner.cancel()
        elif prior_action != 'none':
            getattr(sheet, prior_action)()
        assert window.close() is False
        assert prompts == ['dirty_guard']
        assert window.isVisible()
        assert owner.busy
        assert not window._project_dirty.close_teardown_started
        release.set()
        qtbot.waitUntil(lambda: not window.isVisible())
        assert prompts == ['dirty_guard']
        assert not owner.busy
        assert len(terminals) == 1 and terminals[0][1] == 'cancelled'
        assert window._project_dirty.close_teardown_started
        assert not sheet._input_panel._file_list.loaded_disk_paths()
    finally:
        owner.cancel()
        release.set()
        qtbot.waitUntil(lambda: not owner.busy)


@pytest.mark.parametrize('operation', ['close', 'reject'])
def test_sheet_only_close_waits_for_dbc_then_can_reopen(qtbot, tmp_path, operation):
    from threading import Event
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_batch()
    sheet = window._batch_sheet
    qtbot.addWidget(sheet)
    entered, release = Event(), Event()
    path = tmp_path / 'closing.blf'
    path.write_bytes(b'BLF')

    def broker(*args, cancel_check, **kwargs):
        entered.set()
        assert release.wait(5)
        assert cancel_check()
        return []

    sheet._dbc_imports.broker = broker
    sheet._add_disk_paths_with_blf_context([str(path)])
    try:
        qtbot.waitUntil(entered.is_set)
        getattr(sheet, operation)()
        assert sheet.isVisible()
        assert sheet._dbc_imports.busy
        release.set()
        qtbot.waitUntil(lambda: not sheet.isVisible())
        assert not sheet._dbc_imports.busy
        assert window.isVisible()
        window.open_batch()
        reopened = window._batch_sheet
        qtbot.addWidget(reopened)
        assert reopened.isVisible()
        assert not reopened._dbc_imports.closing
    finally:
        sheet._dbc_imports.cancel()
        release.set()
        qtbot.waitUntil(lambda: not sheet._dbc_imports.busy)


def test_dirty_guard_cancel_does_not_cancel_sheet_dbc(qtbot, tmp_path, monkeypatch):
    from threading import Event
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.open_batch()
    sheet = window._batch_sheet
    qtbot.addWidget(sheet)
    entered, release = Event(), Event()
    path = tmp_path / 'closing.blf'
    path.write_bytes(b'BLF')

    def broker(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return []

    sheet._dbc_imports.broker = broker
    window._project_dirty.mark_user_mutation()
    monkeypatch.setattr(window, '_prompt_unsaved_project', lambda: 'cancel')
    sheet._add_disk_paths_with_blf_context([str(path)])
    try:
        qtbot.waitUntil(entered.is_set)
        assert window.close() is False
        assert not sheet._dbc_imports._active.cancel_event.is_set()
        assert not window._imports.closing
        assert not window._project_dirty.close_teardown_started
        assert window.isVisible()
    finally:
        sheet._dbc_imports.cancel()
        release.set()
        qtbot.waitUntil(lambda: not sheet._dbc_imports.busy)
        monkeypatch.setattr(window, '_prompt_unsaved_project', lambda: 'discard')
