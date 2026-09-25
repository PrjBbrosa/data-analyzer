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


def test_snapshot_axis_appearance_reads_handle_fields(qapp):
    from mf4_analyzer.ui._axis_handle import snapshot_axis_appearance

    handle, _canvas = _pg_time_handle(qapp)
    handle.set_ylim(0.1, 3.0)
    handle.set_title("Snap")
    handle.set_ylabel("Y")
    handle.set_yscale("log")
    handle.grid(False)
    snap = snapshot_axis_appearance(handle)
    assert "Snap" in str(snap["title"])
    assert "Y" in str(snap["y_label"])
    assert snap["y_scale"] == "log"
    assert snap["grid"] is False


def test_snapshot_axis_appearance_swallows_deleted_grid_probe(qapp):
    from mf4_analyzer.ui._axis_handle import snapshot_axis_appearance

    class _DyingHandle:
        def get_title(self):
            return "t"

        def get_xlabel(self):
            return "x"

        def get_ylabel(self):
            return "y"

        def get_xscale(self):
            return "linear"

        def get_yscale(self):
            return "linear"

        def is_grid_enabled(self):
            raise RuntimeError("wrapped C/C++ object of type PlotItem has been deleted")

    snap = snapshot_axis_appearance(_DyingHandle())
    assert snap["grid"] is False
    assert snap["title"] == "t"


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


def _shown_plot():
    """A real PlotItem whose title row and ViewBox geometry can be measured."""
    import pyqtgraph as pg
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui._axis_handle import PgAxisHandle

    widget = pg.GraphicsLayoutWidget()
    widget.resize(640, 420)
    plot = widget.addPlot()
    widget.show()
    QCoreApplication.processEvents()
    handle = PgAxisHandle(plot_item=plot)
    return widget, plot, handle


def _title_row_height(plot):
    return float(plot.layout.rowMaximumHeight(0))


def _curve_limits(values):
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(finite.min()), float(finite.max())


def test_engineering_linear_limits_match_viewbox(qapp):
    _widget, _plot, handle = _shown_plot()
    x = np.linspace(0.0, 4.0, 9)
    y = np.linspace(-2.0, 6.0, 9)
    handle.plot_item.plot(x, y, name="torque")

    assert handle.set_engineering_xlim(0.5, 3.5) is True
    assert handle.set_engineering_ylim(-2.0, 6.0) is True
    assert handle.get_engineering_xlim() == pytest.approx((0.5, 3.5))
    assert handle.get_engineering_ylim() == pytest.approx((-2.0, 6.0))
    assert handle.get_xlim() == pytest.approx(handle.get_engineering_xlim())
    assert handle.get_ylim() == pytest.approx(handle.get_engineering_ylim())


def test_engineering_log_range_matches_curve_and_ticks(qapp):
    """User range 1…100 must span the curve, with ticks reading 1 and 100."""
    from PyQt5.QtCore import QCoreApplication

    _widget, plot, handle = _shown_plot()
    y = np.linspace(1.0, 100.0, 17)
    x = np.linspace(0.1, 10.0, 17)
    curve = plot.plot(x, y, name="level")
    original_y = np.array(curve.getOriginalDataset()[1], copy=True)

    handle.set_xscale("log")
    handle.set_yscale("log")
    QCoreApplication.processEvents()
    assert handle.set_engineering_xlim(0.1, 10.0) is True
    assert handle.set_engineering_ylim(1.0, 100.0) is True

    assert handle.get_engineering_xlim() == pytest.approx((0.1, 10.0))
    assert handle.get_engineering_ylim() == pytest.approx((1.0, 100.0))
    # ViewBox stays in the same space as the log-mapped curve (log10).
    assert handle.get_xlim() == pytest.approx((np.log10(0.1), np.log10(10.0)))
    assert handle.get_ylim() == pytest.approx((0.0, 2.0))
    drawn_x, drawn_y = curve.getData()
    assert _curve_limits(drawn_x) == pytest.approx(handle.get_xlim())
    assert _curve_limits(drawn_y) == pytest.approx(handle.get_ylim())
    assert len(curve.getOriginalDataset()[1]) == len(original_y)
    np.testing.assert_allclose(curve.getOriginalDataset()[1], original_y)

    x_axis = plot.getAxis("bottom")
    y_axis = plot.getAxis("left")
    assert x_axis.logMode and y_axis.logMode
    x_lo, x_hi = handle.get_xlim()
    y_lo, y_hi = handle.get_ylim()
    assert x_axis.tickStrings([x_lo, x_hi], 1.0, 1.0) == ["0.1", "10¹"]
    assert y_axis.tickStrings([y_lo, y_hi], 1.0, 1.0) == ["1", "10²"]

    # Raw setters keep ViewBox semantics; engineering reads that space back.
    handle.set_ylim(0.0, 1.0)
    assert handle.get_ylim() == pytest.approx((0.0, 1.0))
    assert handle.get_engineering_ylim() == pytest.approx((1.0, 10.0))


