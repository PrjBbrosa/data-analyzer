"""Shared split/collapse controls and layout alignment for two-row canvases."""
from __future__ import annotations

from PyQt5.QtCore import QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QFrame, QWidget

from mf4_analyzer.ui_kit.axis_metrics import pin_left_axes_to_common_width


# Minimum PlotItem heights enforced while dragging the split divider, so a drag
# can never fully starve either plot (full collapse is the triangle's job).
_SPLIT_MIN_TOP = 90
_SPLIT_MIN_BOTTOM = 70
# Vertical gap between the two stacked plots: wide enough for the divider line
# to read as a separator in clear whitespace (not merged with the plot frames).
_SPLIT_ROW_SPACING = 18
# Bottom-plot height (px) below which a divider drag collapses the lower plot.
_SPLIT_COLLAPSE_AT = 40


class _SplitDivider(QWidget):
    """Thin draggable horizontal divider drawn between two stacked plots."""

    drag_started = pyqtSignal()
    drag_delta = pyqtSignal(int)
    drag_finished = pyqtSignal()
    reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("plotSplitDivider")
        self.setFixedHeight(9)
        self.setCursor(Qt.SizeVerCursor)
        self._press_y = None

    def _hot(self):
        return self._press_y is not None or self.underMouse()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            y = self.height() / 2.0
            hot = self._hot()
            color = QColor("#2563eb") if hot else QColor("#c7d2e2")
            painter.setPen(QPen(color, 2.0 if hot else 1.0))
            painter.drawLine(QPointF(0.0, y), QPointF(float(self.width()), y))
        finally:
            painter.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_y = e.globalPos().y()
            self.update()
            self.drag_started.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press_y is not None:
            self.drag_delta.emit(int(self._press_y - e.globalPos().y()))
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press_y is not None:
            self._press_y = None
            self.update()
            self.drag_finished.emit()
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.reset_requested.emit()
        e.accept()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class _CollapsedRail(QFrame):
    """Thin horizontal rail shown when the lower plot is folded away."""

    expand_requested = pyqtSignal()
    HEIGHT_PX = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("plotCollapsedRail")
        self.setFixedHeight(self.HEIGHT_PX)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("展开下图")
        self._hover = False

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.expand_requested.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, event):
        super().paintEvent(event)  # QSS faint bg + top border
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            color = QColor("#2563eb") if self._hover else QColor("#7b8699")
            cx, cy = self.width() / 2.0, self.height() / 2.0
            hw, hh = 4.5, 2.5
            pts = [QPointF(cx, cy - hh), QPointF(cx + hw, cy + hh),
                   QPointF(cx - hw, cy + hh)]  # triangle apex up
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF(pts))
        finally:
            painter.end()


def _split_boundary_y(top_plot, bottom_plot) -> float:
    """Y of the divider: centre of the white gap between two PlotItems."""
    top_b = float(top_plot.sceneBoundingRect().bottom())
    bot_t = float(bottom_plot.sceneBoundingRect().top())
    return (top_b + bot_t) / 2.0


def _position_collapse_layout(rail, divider, top_plot, bottom_plot, collapsed):
    """Place the collapsed rail or divider for a two-row stacked canvas."""
    if collapsed:
        if divider is not None:
            divider.hide()
        if rail is not None:
            rail.setVisible(True)
            rail.raise_()
        return
    if rail is not None:
        rail.setVisible(False)
    if divider is None:
        return
    try:
        vb = top_plot.vb.sceneBoundingRect()
    except Exception:
        return
    try:
        boundary_y = _split_boundary_y(top_plot, bottom_plot)
    except Exception:
        boundary_y = float(vb.bottom())
    parent = divider.parentWidget()
    width = int(parent.width()) if parent is not None else int(vb.width())
    if not top_plot.isVisible() or width <= 0:
        divider.hide()
        return
    divider.setFixedWidth(width)
    divider.move(0, max(0, int(boundary_y - divider.height() / 2)))
    divider.show()
    divider.raise_()


def _apply_plot_collapse(top_plot, bottom_plot, state, bottom_default_max):
    """Collapse the lower plot or restore both rows without restructuring."""
    big = 100000
    if state == 'bottom':
        bottom_plot.setMaximumHeight(0)
        bottom_plot.setVisible(False)
        top_plot.setVisible(True)
        top_plot.setMaximumHeight(big)
    else:
        top_plot.setVisible(True)
        top_plot.setMaximumHeight(big)
        bottom_plot.setVisible(True)
        bottom_plot.setMaximumHeight(int(bottom_default_max))


def _available_split_height(canvas) -> float:
    """Total height the two stacked plots share."""
    glw = getattr(canvas, '_glw', None)
    if glw is not None:
        try:
            h = float(glw.viewport().height())
            if h > 0:
                return h
        except Exception:
            pass
    try:
        return float(canvas.height())
    except Exception:
        return 0.0


