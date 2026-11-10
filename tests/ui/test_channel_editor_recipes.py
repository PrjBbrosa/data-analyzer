"""Freeze the channel editor's six single ops, six dual ops, and expressions."""
import numpy as np
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from mf4_analyzer.ui.dialogs import ChannelEditorDialog


def _files(tmp_path, n=8):
    import pandas as pd
    from mf4_analyzer.io.file_data import FileData

    rpm = np.arange(n, dtype=float)
    torque = np.array([2.0, 0.0, -1.0, 4.0, 1.0, 3.0, 0.0, 5.0], dtype=float)
    frame = pd.DataFrame({
        "time": np.arange(n, dtype=float) / 10.0,
        "rpm": rpm,
        "torque": torque,
    })
    fd = FileData(
        tmp_path / "eps.csv", frame, list(frame.columns),
        {"rpm": "rpm", "torque": "Nm"},
    )
    return {"f0": fd}, fd


def _silence(monkeypatch):
    notes = []

    def _record(*args, **kwargs):
        notes.append(args)

    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(
            f"mf4_analyzer.ui.dialogs.channel_editor.QMessageBox.{name}",
            _record,
        )
    monkeypatch.setattr(
        "mf4_analyzer.ui.dialogs.channel_editor.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.Yes,
    )
    return notes


def _check_only(dlg, names):
    wanted = set(names)
    for item in dlg._iter_export_items():
        item.setCheckState(Qt.Checked if item.text() in wanted else Qt.Unchecked)


def test_dialog_single_dual_and_expression_match_numpy(qapp, tmp_path, monkeypatch):
    notes = _silence(monkeypatch)
    files, fd = _files(tmp_path)
    dlg = ChannelEditorDialog(None, files, "f0")
    time = np.array(fd.time_array, copy=True)
    rpm = fd.data["rpm"].to_numpy(dtype=float)
    torque = fd.data["torque"].to_numpy(dtype=float)
    single = {
        0: ("d_dt_rpm", np.gradient(rpm, time), "rpm"),
        1: (
            "int_rpm",
            np.concatenate(([0.0], np.cumsum(
                0.5 * (rpm[1:] + rpm[:-1]) * np.diff(time)
            ))),
            "rpm",
        ),
        2: ("scaled_rpm", rpm * 2.5, "rpm"),
        3: ("offset_rpm", rpm - 1.25, "rpm"),
        4: ("mavg_rpm", np.convolve(rpm, np.ones(3) / 3.0, mode="same"), "rpm"),
        5: ("abs_rpm", np.abs(rpm), "rpm"),
    }
    dlg.combo_src.setCurrentText("rpm")
    for index, (name, expected, unit) in single.items():
        dlg.combo_op.setCurrentIndex(index)
        if index == 2:
            dlg.spin_p.setValue(2.5)
        elif index == 3:
            dlg.spin_p.setValue(-1.25)
        elif index == 4:
            dlg.spin_p.setValue(1)
        dlg._create_single()
        assert name in dlg.new_channels, notes
        values, got_unit = dlg.new_channels[name]
        np.testing.assert_array_equal(np.asarray(values), expected)
        assert got_unit == unit
        assert dlg._edit_log.entries[-1].name == name
    assert dlg._edit_log.active_derive("mavg_rpm").param == 3

    dlg.combo_src.setCurrentText("rpm")
    dlg.combo_op.setCurrentIndex(5)
    dlg._create_single()
    assert "abs_rpm_1" in dlg.new_channels

    with np.errstate(divide="ignore", invalid="ignore"):
        divided = np.where(torque != 0, rpm / torque, 0.0)
    dual_expected = {
        "add": rpm + torque,
        "sub": rpm - torque,
        "mul": rpm * torque,
        "div": divided,
        "max": np.maximum(rpm, torque),
        "min": np.minimum(rpm, torque),
    }
    for index, (fn, expected) in enumerate(dual_expected.items()):
        dlg.combo_op2.setCurrentIndex(index)
        dlg.combo_a.setCurrentText("rpm")
        dlg.combo_b.setCurrentText("torque")
        dlg.edit_name2.setText(f"dual_{fn}")
        dlg._create_dual()
        assert f"dual_{fn}" in dlg.new_channels, notes
        values, unit = dlg.new_channels[f"dual_{fn}"]
        np.testing.assert_array_equal(np.asarray(values, dtype=float), expected)
        if fn == "div":
            assert unit == "rpm/Nm"
        else:
            assert unit == ""

    dlg.combo_op2.setCurrentIndex(dlg.CUSTOM_OP_INDEX)
    dlg.combo_a.setCurrentText("rpm")
    dlg.combo_b.setCurrentText("torque")
    dlg.edit_expr.setText("sqrt(A^2+B^2)*0.5")
    dlg.edit_name2.setText("mag")
    dlg._create_dual()
    assert "mag" in dlg.new_channels, notes
    np.testing.assert_allclose(
        np.asarray(dlg.new_channels["mag"][0], dtype=float),
        np.sqrt(rpm ** 2 + torque ** 2) * 0.5,
    )
    expr = dlg._edit_log.active_derive("mag")
    assert expr.a == "rpm" and expr.b == "torque"
    assert not notes


def test_dialog_moving_avg_window_at_least_the_series_is_the_mean(qapp, tmp_path, monkeypatch):
    _silence(monkeypatch)
    files, fd = _files(tmp_path)
    dlg = ChannelEditorDialog(None, files, "f0")
    dlg.combo_src.setCurrentText("rpm")
    dlg.combo_op.setCurrentIndex(4)
    assert dlg.spin_p.value() == 50
    dlg._create_single()
    rpm = fd.data["rpm"].to_numpy(dtype=float)
    np.testing.assert_array_equal(
        np.asarray(dlg.new_channels["mavg_rpm"][0]),
        np.full(rpm.shape, rpm.mean()),
    )


