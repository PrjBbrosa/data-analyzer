"""PgLineCanvas: dual-row spectrum canvas tests (offscreen)."""
import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication, QPointF, Qt

from mf4_analyzer.ui.chart_stack import PgNavigationToolbar
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


def test_line_canvas_hides_title_rows_and_disables_axis_si_prefix(canvas):
    canvas.plot_spectra(
        [_entry(), _entry("f2 · vib", "#dc2626")], xlim=(0.0, 500.0),
        amp_label='Amplitude',
        title='FFT · 2 条曲线', y_auto=True, y_min=0.0, y_max=0.0,
    )

    for plot in (canvas._plot_amp, canvas._plot_time):
        assert not plot.titleLabel.isVisible()
        assert plot.titleLabel.maximumHeight() == 0
        assert plot.getAxis('left').autoSIPrefix is False
        assert plot.getAxis('bottom').autoSIPrefix is False


def test_toolbar_home_keeps_full_fft_range_with_visual_padding(canvas, qapp):
    """Home/查看全部 should include all FFT data without pinning boundary
    tick labels directly on the plot frame."""
    canvas.show()
    qapp.processEvents()
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0),
        amp_label='Amplitude',
        title='FFT - vib', y_auto=True, y_min=0.0, y_max=0.0,
    )
    toolbar = PgNavigationToolbar(canvas)

    canvas._plot_amp.setXRange(100.0, 200.0, padding=0)
    canvas._plot_time.setXRange(0.25, 0.5, padding=0)
    toolbar.home()
    qapp.processEvents()

    (x0, x1), _ = canvas._plot_amp.vb.viewRange()
    (tx0, tx1), _ = canvas._plot_time.vb.viewRange()
    assert x0 < 0.0
    assert x1 > 500.0
    assert tx0 < 0.0
    assert tx1 > 1.0
    assert x0 > -50.0
    assert tx0 > -0.1

    toolbar.deleteLater()
    canvas.hide()


def test_toolbar_home_preview_only_keeps_time_padding_without_amp_autorange(canvas, qapp):
    """Before FFT is computed, View All should reset the source preview without
    letting the empty spectrum plot auto-range into a drifting blank frame."""
    canvas.show()
    qapp.processEvents()
    canvas.plot_time_preview([_entry()], title='时域预览')
    toolbar = PgNavigationToolbar(canvas)

    canvas._plot_amp.setXRange(0.0, 1.0, padding=0)
    canvas._plot_amp.setYRange(0.0, 1.0, padding=0)
    canvas._plot_time.setXRange(0.25, 0.5, padding=0)
    toolbar.home()
    qapp.processEvents()

    (x0, x1), (y0, y1) = canvas._plot_amp.vb.viewRange()
    (tx0, tx1), _ = canvas._plot_time.vb.viewRange()
    assert x0 == pytest.approx(0.0)
    assert x1 == pytest.approx(1.0)
    assert y0 == pytest.approx(0.0)
    assert y1 == pytest.approx(1.0)
    assert tx0 < 0.0
    assert tx1 > 1.0
    assert tx0 > -0.1

    toolbar.deleteLater()
    canvas.hide()


def test_ctrl_wheel_zooms_fft_line_canvas_x_only(canvas, qapp):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0),
        amp_label='Amplitude',
        title='FFT - vib', y_auto=True, y_min=0.0, y_max=0.0,
    )
    canvas._plot_amp.setXRange(0.0, 500.0, padding=0)
    canvas._plot_amp.setYRange(-1.0, 1.0, padding=0)
    qapp.processEvents()

    x_before, y_before = canvas._plot_amp.vb.viewRange()
    consumed = canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ControlModifier,
        x_pos=250.0, y_pos=0.0, view_box=canvas._plot_amp.vb,
    )
    qapp.processEvents()
    x_after, y_after = canvas._plot_amp.vb.viewRange()

    assert consumed is True
    assert (x_after[1] - x_after[0]) < (x_before[1] - x_before[0])
    assert y_after == pytest.approx(y_before)


