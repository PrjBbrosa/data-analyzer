"""Unit tests for the shared nice-number tick math helpers.

These live in ``mf4_analyzer.ui_kit.ticks_math`` (the lowest UI layer) so
both the Analyzer pyqtgraph canvas and the Cockpit live-card sparklines can
reuse the same graticule math without importing ``ui.*``.
"""
from mf4_analyzer.ui_kit.ticks_math import _nice_per_div, _frame_to_nice, _fmt_tick


def test_nice_per_div_snaps_up():
    assert _nice_per_div(0.7) == 0.8
    assert _nice_per_div(23) == 25


def test_frame_to_nice_returns_n_plus_one_ticks():
    bottom, top, ticks = _frame_to_nice(0.0, 9.7, 4)
    assert len(ticks) == 5 and bottom <= 0.0 and top >= 9.7


def test_fmt_tick_compact():
    assert _fmt_tick(0.0) == "0"
    assert _fmt_tick(1500) == "1500"
