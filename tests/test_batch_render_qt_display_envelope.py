from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_qt import (
    BatchRenderContext,
    BatchSeries,
    BatchTimeFigureSpec,
)
from mf4_analyzer.batch_render_qt import _builder
from mf4_analyzer.signal._envelope_cutils import positions_envelope as real_envelope


def _context() -> BatchRenderContext:
    return BatchRenderContext(channel="dense time channel", unit="g", method="time")


def _dense_series(*, count: int = 2, dual_y: bool = False, panels: bool = False):
    x = np.linspace(11.0, 21.0, 60_000, dtype=np.float64)
    items = []
    for index in range(count):
        y = np.where(np.arange(x.size) % 2, 255.0, 0.0)
        y = y + index
        y[1234] = 999.0 + index
        y[4321] = -888.0 - index
        items.append(
            BatchSeries(
                x=x.copy(),
                y=y,
                label=f"dense-{index}",
                unit="rpm" if dual_y and index % 2 else "g",
                panel=index if panels else 0,
            )
        )
    return tuple(items)


@pytest.mark.parametrize(
    ("layout", "dual_y", "x_source"),
    [
        ("overlay", False, "time"),
        ("overlay", True, "time"),
        ("subplot", False, "time"),
        ("overlay", False, "channel"),
    ],
)
def test_time_display_envelope_uses_real_view_width_across_layouts(
    qapp, monkeypatch, layout, dual_y, x_source
):
    calls = []

    def envelope_spy(t, sig, **kwargs):
        calls.append((np.asarray(t), np.asarray(sig), dict(kwargs)))
        return real_envelope(t, sig, **kwargs)

    monkeypatch.setattr(_builder, "positions_envelope", envelope_spy)
    series = _dense_series(dual_y=dual_y, panels=layout == "subplot")
    raw_before = tuple((item.x.copy(), item.y.copy()) for item in series)
    spec = BatchTimeFigureSpec(
        series,
        layout=layout,
        x_source=x_source,
        x_origin="absolute" if x_source == "channel" else "zero",
        x_label="Rack position (mm)" if x_source == "channel" else "Time (s)",
        panel_titles=("first", "second") if layout == "subplot" else (),
    )
    scene = _builder.build_batch_scene(
        ("time", spec),
        options=BatchRenderOptions(width_px=1920, height_px=1080),
        context=_context(),
    )
    try:
        scene.show_and_settle()
        qapp.processEvents()

        assert len(calls) == len(series)
        assert len(scene.curves) == len(series)
        for index, (curve, item, call) in enumerate(zip(scene.curves, series, calls)):
            display_x, display_y = curve.getData()
            call_x, call_y, kwargs = call
            plot = scene.plots[index] if layout == "subplot" else scene.plots[0]
            actual_width = max(1, int(round(plot.vb.sceneBoundingRect().width())))

            assert 1 <= kwargs["pixel_width"] <= actual_width
            assert kwargs["pixel_width"] == min(actual_width, 350)
            assert kwargs["xlim"] == pytest.approx(tuple(plot.vb.viewRange()[0]))
            assert len(display_x) <= 2 * actual_width
            assert np.min(display_y) == pytest.approx(np.min(item.y))
            assert np.max(display_y) == pytest.approx(np.max(item.y))
            expected_call_x = (
                item.x if x_source == "channel" else item.x - item.x[0]
            )
            assert np.array_equal(call_x, expected_call_x)
            assert np.shares_memory(call_y, item.y)
            assert curve.opts["antialias"] is False
            assert np.array_equal(item.x, raw_before[index][0])
            assert np.array_equal(item.y, raw_before[index][1])
        if x_source == "channel":
            assert scene.plots[0].getAxis("bottom").labelText == "Rack position (mm)"
            assert scene.curves[0].getData()[0][0] >= 11.0
    finally:
        scene.close()


