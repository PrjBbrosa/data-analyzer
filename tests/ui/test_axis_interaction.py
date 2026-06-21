"""Tests for pyqtgraph-only chart-options dialog dispatch."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PyQt5.QtWidgets import QDialog


def _pg_time_handle(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    t = np.linspace(0.0, 1.0, 40)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t), "#1769e0", "rpm")
    ], mode="subplot")
    return canvas.axes_list[0], canvas


def test_edit_chart_options_dialog_returns_true_when_accepted(qapp, monkeypatch):
    from mf4_analyzer.ui import dialogs as dialogs_mod
    from mf4_analyzer.ui._axis_interaction import edit_chart_options_dialog

    handle, canvas = _pg_time_handle(qapp)
    captured = {}

    class FakeDialog:
        def __init__(self, parent, axis_handle):
            captured["parent"] = parent
            captured["handle"] = axis_handle

        def exec_(self):
            return QDialog.Accepted

        def was_applied(self):
            return False

    monkeypatch.setattr(dialogs_mod, "ChartOptionsDialog", FakeDialog)

    assert edit_chart_options_dialog(canvas, handle) is True
    assert captured == {"parent": canvas, "handle": handle}


def test_edit_chart_options_dialog_returns_true_when_applied_then_closed(
    qapp, monkeypatch,
):
    from mf4_analyzer.ui import dialogs as dialogs_mod
    from mf4_analyzer.ui._axis_interaction import edit_chart_options_dialog

    handle, canvas = _pg_time_handle(qapp)

    class FakeDialog:
        def __init__(self, parent, axis_handle):
            assert parent is canvas
            assert axis_handle is handle

        def exec_(self):
            return QDialog.Rejected

        def was_applied(self):
            return True

    monkeypatch.setattr(dialogs_mod, "ChartOptionsDialog", FakeDialog)

    assert edit_chart_options_dialog(canvas, handle) is True


def test_edit_chart_options_dialog_returns_false_when_rejected_without_apply(
    qapp, monkeypatch,
):
    from mf4_analyzer.ui import dialogs as dialogs_mod
    from mf4_analyzer.ui._axis_interaction import edit_chart_options_dialog

    handle, canvas = _pg_time_handle(qapp)

    class FakeDialog:
        def __init__(self, parent, axis_handle):
            assert parent is canvas
            assert axis_handle is handle

        def exec_(self):
            return QDialog.Rejected

        def was_applied(self):
            return False

    monkeypatch.setattr(dialogs_mod, "ChartOptionsDialog", FakeDialog)

    assert edit_chart_options_dialog(canvas, handle) is False


def test_edit_chart_options_dialog_rejects_raw_pyqtgraph_plot_item(qapp):
    from mf4_analyzer.ui._axis_interaction import edit_chart_options_dialog
    import pyqtgraph as pg

    with pytest.raises(TypeError, match="unsupported axis object: PlotItem"):
        edit_chart_options_dialog(None, pg.PlotItem())
