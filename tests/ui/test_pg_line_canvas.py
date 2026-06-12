"""PgLineCanvas: dual-row spectrum canvas tests (offscreen)."""
import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication, QPointF, Qt

from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


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
    c = PgLineCanvas()
    c.resize(640, 480)
    yield c
    c.deleteLater()


def _entry(label='f1 · vib', color='#2563eb'):
    freq = np.linspace(0, 500, 256)
    amp = np.exp(-((freq - 120) / 15.0) ** 2)
    time = np.linspace(0, 1.0, 1000)
    signal = np.sin(2 * np.pi * 12.0 * time)
    return {'label': label, 'color': color, 'freq': freq,
            'amp': amp, 'time': time, 'signal': signal}


def test_plot_spectra_single_entry(canvas):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0),
        amp_label='Amplitude',
        title='FFT - vib', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 1
    assert len(canvas._time_curves) == 1
    xs, ys = canvas._amp_curves[0].getData()
    assert len(xs) == 256
    (x0, x1), _ = canvas._plot_amp.vb.viewRange()
    assert (x0, x1) == (pytest.approx(0.0), pytest.approx(500.0))
    tx, ty = canvas._time_curves[0].getData()
    assert len(tx) == 1000
    assert len(ty) == 1000
    assert canvas._plot_time.getAxis('bottom').labelText == 'Time (s)'


def test_fft_curves_are_antialiased(canvas):
    canvas.plot_spectra(
        [_entry(), _entry('f2 · vib', '#dc2626')],
        xlim=(0.0, 500.0),
        amp_label='Amplitude',
        title='FFT',
        y_auto=True,
        y_min=0.0,
        y_max=0.0,
    )
    curves = canvas._amp_curves + canvas._time_curves
    assert curves
    assert all(c.opts.get('antialias') is True for c in curves)


def test_plot_spectra_overlay_n(canvas):
    canvas.plot_spectra(
        [_entry('a', '#2563eb'), _entry('b', '#dc2626'), _entry('c', '#16a34a')],
        xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 3
    assert len(canvas._time_curves) == 1
    # replot replaces, never accumulates
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='A',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 1
    assert len(canvas._time_curves) == 1


def test_cursor_readout_values(canvas):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    rows = canvas.readout_at(120.0)
    assert len(rows) == 1
    label, freq, amp_val = rows[0]
    assert label == 'f1 · vib'
    assert amp_val == pytest.approx(1.0, abs=0.01)


def test_remark_snaps_to_curve(canvas):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at('amp', 119.0, 0.5)   # off-curve y → snaps to nearest sample
    assert len(canvas._remarks) == 1
    # Nearest sample to x=119.0 on linspace(0, 500, 256) is index 61 →
    # x = 61*500/255 ≈ 119.6078; y must snap to the CURVE value
    # exp(-((119.6078-120)/15)**2) ≈ 0.9993, not the clicked 0.5.
    xs, ys = canvas._remarks[0]['dot'].getData()
    assert xs[0] == pytest.approx(119.6078, abs=1e-3)
    assert ys[0] == pytest.approx(0.9993, abs=1e-3)
    # Dot color matches the time-domain annotation dots and the mpl
    # DANGER token (#dc2626), same as PgHeatmapCanvas — not an ad hoc red.
    assert canvas._remarks[0]['dot'].opts['brush'].color().name() == '#dc2626'
    canvas.clear_remarks()
    assert canvas._remarks == []


def test_axis_region_click_neither_adds_nor_deletes_remark(canvas, qapp):
    # plot.sceneBoundingRect() INCLUDES the axis/title/legend chrome, so a
    # click in the left-axis gutter used to map through vb.mapSceneToView
    # to an extrapolated coordinate: left-click added an off-plot remark,
    # right-click deleted the nearest remark with no distance gate. The
    # guard must use vb.sceneBoundingRect() (same family as the heatmap
    # colorbar guard, test_right_click_on_colorbar_region_keeps_remarks).
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    canvas.show()
    qapp.processEvents()  # realize the GraphicsLayout geometry
    canvas.set_remark_enabled(True)
    canvas.add_remark_at('amp', 119.0, 0.5)
    assert len(canvas._remarks) == 1

    plot_rect = canvas._plot_amp.sceneBoundingRect()
    vb_rect = canvas._plot_amp.vb.sceneBoundingRect()
    # Midpoint of the left-axis gutter: inside the plot's scene rect but
    # outside the ViewBox — the precondition asserts pin the scenario.
    sp = QPointF((plot_rect.left() + vb_rect.left()) / 2.0,
                 vb_rect.center().y())
    assert plot_rect.contains(sp)
    assert not vb_rect.contains(sp)

    canvas._on_click(_FakeSceneClick(sp, Qt.LeftButton))
    assert len(canvas._remarks) == 1, "axis-gutter left-click added a remark"
    canvas._on_click(_FakeSceneClick(sp, Qt.RightButton))
    assert len(canvas._remarks) == 1, "axis-gutter right-click deleted a remark"
    canvas.hide()


def test_grab_pixmap_offscreen_smoke(canvas, qapp):
    # Pattern per test_pg_timedomain_canvas.py grab smoke + the export
    # pixel characterization tests: non-null, ~2x geometry, written to
    # /tmp for human inspection, and a non-all-white pixel sample (this
    # repo has an OpenGL all-white-export history — geometry alone does
    # not prove the export rendered).
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT - vib',
        y_auto=True, y_min=0.0, y_max=0.0,
    )
    canvas.show()
    QCoreApplication.processEvents()

    pix = canvas.grab_pixmap()  # default scale=2.0
    assert pix is not None
    assert not pix.isNull(), "grab_pixmap returned a null pixmap"
    dpr = canvas._glw.devicePixelRatioF()
    assert pix.width() == pytest.approx(canvas._glw.width() * dpr * 2.0, abs=2)
    assert pix.height() == pytest.approx(canvas._glw.height() * dpr * 2.0, abs=2)

    out_path = "/tmp/pg_line_canvas_fft_smoke.png"
    assert pix.save(out_path), f"failed to write screenshot to {out_path!r}"

    # Sampled non-white assertion (white background → curve/axes/legend
    # must leave a substantial non-white footprint).
    img = pix.toImage()
    nonwhite = 0
    for y in range(0, img.height(), 4):
        for x in range(0, img.width(), 4):
            c = img.pixelColor(x, y)
            if c.red() < 245 or c.green() < 245 or c.blue() < 245:
                nonwhite += 1
    assert nonwhite > 200, "2x export looks blank (all-white)"
    canvas.hide()


