"""Small Qt/pyqtgraph plot helpers with no Analyzer UI dependency."""
from __future__ import annotations

import pyqtgraph as pg


def hide_native_auto_button(plot) -> None:
    """Hide pyqtgraph's built-in lower-left auto-range button."""
    hide = getattr(plot, "hideButtons", None)
    if callable(hide):
        hide()


def show_major_grid_left_bottom_only(plot, *, x=True, y=True, alpha=0.25):
    """Enable major grid on left+bottom and force top/right off."""
    plot.showGrid(x=bool(x), y=bool(y), alpha=alpha)
    for name in ("top", "right"):
        try:
            plot.getAxis(name).setGrid(False)
        except Exception:
            pass


def _vertical_label_margin(axis) -> float:
    """Re-derive pyqtgraph's ``m`` slack from ``hideOverlappingLabels``.

    Mirrors ``AxisItem.boundingRect`` (pyqtgraph 0.14, AxisItem.py:944-954)
    exactly: ``True`` → 0, ``False`` → 15, anything numeric → that number,
    anything else → 0.
    """
    try:
        hide_overlapping = axis.style["hideOverlappingLabels"]
    except Exception:
        return 0.0
    if hide_overlapping is True:
        return 0.0
    if hide_overlapping is False:
        return 15.0
    try:
        return float(int(hide_overlapping))
    except (TypeError, ValueError):
        return 0.0


class GridLabelSlackAxisItem(pg.AxisItem):
    """Vertical ``AxisItem`` that keeps its tick-label slack when a grid is on.

    Why this exists (D2, 2026-08-04 "纵坐标只显示一半"):
        A left/right ``AxisItem`` is always built with
        ``hideOverlappingLabels = False`` (AxisItem.py:66-69) precisely so that
        "labels on vertical axis [can] extend above and below the length of the
        axis" — that maps to ``m = 15`` px of vertical slack in
        ``boundingRect``. The first and last tick labels are centred ON the
        axis ends, so half of each one legitimately pokes past the end and
        needs that slack.

        But ``boundingRect`` early-returns on the grid branch
        (AxisItem.py:956-961): when the axis is linked to a view AND
        ``self.grid is not False`` it returns ``geometry ∪ linkedViewRect`` and
        the ``m`` slack is never applied. ``generateDrawSpecs`` then filters
        every tick label through ``if br & rect != rect: continue``
        (AxisItem.py:1688-1692) — a label that does not fit ENTIRELY inside the
        bounding rect is not clipped, it is **dropped**. So merely switching
        the Y grid on silently deletes the topmost and bottommost tick values:

            y range [0, 1], grid off → ['0', '0.25', '0.5', '0.75', '1']
            y range [0, 1], grid on  → ['0.25', '0.5', '0.75']

        Every chart in this app enables the left/bottom grid
        (:func:`show_major_grid_left_bottom_only`), so every chart could lose
        its end-of-range Y tick values.

    Fix: re-apply the same ``±m`` vertical adjustment on the grid branch, so
    the two branches agree about how far a vertical tick label may extend.
    A LARGER bounding rect is always safe for QGraphicsScene (it only widens
    the repaint/index region; too-small is what produces artifacts).

    Scope notes:
        * Horizontal (top/bottom) axes are returned untouched — they are built
          with ``hideOverlappingLabels = True`` (``m = 0``), so the grid branch
          already loses nothing.
        * Only the vertical slack is restored. The non-grid branch's
          ``-min(0, tickLength)`` horizontal extension is already covered by
          the grid branch's union with the linked-view rect.
        * This does NOT address the pinned-width defect (D1) — an axis whose
          width is pinned too narrow still drops labels horizontally. The two
          are independent and are fixed separately.
    """

    def boundingRect(self):
        rect = super().boundingRect()
        if self.orientation not in ("left", "right"):
            return rect
        # Detect the same early-return branch AxisItem.boundingRect took. When
        # it is not taken, the base class already applied the slack itself.
        try:
            on_grid_branch = (
                self.grid is not False and self.linkedView() is not None
            )
        except Exception:
            return rect
        if not on_grid_branch:
            return rect
        margin = _vertical_label_margin(self)
        if not margin:
            return rect
        return rect.adjusted(0, -margin, 0, margin)


__all__ = [
    "GridLabelSlackAxisItem",
    "hide_native_auto_button",
    "show_major_grid_left_bottom_only",
]