def test_log_engineering_rejects_non_positive_without_changing_view(qapp):
    from PyQt5.QtCore import QCoreApplication

    _widget, plot, handle = _shown_plot()
    y = np.array([-5.0, -1.0, 2.0, 50.0, np.nan, np.inf])
    x = np.arange(len(y), dtype=np.float64)
    curve = plot.plot(x, np.array([1.0, 2.0, 4.0, 8.0, 16.0, 32.0]), name="positive")
    mixed = plot.plot(x, y, name="mixed")
    handle.set_yscale("log")
    QCoreApplication.processEvents()
    assert handle.set_engineering_ylim(1.0, 32.0) is True
    view = handle.get_ylim()
    drawn = np.array(curve.getData()[1], copy=True)
    original = np.array(mixed.getOriginalDataset()[1], copy=True)

    data_lo = float(np.nanmin(y))
    data_hi = float(np.nanmax(np.where(np.isfinite(y), y, np.nan)))
    assert data_lo < 0 < data_hi
    assert handle.set_engineering_ylim(data_lo, data_hi) is False
    assert handle.set_engineering_ylim(-8.0, -1.0) is False
    assert handle.set_engineering_ylim(0.0, 10.0) is False
    assert handle.set_engineering_ylim(float("nan"), 10.0) is False
    assert handle.set_engineering_ylim(1.0, float("inf")) is False
    assert handle.set_engineering_ylim(4.0, 4.0) is False
    assert handle.set_engineering_ylim(8.0, 2.0) is False

    assert handle.get_ylim() == pytest.approx(view)
    np.testing.assert_allclose(curve.getData()[1], drawn)
    np.testing.assert_array_equal(mixed.getOriginalDataset()[1], original)
    assert len(mixed.getOriginalDataset()[0]) == len(x)
    assert len(mixed.getOriginalDataset()[1]) == len(y)


def test_engineering_limits_reject_bad_shape_and_keep_curve_length(qapp):
    _widget, plot, handle = _shown_plot()
    x = np.arange(4, dtype=np.int64)
    y = np.array([1.0, 10.0, 100.0, 1000.0])
    curve = plot.plot(x, y, name="decade")
    empty = plot.plot(np.array([]), np.array([]), name="empty")
    short = plot.plot(np.array([2.0]), np.array([3.0]), name="short")
    handle.set_xlim(0.0, 3.0)
    handle.set_ylim(1.0, 1000.0)
    before = (handle.get_xlim(), handle.get_ylim())

    with pytest.raises(ValueError):
        handle.set_engineering_ylim(np.array([1.0, 2.0]), 10.0)
    with pytest.raises(ValueError):
        handle.set_engineering_xlim(np.array([]), 1.0)
    with pytest.raises(ValueError):
        handle.set_engineering_xlim(np.array("nope"), 3.0)
    with pytest.raises(ValueError):
        handle.set_engineering_ylim(True, 2.0)

    assert handle.get_xlim() == pytest.approx(before[0])
    assert handle.get_ylim() == pytest.approx(before[1])
    original_x, original_y = curve.getOriginalDataset()
    assert len(original_x) == 4
    assert len(original_y) == 4
    # An empty PlotDataItem keeps a null dataset. Setting a range must not
    # invent samples or shorten the length-1 curve.
    assert empty.getOriginalDataset() == (None, None)
    assert len(short.getOriginalDataset()[1]) == 1

    handle.set_yscale("log")
    assert handle.set_engineering_ylim(1.0, 1000.0) is True
    after_x, after_y = curve.getOriginalDataset()
    assert len(after_x) == len(original_x)
    assert len(after_y) == len(original_y)
    assert after_x.dtype == original_x.dtype
    assert after_y.dtype == original_y.dtype
    np.testing.assert_array_equal(after_y, original_y)
    assert empty.getOriginalDataset() == (None, None)
    assert len(short.getOriginalDataset()[1]) == 1


def test_linear_restore_puts_engineering_and_curve_in_one_space(qapp):
    from PyQt5.QtCore import QCoreApplication

    _widget, plot, handle = _shown_plot()
    y = np.linspace(1.0, 100.0, 11)
    curve = plot.plot(np.linspace(0.1, 10.0, 11), y, name="level")
    handle.set_yscale("log")
    QCoreApplication.processEvents()
    assert handle.set_engineering_ylim(1.0, 100.0) is True
    handle.set_yscale("linear")
    QCoreApplication.processEvents()

    drawn = curve.getData()[1]
    original = curve.getOriginalDataset()[1]
    assert handle.get_yscale() == "linear"
    assert handle.get_engineering_ylim() == pytest.approx(handle.get_ylim())
    np.testing.assert_allclose(drawn, original)
    eng_lo, eng_hi = handle.get_engineering_ylim()
    assert eng_lo <= float(np.min(original))
    assert eng_hi >= float(np.max(original))
    assert float(np.max(drawn)) == pytest.approx(100.0)


