"""Empty-hint overlay behaviour, asserted identically on both analysis canvases.

``PgLineCanvas`` and ``PgHeatmapCanvas`` each carried a byte-identical copy of
``show_empty_hint`` / ``_reposition_empty_hint`` / ``clear_empty_hint`` apart
from which PlotItem they hang the label on. These tests pin the behaviour that
the shared implementation has to keep for BOTH, so the extraction cannot
silently regress one of them.

The two canvases anchor the hint on different plots on purpose -- line has a
two-row spectrum/time stack and puts the hint on the amplitude row -- so the
"which viewbox" question is asserted per canvas rather than parametrized away.
"""
from __future__ import annotations

import pytest

from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


def _make_line():
    return PgLineCanvas()


def _make_heatmap():
    return PgHeatmapCanvas()


CANVAS_FACTORIES = [
    pytest.param(_make_line, id="line"),
    pytest.param(_make_heatmap, id="heatmap"),
]


def _hint_viewbox(canvas):
    """The ViewBox the canvas anchors its empty hint on."""
    plot = getattr(canvas, "_plot_amp", None) or canvas._plot
    return plot.vb


@pytest.fixture(params=CANVAS_FACTORIES)
def hint_canvas(request, qapp):
    c = request.param()
    c.resize(640, 480)
    yield c
    c.deleteLater()


def test_show_adds_a_visible_item_carrying_the_text(hint_canvas):
    hint_canvas.show_empty_hint("点击『计算』生成")

    item = hint_canvas._empty_hint_item
    assert item is not None
    assert item.scene() is not None
    assert item.isVisible()
    assert hint_canvas._empty_hint_text == "点击『计算』生成"
    assert "点击『计算』生成" in item.toPlainText()


def test_hint_is_anchored_on_the_canvas_own_viewbox(hint_canvas):
    hint_canvas.show_empty_hint("待计算")

    vb = _hint_viewbox(hint_canvas)
    assert hint_canvas._empty_hint_item.parentItem() is vb.childGroup


def test_hint_is_ignored_by_auto_range(hint_canvas):
    """ignoreBounds=True: the label must not drag the view range around.

    pyqtgraph records that by keeping the item OUT of ``addedItems``, which is
    the list ``childrenBounds`` walks.
    """
    hint_canvas.show_empty_hint("待计算")

    vb = _hint_viewbox(hint_canvas)
    assert hint_canvas._empty_hint_item not in vb.addedItems


def test_clear_removes_item_and_text(hint_canvas):
    hint_canvas.show_empty_hint("待计算")

    hint_canvas.clear_empty_hint()

    assert hint_canvas._empty_hint_item is None
    assert hint_canvas._empty_hint_text == ""


def test_clear_is_idempotent_without_a_prior_show(hint_canvas):
    hint_canvas.clear_empty_hint()
    hint_canvas.clear_empty_hint()

    assert hint_canvas._empty_hint_item is None
    assert hint_canvas._empty_hint_text == ""


def test_empty_text_clears_instead_of_showing_a_blank_box(hint_canvas):
    hint_canvas.show_empty_hint("待计算")

    hint_canvas.show_empty_hint("")

    assert hint_canvas._empty_hint_item is None
    assert hint_canvas._empty_hint_text == ""


def test_none_text_clears_too(hint_canvas):
    hint_canvas.show_empty_hint("待计算")

    hint_canvas.show_empty_hint(None)

    assert hint_canvas._empty_hint_item is None
    assert hint_canvas._empty_hint_text == ""


def test_repeated_show_reuses_one_item_and_replaces_the_text(hint_canvas):
    hint_canvas.show_empty_hint("第一条")
    first = hint_canvas._empty_hint_item

    hint_canvas.show_empty_hint("第二条")

    assert hint_canvas._empty_hint_item is first
    assert hint_canvas._empty_hint_text == "第二条"
    assert "第二条" in first.toPlainText()
    assert "第一条" not in first.toPlainText()
    vb = _hint_viewbox(hint_canvas)
    siblings = [c for c in vb.childGroup.childItems() if c is first]
    assert siblings == [first]


