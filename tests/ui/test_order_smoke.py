"""Order-mode smoke tests for Plan T6.

Two tests cover the user-visible behaviours added in Task 6:

1. ``OrderContextual.cancel_requested`` exists as a Qt signal so the
   Inspector can publish a cancel intent without MainWindow having to
   peek into widget internals.
2. ``MainWindow.open_batch`` actively downgrades a stale
   ``_last_batch_preset`` (whose ``signal[0]`` references a fid no
   longer in ``self.files``) to ``None`` BEFORE forwarding to
   ``BatchSheet``, AND emits a toast informing the user.

The tests run under the ``offscreen`` Qt platform, set up by the
shared ``tests/ui/conftest.py``.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest


def test_order_contextual_exposes_cancel_signal(qtbot):
    from mf4_analyzer.ui.inspector_sections import OrderContextual

    w = OrderContextual()
    qtbot.addWidget(w)
    assert hasattr(w, 'cancel_requested')


def test_open_batch_drops_stale_preset_signal(qtbot, monkeypatch):
    """When ``_last_batch_preset.signal`` references a fid no longer in
    ``self.files``, ``open_batch`` must replace ``current_preset`` with
    ``None`` (so the Sheet starts fresh) AND toast the user.

    Codex round-1 feedback D13/F19: the previous implementation forwarded
    a stale preset to ``BatchSheet`` and silently let ``_expand_tasks``
    return zero — the user got no signal that the preset was invalid.
    """
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

    captured = {}

    class FakeSheet:
        def __init__(self, parent, files, current_preset=None):
            captured['current_preset'] = current_preset
            captured['files'] = files

        def exec_(self):
            return 0  # treat as user-cancelled so BatchRunner.run is skipped

    toast_msgs = []
    monkeypatch.setattr(
        'mf4_analyzer.ui.drawers.batch_sheet.BatchSheet', FakeSheet,
    )
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, kind='info': toast_msgs.append((kind, msg)),
    )

    win.open_batch()

    assert captured.get('current_preset') is None, (
        f"stale preset must not be forwarded to BatchSheet; "
        f"got {captured.get('current_preset')}"
    )
    assert any(
        '失效' in msg or 'stale' in msg.lower()
        for kind, msg in toast_msgs
    ), f"expected stale-preset toast, got {toast_msgs}"
