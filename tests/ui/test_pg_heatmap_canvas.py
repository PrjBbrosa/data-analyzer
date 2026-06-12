"""PgHeatmapCanvas: levels/extent math + API-parity tests (offscreen)."""
import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import QPointF, Qt

from mf4_analyzer.ui.chart_stack import PgNavigationToolbar
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult


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


class _FakeMenuEvent:
    def __init__(self, accepted_item):
        self.acceptedItem = accepted_item

    def screenPos(self):
        return QPointF(0.0, 0.0)


class _FakeMouseModeController:
    def current_mouse_mode(self):
        return "pan"

    def set_pan_mode(self):
        pass

    def set_zoom_mode(self):
        pass


def _open_context_menu(view_box, monkeypatch):
    from PyQt5.QtWidgets import QMenu

    captured = {}

    def _fake_popup(self, *_args, **_kwargs):
        captured["menu"] = self

    monkeypatch.setattr(QMenu, "popup", _fake_popup, raising=True)
    view_box.raiseContextMenu(_FakeMenuEvent(view_box))
    return captured.get("menu")


def _menu_texts(menu):
    return [
        action.text().replace("&", "").strip()
        for action in menu.actions()
        if not action.isSeparator() and action.text().replace("&", "").strip()
    ]


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


def test_heatmap_hides_title_row_and_disables_axis_si_prefix(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        x_label='Frequency (Hz)', y_label='Order',
        title='Order · 3 条曲线',
        amplitude_mode='amplitude', z_auto=True,
    )

    assert not canvas._plot.titleLabel.isVisible()
    assert canvas._plot.titleLabel.maximumHeight() == 0
    assert canvas._plot.getAxis('left').autoSIPrefix is False
    assert canvas._plot.getAxis('bottom').autoSIPrefix is False


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


def test_interp_bilinear_enables_smooth_image_paint(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
        interp='bilinear',
    )
    assert canvas._img.smooth_transform_enabled() is True

    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
        interp='nearest',
    )
    assert canvas._img.smooth_transform_enabled() is False


def test_heatmap_default_interpolation_is_smooth(canvas):
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
    )

    assert canvas._img.smooth_transform_enabled() is True


def test_heatmap_context_menu_is_chinese_and_keeps_plot_options(canvas, monkeypatch):
    canvas.register_mouse_mode_controller(_FakeMouseModeController())
    canvas.plot_or_update_heatmap(
        matrix=_mat(),
        x_extent=(0.0, 10.0),
        y_extent=(0.0, 8.0),
        amplitude_mode='amplitude',
        z_auto=True,
    )

    menu = _open_context_menu(canvas._plot.vb, monkeypatch)

    assert menu is not None
    top = _menu_texts(menu)
    assert "绘图选项" in top
    assert "Plot Options" not in top
    assert "查看全部" in top
    assert "X 轴范围" in top
    assert "Y 轴范围" in top
    assert "网格" in top
    assert "Mouse Mode" not in top


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


@pytest.mark.parametrize("with_slice", [False, True])
def test_heatmap_plots_draw_full_neutral_axis_frame_without_viewbox_overlap(
    qapp, with_slice
):
    from mf4_analyzer.ui._axis_handle import (
        PG_AXIS_NEUTRAL_COLOR,
        PG_AXIS_NEUTRAL_WIDTH,
    )

    c = PgHeatmapCanvas(with_slice=with_slice)
    try:
        plots = [c._plot]
        if with_slice:
            plots.append(c._slice_plot)

        for plot in plots:
            assert getattr(plot.getViewBox(), "border", None) is None
            for side in ("left", "bottom", "top", "right"):
                axis = plot.getAxis(side)
                assert axis.pen().color().name().lower() == PG_AXIS_NEUTRAL_COLOR
                assert axis.pen().widthF() == pytest.approx(PG_AXIS_NEUTRAL_WIDTH)
            assert plot.getAxis("top").isVisible()
            assert plot.getAxis("right").isVisible()
            assert plot.getAxis("top").style.get("showValues") is False
            assert plot.getAxis("right").style.get("showValues") is False
            assert float(plot.getAxis("top").height()) <= 4.0
            assert float(plot.getAxis("right").width()) <= 4.0
    finally:
        c.deleteLater()


