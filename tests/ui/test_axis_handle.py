"""Tests for ``mf4_analyzer.ui._axis_handle.MplAxisHandle``.

Task 3 of the pyqtgraph TimeDomain migration plan
(``docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md``)
introduces an ``AxisHandle`` Protocol so ``ChartOptionsDialog`` and
``_axis_interaction`` can target both matplotlib axes and (later) a
pyqtgraph ViewBox/AxisItem pair.

These tests pin every signature in design §5.3 against a REAL
matplotlib ``Axes`` (no MagicMocks) per the
``codex-phantom-api-surface-guards`` defensive gate. The pyqtgraph stub
class is intentionally left as ``NotImplementedError`` and is exercised
only by a "raises on use" probe so T5 can fill it later.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from matplotlib.figure import Figure


def _axes_with_data():
    """Build a real Axes wired into a Figure with one visible line."""
    fig = Figure(figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([0.0, 1.0, 2.0], [0.0, 1.0, 4.0], color="#1769e0", label="curve")
    ax.set_xlim(0.0, 2.0)
    ax.set_ylim(0.0, 4.0)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("value")
    ax.set_title("title")
    fig.canvas.draw()
    return fig, ax


def test_mpl_axis_handle_get_xlim_and_set_xlim():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)

    assert h.get_xlim() == pytest.approx((0.0, 2.0))
    h.set_xlim(1.0, 5.0)
    assert ax.get_xlim() == pytest.approx((1.0, 5.0))


def test_mpl_axis_handle_get_ylim_and_set_ylim():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)

    assert h.get_ylim() == pytest.approx((0.0, 4.0))
    h.set_ylim(-1.0, 99.0)
    assert ax.get_ylim() == pytest.approx((-1.0, 99.0))


def test_mpl_axis_handle_xlabel_getter_setter():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)

    assert h.get_xlabel() == "time (s)"
    h.set_xlabel("时间")
    assert ax.get_xlabel() == "时间"


def test_mpl_axis_handle_ylabel_getter_setter():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)

    assert h.get_ylabel() == "value"
    h.set_ylabel("幅值")
    assert ax.get_ylabel() == "幅值"


def test_mpl_axis_handle_title_getter_setter():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)

    assert h.get_title() == "title"
    h.set_title("新标题")
    assert ax.get_title() == "新标题"


def test_mpl_axis_handle_xscale_setter():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    ax.set_xlim(0.1, 10.0)  # log-safe range
    h = MplAxisHandle(ax)

    h.set_xscale("log")
    assert ax.get_xscale() == "log"
    h.set_xscale("linear")
    assert ax.get_xscale() == "linear"


def test_mpl_axis_handle_yscale_setter():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    ax.set_ylim(0.1, 100.0)
    h = MplAxisHandle(ax)

    h.set_yscale("log")
    assert ax.get_yscale() == "log"
    h.set_yscale("linear")
    assert ax.get_yscale() == "linear"


def test_mpl_axis_handle_autoscale_both_default():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    ax.set_xlim(99.0, 100.0)  # off-data so autoscale visibly moves it
    h = MplAxisHandle(ax)

    h.autoscale()
    xlo, xhi = ax.get_xlim()
    assert xlo < 99.0  # autoscale snapped to data


def test_mpl_axis_handle_autoscale_x_only():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    ax.set_xlim(99.0, 100.0)
    h = MplAxisHandle(ax)

    h.autoscale(axis="x")
    xlo, _xhi = ax.get_xlim()
    assert xlo < 99.0


def test_mpl_axis_handle_grid_toggle():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)

    h.grid(True)
    gridlines = list(ax.xaxis.get_gridlines()) + list(ax.yaxis.get_gridlines())
    assert any(gl.get_visible() for gl in gridlines)

    h.grid(False)
    gridlines = list(ax.xaxis.get_gridlines()) + list(ax.yaxis.get_gridlines())
    assert not any(gl.get_visible() for gl in gridlines)


def test_mpl_axis_handle_get_lines_returns_line_handles():
    """``get_lines()`` must return ``LineHandle`` wrappers, not raw
    matplotlib ``Line2D`` artists, so callers see the same protocol on
    matplotlib and pyqtgraph backends."""
    from mf4_analyzer.ui._axis_handle import LineHandle, MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)

    lines = h.get_lines()
    assert len(lines) == 1
    line = lines[0]
    # Each returned object must satisfy the LineHandle protocol.
    assert hasattr(line, "get_label")
    assert hasattr(line, "get_color")
    assert hasattr(line, "set_color")
    assert hasattr(line, "get_visible")
    # Sanity check against the actual matplotlib artist underneath.
    raw = ax.get_lines()[0]
    assert line.get_label() == raw.get_label()
    assert line.get_color() == raw.get_color()
    assert line.get_visible() == raw.get_visible()


def test_mpl_axis_handle_line_handle_set_color_round_trips():
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)

    line = h.get_lines()[0]
    line.set_color("#ef4444")
    assert ax.get_lines()[0].get_color() == "#ef4444"


def test_mpl_axis_handle_get_mappables_empty_for_line_only_axes():
    """An axes with only Line2D artists has no images/collections, so
    ``get_mappables`` must return an empty list (TimeDomain case per
    design §5.3)."""
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)

    assert h.get_mappables() == []


def test_mpl_axis_handle_get_mappables_includes_images_and_collections():
    """An axes carrying an image and a collection must expose them as
    mappables so the ColorMap/ColorScale group of ChartOptionsDialog
    keeps working."""
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    fig = Figure(figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)
    data = np.arange(16, dtype=float).reshape(4, 4)
    im = ax.imshow(data, cmap="viridis")
    h = MplAxisHandle(ax)

    mappables = h.get_mappables()
    assert im in mappables


def test_mpl_axis_handle_request_redraw_delegates_to_canvas():
    """``request_redraw`` must invoke the underlying canvas's
    ``draw_idle`` so the dialog can trigger a redraw after Apply."""
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    fig = Figure(figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)

    calls = {"n": 0}

    class _Probe:
        def draw_idle(self):
            calls["n"] += 1

    fig.canvas = _Probe()  # type: ignore[assignment]
    h = MplAxisHandle(ax)
    h.request_redraw()
    assert calls["n"] == 1


def test_mpl_axis_handle_request_redraw_is_noop_when_no_canvas():
    """If the Axes has no canvas (rare edge), ``request_redraw`` must
    not raise."""
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    fig = Figure(figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)
    fig.canvas = None  # type: ignore[assignment]
    h = MplAxisHandle(ax)
    h.request_redraw()  # must not raise


def test_mpl_axis_handle_wraps_axes_property():
    """``handle.axes`` must remain accessible for code that still
    needs the raw matplotlib Axes during the migration window
    (e.g. ``_sync_curve_axis_color``)."""
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    _fig, ax = _axes_with_data()
    h = MplAxisHandle(ax)
    assert h.axes is ax


def test_pg_axis_handle_is_filled_in_after_t5(qapp):
    """T5 replaced the ``NotImplementedError`` stub of ``PgAxisHandle``
    with real pyqtgraph delegation. The deeper Protocol-conformance
    tests live in ``tests/ui/test_pg_timedomain_canvas.py`` (which
    constructs a real ``GraphicsLayoutWidget``); here we only smoke-check
    that ``get_xlim`` no longer raises ``NotImplementedError`` when
    invoked on a properly-constructed handle."""
    import os
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")
    import pyqtgraph as pg
    from mf4_analyzer.ui._axis_handle import PgAxisHandle

    glw = pg.GraphicsLayoutWidget()
    plot_item = glw.addPlot(row=0, col=0)
    h = PgAxisHandle(plot_item=plot_item)
    # Round-trip should not raise.
    h.set_xlim(0.0, 1.0)
    lo, hi = h.get_xlim()
    assert lo == pytest.approx(0.0)
    assert hi == pytest.approx(1.0)
