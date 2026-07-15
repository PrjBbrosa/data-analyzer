from pathlib import Path

import mf4_analyzer.ui.main_window as mw
from mf4_analyzer.ui.main_window import MainWindow
from PyQt5.QtCore import QMimeData, QPoint, Qt, QUrl
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


def test_open_files_or_project_delegates_to_open_paths(qapp, qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))
    monkeypatch.setattr(
        mw.QFileDialog,
        "getOpenFileNames",
        lambda *a, **k: (["/x/a.csv", "/x/b.mf4"], ""),
    )

    w.open_files_or_project()

    assert captured == [["/x/a.csv", "/x/b.mf4"]]


def test_open_files_or_project_no_selection_skips_dispatch(qapp, qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileNames", lambda *a, **k: ([], ""))

    w.open_files_or_project()

    assert captured == []


def test_open_paths_dispatches_data_files_to_load_one(qapp, qtbot, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    loaded = []
    monkeypatch.setattr(w, "_load_one", lambda fp, **k: loaded.append(fp))

    w._open_paths(["/x/a.csv", "/x/b.mf4"])

    assert loaded == ["/x/a.csv", "/x/b.mf4"]


def test_accept_drops_enabled(qapp, qtbot):
    w = MainWindow()
    qtbot.addWidget(w)

    assert w.acceptDrops() is True


def test_drag_enter_accepts_supported(qapp, qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    f = tmp_path / "a.csv"
    f.write_text("x")
    ev = _enter(_mime([f]))

    w.dragEnterEvent(ev)

    assert ev.isAccepted()


def test_drag_enter_accepts_fdc(qapp, qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    f = tmp_path / "a.fdc"
    f.write_text("x")
    ev = _enter(_mime([f]))

    w.dragEnterEvent(ev)

    assert ev.isAccepted()


def test_drag_enter_accepts_asc(qapp, qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    f = tmp_path / "a.asc"
    f.write_text("Time\tSig\n0\t1\n")
    ev = _enter(_mime([f]))

    w.dragEnterEvent(ev)

    assert ev.isAccepted()


def test_drag_enter_ignores_unsupported(qapp, qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    f = tmp_path / "a.txt"
    f.write_text("x")
    ev = _enter(_mime([f]))

    w.dragEnterEvent(ev)

    assert not ev.isAccepted()


def test_drop_supported_calls_open_paths(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    csv = tmp_path / "a.csv"
    csv.write_text("x")
    mf4 = tmp_path / "b.mf4"
    mf4.write_text("x")
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))

    w.dropEvent(_drop(_mime([csv, mf4])))

    assert [[Path(path) for path in paths] for paths in captured] == [[csv, mf4]]


def test_drop_filters_unsupported_and_toasts(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    csv = tmp_path / "a.csv"
    csv.write_text("x")
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    captured, toasts = [], []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))
    monkeypatch.setattr(
        w, "toast", lambda msg, level="info": toasts.append((msg, level))
    )

    w.dropEvent(_drop(_mime([csv, txt])))

    assert [[Path(path) for path in paths] for paths in captured] == [[csv]]
    assert len(toasts) == 1 and "1" in toasts[0][0]


def test_drop_directory_is_filtered(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    d = tmp_path / "sub"
    d.mkdir()
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))

    w.dropEvent(_drop(_mime([d])))

    assert captured == []


def test_drop_tlproj_passes_through(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    proj = tmp_path / "p.tlproj"
    proj.write_text("{}")
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))

    w.dropEvent(_drop(_mime([proj])))

    assert [[Path(path) for path in paths] for paths in captured] == [[proj]]


def test_overlay_shows_on_enter_hides_on_leave(qapp, qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    f = tmp_path / "a.csv"
    f.write_text("x")

    w.dragEnterEvent(_enter(_mime([f])))

    assert w._drop_overlay is not None
    assert not w._drop_overlay.isHidden()

    w.dragLeaveEvent(QDragLeaveEvent())

    assert w._drop_overlay.isHidden()


def test_overlay_hidden_after_drop(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow()
    qtbot.addWidget(w)
    f = tmp_path / "a.csv"
    f.write_text("x")
    monkeypatch.setattr(w, "_open_paths", lambda paths: None)

    w.dragEnterEvent(_enter(_mime([f])))
    w.dropEvent(_drop(_mime([f])))

    assert w._drop_overlay.isHidden()


def test_overlay_transparent_to_mouse(qapp, qtbot, tmp_path):
    w = MainWindow()
    qtbot.addWidget(w)
    f = tmp_path / "a.csv"
    f.write_text("x")

    w.dragEnterEvent(_enter(_mime([f])))

    assert w._drop_overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