# ----------------------------------------------------------------------
# FFT-vs-Time slice row (with_slice=True). Task 7.
# ----------------------------------------------------------------------
def _spec_result():
    freqs = np.linspace(0, 500, 64)
    times = np.linspace(0, 2.0, 10)
    amp = np.random.RandomState(7).rand(64, 10).astype(np.float32) + 0.01
    return SpectrogramResult(
        times=times, frequencies=freqs, amplitude=amp,
        params=SpectrogramParams(fs=1000.0, nfft=128),
        channel_name='vib', unit='g', metadata={'frames': 10},
    )


def _make_spec(channel, amplitude):
    freqs = np.linspace(0, 500, 16)
    times = np.linspace(0, 1.0, 4)
    return SpectrogramResult(
        times=times, frequencies=freqs, amplitude=amplitude,
        params=SpectrogramParams(fs=1000.0, nfft=32),
        channel_name=channel, unit='g', metadata={'frames': 4},
    )


def test_db_memo_keys_on_epoch_token_not_id(qapp):
    """Regression for V7 commit 6d539d1c: the dB memo keys on a stamped
    monotonic epoch token, NOT ``id(result)``.

    After an ``AnalysisResultCache`` LRU eviction frees a SpectrogramResult,
    CPython can reuse that id() for the NEXT result; an ``id()``-keyed dB memo
    would then serve result A's dB matrix for result B (silent stale image).

    We make the bug DETERMINISTIC by simulating an id() collision directly:
    plot A (caches A's dB under A's token), then HAND-INJECT a fake cache
    entry keyed on A's ``id()`` (what the old code would have produced) and
    verify the current code does NOT read it for a distinct B — because B
    carries its own distinct epoch token. We also assert the two results get
    different tokens, which is the property the fix guarantees.
    """
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(320, 240)

    result_a = _make_spec('A', np.ones((16, 4), dtype=np.float32))
    c.plot_result(result_a, amplitude_mode='amplitude_db', z_auto=True)
    token_a = result_a._pg_db_epoch
    disp_a = c._matrix_disp.copy()

    # Result B: DIFFERENT amplitude (a ramp). Stamp B's token first so we can
    # assert it differs from A's even when their id()s would collide.
    ramp = np.tile(
        np.linspace(0.01, 100.0, 16, dtype=np.float32)[:, None], (1, 4))
    result_b = _make_spec('B', ramp)
    token_b = c._result_db_token(result_b)
    # The stamped tokens MUST differ — this is the whole fix. (Two live
    # objects always get distinct monotonic epoch tokens; an id()-keyed token
    # could collide once the first object is freed and its id() reused.)
    assert token_b != ('epoch', token_a), "epoch token collided"
    assert result_b._pg_db_epoch != token_a

    # Poison the memo with an entry keyed on result_b's CPython id() and a
    # dB ref of 1.0 — the exact shape the OLD ``(id(result), db_ref)`` key
    # produced. If the current memo still consulted id(), plotting B would
    # return this poisoned (A's flat) matrix instead of B's ramp.
    c._db_cache = ((('id', id(result_b)), 1.0), disp_a)
    c.plot_result(result_b, amplitude_mode='amplitude_db', z_auto=True)
    disp_b = c._matrix_disp.copy()

    # B's displayed dB matrix reflects B's ramp, not A's poisoned flat matrix.
    assert not np.allclose(disp_b, disp_a), (
        "B rendered A's stale dB matrix — id()-keyed memo bug regressed"
    )
    from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer
    expected_b = SpectrogramAnalyzer.amplitude_to_db(ramp, 1.0)
    np.testing.assert_allclose(disp_b, expected_b, rtol=1e-5)
    c.deleteLater()


