from types import SimpleNamespace

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QMenu

from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
from mf4_analyzer.ui.recent_files import KIND_FILE, KIND_PROJECT, RecentFilesStore


def test_loaded_menu_sees_files_added_after_empty_batch_open(qtbot, monkeypatch):
    files = {}
    sheet = BatchSheet(None, files=files)
    qtbot.addWidget(sheet)
    widget = sheet._input_panel._file_list
    assert sheet._files is files
    assert widget._files_source is files
    files[7] = SimpleNamespace(
        filename="new.mf4", filepath="/tmp/new.mf4",
        get_signal_channels=lambda: ("torque",),
    )
    def choose(menu, _point):
        assert [action.text() for action in menu.actions()] == ["new.mf4"]
        menu.actions()[0].trigger()
    monkeypatch.setattr(QMenu, "exec_", choose)
    widget._open_loaded_menu()
    assert widget.loaded_source_ids() == (7,)
    files.clear()
    def empty(menu, _point):
        assert len(menu.actions()) == 1
        assert not menu.actions()[0].isEnabled()
    monkeypatch.setattr(QMenu, "exec_", empty)
    widget._open_loaded_menu()


def test_recent_files_reuse_batch_intake_and_preserve_projects(qtbot, tmp_path, monkeypatch):
    store = RecentFilesStore(QSettings(str(tmp_path / "recent.ini"), QSettings.IniFormat))
    data = tmp_path / "new.blf"
    data.touch()
    project = tmp_path / "session.tlproj"
    project.touch()
    store.record_file(str(data))
    store.record_project(str(project))
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    widget = sheet._input_panel._file_list
    widget.set_recent_store(store)
    shown = []
    monkeypatch.setattr(widget._recent_popup, "show_at", shown.append)
    widget._open_recent_popup()
    assert shown == [widget._disk_split]
    assert [entry.path for entry in widget._recent_popup._entries] == [str(data)]
    routed = []
    widget.set_disk_paths_handler(routed.append)
    widget._recent_popup.open_requested.emit(str(data))
    assert routed == [[str(data)]]
    assert widget.loaded_source_ids() == ()
    widget._clear_recent_files()
    assert store.entries(KIND_FILE) == ()
    assert len(store.entries(KIND_PROJECT)) == 1


def test_recent_close_does_not_reopen_on_same_caret_click(qtbot, monkeypatch):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    widget = sheet._input_panel._file_list
    calls = []
    monkeypatch.setattr(widget._recent_popup, "show_at", calls.append)
    widget._on_recent_closed()
    widget._open_recent_popup()
    assert calls == []
