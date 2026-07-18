from pathlib import Path

import numpy as np
import pyqtgraph as pg


NAMES = ("turbo", "viridis")
GOLDEN = Path(__file__).resolve().parents[1] / "data" / "colormap_golden.npz"


def _lut(cm):
    return cm.getLookupTable(0.0, 1.0, 256, alpha=True)


def test_native_colormaps_match_golden_lut():
    golden = np.load(GOLDEN)
    for name in NAMES:
        native = pg.colormap.get(name)
        assert native is not None
        np.testing.assert_array_equal(_lut(native), golden[name])


def test_resolve_colormap_uses_native_and_falls_back():
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _resolve_colormap

    np.testing.assert_array_equal(
        _lut(_resolve_colormap("turbo")), _lut(pg.colormap.get("turbo"))
    )
    np.testing.assert_array_equal(
        _lut(_resolve_colormap("viridis")), _lut(pg.colormap.get("viridis"))
    )
    np.testing.assert_array_equal(
        _lut(_resolve_colormap("not-a-real-map")), _lut(_resolve_colormap("gnuplot2"))
    )


def test_gnuplot2_matches_matplotlib_transfer_function_without_runtime_import():
    """Pin representative entries of Matplotlib's built-in gnuplot2 LUT."""
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _resolve_colormap

    lut = _lut(_resolve_colormap("gnuplot2"))
    np.testing.assert_array_equal(
        lut[[0, 1, 64, 128, 192, 255]],
        np.array([
            [0, 0, 0, 255],
            [0, 0, 4, 255],
            [1, 0, 255, 255],
            [201, 42, 213, 255],
            [255, 170, 85, 255],
            [255, 255, 255, 255],
        ], dtype=np.ubyte),
    )


def test_resolve_colormap_does_not_import_matplotlib():
    import inspect

    import mf4_analyzer.ui.pg_canvas.heatmap_canvas as heatmap_canvas

    source = inspect.getsource(heatmap_canvas)
    assert "import matplotlib" not in source.lower()
    assert "getFromMatplotlib" not in source
