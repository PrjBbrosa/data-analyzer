"""PgHeatmapCanvas: levels/extent math + API-parity tests (offscreen)."""
import numpy as np
import pytest

from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas


@pytest.fixture
def canvas(qapp):
    c = PgHeatmapCanvas()
    c.resize(640, 480)
    yield c
    c.deleteLater()


def _mat():
    # 4 rows (Y) x 5 cols (X), peak = 100 at [2, 3]
    m = np.ones((4, 5))
    m[2, 3] = 100.0
    return m


def test_linear_mode_levels_auto(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    lo, hi = canvas._img.getLevels()
    assert lo == pytest.approx(1.0) and hi == pytest.approx(100.0)


def test_db_mode_manual_levels_clip(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude_db', z_auto=False,
        z_floor=-30.0, z_ceiling=0.0,
    )
    lo, hi = canvas._img.getLevels()
    assert (lo, hi) == (-30.0, 0.0)
    # ref = peak → peak cell is 0 dB; ones are 20log10(1/100) = -40 → clipped to -30
    img = canvas._img.image
    assert img.max() == pytest.approx(0.0)
    assert img.min() == pytest.approx(-30.0)


def test_image_rect_matches_extents(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(2.0, 12.0), y_extent=(1.0, 9.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    r = canvas._img.boundingRect()
    mapped = canvas._img.mapRectToParent(r)
    assert mapped.left() == pytest.approx(2.0)
    assert mapped.right() == pytest.approx(12.0)
    assert mapped.top() == pytest.approx(1.0)
    assert mapped.bottom() == pytest.approx(9.0)


def test_has_result_lifecycle(canvas):
    assert not canvas.has_result()
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 1.0), y_extent=(0.0, 1.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert canvas.has_result()


def test_manual_axis_ranges(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
        x_auto=False, x_min=1.0, x_max=5.0,
        y_auto=False, y_min=2.0, y_max=6.0,
    )
    (x0, x1), (y0, y1) = canvas._plot.vb.viewRange()
    assert (x0, x1) == (pytest.approx(1.0), pytest.approx(5.0))
    assert (y0, y1) == (pytest.approx(2.0), pytest.approx(6.0))


def test_update_path_reuses_colorbar_and_relabels_left_axis(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
        cmap='turbo', cbar_label='Amplitude',
    )
    first_cbar = canvas._cbar
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
        cmap='viridis', cbar_label='Order Amp',
    )
    assert canvas._cbar is first_cbar  # reused, not rebuilt
    # Vertical ColorBarItem applies ``label=`` to the LEFT axis
    # (pg 0.14.0 ColorBarItem.__init__:143); the right axis only
    # carries tick values.
    assert canvas._cbar.getAxis('left').labelText == 'Order Amp'


def test_set_tick_density_accepts_inspector_counts(canvas):
    # Inspector PersistentTop passes integer tick COUNTS (x spinbox
    # 3-30, y spinbox 3-20; defaults 10/8) — the same values the mpl
    # canvases fed into MaxNLocator(nbins=...). NOT pg density factors.
    canvas.set_tick_density(10, 8)
    bottom = canvas._plot.getAxis('bottom')
    left = canvas._plot.getAxis('left')
    # Count->density convention from pg_canvas/tick_density.py
    # (x_n/10.0, y_n/6.0, clamped to [0.35, 3.0]).
    assert bottom._tickDensity == pytest.approx(10 / 10.0)
    assert left._tickDensity == pytest.approx(8 / 6.0)
    for density in (bottom._tickDensity, left._tickDensity):
        assert 0.35 <= density <= 3.0
        assert density != pytest.approx(3.0)  # default counts must not clamp


def test_set_tick_density_clamps_at_spinbox_maxima(canvas):
    # Spinbox maxima (30, 20) hit the density ceiling, never beyond it.
    canvas.set_tick_density(30, 20)
    assert canvas._plot.getAxis('bottom')._tickDensity == pytest.approx(3.0)
    assert canvas._plot.getAxis('left')._tickDensity == pytest.approx(3.0)


def test_db_mode_z_auto_defaults_true(canvas):
    # mpl original (canvases.py:2184) defaults z_auto=True; omitting it
    # must NOT clip the matrix to the (-30, 0) manual window.
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude_db',
    )
    lo, hi = canvas._img.getLevels()
    assert lo == pytest.approx(-40.0)  # 20*log10(1/100), unclipped
    assert hi == pytest.approx(0.0)


def test_colorbar_rounding_adapts_to_level_span(canvas):
    # Default ColorBarItem rounding=1 snaps drags to whole units and
    # enforces a minimum 1-unit span — unusable when the full linear
    # span is 0.5. Rounding must scale with the level span.
    m = np.linspace(0.0, 0.5, 20).reshape(4, 5)
    canvas.plot_or_update_heatmap(
        matrix=m, x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert canvas._cbar.rounding == pytest.approx(0.5 / 1000.0)
