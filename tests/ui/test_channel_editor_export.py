# tests/ui/test_channel_editor_export.py
import csv
import openpyxl
import pytest
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


def test_do_export_excel_filters_missing_channels_preserving_valid_request_order(
    qapp, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.main_window import MainWindow

    a = tmp_path / "a.csv"; _csv(a)
    out = tmp_path / "filtered.xlsx"
    mw = MainWindow(); mw._load_one(str(a))
    fid = next(iter(mw.files))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: (str(out), ""))

    mw._do_export_excel(
        fid, ["spd", "missing", "rpm"], include_time=True, use_range=False
    )

    wb = openpyxl.load_workbook(out)
    headers = [c.value for c in wb.active[1]]
    assert headers == ["Time", "spd", "rpm"]
    assert "missing" not in headers


@pytest.mark.parametrize(
    ("fid_kind", "channels"),
    [
        ("loaded", []),
        ("loaded", ["missing-channel"]),
        ("missing", ["rpm"]),
    ],
)
def test_do_export_excel_export_no_data_toasts_warning_without_save_dialog(
    qapp, tmp_path, monkeypatch, fid_kind, channels
):
    from mf4_analyzer.ui.main_window import MainWindow

    a = tmp_path / "a.csv"; _csv(a)
    mw = MainWindow(); mw._load_one(str(a))
    loaded_fid = next(iter(mw.files))
    fid = loaded_fid if fid_kind == "loaded" else "missing-fid"

    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append((msg, level)))

    def fail_save_dialog(*args, **kwargs):
        raise AssertionError("save dialog must not open when export has no data")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fail_save_dialog)

    mw._do_export_excel(fid, channels, include_time=True, use_range=False)

    assert toasts == [("没有可导出的数据或未勾选通道", "warning")]


def test_do_export_wwt_writes_roundtrippable_file(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.io.loader import DataLoader

    a = tmp_path / "a.csv"; _csv(a, n=128)
    out = tmp_path / "out.wwt"
    mw = MainWindow(); mw._load_one(str(a))
    fid = next(iter(mw.files))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: (str(out), ""))
    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append(msg))
    mw._do_export_channels(fid, ["rpm", "spd"], True, False, "wwt")
    assert out.exists()
    groups = DataLoader.load_wwt(str(out))
    assert len(groups) == 1
    assert "rpm" in groups[0]["channels"]
    assert "spd" in groups[0]["channels"]
    # clean-room 路径不重采样：点数与源一致
    assert len(groups[0]["data"]) == 128
    assert any("可打开" in t or "WinWert" in t for t in toasts)


def test_do_export_wwt_keeps_native_sample_values(qapp, tmp_path, monkeypatch):
    """导出走 float64 原值，不做量化——回读必须逐点精确。"""
    import numpy as np
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.io.loader import DataLoader

    a = tmp_path / "a.csv"; _csv(a, n=512)
    out = tmp_path / "exact.wwt"
    mw = MainWindow(); mw._load_one(str(a))
    fid = next(iter(mw.files))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: (str(out), ""))
    mw._do_export_wwt(fid, ["rpm"], use_range=False)
    src = mw.files[fid].data["rpm"].to_numpy()
    got = DataLoader.load_wwt(str(out))[0]["data"]["rpm"].to_numpy()
    np.testing.assert_allclose(got, src, rtol=0, atol=0)


def test_do_export_wwt_refuses_too_short_source(qapp, tmp_path, monkeypatch):
    """短于 100 点的源不能导出：补点等于凭空造数据，且 TraceLab 也读不回来。"""
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox

    a = tmp_path / "a.csv"; _csv(a, n=50)
    out = tmp_path / "short.wwt"
    mw = MainWindow(); mw._load_one(str(a))
    fid = next(iter(mw.files))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: (str(out), ""))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a_, **k: warned.append(a_[2]))
    mw._do_export_wwt(fid, ["rpm"], use_range=False)
    assert not out.exists()
    assert warned and "100" in warned[0]


def test_do_export_wwt_export_no_data_toasts_warning_without_save_dialog(
    qapp, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.main_window import MainWindow

    a = tmp_path / "a.csv"; _csv(a)
    mw = MainWindow(); mw._load_one(str(a))
    fid = next(iter(mw.files))
    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append((msg, level)))

    def fail_save_dialog(*args, **kwargs):
        raise AssertionError("save dialog must not open when export has no data")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", fail_save_dialog)
    mw._do_export_channels(fid, [], True, False, "wwt")
    assert toasts == [("没有可导出的数据或未勾选通道", "warning")]


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
        lambda fid, chs, t, r, fmt: captured.update(
            fid=fid, chs=chs, t=t, r=r, fmt=fmt
        )
    )
    dlg.chk_export_time.setChecked(True)
    dlg.chk_export_range.setChecked(False)
    dlg.btn_export.click()
    assert captured["fid"] == "f0"
    assert captured["chs"] == ["rpm"]
    assert captured["t"] is True and captured["r"] is False
    assert captured["fmt"] == "excel"


def test_editor_export_wwt_format_emits_and_locks_time(qapp, tmp_path):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    dlg = ChannelEditorDialog(None, _make_files(tmp_path), "f0")
    idx = dlg.combo_export_format.findData("wwt")
    assert idx >= 0
    dlg.combo_export_format.setCurrentIndex(idx)
    assert dlg.btn_export.text() == "导出 WWT"
    assert dlg.chk_export_time.isChecked()
    assert not dlg.chk_export_time.isEnabled()
    captured = {}
    dlg.export_requested.connect(
        lambda fid, chs, t, r, fmt: captured.update(fmt=fmt, chs=chs)
    )
    dlg.btn_export.click()
    assert captured["fmt"] == "wwt"
    assert captured["chs"] == ["rpm", "spd"]


def test_drawer_reemits_export_requested(qapp, tmp_path):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer
    drawer = ChannelEditorDrawer(None, _make_files(tmp_path), "f0")
    got = {}
    drawer.export_requested.connect(
        lambda fid, chs, t, r, fmt: got.update(fid=fid, chs=chs, fmt=fmt))
    drawer._inner.btn_export.click()
    assert got["fid"] == "f0"
    assert got["chs"] == ["rpm", "spd"]   # both default-checked
    assert got["fmt"] == "excel"

def test_editor_export_no_selection_does_not_emit(qapp, tmp_path, monkeypatch):
    # Clicking 导出 with nothing checked must show an info prompt and NOT emit
    # (exercises the cold QMessageBox branch — guards against a NameError).
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QMessageBox
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    dlg = ChannelEditorDialog(None, _make_files(tmp_path), "f0")
    for i in range(dlg.list_export.count()):
        dlg.list_export.item(i).setCheckState(Qt.Unchecked)
    info = {}
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: info.setdefault("hit", True))
    fired = {"n": 0}
    dlg.export_requested.connect(lambda *a: fired.__setitem__("n", fired["n"] + 1))
    dlg.btn_export.click()
    assert fired["n"] == 0
    assert info.get("hit") is True
