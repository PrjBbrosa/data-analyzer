"""Actual MainWindow render entries retain full result axes and slice masks."""
import numpy as np
import pytest
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult


def test_fft_time_production_auto_frequency_and_home_slice(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    win.toolbar._set_mode('fft_time')
    canvas = win.chart_stack.page_fft_time.pane_canvas(0)
    freqs = np.linspace(0., 12000., 121)
    amp = np.full((121, 3), 1e-6)
    amp[1] = 1.
    r = SpectrogramResult(times=np.array([0., 1., 2.]), frequencies=freqs,
        amplitude=amp, params=SpectrogramParams(fs=24000., nfft=240), channel_name='test', unit='Pa')
    params = win.inspector.fft_time_ctx.get_params()
    params.update(freq_auto=True, y_auto=True, z_auto=True, amplitude_mode='amplitude')
    win._render_fft_time_on(canvas, r, params)
    assert canvas._plot.vb.viewRange()[1] == pytest.approx((0., 12000.))
    assert canvas._panel_freq_range is None
    canvas._plot.setYRange(1000., 2000., padding=0)
    assert canvas._slice_plot.vb.viewRange()[0] == pytest.approx((1000., 2000.))
    canvas.reset_view_to_data_extents()
    assert canvas._slice_plot.vb.viewRange()[0] == pytest.approx((0., 12000.))
    np.testing.assert_array_equal(canvas._matrix_disp, amp)


@pytest.mark.parametrize('mode,raw,expected', [
    ('Amplitude', [0., 100., 200., 900., 1000.], (-50., 1050.)),
    ('Amplitude dB', [0., 1e-15, 0.01, 0.1, 0.1], (-314., -6.)),
])
def test_order_production_slice_uses_transposed_source_valid_mask(qtbot, mode, raw, expected):
    from types import SimpleNamespace
    win = MainWindow()
    qtbot.addWidget(win)
    win.toolbar._set_mode('order')
    ctx = win.inspector.order_ctx
    ctx.apply_params({'amplitude_mode': mode, 'z_auto': True,
                      'db_reference_mode': 'manual', 'db_reference': 1.})
    r = SimpleNamespace(times=np.array([0., 1.]), orders=np.arange(5.),
        amplitude=np.tile(raw, (2, 1)), params=SimpleNamespace(order_res=1., weighting='None', fs=10., nfft=8))
    c = win.chart_stack.page_order.pane_canvas(0)
    win._render_order_on(c, r)
    c.select_time_index(0)
    assert c._slice_plot.vb.viewRange()[1] == pytest.approx(expected)
    assert c._matrix_amp_valid.shape == (5, 2)
    assert c._matrix_amp_valid[0].all() == ('dB' not in mode)
    c._plot.setYRange(3., 4., padding=0)
    assert c._slice_plot.vb.viewRange()[0] == pytest.approx((3., 4.))
    c.reset_view_to_data_extents()
    assert c._slice_plot.vb.viewRange()[0] == pytest.approx((0., 4.))


def test_order_and_fft_time_second_cache_restore_does_not_replot(qtbot):
    """A second cache restore with the same picture does not call the heatmap plot."""
    from types import SimpleNamespace

    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult

    win = MainWindow()
    qtbot.addWidget(win)

    def _spy(canvas, name):
        calls = []
        real = getattr(canvas, name)

        def wrapped(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        setattr(canvas, name, wrapped)
        return calls

    win.toolbar._set_mode("order")
    order_ctx = win.inspector.order_ctx
    order_ctx.apply_params({
        "amplitude_mode": "Amplitude dB",
        "z_auto": False,
        "db_reference_mode": "manual",
        "db_reference": 3.5,
        "z_floor": -50.0,
        "z_ceiling": -10.0,
    })
    order_state = win.analysis_managers["order"].get(
        win.analysis_managers["order"].active
    )
    order_state.params.update(order_ctx.current_params())
    order_pane = order_state.panes[0]
    order_pane.sources = [("fid-order", "torque")]
    order_pane.rpm_source = ("fid-order", "speed")
    order_result = SimpleNamespace(
        times=np.array([0.0, 1.0]),
        orders=np.arange(5.0),
        amplitude=np.ones((2, 5), dtype=float),
        params=SimpleNamespace(order_res=1.0, weighting="None", fs=10.0, nfft=8),
        metadata={"coverage_start": 0.0, "coverage_end": 1.0},
    )
    order_key = win._analysis_cache_key(
        "order", "fid-order", "torque",
        rpm_source=order_pane.rpm_source, pane_idx=0,
    )
    win.analysis_caches["order"].put(order_key, order_result)
    order_canvas = win.chart_stack.page_order.pane_canvas(0)
    order_plots = _spy(order_canvas, "plot_or_update_heatmap")
    win._render_analysis_view_from_cache("order", order_state)
    win._render_analysis_view_from_cache("order", order_state)
    assert order_plots == [1]
    order_state.panes[0].chart_appearances = {"heatmap": {"cmap": "plasma"}}
    win._render_analysis_view_from_cache("order", order_state)
    assert order_plots == [1, 1]

    win.toolbar._set_mode("fft_time")
    fft_ctx = win.inspector.fft_time_ctx
    fft_ctx.apply_params({
        "amplitude_mode": "amplitude_db",
        "z_auto": False,
        "db_reference_mode": "manual",
        "db_reference": 3.5,
        "z_floor": -80.0,
        "z_ceiling": 0.0,
        "freq_auto": True,
    })
    fft_state = win.analysis_managers["fft_time"].get(
        win.analysis_managers["fft_time"].active
    )
    fft_state.params.update(fft_ctx.current_params())
    fft_pane = fft_state.panes[0]
    fft_pane.sources = [("fid-fft", "speed")]
    freqs = np.linspace(0.0, 200.0, 16)
    amp = np.full((16, 4), 0.2, dtype=np.float32)
    amp[4, :] = 1.0
    fft_result = SpectrogramResult(
        times=np.linspace(0.0, 0.4, 4),
        frequencies=freqs,
        amplitude=amp,
        params=SpectrogramParams(fs=1000.0, nfft=32),
        channel_name="speed",
        unit="rpm",
        metadata={"frames": 4},
    )
    fft_key = win._analysis_cache_key("fft_time", "fid-fft", "speed", pane_idx=0)
    win.analysis_caches["fft_time"].put(fft_key, fft_result)
    fft_canvas = win.chart_stack.page_fft_time.pane_canvas(0)
    fft_plots = _spy(fft_canvas, "plot_result")
    win._render_analysis_view_from_cache("fft_time", fft_state)
    win._render_analysis_view_from_cache("fft_time", fft_state)
    assert fft_plots == [1]
    fft_state.params["z_floor"] = -60.0
    fft_ctx.apply_params({"z_floor": -60.0})
    win._render_analysis_view_from_cache("fft_time", fft_state)
    assert fft_plots == [1, 1]
