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
        displayed = artist.get_text().replace("\u25cf ", "").replace("\n", " ")
        assert full_name in displayed
        assert "..." not in artist.get_text()
        assert "\u2026" not in artist.get_text()


def test_timedomain_subplot_relayouts_after_resize_keep_ticks_visible(qtbot):
    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(1000, 420)
    canvas.show()
    qtbot.waitExposed(canvas)
    t = np.linspace(0.0, 10.0, 800)

    canvas.plot_channels([
        ("[taiyaok ] Rte_TAS_mTorsionBarTorque", True, t, np.sin(t), "#8b5cf6", ""),
        ("[taiyaok ] Rte_VehSpdMpsA_bSpeed", True, t, 4.0 + np.cos(t), "#00b894", ""),
        ("[yuandi] Rte_TAS_mTorsionBarTorque", True, t, 2.0 * np.sin(t), "#7c3aed", ""),
    ], mode="subplot")
    canvas.draw()

    canvas.resize(430, 420)
    qtbot.wait(120)
    canvas.draw()

    renderer = canvas.fig.canvas.get_renderer()
    leftmost_tick = min(
        tick.label1.get_window_extent(renderer).x0
        for ax in canvas.axes_list
        for tick in ax.yaxis.get_major_ticks()
        if tick.label1.get_visible()
    )
    assert leftmost_tick >= 0


def test_timedomain_overlay_click_selects_curve_for_y_controls(qtbot):
    from matplotlib.backend_bases import MouseEvent

    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 500)
    canvas.show()
    qtbot.waitExposed(canvas)

    t = np.linspace(0.0, 1.0, 80)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    canvas.draw()

    torque_ax, torque_line = canvas._channel_lines["torque"]
    x_data = float(torque_line.get_xdata()[30])
    y_data = float(torque_line.get_ydata()[30])
    x_pix, y_pix = torque_ax.transData.transform((x_data, y_data))
    event = MouseEvent(
        "button_press_event", canvas, x_pix, y_pix, button=1
    )
    canvas.callbacks.process("button_press_event", event)

    assert canvas.selected_overlay_channel() == "torque"
    assert (
        torque_line.get_linewidth()
        > canvas._channel_lines["speed"][1].get_linewidth()
    )
    assert canvas._channel_lines["speed"][1].get_alpha() < 1.0


def test_timedomain_overlay_scroll_y_moves_selected_curve_only(qtbot):
    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 500)
    canvas.show()
    qtbot.waitExposed(canvas)

    t = np.linspace(0.0, 1.0, 80)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    canvas.select_overlay_channel("torque")

    speed_ax = canvas._channel_lines["speed"][0]
    torque_ax = canvas._channel_lines["torque"][0]
    before_speed = speed_ax.get_ylim()
    before_torque = torque_ax.get_ylim()

    event = SimpleNamespace(
        inaxes=speed_ax, step=1, key="", xdata=0.5, ydata=0.0
    )
    canvas._on_scroll(event)

    assert speed_ax.get_ylim() == pytest.approx(before_speed)
    assert torque_ax.get_ylim() != pytest.approx(before_torque)


def test_timedomain_overlay_shift_wheel_zooms_selected_curve_only(qtbot):
    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 500)
    canvas.show()
    qtbot.waitExposed(canvas)

    t = np.linspace(0.0, 1.0, 80)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    canvas.select_overlay_channel("torque")

    speed_ax = canvas._channel_lines["speed"][0]
    torque_ax = canvas._channel_lines["torque"][0]
    before_speed = speed_ax.get_ylim()
    before_torque = torque_ax.get_ylim()

    event = SimpleNamespace(
        inaxes=speed_ax, step=1, key="shift", xdata=0.5, ydata=0.0
    )
    canvas._on_scroll(event)

    assert speed_ax.get_ylim() == pytest.approx(before_speed)
    assert torque_ax.get_ylim() != pytest.approx(before_torque)


def test_timedomain_overlay_drag_y_moves_selected_curve_only(qtbot):
    from matplotlib.backend_bases import MouseEvent

    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 500)
    canvas.show()
    qtbot.waitExposed(canvas)

    t = np.linspace(0.0, 1.0, 80)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    canvas.draw()

    torque_ax, torque_line = canvas._channel_lines["torque"]
    x_data = float(torque_line.get_xdata()[30])
    y_data = float(torque_line.get_ydata()[30])
    x_pix, y_pix = torque_ax.transData.transform((x_data, y_data))
    press = MouseEvent(
        "button_press_event", canvas, x_pix, y_pix, button=1
    )
    canvas.callbacks.process("button_press_event", press)

    speed_ax = canvas._channel_lines["speed"][0]
    before_speed = speed_ax.get_ylim()
    before_torque = torque_ax.get_ylim()

    move = SimpleNamespace(
        inaxes=speed_ax, x=x_pix, y=y_pix + 30, xdata=0.5, ydata=0.0, button=1
    )
    canvas._on_move(move)

    assert speed_ax.get_ylim() == pytest.approx(before_speed)
    assert torque_ax.get_ylim() != pytest.approx(before_torque)


