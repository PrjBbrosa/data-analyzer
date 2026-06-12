# tests/ui/test_project_session.py
from mf4_analyzer import app_meta


def test_app_meta_constants():
    assert app_meta.APP_VERSION == "v7.0"
    assert app_meta.WINDOW_TITLE == "TraceLab v7.0"
    assert app_meta.RELEASE_URL.startswith("https://")


def test_window_title_uses_app_meta(qapp):
    from mf4_analyzer.ui.main_window import MainWindow
    mw = MainWindow()
    assert mw.windowTitle() == app_meta.WINDOW_TITLE


import csv


def _write_csv(path, n=40):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "rpm"])
        for i in range(n):
            w.writerow([i / 100.0, float(i)])


def test_save_project_writes_file(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui import project_io as pio
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw.view_manager.rename(0, "主视图")
    proj = tmp_path / "s.tlproj"
    mw.save_project(proj)

    doc = pio.load_project_from_json(proj)
    assert [f.path_abs for f in doc.files] == [str(csv_a.resolve())]
    assert doc.files[0].path_rel == "a.csv"
    assert doc.views[0]["name"] == "主视图"
    assert doc.current_mode == "time"


def test_open_project_roundtrip(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw._load_one(str(csv_b))
    mw.view_manager.rename(0, "主视图")
    mw.save_project(proj)

    mw2 = MainWindow()
    mw2.open_project(proj)
    assert [fd.filename for fd in mw2.files.values()] == ["a.csv", "b.csv"]
    assert mw2.view_manager.views[0].name == "主视图"
    assert mw2.chart_stack.current_mode() == "time"


def test_open_project_restores_non_time_mode_consistently(qapp, tmp_path):
    # Reopening a project saved in a non-time mode must leave the chart,
    # the toolbar segment, and the inspector all agreeing on that mode —
    # not just the chart canvas (regression guard for the open_project
    # mode-restore path going through toolbar._set_mode).
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw.chart_stack.set_mode("fft")
    mw.save_project(proj)

    mw2 = MainWindow()
    mw2.open_project(proj)
    assert mw2.chart_stack.current_mode() == "fft"
    assert mw2.toolbar.current_mode() == "fft"


def test_open_project_skips_missing(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw._load_one(str(csv_b))
    mw.save_project(proj)
    csv_b.unlink()  # make one file missing

    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("hit", True))
    mw2 = MainWindow()
    mw2.open_project(proj)
    assert [fd.filename for fd in mw2.files.values()] == ["a.csv"]
    assert warned.get("hit") is True
