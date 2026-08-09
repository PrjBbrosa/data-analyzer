"""Small Qt/pyqtgraph plot helpers with no Analyzer UI dependency."""
from __future__ import annotations

import pyqtgraph as pg
from PyQt5.QtCore import Qt

from mf4_analyzer.ui_kit.ticks_math import bounded_tick_strings


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


# pyqtgraph 0.14 pushes the axis LINE one pixel off the plot rect, away from
# the data (AxisItem.generateDrawSpecs, AxisItem.py:1446-1473: ``left_offset =
# -1.0`` / ``right_offset = 1.0`` applied on the across-the-axis coordinate).
# The same offsets are also applied along the axis, where they are wanted —
# they lengthen the line by a pixel at each end so neighbouring frame lines
# meet at the corners. Only the across component is cancelled here.
_AXIS_LINE_BORDER_NUDGE = {
    "left": (1.0, 0.0),
    "right": (-1.0, 0.0),
    "top": (0.0, 1.0),
    "bottom": (0.0, -1.0),
}


def _linked_view_paints_border(axis) -> bool:
    """True when this axis's ViewBox will stroke its own rect underneath it.

    ``ViewBox.paint`` draws the border whenever ``self.border`` is not None
    (ViewBox.py:1735-1740) — and ``setBorder(None)`` stores a *NoPen* QPen
    rather than None, so the pen style has to be checked too. That is the
    same trap ``heatmap_canvas._apply_neutral_axis_frame`` documents when it
    clears ``vb.border`` by hand.
    """
    view = axis.linkedView()
    border = getattr(view, "border", None) if view is not None else None
    if border is None:
        return False
    try:
        return border.style() != Qt.NoPen
    except Exception:
        return False


class BorderAlignedAxisItem(pg.AxisItem):
    """``AxisItem`` whose axis line lands ON its ViewBox border, not beside it.

    Why this exists (2026-08-04 "每个图左边框多了一条竖线"):
        A chart that draws BOTH a ``ViewBox`` border and axis lines gets two
        strokes per shared edge. They used to be the same stroke; pyqtgraph
        0.14 moved the axis line one pixel outwards (see
        ``_AXIS_LINE_BORDER_NUDGE``), so the pair separates: the border sits
        on the ViewBox rect and the axis line one pixel outside it. On a
        Retina display that is two device-pixel columns with a white one
        between them, which reads as a spurious extra vertical line hugging
        the left edge of every plot — measured at device x=107 (axis line)
        and x=109 (border) on the time-domain subplot canvas.

    Fix: cancel the across-the-axis component of pyqtgraph's offset, so the
    axis line coincides with the border again.

    Gated on the border actually being painted, because the two frame styles
    in this app are mutually exclusive and only one of them has the problem:

    * time-domain canvas and the batch exporter's chart plots draw a
      ``vb.setBorder`` frame and let the axes stroke over it → nudged;
    * the analysis canvases compose the frame out of four axis lines and
      clear the border instead (``_apply_neutral_axis_frame``) → left alone,
      so their frame keeps meeting exactly where it does today.

    The check runs per ``generateDrawSpecs`` rather than at construction:
    ``_builder`` sets a border in ``_new_plot`` and clears it again in
    ``_apply_analysis_frame``, so the answer is not known until paint time.
    """

    def generateDrawSpecs(self, p):
        specs = super().generateDrawSpecs(p)
        if specs is None:
            return specs
        nudge = _AXIS_LINE_BORDER_NUDGE.get(self.orientation)
        if nudge is None or not _linked_view_paints_border(self):
            return specs
        axis_spec, tick_specs, text_specs = specs
        pen, p1, p2 = axis_spec
        shift = pg.Point(*nudge)
        return (pen, p1 + shift, p2 + shift), tick_specs, text_specs


class FrfMinorTickAxisItem(BorderAlignedAxisItem):
    """Bottom axis that accepts explicit FRF log minor-grid tick levels."""

    def set_frf_log_ticks(self, major_ticks, minor_values) -> None:
        self._frf_minor_tick_values = tuple(float(value) for value in minor_values)
        self.setTicks([
            list(major_ticks),
            [(float(value), "") for value in self._frf_minor_tick_values],
        ])

