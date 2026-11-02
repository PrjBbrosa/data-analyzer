"""User-visible import diagnostics stay available after the transient toast."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, Qt

from mf4_analyzer.ui.main_window._project_io_mixin import ProjectIOMixin


def _metadata(*, record=5, state="partial"):
    return {
        "source_kind": "wwt",
        "source_filename": "sample.wwt",
        "skipped_channels": [{"name": "Signal", "reason": "missing-time"}],
        "import_diagnostics": {
            "schema": 1, "state": state, "source_kind": "wwt",
            "counts": {"imported_channels": 1, "skipped_channels": 1},
            "issues": [{
                "code": "missing_time", "message": "Signal 缺少时间轴，已跳过",
                "severity": state, "action": "skipped", "record_index": record,
                "channel": "Signal",
            }],
        },
    }


def test_structured_summary_dedupes_groups_and_legacy_skips():
    calls = []
    host = SimpleNamespace(toast=lambda text, level: calls.append((text, level)))
    meta = _metadata()
    ProjectIOMixin._toast_io_load_diagnostics(host, meta, meta)
    assert len(calls) == 1
    assert calls[0][1] == "warning"
    assert "部分导入" in calls[0][0]
    assert "缺少时间轴" in calls[0][0]


def test_restore_suppresses_toasts_without_removing_metadata():
    calls = []
    host = SimpleNamespace(
        toast=lambda text, level: calls.append((text, level)),
        _restoring_project=True,
    )
    meta = _metadata()
    ProjectIOMixin._toast_io_load_diagnostics(host, meta)
    assert calls == []
    assert meta["import_diagnostics"]["state"] == "partial"


def test_structured_summary_preserves_uncovered_legacy_facts():
    calls = []
    host = SimpleNamespace(toast=lambda text, level: calls.append((text, level)))
    meta = _metadata()
    meta["skipped_channels"].append({"name": "Label", "reason": "non-numeric"})
    meta["warnings"] = ["另外一项原始警告"]
    ProjectIOMixin._toast_io_load_diagnostics(host, meta)
    assert sum("缺少时间轴" in text for text, _ in calls) == 1
    assert any("Label" in text for text, _ in calls)
    assert any("另外一项原始警告" in text for text, _ in calls)


def test_file_card_details_survive_toast_and_follow_row_lifetime(qapp, qtbot):
    from mf4_analyzer.io.file_data import FileData
    from mf4_analyzer.ui.file_navigator import _FileRow
    from mf4_analyzer.ui.widgets.import_diagnostics import ImportDiagnosticsDialog

    frame = pd.DataFrame({"Time": [0., 1.], "Signal": [1., 2.]})
    fd = FileData("/tmp/sample.wwt", frame, list(frame), {}, source_metadata=_metadata())
    row = _FileRow("f1", fd)
    qtbot.addWidget(row)
    row.resize(288, row.sizeHint().height())
    row.show()
    qtbot.mouseClick(row._btn_import_details, Qt.LeftButton)
    dialog = row.findChild(ImportDiagnosticsDialog)
    assert dialog is not None and dialog.isVisible()
    text = dialog._details.toPlainText()
    assert "部分导入" in text and "缺少时间轴" in text
    assert "f1" in text and "记录" in text
    qtbot.mouseClick(row._btn_import_details, Qt.LeftButton)
    assert len(row.findChildren(ImportDiagnosticsDialog)) == 1
    row.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert sip.isdeleted(dialog)


def test_details_distinguish_unknown_and_physical_record_identity(qapp, qtbot):
    from mf4_analyzer.ui.widgets.import_diagnostics import ImportDiagnosticsDialog

    dialog = ImportDiagnosticsDialog([
        ("f1", "同名来源", _metadata(record=5)),
        ("f2", "同名来源", _metadata(record=6)),
        ("f3", "旧来源", {}),
    ])
    qtbot.addWidget(dialog)
    text = dialog._details.toPlainText()
    assert "f1" in text and "f2" in text and "f3" in text
    assert "记录 6" in text and "记录 7" in text
    assert "未记录" in text
    assert text.count("Signal 缺少时间轴，已跳过") == 2


def test_details_show_source_rows_and_legacy_skips(qapp, qtbot):
    from mf4_analyzer.ui.widgets.import_diagnostics import ImportDiagnosticsDialog

    metadata = _metadata()
    payload = metadata["import_diagnostics"]
    payload["counts"].update(count_scope="file", sample_count=128)
    payload["issues"][0]["source_rows"] = [4, 9]
    dialog = ImportDiagnosticsDialog([
        ("f1", "table.csv", metadata),
        ("f2", "old.mat", {"skipped_vars": ["notes"]}),
    ])
    qtbot.addWidget(dialog)
    text = dialog._details.toPlainText()
    assert "原始行 4, 9" in text
    assert "采样点数：128" in text and "计数范围：整个文件" in text
    assert "变量未导入：notes" in text


def test_csv_gui_consumes_attrs_and_does_not_announce_partial_success(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.io.loader import DataLoader

    frame = pd.DataFrame({"Time": np.arange(4.) * .01, "Signal": [1., np.nan, 2., 3.]})
    metadata = _metadata()
    metadata["source_kind"] = "csv"
    frame.attrs["source_metadata"] = metadata
    monkeypatch.setattr(DataLoader, "load_csv", lambda _path: (frame, list(frame), {}))
    mw = MainWindow()
    qtbot.addWidget(mw)
    calls = []
    monkeypatch.setattr(mw, "toast", lambda text, level="info": calls.append((text, level)))
    mw._load_one("/tmp/sample.csv")
    assert len(mw.files) == 1
    fd = next(iter(mw.files.values()))
    assert fd.source_metadata["import_diagnostics"]["state"] == "partial"
    assert any("部分导入" in text and level == "warning" for text, level in calls)
    assert not any(level == "success" for _text, level in calls)


@pytest.mark.parametrize("accept", [False, True])
@pytest.mark.parametrize("empty_reference", ["x", "y"])
def test_real_wwt_empty_axis_keeps_good_curves_and_warns_once(
    qapp, qtbot, tmp_path, monkeypatch, accept, empty_reference,
):
    from PyQt5.QtWidgets import QMessageBox
    from mf4_analyzer.ui.main_window import MainWindow
    from tests._helpers import wwt_factory as wwt

    n = wwt.CHANNEL_N
    path = wwt.write_wwt_file(tmp_path / "empty.wwt", (
        wwt.WwtRecordSpec("Zeit", "Time", "s", n=n, dt=.001),
        wwt.WwtRecordSpec("Real", "Good", "N", values=np.arange(n)),
        wwt.WwtRecordSpec("Zeit", "Empty", "s", n=0, dt=.001),
        wwt.WwtRecordSpec("Zeit", "Time", "s", n=n, dt=.001),
        wwt.WwtRecordSpec("Real", "Other", "N", values=np.arange(n)),
    ), (
        wwt.WwtWindowSpec(
            wwt.RECT_WIN_A, wwt.WwtCurveSpec(0, "Time", 0., .127),
            (wwt.WwtCurveSpec(1, "Good", 0., 127., x_record_index=0,
                              visible=True, selected=True),
             wwt.WwtCurveSpec(4 if empty_reference == "x" else 2, "Bad", 0., 127.,
                              x_record_index=2 if empty_reference == "x" else 0,
                              visible=True, selected=True)),
        ),
    ))
    mw = MainWindow()
    qtbot.addWidget(mw)
    calls, errors = [], []
    monkeypatch.setattr(mw, "toast", lambda text, level="info": calls.append((text, level)))
    monkeypatch.setattr(mw._wwt_import, "_ask_layout", lambda *args, **kwargs: accept)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args))
    mw._load_one(str(path))
    qapp.processEvents()
    assert not errors
    assert len(mw.files) == 1
    fd = next(iter(mw.files.values()))
    assert "Good" in fd.channels and len(fd.data) == n
    empty_warnings = [text for text, level in calls if level == "warning" and "空时间轴" in text]
    assert len(empty_warnings) == 1
    assert fd.source_metadata["import_diagnostics"]["state"] == "warning"
    if accept:
        assert any(channel == "Good" for view in mw.view_manager.views for _, channel in view.checked)


def test_saved_explicit_sampling_rate_reaches_untimed_csv_loader(qapp, qtbot, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow

    path = tmp_path / "untimed.csv"
    path.write_text("Signal\n1\n2\n3\n")
    mw = MainWindow()
    qtbot.addWidget(mw)
    frame = pd.DataFrame({"Signal": [1., 2., 3.]})
    fd = mw._register_file_data(str(path), frame, ["Signal"], {}, fs=500.)
    fd.rebuild_time_axis(500., reason="manual")
    project = tmp_path / "manual.tlproj"
    assert mw.save_project(project)
    mw.open_project(project)
    assert len(mw.files) == 1
    loaded = next(iter(mw.files.values()))
    assert loaded._time_source == "manual"
    np.testing.assert_allclose(loaded.time_array, [0., .002, .004])


def test_multi_file_partial_import_has_no_unconditional_success(qapp, qtbot, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    paths = []
    for name, values in (("good", "1\n2\n3"), ("partial", "1\nbroken\n3")):
        path = tmp_path / f"{name}.csv"
        rows = values.splitlines()
        path.write_text("Time,Signal\n" + "\n".join(f"{i * .01},{v}" for i, v in enumerate(rows)))
        paths.append(str(path))
    mw = MainWindow()
    qtbot.addWidget(mw)
    calls = []
    monkeypatch.setattr(mw, "toast", lambda text, level="info": calls.append((text, level)))
    mw._open_data_paths(paths)
    assert len(mw.files) == 2
    assert not any("已加载 2 个文件" in text and level == "success" for text, level in calls)
    assert any("1 个文件" in text and level == "warning" for text, level in calls)


def test_project_reopen_recomputes_diagnostics_and_keeps_details(qapp, qtbot, tmp_path, monkeypatch):
    import json
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.widgets.import_diagnostics import ImportDiagnosticsDialog

    path = tmp_path / "data.csv"
    path.write_text("Time,Signal\n0,1\n.01,2\n.02,3\n.03,4\n")
    project = tmp_path / "data.tlproj"
    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._load_one(str(path))
    assert mw.save_project(project)
    assert "import_diagnostics" not in json.dumps(json.loads(project.read_text()))
    path.write_text("Time,Signal\n0,1\n.01,broken\n.02,3\n.03,4\n")
    calls = []
    monkeypatch.setattr(mw, "toast", lambda text, level="info": calls.append((text, level)))
    mw.open_project(project)
    assert len(mw.files) == 1
    fd = next(iter(mw.files.values()))
    assert fd.source_metadata["import_diagnostics"]["state"] == "partial"
    row = next(iter(mw.navigator._rows.values()))
    row._show_import_details()
    dialog = row.findChild(ImportDiagnosticsDialog)
    assert "部分导入" in dialog._details.toPlainText()
    assert not any("缺口" in text and level == "warning" for text, level in calls)
