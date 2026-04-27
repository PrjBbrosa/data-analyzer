"""Tests for ``PlotCanvas.plot_or_update_heatmap`` amplitude-mode params.

Covers Wave 3, Task 3.1 of the FFT/order head-parity plan
(`docs/superpowers/plans/2026-04-28-fft-order-head-parity.md`):

  - Heatmap supports ``amplitude_mode='amplitude_db'`` with ``dynamic``
    clipping (30/50/80 dB or 'Auto'), reusing the dB conversion pattern
    from ``SpectrogramCanvas``.
  - Default behaviour (``amplitude_mode='amplitude'`` / ``dynamic='Auto'``)
    is unchanged — the matrix is passed through linearly.
  - In dB mode the rendered ``AxesImage`` array is normalized so its peak
    is ~0 dB and its floor is bounded by the requested dynamic range.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest

from mf4_analyzer.ui.canvases import PlotCanvas


def test_heatmap_db_mode_with_30db_clamps_to_minus30_zero(qapp):
    canvas = PlotCanvas()
    # Synthesize a matrix with a 100x dynamic range (peak = 1.0).
    m = np.array([[1.0, 0.5, 0.1, 0.001]] * 4)
    canvas.plot_or_update_heatmap(
        matrix=m, x_extent=(0, 1), y_extent=(0, 1),
        x_label='x', y_label='y', title='t',
        amplitude_mode='amplitude_db', dynamic='30 dB',
    )
    im = canvas._heatmap_im
    assert im is not None
    arr = im.get_array()
    assert arr.max() == pytest.approx(0.0, abs=0.5)
    assert arr.min() >= -30.0


def test_heatmap_linear_mode_passes_through(qapp):
    canvas = PlotCanvas()
    m = np.array([[2.0, 1.0], [0.5, 0.1]])
    canvas.plot_or_update_heatmap(
        matrix=m, x_extent=(0, 1), y_extent=(0, 1),
        x_label='x', y_label='y', title='t',
        amplitude_mode='amplitude', dynamic='Auto',
    )
    arr = canvas._heatmap_im.get_array()
    assert arr.max() == pytest.approx(2.0)
    assert arr.min() == pytest.approx(0.1)


def test_heatmap_db_50db_dynamic(qapp):
    canvas = PlotCanvas()
    m = np.array([[1.0, 1e-3, 1e-5, 1e-7]])
    canvas.plot_or_update_heatmap(
        matrix=m, x_extent=(0, 1), y_extent=(0, 1),
        x_label='x', y_label='y', title='t',
        amplitude_mode='amplitude_db', dynamic='50 dB',
    )
    arr = canvas._heatmap_im.get_array()
    assert arr.min() >= -50.0
