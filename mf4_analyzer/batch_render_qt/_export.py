"""Exact-pixel QImage rendering and PNG encoding."""
from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from pathlib import Path

import pyqtgraph as pg
from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QImage, QPainter

from ._builder import BuiltBatchScene


# Curves are built with pyqtgraph's native antialiasing off (see _builder);
# supersampling the whole scene and filtering it back down is the export's
# only smoothing mechanism. Its cost is a pure function of output area, where
# native antialiasing costs whatever the samples happen to look like: it drops
# PlotCurveItem's drawLines fast path for a full QPainterPath composite, which
# measured 15x slower than this on a five-panel channel-vs-channel page.
_SSAA_FACTOR = 3
# QImage rejects sides past 32767 px; leave room for the layout's own rounding.
_SSAA_MAX_SIDE_PX = 32_000
# 160 MP of ARGB32 scratch is ~640 MB. 3x FHD is 18.7 MP, 3x 4K is 74.6 MP.
_SSAA_MAX_PIXELS = 160_000_000

_PEN_OPT_KEYS = ("pen", "shadowPen", "symbolPen")


def supersample_factor(width_px: int, height_px: int) -> int:
    """Largest supersampling factor the scratch canvas can still hold.

    Falls back to 1 (no antialiasing, matching the pre-supersampling export)
    rather than failing, so an extreme image size stays renderable.
    """
    for factor in range(_SSAA_FACTOR, 1, -1):
        if (
            width_px * factor <= _SSAA_MAX_SIDE_PX
            and height_px * factor <= _SSAA_MAX_SIDE_PX
            and width_px * height_px * factor * factor <= _SSAA_MAX_PIXELS
        ):
            return factor
    return 1


def _scalable_pen(pen) -> bool:
    # opts entries are colour specs as often as they are QPens.
    return pen is not None and hasattr(pen, "isCosmetic") and pen.isCosmetic()


def _widened(pen, factor: int):
    widened = pg.mkPen(pen)
    # Hairline pens (width 0) already rasterize one device pixel wide.
    widened.setWidthF(max(pen.widthF(), 1.0) * factor)
    return widened


@contextmanager
def _prepared_for_supersampling(graphics_scene, factor: int):
    """Make one supersampled pass render like a scaled-up 1x page.

    Two families of scene state are pinned to device pixels and would
    otherwise survive the scale-up unchanged, only to be shrunk by the
    downscale that follows:

    * **Cosmetic pens.** ``pg.mkPen`` defaults to cosmetic, so pen widths are
      device pixels and ignore the source->target transform of
      ``QGraphicsScene.render()``; every stroke would come back
      ``1/factor`` as wide. pyqtgraph's own ``resolutionScale`` export hook
      is no help — only ScatterPlotItem reads it.
    * **Transform-ignoring items.** ``LegendItem`` (and pyqtgraph's native
      auto-range button) set ``ItemIgnoresTransformations`` to stay
      screen-sized. Clearing the flag lets the painter scale them like
      everything else; their geometry is already in view-pixel coordinates,
      and their anchored scene position does not depend on the flag.

    Restoring matters as much as scaling up: callers render the same settled
    scene more than once (the parity guards do), and a scene left scaled
    would compound on the next pass.
    """
    if factor == 1:
        yield
        return
    restores = []
    ignores_transformations = (
        pg.QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    )
    for item in graphics_scene.items():
        touched = False
        opts = getattr(item, "opts", None)
        if isinstance(opts, dict):
            for key in _PEN_OPT_KEYS:
                pen = opts.get(key)
                if _scalable_pen(pen):
                    restores.append(partial(opts.__setitem__, key, pen))
                    opts[key] = _widened(pen, factor)
                    touched = True
        if isinstance(item, pg.AxisItem):
            # Grid lines derive from the axis pen, so this covers them too.
            pen = item.pen()
            if _scalable_pen(pen):
                restores.append(partial(item.setPen, pen))
                item.setPen(_widened(pen, factor))
                touched = True
        elif isinstance(item, pg.ViewBox):
            pen = item.border
            if _scalable_pen(pen):
                restores.append(partial(item.setBorder, pen))
                item.setBorder(_widened(pen, factor))
                touched = True
        if item.flags() & ignores_transformations:
            restores.append(partial(item.setFlag, ignores_transformations, True))
            item.setFlag(ignores_transformations, False)
            touched = True
        if touched:
            item.update()
    try:
        yield
    finally:
        for restore in reversed(restores):
            restore()


def render_scene_image(
    scene: BuiltBatchScene, *, metadata: dict[str, str] | None = None
) -> QImage:
    """Render one settled scene at the option's authoritative pixel size."""

    scene.show_and_settle()
    width = scene.options.width_px
    height = scene.options.height_px
    factor = supersample_factor(width, height)
    canvas = QImage(
        width * factor,
        height * factor,
        QImage.Format_ARGB32_Premultiplied,
    )
    if canvas.isNull():
        raise RuntimeError("batch renderer created a null QImage")
    # The view's background brush belongs to the widget, not the scene, so the
    # fill below is what puts it on the canvas.
    canvas.fill(scene.theme.background)
    graphics_scene = scene.widget.scene()
    painter = QPainter(canvas)
    try:
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        with _prepared_for_supersampling(graphics_scene, factor):
            graphics_scene.render(
                painter,
                QRectF(0, 0, width * factor, height * factor),
                QRectF(0, 0, width, height),
            )
    finally:
        painter.end()
    image = canvas if factor == 1 else canvas.scaled(
        width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation
    )
    # Both of these belong on the delivered image: QImage.scaled() carries no
    # text keys across, and AxisItem records its paint commands at the active
    # paint-device DPI, so PNG resolution metadata has to land after drawing
    # for the QPicture to use the same logical DPI as the on-screen plot.
    for key, value in dict(metadata or {}).items():
        image.setText(str(key), str(value))
    image.setDotsPerMeterX(round(scene.options.dpi / 0.0254))
    image.setDotsPerMeterY(round(scene.options.dpi / 0.0254))
    return image


def save_png(image: QImage, path) -> Path:
    target = Path(path)
    if image.isNull():
        raise RuntimeError("cannot save a null QImage")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(target), "PNG"):
        raise RuntimeError(f"failed to write batch PNG: {target}")
    return target


__all__ = ["render_scene_image", "save_png", "supersample_factor"]
