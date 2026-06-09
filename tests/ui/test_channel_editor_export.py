# tests/ui/test_channel_editor_export.py
import csv
import openpyxl
from PyQt5.QtWidgets import QFileDialog


def _csv(path, n=20):
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time", "rpm", "spd"])
        for i in range(n):
            w.writerow([i / 100.0, float(i), float(2 * i)])


def test_do_export_excel_writes_selected(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    out = tmp_path / "out.xlsx"
    mw = MainWindow(); mw._load_one(str(a))
    fid = next(iter(mw.files))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: (str(out), ""))
    mw._do_export_excel(fid, ["rpm"], include_time=True, use_range=False)
    assert out.exists()
    wb = openpyxl.load_workbook(out)
    headers = [c.value for c in wb.active[1]]
    assert headers == ["Time", "rpm"]
