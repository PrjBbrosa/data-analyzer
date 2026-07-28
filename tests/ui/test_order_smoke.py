"""Order-mode and batch-entry smoke tests.

The tests cover these user-visible behaviours:

1. ``OrderContextual`` no longer exposes the old cancel placeholder
   because order analysis is still synchronous and cannot be cancelled.
2. ``MainWindow.open_batch`` rebuilds from live Inspector state instead of
   allowing ``_last_batch_preset`` to override it.
3. ``BatchSheet`` remains the only live Run owner after its modal loop ends.

The tests run under the ``offscreen`` Qt platform, set up by the
shared ``tests/ui/conftest.py``.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest


def test_order_contextual_does_not_expose_cancel_placeholder(qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual

    w = OrderContextual()
    qtbot.addWidget(w)
    assert not hasattr(w, 'cancel_requested')
    assert not hasattr(w, 'btn_cancel')


def test_open_batch_ignores_stale_last_preset_in_favor_of_live_state(
    qtbot, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.batch import AnalysisPreset

    win = MainWindow()
    qtbot.addWidget(win)
    # MainWindow needs at least 1 entry in `self.files` to clear the
    # "请先加载文件" guard. We don't need a real fd — open_batch never
    # dereferences the value before we hit the stale-preset block.
    win.files[0] = object()

    win._last_batch_preset = AnalysisPreset.from_current_single(
        name="stale", method="fft", signal=(99999, "nope"),
        params={"fs": 1024.0, "nfft": 1024},
    )
    live = AnalysisPreset.from_current_single(
        name="live", method="fft", signal=(0, "sig"),
        params={"fs": 2048.0, "nfft": None, "nfft_mode": "auto"},
    )
    monkeypatch.setattr(win, "_build_current_batch_preset", lambda: live)

    captured = {}

    class FakeSheet:
        def __init__(self, parent, files, current_preset=None):
            captured['current_preset'] = current_preset
            captured['files'] = files

        def exec_(self):
            return 0  # treat as user-cancelled so BatchRunner.run is skipped

    toast_msgs = []
    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.batch.BatchSheet', FakeSheet,
    )
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, kind='info': toast_msgs.append((kind, msg)),
    )

    win.open_batch()

    assert captured.get('current_preset') is live
    assert not toast_msgs


def test_open_batch_has_no_duplicate_run_after_sheet_exec(qtbot, monkeypatch):
    from PyQt5.QtWidgets import QDialog
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    class FakeSheet:
        def __init__(self, parent, files, current_preset=None):
            pass

        def exec_(self):
            return QDialog.Accepted

        def get_preset(self):
            raise AssertionError("BatchSheet owns the only live run path")

    monkeypatch.setattr('mf4_analyzer.ui.drawers.batch.BatchSheet', FakeSheet)

    win.open_batch()


def test_open_batch_allows_empty_file_map(qtbot, monkeypatch):
    """Batch can start from disk paths, so the sheet must open with no files."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    captured = {}

    class FakeSheet:
        def __init__(self, parent, files, current_preset=None):
            captured["files"] = files
            captured["current_preset"] = current_preset

        def exec_(self):
            return 0

    toast_msgs = []
    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.batch.BatchSheet', FakeSheet,
    )
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, kind='info': toast_msgs.append((kind, msg)),
    )

    win.open_batch()

    assert captured["files"] == {}
    assert captured["current_preset"] is None
    assert not any("请先加载文件" in msg for _kind, msg in toast_msgs)
