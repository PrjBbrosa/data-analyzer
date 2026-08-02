"""Tests for ``BatchRunnerThread`` and ``BatchSheet`` cancel-button wiring.

Per spec §6.2: unlock is bound to ``QThread.finished`` (Qt-emitted signal),
NOT to ``finished_with_result``. This guarantees the dialog never gets
stuck locked even if ``runner.run()`` raises before the result signal.
"""


def test_runner_thread_marshals_real_render_to_gui_and_returns_complete_result(
    qtbot, qapp, tmp_path, monkeypatch,
):
    """Real data+PNG execution must block-marshal render work to the GUI."""
    import numpy as np
    import pandas as pd
    from PyQt5.QtCore import QThread
    from mf4_analyzer.batch import (
        AnalysisPreset, BatchRunner,
    )
    from mf4_analyzer.batch_manifest import load_batch_manifest
    import mf4_analyzer.batch_render_qt as qt_renderer
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch.runner_thread import BatchRunnerThread

    import threading

    render_threads = []
    encode_thread_ids = []
    original_builder = qt_renderer.build_batch_scene
    original_save = qt_renderer.save_png

    def build_with_warning(*args, warnings_out=None, **kwargs):
        render_threads.append(QThread.currentThread())
        warnings_out.append("gui-thread-render-warning")
        return original_builder(*args, warnings_out=warnings_out, **kwargs)

    def save_on_caller_thread(image, path):
        encode_thread_ids.append(threading.get_ident())
        return original_save(image, path)

    monkeypatch.setattr(qt_renderer, "build_batch_scene", build_with_warning)
    monkeypatch.setattr(qt_renderer, "save_png", save_on_caller_thread)

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
    qtbot.waitUntil(lambda: len(results) == 1, timeout=10_000)
    assert results[0].status == "done"
    assert render_threads == [qapp.thread()]
    assert len(encode_thread_ids) == 1
    assert encode_thread_ids[0] != threading.main_thread().ident
    item = results[0].items[0]
    assert item.warnings == ["gui-thread-render-warning"]
    assert set(item.artifact_facts) == {"data", "image"}
    assert all(
        facts["checksum_status"] == "complete" and facts["sha256"]
        for facts in item.artifact_facts.values()
    )
    manifest = load_batch_manifest(results[0].manifest_path)
    assert manifest["entries"][0]["warnings"] == [
        "gui-thread-render-warning"
    ]
    assert set(manifest["entries"][0]["artifacts"]) == {"data", "image"}
    assert any(e.kind == "run_finished" for e in events)


def test_runner_thread_propagates_gui_render_failure_and_rolls_back_set(
    qtbot, tmp_path, monkeypatch,
):
    import numpy as np
    import pandas as pd

    from mf4_analyzer.batch import AnalysisPreset, BatchRunner
    import mf4_analyzer.batch_render_qt as qt_renderer
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch.runner_thread import BatchRunnerThread

    def fail_on_gui(*_args, **_kwargs):
        raise RuntimeError("gui-render-marker")

    monkeypatch.setattr(qt_renderer, "build_batch_scene", fail_on_gui)
    t = np.arange(1024) / 512.0
    frame = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 50 * t)})
    fd = FileData(tmp_path / "failure.csv", frame, list(frame.columns), {}, idx=0)
    preset = AnalysisPreset.from_current_single(
        name="failure",
        method="fft",
        signal=(0, "sig"),
        params={"fs": 512.0, "window": "hanning", "nfft": 512},
    )
    output_dir = tmp_path / "out"
    thread = BatchRunnerThread(BatchRunner({0: fd}), preset, output_dir)
    results = []
    thread.finished_with_result.connect(results.append)

    thread.start()
    qtbot.waitUntil(lambda: len(results) == 1, timeout=10_000)

    result = results[0]
    assert result.status == "blocked"
    assert result.items[0].status == "failed"
    assert "gui-render-marker" in result.items[0].message
    assert not list(output_dir.glob("*.csv"))
    assert not list(output_dir.glob("*.png"))
    assert not list(output_dir.glob(".*.batch-stage.*"))
    assert not list(output_dir.glob(".*.batch-reserve"))


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


