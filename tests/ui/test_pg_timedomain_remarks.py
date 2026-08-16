"""Time-domain remark snapshot / restore (View overlay persistence Task 2)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication, QPointF


def _pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _speed_rows(t=None, sig=None, *, fid="fid-1"):
    if t is None:
        t = np.asarray([0.0, 0.5, 1.0], dtype=np.float64)
    if sig is None:
        sig = np.asarray([10.0, 20.0, 30.0], dtype=np.float64)
    return [("speed", True, t, sig, "#1769e0", "rpm", fid)]


def _viewport_point_for_data(canvas, handle, x, y=None):
    vb = handle.view_box
    assert vb is not None
    if y is None:
        _x_range, y_range = vb.viewRange()
        y = (float(y_range[0]) + float(y_range[1])) / 2.0
    scene_pos = vb.mapViewToScene(QPointF(float(x), float(y)))
    return canvas._glw.mapFromScene(scene_pos)


def _plot_speed(canvas, rows=None):
    rows = _speed_rows() if rows is None else rows
    canvas.plot_channels(rows, mode="subplot")
    QCoreApplication.processEvents()
    return rows


def _add_remark_on_speed(canvas, x=0.5, y=20.0):
    handle = canvas.axes_list[0]
    point = _viewport_point_for_data(canvas, handle, x, y)
    canvas._annotations._add_remark(point)
    assert canvas.remark_count() >= 1


def test_add_remark_snapshot_has_source_and_finite_xy(qapp):
    canvas = _pg_canvas(qapp)
    _plot_speed(canvas)
    _add_remark_on_speed(canvas)

    snap = canvas.snapshot_remarks()
    assert len(snap) == 1
    item = snap[0]
    assert item["source"] == ["fid-1", "speed"]
    assert isinstance(item["source"], list)
    assert math.isfinite(item["x"])
    assert math.isfinite(item["y"])
    assert math.isfinite(item["label_dx"])
    assert math.isfinite(item["label_dy"])


def test_clear_drops_remarks_and_snapshot_is_empty(qapp):
    canvas = _pg_canvas(qapp)
    _plot_speed(canvas)
    _add_remark_on_speed(canvas)
    assert canvas._annotations.remarks
    assert canvas.snapshot_remarks()

    canvas.clear()

    assert canvas._annotations.remarks == []
    assert canvas.snapshot_remarks() == []
    assert canvas.remark_count() == 0


def test_restore_remarks_rebinds_after_plot_channels_rebuild(qapp):
    canvas = _pg_canvas(qapp)
    _plot_speed(canvas)
    payload = [
        {
            "source": ["fid-1", "speed"],
            "x": 0.51,
            "y": 999.0,
            "label_dx": 0.08,
            "label_dy": 0.4,
        }
    ]

    canvas.plot_channels(_speed_rows(), mode="subplot")
    QCoreApplication.processEvents()
    canvas.restore_remarks(payload)

    assert canvas.remark_count() == 1
    live = canvas._annotations.remarks[0]
    assert live["source"] == ("fid-1", "speed")
    assert live["data_x"] == pytest.approx(0.5)
    assert live["data_y"] == pytest.approx(20.0)
    assert live["data_y"] != pytest.approx(999.0)
    text = live["text"]
    assert text.flags() & text.ItemIsMovable
    pos = text.pos()
    assert float(pos.x()) == pytest.approx(0.5 + 0.08)
    assert float(pos.y()) == pytest.approx(20.0 + 0.4)

    snap = canvas.snapshot_remarks()
    assert len(snap) == 1
    assert snap[0]["source"] == ["fid-1", "speed"]
    assert snap[0]["x"] == pytest.approx(0.5)
    assert snap[0]["y"] == pytest.approx(20.0)


def test_restore_remarks_skips_missing_channel_without_throwing(qapp):
    canvas = _pg_canvas(qapp)
    _plot_speed(canvas)
    payload = [
        {
            "source": ["missing-fid", "nope"],
            "x": 0.5,
            "y": 20.0,
            "label_dx": 0.1,
            "label_dy": 0.1,
        },
        {
            "source": ["fid-1", "speed"],
            "x": 0.5,
            "y": 20.0,
            "label_dx": 0.1,
            "label_dy": 0.1,
        },
    ]

    canvas.restore_remarks(payload)

    assert canvas.remark_count() == 1
    assert canvas.snapshot_remarks()[0]["source"] == ["fid-1", "speed"]


def test_restore_remarks_survives_two_full_plot_channels_rebuilds(qapp):
    canvas = _pg_canvas(qapp)
    rows = _speed_rows()
    _plot_speed(canvas, rows)
    _add_remark_on_speed(canvas)
    snap = canvas.snapshot_remarks()
    assert snap
    source = snap[0]["source"]

    canvas.plot_channels(rows, mode="subplot")
    QCoreApplication.processEvents()
    assert canvas.remark_count() == 0

    canvas.plot_channels(rows, mode="subplot")
    QCoreApplication.processEvents()
    assert canvas.remark_count() == 0

    canvas.restore_remarks(snap)
    rebound = canvas.snapshot_remarks()
    assert len(rebound) == 1
    assert rebound[0]["source"] == source
    text = canvas._annotations.remarks[0]["text"]
    assert text.flags() & text.ItemIsMovable


def test_cursor_placement_wrappers_do_not_raise_without_cursor_api(qapp):
    canvas = _pg_canvas(qapp)
    assert canvas.snapshot_cursor_placement() is None or isinstance(
        canvas.snapshot_cursor_placement(), dict
    )
    canvas.restore_cursor_placement(None)
    canvas.restore_cursor_placement({"ax": 1.0, "bx": 2.5})


def test_prefixed_plot_name_snapshots_raw_channel_and_restores(qapp):
    canvas = _pg_canvas(qapp)
    t = np.asarray([0.0, 0.5, 1.0], dtype=np.float64)
    sig = np.asarray([10.0, 20.0, 30.0], dtype=np.float64)
    rows = [("[a.csv] speed", True, t, sig, "#1769e0", "rpm", "fid-1")]
    canvas.plot_channels(rows, mode="subplot")
    QCoreApplication.processEvents()
    _add_remark_on_speed(canvas)

    snap = canvas.snapshot_remarks()
    assert snap[0]["source"] == ["fid-1", "speed"]

    canvas.plot_channels(rows, mode="subplot")
    QCoreApplication.processEvents()
    canvas.restore_remarks(snap)
    rebound = canvas.snapshot_remarks()
    assert len(rebound) == 1
    assert rebound[0]["source"] == ["fid-1", "speed"]
    assert rebound[0]["x"] == pytest.approx(0.5)
    assert rebound[0]["y"] == pytest.approx(20.0)