class GridLabelSlackAxisItem(BorderAlignedAxisItem):
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
        * Keeping the end labels is only half the job: they are centred ON the
          axis end, so on stacked subplots they land in the neighbouring row.
          ``generateDrawSpecs`` below pulls them back inside.
        * ``tickStrings`` below bounds how WIDE a label may get in the first
          place; that is a separate defect from either of the above.
    """

    def tickStrings(self, values, scale, spacing):
        """Bound the printed digit count of an automatically ticked Y axis.

        Why (2026-08-09 "纵坐标 35.0000000034 把 canvas 推到右边"): pyqtgraph's
        default formatting has no exit from its fixed-point branch, so an axis
        framed onto float64 rounding residue emits 18-character labels and
        ``pin_left_axes_to_common_width`` pins every subplot row's left axis to
        the ~143 px they measure. See ``ui_kit.ticks_math.bounded_tick_strings``
        for the full mechanism and for why ordinary axes come out unchanged.

        Vertical only. Horizontal axes pay for a long label in a dimension they
        have to spare, and the time-domain X path already backs off on label
        collision (``tick_density._fit_x_tick_labels``) — re-formatting under
        it would only perturb which ticks that fit chooses. Log mode has its
        own ``logTickStrings`` and is left to pyqtgraph.

        This is a SAFETY NET for ranges that arrive from outside auto-framing
        (wheel zoom, a restored project range, a manually entered range);
        ``_frame_handle_y`` is what stops auto-framing producing them.
        """
        if self.orientation not in ("left", "right") or self.logMode:
            return super().tickStrings(values, scale, spacing)
        try:
            return bounded_tick_strings(values, scale, spacing)
        except (TypeError, ValueError, OverflowError):
            return super().tickStrings(values, scale, spacing)

    def generateDrawSpecs(self, p):
        """Keep every end-of-range tick label inside this axis's own span.

        Why (2026-08-04 "上下两个图的数字有重叠"):
            ``boundingRect`` above stops pyqtgraph dropping the first/last
            tick label, but it does not move them: ``generateDrawSpecs``
            centres a tick label on its tick (AxisItem.py:1676,
            ``x - height/2``), and the first/last tick sits exactly on the end
            of the axis whenever the view range ends on a tick — e.g. a
            constant signal autoranged to [-1, 1]. Half of a ~13 px label
            therefore hangs ~6.5 px past the row.

            Stacked subplot rows are only 5 px apart
            (``canvas.py`` ``ci.setSpacing(2)`` plus the PlotItem margins), so
            the upper row's ``-1.0`` and the lower row's ``1.0`` are drawn on
            top of each other. Before the slack was restored both were simply
            missing, which is how this stayed invisible.

        Fix: translate an overhanging label back inside the axis rect instead
        of dropping it or buying space for it. The label stops being exactly
        centred on its grid line (by at most half its height) but stays
        readable, adjacent rows can no longer collide, and no chart area is
        given up — a per-row spacing increase would have cost ~9 px per
        boundary, i.e. over 10% of the plot height at the 12-row maximum.

        Only vertical axes are touched. Horizontal ones are built with
        ``hideOverlappingLabels = True``, so pyqtgraph drops an overhanging X
        label rather than letting it escape, and the tick-density back-off
        (``test_x_tick_target_count_backs_off_before_label_overlap``) is what
        keeps them apart.
        """
        specs = super().generateDrawSpecs(p)
        if specs is None or self.orientation not in ("left", "right"):
            return specs
        axis_spec, tick_specs, text_specs = specs
        bounds = self.mapRectFromParent(self.geometry())
        top, bottom = bounds.top(), bounds.bottom()
        clamped = []
        for rect, flags, text in text_specs:
            # A label taller than the whole axis cannot be made to fit; leave
            # it centred rather than pinning it to an arbitrary end.
            if rect.height() <= bounds.height():
                if rect.top() < top:
                    rect = rect.translated(0.0, top - rect.top())
                elif rect.bottom() > bottom:
                    rect = rect.translated(0.0, bottom - rect.bottom())
            clamped.append((rect, flags, text))
        return axis_spec, tick_specs, clamped

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
    "BorderAlignedAxisItem",
    "FrfMinorTickAxisItem",
    "GridLabelSlackAxisItem",
    "hide_native_auto_button",
    "show_major_grid_left_bottom_only",
]
