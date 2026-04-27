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
