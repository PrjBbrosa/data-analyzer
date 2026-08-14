"""Dense-discrete smooth raster layer contracts for the pyqtgraph canvas."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import Qt

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas.dense_raster import (
    build_dense_raster_image,
    raster_would_stretch,
)


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


def _dense_continuous_rows(count=3, *, samples=120_000):
    t = np.linspace(0.0, 50.0, samples, dtype=np.float64)
    colors = ("#1769e0", "#00a67d", "#ff5a0a", "#8747ff")
    return [
        (
            f"physical-{idx}",
            True,
            t,
            np.sin((idx + 1) * t) + 0.02 * np.cos(31.0 * t),
            colors[idx % len(colors)],
            "g",
            "dense-continuous",
        )
        for idx in range(count)
    ]


def _shown_canvas(qapp, rows, *, mode="subplot"):
    canvas = TimeDomainCanvasPG()
    canvas.resize(1200, 700)
    canvas.show()
    qapp.processEvents()
    canvas.plot_channels(rows, mode=mode)
    qapp.processEvents()
    return canvas


def _force_ink_raster(canvas, name):
    """Admit ``name`` on the ink leg so parked CRC policy still has a pixmap."""
    from mf4_analyzer.ui.pg_canvas.renderer import _INK_AA_OFF

    ck = canvas._channel_lines.composite_key_for(name)
    canvas._line_ink_state[ck] = (float(_INK_AA_OFF) + 1.0, True)
    canvas._ink_raster_admitted.add(ck)
    canvas._dense_raster.flush_pending(canvas._interaction_generation)


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


@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
def test_dense_raster_is_transform_only_until_100ms_settle(qtbot, qapp):
    canvas = _shown_canvas(qapp, [_row()])
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    item = entry.item
    before_key = item.pixmap().cacheKey()
    pdi = canvas._channel_lines["EPS_CRC1"][1].plot_data_item

    canvas._primary_xaxis_ax.view_box.setXRange(8.0, 10.0, padding=0)
    qapp.processEvents()

    # Probe the pre-settle state while the debounce timer is still armed, not
    # after a wall-clock qtbot.wait(50): under full-suite load that wait can
    # overrun _INTERACTION_SETTLE_MS, the raster re-renders, and the cacheKey
    # assertion below fails for a reason that has nothing to do with the
    # contract under test.
    assert canvas._refresh_timer.isActive()
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


@pytest.mark.parametrize(
    "mode,count", [("subplot", 1), ("subplot", 3), ("overlay", 3)],
)
def test_dense_continuous_does_not_enter_crc_pixmap_backend(qapp, mode, count):
    """Six DPR2 pixmaps regress Cocoa composition; keep physical rows native."""
    rows = _dense_continuous_rows(count)
    canvas = _shown_canvas(qapp, rows, mode=mode)
    canvas._dense_raster.flush_pending(canvas._interaction_generation)

    assert all(
        canvas._dense_raster.entry_for(row[0]) is None for row in rows
    )


@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
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
@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
def test_dense_raster_visibility_color_and_revision_invalidate(qapp):
    row = _row()
    # Overlay, not subplot: a7cec68 made a zero-row subplot selection
    # structural ("subplot-empty-selection-reset"), so subplot never reaches
    # the in-place hide this asserts on. Overlay still does.
    canvas = _shown_canvas(qapp, [row], mode="overlay")
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    entry = canvas._dense_raster.entry_for("EPS_CRC1")
    first_key = entry.item.pixmap().cacheKey()
    context = canvas._selection_context_key

    assert canvas.try_apply_selection_delta(
        [], mode="overlay", render_context_key=context,
    )["applied"] is True
    assert entry.item.isVisible() is False
    assert canvas.try_apply_selection_delta(
        [row], mode="overlay", render_context_key=context,
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


@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
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
@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
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


@pytest.mark.crc_dense_discrete_policy
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


# ---------------------------------------------------------------------------
# Ink-driven raster admission (spec §4.3, plan Task 4).
#
# The raster backend used to be reserved for ``strategy == "dense_discrete"``.
# Spec §4.3 widens it to the OTHER geometry vector AA cannot afford: a line
# whose measured vertical ink is over the shared AA/raster band. Everything
# below fences that widening — the shared predicate itself, the five consumers
# that were re-pointed at it, and the memory caps that had to be re-baselined
# so a full-row image is admissible at all.
# ---------------------------------------------------------------------------

_MIB = 1024 * 1024


def _oscillating_row(name="ch0", *, data_id="ink-fid"):
    """Spec §3.2 fixture: 1M samples @20 kHz, a 2300 Hz ±100 oscillation on a
    slow 0.7 Hz swing. Every envelope bucket spans nearly the full amplitude,
    so with Y fitted to the data the line paints as a solid ink band —
    ``strategy`` stays ``general`` (approx_unique is huge), which is exactly
    why the old dense-discrete-only admission could never reach it.
    """
    t = np.arange(1_000_000, dtype=np.float64) / 20_000.0
    sig = (
        100.0 * np.sin(2 * np.pi * 2300.0 * t)
        + 8.0 * np.sin(2 * np.pi * 0.7 * t)
    )
    return (name, True, t, sig, "#1769e0", "u", data_id)


def _ink_canvas(qapp, *, width=1920, height=900, rows=None):
    canvas = TimeDomainCanvasPG()
    canvas.resize(width, height)
    canvas.show()
    qapp.processEvents()
    canvas.plot_channels(rows or [_oscillating_row()], mode="subplot")
    qapp.processEvents()
    return canvas


def _ink_admitted_canvas(qapp, **kwargs):
    """A settled canvas whose single ``general`` line is over the ink band."""
    canvas = _ink_canvas(qapp, **kwargs)
    canvas.fit_y_to_visible_x()
    canvas._flush_pending_refresh()
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    return canvas, canvas._channel_lines.composite_key_for("ch0")


def _row_image_bytes(canvas, ck):
    """The item-cap target for this row: logical-2x device pixels x 4 B."""
    axis, _line = canvas._channel_lines[ck]
    rect = axis.view_box.sceneBoundingRect()
    raster_dpr = max(2.0, float(canvas._glw.devicePixelRatioF()))
    return (
        max(1, int(round(int(round(rect.width())) * raster_dpr)))
        * max(1, int(round(int(round(rect.height())) * raster_dpr)))
        * 4
    )


@pytest.mark.crc_dense_discrete_policy
def test_raster_backend_eligible_admits_dense_discrete_at_any_ink(qapp):
    """Leg one of the predicate: the original strategy admission is untouched
    and does NOT consult ink (a CRC counter is admissible while flat)."""
    canvas = _shown_canvas(qapp, [_row()])
    ck = canvas._channel_lines.composite_key_for("EPS_CRC1")

    assert canvas._channel_render_profiles[ck].strategy == "dense_discrete"
    canvas._line_ink_state[ck] = (0.0, False)
    assert canvas._raster_backend_eligible(ck) is True
    assert ck not in canvas._ink_raster_admitted


def test_parked_dense_discrete_policy_defers_crc_raster_to_ink(qapp):
    """With the CRC policy parked, a flat counter is not raster-eligible
    until ink crosses the shared AA band."""
    from mf4_analyzer.render_profile import DENSE_DISCRETE_POLICY_ENABLED

    if DENSE_DISCRETE_POLICY_ENABLED:
        pytest.skip("CRC dense_discrete policy is on")
    canvas = _shown_canvas(qapp, [_row()])
    ck = canvas._channel_lines.composite_key_for("EPS_CRC1")
    assert canvas._channel_render_profiles[ck].strategy == "dense_discrete"
    canvas._line_ink_state[ck] = (0.0, False)
    canvas._ink_raster_admitted.discard(ck)
    assert canvas._raster_backend_eligible(ck) is False


def test_raster_backend_eligible_ink_admission_has_hysteresis(qapp):
    """Leg two: a ``general`` line is admitted over ``_INK_AA_OFF`` and only
    released under ``_INK_AA_ON``. Inside the band the previous decision is
    held, so a line hovering on the boundary cannot flap between the raster
    and vector backends (spec §4.3 "同一边界防抖").
    """
    from mf4_analyzer.ui.pg_canvas.renderer import _INK_AA_ON, _INK_AA_OFF

    canvas = _shown_canvas(qapp, [_smooth_row()])
    ck = canvas._channel_lines.composite_key_for("smooth")
    assert canvas._channel_render_profiles[ck].strategy != "dense_discrete"
    mid = (_INK_AA_ON + _INK_AA_OFF) / 2.0

    def eligible(ink):
        canvas._line_ink_state[ck] = (float(ink), ink > _INK_AA_OFF)
        return canvas._raster_backend_eligible(ck)

    # Below the ON threshold: out.
    assert eligible(_INK_AA_ON - 1.0) is False
    # Rising INTO the band is not enough — admission needs the OFF crossing.
    assert eligible(mid) is False
    assert eligible(_INK_AA_OFF) is False
    # Over OFF: admitted, and the admission set records it.
    assert eligible(_INK_AA_OFF + 1.0) is True
    assert ck in canvas._ink_raster_admitted
    # Falling back INTO the band keeps the raster backend (no flap).
    assert eligible(mid) is True
    assert eligible(_INK_AA_ON) is True
    # Only under ON is it released.
    assert eligible(_INK_AA_ON - 1.0) is False
    assert ck not in canvas._ink_raster_admitted


def test_raster_backend_eligible_round_trips_the_band_without_flapping(qapp):
    """Ten boundary round trips must produce exactly ten state changes — the
    admission is a function of the crossing, not of the visit count."""
    from mf4_analyzer.ui.pg_canvas.renderer import _INK_AA_ON, _INK_AA_OFF

    canvas = _shown_canvas(qapp, [_smooth_row()])
    ck = canvas._channel_lines.composite_key_for("smooth")
    mid = (_INK_AA_ON + _INK_AA_OFF) / 2.0
    observed = []
    for _ in range(5):
        for ink in (_INK_AA_OFF + 1.0, mid, mid, _INK_AA_ON - 1.0, mid, mid):
            canvas._line_ink_state[ck] = (float(ink), False)
            observed.append(canvas._raster_backend_eligible(ck))

    assert observed == [True, True, True, False, False, False] * 5


def test_clear_resets_ink_raster_admission(qapp):
    from mf4_analyzer.ui.pg_canvas.renderer import _INK_AA_OFF

    canvas = _shown_canvas(qapp, [_smooth_row()])
    ck = canvas._channel_lines.composite_key_for("smooth")
    canvas._line_ink_state[ck] = (_INK_AA_OFF * 2.0, True)
    assert canvas._raster_backend_eligible(ck) is True

    canvas.clear()

    assert canvas._ink_raster_admitted == set()


def test_high_ink_general_line_gets_raster_entry_and_suppressed_pen(qapp):
    """End to end: the geometry vector AA measured at 63 s/frame settles onto
    the raster backend instead — entry present, native stroke suppressed, and
    the quality dot reads the dense-raster path (spec §4.3)."""
    from mf4_analyzer.ui.pg_canvas.renderer import _INK_AA_OFF

    canvas, ck = _ink_admitted_canvas(qapp)
    ink, high = canvas._line_ink_state.get(ck)
    pdi = canvas._channel_lines[ck][1].plot_data_item

    assert high is True
    assert ink > _INK_AA_OFF
    assert canvas._channel_render_profiles[ck].strategy != "dense_discrete"
    assert canvas._raster_backend_eligible(ck) is True

    entry = canvas._dense_raster.entry_for(ck)
    assert entry is not None and entry.item.isVisible()
    assert pdi.opts["pen"] is None
    assert _curve_has_no_pen(pdi.curve)
    assert pdi.isVisible() is True
    status = canvas.quality_status()
    assert status["state"] == "green"
    assert status["render_path"] == "dense-raster"


def test_ink_falling_under_band_restores_the_native_vector_line(qapp):
    """Widening Y drops the ink under ``_INK_AA_ON``; the raster entry is
    dropped and the saved native pen comes back."""
    from mf4_analyzer.ui.pg_canvas.renderer import _INK_AA_ON

    canvas, ck = _ink_admitted_canvas(qapp)
    assert canvas._dense_raster.entry_for(ck) is not None
    axis, line = canvas._channel_lines[ck]
    pdi = line.plot_data_item

    axis.set_ylim(-100_000.0, 100_000.0)
    canvas._flush_pending_refresh()

    ink, high = canvas._line_ink_state.get(ck)
    assert high is False
    assert ink < _INK_AA_ON
    assert canvas._raster_backend_eligible(ck) is False
    assert canvas._dense_raster.entry_for(ck) is None
    assert pdi.opts["pen"] is not None
    assert not _curve_has_no_pen(pdi.curve)


def test_interactive_skip_path_covers_ink_admitted_lines(qapp):
    """The transform-only interaction contract must extend to the widened
    admission: while a held gesture stays inside the raster's own coverage the
    line takes ZERO ``setData`` calls (the ``held_pan_setdata_count == 0``
    contract in scripts/benchmark_timedomain_interaction.py).
    """
    canvas, ck = _ink_admitted_canvas(qapp)
    entry = canvas._dense_raster.entry_for(ck)
    assert entry is not None
    coverage = canvas._display_x_coverage_by_channel[ck]

    setdata_calls = []
    pdi = canvas._channel_lines[ck][1].plot_data_item
    original_setdata = pdi.setData

    def counted_setdata(*args, **kwargs):
        setdata_calls.append(args)
        return original_setdata(*args, **kwargs)

    pdi.setData = counted_setdata

    lo, hi = (float(v) for v in coverage)
    span = hi - lo
    canvas._begin_view_interaction()
    try:
        for step in range(1, 6):
            inset = span * 0.02 * step
            canvas._refresh_visible_data(
                xlim_override=(lo + inset, hi - inset), interactive=True,
            )
    finally:
        canvas._end_view_interaction()

    assert setdata_calls == []
    assert canvas._dense_raster.entry_for(ck) is entry
    # The skip must also carry the recorded ink forward, or the AA gate would
    # re-arm mid-gesture over an ink band that is still on screen.
    assert canvas._frame_ink_high is True


def test_full_row_raster_image_fits_the_item_cap(qapp):
    """Spec §4.3: a single 1920x900 row is ~26 MiB at logical 2x. Under the
    old 16 MiB item cap the raster upgrade was rejected for exactly the
    geometry that needs it most."""
    from mf4_analyzer.ui.pg_canvas.dense_raster import DEFAULT_MAX_ITEM_BYTES

    canvas, ck = _ink_admitted_canvas(qapp)
    entry = canvas._dense_raster.entry_for(ck)
    target = _row_image_bytes(canvas, ck)

    assert canvas._glw.devicePixelRatioF() == 1.0  # offscreen; raster_dpr = 2
    assert 16 * _MIB < target <= DEFAULT_MAX_ITEM_BYTES
    assert entry is not None
    assert entry.memory_bytes == target


def test_legacy_16mib_item_cap_rejects_the_row_and_stays_native_non_aa(qapp):
    """The rejection path is unchanged by the widening: native non-AA plus a
    red dot — never a fallback into the vector AA the ink budget just refused.
    """
    canvas, ck = _ink_admitted_canvas(qapp)
    pdi = canvas._channel_lines[ck][1].plot_data_item
    assert canvas._dense_raster.entry_for(ck) is not None
    aa_before = bool(pdi.curve.opts.get("antialias", False))

    canvas._dense_raster.max_item_bytes = 16 * _MIB
    canvas._dense_raster.invalidate_all("legacy-item-cap", schedule=True)
    canvas._dense_raster.flush_pending(canvas._interaction_generation)

    assert canvas._dense_raster.entry_for(ck) is None
    assert pdi.opts["pen"] is not None
    assert pdi.curve.isVisible() is True
    assert bool(pdi.curve.opts.get("antialias", False)) is aa_before
    assert canvas._quality.aa_on is False
    status = canvas.quality_status()
    assert status["state"] == "red"
    assert status["render_path"] == "native-non-aa"
    assert status["block_reason"] == "high-raster-cost"


def test_dense_raster_memory_caps_stay_in_the_spec_band():
    """Mutation guard for the two caps re-baselined in spec §4.3 / §5.

    Change spec §5 FIRST, then these bands. The tiling argument they encode:
    subplot rows tile the viewport, so the sum of all row images is about one
    viewport of device pixels (1920x1080 @dpr2 -> 3840x2160 x 4 B ~ 31.6 MiB),
    while the single worst-case ROW image is ~26 MiB (1920x900 logical at
    logical 2x). The item cap must clear that row; the global cap must hold a
    tiled viewport PLUS the 2x QImage+QPixmap peak of the row being built.
    """
    from mf4_analyzer.ui.pg_canvas.dense_raster import (
        DEFAULT_MAX_GLOBAL_BYTES, DEFAULT_MAX_ITEM_BYTES,
    )

    # Below 24 MiB the full-row upgrade is rejected (the bug this fixes);
    # above 64 MiB one retained row could outweigh the whole tiled viewport.
    assert 24 * _MIB <= DEFAULT_MAX_ITEM_BYTES <= 64 * _MIB
    # Below 64 MiB a tiled viewport plus one build peak no longer fits; above
    # 128 MiB the aggregate stops being a meaningful ceiling.
    assert 64 * _MIB <= DEFAULT_MAX_GLOBAL_BYTES <= 128 * _MIB
    # The global cap has to absorb the build-time QImage+QPixmap 2x peak of a
    # single max-size item on top of what is already retained.
    assert DEFAULT_MAX_GLOBAL_BYTES >= 2 * DEFAULT_MAX_ITEM_BYTES


def _subsample_gap_rows():
    """100 Hz CAN-like file: smooth analog + high-variation integer angle."""
    fs = 100.0
    n = 4_000
    t = np.arange(n, dtype=np.float64) / fs
    torque = np.zeros(n, dtype=np.float64)
    angle = np.where((np.arange(n) % 2) == 0, 0.0, 55_000.0).astype(np.float64)
    return [
        ("torque", True, t, torque, "#1769e0", "Nm", "tiaodamping"),
        ("angle", True, t, angle, "#ff5a0a", "", "tiaodamping"),
    ]


def _gap_xlim(t, *, span=2e-6):
    """Return a window strictly between two adjacent 100 Hz samples."""
    mid = 0.5 * (float(t[1685]) + float(t[1686]))
    half = span / 2.0
    return mid - half, mid + half


def _assert_angle_not_stretched_block(canvas, view_lo, view_hi, *, dt=0.01):
    pdi = canvas._channel_lines["angle"][1].plot_data_item
    xd, yd = pdi.getData()
    xd = np.asarray([] if xd is None else xd, dtype=float)
    yd = np.asarray([] if yd is None else yd, dtype=float)
    entry = canvas._dense_raster.entry_for("angle")
    view_span = float(view_hi) - float(view_lo)
    if entry is not None and entry.item.isVisible():
        rect_span = float(entry.data_rect[1] - entry.data_rect[0])
        assert rect_span <= max(4.0 * view_span, 2.0 * dt), (
            f"raster still mapped to {rect_span:.6g}s while the view is "
            f"{view_span:.6g}s; that stretch paints a solid block"
        )
    return pdi, xd, yd, entry


def test_sub_sample_zoom_does_not_keep_stretched_dense_raster(qapp):
    """Zooming inside one 100 Hz sample interval must not keep the CRC
    raster.  Transforming that pixmap turns one full-height column into a
    solid colour block (wRPS_SpaceAngle_gdu32 at ~200 ns/div).
    """
    rows = _subsample_gap_rows()
    t = rows[0][2]
    canvas = _shown_canvas(qapp, rows)
    _force_ink_raster(canvas, "angle")

    assert canvas._channel_render_profiles[
        canvas._channel_lines.composite_key_for("angle")
    ].strategy == "dense_discrete"
    assert canvas._dense_raster.entry_for("angle") is not None

    lo, hi = _gap_xlim(t)
    canvas._primary_xaxis_ax.view_box.setXRange(lo, hi, padding=0)
    canvas._flush_pending_refresh()
    canvas._dense_raster.flush_pending(canvas._interaction_generation)
    qapp.processEvents()

    pdi, xd, yd, entry = _assert_angle_not_stretched_block(canvas, lo, hi)
    assert entry is None or not entry.item.isVisible()
    assert xd.size >= 2
    assert float(np.nanmax(xd) - np.nanmin(xd)) <= 0.03
    assert pdi.opts.get("pen") is not None or (
        pdi.curve.opts.get("pen") is not None
        and pdi.curve.opts.get("pen").style() != Qt.NoPen
    )


def test_sub_sample_zoom_drops_raster_before_settle(qapp):
    """The solid block is the transform-only pixmap, not the settled frame.

    Ctrl+wheel / box-zoom restarts the 100 ms quiet window on every notch,
    so the stretched CRC column is what the user actually stares at.
    """
    rows = _subsample_gap_rows()
    t = rows[0][2]
    canvas = _shown_canvas(qapp, rows)
    _force_ink_raster(canvas, "angle")
    before = canvas._dense_raster.entry_for("angle")
    assert before is not None and before.item.isVisible()

    lo, hi = _gap_xlim(t)
    canvas._primary_xaxis_ax.view_box.setXRange(lo, hi, padding=0)
    qapp.processEvents()

    assert canvas._refresh_timer.isActive()
    entry = canvas._dense_raster.entry_for("angle")
    assert entry is None or not entry.item.isVisible()


def test_raster_would_stretch_detects_sub_column_views():
    assert raster_would_stretch(40.0, 2e-6, 1200) is True
    assert raster_would_stretch(40.0, 2.0, 1200) is False
    assert raster_would_stretch(2.0, 2.0, 1200) is False
