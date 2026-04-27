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
    for forbidden in ("file_ids", "file_paths", "signal", "rpm_signal"):
        assert forbidden not in raw
    assert raw["schema_version"] == 1
