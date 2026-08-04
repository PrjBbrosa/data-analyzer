"""Tests for the Wave-7 toolbar buttons (preset import / export +
fill-from-current).

Five tests verbatim from plan §Wave 7 Step 1 — they exercise:

1. ``apply_preset`` for a ``free_config`` preset (signal picker + method +
   RPM channel are filled, files are NOT cleared).
2. ``apply_preset`` for a ``current_single`` preset (picker filled with
   the captured signal, file list narrowed to the captured file id,
   ``time_range`` round-tripped).
3. ``apply_preset`` red-marks signals that fall outside the current file
   intersection (spec §4.2).
4. ``_on_import_preset`` surfaces an ``UnsupportedPresetVersion`` via
   the warning toast.
5. ``_on_export_preset`` strips runtime / legacy fields and writes
   ``schema_version == 1``.

The ``qt_app_files`` fixture is module-local: it builds a one-file
in-memory ``FileData`` map (CSV pattern, mirroring the W6 runner-thread
test) so the sheet can resolve the captured ``signal_fid`` against
``_files_source``.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from PyQt5.QtWidgets import QFileDialog


@pytest.fixture
def qt_app_files(tmp_path):
    """One-file FileData map keyed by fid=0 with a 'sig' column.

    The file path lives under ``tmp_path`` so each test gets a fresh
    on-disk artefact even though the FileData itself is in-memory. The
    'Time' column is filtered out of the signal universe by
    ``FileData.get_signal_channels`` (it is in ``_TIME_NAMES``), leaving
    ``{"sig"}`` as the picker's available set.
    """
    import numpy as np
    import pandas as pd
    from mf4_analyzer.io import FileData

    n = 256
    t = np.arange(n) / 128.0
    df = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 10 * t)})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0)
    return {0: fd}


def test_apply_preset_free_config_fills_picker(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    from mf4_analyzer.batch import AnalysisPreset
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    p = AnalysisPreset.free_config(
        name="t", method="order_time",
        target_signals=("vibration_x",), rpm_channel="engine_rpm",
        params={"window": "hanning", "nfft": 1024, "max_order": 20.0},
    )
    sheet.apply_preset(p)
    assert sheet.method() == "order_time"
    assert "vibration_x" in sheet.selected_signals()
    assert sheet.rpm_channel() == "engine_rpm"


def test_apply_preset_current_single_round_trip(qtbot, tmp_path, qt_app_files):
    """current_single preset (from main window) should fill picker with the
    one captured signal and select that file (spec §6.4)."""
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    from mf4_analyzer.batch import AnalysisPreset
    files = qt_app_files  # fixture providing {fid: FileData}
    sheet = BatchSheet(None, files=files)
    qtbot.addWidget(sheet)
    fid = next(iter(files))
    p = AnalysisPreset.from_current_single(
        name="cs", method="fft", signal=(fid, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024,
                "time_range": (1.0, 5.0)},
    )
    sheet.apply_preset(p)
    assert sheet.method() == "fft"
    assert sheet.selected_signals() == ("sig",)
    assert fid in sheet.file_ids()
    assert sheet.time_range() == (1.0, 5.0)


@pytest.mark.parametrize(
    ("group_by", "expected_artifacts"),
    (("none", 8), ("source", 6), ("channel", 6)),
)
def test_run_click_uses_real_group_preview_artifact_count(
    qtbot, tmp_path, monkeypatch, group_by, expected_artifacts,
):
    import numpy as np
    import pandas as pd

    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch.runner_thread import BatchRunnerThread
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    t = np.arange(32, dtype=float) / 32.0
    frame = pd.DataFrame({"Time": t, "sig": t * 2.0, "sig2": t * 3.0})
    files = {
        "source-a": FileData(
            tmp_path / "a.csv", frame.copy(), list(frame), {}, idx=0,
        ),
        "source-b": FileData(
            tmp_path / "b.csv", frame.copy(), list(frame), {}, idx=1,
        ),
    }
    sheet = BatchSheet(None, files=files)
    qtbot.addWidget(sheet)
    sheet.apply_files(("source-a", "source-b"), ())
    sheet.apply_signals(("sig", "sig2"))
    sheet.apply_method("time")
    if group_by != "none":
        sheet.apply_params({"render_group_by": group_by})
    sheet._output_panel.apply_directory(str(tmp_path / f"out-{group_by}"))
    sheet._resume_manifest_path = str(tmp_path / "runtime-only.json")

    monkeypatch.setattr(BatchRunnerThread, "start", lambda _thread: None)

    sheet._on_run_clicked()
    try:
        assert sheet._runner_thread is not None
        assert not hasattr(sheet._runner_thread._preset, "resume_manifest")
        assert sheet._task_list.row_count() == 4
        assert sheet._task_list._idle_label.text() == (
            f"4 \u4efb\u52a1\u5f85\u6267\u884c \u00b7 "
            f"{expected_artifacts} \u8f93\u51fa"
        )
    finally:
        sheet._on_thread_finished()


def test_build_current_batch_preset_supports_fft_time(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    params = {
        "window": "blackman",
        "nfft": 2048,
        "overlap": 0.75,
        "remove_mean": False,
        "weighting": "A",
        "db_reference": 2.0,
        "avg_mode": "linear",
    }
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "fft_time")
    monkeypatch.setattr(
        win.inspector.fft_time_ctx, "current_signal", lambda: ("f1", "sig")
    )
    monkeypatch.setattr(
        win.inspector.fft_time_ctx,
        "get_params",
        lambda: (_ for _ in ()).throw(AssertionError("use current_params")),
    )
    monkeypatch.setattr(
        win.inspector.fft_time_ctx, "current_params", lambda: dict(params)
    )
    monkeypatch.setattr(win.inspector.fft_time_ctx, "fs", lambda: 512.0)
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: True)
    monkeypatch.setattr(win.inspector.top, "range_values", lambda: (1.0, 2.5))

    preset = win._build_current_batch_preset()

    assert preset.source == "current_single"
    assert preset.name == "当前 FFT vs Time"
    assert preset.method == "fft_time"
    assert preset.signal == ("f1", "sig")
    assert preset.params["window"] == "blackman"
    assert preset.params["nfft"] == 2048
    assert preset.params["overlap"] == 0.75
    assert preset.params["remove_mean"] is False
    assert preset.params["weighting"] == "A"
    assert preset.params["db_reference"] == 2.0
    assert preset.params["fs"] == 512.0
    # FFT-vs-Time consumes the complete valid matrix time domain.  The batch
    # bridge must use the recipe normalizer, so an FFT-only average field and
    # the Inspector's display range cannot leak into the preset.
    assert "avg_mode" not in preset.params
    assert "time_range" not in preset.params


def test_build_current_batch_preset_fft_uses_current_params(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "fft")
    monkeypatch.setattr(
        win.inspector.fft_ctx, "current_signal", lambda: ("f1", "sig")
    )
    monkeypatch.setattr(
        win.inspector.fft_ctx,
        "get_params",
        lambda: (_ for _ in ()).throw(AssertionError("use current_params")),
    )
    monkeypatch.setattr(
        win.inspector.fft_ctx,
        "current_params",
        lambda: {
            "window": "flattop",
            "nfft": 2048,
            "avg_mode": "线性平均",
            "avg_overlap": 75,
            "amp_y": "dB",
            "db_reference": 2.0,
        },
    )
    monkeypatch.setattr(win.inspector.fft_ctx, "fs", lambda: 1000.0)
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: False)

    preset = win._build_current_batch_preset()

    assert preset.method == "fft"
    assert preset.signal == ("f1", "sig")
    assert preset.params["avg_mode"] == "线性平均"
    assert preset.params["avg_overlap"] == 75
    assert preset.params["amp_y"] == "dB"
    assert preset.params["db_reference"] == 2.0
    assert preset.params["fs"] == 1000.0


def test_build_current_batch_preset_supports_time_domain(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "time")
    monkeypatch.setattr(
        win.channel_list,
        "get_checked_channels",
        lambda: [("f1", "sig_a", "#ff0000"), ("f2", "sig_b", "#00ff00")],
    )
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: True)
    monkeypatch.setattr(win.inspector.top, "range_values", lambda: (1.0, 2.0))
    fp = win.inspector.filter_panel
    fp.set_enabled(True)
    fp.set_kind("低通")
    fp.set_cutoff(50.0)
    fp.set_order(6)
    fp.chk_orig.setChecked(False)
    fp.chk_filt.setChecked(True)

    preset = win._build_current_batch_preset()

    assert preset.source == "free_config"
    assert preset.method == "time"
    assert preset.target_signals == ("sig_a", "sig_b")
    assert preset.file_ids == ("f1", "f2")
    assert preset.target_pairs == (("f1", "sig_a"), ("f2", "sig_b"))
    assert preset.params["time_range"] == (1.0, 2.0)
    assert preset.params["filter"]["enabled"] is True
    assert preset.params["filter"]["spec"]["kind"] == "low"
    assert preset.params["filter"]["spec"]["cutoff"] == 50.0
    assert preset.params["filter"]["show_original"] is False
    assert preset.params["filter"]["show_filtered"] is True


def test_apply_preset_marks_unavailable_signals(qtbot):
    """Imported preset whose target_signals are not in the file intersection
    must red-mark them and warn (spec §4.2 partial-missing rule)."""
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    from mf4_analyzer.batch import AnalysisPreset
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    p = AnalysisPreset.free_config(
        name="m", method="fft",
        target_signals=("absent_signal",),
        params={"window": "hanning", "nfft": 1024},
    )
    sheet.apply_preset(p)
    # Signal still selected, but red-marked
    assert "absent_signal" in sheet.selected_signals()
    assert sheet.signals_marked_unavailable() == ("absent_signal",)


def test_import_unsupported_version_toasts(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 99, "name": "x",
                                "method": "fft", "params": {}, "outputs": {}}))
    with patch.object(QFileDialog, "getOpenFileName",
                      return_value=(str(bad), "")):
        sheet._on_import_preset()
    assert sheet._last_toast_kind == "warning"
    assert "不支持" in sheet._last_toast_text


def test_export_strips_runtime_fields(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    out = tmp_path / "p.json"
    with patch.object(QFileDialog, "getSaveFileName",
                      return_value=(str(out), "")):
        sheet._on_export_preset()
    raw = json.loads(out.read_text(encoding="utf-8"))
    for forbidden in (
        "file_ids", "file_paths", "signal", "rpm_signal", "target_pairs",
    ):
        assert forbidden not in raw
    assert raw["schema_version"] == 1


def test_build_current_batch_preset_order_uses_complete_current_params(
    qtbot, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "order")
    monkeypatch.setattr(
        win.inspector.order_ctx, "current_signal", lambda: ("f1", "sig")
    )
    monkeypatch.setattr(
        win.inspector.order_ctx, "current_rpm", lambda: ("f2", "rpm")
    )
    monkeypatch.setattr(
        win.inspector.order_ctx,
        "get_params",
        lambda: (_ for _ in ()).throw(AssertionError("use current_params")),
    )
    monkeypatch.setattr(
        win.inspector.order_ctx,
        "current_params",
        lambda: {
            "nfft": None,
            "nfft_mode": "auto",
            "samples_per_rev": 2048,
            "rpm_mode": "manual",
            "manual_rpm": 1800.0,
            "db_reference_mode": "auto",
            "db_reference": 1.0,
        },
    )
    monkeypatch.setattr(win.inspector.order_ctx, "fs", lambda: 4096.0)
    monkeypatch.setattr(win.inspector.order_ctx, "rpm_factor", lambda: 2.0)
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: False)

    preset = win._build_current_batch_preset()

    assert preset.rpm_signal == ("f2", "rpm")
    assert preset.params["nfft"] is None
    assert preset.params["nfft_mode"] == "auto"
    assert preset.params["samples_per_rev"] == 2048
    assert preset.params["db_reference_mode"] == "auto"
    assert preset.params["fs"] == 4096.0
    assert preset.params["rpm_factor"] == 2.0
    # Batch retired the fixed-RPM mode, so the hand-off must not forward it
    # even though the order view still emits it (followup design C1).
    assert "manual_rpm" not in preset.params
    assert "rpm_mode" not in preset.params


def test_order_handoff_strips_retired_rpm_keys_and_keeps_everything_else(
    qtbot, monkeypatch,
):
    """The bridge hands batch a recipe batch can actually run.

    Before this, an order view sitting on a fixed RPM produced a preset whose
    only possible outcome was a per-item ``rpm channel is required`` deep in
    the run — the retired keys travelled but nothing consumed them.
    """
    from mf4_analyzer.batch_recipe import KNOWN_PARAM_FIELDS
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "order")
    monkeypatch.setattr(
        win.inspector.order_ctx, "current_signal", lambda: ("f1", "sig")
    )
    # A view on manual RPM reports no channel — that is the whole problem.
    monkeypatch.setattr(win.inspector.order_ctx, "current_rpm", lambda: None)
    monkeypatch.setattr(
        win.inspector.order_ctx,
        "current_params",
        lambda: {
            "max_order": 20.0,
            "order_res": 0.05,
            "samples_per_rev": 2048,
            "weighting": "A",
            "rpm_mode": "manual",
            "manual_rpm": 1800.0,
        },
    )
    monkeypatch.setattr(win.inspector.order_ctx, "fs", lambda: 4096.0)
    monkeypatch.setattr(win.inspector.order_ctx, "rpm_factor", lambda: 2.0)
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: False)

    preset = win._build_current_batch_preset()

    assert "rpm_mode" not in preset.params
    assert "manual_rpm" not in preset.params
    # Everything the user actually configured still travels.
    assert preset.params["max_order"] == 20.0
    assert preset.params["order_res"] == 0.05
    assert preset.params["samples_per_rev"] == 2048
    assert preset.params["weighting"] == "A"
    assert preset.params["fs"] == 4096.0
    assert preset.params["rpm_factor"] == 2.0
    # Nothing retired survives, whatever gets retired next.
    assert not (set(preset.params) - KNOWN_PARAM_FIELDS) & {
        "rpm_mode", "manual_rpm",
    }


def test_open_batch_puts_manual_rpm_handoff_notice_in_sheet(qtbot, monkeypatch):
    """The manual-RPM warning belongs to the modal sheet, not a host toast."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    # ``open_batch`` drops a preset whose file is gone before it looks at
    # anything else, so the file has to be registered for the RPM notice to
    # be reachable at all.
    monkeypatch.setitem(win.files, "f1", object())
    monkeypatch.setattr(win.toolbar, "current_mode", lambda: "order")
    monkeypatch.setattr(
        win.inspector.order_ctx, "current_signal", lambda: ("f1", "sig")
    )
    monkeypatch.setattr(win.inspector.order_ctx, "current_rpm", lambda: None)
    monkeypatch.setattr(
        win.inspector.order_ctx,
        "current_params",
        lambda: {"rpm_mode": "manual", "manual_rpm": 1800.0},
    )
    monkeypatch.setattr(win.inspector.order_ctx, "fs", lambda: 4096.0)
    monkeypatch.setattr(win.inspector.order_ctx, "rpm_factor", lambda: 1.0)
    monkeypatch.setattr(win.inspector.top, "range_enabled", lambda: False)

    toasts = []
    monkeypatch.setattr(
        win, "toast", lambda text, kind="info": toasts.append((text, kind))
    )
    discovered = []
    monkeypatch.setattr(win.chart_stack, "mark_discovered", discovered.append)
    sheets = []

    class _FakeSheet:
        def __init__(self, *args, **kwargs):
            self.notice = ""
            sheets.append(self)

        def set_handoff_notice(self, text):
            self.notice = text

        def exec_(self):
            return 0

    monkeypatch.setattr("mf4_analyzer.ui.drawers.batch.BatchSheet", _FakeSheet)

    for mode, expected_notice in (("manual", True), ("channel", False)):
        toasts.clear()
        sheets.clear()
        monkeypatch.setattr(win.inspector.order_ctx, "rpm_mode", lambda m=mode: m)
        win.open_batch()
        assert not [t for t, _kind in toasts if "RPM" in t], (mode, toasts)
        assert bool(sheets[0].notice) is expected_notice
        assert discovered[-1] == "batch.export_options"
        if expected_notice:
            assert "RPM 通道" in sheets[0].notice


def test_batch_sheet_handoff_notice_is_visible_beside_rpm_controls(qtbot):
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.set_handoff_notice(
        "批处理阶次分析不支持固定 RPM，请在批处理里指定 RPM 通道"
    )
    sheet.apply_method("order_time")
    sheet.show()

    assert sheet._handoff_notice.text() == (
        "批处理阶次分析不支持固定 RPM，请在批处理里指定 RPM 通道"
    )
    assert sheet._handoff_notice.isVisibleTo(sheet)
    notice_row, _role = sheet._input_panel._form_ref.getWidgetPosition(
        sheet._handoff_notice
    )
    assert notice_row == sheet._input_panel._rpm_factor_row_index + 1
