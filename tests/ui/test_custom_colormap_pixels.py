"""Compare actual Qt raster bytes against independent registered RGB samples."""
from types import SimpleNamespace

import numpy as np
import pytest

from mf4_analyzer.colormaps import list_colormap_specs, load_rgb_lut


def _image_rows(item):
    item.render()
    image = item.qimage.copy()  # Own bytes; no dangling temporary QImage bits view.
    return [[image.pixelColor(x, 0).getRgb()[:3] for x in range(image.width())]]


@pytest.mark.parametrize("ident", [s.id for s in list_colormap_specs() if s.provider == "rgb_lut"])
@pytest.mark.parametrize("levels", [(10., 40.), (20., 50.), (0., 50.), (-60., -10.)])
@pytest.mark.parametrize("kind", ["fft_time", "order_time"])
def test_gui_batch_and_colorbar_raster_match_resource(qtbot, qapp, ident, levels, kind):
    from mf4_analyzer.batch_image_options import BatchRenderOptions
    from mf4_analyzer.batch_render_qt import BatchRenderContext
    from mf4_analyzer.batch_render_qt._builder import build_batch_scene
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas

    lo, hi = levels
    # Bin centers avoid floating boundary ambiguity. Also sample saturation on
    # both ends. Expected colors come from versioned bytes, not Qt's mapper.
    t = np.r_[-1., (np.arange(256) + .5) / 256, 2.]
    matrix = np.tile(lo + t * (hi - lo), (4, 1))
    original = matrix.copy()
    rgb = np.asarray(load_rgb_lut(ident))
    expected = np.vstack((rgb[0], rgb, rgb[-1]))[None, :, :]
    canvas = PgHeatmapCanvas(with_slice=False)
    qtbot.addWidget(canvas)
    canvas.plot_or_update_heatmap(matrix, (0., 258.), (0., 4.),
        cmap=ident, amplitude_mode="amplitude", z_auto=False,
        z_floor=lo, z_ceiling=hi)
    payload = SimpleNamespace(x=np.arange(258.), y=np.arange(4.),
        matrix=matrix.T.copy(), x_name="time_s",
        y_name="frequency_hz" if kind == "fft_time" else "order", metadata={})
    scene = build_batch_scene((kind, payload),
        params={"cmap": ident, "amplitude_mode": "amplitude", "z_auto": False,
                "z_floor": lo, "z_ceiling": hi},
        context=BatchRenderContext(source_display_name="Synthetic", channel="Ramp", unit="g",
                                   method=kind, task_id="colormap-pixel-probe"),
        options=BatchRenderOptions(width_px=960, height_px=640))
    try:
        for item in (canvas._img, scene.image_item):
            np.testing.assert_array_equal(_image_rows(item), expected)
        for colorbar in (canvas._cbar, scene.colorbar):
            image = colorbar.bar.pixmap().toImage().copy()
            actual = [image.pixelColor(0, y).getRgb()[:3] for y in range(image.height())]
            np.testing.assert_array_equal(actual, rgb)
        np.testing.assert_array_equal(matrix, original)
        np.testing.assert_array_equal(payload.matrix, original.T)
    finally:
        scene.close()