def test_slice_updates_on_select(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=True, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0, y_auto=True, y_min=0.0, y_max=0.0,
    )
    c.select_time_index(3)
    xs, ys = c._slice_curve.getData()
    assert len(xs) == 64
    # slice shows the SAME display-space (dB) values as column 3
    expected = c._matrix_disp[:, 3]
    np.testing.assert_allclose(ys, expected, rtol=1e-6)
    c.deleteLater()


def test_plot_result_without_slice_flag_has_no_slice_row(qapp):
    c = PgHeatmapCanvas(with_slice=False)
    assert not hasattr(c, '_slice_curve') or c._slice_curve is None
    c.deleteLater()


def test_plot_result_defaults_to_smooth_image_paint(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    try:
        c.plot_result(_spec_result(), amplitude_mode='amplitude_db', cmap='turbo')

        assert c._img.smooth_transform_enabled() is True
    finally:
        c.deleteLater()


def test_plot_result_db_vmin_vmax_not_overridden_by_internal_auto(qapp):
    # The dB matrix + clip + levels are computed in plot_result; the
    # explicit vmin/vmax it hands to plot_or_update_heatmap must survive
    # (amplitude_mode='amplitude' + non-None vmin/vmax → no nanmin/nanmax
    # override). With z_auto=False the levels are exactly (z_floor,
    # z_ceiling), NOT the data's nanmin/nanmax.
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=False, z_floor=-60.0, z_ceiling=-3.0, freq_range=None,
    )
    lo, hi = c._img.getLevels()
    assert (lo, hi) == (pytest.approx(-60.0), pytest.approx(-3.0))
    # If plot_or_update_heatmap's linear branch had re-derived levels from
    # the display matrix (nanmin/nanmax), it would NOT equal the explicit
    # (-60, -3) window — confirm the two differ so the test bites.
    clipped = c._matrix_disp
    auto_lo, auto_hi = float(np.nanmin(clipped)), float(np.nanmax(clipped))
    assert (auto_lo, auto_hi) != (pytest.approx(-60.0), pytest.approx(-3.0))
    # The colorbar mirrors the same explicit window, not a re-derived one.
    blo, bhi = c._cbar.levels()
    assert (blo, bhi) == (pytest.approx(-60.0), pytest.approx(-3.0))
    c.deleteLater()


