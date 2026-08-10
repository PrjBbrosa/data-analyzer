"""BatchSheet reuses MainWindow BLF/DBC dialogs for disk/drop intake."""
from __future__ import annotations

from pathlib import Path

from mf4_analyzer.io.source_adapters import AdapterAvailability, SourceDescriptor
from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin


def _ready_if_dbc(path, context=None):
    ctx = dict(context or {})
    if ctx.get("dbc_paths"):
        return AdapterAvailability("ready", "")
    return AdapterAvailability(
        "limited",
        "BLF 需要 DBC 解码上下文，raw CAN frame 不作为批处理信号来源",
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
    qtbot.wait(50)

    assert calls == [[str(blf)]]
    assert sheet._source_context.get("dbc_paths") == [dbc]
    assert sheet._make_runner()._source_context.get("dbc_paths") == [dbc]
    assert sheet._input_panel._file_list.loaded_disk_paths() == (str(blf),)


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
    qtbot.wait(50)

    assert calls == [[str(blf)]]
    assert "dbc_paths" not in sheet._source_context
    assert str(blf) not in sheet._input_panel._file_list.loaded_disk_paths()
    assert str(other) in sheet._input_panel._file_list.loaded_disk_paths()
    assert "已取消 BLF 的 DBC 选择" in sheet._last_toast_text


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
    qtbot.wait(50)

    assert calls == []
    assert sheet._source_context["dbc_paths"] == [dbc]
    assert sheet._input_panel._file_list.loaded_disk_paths() == (str(blf),)


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
