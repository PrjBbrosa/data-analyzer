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
    assert abs(d['right'] - 0.955) < 1e-9
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
    # Task 2.10 dropped SpectrogramCanvas.plot_result's tight_layout call
    # in favor of subplots_adjust(**SPECTROGRAM_SUBPLOT_ADJUST), so the
    # call-site count went 5 -> 4. The guard's intent is "no bare
    # default-padded tight_layout calls"; the lower bound just tracks
    # how many call sites currently exist.
    assert len(calls) >= 4, f"expected >=4 tight_layout call sites, got {len(calls)}"
    for args in calls:
        assert "CHART_TIGHT_LAYOUT_KW" in args, (
            f"tight_layout call without CHART_TIGHT_LAYOUT_KW kwargs: ({args})"
        )


def test_spectrogram_figsize_aligned():
    """Task 2.10: SpectrogramCanvas figsize must align with the other
    canvases (10x6) — the legacy 12x8 wasted horizontal real estate."""
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    assert canvas.fig.get_size_inches().tolist() == [10.0, 6.0]


def test_spectrogram_subplotpars_right_leaves_colorbar_room(qtbot):
    """Task 2.10 (S1-T1 + S1-T3): subplots_adjust(**SPECTROGRAM_SUBPLOT_ADJUST)
    must keep a small right margin so the colorbar tightbbox does not overlap
    the spectrogram axes' tightbbox.

    Notes
    -----
    Per ``pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt`` the bbox
    path returns usable coords under ``QT_QPA_PLATFORM=offscreen`` once
    the figure has been drawn — no need to fall back to a full-canvas
    grab on headless platforms.
    """
    from mf4_analyzer.ui.canvases import SpectrogramCanvas
    canvas = SpectrogramCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 500)
    canvas.show()
    qtbot.waitExposed(canvas)

    # Apply the constant directly — full plot_result requires a
    # SpectrogramResult, which we don't fabricate here. The constant
    # is wired into plot_result by the implementation under test;
    # asserting subplots_adjust honors the constant value is enough
    # to pin the geometry contract.
    canvas.fig.subplots_adjust(
        **__import__(
            'mf4_analyzer.ui.canvases', fromlist=['SPECTROGRAM_SUBPLOT_ADJUST']
        ).SPECTROGRAM_SUBPLOT_ADJUST
    )
    canvas.draw()
    sp = canvas.fig.subplotpars
    assert abs(sp.right - 0.955) < 0.005
    assert abs(sp.left - 0.07) < 0.005
    assert sp.top >= 0.96