def test_time_display_envelope_preserves_nan_and_nonmonotonic_fallbacks(qapp):
    monotonic_x = np.linspace(0.0, 1.0, 20_000, dtype=np.float64)
    nan_y = np.sin(monotonic_x * 40.0)
    nan_y[5000] = np.nan
    nan_y[6000] = 50.0
    nonmonotonic_x = monotonic_x.copy()
    nonmonotonic_x[10_000], nonmonotonic_x[10_001] = (
        nonmonotonic_x[10_001],
        nonmonotonic_x[10_000],
    )
    nonmonotonic_y = np.cos(monotonic_x * 20.0)
    spec = BatchTimeFigureSpec(
        (
            BatchSeries(monotonic_x, nan_y, "nan", panel=0),
            BatchSeries(nonmonotonic_x, nonmonotonic_y, "nonmonotonic", panel=1),
        ),
        layout="subplot",
        x_source="channel",
        x_origin="absolute",
        panel_titles=("nan", "nonmonotonic"),
    )
    scene = _builder.build_batch_scene(
        ("time", spec),
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=_context(),
    )
    try:
        scene.show_and_settle()
        qapp.processEvents()
        displayed_nan_x, displayed_nan = scene.curves[0].getData()
        displayed_nonmonotonic_x, displayed_nonmonotonic_y = scene.curves[1].getData()

        nan_width = max(
            1, int(round(scene.plots[0].vb.sceneBoundingRect().width()))
        )
        nonmonotonic_width = max(
            1, int(round(scene.plots[1].vb.sceneBoundingRect().width()))
        )
        expected_nan_x, expected_nan_y = real_envelope(
            monotonic_x,
            nan_y,
            xlim=tuple(scene.plots[0].vb.viewRange()[0]),
            pixel_width=nan_width,
            is_monotonic=True,
        )
        expected_nonmonotonic_x, expected_nonmonotonic_y = real_envelope(
            nonmonotonic_x,
            nonmonotonic_y,
            xlim=tuple(scene.plots[1].vb.viewRange()[0]),
            pixel_width=nonmonotonic_width,
            is_monotonic=False,
        )
        assert np.array_equal(displayed_nan_x, expected_nan_x, equal_nan=True)
        assert np.array_equal(displayed_nan, expected_nan_y, equal_nan=True)
        assert np.nanmax(displayed_nan) == pytest.approx(50.0)
        assert np.array_equal(
            displayed_nonmonotonic_x, expected_nonmonotonic_x, equal_nan=True
        )
        assert np.array_equal(
            displayed_nonmonotonic_y, expected_nonmonotonic_y, equal_nan=True
        )
    finally:
        scene.close()


def test_general_time_curve_keeps_single_file_antialias_quality(qapp):
    x = np.linspace(0.0, 1.0, 60_000, dtype=np.float64)
    y = np.sin(2.0 * np.pi * 3.25 * x)
    spec = BatchTimeFigureSpec((BatchSeries(x, y, "smooth", unit="g"),))
    scene = _builder.build_batch_scene(
        ("time", spec),
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=_context(),
    )
    try:
        scene.show_and_settle()
        qapp.processEvents()
        assert scene.curves[0].opts["antialias"] is True
        assert len(scene.curves[0].getData()[0]) < x.size
    finally:
        scene.close()


def test_high_raster_cost_general_profile_disables_native_antialias(qapp):
    x = np.linspace(0.0, 1.0, 60_000, dtype=np.float64)
    y = ((np.arange(x.size, dtype=np.int64) * 997) % 1476) / 3.0
    spec = BatchTimeFigureSpec((BatchSeries(x, y, "dynamic", unit="deg/s"),))
    scene = _builder.build_batch_scene(
        ("time", spec),
        options=BatchRenderOptions(width_px=1920, height_px=1080),
        context=_context(),
    )
    try:
        scene.show_and_settle()
        assert scene._time_curve_bindings[0].profile.strategy == "general"
        assert scene.curves[0].opts["antialias"] is False
        assert len(scene.curves[0].getData()[0]) < x.size
    finally:
        scene.close()


def test_show_and_settle_uses_one_layout_and_paint_event_drain(qapp, monkeypatch):
    x = np.linspace(0.0, 1.0, 1000, dtype=np.float64)
    spec = BatchTimeFigureSpec((BatchSeries(x, np.sin(x), "smooth"),))
    scene = _builder.build_batch_scene(
        ("time", spec),
        options=BatchRenderOptions(width_px=960, height_px=640),
        context=_context(),
    )
    real_app = qapp
    calls = []

    class _AppProxy:
        def processEvents(self):
            calls.append("drain")
            real_app.processEvents()

    class _ApplicationProxy:
        @staticmethod
        def instance():
            return _AppProxy()

    monkeypatch.setattr(_builder, "QApplication", _ApplicationProxy)
    try:
        scene.show_and_settle()
        assert calls == ["drain"]
    finally:
        scene.close()
