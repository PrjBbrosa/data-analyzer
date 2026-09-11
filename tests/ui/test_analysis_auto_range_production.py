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
