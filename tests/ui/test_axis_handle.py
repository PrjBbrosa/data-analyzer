"""Tests for the pyqtgraph-only chart axis handle layer."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest


def _pg_time_handle(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    t = np.linspace(1.0, 3.0, 50)
    canvas.plot_channels([
        ("speed", True, t, 1.0 + np.sin(t), "#1769e0", "rpm")
    ], mode="subplot")
    handle = canvas.axes_list[0]
    handle.set_xlim(1.0, 3.0)
    handle.set_ylim(0.0, 3.0)
    handle.set_xlabel("time (s)")
    handle.set_ylabel("value")
    handle.set_title("title")
    QCoreApplication.processEvents()
    return handle, canvas


def _pg_heatmap_handle(qapp):
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
        PgHeatmapCanvas,
        _HeatmapAxisHandle,
    )

    canvas = PgHeatmapCanvas(with_slice=False)
    matrix = np.arange(9, dtype=float).reshape(3, 3)
    canvas.plot_or_update_heatmap(
        matrix,
        (0.0, 2.0),
        (10.0, 30.0),
        x_label="time_s",
        y_label="frequency_hz",
        cmap="viridis",
        amplitude_mode="amplitude",
        z_auto=False,
        z_floor=0.0,
        z_ceiling=8.0,
    )
    return _HeatmapAxisHandle(canvas), canvas


def test_pg_axis_handle_get_xlim_and_set_xlim(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    assert handle.get_xlim() == pytest.approx((1.0, 3.0))
    handle.set_xlim(1.25, 2.5)
    assert handle.get_xlim() == pytest.approx((1.25, 2.5))


def test_pg_axis_handle_get_ylim_and_set_ylim(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    assert handle.get_ylim() == pytest.approx((0.0, 3.0))
    handle.set_ylim(-1.0, 4.0)
    assert handle.get_ylim() == pytest.approx((-1.0, 4.0))


def test_pg_axis_handle_label_and_title_roundtrip(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    assert "time (s)" in handle.get_xlabel()
    assert "value" in handle.get_ylabel()
    assert "title" in handle.get_title()

    handle.set_xlabel("时间")
    handle.set_ylabel("幅值")
    handle.set_title("新标题")

    assert "时间" in handle.get_xlabel()
    assert "幅值" in handle.get_ylabel()
    assert "新标题" in handle.get_title()


def test_pg_axis_handle_scale_roundtrip(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    handle.set_xscale("log")
    handle.set_yscale("log")
    assert handle.get_xscale() == "log"
    assert handle.get_yscale() == "log"

    handle.set_xscale("linear")
    handle.set_yscale("linear")
    assert handle.get_xscale() == "linear"
    assert handle.get_yscale() == "linear"


def test_pg_axis_handle_autoscale_marks_requested_axis(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    handle.set_xlim(100.0, 101.0)
    handle.autoscale(axis="x")

    assert handle.is_autorange("x") is True


def test_pg_axis_handle_grid_toggle(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    handle.grid(True)
    assert handle.is_grid_enabled() is True
    assert bool(handle.plot_item.getAxis("bottom").grid)

    handle.grid(False)
    assert handle.is_grid_enabled() is False
    assert not handle.plot_item.getAxis("bottom").grid


def test_pg_axis_handle_grid_can_disallow_y_grid(qapp):
    from mf4_analyzer.ui._axis_handle import PgAxisHandle
    import pyqtgraph as pg

    plot_item = pg.PlotItem()
    handle = PgAxisHandle(plot_item=plot_item, allow_y_grid=False)

    handle.grid(True)

    assert bool(plot_item.getAxis("bottom").grid)
    assert not plot_item.getAxis("left").grid


def test_pg_axis_handle_get_lines_returns_line_handles(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    lines = handle.get_lines()
    assert len(lines) == 1
    line = lines[0]
    assert callable(getattr(line, "get_label", None))
    assert callable(getattr(line, "get_color", None))
    assert callable(getattr(line, "set_color", None))
    assert callable(getattr(line, "get_visible", None))
    assert line.get_label() == "speed"
    assert line.get_color().lower() == "#1769e0"
    assert line.get_visible() is True


def test_pg_axis_handle_line_handle_set_color_round_trips(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    line = handle.get_lines()[0]
    line.set_color("#ef4444")

    assert line.get_color().lower() == "#ef4444"


def test_pg_axis_handle_rebuild_legend_idempotent(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    handle.rebuild_legend()
    legend = handle.plot_item.legend
    assert legend is not None
    assert len(legend.items) == 1

    handle.rebuild_legend()
    assert handle.plot_item.legend is legend
    assert len(legend.items) == 1


def test_pg_axis_handle_sync_line_axis_color(qapp):
    from mf4_analyzer.ui._axis_handle import PG_AXIS_NEUTRAL_COLOR

    handle, canvas = _pg_time_handle(qapp)
    line = handle.get_lines()[0]
    axis = handle.y_axis_item()

    handle.sync_line_axis_color(line, "#123456")

    assert axis.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
    assert axis.textPen().color().name().lower() == "#123456"
    assert canvas.channel_data["speed"][2].lower() == "#123456"


def test_pg_axis_handle_get_mappables_empty_for_line_canvas(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    assert handle.get_mappables() == []


def test_pg_heatmap_handle_get_mappables_and_clim_roundtrip(qapp):
    handle, canvas = _pg_heatmap_handle(qapp)

    mappables = handle.get_mappables()
    assert len(mappables) == 1
    mappable = mappables[0]
    assert mappable.get_cmap().name == "viridis"
    assert mappable.get_clim() == pytest.approx((0.0, 8.0))

    mappable.set_clim(1.0, 5.0)

    assert mappable.get_clim() == pytest.approx((1.0, 5.0))
    assert canvas._img.getLevels() == pytest.approx((1.0, 5.0))
    assert canvas._cbar.levels() == pytest.approx((1.0, 5.0))


def test_pg_heatmap_handle_axis_labels_and_limits(qapp):
    handle, _canvas = _pg_heatmap_handle(qapp)

    assert handle.get_xlim() == pytest.approx((0.0, 2.0))
    assert handle.get_ylim() == pytest.approx((10.0, 30.0))
    assert "time_s" in handle.get_xlabel()
    assert "frequency_hz" in handle.get_ylabel()


def test_make_handle_accepts_existing_pg_handle(qapp):
    from mf4_analyzer.ui._axis_handle import make_handle

    handle, _canvas = _pg_time_handle(qapp)

    assert make_handle(handle) is handle


def test_make_handle_rejects_raw_pyqtgraph_plot_item(qapp):
    from mf4_analyzer.ui._axis_handle import make_handle
    import pyqtgraph as pg

    with pytest.raises(TypeError, match="unsupported axis object: PlotItem"):
        make_handle(pg.PlotItem())


def test_pg_axis_handle_axis_item_accessors_prefer_owned_axis(qapp):
    from mf4_analyzer.ui._axis_handle import PgAxisHandle
    import pyqtgraph as pg

    plot_item = pg.PlotItem()
    right_axis = pg.AxisItem("right")

    primary = PgAxisHandle(plot_item=plot_item)
    aux = PgAxisHandle(plot_item=plot_item, axis_item=right_axis)

    assert primary.x_axis_item() is plot_item.getAxis("bottom")
    assert primary.y_axis_item() is plot_item.getAxis("left")
    assert aux.y_axis_item() is right_axis


def test_pg_axis_handle_request_redraw_does_not_raise(qapp):
    handle, _canvas = _pg_time_handle(qapp)

    handle.request_redraw()
