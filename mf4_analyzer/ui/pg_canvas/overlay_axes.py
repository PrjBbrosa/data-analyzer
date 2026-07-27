"""Overlay axis and interaction helpers for the pyqtgraph time-domain canvas."""

from __future__ import annotations

import math

import numpy as np
from PyQt5.QtCore import QEasingCurve, QVariantAnimation, Qt
from PyQt5.QtGui import QFontMetrics

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref

import pyqtgraph as pg

from mf4_analyzer.ui._axis_handle import (
    PG_AXIS_NEUTRAL_COLOR,
    PG_AXIS_NEUTRAL_WIDTH,
    PgAxisHandle,
    _PgLineHandle,
)
from mf4_analyzer.signal.envelope import _is_monotonic_array
from mf4_analyzer.ui.plot_helpers import _middle_ellipsis

from ._shared import _subplot_ylabel_text, _view_state_channel_key
from .context_menu import _localize_pg_context_menu
from .fonts import _apply_pg_axis_font, _pg_chart_font
from .render_profile import (
    bucket_width_for,
    classify_render_profile,
    source_revision_for,
)
from .ticks_math import _adjacent_nice_step, _fmt_tick, _frame_to_nice
from .viewbox import _ModifierWheelViewBox


_OVERLAY_GRID_ALPHA = 0.28
_DEFAULT_OVERLAY_DIVISIONS = 10
_OVERLAY_AXIS_LABEL_MIN_CHARS = 12
_OVERLAY_AXIS_LABEL_FALLBACK_CHARS = 22
_OVERLAY_AXIS_LABEL_VERTICAL_PADDING_PX = 32.0