def _clamp_bottom_split(value, total) -> float:
    """Clamp the bottom plot height to [MIN_BOTTOM, total - MIN_TOP]."""
    hi = max(float(_SPLIT_MIN_BOTTOM), float(total) - _SPLIT_MIN_TOP)
    return max(float(_SPLIT_MIN_BOTTOM), min(hi, float(value)))


class _StackedSplitMixin:
    """Drag/collapse/reset handlers for a two-row stacked split."""

    def _split_top_plot(self):
        raise NotImplementedError

    def _split_bottom_plot(self):
        raise NotImplementedError

    def _split_is_ready(self) -> bool:
        return self._split_bottom_plot() is not None

    def _after_split_collapse_changed(self) -> None:
        pass

    def _after_split_height_changed(self) -> None:
        pass

    def _after_split_drag_finished(self) -> bool:
        return False

    def _after_split_reset(self) -> None:
        pass

    def _set_bottom_collapsed(self, collapsed: bool) -> None:
        if not self._split_is_ready():
            return
        self._bottom_collapsed = bool(collapsed)
        if not self._bottom_collapsed:
            self._bottom_split_h = float(self._bottom_split_default)
        state = 'bottom' if self._bottom_collapsed else 'none'
        _apply_plot_collapse(
            self._split_top_plot(), self._split_bottom_plot(), state,
            self._bottom_split_h)
        self._after_split_collapse_changed()
        self._position_collapse_ctrl()
        self.layout_geometry_changed.emit()

    def _on_collapse_changed(self, state) -> None:
        self._set_bottom_collapsed(state == 'bottom')

    def _position_collapse_ctrl(self, *_args) -> None:
        _position_collapse_layout(
            getattr(self, '_collapsed_rail', None),
            getattr(self, '_split_divider', None),
            self._split_top_plot(), self._split_bottom_plot(),
            getattr(self, '_bottom_collapsed', False))

    def _available_split_height(self) -> float:
        return _available_split_height(self)

    def _on_split_drag_started(self) -> None:
        self._drag_start_bottom_h = float(self._bottom_split_h)

    def _on_split_drag_delta(self, delta) -> None:
        if not self._split_is_ready():
            return
        raw = self._drag_start_bottom_h + delta
        if raw <= _SPLIT_COLLAPSE_AT:
            self._set_bottom_collapsed(True)
            return
        self._bottom_split_h = _clamp_bottom_split(
            raw, self._available_split_height())
        self._split_bottom_plot().setMaximumHeight(int(self._bottom_split_h))
        self._position_collapse_ctrl()
        self._after_split_height_changed()
        self.layout_geometry_changed.emit()

    def _on_split_drag_finished(self) -> None:
        self._position_collapse_ctrl()
        if self._after_split_drag_finished():
            self.layout_geometry_changed.emit()

    def _on_split_reset(self) -> None:
        self._bottom_split_h = float(self._bottom_split_default)
        if not self._bottom_collapsed and self._split_is_ready():
            self._split_bottom_plot().setMaximumHeight(int(self._bottom_split_h))
        self._position_collapse_ctrl()
        self._after_split_reset()
        self.layout_geometry_changed.emit()

    # ------------------------------------------------------------------
    # Cross-pane layout alignment.
    #
    # AnalysisSectionPage drives a three-call protocol on every pane it lays
    # out side by side: prepare (release to natural sizes) -> *_layout_metrics
    # (measure) -> apply (pin to the cross-pane maxima). reset_* is the
    # single-pane path. The two canvases keep their own apply_* signatures --
    # the page passes different keyword names per canvas type and that is part
    # of the contract -- so only the shared body lives here.
    # ------------------------------------------------------------------

    def _alignment_left_axes(self):
        """Left AxisItems that must end up sharing one width."""
        raise NotImplementedError

    def _alignment_bottom_axes(self):
        """Bottom AxisItems whose heights participate in alignment."""
        raise NotImplementedError

    def _activate_graphics_layout(self) -> None:
        """Realize pending geometry for this canvas's layout owners."""
        raise NotImplementedError

    def _release_split_right_spacers(self) -> None:
        """Reset the right-edge reserve to its no-split state.

        Genuinely per-canvas: the line canvas keeps a thin VISIBLE 1px frame on
        both rows so each plot reads as a closed rectangle, while the heatmap
        HIDES the slice's right axis so it cannot pollute the reserve
        measurement that follows. Same call site, opposite intent.
        """

    def _release_split_titles(self) -> None:
        """Re-apply/collapse plot titles after the size release."""

    def prepare_split_layout_alignment(self, title_width: float | None) -> None:
        """Release stale pins, constrain the title, and realize geometry.

        Called by AnalysisSectionPage before it measures multiple panes: first
        release to the natural current text/tick sizes, then pin every pane to
        the maxima.

        The ``setWidth(None)`` release is kept even though the measurement that
        follows it is now font-metric based. It is the only thing that lets a
        cross-pane pin re-TIGHTEN: ``*_layout_metrics`` reports ``max(font
        need, width())``, so without a release the realized term would still be
        carrying whatever the previous -- possibly much wider -- alignment pass
        pinned. A line pane that switched from rack force to steering torque
        would keep a rack-force-sized left margin forever, and a heatmap pane
        that switched from a frequency map to an order map would keep a
        five-digit one.

        Two things had to be true before the release could be trusted. It only
        became load-bearing at all once ``_activate_graphics_layout`` started
        walking the PlotItem layouts: before that it moved size hints nothing
        ever realized, so ``width()`` kept reporting the old pin and the
        release was a no-op that merely looked like one. And it is only SAFE
        because the font-metric term covers the case the release cannot -- a
        natural width read before the new ticks have ever been painted comes
        from a stale ``AxisItem.textWidth`` and under-reports.
        """
        self._split_title_width = (
            max(80.0, float(title_width))
            if title_width is not None else None
        )
        for axis in self._alignment_left_axes():
            try:
                axis.setWidth(None)
            except Exception:
                pass
        for axis in self._alignment_bottom_axes():
            try:
                axis.setHeight(None)
            except Exception:
                pass
        self._release_split_right_spacers()
        self._release_split_titles()
        self._activate_graphics_layout()

    def reset_split_layout_alignment(self) -> None:
        """Single-pane path: release, then unify the stacked left edges.

        prepare_* just released the widths to their natural sizes, which differ
        whenever the two rows' y tick labels differ (spectrum amplitude vs
        time-domain amplitude) -> misaligned left edges. Split mode (>=2 panes)
        is handled by the page via apply_split_layout_alignment, which already
        unifies left widths, so this only runs on the single-pane reset.
        """
        self.prepare_split_layout_alignment(None)
        self._unify_stacked_left_axes()

    def _unify_stacked_left_axes(self) -> None:
        """Pin the stacked left axes to one width so both rows share an edge.

        The width comes from the tick STRINGS each axis is carrying right now
        (``pin_left_axes_to_common_width``), folded with each axis's realized
        ``width()`` so the pin is monotonically non-decreasing within one pass.

        Reading ``AxisItem.width()`` alone cannot answer the question:
        pyqtgraph derives the automatic width from ``AxisItem.textWidth``,
        refreshed only inside ``generateDrawSpecs`` -- i.e. while painting --
        so before the first paint of a new tick set it is still the constructor
        default of 30. Both alignment entry points that matter run on
        ``QTimer.singleShot(0, ...)`` (``_deferred_first_show_align`` and
        AnalysisSectionPage's layout sync), so they routinely land there.

        Two measurements, one per canvas, of what that cost: a 0-480000 N
        spectrum pinned the line canvas's axis to 62.4px against the 101.4px
        its labels needed, leaving a row labelled ``'0'``; a 0-480000 Hz map
        aligned before its first paint pinned the heatmap's to 75.4px against
        the same 101.4px. In both cases ``generateDrawSpecs`` silently DROPPED
        every label that did not fit rather than clipping any (``if br & rect
        != rect: continue``). Re-plotting a wide map over a narrow one was
        worse still -- the released width fell back to the previous labels'
        62.4px.

        No-op with fewer than two axes (a canvas with no second row).

        Note the activation is driven through ``_activate_graphics_layout``
        rather than the helper's ``layout_owners`` argument: they are the same
        call for the line canvas, but the heatmap's activator additionally
        resizes ``ci`` to the widget first, which the plain helper traversal
        does not do.
        """
        axes = self._alignment_left_axes()
        if len(axes) < 2:
            return
        pin_left_axes_to_common_width(axes)
        self._activate_graphics_layout()

    def _pin_split_left_axes(self, left_axis_width: float) -> None:
        for axis in self._alignment_left_axes():
            try:
                axis.setWidth(float(left_axis_width))
            except Exception:
                pass

    @staticmethod
    def _pin_split_bottom_heights(pairs) -> None:
        """Set each ``(plot, height)`` bottom-axis height, skipping blanks.

        A ``None`` plot is a row this canvas does not have (the heatmap without
        a slice row); a ``None`` height is a measurement the page chose not to
        send.
        """
        for plot, height in pairs:
            if plot is None or height is None:
                continue
            try:
                plot.getAxis('bottom').setHeight(float(height))
            except Exception:
                pass