def test_sheet_preview_and_result_share_channel_metadata_reference(qtbot, tmp_path):
    import dataclasses

    import numpy as np
    import pandas as pd
    import pytest

    from mf4_analyzer.batch import BatchOutput, BatchRunner
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    n = 1024
    t = np.arange(n) / 512.0
    fd = FileData(
        tmp_path / "metadata.csv",
        pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 50 * t)}),
        ["Time", "sig"], {"sig": "Nm"}, idx=0,
        channel_metadata={
            "sig": {
                "quantity": "torque", "unit": "Nm", "db_reference": 4.5,
            },
        },
    )
    sheet = BatchSheet(None, files={0: fd})
    qtbot.addWidget(sheet)
    sheet.apply_files(file_ids=(0,), file_paths=())
    sheet.apply_signals(("sig",))
    sheet.apply_method("fft")
    sheet.apply_params({"window": "hanning", "nfft": 512})
    sheet.apply_outputs(BatchOutput(
        export_data=False, export_image=True, data_format="csv",
    ))

    preview = sheet._output_panel.effective_preview_text()
    assert "1×metadata" in preview
    assert "4.5" in preview

    # Keep the test focused on reference parity: the live FileData is already
    # keyed by source_id, so no physical-path resolution is needed here.
    preset = dataclasses.replace(sheet.get_preset(), source_paths=(), file_paths=())
    result = BatchRunner({0: fd}).run(preset, str(tmp_path / "out"))

    assert result.status == "done"
    assert len(result.items) == 1
    assert result.items[0].db_reference_source == "metadata"
    assert result.items[0].db_reference_value == pytest.approx(4.5)


def test_runner_thread_forwards_resume_and_retry_runtime_paths(tmp_path):
    from mf4_analyzer.batch import BatchRunResult
    from mf4_analyzer.ui.drawers.batch.runner_thread import BatchRunnerThread

    calls = []

    class Runner:
        def run(self, preset, output_dir, **kwargs):
            calls.append((preset, output_dir, kwargs))
            return BatchRunResult(status="done")

    for resume_path, retry_path in (
        (tmp_path / "resume.json", None),
        (None, tmp_path / "retry.json"),
    ):
        thread = BatchRunnerThread(
            Runner(), "preset", tmp_path / "out",
            resume_manifest=resume_path,
            retry_failed_manifest=retry_path,
        )
        results = []
        thread.finished_with_result.connect(results.append)

        thread.run()

        assert results[0].status == "done"

    assert calls[0][2]["resume_manifest"] == tmp_path / "resume.json"
    assert calls[0][2]["retry_failed_manifest"] is None
    assert calls[1][2]["resume_manifest"] is None
    assert calls[1][2]["retry_failed_manifest"] == tmp_path / "retry.json"


def test_sheet_does_not_forward_hidden_runtime_manifest_state_to_runner(
    qtbot, tmp_path, monkeypatch,
):
    import numpy as np
    import pandas as pd

    from mf4_analyzer.batch import BatchOutput, BatchRunResult, BatchRunner
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    calls = []

    def fake_run(self, preset, output_dir, **kwargs):
        calls.append(kwargs)
        return BatchRunResult(status="done")

    monkeypatch.setattr(BatchRunner, "run", fake_run)
    t = np.arange(128, dtype=float) / 128.0
    fd = FileData(
        tmp_path / "source.csv",
        pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 8 * t)}),
        ["Time", "sig"], {}, idx=0, fs=128.0,
    )
    sheet = BatchSheet(None, files={0: fd})
    qtbot.addWidget(sheet)
    sheet.apply_files((0,), ())
    sheet.apply_signals(("sig",))
    sheet.apply_method("fft")
    sheet.apply_params({"window": "hanning", "nfft": 128})
    sheet.apply_outputs(BatchOutput(export_data=True, export_image=False))
    sheet._output_panel.apply_directory(str(tmp_path / "out"))

    sheet._on_run_clicked()
    qtbot.waitUntil(lambda: sheet._running is False, timeout=3000)

    sheet._on_run_clicked()
    qtbot.waitUntil(lambda: len(calls) == 2 and not sheet._running, timeout=3000)

    assert calls[0]["resume_manifest"] is None
    assert calls[0]["retry_failed_manifest"] is None
    assert calls[1]["resume_manifest"] is None