def test_log_ranges_do_not_cross_secondary_axis_or_panes(qapp):
    import pyqtgraph as pg
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui._axis_handle import PgAxisHandle

    widget_a, plot_a, primary = _shown_plot()
    widget_b = pg.GraphicsLayoutWidget()
    widget_b.resize(640, 420)
    plot_b = widget_b.addPlot()
    widget_b.show()
    QCoreApplication.processEvents()
    other = PgAxisHandle(plot_item=plot_b)

    y_a = np.linspace(1.0, 100.0, 12)
    y_b = np.linspace(2.0, 8.0, 12)
    curve_a = plot_a.plot(np.linspace(0.0, 1.0, 12), y_a, name="main")
    curve_b = plot_b.plot(np.linspace(0.0, 1.0, 12), y_b, name="other")
    aux_vb = pg.ViewBox()
    plot_a.scene().addItem(aux_vb)
    right = pg.AxisItem("right")
    right.linkToView(aux_vb)
    aux_curve = pg.PlotDataItem(
        np.linspace(0.0, 1.0, 12),
        np.linspace(10.0, 1000.0, 12),
        name="aux",
    )
    aux_vb.addItem(aux_curve)
    aux = PgAxisHandle(plot_item=plot_a, view_box=aux_vb, axis_item=right)
    aux.add_line_item(aux_curve)
    QCoreApplication.processEvents()

    primary.set_yscale("log")
    assert primary.set_engineering_ylim(1.0, 100.0) is True
    other.set_ylim(2.0, 8.0)
    aux.set_ylim(10.0, 1000.0)
    other_view = other.get_ylim()
    aux_view = aux.get_ylim()
    other_drawn = np.array(curve_b.getData()[1], copy=True)

    aux.set_yscale("log")
    assert aux.set_engineering_ylim(10.0, 1000.0) is True
    assert primary.get_engineering_ylim() == pytest.approx((1.0, 100.0))
    assert primary.get_ylim() == pytest.approx((0.0, 2.0))
    assert other.get_ylim() == pytest.approx(other_view)
    np.testing.assert_allclose(curve_b.getData()[1], other_drawn)
    assert _curve_limits(curve_a.getData()[1]) == pytest.approx((0.0, 2.0))
    assert _curve_limits(aux_curve.getData()[1]) == pytest.approx(
        (np.log10(10.0), np.log10(1000.0))
    )
    assert aux.get_ylim() != pytest.approx(aux_view)
    assert right.logMode is True
    assert plot_b.getAxis("left").logMode is False
    assert widget_a is not widget_b


def test_axis_capability_and_target_text(qapp):
    _widget, plot, primary = _shown_plot()
    import pyqtgraph as pg
    from mf4_analyzer.ui._axis_handle import PgAxisHandle

    right = pg.AxisItem("right")
    aux = PgAxisHandle(plot_item=plot, view_box=pg.ViewBox(), axis_item=right)

    assert primary.supports_log_scale("x") is True
    assert primary.supports_log_scale("y") is True
    assert primary.supports_legend_rebuild() is True
    assert primary.shares_x_axis() is False
    primary._shares_x_axis = True
    assert primary.shares_x_axis() is True
    assert aux.shares_x_axis() is False

    assert primary.chart_options_target_text() == "主轴"
    primary.set_title("  扭矩  ")
    assert primary.chart_options_target_text() == "主轴：扭矩"
    assert primary.get_title() == "扭矩"
    primary._chart_options_target = "  时域 · 子图 1  "
    assert primary.chart_options_target_text() == "时域 · 子图 1"
    primary._chart_options_target = "   "
    assert primary.chart_options_target_text() == "主轴：扭矩"
    # The auxiliary handle shares this PlotItem, so it inherits the title
    # while keeping its own axis role.
    assert aux.chart_options_target_text() == "副轴：扭矩"
    bare_plot = pg.PlotItem()
    bare = PgAxisHandle(
        plot_item=bare_plot,
        view_box=pg.ViewBox(),
        axis_item=pg.AxisItem("right"),
    )
    assert bare.chart_options_target_text() == "副轴"
    assert bare_plot is not plot
    assert "当前图" not in primary.chart_options_target_text()
    assert "当前图" not in aux.chart_options_target_text()
    assert "当前图" not in bare.chart_options_target_text()


