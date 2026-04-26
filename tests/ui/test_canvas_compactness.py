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


def test_spectrogram_subplot_adjust_constant_defined():
    from mf4_analyzer.ui import canvases
    assert hasattr(canvases, 'SPECTROGRAM_SUBPLOT_ADJUST')
    d = canvases.SPECTROGRAM_SUBPLOT_ADJUST
    assert abs(d['left'] - 0.07) < 1e-9
    assert abs(d['right'] - 0.93) < 1e-9
    assert abs(d['top'] - 0.97) < 1e-9
    assert abs(d['bottom'] - 0.09) < 1e-9


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
    """Guard: the literal `, 45)` should not appear in find_axis_for_dblclick
    call sites; all call sites must use the AXIS_HIT_MARGIN_PX constant.
    """
    import inspect
    from mf4_analyzer.ui import canvases
    src = inspect.getsource(canvases)
    # Each find_axis_for_dblclick call must reference the constant.
    # Count occurrences of the constant in find_axis_for_dblclick(...) lines.
    import re
    call_pattern = re.compile(r"find_axis_for_dblclick\([^)]*\)")
    calls = call_pattern.findall(src)
    assert len(calls) >= 6, f"expected >=6 call sites, got {len(calls)}: {calls}"
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
    assert len(calls) >= 5, f"expected >=5 tight_layout call sites, got {len(calls)}"
    for args in calls:
        assert "CHART_TIGHT_LAYOUT_KW" in args, (
            f"tight_layout call without CHART_TIGHT_LAYOUT_KW kwargs: ({args})"
        )