def test_dialog_create_then_delete_leaves_an_empty_log(qapp, tmp_path, monkeypatch):
    _silence(monkeypatch)
    files, _fd = _files(tmp_path)
    dlg = ChannelEditorDialog(None, files, "f0")
    dlg.combo_src.setCurrentText("rpm")
    dlg.combo_op.setCurrentIndex(5)
    dlg._create_single()
    assert "abs_rpm" in dlg.new_channels
    _check_only(dlg, {"abs_rpm"})
    dlg._remove()
    assert dlg._edit_log.entries == []
    assert dlg.new_channels == {}
    assert dlg.removed_channels == set()


def test_dialog_delete_of_a_loader_channel_is_recorded(qapp, tmp_path, monkeypatch):
    _silence(monkeypatch)
    files, _fd = _files(tmp_path)
    dlg = ChannelEditorDialog(None, files, "f0")
    _check_only(dlg, {"rpm"})
    dlg._remove()
    assert dlg.removed_channels == {"rpm"}
    assert dlg._edit_log.entries[-1].names == ("rpm",)
    assert "rpm" not in dlg.new_channels


def _combo_texts(combo):
    return [combo.itemText(index) for index in range(combo.count())]


def test_single_create_rejects_a_channel_marked_for_removal(qapp, tmp_path, monkeypatch):
    notes = _silence(monkeypatch)
    files, _fd = _files(tmp_path)
    dlg = ChannelEditorDialog(None, files, "f0")
    _check_only(dlg, {"rpm"})
    dlg._remove()
    logged = list(dlg._edit_log.entries)
    dlg.combo_src.setCurrentText("rpm")
    dlg.combo_op.setCurrentIndex(5)
    dlg._create_single()
    assert dlg.new_channels == {}
    assert dlg._edit_log.entries == logged
    assert notes[-1][1] == "无法创建"
    assert "rpm" in notes[-1][2]
    assert "已标记删除" in notes[-1][2]
    assert "源通道不存在或参数越界" not in notes[-1][2]


def test_dual_create_rejects_a_channel_marked_for_removal(qapp, tmp_path, monkeypatch):
    notes = _silence(monkeypatch)
    files, _fd = _files(tmp_path)

    dlg = ChannelEditorDialog(None, files, "f0")
    _check_only(dlg, {"rpm"})
    dlg._remove()
    logged = list(dlg._edit_log.entries)
    dlg.combo_a.setCurrentText("rpm")
    dlg.combo_b.setCurrentText("torque")
    dlg.combo_op2.setCurrentIndex(0)
    dlg.edit_name2.setText("sum_rpm")
    dlg._create_dual()
    assert dlg.new_channels == {}
    assert dlg._edit_log.entries == logged
    assert "rpm" in notes[-1][2] and "已标记删除" in notes[-1][2]

    dlg = ChannelEditorDialog(None, files, "f0")
    _check_only(dlg, {"torque"})
    dlg._remove()
    logged = list(dlg._edit_log.entries)
    dlg.combo_a.setCurrentText("rpm")
    dlg.combo_b.setCurrentText("torque")
    dlg.combo_op2.setCurrentIndex(0)
    dlg.edit_name2.setText("sum_torque")
    dlg._create_dual()
    assert dlg.new_channels == {}
    assert dlg._edit_log.entries == logged
    assert "torque" in notes[-1][2] and "已标记删除" in notes[-1][2]


def test_remove_drops_the_name_from_source_combos(qapp, tmp_path, monkeypatch):
    _silence(monkeypatch)
    files, _fd = _files(tmp_path)
    dlg = ChannelEditorDialog(None, files, "f0")
    _check_only(dlg, {"rpm"})
    dlg._remove()
    for combo in (dlg.combo_src, dlg.combo_a, dlg.combo_b):
        assert "rpm" not in _combo_texts(combo)
        assert "torque" in _combo_texts(combo)

    dlg = ChannelEditorDialog(None, files, "f0")
    dlg.combo_src.setCurrentText("rpm")
    dlg.combo_op.setCurrentIndex(5)
    dlg._create_single()
    assert "abs_rpm" in _combo_texts(dlg.combo_src)
    _check_only(dlg, {"abs_rpm"})
    dlg._remove()
    for combo in (dlg.combo_src, dlg.combo_a, dlg.combo_b):
        assert "abs_rpm" not in _combo_texts(combo)
        assert "rpm" in _combo_texts(combo)


def test_derive_then_delete_source_survives_apply(qapp, qtbot, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    _silence(monkeypatch)
    csv_path = tmp_path / "eps.csv"
    csv_path.write_text(
        "time,rpm,torque\n" + "".join(f"{i / 10},{i},{i % 4}\n" for i in range(8)),
        encoding="utf-8",
    )
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._load_one(str(csv_path))
    fid = next(iter(mw.files))
    dlg = ChannelEditorDialog(None, mw.files, fid)
    dlg.combo_src.setCurrentText("rpm")
    dlg.combo_op.setCurrentIndex(5)
    dlg._create_single()
    _check_only(dlg, {"rpm"})
    dlg._remove()
    assert "abs_rpm" in dlg.new_channels
    assert any(entry.name == "abs_rpm" for entry in dlg._edit_log.entries)
    monkeypatch.setattr(mw, "_confirm_global_channel_delete", lambda _uses: True)
    mw._apply_channel_edits(
        fid,
        dict(dlg.new_channels),
        set(dlg.removed_channels),
        list(dlg._edit_log.entries),
    )
    fd = mw.files[fid]
    assert "abs_rpm" in fd.channels
    assert "rpm" not in fd.data.columns
