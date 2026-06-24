"""Point annotation helpers for the pyqtgraph time-domain canvas."""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref
from .remarks import (
    RemarkArtist,
    RemarkPoint,
    _annotation_pen_cursor,
    format_remark_label,
)


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
        self._artist = RemarkArtist()

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
        """Return (ch_name, x, y, color, unit) nearest to viewport_pos."""
        x_data = self._cursor_data_x_from_viewport_pos(viewport_pos)
        if x_data is None or not self.channel_data:
            return None
        target_handle = self._remark_target_axis_handle(viewport_pos)
        # Iterate by composite key so each curve is considered once even when
        # two files share a channel name; (name, axis_handle) is resolved from
        # the same composite identity (display name is what the remark shows).
        candidate_items = [
            (ck, name, row)
            for ck, name, row in self.channel_data.composite_items()
        ]
        if target_handle is not None:
            target_keys = {
                ck for ck, _name, (axis_handle, _line)
                in self._channel_lines.composite_items()
                if axis_handle is target_handle
            }
            candidate_items = [
                (ck, name, row)
                for ck, name, row in candidate_items
                if ck in target_keys
            ]
        try:
            scene_pos = self._viewport_pos_to_scene(viewport_pos)
        except Exception:
            scene_pos = None
        best = None
        best_dist = float('inf')
        for ck, ch, (tf, sf, color, unit) in candidate_items:
            if not len(tf):
                continue
            ax = self._channel_lines.get(ck, (None, None))[0]
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
                            unit,
                        )
                except Exception:
                    if best is None:
                        idx = int(np.argmin(np.abs(tf - x_data)))
                        best = (ch, float(tf[idx]), float(sf[idx]), color, unit)
            else:
                if best is None:
                    idx = int(np.argmin(np.abs(tf - x_data)))
                    sx, sy = float(tf[idx]), float(sf[idx])
                    best = (ch, sx, sy, color, unit)
        return best

    def _add_remark(self, viewport_pos):
        """Add a draggable annotation at the data point nearest to viewport_pos."""
        found = self._nearest_data_point(viewport_pos)
        if found is None:
            return
        if len(found) >= 5:
            ch, dx, dy, color, unit = found[:5]
        else:
            ch, dx, dy, color = found
            unit = ""
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
        point = RemarkPoint(
            vb=vb,
            x=float(dx),
            y=float(dy),
            color=color,
            unit_x="s",
            unit_y=unit or "",
        )
        remark = self._artist.add(point)
        self.remarks.append(remark)

    def _format_remark_label(self, x_value, y_value, color=None):
        """Return the compact coordinate label shown by point remarks."""
        return format_remark_label(
            RemarkPoint(
                vb=None,
                x=float(x_value),
                y=float(y_value),
                color=str(color or "#1769e0"),
                unit_x="s",
            )
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
        self._artist.update_leader(remark)

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
            self._artist.remove(r)
        except Exception:
            pass

    def clear_remarks(self):
        """Remove all annotations."""
        self._artist.clear(self.remarks)


__all__ = ["AnnotationManager", "_annotation_pen_cursor"]
