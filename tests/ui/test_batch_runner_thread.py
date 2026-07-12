"""Tests for ``BatchRunnerThread`` and ``BatchSheet`` cancel-button wiring.

Per spec §6.2: unlock is bound to ``QThread.finished`` (Qt-emitted signal),
NOT to ``finished_with_result``. This guarantees the dialog never gets
stuck locked even if ``runner.run()`` raises before the result signal.
"""


def test_runner_thread_emits_progress_and_result(qtbot, tmp_path):
    """Smoke test that the QThread wrapper forwards events + final result."""
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import (
        AnalysisPreset, BatchRunner,
    )
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch.runner_thread import BatchRunnerThread

    n = 1024
    t = np.arange(n) / 512.0
    df = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 50 * t)})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0)
    preset = AnalysisPreset.from_current_single(
        name="t", method="fft", signal=(0, "sig"),
        params={"fs": 512.0, "window": "hanning", "nfft": 512},
    )
    runner = BatchRunner({0: fd})
    th = BatchRunnerThread(runner, preset, tmp_path / "out")
    events, results = [], []
    th.progress.connect(events.append)
    th.finished_with_result.connect(results.append)
    th.start()
    qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)
    assert results[0].status == "done"
    assert any(e.kind == "run_finished" for e in events)


def test_sheet_cancel_button_unlocks_editing(qtbot, tmp_path):
    """Click 中断 → cancel_token set → thread.finished → editing unlocked,
    buttons restored. Pinned to QThread.finished, not finished_with_result.
    """
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    # Build a 3-file batch so cancel mid-run is observable
    fds = {}
    for i in range(3):
        n = 4096
        t = np.arange(n) / 512.0
        df = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 50 * t)})
        fds[i] = FileData(tmp_path / f"x{i}.csv", df,
                          list(df.columns), {}, idx=i)
    sheet = BatchSheet(None, files=fds)
    qtbot.addWidget(sheet)
    sheet.apply_files(file_ids=tuple(fds.keys()), file_paths=())
    sheet.apply_signals(("sig",))
    sheet.apply_method("fft")
    sheet.apply_params({"window": "hanning", "nfft": 512})
    sheet.apply_outputs(BatchOutput(
        export_data=True, export_image=False, data_format="csv"))
    sheet._output_panel.apply_directory(str(tmp_path / "out"))

    sheet._on_run_clicked()
    qtbot.waitUntil(lambda: sheet._running is True, timeout=1000)
    sheet._on_cancel_clicked()  # 中断 button handler
    qtbot.waitUntil(lambda: sheet._running is False, timeout=5000)
    # Editing must be re-enabled
    assert sheet._input_panel.isEnabled()
    assert sheet._analysis_panel.isEnabled()
    assert sheet._output_panel.isEnabled()


def test_sheet_run_passes_db_reference_catalog_snapshot_from_parent(qtbot, tmp_path):
    """dB-reference-defaults Task 10 Part A regression: ``BatchSheet``'s
    ``_on_run_clicked`` is the ONLY live Batch Run path (``MainWindow.
    open_batch``'s own ``BatchRunner`` call is dead code -- ``dlg.exec_()``
    never returns ``Accepted``). It must read ``parent().db_reference_store``
    and forward ``snapshot()``/``prefer_channel_metadata`` into
    ``BatchRunner`` exactly like Task 9 already wired the (unreachable)
    ``open_batch`` call site.

    Proven end-to-end: a channel carries a quantity/unit
    (``torque``/``Nm``) absent from the factory catalog, so an unwired Run
    path would resolve the neutral ``generic`` default (``1.0``, no
    warning) -- resolving instead to the ISOLATED store's custom override
    value (``3.0``, source ``user``) is only possible if the live click
    handler actually forwarded the snapshot.
    """
    import numpy as np
    import pandas as pd
    import pytest
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.db_reference_settings import DbReferenceSettingsStore
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    from PyQt5.QtCore import QSettings

    ini_path = tmp_path / "isolated-db-reference.ini"
    store = DbReferenceSettingsStore(settings=QSettings(str(ini_path), QSettings.IniFormat))
    result = store.save(
        overrides=[],
        custom=[{
            "id": "user.torque_custom",
            "quantity": "torque",
            "label": "自定义扭矩基准",
            "unit": "Nm",
            "aliases": ["Nm"],
            "reference": 3.0,
        }],
        hidden_builtin_ids=[],
        prefer_channel_metadata=True,
    )
    assert result.ok is True

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.db_reference_store = store

    n = 1024
    t = np.arange(n) / 512.0
    df = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 50 * t)})
    fd = FileData(
        tmp_path / "x.csv", df, list(df.columns), {}, idx=0,
        channel_metadata={"sig": {"quantity": "torque", "unit": "Nm"}},
    )

    sheet = BatchSheet(parent, files={0: fd})
    qtbot.addWidget(sheet)
    sheet.apply_files(file_ids=(0,), file_paths=())
    sheet.apply_signals(("sig",))
    sheet.apply_method("fft")
    sheet.apply_params({"window": "hanning", "nfft": 512, "amp_y": "dB"})
    from mf4_analyzer.batch import BatchOutput
    sheet.apply_outputs(BatchOutput(
        export_data=False, export_image=True, data_format="csv"))
    sheet._output_panel.apply_directory(str(tmp_path / "out"))

    # Read the result back via ``sheet._last_result`` (set by the Sheet's
    # OWN ``finished_with_result`` handler, wired BEFORE ``thread.start()``
    # inside ``_on_run_clicked``) rather than connecting a spy to
    # ``sheet._runner_thread.finished_with_result`` after the fact: a
    # cross-thread ``pyqtSignal.emit()`` only reaches receivers connected
    # AT THE MOMENT of emission, so a post-``_on_run_clicked()`` connect
    # racing an already-fast-finishing worker thread could silently drop
    # the one-shot signal. ``sheet._running is False`` mirrors the
    # existing ``test_sheet_cancel_button_unlocks_editing`` convention.
    sheet._on_run_clicked()
    qtbot.waitUntil(lambda: sheet._running is False, timeout=5000)

    result = sheet._last_result
    assert result is not None and result.status == "done"
    item = result.items[0]
    assert item.db_reference_value == pytest.approx(3.0)
    assert item.db_reference_source == "user"