def test_clearing_title_collapses_row_and_readback(qapp):
    from PyQt5.QtCore import QCoreApplication

    _widget, plot, handle = _shown_plot()
    QCoreApplication.processEvents()
    baseline_row = _title_row_height(plot)
    baseline_view_y = float(plot.vb.sceneBoundingRect().y())
    seen = []
    handle.add_title_changed_callback(lambda _handle, title: seen.append(title))

    handle.set_title("  Audit title  ")
    QCoreApplication.processEvents()
    assert handle.get_title() == "Audit title"
    assert _title_row_height(plot) > baseline_row
    assert seen[-1] == "Audit title"

    for blank in ("", "   ", "\n\t", None):
        handle.set_title(blank)
        QCoreApplication.processEvents()
        assert handle.get_title() == ""
        assert plot.titleLabel.text == ""
        assert plot.titleLabel.isVisible() is False
        assert _title_row_height(plot) == pytest.approx(baseline_row)
        assert float(plot.vb.sceneBoundingRect().y()) == pytest.approx(baseline_view_y)
        assert seen[-1] == ""


def test_clearing_title_restores_subplot_inside_label(qapp):
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 480)
    t = np.linspace(0.0, 1.0, 24)
    canvas.plot_channels(
        [
            (f"ch{i}", True, t, np.full_like(t, float(i + 1)), "#1769e0", "u")
            for i in range(4)
        ],
        mode="subplot",
    )
    canvas.show()
    QCoreApplication.processEvents()
    handle = canvas.axes_list[0]
    item = next(
        label
        for owner, label in zip(canvas._inside_label_handles, canvas._inside_label_items)
        if owner is handle
    )
    assert item.isVisible() is True
    handle.set_title("Pane")
    QCoreApplication.processEvents()
    assert item.isVisible() is False
    handle.set_title(None)
    QCoreApplication.processEvents()
    assert handle.get_title() == ""
    assert item.isVisible() is True


def test_rebuild_legend_keeps_distinct_curves_that_share_a_name(qapp):
    import json
    from types import SimpleNamespace

    from mf4_analyzer.ui._axis_handle import _PgLineHandle

    _widget, plot, handle = _shown_plot()
    first = plot.plot(np.array([0.0, 1.0]), np.array([1.0, 2.0]), name="same")
    second = plot.plot(np.array([0.0, 1.0]), np.array([3.0, 4.0]), name="same")
    unique = plot.plot(np.array([0.0, 1.0]), np.array([0.0, 1.0]), name="speed")
    hidden = plot.plot(np.array([0.0, 1.0]), np.array([0.0, 1.0]), name="_private")
    key_a = json.dumps(["src-a", "torque"], ensure_ascii=False, separators=(",", ":"))
    key_b = json.dumps(["src-b", "torque"], ensure_ascii=False, separators=(",", ":"))
    key_speed = json.dumps(["src-a", "speed"], ensure_ascii=False, separators=(",", ":"))
    handle._owner_canvas = SimpleNamespace(
        _channel_lines=SimpleNamespace(
            composite_items=lambda: (
                (key_a, "same", (handle, _PgLineHandle(first))),
                (key_b, "same", (handle, _PgLineHandle(second))),
                (key_speed, "speed", (handle, _PgLineHandle(unique))),
            )
        )
    )

    handle.rebuild_legend()
    handle.rebuild_legend()
    legend = handle.plot_item.legend
    rows = []
    for sample, label in legend.items:
        _x_data, y_data = sample.item.getOriginalDataset()
        rows.append((tuple(float(value) for value in y_data), label.text))
    ys = [row[0] for row in rows]
    texts = [row[1] for row in rows]
    assert ys.count((1.0, 2.0)) == 1
    assert ys.count((3.0, 4.0)) == 1
    assert (0.0, 1.0) in ys
    assert len(rows) == 3
    assert first is not second
    assert unique is not hidden
    assert any("same" in text and "src-a" in text for text in texts)
    assert any("same" in text and "src-b" in text for text in texts)
    assert "speed" in texts
    assert all(text != "torque" for text in texts)


def test_autoscale_x_still_uses_owner_raw_union(qapp):
    import pyqtgraph as pg
    from mf4_analyzer.ui._axis_handle import PgAxisHandle

    recorded = []

    class _Owner:
        def get_data_x_union(self):
            recorded.append("union")
            return (4.0, 9.0)

        def restore_visible_xlim(self, xlim, flush=False):
            recorded.append((tuple(xlim), bool(flush)))

    plot = pg.PlotItem()
    handle = PgAxisHandle(plot_item=plot, owner_canvas=_Owner())
    handle.set_xlim(0.0, 1.0)
    handle.autoscale("x")

    assert "union" in recorded
    assert ((4.0, 9.0), True) in recorded
