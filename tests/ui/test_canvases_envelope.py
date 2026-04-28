"""Tests for module-level ``build_envelope`` helper and
``PlotCanvas.plot_or_update_heatmap`` reuse semantics.

Covers Task 4 of the order-canvas-perf plan
(`docs/superpowers/plans/2026-04-26-order-canvas-perf-plan.md`):

  - ``build_envelope`` is module-level on ``mf4_analyzer.ui.canvases``
    and behaviourally identical to the legacy
    ``TimeDomainCanvas._envelope`` for tuple ``xlim``.
  - ``build_envelope`` accepts ``xlim=None`` (full-range) — this is the
    auxiliary callers needing the xlim=None full-range entry; spec §6.4.
  - ``TimeDomainCanvas._envelope`` is a thin wrapper that **keeps its
    required-xlim signature**; ``None`` is the module helper's contract
    only and must not propagate.
  - ``PlotCanvas.plot_or_update_heatmap`` reuses axes / image / colorbar
    on a compatible call (4-clause check from spec §6.2), rebuilds on
    shape change, and resets ``_heatmap_*`` state on ``clear()`` so a
    2-subplot→heatmap round trip does not leave a colorbar ghost.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest

from mf4_analyzer.ui import canvases as cv


# -------------------------------------------------------------------
# build_envelope — module-level + behavioural parity
# -------------------------------------------------------------------


def test_build_envelope_is_module_level():
    assert hasattr(cv, 'build_envelope'), "build_envelope must be module-level"


def test_build_envelope_matches_timedomain_envelope_behaviour(qtbot):
    canvas = cv.TimeDomainCanvas()
    qtbot.addWidget(canvas)
    n = 100_000
    t = np.linspace(0.0, 10.0, n)
    sig = np.sin(2 * np.pi * 1.0 * t) + 0.1 * np.random.default_rng(0).standard_normal(n)
    xs1, ys1 = canvas._envelope(t, sig, xlim=(2.0, 8.0), pixel_width=800)
    xs2, ys2 = cv.build_envelope(t, sig, xlim=(2.0, 8.0), pixel_width=800)
    np.testing.assert_array_equal(xs1, xs2)
    np.testing.assert_array_equal(ys1, ys2)


def test_build_envelope_xlim_none_uses_full_range(qtbot):
    """codex round-2 G22: callers may invoke ``build_envelope`` with
    ``xlim=None``; that must equal ``xlim=(t[0], t[-1])`` rather than
    raise ``TypeError``.
    """
    n = 50_000
    t = np.linspace(0.0, 5.0, n)
    sig = np.sin(2 * np.pi * 2.0 * t)
    xs_none, ys_none = cv.build_envelope(t, sig, xlim=None, pixel_width=600)
    xs_full, ys_full = cv.build_envelope(
        t, sig, xlim=(float(t[0]), float(t[-1])), pixel_width=600
    )
    np.testing.assert_array_equal(xs_none, xs_full)
    np.testing.assert_array_equal(ys_none, ys_full)


def test_timedomain_envelope_thin_wrapper_does_not_accept_none(qtbot):
    """``TimeDomainCanvas._envelope`` is a thin wrapper that keeps its
    required-``xlim`` signature; ``None`` is ``build_envelope``'s
    contract only and must not be propagated into the wrapper to avoid
    inflating the canvas's compatibility surface.
    """
    canvas = cv.TimeDomainCanvas()
    qtbot.addWidget(canvas)
    n = 100
    t = np.linspace(0.0, 1.0, n)
    sig = np.zeros(n)
    # Tuple xlim must work (existing contract).
    canvas._envelope(t, sig, xlim=(0.0, 1.0), pixel_width=200)
    # None must raise — the thin wrapper does NOT widen the contract.
    with pytest.raises(TypeError):
        canvas._envelope(t, sig, xlim=None, pixel_width=200)


# -------------------------------------------------------------------
# PlotCanvas.plot_or_update_heatmap — reuse / rebuild / lifecycle
# -------------------------------------------------------------------


def test_plot_canvas_heatmap_reuses_artists_on_compatible_call(qtbot):
    """Same shape on a second call must reuse ``_heatmap_ax`` /
    ``_heatmap_im`` / ``_heatmap_cbar`` rather than rebuild — and not
    grow ``fig.axes`` because each rebuild adds another colorbar axis.
    """
    canvas = cv.PlotCanvas()
    qtbot.addWidget(canvas)
    matrix1 = np.random.default_rng(0).random((20, 30))
    canvas.plot_or_update_heatmap(
        matrix=matrix1, x_extent=(0, 10), y_extent=(0, 5),
        x_label='Time', y_label='Order', title='t1',
    )
    ax_obj_1 = canvas._heatmap_ax
    im_obj_1 = canvas._heatmap_im
    cbar_ax_1 = canvas._heatmap_cbar.ax
    n_axes_1 = len(canvas.fig.axes)

    matrix2 = np.random.default_rng(1).random((20, 30))   # same shape
    canvas.plot_or_update_heatmap(
        matrix=matrix2, x_extent=(0, 10), y_extent=(0, 5),
        x_label='Time', y_label='Order', title='t2',
    )
    assert canvas._heatmap_ax is ax_obj_1, "heatmap axes object must be reused"
    assert canvas._heatmap_im is im_obj_1, "imshow artist must be reused"
    assert canvas._heatmap_cbar.ax is cbar_ax_1, "colorbar axes must be reused"
    assert len(canvas.fig.axes) == n_axes_1, "axes count should not grow"


def test_plot_canvas_heatmap_rebuilds_on_shape_change(qtbot):
    """When ``matrix.shape`` changes the compat check fails clause 4 and
    we must fall back to clear+rebuild; the new ``imshow`` artist must
    carry the new shape and not raise.
    """
    canvas = cv.PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.plot_or_update_heatmap(
        matrix=np.zeros((20, 30)), x_extent=(0, 10), y_extent=(0, 5),
        x_label='X', y_label='Y', title='small',
    )
    im_obj_1 = canvas._heatmap_im
    canvas.plot_or_update_heatmap(
        matrix=np.zeros((50, 80)),                       # different shape
        x_extent=(0, 10), y_extent=(0, 5),
        x_label='X', y_label='Y', title='big',
    )
    assert canvas._heatmap_im is not im_obj_1, "shape change must rebuild imshow artist"
    assert canvas._heatmap_im.get_array().shape == (50, 80)


def test_plot_canvas_heatmap_to_2subplot_to_heatmap_no_colorbar_ghost(qtbot):
    """Colorbar-ghost invariant: heatmap → user switches to a 2-subplot
    layout (calls ``clear()`` and adds 2 line subplots) → back to
    heatmap. The figure must not retain a stale colorbar axis (which
    would yield 3+ axes), and ``_heatmap_*`` must be reset by
    ``clear()`` so the compat check correctly rebuilds. This guards the
    heatmap → 2-subplot → heatmap round-trip regardless of which
    feature drives the 2-subplot intermediate state.
    """
    canvas = cv.PlotCanvas()
    qtbot.addWidget(canvas)
    canvas.plot_or_update_heatmap(
        matrix=np.ones((10, 15)), x_extent=(0, 10), y_extent=(0, 5),
        x_label='X', y_label='Y', title='heatmap',
    )
    assert len(canvas.fig.axes) == 2   # heatmap + colorbar

    # Simulate a 2-subplot render: clear + 2 line subplots.
    canvas.clear()
    canvas.fig.add_subplot(2, 1, 1).plot([1, 2, 3])
    canvas.fig.add_subplot(2, 1, 2).plot([3, 2, 1])
    assert canvas._heatmap_ax is None
    assert canvas._heatmap_im is None
    assert canvas._heatmap_cbar is None

    # Back to heatmap.
    canvas.plot_or_update_heatmap(
        matrix=np.ones((10, 15)), x_extent=(0, 10), y_extent=(0, 5),
        x_label='X', y_label='Y', title='heatmap2',
    )
    assert len(canvas.fig.axes) == 2   # heatmap + colorbar — no ghost
    assert canvas._heatmap_cbar is not None


# -------------------------------------------------------------------
# Wave 5: new (z_auto, z_floor, z_ceiling, x_*, y_*) signatures
# -------------------------------------------------------------------


def test_color_limits_z_explicit_floor_ceiling():
    """_color_limits accepts (z_auto=False, z_floor, z_ceiling) and returns them.
    _color_limits accepts z_auto=True and returns (nanmin, nanmax)."""
    import numpy as np
    from mf4_analyzer.ui.canvases import SpectrogramCanvas

    sc = SpectrogramCanvas()
    z = np.array([[-50, -10, -5], [-100, -20, 0]], dtype=float)

    vmin, vmax = sc._color_limits(
        z, amplitude_mode='amplitude_db',
        z_auto=False, z_floor=-30.0, z_ceiling=0.0,
    )
    assert (vmin, vmax) == (-30.0, 0.0)

    vmin, vmax = sc._color_limits(
        z, amplitude_mode='amplitude_db', z_auto=True,
        z_floor=999, z_ceiling=999,  # ignored
    )
    assert vmin == -100.0
    assert vmax == 0.0


def test_plot_or_update_heatmap_axis_args(qtbot):
    """plot_or_update_heatmap accepts new (z_auto, z_floor, z_ceiling, x_auto,
    x_min, x_max, y_auto, y_min, y_max) kwargs without TypeError."""
    import numpy as np
    from mf4_analyzer.ui.canvases import PlotCanvas

    pc = PlotCanvas()
    qtbot.addWidget(pc)
    m = np.random.RandomState(42).rand(8, 8)

    pc.plot_or_update_heatmap(
        matrix=m, x_extent=(0, 4), y_extent=(0, 20),
        x_label='Time (s)', y_label='Order',
        title='test', cmap='turbo', interp='bilinear',
        cbar_label='Amplitude',
        amplitude_mode='amplitude_db',
        z_auto=False, z_floor=-30.0, z_ceiling=0.0,
        x_auto=True, x_min=0.0, x_max=0.0,
        y_auto=False, y_min=2.0, y_max=18.0,
    )
    ax = pc.fig.axes[0]
    lo, hi = ax.get_ylim()
    assert abs(lo - 2.0) < 0.01
    assert abs(hi - 18.0) < 0.01
