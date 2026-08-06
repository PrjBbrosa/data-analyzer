from __future__ import annotations

import numpy as np
import pytest
from PyQt5.QtCore import QPoint, QPointF, Qt
import pyqtgraph as pg

from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
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


# ---------------------------------------------------------------------------
# Viewport hit-testing, asserted identically on both analysis canvases.
#
# ``_viewport_pos_to_scene`` and ``_remark_item_at_viewport_pos`` were carried
# byte-for-byte by PgLineCanvas and PgHeatmapCanvas (5 and 45 lines). These
# tests pin the behaviour of BOTH before it is extracted, so a hit-priority or
# fallback-radius regression cannot slip through on one canvas only.
# ---------------------------------------------------------------------------


def _line_canvas(qapp):
    c = PgLineCanvas()
    c.resize(640, 480)
    c.plot_spectra(
        [{
            'label': 'f1 · steering torque',
            'color': '#2563eb',
            'freq': np.array([0.0, 1.0, 2.0]),
            'amp': np.array([0.0, 100.0, 0.0]),
            'time': np.linspace(0.0, 1.0, 32),
            'signal': np.zeros(32),
        }],
        xlim=(0.0, 2.0), amp_label='Amplitude', title='FFT',
        y_auto=False, y_min=0.0, y_max=100.0,
    )
    c.show()
    qapp.processEvents()
    c.set_remark_enabled(True)
    return c, c._plot_amp.vb


def _heatmap_canvas(qapp):
    c = PgHeatmapCanvas()
    c.resize(640, 480)
    c.plot_or_update_heatmap(
        matrix=np.arange(16, dtype=float).reshape(4, 4),
        x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    c.show()
    qapp.processEvents()
    c.set_remark_enabled(True)
    return c, c._plot.vb


@pytest.fixture(params=[
    pytest.param(_line_canvas, id='line'),
    pytest.param(_heatmap_canvas, id='heatmap'),
])
def hit_canvas(request, qapp):
    canvas, vb = request.param(qapp)
    yield canvas, vb
    canvas.deleteLater()


def _viewport_pos_of(canvas, vb, x, y):
    """Viewport-space QPoint for a data-space point on ``vb``."""
    return canvas._glw.mapFromScene(vb.mapViewToScene(QPointF(x, y)))


def _place_remark(canvas, vb, x, y, color='#dc2626'):
    """Attach a remark directly, bypassing each canvas's differing add path."""
    remark = RemarkArtist().add(
        RemarkPoint(vb=vb, x=float(x), y=float(y), color=color, unit_x='s')
    )
    canvas._remarks.append(remark)
    return remark


def test_viewport_pos_to_scene_matches_the_view_mapping(hit_canvas):
    canvas, _vb = hit_canvas

    pos = QPoint(120, 90)

    assert canvas._viewport_pos_to_scene(pos) == canvas._glw.mapToScene(pos)


def test_viewport_pos_to_scene_swallows_a_bad_position(hit_canvas):
    canvas, _vb = hit_canvas

    assert canvas._viewport_pos_to_scene(object()) is None


def test_no_remarks_means_no_hit(hit_canvas):
    canvas, vb = hit_canvas
    canvas.clear_remarks()

    pos = _viewport_pos_of(canvas, vb, 1.0, 4.0)

    assert canvas._remark_item_at_viewport_pos(pos) is None


def test_click_on_the_remark_dot_hits_it(hit_canvas):
    canvas, vb = hit_canvas
    canvas.clear_remarks()
    remark = _place_remark(canvas, vb, 1.0, 4.0)

    pos = _viewport_pos_of(canvas, vb, 1.0, 4.0)

    assert canvas._remark_item_at_viewport_pos(pos) is remark


def test_click_on_the_label_hits_it(hit_canvas):
    canvas, vb = hit_canvas
    canvas.clear_remarks()
    remark = _place_remark(canvas, vb, 1.0, 4.0)
    label_pos = remark['text'].pos()

    pos = _viewport_pos_of(canvas, vb, label_pos.x(), label_pos.y())

    assert canvas._remark_item_at_viewport_pos(pos) is remark


def test_click_far_away_misses(hit_canvas):
    canvas, vb = hit_canvas
    canvas.clear_remarks()
    _place_remark(canvas, vb, 1.0, 4.0)

    # Well outside the 12px label fallback radius and off every item.
    assert canvas._remark_item_at_viewport_pos(QPoint(2, 2)) is None


@pytest.mark.parametrize(
    'offset,expected_hit',
    [((0, 0), True), ((8, 8), True), ((30, 30), False)],
)
def test_label_anchor_fallback_radius(hit_canvas, monkeypatch, offset,
                                      expected_hit):
    """Stage two of the hit test, isolated.

    Stage one (scene item under the cursor) is disabled so the 12px
    label-anchor radius is what decides; sqrt(8^2+8^2)=11.3 is inside it and
    sqrt(30^2+30^2)=42.4 is not.
    """
    canvas, vb = hit_canvas
    canvas.clear_remarks()
    remark = _place_remark(canvas, vb, 1.0, 4.0)
    label_pos = remark['text'].pos()
    anchor = canvas._glw.mapFromScene(
        vb.mapViewToScene(QPointF(label_pos.x(), label_pos.y())))
    monkeypatch.setattr(
        canvas._glw.scene(), 'items', lambda *_a, **_k: [])

    hit = canvas._remark_item_at_viewport_pos(
        QPoint(anchor.x() + offset[0], anchor.y() + offset[1]))

    assert (hit is remark) is expected_hit


def test_overlapping_remarks_resolve_to_the_topmost_scene_item(hit_canvas):
    """Two remarks stacked at one point: the scene's own stacking order
    decides, because stage one iterates scene items in the outer loop."""
    canvas, vb = hit_canvas
    canvas.clear_remarks()
    lower = _place_remark(canvas, vb, 1.0, 4.0, color='#2563eb')
    upper = _place_remark(canvas, vb, 1.0, 4.0, color='#16a34a')
    pos = _viewport_pos_of(canvas, vb, 1.0, 4.0)

    hit = canvas._remark_item_at_viewport_pos(pos)

    assert hit in (lower, upper)
    owners = {
        id(it): r
        for r in (lower, upper)
        for it in (r['dot'], r['leader'], r['text'],
                   getattr(r['text'], 'textItem', None))
        if it is not None
    }
    items = canvas._glw.scene().items(canvas._glw.mapToScene(pos))
    first_owned = next(
        (owners[id(it)] for it in items if id(it) in owners), None)
    assert hit is first_owned


def test_hit_survives_a_remark_with_no_viewbox(hit_canvas):
    """The fallback loop skips malformed entries instead of raising."""
    canvas, vb = hit_canvas
    canvas.clear_remarks()
    remark = _place_remark(canvas, vb, 1.0, 4.0)
    canvas._remarks.insert(0, {'vb': None, 'text': None})

    pos = _viewport_pos_of(canvas, vb, 1.0, 4.0)

    assert canvas._remark_item_at_viewport_pos(pos) is remark
    canvas._remarks.clear()


def test_unmappable_position_misses_without_raising(hit_canvas):
    canvas, vb = hit_canvas
    canvas.clear_remarks()
    _place_remark(canvas, vb, 1.0, 4.0)

    assert canvas._remark_item_at_viewport_pos(object()) is None
