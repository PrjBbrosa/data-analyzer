"""Cursor interaction helpers for the pyqtgraph time-domain canvas."""

from __future__ import annotations

import time as _time
from dataclasses import replace

import numpy as np
from PyQt5 import sip
from PyQt5.QtCore import Qt

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref

import pyqtgraph as pg

from mf4_analyzer.signal.custom_x_paths import (
    REASON_EMPTY,
    REASON_INCOMPATIBLE_SHAPE,
    REASON_MULTIPLE_PATHS,
    REASON_SAME_DIRECTION,
    REASON_SHORT_SEQUENCE,
    REASON_UNIDIRECTIONAL,
    CustomXCursorResult,
    analyze_custom_x_paths,
    clip_paths,
    sample_custom_x_cursor_from_paths,
    sample_custom_x_dual_delta_from_paths,
)
from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayBranch,
    CursorDisplayChannel,
    CursorDisplayOptions,
)
from mf4_analyzer.ui.plot_helpers import (
    DualCursorBranch,
    DualCursorRow,
    apply_cursor_source_prefix_policy,
    _cursor_identity_parts,
    _format_dual_html,
    _format_single_cursor_channel_html,
    _interp_cursor_value,
    resolve_cursor_source_label,
)
from mf4_analyzer.ui.time_xaxis import CHANNEL_MODE, CursorXAxisContext, TIME_MODE


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
        "_dual_cursor_extreme_points",
        "_cursor_display_options",
        "_source_label_resolver",
        "_custom_x_path_cache",
        "_x_axis_context",
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
        "set_x_axis_context",
        "set_cursor_display_options",
        "cursor_display_options",
        "set_source_label_resolver",
        "invalidate_custom_x_path_cache",
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
        self._dual_cursor_extreme_points = ()
        self._cursor_display_options = None
        self._source_label_resolver = None
        self._custom_x_path_cache = {}
        self._x_axis_context = None

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

    def capture_dual_geometry(self):
        """Armed dual A/B x only. Single-mode hover x is not a capture fact."""
        if not self.dual:
            return None
        ax = _finite_float(self.ax)
        bx = _finite_float(self.bx)
        if ax is None and bx is None:
            return None
        return ("dual", ax, bx)

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
        # Scatter markers are transient cursor decoration.  They are not owned
        # by ``_cursor_item_owners``, so hide their data explicitly before
        # dropping the wrappers during a canvas rebuild.
        self._hide_dual_cursor_extreme_markers()
        self._dual_cursor_extreme_markers = []
        self._dual_cursor_extreme_points = ()
        self.cursor_info.emit("")
        self.dual_cursor_info.emit("")
        self.single_cursor_rows.emit([])
        self.dual_cursor_rows.emit([])

    def reset_all_state(self):
        self._ax = None
        self._bx = None
        self._placing = "A"
        self._cursor_visible = False
        self._dual = False
        self._last_t = 0
        self._x_axis_context = None
        self._dual_cursor_extreme_points = ()

    def set_x_axis_context(self, context):
        self._x_axis_context = context

    def set_source_label_resolver(self, resolver):
        self._source_label_resolver = resolver

    def invalidate_custom_x_path_cache(self, data_id=None, channel=None):
        """Drop memoized ``analyze_custom_x_paths`` results.

        No filters (the monotonicity / envelope full-clear shape) drop the
        whole memo. A ``data_id`` and/or ``channel`` filter drops matching
        keys only. ``channel`` is the composite identity used in
        ``channel_data``.
        """
        if data_id is None and channel is None:
            self._custom_x_path_cache.clear()
            return
        drop = []
        for key in self._custom_x_path_cache:
            key_data_id, key_channel = key
            if data_id is not None and key_data_id != data_id:
                continue
            if channel is not None and key_channel != channel:
                continue
            drop.append(key)
        for key in drop:
            self._custom_x_path_cache.pop(key, None)

    def _custom_x_path_data_id(self, channel_key):
        mapping = getattr(self, "_channel_data_id", None)
        if mapping is None:
            return None
        getter = getattr(mapping, "get", None)
        if not callable(getter):
            return None
        return getter(channel_key)

    @staticmethod
    def _custom_x_path_version(tf, sf):
        tf = np.asarray(tf)
        sf = np.asarray(sf)
        n = int(tf.size)
        if n == 0:
            return (0, 0.0, 0.0, 0.0, 0.0)
        y0 = float(sf[0]) if sf.size else 0.0
        y1 = float(sf[-1]) if sf.size else 0.0
        return (n, float(tf[0]), float(tf[-1]), y0, y1)

    def _custom_x_paths_for_channel(self, channel_key, tf, sf, x_range=None):
        """Return memoized full paths, then apply any cursor A/B clip."""
        try:
            tf_array = np.asarray(tf, dtype=float)
            sf_array = np.asarray(sf, dtype=float)
        except (TypeError, ValueError):
            return None
        if (
            tf_array.ndim != 1
            or sf_array.ndim != 1
            or tf_array.size != sf_array.size
        ):
            return None
        key = (self._custom_x_path_data_id(channel_key), channel_key)
        version = self._custom_x_path_version(tf_array, sf_array)
        cached = self._custom_x_path_cache.get(key)
        if cached is not None and cached[0] == version:
            paths = cached[1]
        else:
            paths = analyze_custom_x_paths(tf_array, sf_array)
            self._custom_x_path_cache[key] = (version, paths)
        return clip_paths(paths, x_range)

    def _sample_custom_x_cursor_cached(self, channel_key, tf, sf, x_value):
        paths = self._custom_x_paths_for_channel(channel_key, tf, sf)
        if paths is None:
            return CustomXCursorResult((), REASON_INCOMPATIBLE_SHAPE)
        return sample_custom_x_cursor_from_paths(paths, x_value)

    def set_cursor_display_options(self, options):
        if not isinstance(options, CursorDisplayOptions):
            raise TypeError("options must be CursorDisplayOptions")
        previous = self.cursor_display_options()
        self._cursor_display_options = options
        value_changed = (
            previous.show_max_value,
            previous.show_min_value,
            previous.show_avg_value,
            previous.show_delta_value,
        ) != (
            options.show_max_value,
            options.show_min_value,
            options.show_avg_value,
            options.show_delta_value,
        )
        point_changed = (
            previous.show_max_point,
            previous.show_min_point,
        ) != (
            options.show_max_point,
            options.show_min_point,
        )
        if self._dual and self._ax is not None and value_changed:
            self._emit_dual_cursor_html()
        elif self._dual and self._ax is not None and point_changed:
            self._update_dual_cursor_extreme_markers(
                self._dual_cursor_extreme_points
            )
            self.draw_idle()

    def cursor_display_options(self):
        if self._cursor_display_options is None:
            return CursorDisplayOptions()
        return self._cursor_display_options

    @property
    def x_axis_context(self):
        return self._x_axis_context

    @x_axis_context.setter
    def x_axis_context(self, value):
        self._x_axis_context = value

    def _is_custom_x_cursor(self):
        ctx = self._x_axis_context
        if ctx is None:
            return False
        mode = getattr(ctx, "mode", TIME_MODE)
        return mode in (CHANNEL_MODE, "channel")

    def set_cursor_visible(self, v):
        """Toggle single-cursor visibility."""
        self._cursor_visible = bool(v)
        if not self._cursor_visible:
            self._hide_cursor_items(self._cursor_line_items)
            self._hide_cursor_items(self._cursor_a_items)
            self._hide_cursor_items(self._cursor_b_items)
            self._hide_dual_cursor_extreme_markers()
            self._dual_cursor_extreme_points = ()
            self.single_cursor_rows.emit([])
            self.dual_cursor_rows.emit([])
            self.cursor_info.emit("")
            self.dual_cursor_info.emit("")
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
            self.dual_cursor_rows.emit([])
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
        self._dual_cursor_extreme_points = ()
        self.dual_cursor_info.emit("")
        self.dual_cursor_rows.emit([])
        self.single_cursor_rows.emit([])
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
        return [
            handle for handle in self.axes_list
            if not getattr(handle, "placeholder", False)
        ]

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
        handles = [
            handle for handle in self.axes_list
            if not getattr(handle, "placeholder", False)
        ]
        if len(markers) == len(handles):
            return markers
        for marker in markers or []:
            self._run_marker_cleanup(marker, lambda: marker.setVisible(False))
        new_markers = []
        for handle in handles:
            vb = handle.view_box
            if vb is None:
                continue
            marker = pg.ScatterPlotItem(size=10)
            marker.setZValue(1100)
            marker.setVisible(False)
            # Creation/binding failures are programming or collaborator
            # failures, not teardown.  Let them propagate rather than hiding
            # a missing marker behind an empty cursor result.
            vb.addItem(marker, ignoreBounds=True)
            new_markers.append(marker)
        self._dual_cursor_extreme_markers = new_markers
        return new_markers

    def _hide_dual_cursor_extreme_markers(self):
        for marker in getattr(self, "_dual_cursor_extreme_markers", []) or []:
            def hide_marker():
                marker.setData([], [])
                marker.setVisible(False)
            self._run_marker_cleanup(marker, hide_marker)

    @staticmethod
    def _run_marker_cleanup(marker, operation):
        """Ignore only the expected race with Qt wrapper destruction.

        Cursor cleanup can run after a ViewBox has deleted its transient
        ScatterPlotItem. Any other marker error represents malformed data or
        wiring and must remain visible to the caller.
        """
        if marker is None or sip.isdeleted(marker):
            return
        try:
            operation()
        except RuntimeError as exc:
            message = str(exc)
            if sip.isdeleted(marker) or (
                "wrapped C/C++ object" in message
                and "has been deleted" in message
            ):
                return
            raise

    def _update_dual_cursor_extreme_markers(self, points_by_channel):
        markers = self._ensure_dual_cursor_extreme_markers()
        options = self.cursor_display_options()
        points_by_handle = {}
        for channel_key, min_x, min_y, max_x, max_y in points_by_channel:
            pair = self._channel_lines.get(channel_key)
            if pair is None:
                continue
            handle = pair[0]
            points = points_by_handle.setdefault(handle, [])
            if options.show_min_point:
                points.append((min_x, min_y, "#16a34a", "o"))
            if options.show_max_point:
                points.append((max_x, max_y, "#dc2626", "d"))
        for marker, handle in zip(markers, [
            h for h in self.axes_list if not getattr(h, "placeholder", False)
        ]):
            points = points_by_handle.get(handle, [])
            if not points:
                marker.setData([], [])
                marker.setVisible(False)
                continue
            marker.setData(
                [point[0] for point in points],
                [point[1] for point in points],
                symbol=[point[3] for point in points],
                size=10,
                pen=[pg.mkPen("#ffffff", width=1.2) for _ in points],
                brush=[pg.mkBrush(point[2]) for point in points],
            )
            marker.setVisible(True)

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
        """Return the set of COMPOSITE keys whose curve is currently hidden
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
        for channel_key, _name, value in items:
            try:
                pdi = value[1].plot_data_item
                if pdi is not None and not pdi.isVisible():
                    hidden.add(channel_key)
            except Exception:
                pass
        return hidden

    def _emit_single_cursor_html(self, x):
        sep = ('<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>')
        custom_x = self._is_custom_x_cursor()
        if custom_x:
            parts = [
                f'<span style="color:#111827;">'
                f'X={self._format_cursor_axis_number(x)}'
                f'{self._cursor_x_unit_suffix()}</span>'
            ]
        else:
            parts = [f'<span style="color:#111827;">t={x:.4f}s</span>']
        rows = []
        for channel_key, ch, (tf, sf, color, u) in self._visible_channel_items():
            source_label, channel_label = resolve_cursor_source_label(
                ch, channel_key, self._source_label_resolver
            )
            unit_s = f" {u}" if u else ""
            if custom_x:
                result = self._sample_custom_x_cursor_cached(
                    channel_key, tf, sf, x,
                )
                branches = tuple(
                    CursorDisplayBranch(
                        self._custom_x_branch_face(value.direction),
                        current_value=value.value,
                    )
                    for value in result.values
                )
                rows.append(CursorDisplayChannel(
                    identity=channel_key,
                    source_label=source_label,
                    channel_label=channel_label,
                    color=color,
                    unit_suffix=unit_s,
                    branches=branches,
                    diagnostic=self._custom_x_single_status(
                        result.reason, bool(branches)
                    ),
                ))
                for branch in branches:
                    parts.append(_format_single_cursor_channel_html(
                        f"{ch} {branch.label}",
                        branch.current_value,
                        unit_s,
                        color,
                    ))
                continue
            if len(tf):
                idx = min(np.searchsorted(tf, x), len(sf) - 1)
                value = sf[idx]
                parts.append(_format_single_cursor_channel_html(
                    ch, value, unit_s, color
                ))
                rows.append(CursorDisplayChannel(
                    identity=channel_key,
                    source_label=source_label,
                    channel_label=channel_label,
                    color=color,
                    unit_suffix=unit_s,
                    current_value=float(value),
                ))
        rows = apply_cursor_source_prefix_policy(rows)
        self.cursor_info.emit(sep.join(parts))
        self.single_cursor_rows.emit(rows)

    def _cursor_x_unit_suffix(self):
        ctx = self._x_axis_context
        unit = str(getattr(ctx, "unit", "") or "").strip()
        return f" {unit}" if unit else ""

    def _format_cursor_axis_number(self, x):
        """Format a custom-X coordinate for the primary pill line.

        Shared by single-cursor ``X=`` and dual-cursor ``A=`` / ``B=`` / ``ΔX=``
        so both faces use the same axis-context precision instead of a
        hardcoded ``:.1f``.
        """
        try:
            value = float(x)
        except (TypeError, ValueError):
            return str(x)
        if not np.isfinite(value):
            return "—"
        return f"{value:.4g}"

    @staticmethod
    def _custom_x_branch_face(direction):
        if direction > 0:
            return "X↑"
        if direction < 0:
            return "X↓"
        return "全程"

    def _hidden_display_names(self):
        """Display-name projection of :meth:`_hidden_channel_names`.

        Hidden identities are composite keys (JSON ``[fid, name]``). Plain-dict
        ``channel_data`` iterates by display name, so the fallback path must
        stay in that domain instead of mixing the two.
        """
        names = set()
        for key in self._hidden_channel_names():
            _source, channel = _cursor_identity_parts(key)
            if channel:
                names.add(channel)
            else:
                names.add(key)
        return names

    def _visible_channel_items(self):
        if hasattr(self.channel_data, "composite_items"):
            hidden = self._hidden_channel_names()
            channel_items = self.channel_data.composite_items()
            for channel_key, ch, values in channel_items:
                if channel_key in hidden:
                    continue
                yield channel_key, ch, values
            return
        hidden_names = self._hidden_display_names()
        for ch, values in self.channel_data.items():
            if ch in hidden_names:
                continue
            yield ch, ch, values

    def _finite_stats(self, y):
        y = np.asarray(y, dtype=float)
        finite = y[np.isfinite(y)]
        if not finite.size:
            return None
        return float(np.min(finite)), float(np.max(finite)), float(np.mean(finite))

    def _extrema_from_contribution(self, channel_key, contrib):
        x = np.asarray(contrib.x, dtype=float)
        y = np.asarray(contrib.y, dtype=float)
        finite = np.isfinite(x) & np.isfinite(y)
        if not np.any(finite):
            return None
        xf = x[finite]
        yf = y[finite]
        min_i = int(np.argmin(yf))
        max_i = int(np.argmax(yf))
        return (
            channel_key,
            float(xf[min_i]),
            float(yf[min_i]),
            float(xf[max_i]),
            float(yf[max_i]),
        )

    def _custom_x_status(self, reason):
        if reason == REASON_EMPTY:
            return "区间内无数据"
        if reason == REASON_INCOMPATIBLE_SHAPE:
            return "X/Y 形状不兼容"
        if reason in (REASON_UNIDIRECTIONAL, REASON_SHORT_SEQUENCE):
            return "全程"
        if reason == REASON_SAME_DIRECTION:
            return "两次同向访问，无法确定升程/回程"
        if reason == REASON_MULTIPLE_PATHS:
            return "无法可靠区分升程/回程"
        return ""

    def _custom_x_single_status(self, reason, has_values):
        if has_values:
            return ""
        if reason == REASON_SHORT_SEQUENCE:
            return "有效数据不足"
        if reason == REASON_EMPTY:
            return "当前 X 不在有效路径内"
        return self._custom_x_status(reason)

    def _build_custom_x_dual_row(self, channel_key, ch, tf, sf, color, unit_suffix, xlo, xhi):
        ctx = self._x_axis_context
        x_unit = str(getattr(ctx, "unit", "") or "").strip()
        tf_array = np.asarray(tf)
        sf_array = np.asarray(sf)
        if (
            tf_array.ndim != 1
            or sf_array.ndim != 1
            or tf_array.size != sf_array.size
        ):
            return DualCursorRow(
                channel_name=ch,
                min_value=None,
                max_value=None,
                avg=None,
                delta=None,
                unit_suffix=unit_suffix,
                color=color,
                identity=channel_key,
                label=ch,
                mode=CHANNEL_MODE,
                branch="",
                status=self._custom_x_status(REASON_INCOMPATIBLE_SHAPE),
                x_unit=x_unit,
                branches=(),
            ), []
        full_paths = self._custom_x_paths_for_channel(channel_key, tf_array, sf_array)
        result = clip_paths(full_paths, (xlo, xhi))
        status = self._custom_x_status(result.reason)
        branches = ()
        stats = None
        delta_by_dir = {}
        # Statistics use only in-range samples. Endpoint interpolation needs
        # the original physical leg, including neighbors outside A/B. Match
        # acquisition indices, not direction alone (cycles can repeat).
        sampling_legs = tuple(
            full for selected in result.accepted
            for full in full_paths.contributions
            if full.direction == selected.direction
            and full.indices[0] <= selected.indices[0]
            and full.indices[-1] >= selected.indices[-1]
        )
        for direction, delta in sample_custom_x_dual_delta_from_paths(
            replace(result, accepted=sampling_legs), self._ax, self._bx,
        ):
            delta_by_dir[int(direction)] = delta
        if result.unique_pair:
            ordered = sorted(result.accepted, key=lambda item: -int(item.direction))
            branch_rows = []
            for contrib in ordered:
                stats = self._finite_stats(contrib.y)
                if stats is None:
                    continue
                direction = int(contrib.direction)
                branch_rows.append(DualCursorBranch(
                    direction=direction,
                    min_value=stats[0],
                    max_value=stats[1],
                    avg=stats[2],
                    delta=delta_by_dir.get(direction),
                ))
            branches = tuple(branch_rows)
            status = ""
        elif result.reason in (REASON_UNIDIRECTIONAL, REASON_SHORT_SEQUENCE):
            samples = result.accepted or result.contributions
            if samples:
                y = np.concatenate(tuple(np.asarray(item.y, dtype=float) for item in samples))
                stats = self._finite_stats(y)
            if stats is not None:
                direction = 0
                if result.reason == REASON_UNIDIRECTIONAL:
                    known_directions = {
                        int(item.direction)
                        for item in result.accepted
                        if int(item.direction) in (-1, 1)
                    }
                    if len(known_directions) == 1:
                        direction = known_directions.pop()
                branches = (DualCursorBranch(
                    direction=direction,
                    min_value=stats[0],
                    max_value=stats[1],
                    avg=stats[2],
                    delta=delta_by_dir.get(direction),
                ),)
                if direction:
                    status = ""
            else:
                status = "区间内无数据"
        extrema = []
        if result.unique_pair:
            sources = result.accepted
        elif result.reason in (REASON_UNIDIRECTIONAL, REASON_SHORT_SEQUENCE):
            sources = result.accepted or result.contributions
        else:
            sources = ()
        for contrib in sources:
            point = self._extrema_from_contribution(channel_key, contrib)
            if point is not None:
                extrema.append(point)
        row = DualCursorRow(
            channel_name=ch,
            min_value=None if not branches else branches[0].min_value,
            max_value=None if not branches else branches[0].max_value,
            avg=None if not branches else branches[0].avg,
            delta=None,
            unit_suffix=unit_suffix,
            color=color,
            identity=channel_key,
            label=ch,
            mode=CHANNEL_MODE,
            branch="",
            status=status,
            x_unit=x_unit,
            branches=branches,
        )
        return row, extrema

    def _emit_dual_cursor_html(self):
        info, dual = [], []
        extreme_points = []
        custom_x = self._is_custom_x_cursor()
        unit_suffix = self._cursor_x_unit_suffix() if custom_x else "s"
        if self._ax is not None:
            if custom_x:
                info.append(
                    f"A={self._format_cursor_axis_number(self._ax)}{unit_suffix}"
                )
            else:
                info.append(f"A={self._ax:.4f}s")
        if self._bx is not None:
            if custom_x:
                info.append(
                    f"B={self._format_cursor_axis_number(self._bx)}{unit_suffix}"
                )
            else:
                info.append(f"B={self._bx:.4f}s")
        if self._ax is not None and self._bx is not None:
            dx = self._bx - self._ax
            if custom_x:
                info.append(
                    f"ΔX={self._format_cursor_axis_number(abs(dx))}{unit_suffix}"
                )
            else:
                info.append(f"ΔT={dx:.4f}s")
                if abs(dx) > 1e-12:
                    info.append(f"1/ΔT={1 / abs(dx):.2f}Hz")
            xlo, xhi = min(self._ax, self._bx), max(self._ax, self._bx)
            for channel_key, ch, (tf, sf, color, u) in self._visible_channel_items():
                if not len(tf):
                    continue
                y_suffix = f" {u}" if u else ""
                if custom_x:
                    row, extrema = self._build_custom_x_dual_row(
                        channel_key, ch, tf, sf, color, y_suffix, xlo, xhi,
                    )
                    dual.append(row)
                    extreme_points.extend(extrema)
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
                delta = _interp_cursor_value(tf, sf, self._bx) - _interp_cursor_value(
                    tf, sf, self._ax
                )
                dual.append(DualCursorRow(
                    channel_name=ch,
                    min_value=float(np.min(seg)),
                    max_value=float(np.max(seg)),
                    avg=float(np.mean(seg)),
                    delta=float(delta),
                    unit_suffix=y_suffix,
                    color=color,
                    identity=channel_key,
                    label=ch,
                    mode=TIME_MODE,
                ))
        if info:
            primary_html = ('<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
                            .join(f'<span style="color:#111827;">{p}</span>' for p in info))
        else:
            primary_html = "Click A"
        self.cursor_info.emit(primary_html)
        options = self.cursor_display_options()
        formatter_options = None if (
            options.show_max_value
            and options.show_min_value
            and options.show_avg_value
            and options.show_delta_value
        ) else options
        self.dual_cursor_info.emit(
            _format_dual_html(dual, formatter_options) if dual else ""
        )
        self.dual_cursor_rows.emit(dual if dual else [])
        self._dual_cursor_extreme_points = tuple(extreme_points)
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


__all__ = ["CursorController", "CursorXAxisContext"]
