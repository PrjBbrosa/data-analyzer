"""T4 consumer contracts: Excel/WWT use_range, Batch seed, full vs selected.

Implementation already gates Batch on ``range_enabled()`` and lets export
dialogs pass their own ``use_range``. These spies freeze that wiring without
running a large real export.
"""
from __future__ import annotations

import csv
from types import SimpleNamespace

import pandas as pd
import pytest
from PyQt5.QtWidgets import QFileDialog


DISPLAY_LO = 0.05
DISPLAY_HI = 0.10


def _write_csv(path, n=20):
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "rpm", "spd"])
        for i in range(n):
            writer.writerow([i / 100.0, float(i), float(2 * i)])


def _full_window_with_display_span(mw, lo=DISPLAY_LO, hi=DISPLAY_HI):
    top = mw.inspector.top
    top.set_range_enabled(False, silent=True)
    top.set_range_values(lo, hi)
    assert top.range_enabled() is False
    got = top.range_values()
    assert got == pytest.approx((lo, hi))
    return top


def test_excel_use_range_true_exports_display_span_even_in_full_mode(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    src = tmp_path / "a.csv"
    _write_csv(src)
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._load_one(str(src))
    fid = next(iter(mw.files))
    top = _full_window_with_display_span(mw)

    reads = []
    real_range = top.range_values

    def spy_range():
        values = real_range()
        reads.append(values)
        return values

    captured = {}

    def spy_to_excel(self, *args, **kwargs):
        captured["n"] = len(self)
        captured["time"] = list(self["Time"])

    monkeypatch.setattr(top, "range_values", spy_range)
    monkeypatch.setattr(pd.DataFrame, "to_excel", spy_to_excel)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(tmp_path / "out.xlsx"), ""),
    )

    mw._do_export_excel(fid, ["rpm"], include_time=True, use_range=True)

    assert len(reads) == 1
    assert reads[0] == pytest.approx((DISPLAY_LO, DISPLAY_HI))
    assert captured["time"] == pytest.approx(
        [i / 100.0 for i in range(5, 11)]
    )
    assert captured["n"] == 6


def test_excel_use_range_false_exports_full_even_when_display_is_local(
    qapp, qtbot, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    src = tmp_path / "a.csv"
    _write_csv(src)
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._load_one(str(src))
    fid = next(iter(mw.files))
    top = _full_window_with_display_span(mw)

    reads = []
    real_range = top.range_values

    def spy_range():
        values = real_range()
        reads.append(values)
        return values

    captured = {}

    def spy_to_excel(self, *args, **kwargs):
        captured["n"] = len(self)
        captured["time"] = list(self["Time"])

    monkeypatch.setattr(top, "range_values", spy_range)
    monkeypatch.setattr(pd.DataFrame, "to_excel", spy_to_excel)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(tmp_path / "out.xlsx"), ""),
    )

    mw._do_export_excel(fid, ["rpm"], include_time=True, use_range=False)

    assert reads == []
    assert captured["n"] == 20
    assert captured["time"][0] == pytest.approx(0.0)
    assert captured["time"][-1] == pytest.approx(0.19)


@pytest.mark.parametrize("use_range, expected_n", [(True, 11), (False, 128)])
def test_wwt_use_range_respects_dialog_flag_not_full_mode(
    qapp, qtbot, tmp_path, monkeypatch, use_range, expected_n,
):
    from mf4_analyzer.io import wwt_export
    from mf4_analyzer.ui.main_window import MainWindow

    src = tmp_path / "a.csv"
    _write_csv(src, n=128)
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._load_one(str(src))
    fid = next(iter(mw.files))
    top = _full_window_with_display_span(mw, lo=0.10, hi=0.20)

    reads = []
    real_range = top.range_values

    def spy_range():
        values = real_range()
        reads.append(values)
        return values

    captured = {}

    def spy_export_wwt(out_path, time, channels, **kwargs):
        captured["n"] = len(time)
        captured["t0"] = float(time[0])
        captured["t1"] = float(time[-1])
        return SimpleNamespace(summary="spy")

    monkeypatch.setattr(top, "range_values", spy_range)
    monkeypatch.setattr(wwt_export, "export_wwt", spy_export_wwt)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        lambda *a, **k: (str(tmp_path / "out.wwt"), ""),
    )

    mw._do_export_wwt(fid, ["rpm"], use_range=use_range)

    if use_range:
        assert len(reads) == 1
        assert reads[0] == pytest.approx((0.10, 0.20))
        assert captured["t0"] == pytest.approx(0.10)
        assert captured["t1"] == pytest.approx(0.20)
    else:
        assert reads == []
        assert captured["t0"] == pytest.approx(0.0)
        assert captured["t1"] == pytest.approx(1.27)
    assert captured["n"] == expected_n


def test_batch_full_mode_does_not_inject_display_window(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "time")
    monkeypatch.setattr(
        win.channel_list,
        "get_checked_channels",
        lambda: [("f1", "sig", "#ff0000")],
    )
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: False)
    monkeypatch.setattr(win.inspector.top, "range_values", lambda: (12.0, 18.0))

    preset = win._build_current_batch_preset()

    assert preset is not None
    assert "time_range" not in preset.params


def test_batch_fft_full_mode_does_not_inject_display_window(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "fft")
    monkeypatch.setattr(
        win.inspector.fft_ctx, "current_signal", lambda: ("f1", "sig")
    )
    monkeypatch.setattr(
        win.inspector.fft_ctx,
        "current_params",
        lambda: {"window": "hanning", "nfft": 1024},
    )
    monkeypatch.setattr(win.inspector.fft_ctx, "fs", lambda: 1000.0)
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: False)
    monkeypatch.setattr(win.inspector.top, "range_values", lambda: (12.0, 18.0))

    preset = win._build_current_batch_preset()

    assert preset.method == "fft"
    assert "time_range" not in preset.params


def test_batch_selected_range_forwards_span(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "time")
    monkeypatch.setattr(
        win.channel_list,
        "get_checked_channels",
        lambda: [("f1", "sig", "#ff0000")],
    )
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: True)
    monkeypatch.setattr(win.inspector.top, "range_values", lambda: (12.0, 18.0))

    preset = win._build_current_batch_preset()

    assert preset.params["time_range"] == (12.0, 18.0)