def test_left_click_selects_frame_when_remark_off(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(
        r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True,
    )
    # Click near the frame at ~1.11s. Avoid the exact midpoint between two
    # frames (1.0s), where 1px layout/frame changes can legitimately flip the
    # nearest-bin tie.
    click_t = float(r.times[5])
    sp = c._plot.vb.mapViewToScene(QPointF(click_t, 250.0))
    c._on_scene_click(_FakeSceneClick(sp, Qt.LeftButton))
    xs, ys = c._slice_curve.getData()
    expected_idx = int(np.argmin(np.abs(r.times - click_t)))
    np.testing.assert_allclose(ys, c._matrix_disp[:, expected_idx], rtol=1e-6)
    # Marker follows the selected time.
    assert c._slice_marker.value() == pytest.approx(float(r.times[expected_idx]))
    assert c._slice_marker.isVisible()
    c.hide()
    c.deleteLater()


def test_left_click_adds_remark_when_remark_on_not_slice(qapp):
    # When remark mode is on, left-click annotates (does NOT select a
    # frame); the two left-click behaviors are mutually exclusive.
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    # plot_result selected frame 0; record its slice for comparison.
    _, ys0 = c._slice_curve.getData()
    c.set_remark_enabled(True)
    sp = c._plot.vb.mapViewToScene(QPointF(1.0, 250.0))
    c._on_scene_click(_FakeSceneClick(sp, Qt.LeftButton))
    assert len(c._remarks) == 1  # annotated, not frame-selected
    _, ys1 = c._slice_curve.getData()
    np.testing.assert_allclose(ys1, ys0)  # slice unchanged
    c.hide()
    c.deleteLater()


def test_hover_emits_cursor_info(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    received = []
    c.cursor_info.connect(received.append)
    sp = c._plot.vb.mapViewToScene(QPointF(1.0, 250.0))
    c._on_scene_hover(sp)
    assert received, "hover over the map must emit cursor_info"
    assert received[-1].startswith('t=')
    assert 'Hz' in received[-1]
    c.hide()
    c.deleteLater()


def test_full_reset_clears_slice_state(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    assert c._slice_marker.isVisible()  # precondition
    c.full_reset()
    assert c._result is None
    assert c._db_cache is None
    assert not c._slice_marker.isVisible()
    xs, ys = c._slice_curve.getData()
    # cleared curve has no data
    assert xs is None or len(xs) == 0
    # slice widgets survive the reset (row not orphaned)
    assert c._slice_curve is not None and c._slice_plot is not None
    c.deleteLater()


def test_select_time_index_noop_without_slice(qapp):
    # Order mode (with_slice=False): select_time_index must be inert and
    # never build a slice row or marker.
    c = PgHeatmapCanvas(with_slice=False)
    c.select_time_index(2)  # no result, no slice → silent no-op
    assert c._slice_curve is None
    assert c._slice_plot is None
    assert c._slice_marker is None
    c.deleteLater()


def test_hover_db_mode_labels_value_db_not_channel_unit(qapp):
    # dB mode: _matrix_disp holds dB numbers, so the readout MUST label the
    # value 'dB' — labeling it the channel unit 'g' is a unit error. Parity
    # with SpectrogramCanvas._on_motion (canvases.py:2028).
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()  # unit='g'
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    received = []
    c.cursor_info.connect(received.append)
    sp = c._plot.vb.mapViewToScene(QPointF(1.0, 250.0))
    c._on_scene_hover(sp)
    assert received, "hover over the map must emit cursor_info"
    msg = received[-1]
    assert msg.endswith(' dB'), f"dB-mode readout must end with ' dB', got {msg!r}"
    # The channel unit 'g' must NOT trail the value in dB mode. Guard a
    # naive substring 'g' (which appears in any value via %.4g) by anchoring
    # on the trailing token only.
    assert not msg.endswith(' g'), f"dB-mode readout wrongly labeled 'g': {msg!r}"
    c.hide()
    c.deleteLater()


def test_hover_linear_mode_labels_value_channel_unit(qapp):
    # Linear mode: value is in the channel unit, so the readout trails the
    # result unit ('g'), NOT 'dB'.
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()  # unit='g'
    c.plot_result(r, amplitude_mode='amplitude', cmap='turbo', z_auto=True)
    received = []
    c.cursor_info.connect(received.append)
    sp = c._plot.vb.mapViewToScene(QPointF(1.0, 250.0))
    c._on_scene_hover(sp)
    assert received, "hover over the map must emit cursor_info"
    msg = received[-1]
    assert msg.endswith(' g'), f"linear-mode readout must trail 'g', got {msg!r}"
    assert ' dB' not in msg, f"linear-mode readout must not say 'dB': {msg!r}"
    c.hide()
    c.deleteLater()


def test_hover_and_remark_read_same_value_in_slice_mode(qapp):
    # Caliber unification (裁决 3): in with_slice mode the hover readout and
    # a placed remark must resolve the SAME cell value at the same
    # coordinate. Pick a boundary coordinate where floor-fraction and
    # argmin-nearest would otherwise disagree, so the test bites.
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    # Pick a frequency coordinate where the floor-fraction picker (extent
    # mapping) and the argmin-nearest picker (over result.frequencies)
    # DISAGREE, so a regression to a floor-fraction _value_at would make
    # this test fail. Search the bins for such a point and pin it.
    freqs = r.frequencies
    y0, y1 = float(freqs[0]), float(freqs[-1])
    rows = len(freqs)

    def _floor_row(yy):
        return min(int((yy - y0) / max(y1 - y0, 1e-12) * rows), rows - 1)

    x = float(r.times[3])
    y = None
    for k in range(1, rows - 1):
        cand = float(freqs[k]) + 0.45 * float(freqs[k + 1] - freqs[k])
        if _floor_row(cand) != int(np.argmin(np.abs(freqs - cand))):
            y = cand
            break
    assert y is not None, "no diverging coordinate found — test would not bite"
    assert _floor_row(y) != int(np.argmin(np.abs(freqs - y)))  # precondition
    # Hover value: parse the trailing numeric token of the cursor pill.
    received = []
    c.cursor_info.connect(received.append)
    sp = c._plot.vb.mapViewToScene(QPointF(x, y))
    c._on_scene_hover(sp)
    assert received
    hover_token = received[-1].rsplit('·', 1)[-1].strip().split()[0]
    # Remark value: _value_at is the remark取值器; it must agree with hover.
    remark_val = c._value_at(x, y)
    # The hover pill formats the value via %.4g; the remark reads the same
    # cell at full precision. Agreement means the remark value formats to the
    # identical %.4g token the hover emitted (same cell, not the same string
    # rounding artifact).
    assert f"{remark_val:.4g}" == hover_token, (
        f"hover token {hover_token!r} vs remark {remark_val} disagree on the cell"
    )
    # And both must equal the argmin-nearest cell in the display matrix.
    t_idx = int(np.argmin(np.abs(r.times - x)))
    f_idx = int(np.argmin(np.abs(r.frequencies - y)))
    assert remark_val == pytest.approx(float(c._matrix_disp[f_idx, t_idx]))
    c.hide()
    c.deleteLater()


def test_value_at_keeps_floor_fraction_in_order_mode(qapp):
    # Order mode (with_slice=False, no _result): _value_at MUST keep the
    # floor-fraction mapping. The caliber unification is scoped to slice
    # mode only — changing Order's picker would regress the existing Order
    # remark tests and silently shift Order annotation values.
    c = PgHeatmapCanvas(with_slice=False)
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    assert c._result is None  # precondition: Order mode never sets _result
    # (8.0, 6.0) is a boundary point: floor-fraction → cell [row 3, col 4]
    # = 1.0; argmin-nearest would round to the peak cell (100.0). The Order
    # picker must stay on floor-fraction.
    assert c._value_at(8.0, 6.0) == pytest.approx(1.0)
    c.deleteLater()


def test_slice_y_label_switches_with_amplitude_mode(qapp):
    # M1: the slice subplot's left (amplitude) axis must be labeled, and the
    # label switches dB vs linear with amplitude_mode (mpl _plot_slice,
    # canvases.py:1878-1880).
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    r = _spec_result()
    c.plot_result(r, amplitude_mode='amplitude_db', cmap='turbo', z_auto=True)
    assert c._slice_plot.getAxis('left').labelText == 'Amplitude (dB)'
    c.plot_result(r, amplitude_mode='amplitude', cmap='turbo', z_auto=True)
    assert c._slice_plot.getAxis('left').labelText == 'Amplitude'
    c.deleteLater()


# ----------------------------------------------------------------------
# full/main export modes (FFT-vs-Time copy: full view vs main chart). M8.
# ----------------------------------------------------------------------
def test_grab_full_vs_main(qapp):
    # full = whole widget (heatmap + slice row); main = heatmap + colorbar
    # only (slice row cropped out). Parity with SpectrogramCanvas
    # grab_full_view / grab_main_chart (canvases.py:2053/2064).
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()  # realize the GraphicsLayout geometry
    c.plot_result(
        _spec_result(), amplitude_mode='amplitude_db', cmap='turbo',
        z_auto=True, z_floor=-80.0, z_ceiling=0.0, freq_range=None,
        x_auto=True, x_min=0.0, x_max=0.0, y_auto=True, y_min=0.0, y_max=0.0,
    )
    full = c.grab_full_view()
    main = c.grab_main_chart()
    assert not full.isNull() and not main.isNull()
    # main excludes the slice row → strictly shorter
    assert main.height() < full.height()
    c.hide()
    c.deleteLater()


def test_grab_main_chart_order_mode_no_slice_does_not_crash(qapp):
    # with_slice=False (Order map): no slice row exists, so grab_main_chart
    # must not crash and main ≈ full height (nothing to crop). The export
    # button is wired for both sections.
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True, cmap='turbo',
    )
    full = c.grab_full_view()
    main = c.grab_main_chart()
    assert not full.isNull() and not main.isNull()
    # No slice row to crop → main spans essentially the whole height (allow
    # a small slack for the heatmap-vs-widget rect difference).
    assert main.height() >= full.height() * 0.5
    c.hide()
    c.deleteLater()


# ----------------------------------------------------------------------
# Toolbar pan/box-zoom parity via axes_list shim (M-heatmap, parity with
# PgLineCanvas M11). PgHeatmapCanvas only got reset_view_to_data_extents
# at M6 (Home), so PgNavigationToolbar's pan/zoom buttons — which walk
# canvas.axes_list → ax.view_box and setMouseMode on each ViewBox — were
# silent no-ops on the order map AND the FFT-vs-Time map (mouseMode stuck
# at PanMode=3, box-zoom dead, _view_boxes() returned []).
# ----------------------------------------------------------------------
def test_axes_list_exposes_primary_viewbox_shim(qapp):
    # Both forms expose at least the main heatmap ViewBox via a shim with a
    # .view_box attribute (the contract PgNavigationToolbar._view_boxes /
    # _primary_view_box read).
    for with_slice in (False, True):
        c = PgHeatmapCanvas(with_slice=with_slice)
        assert hasattr(c, 'axes_list')
        assert len(c.axes_list) >= 1
        view_boxes = [getattr(ax, 'view_box', None) for ax in c.axes_list]
        assert c._plot.vb in view_boxes, (
            f"main heatmap vb missing from axes_list (with_slice={with_slice})"
        )
        c.deleteLater()


@pytest.mark.parametrize("with_slice", [False, True])
def test_toolbar_zoom_mode_flips_heatmap_to_rectmode(qapp, with_slice):
    # The exact production failure: toolbar.set_zoom_mode() walks axes_list
    # and must flip the main heatmap ViewBox into RectMode (box-select zoom).
    # Before the shim, _view_boxes() was empty so the mode never reached the
    # ViewBox — it stayed PanMode=3 and box-zoom was dead.
    c = PgHeatmapCanvas(with_slice=with_slice)
    c.resize(640, 480)
    if with_slice:
        c.plot_result(_spec_result(), amplitude_mode='amplitude_db',
                      cmap='turbo', z_auto=True)
    else:
        c.plot_or_update_heatmap(
            matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
            amplitude_mode='amplitude', z_auto=True,
        )
    toolbar = PgNavigationToolbar(c)
    toolbar.set_zoom_mode()
    assert c._plot.vb.state['mouseMode'] == pg.ViewBox.RectMode
    toolbar.set_pan_mode()
    assert c._plot.vb.state['mouseMode'] == pg.ViewBox.PanMode
    toolbar.deleteLater()
    c.deleteLater()


def test_toolbar_view_boxes_nonempty_and_primary_resolves(qapp):
    # PgNavigationToolbar._view_boxes() must return a non-empty list and
    # _primary_view_box() a real ViewBox for BOTH forms — these feed
    # rebind_history_capture (back/forward) and _set_all_mouse_modes.
    for with_slice in (False, True):
        c = PgHeatmapCanvas(with_slice=with_slice)
        toolbar = PgNavigationToolbar(c)
        boxes = toolbar._view_boxes()
        assert boxes, f"_view_boxes() empty (with_slice={with_slice})"
        assert c._plot.vb in boxes
        primary = toolbar._primary_view_box()
        assert primary is c._plot.vb
        toolbar.deleteLater()
        c.deleteLater()


def test_toolbar_home_still_resets_to_data_extents(qapp):
    # The M6 Home fix (reset_view_to_data_extents) must keep working after
    # the axes_list addition: zoom in, then Home restores a view containing the
    # full extents. A tiny visual margin keeps boundary tick labels off-frame.
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(640, 480)
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    toolbar = PgNavigationToolbar(c)
    # Zoom into a sub-region, then Home.
    c._plot.setXRange(2.0, 4.0, padding=0)
    c._plot.setYRange(1.0, 3.0, padding=0)
    toolbar.home()
    (x0, x1), (y0, y1) = c._plot.vb.viewRange()
    assert x0 < 0.0 and x1 > 10.0
    assert y0 < 0.0 and y1 > 8.0
    assert x0 == pytest.approx(-0.15)
    assert x1 == pytest.approx(10.15)
    assert y0 == pytest.approx(-0.12)
    assert y1 == pytest.approx(8.12)
    toolbar.deleteLater()
    c.deleteLater()


@pytest.mark.parametrize("with_slice", [False, True])
def test_toolbar_home_keeps_heatmap_extents_with_visual_padding(qapp, with_slice):
    """Order and FFT-vs-Time Home/查看全部 should include full data without
    placing boundary tick labels directly on the plot frame."""
    c = PgHeatmapCanvas(with_slice=with_slice)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    toolbar = PgNavigationToolbar(c)

    c._plot.setXRange(2.0, 4.0, padding=0)
    c._plot.setYRange(1.0, 3.0, padding=0)
    toolbar.home()
    qapp.processEvents()

    (x0, x1), (y0, y1) = c._plot.vb.viewRange()
    assert x0 < 0.0
    assert x1 > 10.0
    assert y0 < 0.0
    assert y1 > 8.0
    assert x0 > -1.0
    assert y0 > -1.0

    toolbar.deleteLater()
    c.hide()
    c.deleteLater()


def test_toolbar_box_zoom_drag_actually_zooms(qapp):
    # End-to-end: with the toolbar in zoom mode, a programmatic box-zoom
    # gesture on the heatmap ViewBox must shrink the view to the dragged
    # rectangle (NOT a no-op). RectMode is the precondition for ViewBox to
    # interpret a left-drag as a zoom rectangle rather than a pan.
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    c.plot_or_update_heatmap(
        matrix=_mat(), x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    toolbar = PgNavigationToolbar(c)
    toolbar.set_zoom_mode()
    assert c._plot.vb.state['mouseMode'] == pg.ViewBox.RectMode  # precondition
    # ViewBox.showAxRect is the call RectMode dragging ultimately makes;
    # exercising it through the RectMode-configured ViewBox proves the box
    # zoom path is live (the toolbar wired the mode that gates it).
    from PyQt5.QtCore import QRectF
    c._plot.vb.showAxRect(QRectF(2.0, 1.0, 3.0, 3.0))
    (x0, x1), (y0, y1) = c._plot.vb.viewRange()
    # The view collapses to roughly the 3×3 box (showAxRect adds a small
    # suggestPadding, so assert it shrank and is centered on the box rather
    # than matching the exact corners).
    assert x1 - x0 < 6.0 and y1 - y0 < 6.0, "box zoom did not shrink the view"
    assert (x0 + x1) / 2 == pytest.approx(3.5, abs=0.5)  # box center x = 3.5
    assert (y0 + y1) / 2 == pytest.approx(2.5, abs=0.5)  # box center y = 2.5
    toolbar.deleteLater()
    c.hide()
    c.deleteLater()
