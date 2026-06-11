"""Tests for the module-level ``build_envelope`` helper.

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

The order heatmap's ``PlotCanvas.plot_or_update_heatmap`` reuse tests
were removed when that method was deleted (M5/M6 renderer swap to
``PgHeatmapCanvas``); see ``tests/ui/test_pg_heatmap_canvas.py``.
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
# M9 retired the matplotlib SpectrogramCanvas (FFT-vs-Time moved to
# PgHeatmapCanvas with_slice=True). Its ``_color_limits`` z-range helper
# test was removed with the class; the pg canvas derives z-levels inline
# in plot_result (z_floor/z_ceiling clip + nanmin/nanmax for z_auto) and
# the rendered levels are pinned in tests/ui/test_pg_heatmap_canvas.py
# (``_img.getLevels()`` equals the explicit window).
# -------------------------------------------------------------------
