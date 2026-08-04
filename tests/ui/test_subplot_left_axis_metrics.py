"""D1 regression: the time-domain subplot left-axis pin must fit its ticks.

``_unify_subplot_left_axis_widths`` pins every subplot row's left ``AxisItem``
to one width so the shared time grid is not skewed. It used to compute that
width by releasing the pin (``setWidth(None)``) and immediately reading
``AxisItem.width()`` back — but ``setWidth`` moves only size hints while
``width()`` reports realized geometry, and nothing activated a layout in
between, so the read returned the width that was already pinned. The pin was
a fixed point of itself, frozen at whatever a pre-first-paint
``AxisItem.textWidth`` of 30 produced (~53 px). Any tick label too wide for
that box is not clipped, it is DROPPED entirely by
``AxisItem.generateDrawSpecs`` (``if br & rect != rect: continue``), so a rack
force row spanning +/-5000 N drew the single label ``'0'``.

Everything here is asserted against ``generateDrawSpecs``' textSpecs and
``QFontMetrics`` numbers. Never assert rendered ink: the Qt install on the
development box that produced these cases has no font directory, so offscreen
renders carry no text at all.

Covers items 1 and 5 of section 6.1 in
``docs/analyzer/plans/2026-08-04-y-axis-tick-label-clipping-design.md``.
"""
import numpy as np
import pyqtgraph as pg
import pytest
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui_kit.axis_metrics import (
    axis_tick_texts,
    left_axis_width_for_ticks,
)


# Realized geometry and font metrics are both floats; a sub-pixel shortfall is
# not the bug under test (a dropped label needs whole pixels of shortfall).
_EPS = 0.5

_T = np.linspace(0.0, 30.0, 2000, dtype=np.float64)

# EPS signals: steering-wheel torsion / motor torque are 1-2 character labels,
# rack force is the 5-character one that used to fall off the axis.
_NARROW_ROWS = [
    ("torsion", True, _T, 1.5 * np.sin(_T), "#e04040", "Nm", "f1"),
    ("motor_torque", True, _T, 2.2 * np.sin(_T), "#e08040", "Nm", "f1"),
]
_WIDE_ROW = ("rack_force", True, _T, 5000.0 * np.sin(_T), "#7070e0", "N", "f1")


@pytest.fixture
def drawn_left_labels(monkeypatch):
    """Report the tick strings pyqtgraph actually emitted for a left axis.

    ``generateDrawSpecs`` is where the drop happens, and its third return
    element is the list of ``(rect, flags, text)`` specs that survived the
    fit check — the only trustworthy "what got drawn" signal available
    without inspecting pixels.
    """
    original = pg.AxisItem.generateDrawSpecs

    def _recording(self, p):
        out = original(self, p)
        if out is not None and self.orientation == "left":
            self._recorded_tick_texts = [spec[2] for spec in out[2]]
        return out

    monkeypatch.setattr(pg.AxisItem, "generateDrawSpecs", _recording)
    return lambda axis: getattr(axis, "_recorded_tick_texts", None)


def _canvas():
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(1000, 600)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _settle(canvas):
    """Drain queued layout work and force one paint.

    ``AxisItem.textWidth`` and the recorded textSpecs both only exist after a
    paint, and ``grab()`` is the cheapest way to demand one offscreen.
    """
    QCoreApplication.processEvents()
    canvas.grab()
    QCoreApplication.processEvents()


def _left_axes(canvas):
    return [handle._ax("left") for handle in canvas.axes_list]


def test_added_wide_label_row_widens_every_subplot_left_axis(
    qapp, drawn_left_labels,
):
    """Section 6.1 item 1: adding a +/-5000 N row must re-pin the axes wider.

    Two narrow rows settle first so a too-narrow pin is already in place, which
    is exactly the "add a View / merge Views" sequence users reported.
    """
    canvas = _canvas()
    canvas.plot_channels(list(_NARROW_ROWS), mode="subplot")
    _settle(canvas)

    canvas.plot_channels(list(_NARROW_ROWS) + [_WIDE_ROW], mode="subplot")
    _settle(canvas)

    axes = _left_axes(canvas)
    assert len(axes) == 3, "expected one subplot row per channel"

    for index, axis in enumerate(axes):
        assert axis is not None
        needed = left_axis_width_for_ticks(axis)
        realized = float(axis.width())
        assert realized + _EPS >= needed, (
            f"row {index}: left axis pinned to {realized:.1f}px but its tick "
            f"strings {axis_tick_texts(axis)!r} need {needed:.1f}px"
        )

        drawn = drawn_left_labels(axis)
        assert drawn is not None, f"row {index}: axis never painted"
        missing = [text for text in axis_tick_texts(axis) if text not in drawn]
        assert not missing, (
            f"row {index}: pyqtgraph dropped tick labels {missing!r}; "
            f"drawn={drawn!r} width={realized:.1f}px need={needed:.1f}px"
        )


def test_repeated_unify_never_narrows_the_left_axes(qapp):
    """Section 6.1 item 5: the unifier's fixed point must be the right one.

    Two clauses, and only the second one had teeth against the old code:

    * monotonicity across back-to-back calls — the old implementation was
      trivially monotone because it was *frozen*, so this alone cannot catch
      the defect;
    * the width it settles on must cover what the ticks actually need. The
      old fixed point sat at a stale pre-paint ~53px regardless of how many
      times it ran.
    """
    canvas = _canvas()
    canvas.plot_channels(list(_NARROW_ROWS) + [_WIDE_ROW], mode="subplot")
    _settle(canvas)

    axes = _left_axes(canvas)
    assert len(axes) == 3

    canvas._unify_subplot_left_axis_widths()
    _settle(canvas)
    first = [float(axis.width()) for axis in axes]

    canvas._unify_subplot_left_axis_widths()
    _settle(canvas)
    second = [float(axis.width()) for axis in axes]

    for index, (before, after) in enumerate(zip(first, second)):
        assert after + _EPS >= before, (
            f"row {index}: second unify narrowed the left axis "
            f"{before:.1f}px -> {after:.1f}px"
        )

    for index, (axis, width) in enumerate(zip(axes, first)):
        needed = left_axis_width_for_ticks(axis)
        assert width + _EPS >= needed, (
            f"row {index}: unify settled on {width:.1f}px, below the "
            f"{needed:.1f}px its tick strings {axis_tick_texts(axis)!r} need"
        )
