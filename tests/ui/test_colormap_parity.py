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


def test_default_head_matches_all_resource_samples_and_legacy_stays_named():
    from mf4_analyzer.colormaps import DEFAULT_HEATMAP_CMAP, load_rgb_lut
    from mf4_analyzer.qt_analysis_shared import _GNUPLOT2_COLORMAP, _resolve_colormap

    assert DEFAULT_HEATMAP_CMAP == "tracelab.head-style.v1"
    assert _GNUPLOT2_COLORMAP.name == "gnuplot2"
    np.testing.assert_array_equal(
        _lut(_resolve_colormap(None))[:, :3], load_rgb_lut(DEFAULT_HEATMAP_CMAP),
    )


def test_resolver_does_not_share_mutable_colormap_arrays():
    from mf4_analyzer.colormaps import SUPPORTED_HEATMAP_COLORMAPS
    from mf4_analyzer.qt_analysis_shared import _resolve_colormap

    for ident in SUPPORTED_HEATMAP_COLORMAPS:
        before = _lut(_resolve_colormap(ident)).copy()
        changed = _resolve_colormap(ident)
        changed.color[:] = 0
        changed.pos[:] = 0
        np.testing.assert_array_equal(_lut(_resolve_colormap(ident)), before)


def test_unknown_warns_and_uses_legacy_not_new_default(caplog):
    from mf4_analyzer.qt_analysis_shared import _resolve_colormap

    with caplog.at_level("WARNING"):
        result = _resolve_colormap("missing-palette-parity-test")
    assert "missing-palette-parity-test" in caplog.text
    assert "gnuplot2" in caplog.text
    np.testing.assert_array_equal(_lut(result), _lut(_resolve_colormap("gnuplot2")))


def test_registered_resource_error_propagates(monkeypatch):
    from mf4_analyzer.colormaps import ColormapResourceError, DEFAULT_HEATMAP_CMAP
    import mf4_analyzer.qt_analysis_shared as shared
    import pytest

    def broken(_):
        raise ColormapResourceError("broken registered palette")

    monkeypatch.setattr(shared, "load_rgb_lut", broken)
    with pytest.raises(ColormapResourceError, match="broken registered palette"):
        shared._resolve_colormap(DEFAULT_HEATMAP_CMAP)


def test_head_intermediate_positions_and_endpoint_saturation():
    from mf4_analyzer.colormaps import DEFAULT_HEATMAP_CMAP, load_rgb_lut
    from mf4_analyzer.qt_analysis_shared import _resolve_colormap

    rgb = np.asarray(load_rgb_lut(DEFAULT_HEATMAP_CMAP), dtype=float)
    anchors = np.linspace(0.0, 1.0, 256)
    positions = np.concatenate(([-0.5], (anchors[:-1] + anchors[1:]) / 2, [1.5]))
    expected = np.column_stack([np.interp(positions, anchors, rgb[:, i]) for i in range(3)])
    actual = _resolve_colormap(DEFAULT_HEATMAP_CMAP).map(positions, mode=pg.ColorMap.FLOAT)
    np.testing.assert_allclose(actual[:, :3] * 255, expected, atol=1e-10)
    np.testing.assert_array_equal(actual[:, 3], 1.0)


def test_head_range_mapping_preserves_relative_colors():
    from mf4_analyzer.colormaps import DEFAULT_HEATMAP_CMAP
    from mf4_analyzer.qt_analysis_shared import _resolve_colormap

    cmap = _resolve_colormap(DEFAULT_HEATMAP_CMAP)
    fractions = np.array([-0.1, 0, 1 / 3, 0.5, 0.95, 1, 1.1])
    expected = cmap.map(fractions, mode=pg.ColorMap.FLOAT)
    for lo, hi in [(10, 40), (20, 50), (0, 50), (0.001, 0.03)]:
        values = lo + fractions * (hi - lo)
        np.testing.assert_allclose(cmap.map((values - lo) / (hi - lo), mode=pg.ColorMap.FLOAT), expected, atol=1e-12)
