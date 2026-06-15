"""Shared split/collapse controls for two-row analysis canvases."""
from __future__ import annotations

from PyQt5.QtCore import QPointF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import QFrame, QWidget


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
    HEIGHT_PX = 14

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
            hw, hh = 5.0, 3.0
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
