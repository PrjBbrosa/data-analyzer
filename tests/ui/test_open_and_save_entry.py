# tests/ui/test_open_and_save_entry.py
import csv
from PyQt5.QtWidgets import QFileDialog, QMessageBox


def _csv(path, n=30):
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time", "rpm"])
        for i in range(n):
            w.writerow([i / 100.0, float(i)])


def test_open_data_files_appends(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    b = tmp_path / "b.csv"; _csv(b)
    mw = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(a), str(b)], ""))
    mw.open_files_or_project()
    assert [fd.filename for fd in mw.files.values()] == ["a.csv", "b.csv"]


def test_open_single_project_replaces(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    proj = tmp_path / "s.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)

    mw2 = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(proj)], ""))
    mw2.open_files_or_project()
    assert [fd.filename for fd in mw2.files.values()] == ["a.csv"]


def test_open_replace_confirm_cancel_aborts(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    b = tmp_path / "b.csv"; _csv(b)
    proj = tmp_path / "s.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)

    mw._load_one(str(b))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(proj)], ""))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a_, **k: QMessageBox.No)
    before = [fd.filename for fd in mw.files.values()]
    mw.open_files_or_project()
    assert [fd.filename for fd in mw.files.values()] == before  # unchanged


def test_open_project_plus_files_adds_on_top(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    extra = tmp_path / "extra.csv"; _csv(extra)
    proj = tmp_path / "s.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)

    mw2 = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(proj), str(extra)], ""))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a_, **k: QMessageBox.Yes)
    mw2.open_files_or_project()
    assert sorted(fd.filename for fd in mw2.files.values()) == ["a.csv", "extra.csv"]


def test_open_multiple_projects_rejected(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    p1 = tmp_path / "x.tlproj"; p1.write_text("{}", encoding="utf-8")
    p2 = tmp_path / "y.tlproj"; p2.write_text("{}", encoding="utf-8")
    mw = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(p1), str(p2)], ""))
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a_, **k: warned.setdefault("hit", True))
    mw.open_files_or_project()
    assert warned.get("hit") is True
    assert len(mw.files) == 0


def test_save_disabled_on_empty_session_and_enabled_after_load(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow

    a = tmp_path / "a.csv"
    _csv(a)
    mw = MainWindow()
    assert not mw.toolbar.btn_save_project.isEnabled()
    assert not mw.toolbar.btn_save_caret.isEnabled()
    mw._load_one(str(a))
    assert mw.toolbar.btn_save_project.isEnabled()
    assert mw.toolbar.btn_save_caret.isEnabled()
    mw.close_all(force=True)
    assert not mw.toolbar.btn_save_project.isEnabled()
    assert not mw.toolbar.btn_save_caret.isEnabled()


def test_save_via_dialog_first_time_prompts(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QFileDialog
    a = tmp_path / "a.csv"; _csv(a)
    proj = tmp_path / "new.tlproj"
    mw = MainWindow(); mw._load_one(str(a))
    assert mw._project_path is None
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: (str(proj), ""))
    mw.save_project_via_dialog()
    assert proj.exists()
    assert str(mw._project_path) == str(proj)


def test_save_via_dialog_overwrites_known_path(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QFileDialog
    a = tmp_path / "a.csv"; _csv(a)
    proj = tmp_path / "p.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)   # sets _project_path
    called = {"n": 0}
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: called.__setitem__("n", called["n"] + 1) or ("", ""))
    mw.save_project_via_dialog()
    assert called["n"] == 0          # no Save-As prompt; overwrote known path
    assert proj.exists()


def test_open_project_sets_project_path(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    proj = tmp_path / "p.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)
    mw2 = MainWindow(); mw2.open_project(proj)
    assert str(mw2._project_path) == str(proj)


def test_open_project_sets_path_even_if_render_fails(qapp, tmp_path, monkeypatch):
    # The document is "open" once files/views load; a view-render hiccup must
    # not leave _project_path None (which would make 保存项目 prompt Save-As
    # for an already-open project).
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    proj = tmp_path / "p.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)
    mw2 = MainWindow()

    def _boom(*_a, **_k):
        raise RuntimeError("render failed")
    monkeypatch.setattr(mw2, "_apply_active_view", _boom)
    mw2.open_project(proj)
    assert str(mw2._project_path) == str(proj)
