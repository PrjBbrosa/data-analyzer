"""Task 2.9: compactness constants in mf4_analyzer.ui.canvases.

These tests pin three module-level constants and verify that
``tight_layout(**CHART_TIGHT_LAYOUT_KW)`` actually produces the
compact subplotpars we expect (left margin tight, top margin tight,
no overlap between y-label and y-tick labels).
"""
import pytest


def test_chart_tight_layout_kw_constant_defined():
    from mf4_analyzer.ui import canvases
    assert hasattr(canvases, 'CHART_TIGHT_LAYOUT_KW')
    assert canvases.CHART_TIGHT_LAYOUT_KW.get('pad') == 0.4
    assert canvases.CHART_TIGHT_LAYOUT_KW.get('h_pad') == 0.6
    assert canvases.CHART_TIGHT_LAYOUT_KW.get('w_pad') == 0.4


def test_axis_hit_margin_constant_defined():
    from mf4_analyzer.ui import canvases
    assert canvases.AXIS_HIT_MARGIN_PX == 45


# M9 retired the matplotlib SpectrogramCanvas; SPECTROGRAM_SUBPLOT_ADJUST
# (its colorbar-margin gridspec constant) is no longer re-exported from
# mf4_analyzer.ui.canvases because nothing on the FFT/time path consumes
# it. The constant itself still lives in mf4_analyzer._chart_kw. The
# re-export-presence test was removed with that consumer.


def test_timedomain_subplotpars_after_render(qtbot):
    from mf4_analyzer.ui.canvases import (
        TimeDomainCanvas, CHART_TIGHT_LAYOUT_KW,
    )
    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 500)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    ax.plot([0, 1, 2], [0, 1, 4])
    ax.set_ylabel("amplitude")
    canvas.fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)
    canvas.draw()
    sp = canvas.fig.subplotpars
    assert sp.left <= 0.10
    assert sp.top >= 0.93


def test_ylabel_does_not_overlap_yticks(qtbot):
    """S1-T4: y-label render bbox must not overlap y-tick label bbox."""
    from mf4_analyzer.ui.canvases import (
        TimeDomainCanvas, CHART_TIGHT_LAYOUT_KW,
    )
    canvas = TimeDomainCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(800, 500)
    canvas.show()
    qtbot.waitExposed(canvas)
    ax = canvas.fig.add_subplot(111)
    ax.plot(range(100), range(100))
    ax.set_ylabel("Velocity (m/s)", labelpad=12)
    canvas.fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)
    canvas.draw()
    renderer = canvas.fig.canvas.get_renderer()
    ylabel_bbox = ax.yaxis.label.get_window_extent(renderer)
    tick_bboxes = [t.label1.get_window_extent(renderer) for t in ax.yaxis.get_major_ticks()]
    for tb in tick_bboxes:
        assert not ylabel_bbox.overlaps(tb), (
            f"ylabel overlaps tick: {ylabel_bbox} vs {tb}"
        )


def test_axis_hit_margin_used_in_canvases_source():
    """Guard: canvas hit-test call sites must use AXIS_HIT_MARGIN_PX.

    Double-click handling now routes through target_axes_for_event while hover
    handling still calls find_axis_for_dblclick directly; both paths must use
    the shared margin constant instead of a literal.
    """
    import inspect
    from mf4_analyzer.ui import canvases
    src = inspect.getsource(canvases)
    import re
    call_pattern = re.compile(r"(?:find_axis_for_dblclick|target_axes_for_event)\([^)]*\)")
    calls = call_pattern.findall(src)
    assert len(calls) >= 4, f"expected >=4 call sites, got {len(calls)}: {calls}"
    for call in calls:
        assert "AXIS_HIT_MARGIN_PX" in call, (
            f"call site still uses literal margin: {call}"
        )
        assert ", 45)" not in call, (
            f"literal `45` margin survived in: {call}"
        )


def test_tight_layout_uses_kwargs_in_canvases_source():
    """Guard: every `self.fig.tight_layout(...)` call inside canvases.py must
    pass `**CHART_TIGHT_LAYOUT_KW` so we don't accidentally regress to a
    bare default-padded `tight_layout()` call.
    """
    import inspect, re
    from mf4_analyzer.ui import canvases
    src = inspect.getsource(canvases)
    pattern = re.compile(r"self\.fig\.tight_layout\(([^)]*)\)")
    calls = pattern.findall(src)
    # M9 retired SpectrogramCanvas (FFT-vs-Time moved to pyqtgraph), but
    # its plot_result used subplots_adjust, not tight_layout, so this
    # source-scan guard still covers the surviving mpl canvases
    # (TimeDomainCanvas / PlotCanvas). The guard's intent is "no bare
    # default-padded tight_layout calls"; the lower bound just tracks how
    # many call sites currently exist.
    assert len(calls) >= 4, f"expected >=4 tight_layout call sites, got {len(calls)}"
    for args in calls:
        assert "CHART_TIGHT_LAYOUT_KW" in args, (
            f"tight_layout call without CHART_TIGHT_LAYOUT_KW kwargs: ({args})"
        )


# M9 retired the matplotlib SpectrogramCanvas (FFT-vs-Time moved to
# PgHeatmapCanvas with_slice=True). Its figsize-alignment and
# subplots_adjust/colorbar-margin tests were matplotlib-gridspec-internal
# (fig.get_size_inches, fig.subplotpars) and could not survive the pg swap;
# the pg canvas's layout/colorbar geometry is verified in
# tests/ui/test_pg_heatmap_canvas.py.
