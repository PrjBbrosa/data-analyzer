"""Supersampled-export contracts for the Qt batch renderer.

Curves leave the builder aliased (see ``_builder``); the export pass is what
smooths them, by rendering the settled 1x scene onto an N x canvas and
filtering it back down. These tests pin the parts of that pass that are easy
to break silently: the scale-up of device-pixel state, the restoration of it,
and the metadata that has to survive the downscale.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtGui import QImage, QPainter
from PyQt5.QtWidgets import QGraphicsItem

from mf4_analyzer.batch_image_options import BatchRenderOptions
from mf4_analyzer.batch_render_qt import _export as qt_export
from mf4_analyzer.batch_render_qt._builder import build_batch_scene
from mf4_analyzer.batch_render_qt._export import (
    render_scene_image,
    supersample_factor,
)
from tools.verify_batch_qt_render_parity import _cases


ALL_CASES = {case.name: case for case in _cases()}
ONE_PER_KIND = (
    "time-subplot8",
    "fft-linear",
    "fft-time-linear-auto",
    "order-time-linear-manual",
)
IGNORES_TRANSFORMATIONS = (
    QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
)


def _open(case, *, width=960, height=640):
    return build_batch_scene(
        case.payload,
        params=case.params,
        options=BatchRenderOptions(width_px=width, height_px=height),
        context=case.context,
    )


def _pixels(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    ptr = converted.bits()
    ptr.setsize(converted.byteCount())
    return np.frombuffer(ptr, dtype=np.uint8).reshape(
        converted.height(), converted.width(), 4
    ).copy()


def _force_factor(monkeypatch, factor: int) -> None:
    monkeypatch.setattr(
        qt_export, "supersample_factor", lambda width, height: factor
    )


def _ink_pixels(image: QImage, background) -> int:
    pixels = _pixels(image)[..., :3].astype(np.int16)
    reference = np.array(
        [background.red(), background.green(), background.blue()]
    )
    return int(np.count_nonzero(np.abs(pixels - reference).max(axis=2) > 60))


def test_supersample_factor_clamps_to_qimage_and_memory_limits():
    # Ordinary report sizes get the full factor.
    assert supersample_factor(1920, 1080) == 3
    assert supersample_factor(3840, 2160) == 3
    # 8K would exceed the pixel budget at 3x but fits at 2x.
    assert supersample_factor(7680, 4320) == 2
    # A square page at the option ceiling has to fall back to no supersampling
    # rather than building a canvas QImage would reject.
    assert supersample_factor(16_384, 16_384) == 1
    # The per-side limit alone is enough to pull the factor down.
    assert supersample_factor(16_000, 320) == 2


@pytest.mark.parametrize("name", ONE_PER_KIND)
def test_one_to_one_render_matches_the_widget_render_primitive(
    qapp, monkeypatch, name
):
    """QGraphicsScene.render() at 1:1 reproduces the old widget.render() page.

    The exporter swapped primitives to gain a scalable target rect. At factor
    1 the two have to agree pixel for pixel, or the swap moved the layout.
    """
    _force_factor(monkeypatch, 1)
    scene = _open(ALL_CASES[name])
    try:
        image = render_scene_image(scene)

        reference = QImage(960, 640, QImage.Format_ARGB32_Premultiplied)
        reference.fill(scene.theme.background)
        painter = QPainter(reference)
        painter.setRenderHints(
            QPainter.Antialiasing | QPainter.TextAntialiasing
        )
        scene.widget.render(painter)
        painter.end()

        assert np.array_equal(_pixels(image), _pixels(reference))
    finally:
        scene.close()


@pytest.mark.parametrize("name", ONE_PER_KIND)
def test_export_restores_the_device_pixel_state_it_scales_up(qapp, name):
    """Pens and transform flags are mutated in place and must be put back.

    A pass that skipped the restore would compound on the next export, so the
    check is on the live scene objects rather than on pixels. Pens are
    compared by value, not identity: pyqtgraph rebuilds a curve's pen through
    mkPen whenever setData runs, which settling may legitimately do.
    """
    def pen_value(pen):
        return pen.widthF(), pen.color().name(), pen.style(), pen.isCosmetic()

    scene = _open(ALL_CASES[name])
    try:
        scene.show_and_settle()
        items = list(scene.widget.scene().items())
        curve_pens = [
            (item, pen_value(item.opts["pen"]))
            for item in items
            if isinstance(getattr(item, "opts", None), dict)
            and hasattr(item.opts.get("pen"), "widthF")
        ]
        # AxisItem.pen() answers with a copy, so widths are the observable.
        axis_widths = [
            (item, item.pen().widthF())
            for item in items
            if isinstance(item, pg.AxisItem)
        ]
        flags = [
            (item, bool(item.flags() & IGNORES_TRANSFORMATIONS))
            for item in items
        ]
        assert axis_widths, "every report kind draws axes"

        render_scene_image(scene)

        for item, value in curve_pens:
            assert pen_value(item.opts["pen"]) == value
        for item, width in axis_widths:
            assert item.pen().widthF() == pytest.approx(width)
        for item, flagged in flags:
            assert bool(item.flags() & IGNORES_TRANSFORMATIONS) is flagged
    finally:
        scene.close()


@pytest.mark.parametrize("name", ONE_PER_KIND)
def test_repeated_exports_do_not_compound_the_scaled_pens(qapp, name):
    """Ink stays put across exports; a missed restore would multiply it.

    Byte equality against the *first* image is deliberately not asserted: the
    first paint of a fresh scene warms lazy pyqtgraph caches and already
    differed from later ones before this export path existed. What must hold
    is that nothing grows — a pass that left pens widened would render the
    next one three times heavier again — and that the scene has reached a
    steady state by the second export.
    """
    scene = _open(ALL_CASES[name])
    try:
        images = [render_scene_image(scene) for _ in range(3)]
        counts = [_ink_pixels(image, scene.theme.background) for image in images]
        assert counts[0] > 0
        for count in counts[1:]:
            assert count == pytest.approx(counts[0], rel=0.10)
        assert np.array_equal(_pixels(images[1]), _pixels(images[2]))
    finally:
        scene.close()


def test_supersampling_replaces_hard_strokes_with_blended_ones(
    qapp, monkeypatch
):
    """The visible point of the pass: edges stop being flat pen colour.

    An aliased stroke is pen colour or nothing. Supersampling filters it down
    into a band of blends, so the count of pixels sitting at the exact pen
    colour collapses while the stroke keeps its weight.
    """
    case = ALL_CASES["fft-linear"]

    def measure(factor: int) -> tuple[int, int]:
        _force_factor(monkeypatch, factor)
        scene = _open(case)
        try:
            image = render_scene_image(scene)
            pen = scene.curves[0].opts["pen"].color()
            pen_rgb = np.array([pen.red(), pen.green(), pen.blue()])
            pixels = _pixels(image)[..., :3].astype(np.int16)
            distance = np.abs(pixels - pen_rgb).max(axis=2)
            solid = int(np.count_nonzero(distance <= 20))
            stroke = int(np.count_nonzero(distance <= 160))
            return solid, stroke
        finally:
            scene.close()

    aliased_solid, aliased_stroke = measure(1)
    smoothed_solid, smoothed_stroke = measure(3)

    assert aliased_solid > 0
    # Most of what was flat pen colour is now a blend.
    assert smoothed_solid < aliased_solid * 0.7
    # ...without the stroke losing weight: this is smoothing, not thinning.
    assert smoothed_stroke == pytest.approx(aliased_stroke, rel=0.10)


def test_legend_keeps_its_one_to_one_size_through_the_downscale(
    qapp, monkeypatch
):
    """LegendItem sets ItemIgnoresTransformations and would render 1/factor.

    Qt honours that flag against the painter's world transform, so on the
    supersampled canvas the legend would be drawn at its 1x device size and
    then shrunk by the downscale — measured at roughly a quarter of its ink
    before the export learned to clear the flag.
    """
    case = ALL_CASES["fft-linear"]

    def legend_ink(factor: int) -> int:
        _force_factor(monkeypatch, factor)
        scene = _open(case)
        try:
            image = render_scene_image(scene)
            assert scene.legend is not None
            # Inset by a pixel so the legend's own border stays out of it.
            rect = scene.legend.sceneBoundingRect()
            patch = image.copy(
                int(rect.left()) + 1,
                int(rect.top()) + 1,
                int(rect.width()) - 2,
                int(rect.height()) - 2,
            )
            return _ink_pixels(patch, scene.theme.background)
        finally:
            scene.close()

    one_to_one = legend_ink(1)
    supersampled = legend_ink(3)
    assert one_to_one > 100
    assert supersampled == pytest.approx(one_to_one, rel=0.10)


def test_export_metadata_and_resolution_survive_the_downscale(qapp, tmp_path):
    scene = _open(ALL_CASES["time-subplot8"], width=1920, height=1080)
    try:
        assert qt_export.supersample_factor(1920, 1080) > 1
        image = render_scene_image(scene, metadata={"Title": "batch page"})
        assert image.size().width() == 1920
        assert image.size().height() == 1080
        assert image.text("Title") == "batch page"
        expected_dpm = round(144 / 0.0254)
        assert image.dotsPerMeterX() == expected_dpm
        assert image.dotsPerMeterY() == expected_dpm

        target = tmp_path / "ssaa.png"
        assert image.save(str(target), "PNG")
        reloaded = QImage(str(target))
        assert reloaded.text("Title") == "batch page"
        assert reloaded.dotsPerMeterX() == expected_dpm
    finally:
        scene.close()


def test_prepared_pass_scales_pens_without_moving_the_plot_geometry(qapp):
    """Widening pens inflates bounding rects; it must not move the layout."""
    scene = _open(ALL_CASES["time-subplot8"])
    try:
        scene.show_and_settle()
        before_rects = [p.vb.sceneBoundingRect() for p in scene.plots]
        before_ranges = [
            tuple(map(tuple, p.vb.viewRange())) for p in scene.plots
        ]
        curve_pen = scene.curves[0].opts["pen"]
        original_width = curve_pen.widthF()

        graphics_scene = scene.widget.scene()
        with qt_export._prepared_for_supersampling(graphics_scene, 3):
            assert scene.curves[0].opts["pen"].widthF() == pytest.approx(
                original_width * 3
            )
            assert [
                p.vb.sceneBoundingRect() for p in scene.plots
            ] == before_rects
            assert [
                tuple(map(tuple, p.vb.viewRange())) for p in scene.plots
            ] == before_ranges

        assert scene.curves[0].opts["pen"] is curve_pen
        assert [p.vb.sceneBoundingRect() for p in scene.plots] == before_rects
        assert [
            tuple(map(tuple, p.vb.viewRange())) for p in scene.plots
        ] == before_ranges
    finally:
        scene.close()
