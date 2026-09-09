"""ColorBarItem numeric-axis width: release the 45 px pin and fit tick text.

Vertical ColorBarItem (pyqtgraph 0.14) puts values on the right axis and the
title on the left, then ``setWidth(45)`` on the value axis. Wide or long
decimal strings are not clipped — ``generateDrawSpecs`` drops them
(``if br & rect != rect: continue``). The owning canvas must size that axis
from the strings it is carrying after fonts and levels land, including the
narrow→wide→narrow update path and clear/rebuild.
"""
from __future__ import annotations

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication, Qt
from PyQt5.QtGui import QImage, QPainter

from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas, _HeatmapMappable
from mf4_analyzer.ui_kit.axis_metrics import left_axis_width_for_ticks


_EPS = 0.5


def _drawn_tick_texts(axis):
    image = QImage(8, 8, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    try:
        generated = axis.generateDrawSpecs(painter)
    finally:
        painter.end()
    if not generated:
        return []
    return [str(value) for _rect, _flags, value in generated[2]]


def _major_tick_texts(axis):
    levels = getattr(axis, "_tickLevels", None)
    if levels:
        return [str(text) for _value, text in levels[0] if str(text)]
    try:
        span = float(axis.boundingRect().height())
        if span <= 0.0:
            return []
        low, high = float(axis.range[0]), float(axis.range[1])
        scale = float(axis.autoSIPrefixScale) * float(axis.scale)
        groups = list(axis.tickValues(low, high, span))
        if not groups:
            return []
        spacing, values = groups[0]
        return [
            str(text)
            for text in axis.tickStrings(list(values), scale, spacing)
            if str(text)
        ]
    except Exception:
        return []


def _interior_tick_texts(axis):
    texts = _major_tick_texts(axis)
    return texts[1:-1] if len(texts) > 2 else texts


def _settle(canvas):
    QCoreApplication.processEvents()
    canvas.grab()
    QCoreApplication.processEvents()


def _plot(canvas, vmin, vmax, *, matrix=None):
    data = np.linspace(float(vmin), float(vmax), 20).reshape(4, 5) if matrix is None else matrix
    canvas.plot_or_update_heatmap(
        matrix=data,
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode="amplitude",
        z_auto=False,
        vmin=float(vmin),
        vmax=float(vmax),
        cbar_label="Amplitude",
    )
    _settle(canvas)


def _assert_colorbar_numbers_visible(canvas, *, tag):
    axis = canvas._cbar.axis
    needed = left_axis_width_for_ticks(axis)
    realized = float(axis.width())
    selected = _major_tick_texts(axis)
    drawn = _drawn_tick_texts(axis)
    interior = _interior_tick_texts(axis)
    assert needed <= realized + _EPS, (
        f"{tag}: ticks {selected!r} need {needed:.1f}px, axis is {realized:.1f}px "
        f"(fixedWidth={axis.fixedWidth!r})"
    )
    assert drawn, f"{tag}: colorbar drew no numbers; selected={selected!r}"
    if interior:
        missing = [text for text in interior if text not in drawn]
        assert not missing, (
            f"{tag}: dropped {missing!r}; drawn={drawn!r} selected={selected!r}"
        )
    lo, hi = canvas._cbar.levels()
    img_lo, img_hi = canvas._img.getLevels()
    return realized, (float(lo), float(hi), float(img_lo), float(img_hi))


@pytest.fixture
def canvas(qapp):
    widget = PgHeatmapCanvas()
    widget.resize(800, 560)
    widget.show()
    QCoreApplication.processEvents()
    yield widget
    widget.hide()
    widget.deleteLater()


def test_colorbar_first_plot_of_narrow_decimals_is_readable(canvas):
    _plot(canvas, -123.4568, -123.4561)
    width, levels = _assert_colorbar_numbers_visible(canvas, tag="narrow-decimals")
    assert width > 45.0
    assert levels == pytest.approx((-123.4568, -123.4561, -123.4568, -123.4561))


def test_colorbar_narrow_wide_narrow_update_keeps_levels_and_can_shrink(canvas):
    _plot(canvas, 0.0, 1.0)
    narrow_width, _ = _assert_colorbar_numbers_visible(canvas, tag="narrow")
    first_bar = canvas._cbar

    _plot(canvas, -123.4568, -123.4561)
    wide_width, wide_levels = _assert_colorbar_numbers_visible(canvas, tag="wide")
    assert canvas._cbar is first_bar
    assert wide_width > narrow_width
    assert wide_levels == pytest.approx((-123.4568, -123.4561, -123.4568, -123.4561))

    _plot(canvas, 0.0, 1.0)
    shrunk_width, shrunk_levels = _assert_colorbar_numbers_visible(canvas, tag="shrunk")
    assert canvas._cbar is first_bar
    assert shrunk_width < wide_width
    assert shrunk_levels == pytest.approx((0.0, 1.0, 0.0, 1.0))


def test_colorbar_survives_full_reset_rebuild_and_manual_clim(canvas):
    connections_before = canvas._cbar is None
    _plot(canvas, -123.4568, -123.4561)
    _assert_colorbar_numbers_visible(canvas, tag="before-reset")
    receivers = canvas._cbar.receivers(canvas._cbar.sigLevelsChanged)

    canvas.full_reset()
    _settle(canvas)
    _plot(canvas, 0.1, 480000.0)
    _assert_colorbar_numbers_visible(canvas, tag="after-rebuild")
    assert canvas._cbar.receivers(canvas._cbar.sigLevelsChanged) == receivers
    assert connections_before is False or canvas._cbar is not None

    mappable = _HeatmapMappable(canvas)
    mappable.set_clim(-123.4568, -123.4561)
    _settle(canvas)
    _assert_colorbar_numbers_visible(canvas, tag="after-clim")
    assert canvas._cbar.levels() == pytest.approx((-123.4568, -123.4561))


def test_colorbar_programmatic_level_restore_resizes_without_extra_connections(canvas):
    _plot(canvas, 0.0, 1.0)
    _plot(canvas, -123.4568, -123.4561)
    changed_before = canvas._cbar.receivers(canvas._cbar.sigLevelsChanged)
    finished_before = canvas._cbar.receivers(canvas._cbar.sigLevelsChangeFinished)
    assert canvas.reset_colorbar_levels() is True
    _settle(canvas)
    _assert_colorbar_numbers_visible(canvas, tag="restored")
    assert canvas._cbar.receivers(canvas._cbar.sigLevelsChanged) == changed_before
    assert canvas._cbar.receivers(canvas._cbar.sigLevelsChangeFinished) == finished_before
    assert canvas._cbar.levels() == pytest.approx((-123.4568, -123.4561))
