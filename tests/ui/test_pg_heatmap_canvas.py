"""PgHeatmapCanvas: levels/extent math + API-parity tests (offscreen)."""
import numpy as np
import pytest
from PyQt5.QtCore import QPointF, Qt

from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas


class _FakeSceneClick:
    """Stand-in for a GraphicsScene MouseClickEvent (scenePos + button)."""

    def __init__(self, scene_pos, button):
        self._scene_pos = scene_pos
        self._button = button
        self.accepted = False

    def scenePos(self):
        return self._scene_pos

    def button(self):
        return self._button

    def accept(self):
        self.accepted = True


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


def test_remark_add_and_clear(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(5.0, 4.0)
    assert len(canvas._remarks) == 1
    # Label text carries the FULL (x, y, value) tuple: (5.0, 4.0) maps to
    # cell [row 2, col 2] = 1.0, all rendered via %.3g.
    assert canvas._remarks[0]['label'].toPlainText() == '(5, 4, 1)'
    # Dot color matches the time-domain annotation dots
    # (pg_canvas/annotations.py:221) and the mpl DANGER token
    # (canvases.py:34), not an ad hoc red.
    assert canvas._remarks[0]['dot'].opts['brush'].color().name() == '#dc2626'
    canvas.clear_remarks()
    assert canvas._remarks == []


def test_replot_clears_stale_remarks(canvas):
    # Unlike the mpl labels (x, y only), pg remark labels embed the z
    # value — surviving a replot would display stale data. The mpl
    # rebuild path (self.clear()) dropped annotations on every replot.
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(5.0, 4.0)
    assert canvas._remarks[0]['label'].toPlainText() == '(5, 4, 1)'
    canvas.plot_or_update_heatmap(
        matrix=_mat() * 7.0, x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    # Value at (5, 4) is now 7 — the retained label would still say 1.
    assert canvas._remarks == []


def test_right_click_on_colorbar_region_keeps_remarks(canvas, qapp):
    # ``insert_in`` puts the ColorBarItem inside the PlotItem layout, so
    # _plot.sceneBoundingRect() INCLUDES the colorbar column. A
    # remark-mode right-click there maps to view x beyond the heatmap
    # extent and must NOT delete the nearest remark.
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.show()
    qapp.processEvents()  # realize the GraphicsLayout geometry
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(5.0, 4.0)
    assert len(canvas._remarks) == 1
    # x=11 is outside extent (0, 10) but inside the plot's scene rect
    # (the colorbar column) — the precondition assert pins the scenario.
    sp = canvas._plot.vb.mapViewToScene(QPointF(11.0, 4.0))
    assert canvas._plot.sceneBoundingRect().contains(sp)
    canvas._on_scene_click(_FakeSceneClick(sp, Qt.RightButton))
    assert len(canvas._remarks) == 1
    canvas.hide()


def test_remove_remark_near_deletes_nearest(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(2.0, 2.0)
    canvas.add_remark_at(8.0, 6.0)
    canvas.remove_remark_near(7.5, 5.5)  # nearest is (8, 6)
    assert len(canvas._remarks) == 1
    xs, ys = canvas._remarks[0]['dot'].getData()
    assert (xs[0], ys[0]) == (pytest.approx(2.0), pytest.approx(2.0))


def test_remark_mode_gates_viewbox_menu(canvas):
    # Right-click delete only works because the ViewBox context menu is
    # suppressed while annotating (menuEnabled() is checked BEFORE the
    # menu is raised; sigMouseClicked fires too late to block it).
    canvas.set_remark_enabled(True)
    assert canvas._plot.vb.menuEnabled() is False
    canvas.set_remark_enabled(False)
    assert canvas._plot.vb.menuEnabled() is True


def test_remark_disabled_noop(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(False)
    canvas.add_remark_at(5.0, 4.0)
    assert canvas._remarks == []


def test_value_at_maps_extent_to_cell(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    # peak cell [row 2, col 3]: col 3 of 5 → x ∈ [6,8); row 2 of 4 → y ∈ [4,6)
    assert canvas._value_at(7.0, 5.0) == pytest.approx(100.0)


def test_grab_pixmap_scaled_nonnull(canvas, qapp):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    # Force a layout pass so the inner GraphicsLayoutWidget has real
    # geometry under offscreen Qt (same precedent as the time-domain
    # _pg_canvas helper, test_pg_timedomain_canvas.py:535).
    canvas.show()
    qapp.processEvents()
    pix = canvas.grab_pixmap(scale=2.0)
    assert pix is not None and not pix.isNull()
    assert pix.width() >= canvas.width() * 2 - 2
    canvas.hide()


def test_grab_pixmap_export_center_pixels_not_all_white(canvas, qapp):
    # This repo has an OpenGL all-white-export history (time-domain
    # canvas); export tests must verify PIXELS, not just geometry
    # (pattern: test_pg_timedomain_canvas.py:1228 writes the rendered
    # offscreen output to /tmp for human inspection).
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True, cmap='turbo',
    )
    canvas.show()
    qapp.processEvents()
    pix = canvas.grab_pixmap(scale=2.0)
    assert pix is not None and not pix.isNull()
    out_path = "/tmp/pg_heatmap_grab_pixmap.png"
    assert pix.save(out_path), f"failed to write screenshot to {out_path!r}"
    # The heatmap fill spans the plot area; sample a 3x3 grid around the
    # image center — at least one sample must be a non-white colormap
    # pixel (turbo's low end is dark blue, its peak red; the white
    # GraphicsLayoutWidget background would mean a blank export).
    img = pix.toImage()
    w, h = img.width(), img.height()
    samples = [
        img.pixelColor(int(w * fx), int(h * fy))
        for fx in (0.35, 0.45, 0.55)
        for fy in (0.35, 0.45, 0.55)
    ]
    assert any(
        (c.red(), c.green(), c.blue()) != (255, 255, 255) for c in samples
    ), "center region of the exported heatmap is all white"
    canvas.hide()


def test_grab_pixmap_degenerate_fallback_is_unscaled_1x1(canvas, monkeypatch):
    # Lesson 2026-04-25-tightbbox-survives-offscreen-qt: the 1x1
    # degenerate fallback must stay 1x1 regardless of requested scale
    # (precedent: test_hidpi_grab_preserves_offscreen_fallback,
    # test_pg_timedomain_canvas.py:4301 — force grab() null).
    from PyQt5.QtGui import QPixmap

    monkeypatch.setattr(canvas._glw, "grab", lambda *a, **k: QPixmap())
    pix = canvas.grab_pixmap(scale=2.0)
    assert pix is not None
    assert not pix.isNull(), "fallback pixmap must not be null"
    assert (pix.width(), pix.height()) == (1, 1), (
        f"expected un-scaled 1x1 fallback, got {pix.width()}x{pix.height()}"
    )


def test_full_reset_clears_state(canvas):
    # File-close contract (ChartStack.full_reset_all): every trace of the
    # previous result must go — remarks, result flag, colorbar, matrix.
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at(5.0, 4.0)
    assert len(canvas._remarks) == 1  # precondition pins the scenario
    canvas.full_reset()
    assert canvas._remarks == []
    assert not canvas.has_result()
    assert canvas._cbar is None
    assert canvas._matrix_disp is None


def test_full_reset_then_replot_rebuilds_colorbar(canvas):
    # full_reset detaches the ColorBarItem from the host PlotItem's
    # QGraphicsGridLayout (pg 0.14.0 ColorBarItem.py:225 nests it via
    # ``insert_in.layout.addItem(self, 2, 5)``). This path couples to pg
    # internals, so pin the layout item count across reset+replot: a pg
    # upgrade that breaks the detach would leak an orphaned colorbar
    # column on every file-close/replot cycle.
    baseline = canvas._plot.layout.count()
    m1 = np.linspace(0.0, 10.0, 20).reshape(4, 5)
    canvas.plot_or_update_heatmap(
        matrix=m1, x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    lo, hi = canvas._img.getLevels()
    assert (lo, hi) == (pytest.approx(0.0), pytest.approx(10.0))
    assert canvas._plot.layout.count() == baseline + 1  # bar inserted
    canvas.full_reset()
    assert canvas._plot.layout.count() == baseline  # no orphan item left
    m2 = np.linspace(0.5, 4.5, 20).reshape(4, 5)
    canvas.plot_or_update_heatmap(
        matrix=m2, x_extent=(0.0, 5.0), y_extent=(0.0, 4.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert canvas._cbar is not None
    lo, hi = canvas._img.getLevels()
    assert (lo, hi) == (pytest.approx(0.5), pytest.approx(4.5))
    blo, bhi = canvas._cbar.levels()
    assert (blo, bhi) == (pytest.approx(lo), pytest.approx(hi))
    # Rebuilt bar occupies exactly one layout slot again — count is
    # restored, not accumulated.
    assert canvas._plot.layout.count() == baseline + 1


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
