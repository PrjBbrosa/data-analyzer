"""Presentation-paint acknowledgement lifecycle.

F-X-2: hideEvent during construct/teardown must not raise.
D-D: delayed autorange must not void the first handshake, and a geometry
mismatch rearms at most twice before a single warning and cancel.
"""
from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PyQt5.QtGui import QHideEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


def test_hide_event_during_construct_and_teardown_does_not_raise(qapp):
    constructing = TimeDomainCanvasPG()
    del constructing._presentation_paint_ack_epoch
    constructing.hideEvent(QHideEvent())

    tearing_down = TimeDomainCanvasPG()
    del tearing_down._presentation_paint_ack_epoch
    tearing_down.hideEvent(QHideEvent())


def _shown_line_canvas(qtbot):
    canvas = PgLineCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(640, 480)
    canvas.show()
    qtbot.waitExposed(canvas)
    QApplication.processEvents()
    return canvas


def _shift_plot_view_range(key, delta):
    """Return a geometry key whose every plot viewRange is shifted by ``delta``."""
    plots = tuple(
        (rect, (x_range[0] + delta, x_range[1] + delta), y_range)
        for rect, x_range, y_range in key[5]
    )
    return (*key[:5], plots)


def test_delayed_autorange_on_first_paint_still_acknowledges(qtbot):
    """A line plot with autorange still pending must ack, not cancel.

    Ranges are left unset so pyqtgraph applies them in ``prepareForPaint``
    on the first paint after the curve is added.
    """
    canvas = _shown_line_canvas(qtbot)
    x_values = np.linspace(0.0, 10.0, 50)
    y_values = np.sin(x_values) * 25.0 + 40.0
    canvas._plot_amp.addItem(pg.PlotDataItem(x_values, y_values))
    assert canvas._plot_amp.vb.autoRangeEnabled() == [True, True]
    assert canvas._plot_amp.vb._autoRangeNeedsUpdate is True
    range_before = tuple(
        tuple(axis) for axis in canvas._plot_amp.vb.viewRange()
    )

    received = []
    canvas.presentation_paint_acknowledged.connect(received.append)
    assert canvas.request_presentation_paint_ack("autorange") is True
    generation = canvas._presentation_paint_ack_generation
    QApplication.processEvents()
    QApplication.processEvents()

    assert tuple(tuple(axis) for axis in canvas._plot_amp.vb.viewRange()) != range_before
    assert received == ["autorange"]
    assert canvas._presentation_paint_ack_pending is False
    assert canvas._presentation_paint_ack_request_id is None
    assert canvas._presentation_paint_ack_generation == generation


def test_two_geometry_changes_still_acknowledge_and_the_third_cancels(
    qtbot, monkeypatch, caplog,
):
    """The first two paint/snapshot mismatches rearm; the third cancels once."""
    canvas = _shown_line_canvas(qtbot)
    base = canvas._presentation_paint_ack_geometry_key()
    assert base is not None
    keys = iter(
        _shift_plot_view_range(base, delta) for delta in (0.0, 1.0, 2.0, 2.0, 2.0)
    )
    monkeypatch.setattr(
        canvas, "_presentation_paint_ack_geometry_key", lambda: next(keys),
    )
    received = []
    canvas.presentation_paint_acknowledged.connect(received.append)

    assert canvas.request_presentation_paint_ack("settle") is True
    assert canvas._presentation_paint_ack_token() is None
    assert canvas._presentation_paint_ack_rearms == 1
    assert canvas._presentation_paint_ack_pending is True
    assert canvas._presentation_paint_ack_token() is None
    assert canvas._presentation_paint_ack_rearms == 2
    token = canvas._presentation_paint_ack_token()
    assert token is not None
    canvas._presentation_paint_acked(token)

    assert received == ["settle"]
    assert canvas._presentation_paint_ack_pending is False
    assert canvas._presentation_paint_ack_rearms == 0

    cancel_keys = iter(
        _shift_plot_view_range(base, delta) for delta in (0.0, 3.0, 4.0, 5.0)
    )
    monkeypatch.setattr(
        canvas, "_presentation_paint_ack_geometry_key", lambda: next(cancel_keys),
    )
    with caplog.at_level(logging.WARNING):
        assert canvas.request_presentation_paint_ack("drift") is True
        assert canvas._presentation_paint_ack_token() is None
        assert canvas._presentation_paint_ack_rearms == 1
        assert canvas._presentation_paint_ack_token() is None
        assert canvas._presentation_paint_ack_rearms == 2
        assert canvas._presentation_paint_ack_token() is None

    assert received == ["settle"]
    assert canvas._presentation_paint_ack_pending is False
    assert canvas._presentation_paint_ack_request_id is None
    assert canvas._presentation_paint_ack_rearms == 0
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]
    assert len(warnings) == 1
    assert "viewRange" in warnings[0]
    # The cancelling sample is the third change: shift 4 -> shift 5.
    assert "4.0" in warnings[0]
    assert "5.0" in warnings[0]
