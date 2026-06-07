"""Point annotation helpers for the pyqtgraph time-domain canvas."""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QApplication

from . import _binding  # noqa: F401

import pyqtgraph as pg


_MISSING = object()
_ANNOTATION_CURSOR = None


class _CanvasBackref:
    _delegate_names = frozenset()
    _owned_names = frozenset()

    def __init__(self, canvas):
        object.__setattr__(self, "_c", canvas)

    def __getattribute__(self, name):
        if name not in {
            "_c",
            "_delegate_names",
            "_owned_names",
            "__dict__",
            "__class__",
            "__getattr__",
            "__getattribute__",
            "__setattr__",
        }:
            delegate_names = object.__getattribute__(self, "_delegate_names")
            if name in delegate_names:
                canvas = object.__getattribute__(self, "_c")
                value = getattr(canvas, "__dict__", {}).get(name, _MISSING)
                if value is not _MISSING:
                    return value
        return object.__getattribute__(self, name)

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __setattr__(self, name, value):
        if name == "_c":
            object.__setattr__(self, name, value)
            return
        owned_names = object.__getattribute__(self, "_owned_names")
        delegate_names = object.__getattribute__(self, "_delegate_names")
        if name in owned_names or name in delegate_names:
            object.__setattr__(self, name, value)
            return
        setattr(self._c, name, value)


