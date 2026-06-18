"""Chart-compactness constants re-exported from mf4_analyzer.ui.canvases.

Phase D (2026-06-18): TimeDomainCanvas was retired, so tests that required
a live canvas instance (test_timedomain_subplotpars_after_render,
test_ylabel_does_not_overlap_yticks) and tests that used
``inspect.getsource(canvases)`` to verify tight_layout/axis-margin call
sites in the now-deleted canvas bodies (test_axis_hit_margin_used_in_canvases_source,
test_tight_layout_uses_kwargs_in_canvases_source) were removed.

Surviving: module-constant presence guards that do not require a canvas widget.
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