def test_shift_wheel_zooms_fft_line_canvas_current_plot_y_only(canvas, qapp):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0),
        amp_label='Amplitude',
        title='FFT - vib', y_auto=True, y_min=0.0, y_max=0.0,
    )
    canvas._plot_amp.setXRange(0.0, 500.0, padding=0)
    canvas._plot_amp.setYRange(-1.0, 1.0, padding=0)
    canvas._plot_time.setYRange(-2.0, 2.0, padding=0)
    qapp.processEvents()

    x_before, amp_y_before = canvas._plot_amp.vb.viewRange()
    _time_x_before, time_y_before = canvas._plot_time.vb.viewRange()
    consumed = canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ShiftModifier,
        x_pos=250.0, y_pos=0.0, view_box=canvas._plot_time.vb,
    )
    qapp.processEvents()
    x_after, amp_y_after = canvas._plot_amp.vb.viewRange()
    _time_x_after, time_y_after = canvas._plot_time.vb.viewRange()

    assert consumed is True
    assert x_after == pytest.approx(x_before)
    assert amp_y_after == pytest.approx(amp_y_before)
    assert (time_y_after[1] - time_y_after[0]) < (
        time_y_before[1] - time_y_before[0])


def test_time_preview_manual_range_emits_analysis_window(canvas, qapp):
    canvas.plot_time_preview([_entry()], title='时域预览')
    emitted = []
    canvas.time_preview_range_changed.connect(lambda lo, hi: emitted.append((lo, hi)))

    canvas._plot_time.setXRange(0.2, 0.6, padding=0)
    canvas._plot_time.vb.sigRangeChangedManually.emit(
        canvas._plot_time.vb.state['mouseEnabled'])
    qapp.processEvents()

    assert emitted
    assert emitted[-1] == pytest.approx((0.2, 0.6), abs=1e-6)


def test_fft_amp_curves_are_antialiased(canvas):
    # The FFT amplitude overlay (top row) is always antialiased — it is a
    # bounded spectrum (~freq-bin count), not a multi-million-point time
    # source, so AA cost is negligible. The time-preview (bottom) row is
    # governed separately (AA off for multi-source overlay); see
    # test_time_preview_disables_antialias_for_overlay.
    canvas.plot_spectra(
        [_entry(), _entry('f2 · vib', '#dc2626')],
        xlim=(0.0, 500.0),
        amp_label='Amplitude',
        title='FFT',
        y_auto=True,
        y_min=0.0,
        y_max=0.0,
    )
    assert canvas._amp_curves
    assert all(c.opts.get('antialias') is True for c in canvas._amp_curves)
    # Single-entry preview keeps AA; this two-entry spectrum overlay has a
    # two-source time preview, which goes AA-off.
    assert all(c.opts.get('antialias') is False for c in canvas._time_curves)