def test_readout_text_includes_delta_for_multi_curve(canvas):
    # FFT overlay comparison: format_readout adds a per-curve Δ column
    # (display-space difference vs the first/primary curve) so the user
    # reads the gap as a number instead of eyeballing two lines. Under a
    # dB axis the display-space subtraction is a dB difference; under a
    # linear axis it is a plain value difference — correct either way
    # because the canvas already holds display-space values.
    e1, e2 = _entry('a', '#2563eb'), _entry('b', '#dc2626')
    e2 = dict(e2, amp=e2['amp'] * 0.5, signal=e2['signal'] * 0.5)
    canvas.plot_spectra(
        [e1, e2], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    text = canvas.format_readout(120.0)
    assert 'Δ' in text
    # b is a = a * 0.5 everywhere, so at any snapped sample Δ(b-a) = -a/2.
    # Cross-check against the canvas's own readout instead of hardcoding
    # the linspace sample value: near the 120 Hz peak a≈1.0 → Δ≈-0.5.
    rows = canvas.readout_at(120.0)
    expected_delta = rows[1][2] - rows[0][2]
    assert expected_delta == pytest.approx(-0.5, abs=0.01)
    assert f"{expected_delta:+.4g}" in text
    # the first/primary curve carries no Δ; only later curves do.
    a_seg = text.split('|')[0]
    assert 'Δ' not in a_seg


def test_readout_text_no_delta_for_single_curve(canvas):
    # Single curve → nothing to compare against → no Δ column. The Δ is
    # gated on curve index > 0, so a lone primary curve stays clean.
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    text = canvas.format_readout(120.0)
    assert text != ""
    assert 'Δ' not in text


def test_format_readout_empty_when_no_entries(canvas):
    assert canvas.format_readout(120.0) == ""


def test_set_tick_density_accepts_inspector_counts(canvas):
    # Inspector PersistentTop passes integer tick COUNTS (x spinbox
    # 3-30, y spinbox 3-20; defaults 10/8), NOT pg density factors —
    # same contract as PgHeatmapCanvas.set_tick_density (lesson
    # 2026-06-11-inspector-tick-counts-vs-pg-density-factors).
    canvas.set_tick_density(10, 8)
    for plot in (canvas._plot_amp, canvas._plot_time):
        assert plot.getAxis('bottom')._tickDensity == pytest.approx(10 / 10.0)
        assert plot.getAxis('left')._tickDensity == pytest.approx(8 / 6.0)


def test_set_tick_density_clamps_at_spinbox_maxima(canvas):
    canvas.set_tick_density(30, 20)
    for plot in (canvas._plot_amp, canvas._plot_time):
        assert plot.getAxis('bottom')._tickDensity == pytest.approx(3.0)
        assert plot.getAxis('left')._tickDensity == pytest.approx(3.0)


def test_line_plots_draw_full_neutral_axis_frame_without_viewbox_overlap(qapp):
    from mf4_analyzer.ui._axis_handle import (
        PG_AXIS_NEUTRAL_COLOR,
        PG_AXIS_NEUTRAL_WIDTH,
    )

    c = PgLineCanvas()
    try:
        for plot in (c._plot_amp, c._plot_time):
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


def test_selecting_fft_curve_updates_time_preview(canvas):
    e1 = _entry('a', '#2563eb')
    e2 = _entry('b', '#dc2626')
    e2 = dict(e2, signal=np.cos(2 * np.pi * 5.0 * e2['time']))

    canvas.plot_spectra(
        [e1, e2], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    canvas.select_time_entry(1)

    assert canvas._selected_time_entry_idx == 1
    tx, ty = canvas._time_curves[0].getData()
    np.testing.assert_allclose(tx, e2['time'])
    np.testing.assert_allclose(ty, e2['signal'])
    assert 'b' in canvas._plot_time.titleLabel.text
