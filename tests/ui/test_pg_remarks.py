from __future__ import annotations

from PyQt5.QtCore import Qt
import pyqtgraph as pg

from mf4_analyzer.ui.pg_canvas.remarks import (
    RemarkArtist,
    RemarkPoint,
    format_remark_label,
)


def test_format_remark_label_uses_xyz_with_units_and_y_color(qapp):
    point = RemarkPoint(
        vb=None,
        x=1.25,
        y=42.5,
        z=-18.75,
        color="#00b894",
        unit_x="s",
        unit_y="Hz",
        unit_z="dB",
    )

    html = format_remark_label(point).lower()

    assert "x=1.25 s" in html
    assert "y=42.5 hz" in html
    assert "z=-18.75 db" in html
    assert "#00b894" in html


def test_remark_artist_creates_dot_leader_movable_text(qapp):
    widget = pg.GraphicsLayoutWidget()
    plot = widget.addPlot()
    point = RemarkPoint(
        vb=plot.vb,
        x=1.0,
        y=2.0,
        color="#dc2626",
        unit_x="s",
        unit_y="",
    )

    remark = RemarkArtist().add(point)

    assert remark["dot"].opts["brush"].color().name() == "#dc2626"
    assert remark["leader"].opts["pen"].style() == Qt.DashLine
    assert remark["text"].flags() & remark["text"].ItemIsMovable
    assert remark["label"] is remark["text"]
    assert remark["data_x"] == 1.0
    assert remark["data_y"] == 2.0
    widget.deleteLater()