def test_fft_pan_drops_curve_aa_until_idle(canvas, qapp):
    """During a user pan the overlaid FFT curves must drop antialiasing for a
    cheap raster — mirroring the time-domain canvas's interactive-quality
    policy — then restore crisp AA after a hands-off idle tick. Previously the
    amp curves were ``antialias=True`` permanently with no interactive hook, so
    dragging a multi-curve spectrum re-rasterized AA every frame and stuttered.
    """
    canvas.show()
    qapp.processEvents()
    canvas.plot_spectra(
        [_entry(), _entry('f2 · vib', '#dc2626')],
        xlim=(0.0, 500.0), amp_label='Amplitude', title='FFT',
        y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 2
    # A fresh plot leaves the spectrum crisp (programmatic range, not a drag).
    assert all(c.opts.get('antialias') is True for c in canvas._amp_curves)

    # Simulate a user pan: pyqtgraph's ViewBox.mouseDragEvent emits
    # sigRangeChangedManually on every drag move, unlike a programmatic setRange.
    vb = canvas._plot_amp.vb
    vb.sigRangeChangedManually.emit(vb.state['mouseEnabled'])
    assert all(c.opts.get('antialias') is False for c in canvas._amp_curves), \
        "pan must drop AA on the overlaid FFT curves"
    assert canvas._aa_on is False

    # Hands-off idle tick restores AA on the spectrum overlay.
    canvas._enable_idle_quality()
    assert canvas._aa_on is True
    assert all(c.opts.get('antialias') is True for c in canvas._amp_curves), \
        "idle restores crisp AA on the spectrum"
    # The two-source time preview stays AA-off even when idle (overlay perf).
    assert all(c.opts.get('antialias') is False for c in canvas._time_curves)


def test_fft_quality_status_traffic_light_tracks_aa_state(canvas, qapp):
    """The FFT canvas exposes the same AA traffic-light contract as the
    time-domain canvas so _ChartCard renders the bottom-right quality dot:
    red when there are no curves, green when the spectrum is settled+crisp,
    red during an interactive pan, yellow while waiting for the idle refresh,
    and green again once idle restores AA. Each transition emits the signal."""
    emissions = []
    canvas.quality_status_changed.connect(lambda st: emissions.append(st))

    # No curves yet → red.
    assert canvas.quality_status()["state"] == "red"

    canvas.show()
    qapp.processEvents()
    canvas.plot_spectra(
        [_entry(), _entry('f2 · vib', '#dc2626')],
        xlim=(0.0, 500.0), amp_label='Amplitude', title='FFT',
        y_auto=True, y_min=0.0, y_max=0.0,
    )
    # Fresh crisp spectrum → green, and the render emitted the change.
    assert canvas.quality_status()["state"] == "green"
    assert emissions and emissions[-1]["state"] == "green"

    # Interactive pan drops AA → red.
    vb = canvas._plot_amp.vb
    vb.sigRangeChangedManually.emit(vb.state['mouseEnabled'])
    assert canvas._aa_on is False
    # disable_interactive_quality emitted red; schedule_idle_quality then
    # emitted yellow (idle timer armed) — the latest state is yellow.
    assert canvas._aa_idle_timer.isActive()
    assert canvas.quality_status()["state"] == "yellow"
    assert any(st["state"] == "red" for st in emissions)
    assert emissions[-1]["state"] == "yellow"

    # Idle restores AA → green again. Drive the settled state directly rather
    # than via _enable_idle_quality(), whose QApplication.mouseButtons() gate is
    # flaky under cross-test synthetic mouse events (a leaked press from an
    # earlier test makes it re-arm instead of restoring AA).
    canvas._aa_idle_timer.stop()
    canvas._apply_idle_curve_aa()
    canvas._aa_on = True
    canvas._emit_quality_status()
    assert canvas.quality_status()["state"] == "green"
    assert emissions[-1]["state"] == "green"


def test_fft_ctrl_wheel_zoom_drops_curve_aa(canvas):
    """The custom ctrl/shift wheel zoom sets the range programmatically (no
    sigRangeChangedManually), so it must drop AA explicitly via the wheel
    dispatch hook the same way a drag does."""
    canvas.plot_spectra(
        [_entry(), _entry('f2 · vib', '#dc2626')],
        xlim=(0.0, 500.0), amp_label='Amplitude', title='FFT',
        y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert all(c.opts.get('antialias') is True for c in canvas._amp_curves)
    consumed = canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ControlModifier, x_pos=250.0, y_pos=0.5,
        view_box=canvas._plot_amp.vb,
    )
    assert consumed is True
    assert all(c.opts.get('antialias') is False for c in canvas._amp_curves), \
        "ctrl-wheel zoom must drop AA for the interactive raster"


def test_plot_spectra_overlay_n(canvas):
    canvas.plot_spectra(
        [_entry('a', '#2563eb'), _entry('b', '#dc2626'), _entry('c', '#16a34a')],
        xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 3
    assert len(canvas._time_curves) == 3
    # replot replaces, never accumulates
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='A',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 1
    assert len(canvas._time_curves) == 1


def test_time_preview_overlays_multiple_sources_before_fft(canvas):
    e1 = _entry('a', '#2563eb')
    e2 = _entry('b', '#dc2626')
    e2 = dict(e2, signal=e2['signal'] * 0.5)

    canvas.plot_time_preview([e1, e2], title='时域预览')

    assert len(canvas._amp_curves) == 0
    assert len(canvas._time_curves) == 2
    tx0, ty0 = canvas._time_curves[0].getData()
    tx1, ty1 = canvas._time_curves[1].getData()
    np.testing.assert_allclose(tx0, e1['time'])
    np.testing.assert_allclose(ty0, e1['signal'])
    np.testing.assert_allclose(tx1, e2['time'])
    np.testing.assert_allclose(ty1, e2['signal'])
    assert canvas.has_result() is False


def test_time_preview_does_not_show_channel_name_legend(canvas):
    canvas.plot_time_preview(
        [_entry('a', '#2563eb'), _entry('b', '#dc2626')],
        title='时域预览',
    )

    assert canvas._plot_time.legend is None


def test_plot_spectra_keeps_all_source_time_previews(canvas):
    e1 = _entry('a', '#2563eb')
    e2 = _entry('b', '#dc2626')

    canvas.plot_spectra(
        [e1, e2], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )

    assert len(canvas._amp_curves) == 2
    assert len(canvas._time_curves) == 2


def test_line_canvas_has_no_hover_cursor_line(canvas):
    assert not hasattr(canvas, '_cursor_amp')


def test_empty_fft_keeps_both_plots_labelled(canvas):
    """Empty state: both the amp plot and the time-preview plot carry axis
    titles, so the panel never shows one labelled plot next to a bare one."""
    canvas.full_reset()
    assert canvas._plot_amp.getAxis('left').labelText == 'Amplitude'
    assert canvas._plot_amp.getAxis('bottom').labelText == 'Frequency (Hz)'
    assert canvas._plot_time.getAxis('left').labelText == 'Amplitude'
    assert canvas._plot_time.getAxis('bottom').labelText == 'Time (s)'


def test_both_plots_keep_right_frame_border_single_pane(canvas):
    """Single-pane (no split reserve) must keep a visible right frame on BOTH
    plots — the time-preview right border used to be hidden."""
    canvas.reset_split_layout_alignment()
    assert canvas._plot_amp.getAxis('right').isVisible()
    assert canvas._plot_time.getAxis('right').isVisible()


def test_time_preview_multi_curve_adds_color_coded_y_axes(canvas):
    """Overlaying >1 time-preview source gives each extra curve its own aux
    ViewBox + colour-coded right axis; a single source has none."""
    def _entry(label, color):
        t = np.linspace(0, 1, 200)
        return {'label': label, 'color': color, 'freq': t, 'amp': t,
                'time': t, 'signal': np.sin(t)}

    canvas.plot_time_preview(
        [_entry('a', '#2563eb'), _entry('b', '#22c55e'), _entry('c', '#f59e0b')])
    assert len(canvas._time_overlay_axes) == 2
    assert len(canvas._time_overlay_vbs) == 2
    # The aux axis tick text is colour-coded to its curve.
    assert canvas._time_overlay_axes[0].textPen().color().name() == '#22c55e'
    assert canvas._time_overlay_axes[1].textPen().color().name() == '#f59e0b'

    # Collapsing back to a single source tears the aux axes down.
    canvas.plot_time_preview([_entry('a', '#2563eb')])
    assert canvas._time_overlay_axes == []
    assert canvas._time_overlay_vbs == []


def test_collapse_divider_toggles_plot_visibility(canvas):
    """The collapse control folds the top or bottom plot so the other gets the
    full area; restoring brings both back with the time row's 170px cap."""
    assert canvas._collapse_ctrl is not None
    canvas._on_collapse_changed('bottom')
    assert not canvas._plot_time.isVisible()
    assert canvas._plot_amp.isVisible()
    canvas._on_collapse_changed('top')
    assert not canvas._plot_amp.isVisible()
    assert canvas._plot_time.isVisible()
    assert canvas._plot_time.maximumHeight() > 170
    canvas._on_collapse_changed('none')
    assert canvas._plot_amp.isVisible() and canvas._plot_time.isVisible()
    assert canvas._plot_time.maximumHeight() == 170


def test_collapse_control_toggle_is_sticky_off(qapp):
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _PlotCollapseControl
    ctrl = _PlotCollapseControl()
    emitted = []
    ctrl.collapse_changed.connect(emitted.append)
    ctrl._toggle('top')
    assert ctrl.state() == 'top'
    ctrl._toggle('top')           # clicking the active arrow restores
    assert ctrl.state() == 'none'
    ctrl._toggle('bottom')
    assert ctrl.state() == 'bottom'
    assert emitted == ['top', 'none', 'bottom']


def test_line_canvas_grid_is_major_only(canvas):
    """Analysis canvases default to a major-only grid (no faint minor sub-grid),
    matching the time-domain canvas: maxTickLevel=0 on both plots' bottom/left
    axes so showGrid never draws level-1/2 lines."""
    for plot in (canvas._plot_amp, canvas._plot_time):
        for side in ('bottom', 'left'):
            assert plot.getAxis(side).style.get('maxTickLevel') == 0, (
                f"{side} axis should be major-grid-only (maxTickLevel=0)"
            )


def test_fft_context_menu_is_chinese_and_keeps_plot_options(canvas, monkeypatch):
    canvas.register_mouse_mode_controller(_FakeMouseModeController())
    canvas.plot_time_preview([_entry()], title='时域预览')

    menu = _open_context_menu(canvas._plot_time.vb, monkeypatch)

    assert menu is not None
    top = _menu_texts(menu)
    assert "绘图选项" in top
    assert "Plot Options" not in top
    assert "查看全部" in top
    assert "X 轴范围" in top
    assert "Y 轴范围" in top
    assert "网格" in top
    assert "Mouse Mode" not in top


def test_fft_context_menu_includes_y_autofit(canvas, monkeypatch):
    """The FFT right-click menu gains a 「Y 轴自适应」 entry, mirroring the
    time-domain canvas (previously the line canvas passed y_autofit_handler=None
    so the action never appeared)."""
    canvas.register_mouse_mode_controller(_FakeMouseModeController())
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    menu = _open_context_menu(canvas._plot_amp.vb, monkeypatch)
    assert menu is not None
    assert "Y 轴自适应" in _menu_texts(menu)


def test_fft_y_autofit_fits_to_visible_x_window(canvas, qapp):
    """「Y 轴自适应」 keeps the current X window and collapses Y to the samples
    inside it — zooming X past the spectral peak fits Y to the near-zero tail."""
    canvas.show()
    qapp.processEvents()
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    # The _entry() gaussian peaks (~1.0) near 120 Hz; a 250-400 Hz window is ~0.
    canvas._plot_amp.setXRange(250.0, 400.0, padding=0)
    (x0_before, x1_before), _ = canvas._plot_amp.vb.viewRange()
    canvas._fit_y_to_visible_x(canvas._plot_amp)
    qapp.processEvents()
    (x0, x1), (y0, y1) = canvas._plot_amp.vb.viewRange()
    # X is untouched; Y collapses to the visible near-zero band (not the peak).
    assert (x0, x1) == (pytest.approx(x0_before), pytest.approx(x1_before))
    assert y1 < 0.2, f"Y should fit the visible near-zero window, got {y1}"
    canvas.hide()


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


def test_line_plots_hide_native_auto_fit_buttons(qapp):
    c = PgLineCanvas()
    try:
        for plot in (c._plot_amp, c._plot_time):
            assert getattr(plot, "buttonsHidden", False) is True
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
    tx, ty = canvas._time_curves[1].getData()
    np.testing.assert_allclose(tx, e2['time'])
    np.testing.assert_allclose(ty, e2['signal'])
    selected_width = canvas._time_curves[1].opts['pen'].widthF()
    primary_width = canvas._time_curves[0].opts['pen'].widthF()
    assert selected_width > primary_width


def _big_entry(label='big', color='#2563eb', n=4_000_000, freq_hz=12.0):
    """A multi-million-point time source (worst case for the per-selection
    full-resolution antialiased re-raster the preview used to do)."""
    time = np.linspace(0.0, 10.0, n)
    signal = np.sin(2 * np.pi * freq_hz * time)
    freq = np.linspace(0, 500, 256)
    amp = np.exp(-((freq - 120) / 15.0) ** 2)
    return {'label': label, 'color': color, 'freq': freq, 'amp': amp,
            'time': time, 'signal': signal}


def test_time_preview_decimates_large_source_but_preserves_peaks(canvas, qapp):
    # A multi-million-point trace must NOT be plotted at full resolution:
    # the preview decimates to a min/max envelope (far fewer points) while
    # preserving the visible-window peaks. This is the headline perf change
    # — overlaying N channels at full-res antialias was CPU-raster bound.
    canvas.resize(900, 480)
    canvas.show()
    qapp.processEvents()  # realize plot-area geometry so pixel width is real

    e = _big_entry()
    canvas.plot_time_preview([e], title='时域预览')

    assert len(canvas._time_curves) == 1
    tx, ty = canvas._time_curves[0].getData()
    raw_n = e['signal'].size
    # Decimated curve holds far fewer points than the raw input.
    assert tx.size < raw_n // 100, (
        f"expected heavy decimation, got {tx.size} of {raw_n} points")
    # Peaks preserved: global min/max within float tolerance of the raw.
    assert ty.max() == pytest.approx(e['signal'].max(), abs=1e-6)
    assert ty.min() == pytest.approx(e['signal'].min(), abs=1e-6)
    # Time bounds preserved (no clipping of the first/last sample).
    assert tx.min() == pytest.approx(e['time'].min(), abs=1e-3)
    assert tx.max() == pytest.approx(e['time'].max(), abs=1e-3)
    canvas.hide()


def test_time_preview_single_point_source_still_renders(canvas):
    # n == 1: a single-sample source must still draw exactly one point and
    # must not crash the envelope/decimation path.
    e = {'label': 's', 'color': '#2563eb',
         'freq': np.linspace(0, 500, 16), 'amp': np.ones(16),
         'time': np.array([0.5]), 'signal': np.array([3.0])}
    canvas.plot_time_preview([e], title='时域预览')
    assert len(canvas._time_curves) == 1
    tx, ty = canvas._time_curves[0].getData()
    np.testing.assert_allclose(tx, [0.5])
    np.testing.assert_allclose(ty, [3.0])


def test_time_preview_empty_arrays_render_no_curve(canvas):
    # Empty time/signal arrays: no curve is added and nothing raises.
    e = {'label': 'empty', 'color': '#2563eb',
         'freq': np.linspace(0, 500, 16), 'amp': np.ones(16),
         'time': np.array([]), 'signal': np.array([])}
    canvas.plot_time_preview([e], title='时域预览')
    assert len(canvas._time_curves) == 0


def test_time_preview_disables_antialias_for_overlay(canvas):
    # Single channel keeps antialias (crisp); overlaying >1 channel turns
    # antialias OFF — the win is cutting (points-rasterized × channels),
    # and AA on multi-curve overlays is the CPU-raster cost.
    e1 = _entry('a', '#2563eb')
    canvas.plot_time_preview([e1], title='时域预览')
    assert canvas._time_curves[0].opts.get('antialias') is True

    e2 = _entry('b', '#dc2626')
    canvas.plot_time_preview([e1, e2], title='时域预览')
    assert all(c.opts.get('antialias') is False for c in canvas._time_curves)
