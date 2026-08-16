"""Cursor interaction helpers for the pyqtgraph time-domain canvas."""

from __future__ import annotations

import time as _time

import numpy as np
from PyQt5.QtCore import Qt

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref

import pyqtgraph as pg

from mf4_analyzer.ui.plot_helpers import (
    _format_dual_html,
    _format_single_cursor_channel_html,
    _interp_cursor_value,
)


def _finite_float(value):
    """Return a Python float when ``value`` is a finite number, else None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _parse_placement_payload(payload):
    """Return ``(ax, bx)`` from a D3 dict, or None when the payload is invalid."""
    if not isinstance(payload, dict) or "ax" not in payload:
        return None
    ax = _finite_float(payload.get("ax"))
    if ax is None:
        return None
    if payload.get("bx") is None:
        return ax, None
    bx = _finite_float(payload.get("bx"))
    if bx is None:
        return None
    return ax, bx


class CursorController(_CanvasBackref):
    """Single/dual cursor and cursor HTML emission.

    Phase 4.2 moves cohesive cursor state here while still preserving canvas
    monkeypatch seams for moved methods.
    """

    _owned_names = frozenset({
        "_cursor_visible",
        "_dual",
        "_ax",
        "_bx",
        "_placing",
        "_last_t",
        "_cursor_line_items",
        "_cursor_a_items",
        "_cursor_b_items",
        "_cursor_item_owners",
        "_dual_cursor_extreme_markers",
        "visible",
        "dual",
        "ax",
        "bx",
        "placing",
        "last_t",
    })

    _delegate_names = frozenset({
        "set_cursor_visible",
        "set_dual_cursor_mode",
        "reset_cursor_state",
        "draw_idle",
        "draw",
        "_hide_cursor_items",
        "_ensure_cursor_items",
        "_remove_cursor_items",
        "_set_cursor_items_pos",
        "_ensure_dual_cursor_extreme_markers",
        "_hide_dual_cursor_extreme_markers",
        "_update_dual_cursor_extreme_markers",
        "_cursor_data_x_from_viewport_pos",
        "_handle_cursor_mouse_move",
        "_handle_cursor_mouse_press",
        "_scene_y_from_viewport_pos",
        "_select_overlay_channel_from_scene_pos",
        "_map_view_points_to_scene",
        "_emit_single_cursor_html",
        "_emit_dual_cursor_html",
        "_cursor_x_to_pixmap_x",
        "snapshot_placement",
        "restore_placement",
    })

    def __init__(self, canvas):
        super().__init__(canvas)
        self._cursor_visible = False
        self._dual = False
        self._ax = None
        self._bx = None
        self._placing = "A"
        self._last_t = 0
        self._cursor_line_items = []
        self._cursor_a_items = []
        self._cursor_b_items = []
        self._cursor_item_owners = {}
        self._dual_cursor_extreme_markers = []

    @property
    def visible(self):
        return self._cursor_visible

    @visible.setter
    def visible(self, value):
        self._cursor_visible = bool(value)

    @property
    def dual(self):
        return self._dual

    @dual.setter
    def dual(self, value):
        self._dual = bool(value)

    @property
    def ax(self):
        return self._ax

    @ax.setter
    def ax(self, value):
        self._ax = value

    @property
    def bx(self):
        return self._bx

    @bx.setter
    def bx(self, value):
        self._bx = value

    @property
    def placing(self):
        return self._placing

    @placing.setter
    def placing(self, value):
        self._placing = value

    @property
    def last_t(self):
        return self._last_t

    @last_t.setter
    def last_t(self, value):
        self._last_t = value

    @property
    def line_items(self):
        return self._cursor_line_items

    @property
    def a_items(self):
        return self._cursor_a_items

    @property
    def b_items(self):
        return self._cursor_b_items

    @property
    def extreme_markers(self):
        return self._dual_cursor_extreme_markers

    def clear_items(self):
        self._remove_cursor_items(self._cursor_line_items)
        self._remove_cursor_items(self._cursor_a_items)
        self._remove_cursor_items(self._cursor_b_items)
        self._cursor_item_owners.clear()
        self._dual_cursor_extreme_markers = []

    def reset_all_state(self):
        self._ax = None
        self._bx = None
        self._placing = "A"
        self._cursor_visible = False
        self._dual = False
        self._last_t = 0

    def set_cursor_visible(self, v):
        """Toggle single-cursor visibility."""
        self._cursor_visible = bool(v)
        if not self._cursor_visible:
            self._hide_cursor_items(self._cursor_line_items)
            self._hide_cursor_items(self._cursor_a_items)
            self._hide_cursor_items(self._cursor_b_items)
            self._hide_dual_cursor_extreme_markers()
            self.draw_idle()

    def set_dual_cursor_mode(self, en):
        """Toggle dual-cursor mode.

        Turning dual off hides A/B lines and clears the pill, but keeps
        the data-space placement. ``reset_cursor_state()`` is the explicit
        wipe; ``snapshot_placement()`` returns the stored A/B regardless of
        mode (D3 2026-08-16 revision).
        """
        self._dual = bool(en)
        if not en:
            self._hide_cursor_items(self._cursor_a_items)
            self._hide_cursor_items(self._cursor_b_items)
            self._hide_dual_cursor_extreme_markers()
            self.dual_cursor_info.emit("")
            self.draw_idle()
            return
        if _finite_float(self._ax) is not None:
            self._redraw_dual_placement_items()
            self._emit_dual_cursor_html()
            self.draw_idle()
            return
        self._hide_cursor_items(self._cursor_a_items)
        self._hide_cursor_items(self._cursor_b_items)
        self._hide_dual_cursor_extreme_markers()
        self._emit_dual_cursor_html()
        self.draw_idle()

    def reset_cursor_state(self):
        """Drop dual-cursor placement and request a redraw."""
        self._ax = None
        self._bx = None
        self._placing = "A"
        self._hide_cursor_items(self._cursor_line_items)
        self._hide_cursor_items(self._cursor_a_items)
        self._hide_cursor_items(self._cursor_b_items)
        self._hide_dual_cursor_extreme_markers()
        self.dual_cursor_info.emit("")
        self.draw_idle()

    def snapshot_placement(self):
        """Return dual-cursor data-space placement, or None if A is unset.

        Mode is not a gate (D3 2026-08-16): off/single still persist A/B so
        turning dual back on restores the same points. ``bx`` may be None
        when only A has been placed.
        """
        ax = _finite_float(self._ax)
        if ax is None:
            return None
        return {"ax": ax, "bx": _finite_float(self._bx)}

    def restore_placement(self, payload):
        """Write dual-cursor placement, or clear it when the payload is empty.

        None / illegal payloads wipe ``_ax``/``_bx``, hide A/B items and
        extrema, and reset ``_placing`` to ``"A"``. Dual mode then emits
        once so the pill returns to ``Click A``. This is the View-transaction
        seam that prevents View A placement from leaking into View B.
        ``clear()`` still does not reset ``_ax``/``_bx``.
        """
        parsed = _parse_placement_payload(payload)
        if parsed is None:
            self._ax = None
            self._bx = None
            self._placing = "A"
            self._hide_cursor_items(self._cursor_a_items)
            self._hide_cursor_items(self._cursor_b_items)
            self._hide_dual_cursor_extreme_markers()
            if self._dual:
                self._emit_dual_cursor_html()
            self.draw_idle()
            return
        self._ax, self._bx = parsed
        self._placing = "A" if self._bx is not None else "B"
        if not self._dual:
            return
        self._redraw_dual_placement_items()
        self._emit_dual_cursor_html()
        self.draw_idle()

    def _redraw_dual_placement_items(self):
        """Position A/B InfiniteLines from current ``_ax``/``_bx``."""
        if self._ax is not None:
            a_items = self._ensure_cursor_items(
                "_cursor_a_items", color="#2563eb", width=1.1
            )
            self._set_cursor_items_pos(a_items, self._ax)
        if self._bx is not None:
            b_items = self._ensure_cursor_items(
                "_cursor_b_items", color="#dc2626", width=1.1
            )
            self._set_cursor_items_pos(b_items, self._bx)
        else:
            self._hide_cursor_items(self._cursor_b_items)

    def draw_idle(self):
        """No-op equivalent of matplotlib FigureCanvas.draw_idle."""
        try:
            self._glw.update()
        except Exception:
            pass

    def draw(self):
        """Synchronous redraw alias."""
        self.draw_idle()

    def _hide_cursor_items(self, items):
        for item in items or []:
            try:
                item.setVisible(False)
            except Exception:
                pass

    def _cursor_line_handles(self):
        """ViewBox owners for vertical cursor/hover lines."""
        if self._overlay_mode and self._x_master_handle is not None:
            return [self._x_master_handle]
        return list(self.axes_list)

    def _ensure_cursor_items(self, attr_name, *, color, width=1.0, style=Qt.SolidLine):
        handles = self._cursor_line_handles()
        owners = [handle.view_box for handle in handles if handle.view_box is not None]
        items = getattr(self, attr_name, [])
        item_owners = [self._cursor_item_owner(item) for item in items]
        if len(items) == len(owners) and all(
            owner is expected for owner, expected in zip(item_owners, owners)
        ):
            return items
        self._remove_cursor_items(items)
        pen = pg.mkPen(color=color, width=width, style=style)
        new_items = []
        for vb in owners:
            line = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=pen)
            line.setZValue(1000)
            line.setVisible(False)
            try:
                vb.addItem(line, ignoreBounds=True)
                new_items.append(line)
                self._cursor_item_owners[id(line)] = vb
            except Exception:
                pass
        setattr(self, attr_name, new_items)
        return new_items

    def _cursor_item_owner(self, item):
        owner = self._cursor_item_owners.get(id(item))
        if owner is not None:
            return owner
        try:
            owner = item.getViewBox()
        except Exception:
            owner = None
        if owner is not None:
            self._cursor_item_owners[id(item)] = owner
        return owner

    def _remove_cursor_items(self, items):
        for item in items or []:
            owner = self._cursor_item_owners.pop(id(item), None)
            try:
                item.setVisible(False)
            except Exception:
                pass
            removed = False
            try:
                if owner is None:
                    owner = item.getViewBox()
                if owner is not None:
                    owner.removeItem(item)
                    removed = True
            except Exception:
                pass
            if not removed:
                try:
                    scene = item.scene()
                    if scene is not None:
                        scene.removeItem(item)
                except Exception:
                    pass
        if items:
            items.clear()

    def _set_cursor_items_pos(self, items, x):
        for item in items or []:
            try:
                item.setValue(float(x))
                item.setVisible(True)
            except Exception:
                pass

    def _ensure_dual_cursor_extreme_markers(self):
        markers = getattr(self, "_dual_cursor_extreme_markers", [])
        if len(markers) == len(self.axes_list):
            return markers
        for marker in markers or []:
            try:
                marker.setVisible(False)
            except Exception:
                pass
        new_markers = []
        for handle in self.axes_list:
            vb = handle.view_box
            if vb is None:
                continue
            marker = pg.ScatterPlotItem(size=10)
            marker.setZValue(1100)
            marker.setVisible(False)
            try:
                vb.addItem(marker, ignoreBounds=True)
                new_markers.append(marker)
            except Exception:
                pass
        self._dual_cursor_extreme_markers = new_markers
        return new_markers

    def _hide_dual_cursor_extreme_markers(self):
        for marker in getattr(self, "_dual_cursor_extreme_markers", []) or []:
            try:
                marker.setData([], [])
                marker.setVisible(False)
            except Exception:
                pass

    def _update_dual_cursor_extreme_markers(self, points_by_channel):
        markers = self._ensure_dual_cursor_extreme_markers()
        points_by_handle = {}
        for channel_key, min_x, min_y, max_x, max_y in points_by_channel:
            pair = self._channel_lines.get(channel_key)
            if pair is None:
                continue
            handle = pair[0]
            points_by_handle.setdefault(handle, []).extend((
                (min_x, min_y, "#16a34a"),
                (max_x, max_y, "#dc2626"),
            ))
        for marker, handle in zip(markers, self.axes_list):
            points = points_by_handle.get(handle, [])
            try:
                if not points:
                    marker.setData([], [])
                    marker.setVisible(False)
                    continue
                marker.setData(
                    [point[0] for point in points],
                    [point[1] for point in points],
                    symbol="o",
                    size=10,
                    pen=[pg.mkPen("#ffffff", width=1.2) for _ in points],
                    brush=[pg.mkBrush(point[2]) for point in points],
                )
                marker.setVisible(True)
            except Exception:
                pass

    def _cursor_data_x_from_viewport_pos(self, viewport_pos):
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        handle = self._axis_handle_at_scene_pos(scene_pos)
        if handle is None or handle.view_box is None:
            return None
        try:
            data_pos = handle.view_box.mapSceneToView(scene_pos)
            x = float(data_pos.x())
        except Exception:
            return None
        if not np.isfinite(x):
            return None
        return x

    def _handle_cursor_mouse_move(self, event_or_pos):
        if not self._cursor_visible:
            return False
        try:
            if event_or_pos.buttons() & Qt.LeftButton:
                return False
            viewport_pos = event_or_pos.pos()
        except Exception:
            viewport_pos = event_or_pos
        x = self._cursor_data_x_from_viewport_pos(viewport_pos)
        if x is None:
            return False
        now = _time.monotonic() * 1000
        if now - self._last_t < 33:
            return True
        self._last_t = now
        if self._dual:
            hover_items = self._ensure_cursor_items(
                "_cursor_line_items", color="#64748b", width=1.0, style=Qt.DotLine
            )
            self._set_cursor_items_pos(hover_items, x)
        else:
            items = self._ensure_cursor_items(
                "_cursor_line_items", color="#111827", width=1.0
            )
            self._set_cursor_items_pos(items, x)
            self._emit_single_cursor_html(x)
        self.draw_idle()
        return True

    def _handle_cursor_mouse_press(self, event):
        if not (self._cursor_visible and self._dual):
            return False
        try:
            if event.button() != Qt.LeftButton:
                return False
        except Exception:
            return False
        x = self._cursor_data_x_from_viewport_pos(event.pos())
        if x is None:
            return False
        if self._placing == "A":
            self._ax = x
            self._placing = "B"
            a_items = self._ensure_cursor_items(
                "_cursor_a_items", color="#2563eb", width=1.1
            )
            self._set_cursor_items_pos(a_items, x)
        else:
            self._bx = x
            self._placing = "A"
            b_items = self._ensure_cursor_items(
                "_cursor_b_items", color="#dc2626", width=1.1
            )
            self._set_cursor_items_pos(b_items, x)
        self._emit_dual_cursor_html()
        self.draw_idle()
        return True

    def _scene_y_from_viewport_pos(self, viewport_pos):
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        if scene_pos is None:
            return None
        try:
            return float(scene_pos.y())
        except Exception:
            return None

    def _select_overlay_channel_from_scene_pos(self, scene_pos):
        if scene_pos is None:
            return None

        best_name = None
        best_dist = float("inf")
        try:
            px = float(scene_pos.x())
            py = float(scene_pos.y())
        except Exception:
            return None
        for name, (handle, line) in self._channel_lines.items():
            vb = handle.view_box
            if vb is None:
                continue
            pdi = line.plot_data_item
            # Skip hidden curves: 显示原始/显示滤波后 off makes the line
            # invisible, but its data is still present — it must NOT be a
            # selectable/draggable target (排除另外一个).
            try:
                if not pdi.isVisible():
                    continue
            except Exception:
                pass
            try:
                xdata, ydata = pdi.getData()
            except Exception:
                xdata = ydata = None
            if xdata is None or ydata is None:
                continue
            xdata = np.asarray(xdata, dtype=float)
            ydata = np.asarray(ydata, dtype=float)
            n = min(xdata.size, ydata.size)
            if n == 0:
                continue
            xdata = xdata[:n]
            ydata = ydata[:n]
            finite = np.isfinite(xdata) & np.isfinite(ydata)
            if not finite.any():
                continue
            xdata = xdata[finite]
            ydata = ydata[finite]
            if n > 3000:
                step = max(1, xdata.size // 3000)
                xdata = xdata[::step]
                ydata = ydata[::step]
            try:
                scene_pts = self._map_view_points_to_scene(vb, xdata, ydata)
            except Exception:
                continue
            if scene_pts is None or scene_pts.size == 0:
                continue
            dist = float(np.min(np.hypot(scene_pts[:, 0] - px, scene_pts[:, 1] - py)))
            if dist < best_dist:
                best_dist = dist
                best_name = name
        if best_name is not None and best_dist <= self._overlay_axes.pick_radius_px:
            return best_name
        return None

    def _map_view_points_to_scene(self, view_box, xdata, ydata):
        try:
            from PyQt5.QtCore import QPointF
        except Exception:
            return None
        pts = np.empty((xdata.size, 2), dtype=float)
        ok = 0
        for i in range(xdata.size):
            try:
                sp = view_box.mapViewToScene(QPointF(float(xdata[i]), float(ydata[i])))
                pts[ok, 0] = float(sp.x())
                pts[ok, 1] = float(sp.y())
                ok += 1
            except Exception:
                continue
        if ok == 0:
            return None
        return pts[:ok]

    def _hidden_channel_names(self):
        """Return the set of DISPLAY names whose curve is currently hidden
        (显示原始/显示滤波后 off). The cursor reads samples from
        ``channel_data`` (which always carries the full series, hidden or
        not), so the readout must drop a channel whose ``PlotDataItem`` is not
        visible — otherwise a hidden original/companion still shows up in the
        cursor pill and the dual-cursor stats (and its extreme markers paint).
        Keyed by composite (fid, name) so a same-named channel from another
        file is not falsely hidden."""
        hidden = set()
        lines = getattr(self, "_channel_lines", None)
        if lines is None:
            return hidden
        try:
            items = lines.composite_items()
        except Exception:
            return hidden
        for _ck, name, value in items:
            try:
                pdi = value[1].plot_data_item
                if pdi is not None and not pdi.isVisible():
                    hidden.add(name)
            except Exception:
                pass
        return hidden

    def _emit_single_cursor_html(self, x):
        sep = ('<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>')
        parts = [f'<span style="color:#111827;">t={x:.4f}s</span>']
        hidden = self._hidden_channel_names()
        for ch, (tf, sf, color, u) in self.channel_data.items():
            if ch in hidden:
                continue
            if len(tf):
                idx = min(np.searchsorted(tf, x), len(sf) - 1)
                unit_s = f" {u}" if u else ""
                parts.append(_format_single_cursor_channel_html(ch, sf[idx], unit_s, color))
        self.cursor_info.emit(sep.join(parts))

    def _emit_dual_cursor_html(self):
        info, dual = [], []
        extreme_points = []
        if self._ax is not None:
            info.append(f"A={self._ax:.4f}s")
        if self._bx is not None:
            info.append(f"B={self._bx:.4f}s")
        if self._ax is not None and self._bx is not None:
            dx = self._bx - self._ax
            info.append(f"ΔT={dx:.4f}s")
            if abs(dx) > 1e-12:
                info.append(f"1/ΔT={1 / abs(dx):.2f}Hz")
            xlo, xhi = min(self._ax, self._bx), max(self._ax, self._bx)
            hidden = self._hidden_channel_names()
            if hasattr(self.channel_data, "composite_items"):
                channel_items = self.channel_data.composite_items()
            else:
                channel_items = (
                    (ch, ch, values)
                    for ch, values in self.channel_data.items()
                )
            for channel_key, ch, (tf, sf, color, u) in channel_items:
                if ch in hidden:
                    continue
                if not len(tf):
                    continue
                m = (tf >= xlo) & (tf <= xhi)
                seg = sf[m]
                if not len(seg):
                    continue
                segment_indices = np.flatnonzero(m)
                finite = np.isfinite(seg)
                if np.any(finite):
                    finite_segment = seg[finite]
                    finite_indices = segment_indices[finite]
                    min_idx = int(finite_indices[int(np.argmin(finite_segment))])
                    max_idx = int(finite_indices[int(np.argmax(finite_segment))])
                    extreme_points.append((
                        channel_key,
                        float(tf[min_idx]),
                        float(sf[min_idx]),
                        float(tf[max_idx]),
                        float(sf[max_idx]),
                    ))
                u_suffix = f" {u}" if u else ""
                delta = _interp_cursor_value(tf, sf, self._bx) - _interp_cursor_value(
                    tf, sf, self._ax
                )
                dual.append((
                    ch,
                    float(np.min(seg)),
                    float(np.max(seg)),
                    float(np.mean(seg)),
                    float(delta),
                    u_suffix,
                    color,
                ))
        if info:
            primary_html = ('<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
                            .join(f'<span style="color:#111827;">{p}</span>' for p in info))
        else:
            primary_html = "Click A"
        self.cursor_info.emit(primary_html)
        self.dual_cursor_info.emit(_format_dual_html(dual) if dual else "")
        self.dual_cursor_rows.emit(dual if dual else [])
        if self._ax is not None and self._bx is not None:
            self._update_dual_cursor_extreme_markers(extreme_points)
        else:
            self._hide_dual_cursor_extreme_markers()

    def _cursor_x_to_pixmap_x(self, data_x, pixmap_width):
        primary = self._primary_xaxis_ax
        if primary is None:
            return 0.0
        try:
            lo, hi = primary.get_xlim()
        except Exception:
            return 0.0
        if hi <= lo:
            return 0.0
        frac = (float(data_x) - lo) / (hi - lo)
        frac = max(0.0, min(1.0, frac))
        return frac * float(pixmap_width)


__all__ = ["CursorController"]
