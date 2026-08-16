"""Point annotation helpers for the pyqtgraph time-domain canvas."""

from __future__ import annotations

import json
from math import isfinite

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.view_overlay_state import (
    normalize_remark,
    normalize_remarks,
    raw_channel_name,
)

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref
from ._shared import _view_state_channel_key
from .remarks import (
    RemarkArtist,
    RemarkPoint,
    _annotation_pen_cursor,
    format_remark_label,
    remark_label_offset,
    remark_qt_alive,
)


def _finite_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return number


def _source_tuple(raw):
    """Return a ChannelKey-shaped ``(fid, channel)`` tuple, or None."""
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        fid, channel = raw[0], raw[1]
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not (isinstance(parsed, list) and len(parsed) == 2):
            return None
        fid, channel = parsed[0], parsed[1]
    else:
        return None
    if channel is None:
        return None
    channel_name = str(channel)
    if not channel_name:
        return None
    channel_name = raw_channel_name(channel_name)
    if fid is None:
        return (None, channel_name)
    return (str(fid), channel_name)


def _json_source_list(source):
    parsed = _source_tuple(source)
    if parsed is None:
        return None
    fid, channel = parsed
    return [fid, channel]


def _snap_channel_xy(tf, sf, x):
    """Snap ``x`` to the nearest sample on this channel; y comes from that sample."""
    try:
        tf_arr = np.asarray(tf, dtype=float).reshape(-1)
        sf_arr = np.asarray(sf, dtype=float).reshape(-1)
        target = float(x)
    except (TypeError, ValueError):
        return None
    if tf_arr.size == 0 or sf_arr.size == 0 or not isfinite(target):
        return None
    n = tf_arr.size
    finite = np.isfinite(tf_arr)
    if sf_arr.size < n:
        y_ok = np.zeros(n, dtype=bool)
        y_ok[:sf_arr.size] = np.isfinite(sf_arr)
        finite = finite & y_ok
    else:
        finite = finite & np.isfinite(sf_arr[:n])
    if not finite.any():
        return None
    idxs = np.flatnonzero(finite)
    local = int(np.argmin(np.abs(tf_arr[idxs] - target)))
    idx = int(idxs[local])
    if idx >= sf_arr.size:
        return None
    sx = float(tf_arr[idx])
    sy = float(sf_arr[idx])
    if not (isfinite(sx) and isfinite(sy)):
        return None
    return sx, sy


