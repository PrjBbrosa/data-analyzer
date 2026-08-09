"""Pure-function contracts for :mod:`mf4_analyzer.render_profile`.

The module is deliberately UI-neutral: both the interactive FRF canvas and the
GUI-free batch renderer consume the same helpers, so these cases import nothing
from Qt or pyqtgraph.
"""
from __future__ import annotations

import math

import pytest

from mf4_analyzer.render_profile import log_frequency_tick_levels


def _labels(ticks):
    return [label for _coord, label in ticks]


def _coords(ticks):
    return [coord for coord, _label in ticks]


def test_log_frequency_ticks_stay_sparse_decades_across_several_decades():
    # The canvas pins 1 Hz .. 1 kHz; the sparse decade row is the product
    # style and must not gain mantissa clutter just because a ladder exists.
    assert log_frequency_tick_levels(0.0, 3.0) == [
        (0.0, "1"), (1.0, "10"), (2.0, "100"), (3.0, "1000"),
    ]
    # Batch renderer: 1 Hz .. 50 Hz with view padding still holds two decade
    # integers, so it also keeps the sparse row.
    assert log_frequency_tick_levels(-0.08, 1.78) == [(0.0, "1"), (1.0, "10")]


def test_log_frequency_ticks_drop_to_mantissa_ladder_inside_one_decade():
    ticks = log_frequency_tick_levels(math.log10(20.0), math.log10(80.0))

    # Regression: the decade-only rule yielded an empty row here, which made
    # pyqtgraph draw a frequency axis with no labels at all.
    assert ticks
    assert _labels(ticks) == ["20", "50"]
    assert _coords(ticks) == sorted(_coords(ticks))


def test_log_frequency_ticks_use_full_mantissas_when_the_ladder_is_too_coarse():
    # 21 Hz .. 49 Hz contains no 1-2-5 rung, so 1..9 mantissas fill in.
    ticks = log_frequency_tick_levels(math.log10(21.0), math.log10(49.0))

    assert _labels(ticks) == ["30", "40"]


@pytest.mark.parametrize(
    "lo_hz, hi_hz",
    [
        (1.0, 1000.0),
        (1.0, 50.0),
        (20.0, 80.0),
        (21.0, 49.0),
        (31.0, 39.0),
        (100.0, 100.5),
        (0.02, 0.05),
        (0.5, 1.5),
        (997.0, 1003.0),
        (12345.0, 12345.5),
    ],
)
def test_log_frequency_ticks_always_deliver_at_least_two_major_ticks(lo_hz, hi_hz):
    lo_log, hi_log = math.log10(lo_hz), math.log10(hi_hz)
    ticks = log_frequency_tick_levels(lo_log, hi_log)

    assert len(ticks) >= 2
    # Every tick sits inside the requested window and its label is the
    # physical Hz value of its log10 coordinate.
    for coord, label in ticks:
        assert lo_log - 1e-12 <= coord <= hi_log + 1e-12
        assert float(label) == pytest.approx(10.0 ** coord, rel=1e-9)
    assert _coords(ticks) == sorted(_coords(ticks))
    # Narrow windows must not turn into a label soup either.
    assert len(ticks) <= 8


@pytest.mark.parametrize(
    "lo_log, hi_log",
    [
        (1.0, 1.0),
        (2.0, 1.0),
        (float("nan"), 2.0),
        (1.0, float("nan")),
        (float("-inf"), 1.0),
        (1.0, float("inf")),
    ],
)
def test_log_frequency_ticks_return_empty_instead_of_raising(lo_log, hi_log):
    # Callers keep whatever ticks the axis already had; a degenerate view range
    # must never abort a paint.
    assert log_frequency_tick_levels(lo_log, hi_log) == []


def test_render_profile_stays_importable_without_any_gui_toolkit():
    """Both consumers (interactive canvas, GUI-free batch renderer) share this
    module, so importing it must not drag Qt or pyqtgraph in."""
    import subprocess
    import sys

    probe = (
        "import sys;"
        "import mf4_analyzer.render_profile as m;"
        "m.log_frequency_tick_levels(0.0, 1.0);"
        "bad = [n for n in sys.modules"
        " if n.split('.')[0] in ('PyQt5', 'pyqtgraph', 'matplotlib')];"
        "print(','.join(sorted(bad)))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, check=True,
    )
    assert completed.stdout.strip() == ""