def test_timedomain_overlay_selection_clears_on_replot(qtbot):
    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 500)
    canvas.show()
    qtbot.waitExposed(canvas)

    t = np.linspace(0.0, 1.0, 80)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    canvas.select_overlay_channel("torque")

    canvas.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("current", True, t, np.cos(t * 4.0), "#2563eb", "A"),
    ], mode="overlay")

    assert canvas.selected_overlay_channel() is None




def test_timedomain_overlay_blank_click_clears_selection(qtbot):
    """User-request 2026-05-20 (fix 3): in overlay mode, clicking on a
    blank region of the canvas (no curve under the cursor, no pan/zoom
    tool active, true click = release within pixel tolerance of press)
    must clear the current overlay selection and emit
    ``overlay_channel_selected(None)``.

    Scenario: select a curve via a pick-hit press, simulate a vertical
    drag (motion + release advances ylim but does not deselect — drag,
    not click), then press + release on a blank pixel — selection
    clears, signal fires with None.
    """
    from matplotlib.backend_bases import MouseEvent

    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 500)
    canvas.show()
    qtbot.waitExposed(canvas)

    t = np.linspace(0.0, 1.0, 80)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    canvas.draw()

    # (a) Pick-hit press selects torque.
    torque_ax, torque_line = canvas._channel_lines["torque"]
    xd = float(torque_line.get_xdata()[30])
    yd = float(torque_line.get_ydata()[30])
    xp, yp = torque_ax.transData.transform((xd, yd))
    press = MouseEvent("button_press_event", canvas, xp, yp, button=1)
    canvas.callbacks.process("button_press_event", press)
    assert canvas.selected_overlay_channel() == "torque"

    # (b) Vertical drag: motion shifts ylim but must not deselect.
    canvas._mouse_button_pressed = True
    before_ylim = torque_ax.get_ylim()
    move = SimpleNamespace(
        inaxes=torque_ax, x=xp, y=yp + 40,
        xdata=xd, ydata=yd, button=1,
    )
    canvas._on_move(move)
    after_ylim = torque_ax.get_ylim()
    assert after_ylim != pytest.approx(before_ylim)
    release_drag = MouseEvent(
        "button_release_event", canvas, xp, yp + 40, button=1
    )
    canvas.callbacks.process("button_release_event", release_drag)
    canvas._mouse_button_pressed = False
    # Selection survives the drag.
    assert canvas.selected_overlay_channel() == "torque"

    # (c) Press + release on a blank pixel near the axes corner —
    # far from every curve so the pick-radius search misses.
    blank_x = float(canvas.fig.bbox.width) - 8.0
    blank_y = float(canvas.fig.bbox.height) - 8.0
    deselect_events = []
    canvas.overlay_channel_selected.connect(deselect_events.append)
    press_blank = MouseEvent(
        "button_press_event", canvas, blank_x, blank_y, button=1
    )
    canvas.callbacks.process("button_press_event", press_blank)
    # Selection still live after press alone.
    assert canvas.selected_overlay_channel() == "torque"
    # Release at the same pixel (true click, not drag).
    release_blank = MouseEvent(
        "button_release_event", canvas, blank_x, blank_y, button=1
    )
    canvas.callbacks.process("button_release_event", release_blank)

    # (d) Selection cleared and signal fired with None.
    assert canvas.selected_overlay_channel() is None
    assert deselect_events and deselect_events[-1] is None


def test_timedomain_overlay_blank_drag_does_not_deselect(qtbot):
    """fix 3 negative: a press-on-blank followed by a release at a
    pixel farther than ``_overlay_click_pixel_tol`` away is a drag,
    not a click — selection must survive."""
    from matplotlib.backend_bases import MouseEvent

    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 500)
    canvas.show()
    qtbot.waitExposed(canvas)

    t = np.linspace(0.0, 1.0, 80)
    canvas.plot_channels([
        ("speed", True, t, np.sin(t * 4.0), "#7c3aed", "rpm"),
        ("torque", True, t, 5.0 + np.cos(t * 4.0), "#16a34a", "Nm"),
    ], mode="overlay")
    canvas.select_overlay_channel("torque")
    assert canvas.selected_overlay_channel() == "torque"

    blank_x = float(canvas.fig.bbox.width) - 8.0
    blank_y = float(canvas.fig.bbox.height) - 8.0
    press = MouseEvent("button_press_event", canvas, blank_x, blank_y, button=1)
    canvas.callbacks.process("button_press_event", press)
    # Release 20 px away — drag, not click.
    release = MouseEvent(
        "button_release_event", canvas, blank_x - 20.0, blank_y - 20.0, button=1
    )
    canvas.callbacks.process("button_release_event", release)
    assert canvas.selected_overlay_channel() == "torque"
