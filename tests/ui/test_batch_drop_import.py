"""BatchSheet whole-dialog drag-and-drop import."""

from pathlib import Path

from PyQt5.QtCore import QMimeData, QPoint, QSettings, Qt, QUrl
from PyQt5.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent


def _mime(paths):
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return m


def _enter(mime):
    event = QDragEnterEvent(
        QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    event._mime_ref = mime
    return event


def _drop(mime):
    event = QDropEvent(
        QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    event._mime_ref = mime
    return event


def _prefs_store(tmp_path, name="batch-drop-prefs.ini"):
    from mf4_analyzer.ui.batch_settings import BatchPanelPrefsStore

    return BatchPanelPrefsStore(
        settings=QSettings(str(tmp_path / name), QSettings.IniFormat)
    )


def _make_sheet(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(
        parent=None, files={}, current_preset=None,
        prefs_store=_prefs_store(tmp_path),
    )
    qtbot.addWidget(sheet)
    return sheet


def test_batch_accept_drops_enabled(qapp, qtbot, tmp_path):
    sheet = _make_sheet(qtbot, tmp_path)
    assert sheet.acceptDrops() is True


def test_batch_drag_enter_accepts_supported_and_shows_overlay(qapp, qtbot, tmp_path):
    sheet = _make_sheet(qtbot, tmp_path)
    f = tmp_path / "a.csv"
    f.write_text("x")
    ev = _enter(_mime([f]))

    sheet.dragEnterEvent(ev)

    assert ev.isAccepted()
    assert sheet._drop_overlay is not None
    assert not sheet._drop_overlay.isHidden()
    assert sheet._drop_overlay._message == "松手添加到批处理"


def test_batch_drag_enter_accepts_mf4(qapp, qtbot, tmp_path):
    sheet = _make_sheet(qtbot, tmp_path)
    f = tmp_path / "a.mf4"
    f.write_text("x")
    ev = _enter(_mime([f]))

    sheet.dragEnterEvent(ev)

    assert ev.isAccepted()


def test_batch_drag_enter_ignores_txt(qapp, qtbot, tmp_path):
    sheet = _make_sheet(qtbot, tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("x")
    ev = _enter(_mime([f]))

    sheet.dragEnterEvent(ev)

    assert not ev.isAccepted()
    assert sheet._drop_overlay is None or sheet._drop_overlay.isHidden()


def test_batch_drag_enter_ignores_directory(qapp, qtbot, tmp_path):
    sheet = _make_sheet(qtbot, tmp_path)
    d = tmp_path / "sub"
    d.mkdir()
    ev = _enter(_mime([d]))

    sheet.dragEnterEvent(ev)

    assert not ev.isAccepted()
    assert sheet._drop_overlay is None or sheet._drop_overlay.isHidden()


def test_batch_drag_enter_ignores_tlproj(qapp, qtbot, tmp_path):
    sheet = _make_sheet(qtbot, tmp_path)
    proj = tmp_path / "p.tlproj"
    proj.write_text("{}")
    ev = _enter(_mime([proj]))

    sheet.dragEnterEvent(ev)

    assert not ev.isAccepted()


def test_batch_drop_calls_add_disk_path_in_order(qapp, qtbot, tmp_path, monkeypatch):
    sheet = _make_sheet(qtbot, tmp_path)
    csv = tmp_path / "a.csv"
    csv.write_text("x")
    mf4 = tmp_path / "b.mf4"
    mf4.write_text("x")
    calls = []
    monkeypatch.setattr(
        sheet._input_panel._file_list,
        "add_disk_path",
        lambda p: calls.append(p),
    )

    sheet.dropEvent(_drop(_mime([csv, mf4])))

    assert [Path(p) for p in calls] == [csv, mf4]


def test_batch_drop_filters_unsupported_and_toasts(qapp, qtbot, tmp_path, monkeypatch):
    sheet = _make_sheet(qtbot, tmp_path)
    csv = tmp_path / "a.csv"
    csv.write_text("x")
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    calls = []
    monkeypatch.setattr(
        sheet._input_panel._file_list,
        "add_disk_path",
        lambda p: calls.append(p),
    )

    sheet.dropEvent(_drop(_mime([csv, txt])))

    assert [Path(p) for p in calls] == [csv]
    assert "忽略" in sheet._last_toast_text
    assert "1" in sheet._last_toast_text
    assert sheet._last_toast_kind == "warning"


def test_batch_drop_does_not_call_open_paths(qapp, qtbot, tmp_path, monkeypatch):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    opened = []

    def _forbid_open_paths(paths):
        opened.append(list(paths))

    sheet = BatchSheet(
        parent=None, files={}, current_preset=None,
        prefs_store=_prefs_store(tmp_path, "batch-drop-no-open.ini"),
    )
    qtbot.addWidget(sheet)
    # Guard against a regression that routes drops into MainWindow loading.
    monkeypatch.setattr(
        sheet, "_open_paths", _forbid_open_paths, raising=False,
    )
    csv = tmp_path / "a.csv"
    csv.write_text("x")
    calls = []
    monkeypatch.setattr(
        sheet._input_panel._file_list,
        "add_disk_path",
        lambda p: calls.append(p),
    )

    sheet.dropEvent(_drop(_mime([csv])))

    assert [Path(p) for p in calls] == [csv]
    assert opened == []


def test_batch_running_ignores_enter_and_drop(qapp, qtbot, tmp_path, monkeypatch):
    sheet = _make_sheet(qtbot, tmp_path)
    f = tmp_path / "a.csv"
    f.write_text("x")
    sheet._running = True
    calls = []
    monkeypatch.setattr(
        sheet._input_panel._file_list,
        "add_disk_path",
        lambda p: calls.append(p),
    )

    enter = _enter(_mime([f]))
    sheet.dragEnterEvent(enter)
    assert not enter.isAccepted()
    assert sheet._drop_overlay is None or sheet._drop_overlay.isHidden()

    sheet.dropEvent(_drop(_mime([f])))
    assert calls == []
    # closeEvent prompts when _running; clear so qtbot teardown cannot hang.
    sheet._running = False


def test_batch_duplicate_path_still_one_row(qapp, qtbot, tmp_path, monkeypatch):
    sheet = _make_sheet(qtbot, tmp_path)
    f = tmp_path / "a.csv"
    f.write_text("x")
    monkeypatch.setattr(
        sheet._input_panel._file_list,
        "_start_probe",
        lambda path: None,
    )

    sheet.dropEvent(_drop(_mime([f])))
    sheet.dropEvent(_drop(_mime([f])))

    assert len(sheet._input_panel._file_list._rows) == 1


def test_batch_overlay_hides_on_leave_and_drop(qapp, qtbot, tmp_path, monkeypatch):
    sheet = _make_sheet(qtbot, tmp_path)
    f = tmp_path / "a.csv"
    f.write_text("x")
    monkeypatch.setattr(
        sheet._input_panel._file_list, "add_disk_path", lambda p: None
    )

    sheet.dragEnterEvent(_enter(_mime([f])))
    assert not sheet._drop_overlay.isHidden()

    sheet.dragLeaveEvent(QDragLeaveEvent())
    assert sheet._drop_overlay.isHidden()

    sheet.dragEnterEvent(_enter(_mime([f])))
    sheet.dropEvent(_drop(_mime([f])))
    assert sheet._drop_overlay.isHidden()