class OverlayAxisManager(_CanvasBackref):
    """Overlay axis binding, graticule, selection, and interaction routing."""

    _owned_names = frozenset({
        "selected_channel",
        "drag_start",
        "dragging",
        "snap_anim",
        "snap_anim_ms",
        "divisions",
        "_selected_overlay_channel",
        "_overlay_default_lw",
        "_overlay_default_alpha",
        "_overlay_selected_lw",
        "_overlay_selected_alpha",
        "_overlay_de_emphasised_lw",
        "_overlay_de_emphasised_alpha",
        "_overlay_pick_radius_px",
        "_overlay_axis_column_spacing",
        "_overlay_y_drag_start",
        "_overlay_dragging",
        "_snap_anim",
        "_snap_anim_ms",
        "_overlay_aux_viewboxes",
        "_overlay_aux_axes",
        "_overlay_view_sync_conns",
        "_overlay_divisions",
        "_overlay_grid_lines",
    })

    _delegate_names = frozenset({
        "_add_overlay_axis_handle",
        "_bind_channel",
        "_bind_companion",
        "_overlay_axis_label",
        "_overlay_axis_label_max_chars",
        "_overlay_axis_label_available_height",
        "_refresh_overlay_axis_labels",
        "_apply_pg_axis_style",
        "_sync_pg_channel_color",
        "_configure_overlay_axis_geometry",
        "_initial_bind_pixel_width",
        "_configure_subplot_bottom_axis",
        "_build_overlay_y_grid",
        "_repin_overlay_channel_ticks",
        "_snap_overlay_channel_to_grid",
        "_stop_snap_anim",
        "_animate_overlay_snap",
        "_apply_overlay_box_zoom_y",
        "_teardown_overlay_aux_viewboxes",
        "_overlay_axis_handle_at_scene_pos",
        "_set_x_master_mouse_enabled",
        "_press_view_box_in_rect_mode",
        "_handle_overlay_mouse_press",
        "_handle_overlay_mouse_move",
        "_handle_overlay_mouse_release",
        "_sync_overlay_aux_viewboxes",
        "_connect_overlay_view_sync",
        "_disconnect_overlay_view_sync",
        "select_overlay_channel",
        "_overlay_emphasis_for_channel",
        "_apply_overlay_emphasis",
        "_apply_pdi_emphasis",
        "_begin_overlay_y_drag_at",
        "_apply_overlay_y_drag_at",
        "_selected_overlay_axes",
        "_handle_wheel_dispatch",
    })

    def __init__(self, canvas):
        super().__init__(canvas)
        self._selected_overlay_channel = None
        self._overlay_default_lw = 1.5
        self._overlay_default_alpha = 1.0
        self._overlay_selected_lw = 2.6
        self._overlay_selected_alpha = 1.0
        self._overlay_de_emphasised_lw = 1.35
        self._overlay_de_emphasised_alpha = 0.42
        self._overlay_pick_radius_px = 12.0
        self._overlay_axis_column_spacing = 12
        self._overlay_y_drag_start = None
        self._overlay_dragging = False
        self._snap_anim = None
        self._snap_anim_ms = 150
        self._overlay_aux_viewboxes = []
        self._overlay_aux_axes = []
        self._overlay_view_sync_conns = []
        self._overlay_divisions = _DEFAULT_OVERLAY_DIVISIONS
        self._overlay_grid_lines = []

    @property
    def selected_channel(self):
        return self._selected_overlay_channel

    @selected_channel.setter
    def selected_channel(self, value):
        self._selected_overlay_channel = value

    @property
    def default_lw(self):
        return self._overlay_default_lw

    @property
    def default_alpha(self):
        return self._overlay_default_alpha

    @property
    def selected_lw(self):
        return self._overlay_selected_lw

    @property
    def selected_alpha(self):
        return self._overlay_selected_alpha

    @property
    def de_emphasised_lw(self):
        return self._overlay_de_emphasised_lw

    @property
    def de_emphasised_alpha(self):
        return self._overlay_de_emphasised_alpha

    @property
    def pick_radius_px(self):
        return self._overlay_pick_radius_px

    @property
    def axis_column_spacing(self):
        return self._overlay_axis_column_spacing

    @property
    def drag_start(self):
        return self._overlay_y_drag_start

    @drag_start.setter
    def drag_start(self, value):
        self._overlay_y_drag_start = value

    @property
    def dragging(self):
        return self._overlay_dragging

    @dragging.setter
    def dragging(self, value):
        self._overlay_dragging = bool(value)

    @property
    def snap_anim(self):
        return self._snap_anim

    @snap_anim.setter
    def snap_anim(self, value):
        self._snap_anim = value

    @property
    def snap_anim_ms(self):
        return self._snap_anim_ms

    @snap_anim_ms.setter
    def snap_anim_ms(self, value):
        self._snap_anim_ms = int(value)

    @property
    def aux_viewboxes(self):
        return self._overlay_aux_viewboxes

    @property
    def aux_axes(self):
        return self._overlay_aux_axes

    @property
    def view_sync_connections(self):
        return self._overlay_view_sync_conns

    @property
    def divisions(self):
        return self._overlay_divisions

    @divisions.setter
    def divisions(self, value):
        self._overlay_divisions = max(3, min(20, int(value)))

    def _current_overlay_divisions(self):
        return max(3, min(20, int(getattr(
            self, "_overlay_divisions", _DEFAULT_OVERLAY_DIVISIONS
        ))))

    @property
    def grid_lines(self):
        return self._overlay_grid_lines

    def reset_for_rebuild(self):
        self._selected_overlay_channel = None
        self._overlay_y_drag_start = None
        self._overlay_dragging = False
        self._snap_anim = None
        self._overlay_aux_viewboxes = []
        self._overlay_aux_axes = []
        self._overlay_view_sync_conns = []
        self._overlay_grid_lines = []

    def _add_overlay_axis_handle(self, primary_plot, index):
        """Create one dedicated Y axis/ViewBox for an overlay channel."""
        aux_vb = _ModifierWheelViewBox(owner_canvas=self._c)
        _localize_pg_context_menu(getattr(aux_vb, "menu", None))
        if index == 0:
            try:
                primary_plot.showAxis("left")
            except Exception:
                pass
            axis_item = primary_plot.getAxis("left")
        else:
            axis_item = pg.AxisItem("right")
            try:
                axis_item.enableAutoSIPrefix(False)
            except Exception:
                pass
            _apply_pg_axis_font(axis_item)
            try:
                primary_plot.layout.addItem(axis_item, 2, 2 + index)
            except Exception:
                pass
            try:
                axis_item.setZValue(-10000)
            except Exception:
                pass
            try:
                primary_plot.layout.setHorizontalSpacing(
                    self._overlay_axis_column_spacing
                )
            except Exception:
                pass
        try:
            primary_plot.scene().addItem(aux_vb)
        except Exception:
            pass
        try:
            axis_item.linkToView(aux_vb)
        except Exception:
            pass
        try:
            aux_vb.setMouseEnabled(x=False, y=False)
        except Exception:
            pass
        self._overlay_aux_viewboxes.append(aux_vb)
        self._overlay_aux_axes.append(axis_item)
        return PgAxisHandle(
            plot_item=primary_plot,
            view_box=aux_vb,
            axis_item=axis_item,
            owner_canvas=self._c,
            allow_y_grid=False,
        )

    def _bind_channel(
        self, axis_handle, name, t, sig, color, unit, data_id,
        *, xlabel=None, skip_envelope=False,
        axis_label=None, axis_color=None, update_axis_style=True,
    ):
        """Attach one channel to ``axis_handle``."""
        pi = axis_handle.plot_item
        if pi is None:
            return
        t_arr = np.asarray(t)
        sig_arr = np.asarray(sig)
        is_monotonic = self._cached_is_monotonic(data_id, name, t_arr)
        ck = _view_state_channel_key(data_id, name)
        profiles = getattr(self, "_channel_render_profiles", None)
        if profiles is None:
            profiles = {}
            self._channel_render_profiles = profiles
        source_revision = source_revision_for(t_arr, sig_arr)
        profile = profiles.get(ck)
        if profile is None or profile.source_revision != source_revision:
            profile = classify_render_profile(
                t_arr, sig_arr, source_revision=source_revision,
            )
            profiles[ck] = profile
        if skip_envelope:
            bind_t = bind_s = np.empty(0, dtype=np.float64)
        else:
            try:
                from mf4_analyzer.ui import pg_canvases as legacy_pg_canvases
                envelope_builder = legacy_pg_canvases.build_envelope
            except Exception:
                from mf4_analyzer.signal.envelope import build_envelope as envelope_builder
            initial_width = self._initial_bind_pixel_width(
                axis_handle, source_len=len(sig_arr)
            )
            initial_width = bucket_width_for(
                profile,
                mode="overlay" if self._overlay_mode else "subplot",
                pixel_width=initial_width,
                interactive=False,
            )
            bind_t, bind_s = envelope_builder(
                t_arr,
                sig_arr,
                xlim=None,
                pixel_width=initial_width,
                is_monotonic=is_monotonic,
            )
        pen = pg.mkPen(color=color, width=self._overlay_default_lw)
        primary_vb = pi.getViewBox() if hasattr(pi, "getViewBox") else None
        target_vb = axis_handle.view_box
        if target_vb is not None and target_vb is not primary_vb:
            pdi = pg.PlotDataItem(bind_t, bind_s, pen=pen, name=name)
            try:
                target_vb.addItem(pdi)
            except Exception:
                pass
            add_line_item = getattr(axis_handle, "add_line_item", None)
            if callable(add_line_item):
                add_line_item(pdi)
        else:
            pdi = pi.plot(bind_t, bind_s, pen=pen, name=name)
        # IDENTITY is the composite (data_id, name) key so two same-named
        # channels from differently-truncated files never overwrite each other
        # (multi-file same-name root fix); the display ``name`` is recorded for
        # iteration / bare-name lookups.
        self.channel_data.set_with_label(ck, name, (t_arr, sig_arr, color, unit))
        self._invalidate_raw_x_bounds(t_arr)
        self._channel_data_id.set_with_label(ck, name, data_id)
        line_handle = _PgLineHandle(pdi, label_fallback=name)
        self._channel_lines.set_with_label(ck, name, (axis_handle, line_handle))
        self._channel_view_state_lines[ck] = (axis_handle, line_handle)
        self._channel_is_monotonic.set_with_label(
            ck, name, is_monotonic
        )

        if update_axis_style:
            try:
                if axis_label is not None:
                    label = axis_label
                elif self._overlay_mode:
                    label = self._overlay_axis_label(axis_handle, name, unit)
                else:
                    label = _subplot_ylabel_text(name, unit)
                axis_handle.set_ylabel(label)
                _apply_pg_axis_font(axis_handle.y_axis_item())
            except Exception:
                pass
            if self._overlay_mode:
                self._configure_overlay_axis_geometry(axis_handle)
            self._apply_pg_axis_style(
                axis_handle, axis_color if axis_color is not None else color
            )
        if xlabel is not None:
            try:
                axis_handle.set_xlabel(xlabel)
                _apply_pg_axis_font(axis_handle.x_axis_item())
            except Exception:
                pass

    def _bind_companion(
        self, source_handle, name, t, sig, color, unit, data_id,
        *, visible=True, dash=True, skip_envelope=False,
    ):
        """Attach a display companion curve onto ``source_handle``'s axis.

        Unlike :meth:`_bind_channel` this does NOT allocate a new axis/row:
        the companion (e.g. a filter overlay) renders on the SAME ViewBox as
        its source channel, sharing that channel's Y axis and label. It is
        drawn with a dashed pen so the original (solid) and the overlay are
        distinguishable while staying in the same color family. The companion
        IS registered in ``channel_data`` / ``_channel_lines`` under its own
        ``name`` so the viewport envelope refresh and grab export treat it
        like any other curve; it is tracked in ``_companion_names`` so the
        stats / emphasis paths can tell it apart from a real channel.
        """
        pi = source_handle.plot_item
        if pi is None:
            return
        t_arr = np.asarray(t)
        sig_arr = np.asarray(sig)
        is_monotonic = self._cached_is_monotonic(data_id, name, t_arr)
        ck = _view_state_channel_key(data_id, name)
        profiles = getattr(self, "_channel_render_profiles", None)
        if profiles is None:
            profiles = {}
            self._channel_render_profiles = profiles
        source_revision = source_revision_for(t_arr, sig_arr)
        profile = profiles.get(ck)
        if profile is None or profile.source_revision != source_revision:
            profile = classify_render_profile(
                t_arr, sig_arr, source_revision=source_revision,
            )
            profiles[ck] = profile
        if skip_envelope:
            bind_t = bind_s = np.empty(0, dtype=np.float64)
        else:
            try:
                from mf4_analyzer.ui import pg_canvases as legacy_pg_canvases
                envelope_builder = legacy_pg_canvases.build_envelope
            except Exception:
                from mf4_analyzer.signal.envelope import build_envelope as envelope_builder
            initial_width = self._initial_bind_pixel_width(
                source_handle, source_len=len(sig_arr)
            )
            initial_width = bucket_width_for(
                profile,
                mode="overlay" if self._overlay_mode else "subplot",
                pixel_width=initial_width,
                interactive=False,
            )
            bind_t, bind_s = envelope_builder(
                t_arr,
                sig_arr,
                xlim=None,
                pixel_width=initial_width,
                is_monotonic=is_monotonic,
            )
        style = Qt.DashLine if dash else Qt.SolidLine
        pen = pg.mkPen(
            color=color, width=self._overlay_default_lw, style=style
        )
        primary_vb = pi.getViewBox() if hasattr(pi, "getViewBox") else None
        target_vb = source_handle.view_box
        if target_vb is not None and target_vb is not primary_vb:
            pdi = pg.PlotDataItem(bind_t, bind_s, pen=pen, name=name)
            try:
                target_vb.addItem(pdi)
            except Exception:
                pass
            add_line_item = getattr(source_handle, "add_line_item", None)
            if callable(add_line_item):
                add_line_item(pdi)
        else:
            pdi = pi.plot(bind_t, bind_s, pen=pen, name=name)
        try:
            pdi.setVisible(bool(visible))
        except Exception:
            pass
        self.channel_data.set_with_label(ck, name, (t_arr, sig_arr, color, unit))
        self._invalidate_raw_x_bounds(t_arr)
        self._channel_data_id.set_with_label(ck, name, data_id)
        line_handle = _PgLineHandle(pdi, label_fallback=name)
        self._channel_lines.set_with_label(ck, name, (source_handle, line_handle))
        self._channel_view_state_lines[ck] = (source_handle, line_handle)
        self._channel_is_monotonic.set_with_label(
            ck, name, is_monotonic
        )
        # Track companions by COMPOSITE key so a same-named companion from a
        # different file is distinguished (matches the channel_data identity).
        self._companion_names.add(ck)

    def _cached_is_monotonic(self, data_id, name, t_arr):
        """Return monotonicity from a cheap cross-rebuild fingerprint cache."""
        try:
            n = int(len(t_arr))
            if n:
                key = (data_id, name, n, float(t_arr[0]), float(t_arr[-1]))
            else:
                key = (data_id, name, 0, 0.0, 0.0)
        except Exception:
            return _is_monotonic_array(t_arr)
        cache = self._monotonic_fingerprint_cache
        cached = cache.get(key)
        if cached is None:
            if len(cache) > 256:
                cache.clear()
            cached = bool(_is_monotonic_array(t_arr))
            cache[key] = cached
        return cached

    def _overlay_axis_label(self, axis_handle, name, unit):
        base = str(name).replace("\n", " ")
        suffix = f" ({unit})" if unit else ""
        max_chars = self._overlay_axis_label_max_chars(axis_handle, base, suffix)
        compact = _middle_ellipsis(base, max_chars=max_chars)
        return f"{compact}{suffix}"

    def _overlay_axis_label_max_chars(self, axis_handle, base, suffix):
        """Return the largest label budget that fits the rotated Y axis."""
        text = str(base)
        if not text:
            return _OVERLAY_AXIS_LABEL_FALLBACK_CHARS

        available = self._overlay_axis_label_available_height(axis_handle)
        if available <= 0:
            return min(len(text), _OVERLAY_AXIS_LABEL_FALLBACK_CHARS)

        metrics = QFontMetrics(_pg_chart_font(9))

        def text_width(value):
            try:
                return float(metrics.horizontalAdvance(value))
            except AttributeError:  # pragma: no cover - older Qt fallback
                return float(metrics.width(value))

        full_label = f"{text}{suffix}"
        if text_width(full_label) <= available:
            return len(text)

        low = min(_OVERLAY_AXIS_LABEL_MIN_CHARS, len(text))
        high = len(text)
        best = low
        while low <= high:
            mid = (low + high) // 2
            candidate = f"{_middle_ellipsis(text, max_chars=mid)}{suffix}"
            if text_width(candidate) <= available:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return max(_OVERLAY_AXIS_LABEL_MIN_CHARS, min(best, len(text)))

    def _overlay_axis_label_available_height(self, axis_handle):
        heights = []
        try:
            axis = axis_handle.y_axis_item()
        except Exception:
            axis = None
        if axis is not None:
            try:
                h = float(axis.size().height())
                if h > 0:
                    heights.append(h)
            except Exception:
                pass
            try:
                h = float(axis.sceneBoundingRect().height())
                if h > 0:
                    heights.append(h)
            except Exception:
                pass
        vb = getattr(axis_handle, "view_box", None)
        if vb is not None:
            try:
                h = float(vb.sceneBoundingRect().height())
                if h > 0:
                    heights.append(h)
            except Exception:
                pass
        try:
            viewport = self._glw.viewport()
            if viewport is not None:
                h = float(viewport.height())
                if h > 0:
                    heights.append(h)
        except Exception:
            pass
        if not heights:
            return 0.0
        return max(0.0, max(heights) - _OVERLAY_AXIS_LABEL_VERTICAL_PADDING_PX)

    def _refresh_overlay_axis_labels(self):
        if not self._overlay_mode or not self._channel_lines:
            return
        # Iterate by composite key so the unit/color row is read from the SAME
        # file's channel_data entry (a bare-name lookup could resolve a
        # same-named channel from another file).
        for ck, name, (handle, _line) in self._channel_lines.composite_items():
            row = self.channel_data.get(ck)
            unit = row[3] if row is not None else ""
            color = row[2] if row is not None else PG_AXIS_NEUTRAL_COLOR
            try:
                handle.set_ylabel(self._overlay_axis_label(handle, name, unit))
                _apply_pg_axis_font(handle.y_axis_item())
                self._configure_overlay_axis_geometry(handle)
                self._apply_pg_axis_style(handle, color)
            except Exception:
                pass

    def _apply_pg_axis_style(self, axis_handle, color):
        """Keep grid/axis lines neutral while tick text follows the channel."""
        try:
            axis = axis_handle.y_axis_item()
        except Exception:
            axis = None
        if axis is None:
            return
        _apply_pg_axis_font(axis)
        try:
            axis.setPen(
                pg.mkPen(color=PG_AXIS_NEUTRAL_COLOR, width=PG_AXIS_NEUTRAL_WIDTH)
            )
        except Exception:
            pass
        try:
            axis.setTextPen(pg.mkPen(color=color))
        except Exception:
            pass

    def _sync_pg_channel_color(self, channel_key, color):
        # ``channel_key`` may be a COMPOSITE (data_id, name) identity key (the
        # precise curve the user recolored) or a bare display name (legacy
        # callers). _ChannelKeyDict resolves both; writing by the composite key
        # lands the color on the EXACT file's channel even when two files share
        # a truncated display name (multi-file same-name collision class).
        row = self.channel_data.get(channel_key)
        if row is not None:
            self.channel_data[channel_key] = (row[0], row[1], color, row[3])
        # Inside-axis labels are matched by DISPLAY name, so resolve the
        # composite key down to its display label for that comparison.
        display_name = self.channel_data.display_label(channel_key, channel_key)
        for handle, item in zip(self._inside_label_handles, self._inside_label_items):
            if self._channel_name_for_handle(handle) != display_name:
                continue
            try:
                item.setColor(pg.mkColor(color))
                item.border = pg.mkPen(color=color, width=0.8)
                item.update()
            except Exception:
                pass
        self.draw_idle()

    def _configure_overlay_axis_geometry(self, axis_handle):
        """Overlay-only axis geometry so the rotated label clears the ticks."""
        try:
            axis = axis_handle.y_axis_item()
        except Exception:
            axis = None
        if axis is None:
            return
        try:
            axis.enableAutoSIPrefix(False)
        except Exception:
            pass
        try:
            axis.setWidth(None)
        except Exception:
            pass

    def _initial_bind_pixel_width(self, axis_handle=None, *, source_len=None) -> int:
        """Return a first-frame envelope width close to the visible plot width.

        When the subplot dense-stack cap is active (>= 2 high-density rows,
        recorded on the canvas as ``_subplot_dense_count`` by ``plot_channels``)
        and ``source_len`` marks THIS channel as dense, the returned width is
        capped via the renderer's subplot dense rule so the first painted frame
        already holds the reduced bucket count — re-showing the hidden
        originals then repaints capped walls, not full-resolution ones.
        """
        widths = []
        if axis_handle is not None:
            vb = getattr(axis_handle, "view_box", None)
            if vb is not None:
                try:
                    w = int(vb.sceneBoundingRect().width())
                    if w > 1:
                        widths.append(w)
                except Exception:
                    pass
        try:
            viewport = self._glw.viewport()
            if viewport is not None:
                w = int(viewport.width())
                if w > 1:
                    widths.append(w)
        except Exception:
            pass
        if not widths:
            pw = self.MAX_PTS
        else:
            pw = max(1, min(self.MAX_PTS, max(widths)))
        dense_count = getattr(self._c, "_subplot_dense_count", 0)
        if source_len is not None and dense_count and dense_count >= 2:
            try:
                pw = self._renderer._subplot_effective_width(
                    pw, source_len, dense_count
                )
            except Exception:
                pass
        return pw

    def _configure_subplot_bottom_axis(self, axis_handle, *, is_bottom):
        pi = axis_handle.plot_item
        if pi is None:
            return
        try:
            bottom = pi.getAxis("bottom")
        except Exception:
            bottom = None
        if bottom is None:
            return
        try:
            bottom.setStyle(showValues=bool(is_bottom))
            _apply_pg_axis_font(bottom)
        except Exception:
            pass
        if not is_bottom:
            try:
                bottom.setLabel(text="")
                _apply_pg_axis_font(bottom)
            except Exception:
                pass

    def _build_overlay_y_grid(self):
        """Lock X-master ViewBox to Y=[0,1] and add shared grid lines."""
        if self._x_master_handle is None:
            return
        vb = getattr(self._x_master_handle, "view_box", None)
        if vb is None:
            return
        try:
            vb.enableAutoRange(axis="y", enable=False)
            vb.setYRange(0.0, 1.0, padding=0)
            vb.setMouseEnabled(x=True, y=False)
        except Exception:
            pass

        for line in list(self._overlay_grid_lines):
            try:
                vb.removeItem(line)
            except Exception:
                pass
        self._overlay_grid_lines = []

        n = self._current_overlay_divisions()
        alpha_int = max(1, min(255, int(round(_OVERLAY_GRID_ALPHA * 255))))
        pen = pg.mkPen(color=(180, 180, 180, alpha_int), width=1)
        lines = []
        for i in range(1, n):
            line = pg.InfiniteLine(
                pos=i / n,
                angle=0,
                movable=False,
                pen=pen,
            )
            try:
                vb.addItem(line)
                lines.append(line)
            except Exception:
                pass
        self._overlay_grid_lines = lines

    def _repin_overlay_channel_ticks(self):
        """Frame overlay channels and pin their ticks to the shared graticule."""
        if not getattr(self, "_overlay_mode", False):
            return
        n = self._current_overlay_divisions()
        for handle in list(self.axes_list):
            try:
                lo, hi = handle.get_ylim()
            except Exception:
                continue
            bottom, top, ticks = _frame_to_nice(lo, hi, n)
            try:
                handle.set_ylim(bottom, top)
            except Exception:
                continue
            axis = handle.y_axis_item() if hasattr(handle, "y_axis_item") else None
            if axis is None:
                continue
            try:
                axis.setStyle(maxTickLevel=0)
            except Exception:
                pass
            try:
                axis.setTicks([[(value, _fmt_tick(value)) for value in ticks], []])
            except Exception:
                pass

    def _snap_overlay_channel_to_grid(self, ax):
        """Snap a dragged overlay channel to its current graticule span."""
        if ax is None:
            return
        try:
            lo, hi = ax.get_ylim()
        except Exception:
            return
        span = hi - lo
        if not (math.isfinite(span) and span > 0):
            return
        n = self._current_overlay_divisions()
        per_div = span / n
        if not (math.isfinite(per_div) and per_div > 0):
            return
        bottom = round(lo / per_div) * per_div
        if abs(bottom) < per_div * 1e-10:
            bottom = 0.0
        top = bottom + span
        ticks = [bottom + k * per_div for k in range(n + 1)]
        try:
            ax.set_ylim(bottom, top)
            axis = ax.y_axis_item() if hasattr(ax, "y_axis_item") else None
            if axis is not None:
                axis.setStyle(maxTickLevel=0)
                axis.setTicks([[(value, _fmt_tick(value)) for value in ticks], []])
        except Exception:
            pass

    def _stop_snap_anim(self):
        """Stop any in-flight drag-release snap animation."""
        anim = getattr(self, "_snap_anim", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
            self._snap_anim = None

    def _animate_overlay_snap(self, ax):
        """Glide ``ax`` from its dragged position to the nice graticule."""
        if ax is None:
            return
        self._stop_snap_anim()
        try:
            lo, hi = ax.get_ylim()
        except Exception:
            return
        span = hi - lo
        if not (math.isfinite(span) and span > 0):
            return
        n = self._current_overlay_divisions()
        per_div = span / n
        if not (math.isfinite(per_div) and per_div > 0):
            return
        bottom = round(lo / per_div) * per_div
        if abs(bottom) < per_div * 1e-10:
            bottom = 0.0
        top = bottom + span
        duration = int(getattr(self, "_snap_anim_ms", 150))
        if duration <= 0 or abs(bottom - lo) < per_div * 1e-6:
            self._snap_overlay_channel_to_grid(ax)
            return

        ticks = [bottom + k * per_div for k in range(n + 1)]
        try:
            axis = ax.y_axis_item() if hasattr(ax, "y_axis_item") else None
            if axis is not None:
                axis.setStyle(maxTickLevel=0)
                axis.setTicks([[(value, _fmt_tick(value)) for value in ticks], []])
        except Exception:
            pass

        start_lo, start_hi = lo, hi
        anim = QVariantAnimation(self._c)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def _on_value(frac):
            try:
                f = float(frac)
            except Exception:
                return
            cur_lo = start_lo + (bottom - start_lo) * f
            cur_hi = start_hi + (top - start_hi) * f
            try:
                ax.set_ylim(cur_lo, cur_hi)
            except Exception:
                return
            self._refresh = True
            self.draw_idle()

        def _on_finished():
            self._snap_overlay_channel_to_grid(ax)
            self._snap_anim = None
            self._refresh = True
            self.draw_idle()

        anim.valueChanged.connect(_on_value)
        anim.finished.connect(_on_finished)
        self._snap_anim = anim
        anim.start()

    def _apply_overlay_box_zoom_y(self):
        """Restore fixed grid Y and redirect RectMode Y span to EVERY channel.

        Each channel maps the same on-screen box fraction ``[f0, f1]`` onto its
        own data ylim, so a rubber-band box zooms all overlaid series together
        (units differ per channel; only the screen fraction is shared). No
        pre-selection needed."""
        if not getattr(self, "_overlay_mode", False):
            return
        master = self._x_master_handle
        if master is None:
            return
        vb = getattr(master, "view_box", None)
        if vb is None:
            return
        try:
            y0, y1 = vb.viewRange()[1]
        except Exception:
            return
        already_locked = abs(y0 - 0.0) < 1e-9 and abs(y1 - 1.0) < 1e-9
        if not already_locked:
            try:
                vb.enableAutoRange(axis="y", enable=False)
                vb.setYRange(0.0, 1.0, padding=0)
            except Exception:
                pass
        if already_locked:
            # Box never pulled the graticule Y off [0, 1] → no Y span to map.
            self._refresh = True
            self.draw_idle()
            return
        f0 = max(0.0, min(1.0, min(y0, y1)))
        f1 = max(0.0, min(1.0, max(y0, y1)))
        if f1 - f0 < 1e-6:
            # Box too short in Y → X-only zoom; leave every channel's Y as-is.
            self._refresh = True
            self.draw_idle()
            return
        n = self._current_overlay_divisions()
        for handle in (self.axes_list or []):
            if handle is None:
                continue
            try:
                clo, chi = handle.get_ylim()
            except Exception:
                continue
            cspan = chi - clo
            if not (math.isfinite(cspan) and cspan > 0):
                continue
            new_lo = clo + f0 * cspan
            new_hi = clo + f1 * cspan
            bottom, top, ticks = _frame_to_nice(new_lo, new_hi, n)
            try:
                handle.set_ylim(bottom, top)
                axis = (
                    handle.y_axis_item() if hasattr(handle, "y_axis_item") else None
                )
                if axis is not None:
                    axis.setStyle(maxTickLevel=0)
                    axis.setTicks([[(value, _fmt_tick(value)) for value in ticks], []])
            except Exception:
                continue
        self._refresh = True
        self.draw_idle()

    def _teardown_overlay_aux_viewboxes(self):
        """Remove every overlay aux ViewBox and appended axis from the scene."""
        for aux_vb in list(self._overlay_aux_viewboxes):
            try:
                scene = aux_vb.scene()
                if scene is not None:
                    scene.removeItem(aux_vb)
            except Exception:
                pass
        for ax_item in list(self._overlay_aux_axes):
            primary = self._primary_xaxis_ax
            try:
                if primary is not None and primary.plot_item is not None:
                    primary.plot_item.layout.removeItem(ax_item)
            except Exception:
                pass
            try:
                scene = ax_item.scene()
                if scene is not None:
                    scene.removeItem(ax_item)
            except Exception:
                pass

    def _overlay_axis_handle_at_scene_pos(self, scene_pos):
        """Return the overlay channel whose Y-axis gutter contains scene_pos."""
        if scene_pos is None:
            return None
        handles = list(self.axes_list)
        selected = self._selected_overlay_axes()
        if selected is not None:
            handles = [selected] + [h for h in handles if h is not selected]
        for handle in handles:
            axis = handle.y_axis_item() if hasattr(handle, "y_axis_item") else None
            if axis is None:
                continue
            try:
                rect = axis.sceneBoundingRect()
                if rect.contains(scene_pos):
                    return handle
            except Exception:
                continue
        return None

    def _set_x_master_mouse_enabled(self, enabled):
        """Toggle the X-master ViewBox's mouse interaction."""
        master = self._x_master_handle
        if master is None:
            return
        vb = master.view_box
        if vb is None:
            return
        try:
            vb.setMouseEnabled(x=bool(enabled), y=False)
        except Exception:
            pass

    def _press_view_box_in_rect_mode(self, scene_pos):
        """Return True when the ViewBox under ``scene_pos`` is in RectMode."""
        vb = None
        handle = self._axis_handle_at_scene_pos(scene_pos)
        if handle is not None:
            vb = handle.view_box
        if vb is None and self._primary_xaxis_ax is not None:
            vb = self._primary_xaxis_ax.view_box
        if vb is None:
            return False
        try:
            return vb.state.get("mouseMode") == pg.ViewBox.RectMode
        except Exception:
            return False

    def _handle_overlay_mouse_press(self, event):
        """Overlay-mode left-press is a no-op: a plain drag always falls
        through to the ViewBox (X-master pan / RectMode box-zoom).

        The former Alt(Option)+press「选中曲线 + 单条 Y 拖动」手势被移除
        (2026-07-09)：单条 Y 控制改由「滚轮停在该曲线自己的 Y 轴上」承担
        (平移 / Shift 缩放)，编辑颜色/坐标改由「双击该曲线或其 Y 轴」触发
        (见 canvas._handle_viewport_double_click)。返回 False 让 pyqtgraph
        处理，Pan 工具按钮保持不变。"""
        return False

    def _handle_overlay_mouse_move(self, event):
        """Apply a Y-drag while the left button is held in overlay mode."""
        if not self._overlay_dragging:
            return False
        try:
            if not (event.buttons() & Qt.LeftButton):
                return False
            viewport_pos = event.pos()
        except Exception:
            return False
        cur_y = self._scene_y_from_viewport_pos(viewport_pos)
        if cur_y is None:
            return False
        self._apply_overlay_y_drag_at(current_y_px=cur_y)
        return True

    def _handle_overlay_mouse_release(self, event):
        """End a live overlay Y-drag and re-enable the X-master pan."""
        if not self._overlay_dragging:
            return False
        self._overlay_dragging = False
        self._overlay_y_drag_start = None
        self._set_x_master_mouse_enabled(True)
        selected_ax = self._selected_overlay_axes()
        self._animate_overlay_snap(selected_ax)
        self.schedule_idle_quality()
        return True

    def _sync_overlay_aux_viewboxes(self):
        if not self._overlay_aux_viewboxes or self._primary_xaxis_ax is None:
            return
        primary_vb = self._primary_xaxis_ax.view_box
        if primary_vb is None:
            return
        try:
            rect = primary_vb.sceneBoundingRect()
        except Exception:
            return
        for aux_vb in list(self._overlay_aux_viewboxes):
            try:
                aux_vb.setGeometry(rect)
            except Exception:
                continue
            try:
                xlo, xhi = self._primary_xaxis_ax.get_xlim()
                aux_vb.setXRange(float(xlo), float(xhi), padding=0)
            except Exception:
                pass

    def _connect_overlay_view_sync(self):
        self._disconnect_overlay_view_sync()
        if self._primary_xaxis_ax is None or not self._overlay_aux_viewboxes:
            return
        primary_vb = self._primary_xaxis_ax.view_box
        if primary_vb is None or not hasattr(primary_vb, "sigResized"):
            return

        def _handler(*_args):
            self._sync_overlay_aux_viewboxes()

        try:
            primary_vb.sigResized.connect(_handler)
            self._overlay_view_sync_conns.append((primary_vb, _handler))
        except Exception:
            pass

    def _disconnect_overlay_view_sync(self):
        for vb, handler in self._overlay_view_sync_conns:
            try:
                vb.sigResized.disconnect(handler)
            except Exception:
                pass
        self._overlay_view_sync_conns = []

    def select_overlay_channel(self, name, *, notify=True):
        """Select an overlay channel: emphasise it (bold + others dimmed).

        ``notify=True`` also emits ``overlay_channel_selected`` (the nav/toolbar
        handoff). The double-click-to-edit highlight passes ``notify=False`` so
        merely opening a curve's 图表选项 does not toggle the pan/zoom tool."""
        if name is not None and name not in self._channel_lines:
            return
        if self._selected_overlay_channel == name:
            return
        self._selected_overlay_channel = name
        self._apply_overlay_emphasis()
        if notify:
            self.overlay_channel_selected.emit(name)
        self.draw_idle()

    def _overlay_emphasis_for_channel(self, name):
        """Return ``(line_width, alpha)`` currently displayed for ``name``."""
        pair = self._channel_lines.get(name)
        if pair is None:
            return (None, None)
        _axis_facade, line_facade = pair
        pdi = line_facade.plot_data_item
        opts = getattr(pdi, "opts", {}) or {}
        pen = opts.get("pen")
        width = 1.0
        alpha = 1.0
        try:
            from PyQt5.QtGui import QPen
            if isinstance(pen, QPen):
                width = float(pen.widthF() or 1.0)
        except Exception:
            pass
        try:
            opacity = pdi.opacity()
            if opacity is not None:
                alpha = float(opacity)
        except Exception:
            pass
        return (width, alpha)

    def _apply_overlay_emphasis(self):
        """Apply line width and alpha for current overlay selection."""
        selected = self._selected_overlay_channel
        for name, (_axis_facade, line_facade) in self._channel_lines.items():
            pdi = line_facade.plot_data_item
            if not self._overlay_mode or selected is None:
                self._apply_pdi_emphasis(
                    pdi,
                    width=self._overlay_default_lw,
                    alpha=self._overlay_default_alpha,
                )
                continue
            if name == selected:
                self._apply_pdi_emphasis(
                    pdi,
                    width=self._overlay_selected_lw,
                    alpha=self._overlay_selected_alpha,
                )
            else:
                self._apply_pdi_emphasis(
                    pdi,
                    width=self._overlay_de_emphasised_lw,
                    alpha=self._overlay_de_emphasised_alpha,
                )

    def _apply_pdi_emphasis(self, pdi, *, width, alpha):
        """Set line width and alpha on a single PlotDataItem."""
        try:
            opts = getattr(pdi, "opts", {}) or {}
            pen = opts.get("pen")
            color = None
            # Preserve the existing pen STYLE (e.g. companion overlays use a
            # dashed pen): rebuilding it color+width only would silently reset
            # a dashed curve back to solid on every emphasis re-apply.
            style = None
            try:
                from PyQt5.QtGui import QPen
                if isinstance(pen, QPen):
                    color = pen.color()
                    style = pen.style()
            except Exception:
                color = None
            if color is None:
                try:
                    color = pg.mkColor(pen)
                except Exception:
                    color = None
            kwargs = {"width": float(width)}
            if color is not None:
                kwargs["color"] = color
            if style is not None:
                kwargs["style"] = style
            pdi.setPen(pg.mkPen(**kwargs))
        except Exception:
            pass
        try:
            pdi.setOpacity(float(alpha))
        except Exception:
            pass

    def _begin_overlay_y_drag_at(self, *, start_y_px):
        """Capture the (pixel, ylim) pair for selected-channel Y drag."""
        ax = self._selected_overlay_axes()
        if ax is None:
            self._overlay_y_drag_start = None
            return
        try:
            lo, hi = ax.get_ylim()
        except Exception:
            self._overlay_y_drag_start = None
            return
        self._overlay_y_drag_start = (float(start_y_px), (float(lo), float(hi)))

    def _apply_overlay_y_drag_at(self, *, current_y_px):
        """Apply the pan implied by a Y drag from start to ``current_y_px``."""
        if self._overlay_y_drag_start is None:
            return False
        ax = self._selected_overlay_axes()
        if ax is None:
            self._overlay_y_drag_start = None
            return False
        start_y, (lo, hi) = self._overlay_y_drag_start
        vb = ax.view_box
        height = 1.0
        if vb is not None:
            try:
                rect = vb.sceneBoundingRect()
                height = max(float(rect.height()), 1.0)
            except Exception:
                height = 1.0
        dy_px = float(current_y_px) - float(start_y)
        shift = -dy_px * (hi - lo) / height
        try:
            ax.set_ylim(lo + shift, hi + shift)
        except Exception:
            return False
        self.visible_range_changed.emit()
        self._refresh = True
        self.draw_idle()
        return True

    def _selected_overlay_axes(self):
        """Return the axis facade associated with the selected channel."""
        if self._selected_overlay_channel is None:
            return None
        pair = self._channel_lines.get(self._selected_overlay_channel)
        if pair is None:
            return None
        axis_handle, _line_handle = pair
        return axis_handle

    def _overlay_cursor_y_fraction(self, scene_pos, view_box):
        """Cursor Y as a fraction of the overlay plot rect (0 = bottom,
        1 = top), used to anchor an all-channel Y zoom at the point under the
        cursor (matching the X-master zoom anchor). Falls back to 0.5 (center)
        when the position/geometry is unavailable. All overlay aux ViewBoxes
        share the X-master's scene rect, so any of them gives the same rect."""
        try:
            vb = view_box
            if vb is None and self._x_master_handle is not None:
                vb = self._x_master_handle.view_box
            rect = vb.sceneBoundingRect()
            h = float(rect.height())
            if h <= 0 or scene_pos is None:
                return 0.5
            frac = (float(rect.bottom()) - float(scene_pos.y())) / h
            if not math.isfinite(frac):
                return 0.5
            return max(0.0, min(1.0, frac))
        except Exception:
            return 0.5

    def _handle_wheel_dispatch(self, *, delta, modifiers, x_pos, y_pos,
                               view_box=None, scene_pos=None, axis=None):
        """Central wheel dispatch routed from ``_ModifierWheelViewBox``.

        ``axis`` is set by pyqtgraph's ``AxisItem.wheelEvent`` when the wheel is
        over a Y-axis GUTTER (``axis == 1``) rather than the plot area; in
        overlay mode that scopes the zoom/pan to that ONE channel's axis."""
        step = 1 if delta > 0 else -1 if delta < 0 else 0
        if step == 0:
            return False
        factor = 0.85 if step > 0 else 1.0 / 0.85

        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        self.disable_interactive_quality()

        if getattr(self, "_overlay_mode", False) and not ctrl:
            # Wheel over ONE channel's Y-axis gutter (axis == 1) → scroll/zoom
            # only THAT channel (its own axis is the natural per-channel
            # control). Wheel over the plot AREA (axis is None) → act on EVERY
            # channel together, like the shared X (Ctrl+wheel), so no
            # pre-selection is needed. Each channel keeps its own range but
            # scales by the SAME factor, anchored at the cursor's fractional
            # viewport-Y. axes_list holds exactly the per-channel Y axes (the
            # curveless X-master is not in it).
            single = (
                self._axis_handle_for_view_box(view_box)
                if axis == 1 else None
            )
            if single is not None:
                handles = [single]
            else:
                handles = [h for h in (self.axes_list or []) if h is not None]
            if not handles:
                self.schedule_idle_quality()
                return True
            n = self._current_overlay_divisions()
            frac = self._overlay_cursor_y_fraction(scene_pos, view_box)
            changed = False
            for target in handles:
                try:
                    lo, hi = target.get_ylim()
                except Exception:
                    continue
                span = hi - lo
                if not (math.isfinite(span) and span > 0):
                    continue
                if shift:
                    # Step the per-division to the ADJACENT nice value (not a
                    # raw factor) so _frame_to_nice can't snap the result back
                    # to the original span — a guaranteed visible zoom step,
                    # applied identically to every channel.
                    current_per_div = span / n
                    next_per_div = _adjacent_nice_step(
                        current_per_div, -1 if step > 0 else 1
                    )
                    if next_per_div is None:
                        next_per_div = current_per_div * factor
                    anchor = lo + frac * span
                    framed_span = max(next_per_div, (n - 1) * next_per_div)
                    new_lo = anchor - frac * framed_span
                    new_hi = anchor + (1.0 - frac) * framed_span
                    bottom, top, ticks = _frame_to_nice(new_lo, new_hi, n)
                else:
                    # Plain-wheel vertical pan. Sign is NEGATED vs ``step`` so
                    # wheel-up moves the view toward LOWER Y (content scrolls
                    # up on screen) — the Windows-traditional wheel feel users
                    # asked for. The earlier ``+ step`` matched macOS
                    # natural-scroll and felt inverted on a Windows mouse.
                    per_div = span / n
                    bottom = lo - step * per_div
                    top = hi - step * per_div
                    ticks = [bottom + k * per_div for k in range(n + 1)]
                try:
                    target.set_ylim(bottom, top)
                    axis = (
                        target.y_axis_item()
                        if hasattr(target, "y_axis_item")
                        else None
                    )
                    if axis is not None:
                        axis.setStyle(maxTickLevel=0)
                        axis.setTicks(
                            [[(value, _fmt_tick(value)) for value in ticks], []]
                        )
                    changed = True
                except Exception:
                    continue
            if changed:
                self.visible_range_changed.emit()
                self._refresh = True
                self.draw_idle()
            self.schedule_idle_quality()
            return True

        target = self._axis_handle_for_view_box(view_box) or self._primary_xaxis_ax
        if target is None:
            return False

        try:
            if ctrl:
                lo, hi = target.get_xlim()
                c = float(x_pos) if np.isfinite(x_pos) else (lo + hi) / 2.0
                new_lo = c - (c - lo) * factor
                new_hi = c + (hi - c) * factor
                target.set_xlim(new_lo, new_hi)
            elif shift:
                lo, hi = target.get_ylim()
                c = float(y_pos) if np.isfinite(y_pos) else (lo + hi) / 2.0
                new_lo = c - (c - lo) * factor
                new_hi = c + (hi - c) * factor
                target.set_ylim(new_lo, new_hi)
            else:
                # Plain-wheel vertical pan — direction negated to match the
                # Windows-traditional wheel feel (see the overlay branch above).
                lo, hi = target.get_ylim()
                d = (hi - lo) * 0.1 * step
                target.set_ylim(lo - d, hi - d)
        except Exception:
            return False

        self.visible_range_changed.emit()
        self._refresh = True
        self.draw_idle()
        self.schedule_idle_quality()
        return True


__all__ = ["OverlayAxisManager"]
