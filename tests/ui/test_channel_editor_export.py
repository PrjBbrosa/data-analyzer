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


def _make_files(tmp_path):
    import pandas as pd
    import numpy as np
    from mf4_analyzer.io.file_data import FileData
    df = pd.DataFrame({"time": np.arange(20) / 100.0,
                       "rpm": np.arange(20.0), "spd": np.arange(20.0) * 2})
    fd = FileData(str(tmp_path / "demo.mf4"), df, list(df.columns), {}, 0)
    return {"f0": fd}


def test_editor_has_export_section_between_dual_and_delete(qapp, tmp_path):
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    from PyQt5.QtWidgets import QGroupBox
    dlg = ChannelEditorDialog(None, _make_files(tmp_path), "f0")
    boxes = [b.title() for b in dlg.findChildren(QGroupBox)]
    assert "导出" in boxes
    # order: 双通道运算 ... 导出 ... 删除
    assert boxes.index("导出") > boxes.index("双通道运算 (A ⊕ B)")
    assert boxes.index("导出") < boxes.index("删除")
    # checkable export list, defaults checked
    assert dlg.list_export.count() == 2  # rpm, spd (time excluded)


def test_editor_export_button_emits_signal(qapp, tmp_path):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    dlg = ChannelEditorDialog(None, _make_files(tmp_path), "f0")
    # uncheck spd, keep rpm
    for i in range(dlg.list_export.count()):
        it = dlg.list_export.item(i)
        it.setCheckState(Qt.Checked if it.text() == "rpm" else Qt.Unchecked)
    captured = {}
    dlg.export_requested.connect(
        lambda fid, chs, t, r: captured.update(fid=fid, chs=chs, t=t, r=r))
    dlg.chk_export_time.setChecked(True)
    dlg.chk_export_range.setChecked(False)
    dlg.btn_export.click()
    assert captured["fid"] == "f0"
    assert captured["chs"] == ["rpm"]
    assert captured["t"] is True and captured["r"] is False


def test_drawer_reemits_export_requested(qapp, tmp_path):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer
    drawer = ChannelEditorDrawer(None, _make_files(tmp_path), "f0")
    got = {}
    drawer.export_requested.connect(
        lambda fid, chs, t, r: got.update(fid=fid, chs=chs))
    drawer._inner.btn_export.click()
    assert got["fid"] == "f0"
    assert got["chs"] == ["rpm", "spd"]   # both default-checked
