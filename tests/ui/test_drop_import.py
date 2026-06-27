import mf4_analyzer.ui.main_window as mw
from mf4_analyzer.ui.main_window import MainWindow


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