def test_repeated_show_does_not_stack_reposition_connections(hint_canvas):
    """Each show disconnects before reconnecting, so the slot never doubles up.

    Without the disconnect this grows by one receiver per show, and every
    range change then runs the reposition N times.
    """
    vb = _hint_viewbox(hint_canvas)

    hint_canvas.show_empty_hint("第一条")
    after_first = (vb.receivers(vb.sigResized),
                   vb.receivers(vb.sigRangeChanged))

    hint_canvas.show_empty_hint("第二条")
    hint_canvas.show_empty_hint("第三条")
    hint_canvas.show_empty_hint("第四条")

    assert (vb.receivers(vb.sigResized),
            vb.receivers(vb.sigRangeChanged)) == after_first


def test_clear_releases_the_reposition_connections(hint_canvas):
    vb = _hint_viewbox(hint_canvas)
    before = (vb.receivers(vb.sigResized), vb.receivers(vb.sigRangeChanged))

    hint_canvas.show_empty_hint("待计算")
    hint_canvas.clear_empty_hint()

    assert (vb.receivers(vb.sigResized),
            vb.receivers(vb.sigRangeChanged)) == before


def test_reposition_follows_the_viewbox_centre_after_resize(hint_canvas):
    hint_canvas.show_empty_hint("待计算")
    item = hint_canvas._empty_hint_item
    vb = _hint_viewbox(hint_canvas)

    vb.setRange(xRange=(0.0, 10.0), yRange=(0.0, 10.0), padding=0)
    hint_canvas._reposition_empty_hint()
    before = (item.pos().x(), item.pos().y())

    vb.setRange(xRange=(100.0, 200.0), yRange=(-50.0, 50.0), padding=0)
    hint_canvas._reposition_empty_hint()
    after = (item.pos().x(), item.pos().y())

    assert before != after
    # Centre of the new range, mapped back through the same viewbox.
    expected = vb.mapSceneToView(vb.sceneBoundingRect().center())
    assert after == pytest.approx((expected.x(), expected.y()), rel=1e-6)


def test_reposition_is_a_noop_once_cleared(hint_canvas):
    hint_canvas.show_empty_hint("待计算")
    hint_canvas.clear_empty_hint()

    hint_canvas._reposition_empty_hint()  # must not raise

    assert hint_canvas._empty_hint_item is None


def test_range_change_signal_repositions_a_live_hint(hint_canvas):
    hint_canvas.show_empty_hint("待计算")
    item = hint_canvas._empty_hint_item
    vb = _hint_viewbox(hint_canvas)
    vb.setRange(xRange=(0.0, 1.0), yRange=(0.0, 1.0), padding=0)
    before = (item.pos().x(), item.pos().y())

    vb.setRange(xRange=(500.0, 900.0), yRange=(20.0, 60.0), padding=0)

    after = (item.pos().x(), item.pos().y())
    assert before != after


def test_range_change_after_clear_does_not_move_a_stale_item(hint_canvas):
    """The disconnect in clear must actually land, or a removed item keeps
    receiving sigRangeChanged and pyqtgraph raises on the deleted C++ side."""
    hint_canvas.show_empty_hint("待计算")
    item = hint_canvas._empty_hint_item
    hint_canvas.clear_empty_hint()
    frozen = (item.pos().x(), item.pos().y())

    vb = _hint_viewbox(hint_canvas)
    vb.setRange(xRange=(1000.0, 2000.0), yRange=(1.0, 2.0), padding=0)

    assert (item.pos().x(), item.pos().y()) == frozen


def test_show_after_clear_rebuilds_a_fresh_item(hint_canvas):
    hint_canvas.show_empty_hint("第一条")
    first = hint_canvas._empty_hint_item
    hint_canvas.clear_empty_hint()

    hint_canvas.show_empty_hint("第二条")

    assert hint_canvas._empty_hint_item is not None
    assert hint_canvas._empty_hint_item is not first
    assert hint_canvas._empty_hint_item.scene() is not None
    assert "第二条" in hint_canvas._empty_hint_item.toPlainText()


def test_non_string_text_is_coerced(hint_canvas):
    hint_canvas.show_empty_hint(42)

    assert hint_canvas._empty_hint_text == "42"
    assert "42" in hint_canvas._empty_hint_item.toPlainText()
