"""Dense-discrete smooth raster layer contracts for the pyqtgraph canvas."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import Qt

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.dense_raster import build_dense_raster_image


def _row(name="EPS_CRC1", *, data_id="real-blf", phase=0):
    n = 5_727
    t = np.arange(n, dtype=np.float64) / 100.0
    values = ((np.arange(n) + phase) % 256).astype(np.float64)
    return (name, True, t, values, "#16a34a", "", data_id)


def _dense_rows_with_companion():
    primary = _row("EPS_CRC1", data_id="dense-companion")
    companion = _row(
        "EPS_CRC1 (filtered)", data_id="dense-companion", phase=3,
    )
    return [
        primary,
        (*companion, {"companion_of": "EPS_CRC1", "dash": True}),
    ]


def _smooth_row():
    t = np.linspace(0.0, 57.26, 2000)
    return (
        "smooth",
        True,
        t,
        np.sin(t),
        "#2563eb",
        "",
        "mixed",
    )


def _shown_canvas(qapp, rows, *, mode="subplot"):
    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    qapp.processEvents()
    canvas.plot_channels(rows, mode=mode)
    qapp.processEvents()
    return canvas


def _curve_has_no_pen(curve):
    pen = curve.opts.get("pen")
    return pen is None or pen.style() == Qt.NoPen


def test_dense_image_dpr_mapping_reaches_both_data_corners(qapp):
    image = build_dense_raster_image(
        np.array([0.0, 1.0]),
        np.array([0.0, 1.0]),
        data_rect=(0.0, 1.0, 0.0, 1.0),
        logical_size=(100, 50),
        dpr=2.0,
        color="#16a34a",
    )

    def has_alpha_near(x, y):
        for px in range(max(0, x - 3), min(image.width(), x + 4)):
            for py in range(max(0, y - 3), min(image.height(), y + 4)):
                if image.pixelColor(px, py).alpha() > 0:
                    return True
        return False

    assert image.width() == 200 and image.height() == 100
    assert image.devicePixelRatioF() == 2.0
    assert has_alpha_near(0, 99)
    assert has_alpha_near(199, 0)


def test_dense_single_uses_smooth_pixmap_but_keeps_raw_pdi_semantics(qapp):
    row = _row()
    canvas = _shown_canvas(qapp, [row])
    canvas._dense_raster.flush_pending(canvas._interaction_generation)

    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    pdi = canvas._channel_lines["EPS_CRC1"][1].plot_data_item

    assert entry is not None and entry.item.isVisible()
    assert entry.item.transformationMode() == Qt.SmoothTransformation
    assert entry.item.acceptedMouseButtons() == Qt.NoButton
    assert pdi.isVisible() is True
    assert pdi.curve.isVisible() is True
    assert _curve_has_no_pen(pdi.curve)
    assert pdi.dataBounds(0) is not None
    assert len(canvas.channel_data["EPS_CRC1"][1]) == 5_727
    assert canvas._quality.aa_on is False
    status = canvas.quality_status()
    assert status["state"] == "green"
    assert status["render_path"] == "dense-raster"
    assert status["tooltip"] == "平滑曲线已完成（高分辨率缓存）"


def test_dense_raster_is_transform_only_until_100ms_settle(qtbot, qapp):
    canvas = _shown_canvas(qapp, [_row()])
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    item = entry.item
    before_key = item.pixmap().cacheKey()
    pdi = canvas._channel_lines["EPS_CRC1"][1].plot_data_item

    canvas._primary_xaxis_ax.view_box.setXRange(8.0, 10.0, padding=0)
    qapp.processEvents()
    qtbot.wait(50)

    assert canvas._dense_raster.entry_for("EPS_CRC1").item is item
    assert item.pixmap().cacheKey() == before_key
    assert pdi.curve.isVisible() is True
    assert _curve_has_no_pen(pdi.curve)
    assert canvas.quality_status()["state"] == "yellow"

    qtbot.wait(canvas._INTERACTION_SETTLE_MS + 40)
    settled = canvas._dense_raster.entry_for("EPS_CRC1")
    assert settled.item is item
    assert item.pixmap().cacheKey() != before_key
    assert settled.generation == canvas._interaction_generation
    assert settled.data_rect[0] <= 8.0
    assert settled.data_rect[1] >= 10.0
    assert canvas.quality_status()["state"] == "green"


def test_y_only_interaction_rebuilds_after_quiet_window(qtbot, qapp):
    canvas = _shown_canvas(qapp, [_row()])
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    before_key = entry.item.pixmap().cacheKey()
    view_box = canvas._primary_xaxis_ax.view_box

    canvas._begin_view_interaction()
    view_box.setYRange(40.0, 80.0, padding=0)
    canvas._end_view_interaction()
    qapp.processEvents()
    qtbot.wait(50)

    assert entry.item.pixmap().cacheKey() == before_key
    assert canvas.quality_status()["state"] == "yellow"

    qtbot.wait(canvas._INTERACTION_SETTLE_MS + 40)
    settled = canvas._dense_raster.entry_for("EPS_CRC1")
    assert settled.item.pixmap().cacheKey() != before_key
    assert settled.data_rect[2] <= 40.0
    assert settled.data_rect[3] >= 80.0
    assert canvas.quality_status()["state"] == "green"


def test_programmatic_set_ylim_rebuilds_dense_raster(qtbot, qapp):
    canvas = _shown_canvas(qapp, [_row()])
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    axis, _line = canvas._channel_lines["EPS_CRC1"]
    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    before_key = entry.item.pixmap().cacheKey()

    axis.set_ylim(60.0, 100.0)
    qtbot.wait(50)

    assert entry.item.pixmap().cacheKey() == before_key

    qtbot.wait(canvas._INTERACTION_SETTLE_MS + 40)
    settled = canvas._dense_raster.entry_for("EPS_CRC1")
    assert settled.item.pixmap().cacheKey() != before_key
    assert settled.data_rect[2] <= 60.0
    assert settled.data_rect[3] >= 100.0


@pytest.mark.parametrize("autoscale_axis", ["y", "both"])
def test_programmatic_y_autoscale_rebuilds_at_final_range(
    qtbot, qapp, autoscale_axis,
):
    canvas = _shown_canvas(qapp, [_row()])
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    axis, _line = canvas._channel_lines["EPS_CRC1"]
    axis.set_ylim(60.0, 100.0)
    qtbot.wait(canvas._INTERACTION_SETTLE_MS + 40)
    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    before_key = entry.item.pixmap().cacheKey()

    axis.autoscale(autoscale_axis)
    qapp.processEvents()
    qtbot.wait(50)
    assert entry.item.pixmap().cacheKey() == before_key

    qtbot.wait(canvas._INTERACTION_SETTLE_MS + 60)
    settled = canvas._dense_raster.entry_for("EPS_CRC1")
    ylo, yhi = axis.get_ylim()
    assert settled.item.pixmap().cacheKey() != before_key
    assert settled.data_rect[2] <= min(ylo, yhi)
    assert settled.data_rect[3] >= max(ylo, yhi)


def test_held_pan_crossing_buffer_gets_coarse_raster_refresh(qtbot, qapp):
    canvas = _shown_canvas(qapp, [_row()])
    axis, _line = canvas._channel_lines["EPS_CRC1"]
    axis.view_box.setXRange(5.0, 10.0, padding=0)
    canvas._flush_pending_refresh()
    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    before_key = entry.item.pixmap().cacheKey()
    assert entry.data_rect[1] < 20.0

    canvas._begin_view_interaction()
    axis.view_box.setXRange(20.0, 25.0, padding=0)
    qtbot.wait(50)
    assert entry.item.pixmap().cacheKey() == before_key

    qtbot.wait(260)
    refreshed = canvas._dense_raster.entry_for("EPS_CRC1")
    assert canvas._interaction_depth == 1
    assert refreshed.item.pixmap().cacheKey() != before_key
    assert refreshed.data_rect[0] <= 20.0
    assert refreshed.data_rect[1] >= 25.0
    canvas._end_view_interaction()


def test_dense_raster_visibility_color_and_revision_invalidate(qapp):
    row = _row()
    canvas = _shown_canvas(qapp, [row])
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    first_key = entry.item.pixmap().cacheKey()
    context = canvas._selection_context_key

    assert canvas.try_apply_selection_delta(
        [], mode="subplot", render_context_key=context,
    )["applied"] is True
    assert entry.item.isVisible() is False
    assert canvas.try_apply_selection_delta(
        [row], mode="subplot", render_context_key=context,
    )["applied"] is True
    assert entry.item.isVisible() is True

    composite = canvas._channel_lines.composite_key_for("EPS_CRC1")
    axis, line = canvas._channel_lines[composite]
    line.set_color("#dc2626")
    axis.sync_line_axis_color(line, "#dc2626")
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    recolored = canvas._dense_raster.entry_for(composite)
    assert recolored.color == "#dc2626"
    assert recolored.item.pixmap().cacheKey() != first_key
    assert recolored.native_pen.widthF() == entry.native_pen.widthF()
    recolored_key = recolored.item.pixmap().cacheKey()

    pdi = canvas._channel_lines[composite][1].plot_data_item
    pdi.setPen(pg.mkPen(color="#dc2626", width=1.8))
    canvas._dense_raster.invalidate_all("line-width", schedule=True)
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    widened = canvas._dense_raster.entry_for(composite)
    assert widened.native_pen.widthF() == 1.8
    assert widened.item.pixmap().cacheKey() != recolored_key

    row[3][:] = (np.arange(row[3].size) * 3) % 256
    color_key = widened.item.pixmap().cacheKey()
    canvas._primary_xaxis_ax.view_box.setXRange(4.0, 7.0, padding=0)
    canvas._flush_pending_refresh()
    revised = canvas._dense_raster.entry_for(composite)
    assert revised.item.pixmap().cacheKey() != color_key
    assert revised.source_revision != recolored.source_revision


def test_production_color_sync_survives_memory_fallback(qapp):
    canvas = _shown_canvas(qapp, [_row()])
    manager = canvas._dense_raster
    manager.flush_pending(canvas._interaction_generation)
    axis, line = canvas._channel_lines["EPS_CRC1"]
    initial_width = manager.entry_for("EPS_CRC1").native_pen.widthF()
    assert line.get_color() == "#16a34a"

    line.set_color("#dc2626")
    axis.sync_line_axis_color(line, "#dc2626")
    manager.max_item_bytes = 1
    manager.flush_pending(canvas._interaction_generation)

    pen = line.plot_data_item.opts["pen"]
    assert manager.entry_for("EPS_CRC1") is None
    assert pen.color().name() == "#dc2626"
    assert pen.widthF() == initial_width


def test_dense_companion_restores_dash_and_deactivates_raster(qapp):
    canvas = _shown_canvas(qapp, _dense_rows_with_companion())
    manager = canvas._dense_raster
    manager.flush_pending(canvas._interaction_generation)
    companion_key = next(iter(canvas._companion_names))
    companion_pdi = canvas._channel_lines[companion_key][1].plot_data_item
    assert companion_pdi.opts["pen"].style() == Qt.DashLine
    assert manager.entry_for(companion_key) is None

    canvas.set_original_lines_visible(False)
    manager.flush_pending(canvas._interaction_generation)
    solid_entry = manager.entry_for(companion_key)
    assert solid_entry is not None
    assert solid_entry.native_pen.style() == Qt.SolidLine

    canvas.set_original_lines_visible(True)
    manager.flush_pending(canvas._interaction_generation)

    assert manager.entry_for(companion_key) is None
    assert companion_pdi.opts["pen"].style() == Qt.DashLine
    assert not companion_pdi.curve.opts.get("antialias", False)


def test_dense_companion_production_recolor_preserves_dash_fallback(qapp):
    canvas = _shown_canvas(qapp, _dense_rows_with_companion())
    manager = canvas._dense_raster
    manager.flush_pending(canvas._interaction_generation)
    companion_key = next(iter(canvas._companion_names))
    axis, line = canvas._channel_lines[companion_key]
    original_width = line.plot_data_item.opts["pen"].widthF()

    line.set_color("#dc2626")
    axis.sync_line_axis_color(line, "#dc2626")
    manager.flush_pending(canvas._interaction_generation)

    pen = line.plot_data_item.opts["pen"]
    assert pen.color().name() == "#dc2626"
    assert pen.widthF() == original_width
    assert pen.style() == Qt.DashLine
    assert manager.entry_for(companion_key) is None


def test_overlay_and_memory_limit_fall_back_to_native_non_aa(qapp):
    canvas = _shown_canvas(qapp, [_row("a"), _row("b", phase=1)], mode="overlay")
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    assert canvas._dense_raster.entries == {}
    for _name, (_axis, line) in canvas._channel_lines.items():
        assert line.plot_data_item.curve.isVisible() is True
        assert not line.plot_data_item.curve.opts.get("antialias", False)

    single = _shown_canvas(qapp, [_row()])
    single._dense_raster.max_item_bytes = 1
    single._dense_raster.invalidate_all("test-budget", schedule=True)
    single._dense_raster.flush_pending(single._interaction_generation)
    pdi = single._channel_lines["EPS_CRC1"][1].plot_data_item
    assert single._dense_raster.entry_for("EPS_CRC1") is None
    assert pdi.curve.isVisible() is True
    status = single.quality_status()
    assert status["state"] == "red"
    assert status["block_reason"] == "high-raster-cost"

    single._dense_raster.max_item_bytes = 16 * 1024 * 1024
    single._dense_raster.max_global_bytes = 1
    single._dense_raster.invalidate_all("test-global-budget", schedule=True)
    single._dense_raster.flush_pending(single._interaction_generation)
    assert single._dense_raster.entry_for("EPS_CRC1") is None
    assert not _curve_has_no_pen(pdi.curve)

    peak = _shown_canvas(qapp, [_row(data_id="global-peak")])
    peak_manager = peak._dense_raster
    peak_manager.flush_pending(peak._interaction_generation)
    peak_entry = peak_manager.entry_for("EPS_CRC1")
    retained_global = peak_manager.global_memory_bytes()
    peak_manager.max_global_bytes = retained_global + peak_entry.memory_bytes + 1
    peak_manager.invalidate_all("test-image-pixmap-peak", schedule=True)
    peak_manager.flush_pending(peak._interaction_generation)
    assert peak_manager.entry_for("EPS_CRC1") is None


@pytest.mark.parametrize("scale_axis", ["x", "y"])
def test_log_axis_production_setter_falls_back_with_latest_pen(qapp, scale_axis):
    canvas = _shown_canvas(qapp, [_row()])
    axis, line = canvas._channel_lines["EPS_CRC1"]
    initial_width = canvas._dense_raster.entry_for("EPS_CRC1").native_pen.widthF()
    line.set_color("#dc2626")
    axis.sync_line_axis_color(line, "#dc2626")
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    assert canvas._dense_raster.entry_for("EPS_CRC1") is not None
    assert not canvas._dense_raster.timer.isActive()

    getattr(axis, f"set_{scale_axis}scale")("log")
    qapp.processEvents()

    assert canvas._dense_raster.entry_for("EPS_CRC1") is None
    assert line.plot_data_item.isVisible() is True
    assert not _curve_has_no_pen(line.plot_data_item.curve)
    assert line.plot_data_item.opts["pen"].color().name() == "#dc2626"
    assert line.plot_data_item.opts["pen"].widthF() == initial_width
    assert not line.plot_data_item.curve.opts.get("antialias", False)
    assert canvas.quality_status()["state"] == "red"


def test_scale_setter_does_not_invalidate_ordinary_curve(qapp, monkeypatch):
    t = np.linspace(0.0, 10.0, 1000)
    row = ("smooth", True, t, np.sin(t), "#2563eb", "", "ordinary")
    canvas = _shown_canvas(qapp, [row])
    axis, _line = canvas._channel_lines["smooth"]
    calls = []
    monkeypatch.setattr(
        canvas._dense_raster,
        "invalidate_all",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    axis.set_yscale("log")

    assert calls == []
    assert canvas._dense_raster.entries == {}


def test_mixed_subplot_uses_raster_for_dense_and_native_aa_for_smooth(
    qtbot, qapp, monkeypatch,
):
    from PyQt5.QtWidgets import QApplication

    canvas = _shown_canvas(qapp, [_row(data_id="mixed"), _smooth_row()])
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    dense_curve = canvas._channel_lines["EPS_CRC1"][1].plot_data_item.curve
    smooth_curve = canvas._channel_lines["smooth"][1].plot_data_item.curve
    monkeypatch.setattr(
        QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton),
    )

    canvas.try_enable_idle_quality()

    assert not dense_curve.opts.get("antialias", False)
    assert smooth_curve.opts.get("antialias", False)
    status = canvas.quality_status()
    assert status["state"] == "green"
    assert status["render_path"] == "dense-raster+native-aa"
    assert status["tooltip"] == "高分辨率平滑缓存；其他曲线抗锯齿已完成"

    observed = []
    original_grab = canvas._grab_widget_scaled

    def capture_export_aa(widget, scale):
        observed.append((
            bool(dense_curve.opts.get("antialias", False)),
            bool(smooth_curve.opts.get("antialias", False)),
        ))
        return original_grab(widget, scale)

    monkeypatch.setattr(canvas, "_grab_widget_scaled", capture_export_aa)
    assert not canvas.grab_pixmap(scale=1.0).isNull()
    assert observed and all(not dense and smooth for dense, smooth in observed)

    canvas._begin_view_interaction()
    canvas._primary_xaxis_ax.view_box.setXRange(10.0, 15.0, padding=0)
    assert not dense_curve.opts.get("antialias", False)
    assert not smooth_curve.opts.get("antialias", False)
    canvas._end_view_interaction()
    qtbot.wait(canvas._INTERACTION_SETTLE_MS + 200)

    assert not dense_curve.opts.get("antialias", False)
    assert smooth_curve.opts.get("antialias", False)


def test_mixed_subplot_dense_fallback_still_blocks_all_native_aa(
    qapp, monkeypatch,
):
    from PyQt5.QtWidgets import QApplication

    canvas = _shown_canvas(qapp, [_row(data_id="mixed"), _smooth_row()])
    manager = canvas._dense_raster
    monkeypatch.setattr(
        QApplication, "mouseButtons", staticmethod(lambda: Qt.NoButton),
    )
    manager.flush_pending(canvas._interaction_generation)
    canvas.try_enable_idle_quality()
    smooth_curve = canvas._channel_lines["smooth"][1].plot_data_item.curve
    assert smooth_curve.opts.get("antialias", False)

    manager.max_item_bytes = 1
    manager.invalidate_all("mixed-fallback", schedule=True)
    manager.flush_pending(canvas._interaction_generation)
    curves = [
        canvas._channel_lines[name][1].plot_data_item.curve
        for name in ("EPS_CRC1", "smooth")
    ]

    assert manager.entry_for("EPS_CRC1") is None
    assert canvas._quality.aa_on is False
    assert not any(curve.opts.get("antialias", False) for curve in curves)
    assert canvas.quality_status()["block_reason"] == "high-raster-cost"


def test_pending_export_flushes_dense_raster_without_enabling_native_aa(qapp):
    canvas = _shown_canvas(qapp, [_row()])
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    old_key = canvas._dense_raster.entry_for("EPS_CRC1").item.pixmap().cacheKey()
    canvas._primary_xaxis_ax.view_box.setXRange(12.0, 15.0, padding=0)
    assert canvas._refresh_pending is True

    pixmap = canvas.grab_pixmap(scale=2.0)

    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    assert not pixmap.isNull()
    assert canvas._refresh_pending is False
    assert entry.item.pixmap().cacheKey() != old_key
    assert entry.data_rect[0] <= 12.0 and entry.data_rect[1] >= 15.0
    assert canvas._quality.aa_on is False
    assert _curve_has_no_pen(
        canvas._channel_lines["EPS_CRC1"][1].plot_data_item.curve
    )


def test_clear_replaces_timers_and_stale_timeouts_cannot_touch_rebuild(qapp):
    canvas = _shown_canvas(qapp, [_row()])
    manager = canvas._dense_raster
    manager.flush_pending(canvas._interaction_generation)
    old_entry = manager.entry_for("EPS_CRC1")
    old_item = old_entry.item
    manager.schedule_rebuild("old-generation", delay_ms=1000)
    manager.schedule_resuppress()
    old_rebuild_timer = manager.timer
    old_suppress_timer = manager.suppress_timer
    old_generation = canvas._interaction_generation

    canvas.clear()

    assert canvas._interaction_generation == old_generation + 1
    assert old_item.scene() is None
    assert manager.timer is not old_rebuild_timer
    assert manager.suppress_timer is not old_suppress_timer

    canvas.plot_channels([_row(phase=3)], mode="subplot")
    qapp.processEvents()
    manager.flush_pending(canvas._interaction_generation)
    new_entry = manager.entry_for("EPS_CRC1")
    new_key = new_entry.item.pixmap().cacheKey()

    old_rebuild_timer.timeout.emit()
    old_suppress_timer.timeout.emit()
    qapp.processEvents()

    assert manager.entry_for("EPS_CRC1") is new_entry
    assert new_entry.item.pixmap().cacheKey() == new_key
    assert new_entry.generation == canvas._interaction_generation