def _annotation_pen_cursor():
    global _ANNOTATION_CURSOR
    if _ANNOTATION_CURSOR is not None:
        return _ANNOTATION_CURSOR
    pix = QPixmap(24, 24)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(
            QPen(QColor("#1769e0"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.drawLine(6, 18, 17, 7)
        painter.drawLine(14, 6, 18, 10)
        painter.drawLine(5, 19, 9, 19)
        painter.setPen(
            QPen(QColor("#1e293b"), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.drawEllipse(3, 17, 4, 4)
    finally:
        painter.end()
    _ANNOTATION_CURSOR = QCursor(pix, 5, 19)
    return _ANNOTATION_CURSOR


class AnnotationManager(_CanvasBackref):
    """Point remarks and annotation-mode mouse routing."""

    _owned_names = frozenset({
        "enabled",
        "remarks",
        "press_pos",
        "press_dragged",
    })

    _delegate_names = frozenset({
        "set_remark_enabled",
        "_clear_annotation_press_state",
        "_remark_target_axis_handle",
        "_nearest_data_point",
        "_add_remark",
        "_format_remark_label",
        "_remark_item_at_viewport_pos",
        "_annotation_drag_threshold",
        "_handle_annotation_mouse_press",
        "_handle_annotation_mouse_move",
        "_handle_annotation_mouse_release",
        "_update_remark_leader",
        "_remove_remark_at",
        "_remove_remark_by_index",
        "clear_remarks",
    })

    def __init__(self, canvas):
        super().__init__(canvas)
        self.enabled = False
        self.remarks = []
        self.press_pos = None
        self.press_dragged = False

    def set_remark_enabled(self, enabled):
        """Enable or disable annotation mode; changes cursor shape."""
        self.enabled = bool(enabled)
        self._clear_annotation_press_state()
        try:
            vp = self._glw.viewport()
            if vp:
                if self.enabled:
                    vp.setCursor(_annotation_pen_cursor())
                else:
                    vp.setCursor(Qt.ArrowCursor)
        except Exception:
            pass

    def _clear_annotation_press_state(self):
        self.press_pos = None
        self.press_dragged = False

    def _remark_target_axis_handle(self, viewport_pos):
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        if self._overlay_mode:
            return None
        return self._axis_handle_at_scene_pos(scene_pos)

    def _nearest_data_point(self, viewport_pos):
        """Return (ch_name, x, y, color) of the data point nearest to viewport_pos."""
        x_data = self._cursor_data_x_from_viewport_pos(viewport_pos)
        if x_data is None or not self.channel_data:
            return None
        target_handle = self._remark_target_axis_handle(viewport_pos)
        candidate_items = self.channel_data.items()
        if target_handle is not None:
            target_names = {
                name for name, (axis_handle, _line) in self._channel_lines.items()
                if axis_handle is target_handle
            }
            candidate_items = [
                (name, row)
                for name, row in self.channel_data.items()
                if name in target_names
            ]
        try:
            scene_pos = self._viewport_pos_to_scene(viewport_pos)
        except Exception:
            scene_pos = None
        best = None
        best_dist = float('inf')
        for ch, (tf, sf, color, _unit) in candidate_items:
            if not len(tf):
                continue
            ax = self._channel_lines.get(ch, (None, None))[0]
            if ax is None:
                ax = target_handle or self._primary_xaxis_ax or (
                    self.axes_list[0] if self.axes_list else None
                )
            vb = ax.view_box if ax else None
            if scene_pos is not None:
                try:
                    if vb is None:
                        continue
                    tf_arr = np.asarray(tf, dtype=float)
                    sf_arr = np.asarray(sf, dtype=float)
                    n = min(tf_arr.size, sf_arr.size)
                    if n == 0:
                        continue
                    tf_arr = tf_arr[:n]
                    sf_arr = sf_arr[:n]
                    finite = np.isfinite(tf_arr) & np.isfinite(sf_arr)
                    if not finite.any():
                        continue
                    tf_arr = tf_arr[finite]
                    sf_arr = sf_arr[finite]
                    try:
                        x_range, _y_range = vb.viewRange()
                        rect = vb.sceneBoundingRect()
                        span = abs(float(x_range[1]) - float(x_range[0]))
                        width = max(float(rect.width()), 1.0)
                        half_window = max((span / width) * 48.0, 1e-12)
                    except Exception:
                        half_window = 0.0
                    if half_window > 0.0:
                        idxs = np.flatnonzero(np.abs(tf_arr - x_data) <= half_window)
                    else:
                        idxs = np.asarray([], dtype=int)
                    if idxs.size == 0:
                        nearest_idx = int(np.argmin(np.abs(tf_arr - x_data)))
                        start = max(0, nearest_idx - 32)
                        stop = min(tf_arr.size, nearest_idx + 33)
                        idxs = np.arange(start, stop, dtype=int)
                    scene_pts = self._map_view_points_to_scene(
                        vb, tf_arr[idxs], sf_arr[idxs]
                    )
                    if scene_pts is None or scene_pts.size == 0:
                        continue
                    dist_sq = (
                        (scene_pts[:, 0] - float(scene_pos.x())) ** 2
                        + (scene_pts[:, 1] - float(scene_pos.y())) ** 2
                    )
                    local_i = int(np.argmin(dist_sq))
                    dist = float(dist_sq[local_i])
                    if dist < best_dist:
                        src_idx = int(idxs[local_i])
                        best_dist = dist
                        best = (
                            ch,
                            float(tf_arr[src_idx]),
                            float(sf_arr[src_idx]),
                            color,
                        )
                except Exception:
                    if best is None:
                        idx = int(np.argmin(np.abs(tf - x_data)))
                        best = (ch, float(tf[idx]), float(sf[idx]), color)
            else:
                if best is None:
                    idx = int(np.argmin(np.abs(tf - x_data)))
                    sx, sy = float(tf[idx]), float(sf[idx])
                    best = (ch, sx, sy, color)
        return best

    def _add_remark(self, viewport_pos):
        """Add a draggable annotation at the data point nearest to viewport_pos."""
        found = self._nearest_data_point(viewport_pos)
        if found is None:
            return
        ch, dx, dy, color = found
        try:
            ax = self._channel_lines.get(ch, (None, None))[0]
            if ax is None:
                ax = self._remark_target_axis_handle(viewport_pos)
            if ax is None:
                ax = self._primary_xaxis_ax or (
                    self.axes_list[0] if self.axes_list else None
                )
            vb = ax.view_box if ax else None
        except Exception:
            vb = None
        if vb is None:
            return
        dot = pg.ScatterPlotItem(
            x=[dx], y=[dy], size=8,
            pen=pg.mkPen('#dc2626', width=1.5),
            brush=pg.mkBrush('#dc2626'),
            pxMode=True,
        )
        vb.addItem(dot)
        try:
            vrange = vb.viewRange()
            ox = (vrange[0][1] - vrange[0][0]) * 0.06
            oy = (vrange[1][1] - vrange[1][0]) * 0.08
        except Exception:
            ox, oy = 0, 0
        lx, ly = dx + ox, dy + oy
        leader = pg.PlotDataItem(
            x=[dx, lx], y=[dy, ly],
            pen=pg.mkPen(color, width=1.0, style=Qt.DashLine),
        )
        vb.addItem(leader)
        label_text = self._format_remark_label(dx, dy, color)
        text = pg.TextItem(
            html=label_text,
            color=color,
            fill=pg.mkBrush(255, 255, 255, 210),
            border=pg.mkPen(color, width=0.8),
        )
        text.setPos(lx, ly)
        text.setFlag(text.ItemIsMovable, True)
        vb.addItem(text)
        remark = {
            'vb': vb, 'dot': dot, 'text': text, 'leader': leader,
            'data_x': dx, 'data_y': dy,
        }
        self.remarks.append(remark)
        try:
            text.sigPositionChanged.connect(
                lambda item, r=remark: self._update_remark_leader(r)
            )
        except Exception:
            orig_item_change = text.itemChange

            def patched_item_change(change, value, _r=remark, _orig=orig_item_change):
                result = _orig(change, value)
                if change == text.ItemPositionHasChanged:
                    self._update_remark_leader(_r)
                return result

            text.itemChange = patched_item_change

    def _format_remark_label(self, x_value, y_value, color=None):
        """Return the compact coordinate label shown by point remarks."""
        y_color = str(color or "#1769e0")
        return (
            f"<div>X={x_value:.4g}</div>"
            f"<div style='color:{y_color}; font-weight:600;'>Y={y_value:.4g}</div>"
        )

    def _remark_item_at_viewport_pos(self, viewport_pos):
        """Return the remark under a viewport click, or None."""
        from PyQt5.QtCore import QPointF as _QPointF
        if not self.remarks:
            return None
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        if scene_pos is None:
            return None
        try:
            scene_items = self._glw.scene().items(scene_pos)
        except Exception:
            scene_items = []
        for item in scene_items:
            for remark in self.remarks:
                text = remark.get('text')
                candidates = (
                    text,
                    getattr(text, 'textItem', None),
                    remark.get('dot'),
                    remark.get('leader'),
                )
                if any(
                    item is candidate
                    for candidate in candidates
                    if candidate is not None
                ):
                    return remark
        try:
            sp = scene_pos.toPoint() if hasattr(scene_pos, 'toPoint') else scene_pos
            for remark in self.remarks:
                vb = remark.get('vb')
                text = remark.get('text')
                if vb is None or text is None:
                    continue
                lpos = text.pos()
                label_scene_pos = vb.mapViewToScene(_QPointF(lpos.x(), lpos.y()))
                dist_sq = (
                    (label_scene_pos.x() - sp.x()) ** 2
                    + (label_scene_pos.y() - sp.y()) ** 2
                )
                if dist_sq <= 12 ** 2:
                    return remark
        except Exception:
            return None
        return None

    def _annotation_drag_threshold(self):
        try:
            return max(1, int(QApplication.startDragDistance()))
        except Exception:
            return 10

    def _handle_annotation_mouse_press(self, event):
        if not self.enabled:
            return None
        if event.button() == Qt.RightButton:
            scene_pos = self._viewport_pos_to_scene(event.pos())
            self._last_rclick_scene_pos = scene_pos
            self._remove_remark_at(scene_pos)
            self._clear_annotation_press_state()
            return True
        if event.button() != Qt.LeftButton:
            return None
        if self._remark_item_at_viewport_pos(event.pos()) is not None:
            self._clear_annotation_press_state()
            return False
        self.press_pos = event.pos()
        self.press_dragged = False
        return False

    def _handle_annotation_mouse_move(self, event):
        if not self.enabled or self.press_pos is None:
            return None
        try:
            if event.buttons() & Qt.LeftButton:
                delta = event.pos() - self.press_pos
                if delta.manhattanLength() >= self._annotation_drag_threshold():
                    self.press_dragged = True
        except Exception:
            pass
        return False

    def _handle_annotation_mouse_release(self, event):
        if not self.enabled or self.press_pos is None:
            return None
        if event.button() != Qt.LeftButton:
            self._clear_annotation_press_state()
            return None
        start_pos = self.press_pos
        try:
            delta = event.pos() - start_pos
            moved = delta.manhattanLength() >= self._annotation_drag_threshold()
        except Exception:
            moved = self.press_dragged
        dragged = self.press_dragged or moved
        self._clear_annotation_press_state()
        if dragged:
            return False
        self._add_remark(event.pos())
        return True

    def _update_remark_leader(self, remark):
        """Redraw leader line from data point to text label current position."""
        try:
            text = remark['text']
            dx, dy = remark['data_x'], remark['data_y']
            lpos = text.pos()
            lx, ly = float(lpos.x()), float(lpos.y())
            remark['leader'].setData(x=[dx, lx], y=[dy, ly])
        except Exception:
            pass

    def _remove_remark_at(self, scene_pos):
        """Remove annotation nearest to scene_pos (right-click delete)."""
        from PyQt5.QtCore import QPointF as _QPointF
        if not self.remarks or scene_pos is None:
            return
        best_idx, best_dist = 0, float('inf')
        try:
            sp = scene_pos.toPoint() if hasattr(scene_pos, 'toPoint') else scene_pos
            for i, r in enumerate(self.remarks):
                vb = r.get('vb')
                if vb is None:
                    continue
                lpos = r['text'].pos()
                s = vb.mapViewToScene(_QPointF(lpos.x(), lpos.y()))
                d = (s.x() - sp.x()) ** 2 + (s.y() - sp.y()) ** 2
                if d < best_dist:
                    best_dist, best_idx = d, i
        except Exception:
            return
        self._remove_remark_by_index(best_idx)

    def _remove_remark_by_index(self, idx):
        try:
            r = self.remarks.pop(idx)
            vb = r.get('vb')
            if vb:
                for item_key in ('dot', 'text', 'leader'):
                    item = r.get(item_key)
                    if item is not None:
                        try:
                            vb.removeItem(item)
                        except Exception:
                            pass
        except Exception:
            pass

    def clear_remarks(self):
        """Remove all annotations."""
        for r in list(self.remarks):
            vb = r.get('vb')
            if vb:
                for item_key in ('dot', 'text', 'leader'):
                    item = r.get(item_key)
                    if item is not None:
                        try:
                            vb.removeItem(item)
                        except Exception:
                            pass
        self.remarks.clear()


__all__ = ["AnnotationManager", "_annotation_pen_cursor"]