class AnnotationManager(_CanvasBackref):
    """Point remarks and annotation-mode mouse routing."""

    _owned_names = frozenset({
        "enabled",
        "remarks",
        "press_pos",
        "press_dragged",
        "_artist",
        "_intent",
        "markup_revision",
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
        "_drop_remark_projection",
        "_project_remarks",
        "snapshot_remarks",
        "restore_remarks",
    })

    def __init__(self, canvas):
        super().__init__(canvas)
        self.enabled = False
        self.remarks = []
        self._intent = []
        self.press_pos = None
        self.press_dragged = False
        self.markup_revision = 0
        self._artist = RemarkArtist(on_moved=self._bump_markup_revision)

    def _bump_markup_revision(self):
        self.markup_revision = int(self.markup_revision) + 1
        signal = getattr(self._c, "markup_revision_changed", None)
        emit = getattr(signal, "emit", None)
        if callable(emit):
            emit()

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
        """Return (ch_name, x, y, color, unit, ck) nearest to viewport_pos."""
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
                            ck,
                        )
                except Exception:
                    if best is None:
                        idx = int(np.argmin(np.abs(tf - x_data)))
                        best = (
                            ch, float(tf[idx]), float(sf[idx]), color, unit, ck,
                        )
            else:
                if best is None:
                    idx = int(np.argmin(np.abs(tf - x_data)))
                    sx, sy = float(tf[idx]), float(sf[idx])
                    best = (ch, sx, sy, color, unit, ck)
        return best

    def _add_remark(self, viewport_pos):
        """Add a draggable annotation at the data point nearest to viewport_pos."""
        found = self._nearest_data_point(viewport_pos)
        if found is None:
            return
        ch, dx, dy, color = found[0], found[1], found[2], found[3]
        unit = found[4] if len(found) >= 5 else ""
        ck = found[5] if len(found) >= 6 else None
        if isinstance(ck, (list, tuple)) and len(ck) == 2:
            ck = _view_state_channel_key(ck[0], ck[1])
        if ck is None:
            ck = self._channel_lines.resolve_unique(ch)
        lookup_ck = ck
        if lookup_ck is None:
            lookup_ck = self._channel_lines.composite_key_for(ch)
        try:
            ax = None
            if lookup_ck is not None:
                pair = self._channel_lines.get(lookup_ck)
                if pair:
                    ax = pair[0]
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
        source = _source_tuple(ck)
        if source is not None:
            remark["source"] = source
        self.remarks.append(remark)
        intent = self._intent_dict_from_remark(remark)
        if intent is not None:
            self._intent.append(intent)
        self._bump_markup_revision()

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
            return
        self._pop_intent_for_remark(r)
        self._bump_markup_revision()

    def clear_remarks(self):
        """Remove all annotations (intent + Qt projection)."""
        self._intent = []
        if not self.remarks:
            return
        self._drop_remark_projection()
        self._bump_markup_revision()

    def _drop_remark_projection(self):
        """Remove Qt remark items without touching the intent list."""
        if not self.remarks:
            return
        self._artist.clear(self.remarks)

    def _project_remarks(self):
        """Rebind the intent list onto the current channel lines."""
        self._drop_remark_projection()
        for item in list(self._intent):
            self._restore_one_remark(item)

    def _intent_dict_from_remark(self, remark):
        if not isinstance(remark, dict):
            return None
        source = _json_source_list(remark.get("source"))
        x = _finite_float(remark.get("data_x"))
        y = _finite_float(remark.get("data_y"))
        offset = remark_label_offset(remark)
        if source is None or x is None or y is None or offset is None:
            return None
        return normalize_remark({
            "source": source,
            "x": x,
            "y": y,
            "label_dx": float(offset[0]),
            "label_dy": float(offset[1]),
        })

    def _pop_intent_for_remark(self, remark):
        source = _source_tuple(remark.get("source") if isinstance(remark, dict) else None)
        rx = _finite_float(remark.get("data_x") if isinstance(remark, dict) else None)
        best_i, best_d = None, float("inf")
        for i, intent in enumerate(self._intent):
            if _source_tuple(intent.get("source")) != source:
                continue
            ix = _finite_float(intent.get("x"))
            if ix is None or rx is None:
                continue
            dist = abs(ix - rx)
            if dist < best_d:
                best_i, best_d = i, dist
        if best_i is None:
            return
        self._intent.pop(best_i)

    def snapshot_remarks(self):
        """Return the Qt-free intent list, reading live offsets back when drawn."""
        used = set()
        payload = []
        for intent in list(self._intent):
            item = dict(intent)
            live = self._live_remark_for_intent(item, used)
            if live is not None:
                offset = remark_label_offset(live)
                if offset is not None:
                    item["label_dx"] = float(offset[0])
                    item["label_dy"] = float(offset[1])
                x = _finite_float(live.get("data_x"))
                y = _finite_float(live.get("data_y"))
                if x is not None:
                    item["x"] = x
                if y is not None:
                    item["y"] = y
            payload.append(item)
        return payload

    def _live_remark_for_intent(self, intent, used):
        source = _source_tuple(intent.get("source"))
        ix = _finite_float(intent.get("x"))
        best_i, best_d = None, float("inf")
        for i, remark in enumerate(self.remarks):
            if i in used or not isinstance(remark, dict):
                continue
            if not remark_qt_alive(remark.get("vb")):
                continue
            if not remark_qt_alive(remark.get("text")):
                continue
            if _source_tuple(remark.get("source")) != source:
                continue
            rx = _finite_float(remark.get("data_x"))
            if rx is None or ix is None:
                continue
            dist = abs(rx - ix)
            if dist < best_d:
                best_i, best_d = i, dist
        if best_i is None:
            return None
        used.add(best_i)
        return self.remarks[best_i]

    def restore_remarks(self, payload):
        """Replace the intent list and project it onto the current plot."""
        self._intent = normalize_remarks(payload)
        self._project_remarks()

    def _line_binding_for_source(self, source):
        """Return ``(axis_line_pair, channel_data_row)`` for a remark source.

        Persisted identity is ``(fid, raw channel)``. Live plot rows are
        keyed by ``(fid, [{short}] channel)``, so exact composite lookup is
        tried first and a fid-scoped display-name match is the fallback.
        """
        parsed = _source_tuple(source)
        if parsed is None or parsed[0] is None:
            return None, None
        fid, channel = parsed
        lines = self._channel_lines
        data = self.channel_data
        ck = _view_state_channel_key(fid, channel)
        pair = lines.get(ck) if hasattr(lines, "get") else None
        row = data.get(ck) if hasattr(data, "get") else None
        if pair and row:
            return pair, row
        composite_items = getattr(lines, "composite_items", None)
        if not callable(composite_items):
            return None, None
        wanted = (fid, channel)
        for item_ck, _display_name, item_pair in composite_items():
            if _source_tuple(item_ck) != wanted:
                continue
            item_row = data.get(item_ck) if hasattr(data, "get") else None
            if item_pair and item_row:
                return item_pair, item_row
        return None, None

    def _line_is_drawn(self, pair):
        try:
            line = pair[1]
        except (TypeError, IndexError):
            return False
        pdi = getattr(line, "plot_data_item", None)
        if pdi is None:
            return True
        try:
            return bool(pdi.isVisible())
        except Exception:
            return True

    def _restore_one_remark(self, raw):
        if not isinstance(raw, dict):
            return
        pair, row = self._line_binding_for_source(raw.get("source"))
        if not pair or not row:
            return
        if not self._line_is_drawn(pair):
            return
        try:
            ax = pair[0]
        except (TypeError, IndexError):
            return
        vb = ax.view_box if ax is not None else None
        if vb is None:
            return
        try:
            tf, sf, color, unit = row[0], row[1], row[2], row[3]
        except (TypeError, IndexError, ValueError):
            return
        x = _finite_float(raw.get("x"))
        if x is None:
            return
        snapped = _snap_channel_xy(tf, sf, x)
        if snapped is None:
            return
        sx, sy = snapped
        source = _source_tuple(raw.get("source"))
        point = RemarkPoint(
            vb=vb,
            x=sx,
            y=sy,
            color=color,
            unit_x="s",
            unit_y=unit or "",
            label_dx=_finite_float(raw.get("label_dx")),
            label_dy=_finite_float(raw.get("label_dy")),
        )
        try:
            remark = self._artist.add(point)
        except Exception:
            return
        if source is not None:
            remark["source"] = source
        self.remarks.append(remark)


__all__ = ["AnnotationManager", "_annotation_pen_cursor"]
