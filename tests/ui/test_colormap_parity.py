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
        _lut(_resolve_colormap("not-a-real-map")), _lut(pg.colormap.get("viridis"))
    )


def test_resolve_colormap_does_not_call_matplotlib():
    import inspect

    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _resolve_colormap

    assert "getFromMatplotlib" not in inspect.getsource(_resolve_colormap)
