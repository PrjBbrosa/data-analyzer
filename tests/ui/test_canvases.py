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
from types import SimpleNamespace

from mf4_analyzer.ui.canvases import (
    PlotCanvas,
    SpectrogramCanvas,
    TimeDomainCanvas,
    _format_dual_html,
)


def test_heatmap_db_mode_with_30db_clamps_to_minus30_zero(qapp):
    canvas = PlotCanvas()
    # Synthesize a matrix with a 100x dynamic range (peak = 1.0).
    m = np.array([[1.0, 0.5, 0.1, 0.001]] * 4)
    canvas.plot_or_update_heatmap(
        matrix=m, x_extent=(0, 1), y_extent=(0, 1),
        x_label='x', y_label='y', title='t',
        amplitude_mode='amplitude_db',
        z_auto=False, z_floor=-30.0, z_ceiling=0.0,
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
        amplitude_mode='amplitude', z_auto=True,
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
        amplitude_mode='amplitude_db',
        z_auto=False, z_floor=-50.0, z_ceiling=0.0,
    )
    arr = canvas._heatmap_im.get_array()
    assert arr.min() >= -50.0


def test_spectrogram_manual_x_range_controls_time_axis(qapp):
    """FFT Time manual X controls are time-axis limits, not frequency limits."""
    canvas = SpectrogramCanvas()
    result = SimpleNamespace(
        times=np.array([0.0, 1.0, 2.0, 3.0]),
        frequencies=np.array([0.0, 10.0, 20.0]),
        amplitude=np.ones((3, 4), dtype=float),
        params=SimpleNamespace(db_reference=1.0),
    )

    canvas.plot_result(
        result,
        amplitude_mode='amplitude',
        x_auto=False,
        x_min=1.0,
        x_max=2.0,
    )

    assert canvas._ax_spec.get_xlim() == pytest.approx((1.0, 2.0))


def test_spectrogram_layout_uses_right_canvas_and_aligns_axes(qtbot):
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(1400, 800)
    canvas.show()
    qtbot.waitExposed(canvas)
    result = SimpleNamespace(
        times=np.linspace(0.0, 40.0, 64),
        frequencies=np.linspace(0.0, 50.0, 32),
        amplitude=np.ones((32, 64), dtype=float),
        params=SimpleNamespace(db_reference=1.0),
    )

    canvas.plot_result(result)
    canvas.draw()

    spec_pos = canvas._ax_spec.get_position()
    slice_pos = canvas._ax_slice.get_position()
    cbar_pos = canvas._colorbar.ax.get_position()
    assert abs(spec_pos.x1 - slice_pos.x1) < 0.01
    assert cbar_pos.x1 > 0.93


def test_order_heatmap_has_borderless_main_axes_and_no_cbar_x_ticks(qapp):
    canvas = PlotCanvas()
    matrix = np.ones((20, 40), dtype=float)

    canvas.plot_or_update_heatmap(
        matrix=matrix,
        x_extent=(0.0, 40.0),
        y_extent=(0.0, 20.0),
        x_label='Time (s)',
        y_label='Order',
        title='时间-阶次谱',
        amplitude_mode='amplitude_db',
        z_auto=False,
        z_floor=-50.0,
        z_ceiling=-10.0,
    )
    canvas.set_tick_density(10, 5)
    canvas.draw()

    main_ax = canvas._heatmap_ax
    cbar_ax = canvas._heatmap_cbar.ax
    assert all(not spine.get_visible() for spine in main_ax.spines.values())
    assert not cbar_ax.xaxis.get_visible()
    assert all(not label.get_visible() for label in cbar_ax.get_xticklabels())


def test_dual_cursor_html_labels_endpoint_delta_with_hollow_triangle():
    html = _format_dual_html([
        ("torque", 1.0, 3.0, 2.0, 4.0, " Nm", "#123456"),
    ])

    assert "RMS" not in html
    assert "△" in html
    assert "4 Nm" in html


def test_dual_cursor_delta_uses_interpolated_cursor_point_difference(qapp):
    canvas = TimeDomainCanvas()
    t = np.array([0.0, 1.0, 2.0], dtype=float)
    sig = np.array([10.0, 20.0, 50.0], dtype=float)
    canvas.channel_data["torque"] = (t, sig, "#123456", "Nm")
    canvas._ax = 0.25
    canvas._bx = 1.75

    emitted = []
    canvas.dual_cursor_info.connect(emitted.append)
    canvas._update_dual()

    assert emitted
    html = emitted[-1]
    assert "RMS" not in html
    assert "△" in html
    # Linear interpolation: A=12.5, B=42.5, so B-A = 30.0.
    assert "30 Nm" in html


def test_timedomain_subplot_long_ylabel_switches_to_inside_labels(qtbot):
    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(1000, 420)
    canvas.show()
    qtbot.waitExposed(canvas)
    t = np.linspace(0.0, 1.0, 200)
    names = [
        "[Recorder_2026-04-2] AppCtrl_ES_DistanceRollingCounter_u16",
        "[Recorder_2026-04-2] AppCtrl_ES_DistanceRangeCheckStatus_bool",
    ]

    canvas.plot_channels([
        (names[0], True, t, np.sin(t * 12.0), "#ef4444", ""),
        (names[1], True, t, np.cos(t * 10.0), "#f97316", ""),
    ], mode="subplot")

    assert canvas._last_channel_label_mode == "inside"
    assert len(canvas._inside_channel_label_artists) == len(names)
    assert set(canvas.channel_data) == set(names)
    for ax in canvas.axes_list:
        assert ax.get_ylabel() == ""
    for artist, full_name in zip(canvas._inside_channel_label_artists, names):
        x, y = artist.get_position()
        assert x <= 0.03
        assert y >= 0.96
        assert artist.get_gid() == full_name
        assert "..." in artist.get_text() or "…" in artist.get_text()
