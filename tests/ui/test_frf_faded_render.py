"""Low-trust styling must keep the interactive raster path inexpensive."""
from types import SimpleNamespace

import numpy as np
from PyQt5.QtCore import QPointF
from PyQt5.QtGui import QColor, QImage, QPainter

from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas


class _PaintCalls(QPainter):
    def __init__(self, image):
        super().__init__(image)
        self.line_calls = 0
        self.path_calls = 0

    def drawLines(self, *args):
        self.line_calls += 1
        return super().drawLines(*args)

    def drawPath(self, *args):
        self.path_calls += 1
        return super().drawPath(*args)


def _canvas(qtbot):
    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 700)
    canvas.set_result(SimpleNamespace(
        frequencies=np.arange(1., 10.),
        transfer=np.array([1.03, 1.03, 1.03, np.nan, 1.03, 1.03, 1.03, np.nan, 1.03], complex),
        coherence=np.array([.95, .95, .95, np.nan, .2, .2, .2, np.nan, .2]),
    ), {
        "frequency_scale": "linear", "magnitude_scale": "linear",
        "phase_mode": "wrapped", "fade_low_coherence": True,
    })
    return canvas


def test_faded_curves_paint_segments_without_joining_nan_gaps(qtbot):
    canvas = _canvas(qtbot)
    image = QImage(200, 100, QImage.Format_ARGB32)
    image.fill(QColor("white"))
    painter = _PaintCalls(image)
    painter.scale(15., 15.)
    try:
        for item in (canvas._magnitude_low_curve, canvas._phase_low_curve):
            item.curve.paint(painter, None, None)
        assert painter.line_calls == 2
        assert painter.path_calls == 0
    finally:
        painter.end()
    # No segment may bridge either missing-data gap.
    segments = canvas._magnitude_low_curve.curve._getLineSegments()[0]
    assert [(line.x1(), line.x2()) for line in segments] == [
        (1., 2.), (2., 3.), (5., 6.), (6., 7.),
    ]
    np.testing.assert_array_equal(canvas._magnitude_low_points.xData, [9.])


def test_faded_base_keeps_trusted_curve_visible_in_capture(qtbot):
    canvas = _canvas(qtbot)
    canvas.show()
    qtbot.wait(30)
    canvas.set_xlim(.5, 9.5)
    canvas.set_ylim("magnitude", .5, 1.5)
    canvas.disable_interactive_quality()
    image = canvas.grab_pixmap(scale=1.).toImage()
    dpr = image.devicePixelRatioF()

    def nearby_colors(x):
        scene = canvas._plot_magnitude.vb.mapViewToScene(QPointF(x, 1.03))
        position = canvas._glw.mapFromScene(scene)
        px, py = round(position.x() * dpr), round(position.y() * dpr)
        return {
            image.pixelColor(px + dx, py + dy).name()
            for dx in range(-2, 3) for dy in range(-2, 3)
        }

    assert "#1769e0" in nearby_colors(2.2)
    assert "#bfd6f6" in nearby_colors(6.2)
    # Singleton low-trust points use the same pale ink as the continuous run.
    assert canvas._magnitude_low_points.opts["symbolBrush"].color() == QColor("#bfd6f6")
