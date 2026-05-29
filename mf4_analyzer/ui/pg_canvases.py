"""Pyqtgraph-backed TimeDomain canvas (Task 5 of the migration plan).

Implements design §5.1, §5.2, §5.4, §5.5 of
``docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md``.

``TimeDomainCanvasPG`` is the production time-domain renderer
(``ChartStack`` constructs it as ``canvas_time``). Its compatibility
surface mirrors ``mf4_analyzer.ui.canvases.TimeDomainCanvas`` so callers
see the same signals, attributes, and methods regardless of backend.

Architecture
------------
The canvas is a ``QWidget`` (not a direct ``pg.GraphicsLayoutWidget``
subclass) so it can carry pyqtSignals AND expose ``grab_pixmap()`` /
``grab()`` without battling Qt's metaclass rules. Internally it owns a
single ``pg.GraphicsLayoutWidget`` and one ``pg.PlotItem`` per subplot. The
production performance path follows the current visible-render pipeline:

    set_xlim → positions_envelope → visible PlotDataItem.setData

The older custom ``QPainterPath``/``QPixmap`` helpers remain only for
standalone geometry parity tests. They are not run from the pan refresh
hot path because no visible painter consumes their output.

Lessons honored
---------------
- ``pyqt-ui/2026-04-25-cache-invalidation-event-conditional``: the
  curve-layer cache compares a ``_last_range_key`` per channel against
  the incoming key; repeated flushes with the same xlim do NOT inflate
  the cache.
- ``pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before``:
  ``_flush_pending_refresh`` drains AFTER the mutation. The
  ``sigXRangeChanged`` callback re-schedules the QTimer; ``set_xlim``
  → flush ordering is preserved by routing both through the same
  ``_refresh_visible_data`` method.
- ``signal-processing/2026-04-25-envelope-cache-bucket-width-quantization``:
  the range key is ``(channel, bucketed_lo, bucketed_hi,
  bucketed_pixel_width)`` where the quantum is ``span / pixel_width``
  (one pixel), matching ``TimeDomainCanvas._envelope_cached``.
- ``signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface``:
  ``positions_envelope`` is called from ``_refresh_visible_data`` on the
  hot path, NOT just a helper.
- ``pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt``: ``grab_pixmap``
  falls back to ``QWidget.grab()`` and finally to a degenerate-rect
  null-safe pixmap.
- Design Risk Register R7: ``os.environ.setdefault('PYQTGRAPH_QT_LIB',
  'PyQt5')`` runs BEFORE ``import pyqtgraph`` so the Qt-binding probe
  cannot drift to PySide.
"""
from __future__ import annotations

# R7: pin the Qt binding before pyqtgraph runs its own probe. Setdefault
# (not setitem) so the user can override this from the environment when
# debugging.
import os as _os
_os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")

import logging
from collections import OrderedDict
from typing import Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from mf4_analyzer.signal._envelope_cutils import positions_envelope
from mf4_analyzer.ui._axis_handle import PgAxisHandle, _PgLineHandle
from mf4_analyzer.ui.canvases import (
    _format_dual_html,
    _interp_cursor_value,
    _is_monotonic_array,
    _compact_axis_label,
    _split_prefixed_label,
    build_envelope,
)


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ViewBox subclass with modifier-aware wheel dispatch (T6 requirement 4).
#
# Pyqtgraph 0.14 ViewBox.wheelEvent ignores keyboard modifiers (verified by
# grepping .venv/lib/python3.12/site-packages/pyqtgraph/graphicsItems/
# ViewBox/ViewBox.py:1297-1316 — no `modifiers()` reference). We subclass
# so we can dispatch on Ctrl/Shift/no-modifier without monkey-patching the
# base class.
# ---------------------------------------------------------------------------


class _ModifierWheelViewBox(pg.ViewBox):
    """ViewBox that consults Qt keyboard modifiers on wheel events.

    Behavior matches canvases.py:_on_scroll exactly:

    - Ctrl + wheel  → zoom X (preserve Y)
    - Shift + wheel → zoom Y (preserve X)
    - plain wheel   → pan Y  (preserve X span)
    """

    def __init__(self, *args, owner_canvas=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Weak-ref-style backref to the canvas; the canvas does NOT store
        # the ViewBox so this stays well-defined.
        self._owner_canvas = owner_canvas

    def wheelEvent(self, ev, axis=None):
        # Route through the canvas's central dispatch so the test surface
        # (_handle_wheel_dispatch) and the live UI share one code path.
        owner = self._owner_canvas
        if owner is None:
            super().wheelEvent(ev, axis=axis)
            return
        try:
            delta = float(ev.delta())
            modifiers = ev.modifiers()
            scene_pos = ev.scenePos()
            data_pos = self.mapSceneToView(scene_pos)
            x_pos = float(data_pos.x())
            y_pos = float(data_pos.y())
        except Exception:
            super().wheelEvent(ev, axis=axis)
            return
        consumed = owner._handle_wheel_dispatch(
            delta=delta, modifiers=modifiers, x_pos=x_pos, y_pos=y_pos,
            view_box=self,
        )
        if consumed:
            ev.accept()
        else:
            super().wheelEvent(ev, axis=axis)


# ---------------------------------------------------------------------------
# Curve-layer cache key quantization (signal-processing/
# 2026-04-25-envelope-cache-bucket-width-quantization).
# ---------------------------------------------------------------------------


def _quantize_range_key(
    channel: str,
    xlim: Tuple[float, float],
    pixel_width: int,
) -> Tuple[str, int, int, int]:
    """Return the bucket-quantized cache key for one curve frame.

    The quantum is ``span / pixel_width`` so two xlims that differ by
    less than one pixel collapse to the same key — the envelope output
    is literally identical for those frames.
    """
    if pixel_width is None or pixel_width < 1:
        pixel_width = 1
    x0, x1 = float(xlim[0]), float(xlim[1])
    if x1 < x0:
        x0, x1 = x1, x0
    span = x1 - x0
    quantum = (span / pixel_width) if span > 0 else 1.0
    if quantum <= 0:
        quantum = 1.0
    qx0 = int(round(x0 / quantum))
    qx1 = int(round(x1 / quantum))
    return (channel, qx0, qx1, int(pixel_width))


# ---------------------------------------------------------------------------
# TimeDomainCanvasPG
# ---------------------------------------------------------------------------


class TimeDomainCanvasPG(QWidget):
    """Pyqtgraph-backed drop-in for ``canvases.TimeDomainCanvas``."""

    # Signal contract (design §3.1 — frozen by W0 contract test).
    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)
    span_selected = pyqtSignal(float, float)
    overlay_channel_selected = pyqtSignal(object)

    # Mirror TimeDomainCanvas constants so callers see the same surface.
    MAX_PTS = 8000

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- inner widget tree ------------------------------------------
        # GraphicsLayoutWidget is the host for one or more PlotItem rows.
        # We keep it as a child rather than subclassing so this widget
        # itself can carry pyqtSignals without metaclass conflicts.
        self._glw = pg.GraphicsLayoutWidget(self)
        # Quiet background to match the matplotlib CHART_FACE; the actual
        # chart surface stays white.
        self._glw.setBackground("#ffffff")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._glw)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self._glw.setMouseTracking(True)

        # --- public state (design §5.5 compat seams) --------------------
        # axes_list is a list of PgAxisHandle (one per visible channel
        # in subplot mode, one shared in single/overlay mode).
        self.axes_list = []
        # _channel_lines is {name: (axis_facade, line_facade)} parity
        # with TimeDomainCanvas — used by ChartOptionsDialog and color sync.
        self._channel_lines = {}
        # channel_data is the raw post-range-filter dict — STAYS RAW.
        # get_statistics reads this; the envelope cache never feeds it.
        self.channel_data = {}
        # Parallel data_id dict (kept separate per design §4.2).
        self._channel_data_id = {}
        # Per-channel monotonicity cache, populated once per
        # plot_channels build. Used in _refresh_visible_data so the hot
        # path skips np.diff(t).
        self._channel_is_monotonic = {}
        # The "primary" axis facade — its sigXRangeChanged drives the
        # viewport-aware envelope refresh. Set after plot_channels.
        self._primary_xaxis_ax = None

        # --- cursor / dual-cursor state (matches TimeDomainCanvas) -----
        self._cursor_visible = False
        self._dual = False
        self._ax = None  # cursor A x-position
        self._bx = None  # cursor B x-position
        self._placing = "A"
        self._refresh = True
        self._last_t = 0

        # --- viewport refresh wiring ------------------------------------
        # 40 ms ≈ 25 FPS coalesce window, matching TimeDomainCanvas.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self._refresh_visible_data)
        self._refresh_pending = False
        # The sigXRangeChanged connections so we can drop them on
        # rebuild (pyqtgraph analogue of the matplotlib callbacks
        # lifecycle lesson). We connect on EVERY subplot ViewBox (not
        # just the primary) because pyqtgraph's setXLink is intentionally
        # NOT used — any user-driven xlim mutation can originate from
        # any subplot, so we must propagate from source -> siblings
        # explicitly. List of (view_box, partial_handler) pairs.
        self._xrange_conns: list = []

        # --- curve-layer pixmap cache (design §5.2) ---------------------
        # Keyed by (channel_name, bucketed_lo, bucketed_hi, bucketed_pixel_width).
        # Value: ("painter_path", QPainterPath, QPixmap). Production
        # rendering blits the cached pixmap; cursor/span/overlay overlays
        # draw AFTER blit. PlotDataItem.setData remains the fallback path
        # for the initial bind only — pan/refresh goes through this cache.
        self._curve_path_cache: "OrderedDict[Tuple[str, int, int, int], Tuple]" = (
            OrderedDict()
        )
        self._curve_path_cache_capacity = 64
        # Per-channel "last range key" so a re-flush with no xlim change
        # is a no-op (pyqt-ui/2026-04-25-cache-invalidation-event-conditional).
        self._last_range_key: dict = {}

        # --- compatibility seams expected by main_window / chart_stack --
        # span_selector kept as None so existing main_window code
        # (`canvas.span_selector = ...`) does not AttributeError.
        self.span_selector = None
        self._span_callback = None

        # --- chart-options dialog wiring (parity with matplotlib path) --
        # Remembered axis for the toolbar 图表选项 button when no subplot
        # is under the cursor (mirrors canvases.py:_open_chart_options_for_axes
        # `_chart_options_ax`). Double-click resolves the subplot under the
        # cursor; the toolbar button falls back to this / the primary axis.
        self._chart_options_ax = None
        # Re-entry guard for the double-click → modal dialog path. A fast
        # double-click on a popover/modal could otherwise open it twice
        # (pyqt-ui/2026-04-26-popover-accept-deactivate-race). Flipped True
        # for the duration of the dialog's exec_ and cleared in finally.
        self._chart_options_opening = False
        # Double-click dispatch: a double-click over a subplot opens the
        # chart-options dialog for THAT subplot's axis (parity with
        # canvases.py:1370 `button == 1 and dblclick`). We use a QWidget
        # event filter on the GraphicsLayoutWidget's viewport rather than
        # the GraphicsScene's `sigMouseClicked` because the scene's click
        # pipeline (sendClickEvent → mouseReleaseEvent) does not deliver
        # under ``QT_QPA_PLATFORM=offscreen`` via ``QTest.mouseDClick``,
        # whereas plain QWidget ``QEvent.MouseButtonDblClick`` delivery
        # does. The filter maps the viewport pixel to a scene position so
        # the subplot hit-test stays accurate.
        try:
            viewport = self._glw.viewport()
            if viewport is not None:
                viewport.setMouseTracking(True)
                viewport.installEventFilter(self)
        except Exception:
            pass

        # --- T6: overlay-mode selection + per-channel emphasis ----------
        # Mirrors canvases.py:_apply_overlay_selection_style (lw 1.0 / 1.8;
        # alpha 0.42 / 1.0). Stored per channel so test/UI can probe.
        self._overlay_mode = False
        self._selected_overlay_channel = None
        # Per-channel default emphasis: (line_width, alpha). Default
        # state mirrors matplotlib's "no selection" line: lw=1.05,
        # alpha=None (treated as 1.0). De-emphasised state is
        # (1.0, 0.42); selected is (1.8, 1.0).
        self._overlay_default_lw = 1.7
        self._overlay_default_alpha = 1.0
        self._overlay_selected_lw = 2.6
        self._overlay_selected_alpha = 1.0
        self._overlay_de_emphasised_lw = 1.35
        self._overlay_de_emphasised_alpha = 0.42

        # Pixel pick radius for overlay nearest-curve hit-test. Mirrors
        # canvases.py:_overlay_pick_radius_px = 12.0 (the matplotlib
        # reference). Used by _select_overlay_channel_from_scene_pos.
        self._overlay_pick_radius_px = 12.0

        # Selected-channel Y-drag bookkeeping: (start_y_px, (lo, hi)).
        # _begin_overlay_y_drag_at captures, _apply_overlay_y_drag_at
        # consumes. ChartStack/MainWindow wire mouse events to these.
        self._overlay_y_drag_start = None
        # True for the duration of a live mouse-driven Y-drag so the
        # eventFilter knows MouseMove is a drag (Problem 2). Cleared on
        # release. While True the X-master ViewBox's mouse pan is disabled
        # so the curve Y-drag does not fight the default ViewBox pan.
        self._overlay_dragging = False
        self._overlay_aux_viewboxes = []
        self._overlay_aux_axes = []
        self._overlay_view_sync_conns = []
        # The X-master axis handle in overlay mode. Its ViewBox owns the
        # shared X range, the default mouse-pan, and the scene geometry
        # anchor; NO curves are attached to it (every channel — including
        # the first/left one — lives on its own aux ViewBox). In
        # subplot/single mode this stays None and _primary_xaxis_ax is
        # axes_list[0] as before.
        self._x_master_handle = None

        # T6 requirement 1: subplot inside-label bookkeeping. Mirrors
        # canvases.py:_apply_inside_channel_labels — when bbox overlap
        # would clip outer ylabels, flip them to an inside-axes TextItem.
        self._inside_label_items = []
        self._inside_label_handles = []
        self._inside_label_conns = []
        # Cache the last subplot label specs so a resize-driven recheck
        # can re-place labels without re-walking the plot.
        self._subplot_label_specs = []

        # Inspector tick-density defaults mirror PersistentTop defaults.
        self._tick_density = (10, 6)

        # Cursor line scene items. In single mode _cursor_line_items is the
        # live hover line on each subplot. In dual mode _cursor_a_items and
        # _cursor_b_items hold the placed A/B cursors.
        self._cursor_line_items = []
        self._cursor_a_items = []
        self._cursor_b_items = []

    # ------------------------------------------------------------------
    # Public surface (signal/method names frozen by W0 contract tests).
    # ------------------------------------------------------------------

    def plot_channels(self, ch_list, mode="overlay", xlabel="Time (s)"):
        """Build the chart for ``ch_list``.

        Row shape (legacy or preferred):

        - ``(name, visible, t, sig, color, unit)`` — legacy
        - ``(name, visible, t, sig, color, unit, data_id)`` — preferred

        ``data_id`` is required for the curve-layer cache to key entries
        per-source-file; rows without it route through the slow path.
        """
        self.clear()

        vis = []
        for row in ch_list:
            if not row[1]:
                continue
            if len(row) >= 7:
                name, _, t, sig, color, unit, data_id = row[:7]
            else:
                name, _, t, sig, color, unit = row[:6]
                data_id = None
            vis.append((name, t, sig, color, unit, data_id))

        if not vis:
            return

        overlay_mode = (mode == "overlay" and len(vis) >= 2)
        subplot_mode = (mode == "subplot" and len(vis) > 1)
        self._overlay_mode = overlay_mode  # parity attr name with TimeDomainCanvas

        if subplot_mode:
            for i, (name, t, sig, color, unit, data_id) in enumerate(vis):
                pi = self._add_plot_item(row=i, col=0)
                handle = PgAxisHandle(plot_item=pi)
                self.axes_list.append(handle)
                self._bind_channel(
                    handle, name, t, sig, color, unit, data_id,
                    xlabel=xlabel if i == len(vis) - 1 else None,
                )
                self._configure_subplot_bottom_axis(handle, is_bottom=(i == len(vis) - 1))
            # NOTE: we intentionally do NOT call ``setXLink`` here.
            # Pyqtgraph's linked-view propagation uses screen-geometry
            # interpolation (ViewBox.linkedViewChanged) which produces a
            # small per-subplot shift when the subplots' screen widths
            # differ (the bottommost subplot owns the x-axis label
            # gutter). For an analytical app the linked range MUST be
            # exact, so we propagate explicitly via _propagate_xlim_to_siblings
            # on every sigXRangeChanged tick from the primary.
            # Subplot labels need bbox-overlap-driven inside/outside flip.
            # vis[i] is (name, t, sig, color, unit, data_id); color at idx 3.
            self._subplot_label_specs = [
                (self.axes_list[i], vis[i][0], vis[i][3])
                for i in range(len(vis))
            ]
            # Apply once now; resize re-checks via resizeEvent.
            self._recheck_subplot_label_placement()
            # Each subplot's left AxisItem auto-sizes to its OWN tick-label
            # text width, so rows with wider numeric labels push their
            # plot-area left edge further right than narrower rows — the
            # shared time grid then looks skewed between rows. Range is
            # already exact via _propagate_xlim_to_siblings; here we only fix
            # geometry by unifying every left axis to the widest one so all
            # plot-area left edges land at the same screen x.
            self._unify_subplot_left_axis_widths()
        elif overlay_mode:
            # Overlay: one PlotItem whose MAIN ViewBox is demoted to an
            # X-master / mouse-capture-only surface (NO curves attached),
            # plus one dedicated aux ViewBox + Y axis PER channel. This is
            # the symmetric layout — the first/left channel is no longer
            # special-cased onto the shared main ViewBox, so its Y drag no
            # longer fights X-padding the way it did when it owned the
            # geometry/X/mouse anchor simultaneously. Channel 1 binds the
            # LEFT axis; channels 2..N bind successive right axes. Mirrors
            # the original matplotlib twinx stack: every channel owns an
            # independent Y axis while all share X.
            pi = self._add_plot_item(row=0, col=0)
            # X-master handle wraps the main ViewBox; never enters
            # axes_list and never carries a curve.
            self._x_master_handle = PgAxisHandle(plot_item=pi)
            # Channel 1 → dedicated aux ViewBox bound to the LEFT axis.
            first_handle = self._add_overlay_axis_handle(pi, 0)
            self.axes_list.append(first_handle)
            self._bind_channel(first_handle, *vis[0], xlabel=xlabel)
            # Channels 2..N → dedicated aux ViewBoxes bound to right axes.
            for idx, (name, t, sig, color, unit, data_id) in enumerate(vis[1:], start=1):
                handle = self._add_overlay_axis_handle(pi, idx)
                self.axes_list.append(handle)
                self._bind_channel(handle, name, t, sig, color, unit, data_id, xlabel=xlabel)
            # Apply default emphasis state (no selection).
            self._apply_overlay_emphasis()
        else:
            # Single channel.
            pi = self._add_plot_item(row=0, col=0)
            handle = PgAxisHandle(plot_item=pi)
            self.axes_list.append(handle)
            name, t, sig, color, unit, data_id = vis[0]
            self._bind_channel(handle, name, t, sig, color, unit, data_id, xlabel=xlabel)

        for handle in self.axes_list:
            self._attach_axis_handle_callbacks(handle)

        # Primary X-axis owner. Subplot/single mode: it is axes_list[0]
        # and we listen on EVERY axis ViewBox (origin-aware propagation;
        # see _on_xrange_changed). Overlay mode: it is the dedicated
        # X-master ViewBox (which is NOT in axes_list because no channel
        # curve lives on it); we listen on the X-master AND every aux
        # channel ViewBox so a pan from any of them propagates the exact
        # range to all the others.
        if self.axes_list:
            if self._overlay_mode and self._x_master_handle is not None:
                self._primary_xaxis_ax = self._x_master_handle
                self._connect_xrange_listener(self._x_master_handle)
            else:
                self._primary_xaxis_ax = self.axes_list[0]
            for handle in self.axes_list:
                self._connect_xrange_listener(handle)
            self._set_xrange_to_data_union()
            if self._overlay_mode:
                self._sync_overlay_aux_viewboxes()
                self._connect_overlay_view_sync()

        self._refresh = True
        self._apply_tick_density_to_all_axes()

    def _add_plot_item(self, *, row, col):
        """Add a PlotItem hosted by our ``_ModifierWheelViewBox``.

        Mirrors ``GraphicsLayoutWidget.addPlot`` but injects the custom
        ViewBox so wheel events route through ``_handle_wheel_dispatch``
        (T6 requirement 4). Also installs a ``sigMouseClicked`` hook on
        the scene for blank-click deselect in overlay mode.
        """
        vb = _ModifierWheelViewBox(owner_canvas=self)
        pi = self._glw.addPlot(row=row, col=col, viewBox=vb)
        try:
            pi.showGrid(x=True, y=True, alpha=0.28)
        except Exception:
            pass
        return pi

    def _add_overlay_axis_handle(self, primary_plot, index):
        """Create one dedicated Y axis/ViewBox for an overlay channel.

        Symmetric layout (Problem 3): EVERY channel — including the
        first — gets its own aux ViewBox so its Y drag never fights the
        X-master's padding.

        - ``index == 0`` → channel 1 binds the built-in LEFT axis.
        - ``index == 1`` → channel 2 reuses the built-in right axis.
        - ``index >= 2`` → channels 3+ append extra right axes to the
          PlotItem layout (pyqtgraph's MultiplePlotAxes example).

        All aux ViewBoxes share the X-master plot's scene geometry and X
        range and have their OWN mouse pan disabled so the main (X-master)
        ViewBox stays the sole mouse-capture surface.
        """
        aux_vb = _ModifierWheelViewBox(owner_canvas=self)
        if index == 0:
            # Channel 1: bind the existing LEFT axis to the aux ViewBox so
            # the left axis tracks this channel's independent Y range.
            try:
                primary_plot.showAxis("left")
            except Exception:
                pass
            axis_item = primary_plot.getAxis("left")
        elif index == 1:
            try:
                primary_plot.showAxis("right")
            except Exception:
                pass
            axis_item = primary_plot.getAxis("right")
        else:
            axis_item = pg.AxisItem("right")
            try:
                primary_plot.layout.addItem(axis_item, 2, 2 + index)
            except Exception:
                pass
            try:
                axis_item.setZValue(-10000)
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
        # Aux ViewBoxes are display-only overlays: the X-master ViewBox is
        # the mouse-pan surface. Disabling mouse here keeps the overlapping
        # aux ViewBoxes from stealing the pan drag (Problem 3 "mouse-
        # capture only" demotion of the main ViewBox).
        try:
            aux_vb.setMouseEnabled(x=False, y=False)
        except Exception:
            pass
        self._overlay_aux_viewboxes.append(aux_vb)
        self._overlay_aux_axes.append(axis_item)
        handle = PgAxisHandle(plot_item=primary_plot, view_box=aux_vb, axis_item=axis_item)
        return handle

    def plot_channels_preserving_xlim(self, ch_list, mode="overlay", xlabel="Time (s)"):
        """Rebuild the chart with ``ch_list``/``mode`` while preserving
        the current primary xlim across the teardown→build cycle.

        T6 requirement 5: mirrors the pattern at main_window.py:382-448
        BUT keeps the capture/restore INSIDE the canvas — per the brief,
        MainWindow should not be involved in the mode-switch path of the
        pyqtgraph canvas. The tangent-only guard at main_window.py:430
        is NOT re-derived here (out of scope per defensive-gate
        ``codex-confirmed-issue-list-means-remaining-scope`` annotations).
        """
        cur_xlim = self._capture_primary_xlim()
        self.plot_channels(ch_list, mode=mode, xlabel=xlabel)
        if cur_xlim is not None:
            self._restore_primary_xlim(cur_xlim)

    def _capture_primary_xlim(self):
        ax = self._primary_xaxis_ax
        if ax is None:
            return None
        try:
            lo, hi = ax.get_xlim()
        except Exception:
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        return (float(lo), float(hi))

    def _restore_primary_xlim(self, xlim):
        ax = self._primary_xaxis_ax
        if ax is None:
            return
        new_lo, new_hi = xlim
        try:
            ax.set_xlim(float(new_lo), float(new_hi))
        except Exception:
            return
        # Order per pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before:
        # mutate, then flush. set_xlim above fired sigXRangeChanged and
        # scheduled the 40 ms debounced QTimer; drain it synchronously
        # so the post-switch frame is the high-detail envelope.
        try:
            self._flush_pending_refresh()
        except Exception:
            pass

    def _bind_channel(self, axis_handle, name, t, sig, color, unit, data_id, *, xlabel=None):
        """Attach one channel to ``axis_handle``.

        Initial bind installs a ``PlotDataItem`` on either the PlotItem's
        primary ViewBox or an overlay auxiliary ViewBox. Subsequent pan/
        zoom refreshes feed the visible item with the current envelope.
        """
        pi = axis_handle.plot_item
        if pi is None:
            return
        # Downsample once for the static bind so we don't ship 100k
        # points into Qt's painter on construction. The fallback uses
        # build_envelope's xlim=None full-range contract — purely a
        # smoke-render path; the cache populates on first set_xlim.
        try:
            xlim = axis_handle.get_xlim()
        except Exception:
            xlim = None
        bind_t, bind_s = build_envelope(
            np.asarray(t),
            np.asarray(sig),
            xlim=None,
            pixel_width=self._initial_bind_pixel_width(axis_handle),
            is_monotonic=None,
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
        # Store the raw arrays + parallel dicts; channel_data stays RAW
        # so get_statistics is unaffected by envelope output.
        t_arr = np.asarray(t)
        sig_arr = np.asarray(sig)
        self.channel_data[name] = (t_arr, sig_arr, color, unit)
        self._channel_data_id[name] = data_id
        line_handle = _PgLineHandle(pdi, label_fallback=name)
        self._channel_lines[name] = (axis_handle, line_handle)
        # Cache monotonicity once per build (parity with F-1 follow-up).
        self._channel_is_monotonic[name] = _is_monotonic_array(t_arr)

        # Y-axis label uses the channel's color so the overlay/subplot
        # visual cue matches the matplotlib renderer.
        try:
            compact = _compact_axis_label(name, unit, max_chars=20)
            label = f"{compact}" + (f" ({unit})" if unit else "")
            axis_handle.set_ylabel(label)
        except Exception:
            pass
        self._apply_pg_axis_style(axis_handle, color)
        if xlabel is not None:
            try:
                axis_handle.set_xlabel(xlabel)
            except Exception:
                pass

    def _apply_pg_axis_style(self, axis_handle, color):
        """Match the original TimeDomain y-axis color cue."""
        try:
            axis = axis_handle.y_axis_item()
        except Exception:
            axis = None
        if axis is None:
            return
        try:
            axis.setPen(pg.mkPen(color=color, width=2.0))
        except Exception:
            pass
        try:
            axis.setTextPen(pg.mkPen(color=color))
        except Exception:
            pass

    def _initial_bind_pixel_width(self, axis_handle=None) -> int:
        """Return a first-frame envelope width close to the visible plot width."""
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
            return self.MAX_PTS
        return max(1, min(self.MAX_PTS, max(widths)))

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
        except Exception:
            pass
        if not is_bottom:
            try:
                bottom.setLabel(text="")
            except Exception:
                pass

    def set_xlim(self, lo, hi):
        """Apply a new xlim to the primary axis. Compatibility-only:
        external callers should prefer ``self._primary_xaxis_ax.set_xlim``.
        """
        primary = self._primary_xaxis_ax
        if primary is None:
            return
        primary.set_xlim(float(lo), float(hi))

    def reset_view_to_data_extents(self):
        """Toolbar Home helper: autoscale Y per axis and share union raw X."""
        for handle in self.axes_list:
            vb = handle.view_box
            if vb is None:
                continue
            try:
                vb.autoRange()
            except Exception:
                pass
        self._set_xrange_to_data_union()
        self._refresh = True
        self.draw_idle()

    def _data_x_union(self):
        bounds = []
        for t, _sig, _color, _unit in self.channel_data.values():
            try:
                arr = np.asarray(t, dtype=float)
                finite = arr[np.isfinite(arr)]
            except Exception:
                finite = np.asarray([])
            if finite.size:
                bounds.append((float(finite.min()), float(finite.max())))
        if not bounds:
            return None
        return (min(lo for lo, _hi in bounds), max(hi for _lo, hi in bounds))

    def _set_xrange_to_data_union(self):
        x_union = self._data_x_union()
        if x_union is None:
            return
        lo, hi = x_union
        # In overlay mode the X-master ViewBox owns the shared X range but
        # is not in axes_list (no curve lives on it); seed its X too so
        # cursor mapping and _current_pixel_width read a real range.
        handles = list(self.axes_list)
        if (
            self._overlay_mode
            and self._x_master_handle is not None
            and self._x_master_handle not in handles
        ):
            handles.append(self._x_master_handle)
        for handle in handles:
            vb = handle.view_box
            try:
                if vb is not None:
                    vb.blockSignals(True)
                handle.set_xlim(lo, hi)
            except Exception:
                pass
            finally:
                try:
                    if vb is not None:
                        vb.blockSignals(False)
                except Exception:
                    pass

    def clear(self):
        """Tear down the chart. Mirrors TimeDomainCanvas.clear."""
        # Drop xrange listener before we wipe the axes it points at.
        self._disconnect_xrange_listener()
        self._disconnect_overlay_view_sync()
        self._teardown_inside_labels()
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        self._refresh_pending = False

        # Strip everything from the GraphicsLayoutWidget.
        try:
            self._glw.clear()
        except Exception:
            pass

        self.axes_list = []
        self._channel_lines = {}
        self.channel_data = {}
        self._channel_data_id = {}
        self._channel_is_monotonic = {}
        self._primary_xaxis_ax = None
        self._curve_path_cache.clear()
        self._last_range_key.clear()
        self._overlay_mode = False
        self._refresh = True
        # T6 — drop overlay selection + subplot label scaffolding so the
        # next plot_channels build starts from a clean slate. Inside-label
        # scene items were already removed by _teardown_inside_labels()
        # above (pg.GLW.clear() does NOT remove scene().addItem() items).
        self._selected_overlay_channel = None
        self._overlay_y_drag_start = None
        self._overlay_dragging = False
        self._x_master_handle = None
        self._overlay_aux_viewboxes = []
        self._overlay_aux_axes = []
        self._subplot_label_specs = []
        self._cursor_line_items = []
        self._cursor_a_items = []
        self._cursor_b_items = []
        # Cursor placement is NOT cleared here — full_reset / reset_cursor_state
        # do that. Mirror TimeDomainCanvas.clear's behavior.

    def full_reset(self):
        """Clear chart AND cursor state. Use on file close."""
        self.clear()
        self._ax = None
        self._bx = None
        self._placing = "A"
        self._cursor_visible = False
        self._dual = False
        self._curve_path_cache.clear()
        self._last_range_key.clear()
        self._last_t = 0
        self.draw_idle()

    def set_cursor_visible(self, v):
        """Toggle single-cursor visibility."""
        self._cursor_visible = bool(v)
        if not self._cursor_visible:
            self._hide_cursor_items(self._cursor_line_items)
            self._hide_cursor_items(self._cursor_a_items)
            self._hide_cursor_items(self._cursor_b_items)
            self.draw_idle()

    def set_dual_cursor_mode(self, en):
        """Toggle dual-cursor mode."""
        self._dual = bool(en)
        if not en:
            self._ax = None
            self._bx = None
            self._placing = "A"
            self._refresh = True
            self._hide_cursor_items(self._cursor_a_items)
            self._hide_cursor_items(self._cursor_b_items)
            self.dual_cursor_info.emit("")
            self.draw_idle()

    def reset_cursor_state(self):
        """Drop dual-cursor placement and request a redraw.

        Compatibility seam called by ``MainWindow._reset_cursors``. The
        ordering (mutate fields, then redraw) follows
        ``pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before``.
        """
        self._ax = None
        self._bx = None
        self._placing = "A"
        self._refresh = True
        self._hide_cursor_items(self._cursor_line_items)
        self._hide_cursor_items(self._cursor_a_items)
        self._hide_cursor_items(self._cursor_b_items)
        self.dual_cursor_info.emit("")
        self.draw_idle()

    def draw_idle(self):
        """No-op equivalent of matplotlib FigureCanvas.draw_idle.

        Pyqtgraph re-renders automatically on data/range changes; we
        only need to nudge the scene so post-Apply paint passes flush.
        """
        # Avoid an explicit repaint here — pyqtgraph's scene already
        # invalidates lazily. The cursor/span overlays will need an
        # update() pass once T6 wires them.
        try:
            self._glw.update()
        except Exception:
            pass

    def draw(self):
        """Synchronous redraw alias (matplotlib FigureCanvas parity).

        MainWindow.plot_time() calls ``self.canvas_time.draw()`` on the
        no-files / no-checked-channels / no-plottable-data early-return
        paths. Pyqtgraph's scene already invalidates lazily, so this is
        a thin alias over ``draw_idle()`` — no flush bookkeeping needed
        per ``pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before``
        (draw_idle handles scheduling; this is a parity seam, not a
        mutator).
        """
        self.draw_idle()

    # ------------------------------------------------------------------
    # Cursor item helpers.
    # ------------------------------------------------------------------

    def _hide_cursor_items(self, items):
        for item in items or []:
            try:
                item.setVisible(False)
            except Exception:
                pass

    def _ensure_cursor_items(self, attr_name, *, color, width=1.0, style=Qt.SolidLine):
        items = getattr(self, attr_name, [])
        if len(items) == len(self.axes_list):
            return items
        self._remove_cursor_items(items)
        pen = pg.mkPen(color=color, width=width, style=style)
        new_items = []
        for handle in self.axes_list:
            vb = handle.view_box
            if vb is None:
                continue
            line = pg.InfiniteLine(pos=0.0, angle=90, movable=False, pen=pen)
            line.setZValue(1000)
            line.setVisible(False)
            try:
                vb.addItem(line, ignoreBounds=True)
                new_items.append(line)
            except Exception:
                pass
        setattr(self, attr_name, new_items)
        return new_items

    def _remove_cursor_items(self, items):
        for item in items or []:
            try:
                parent = item.parentItem()
                if parent is not None and hasattr(parent, "removeItem"):
                    parent.removeItem(item)
            except Exception:
                pass

    def _set_cursor_items_pos(self, items, x):
        for item in items or []:
            try:
                item.setValue(float(x))
                item.setVisible(True)
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
        self._last_t = 0
        if self._dual:
            hover_items = self._ensure_cursor_items(
                "_cursor_line_items", color="#64748b", width=1.0, style=Qt.DotLine
            )
            self._set_cursor_items_pos(hover_items, x)
            self._emit_dual_cursor_html()
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

    # ------------------------------------------------------------------
    # Overlay selection + Y-drag mouse wiring (Problem 2). Ports
    # canvases.py:_select_overlay_channel_from_event (850-895) and
    # _update_overlay_y_drag (916) onto the pyqtgraph eventFilter, driven
    # by real Qt events rather than the matplotlib callback dispatcher.
    # ------------------------------------------------------------------

    def _scene_y_from_viewport_pos(self, viewport_pos):
        """Map a viewport-pixel ``QPoint`` to a scene Y coordinate.

        The Y-drag helpers work in a single monotonic pixel axis; scene Y
        (top-origin, increasing downward) is used consistently for both
        the begin-capture and apply steps so the delta is well-defined.
        Returns ``None`` on failure.
        """
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        if scene_pos is None:
            return None
        try:
            return float(scene_pos.y())
        except Exception:
            return None

    def _select_overlay_channel_from_scene_pos(self, scene_pos):
        """Resolve which overlay channel a press at ``scene_pos`` selects.

        Port of canvases.py:_select_overlay_channel_from_event: first try a
        direct Y-axis hit (the click landed on a channel's axis gutter via
        its ViewBox), then fall back to the nearest curve point within
        ``_overlay_pick_radius_px``. Returns the channel name or ``None``.
        """
        if scene_pos is None:
            return None
        # Axis/ViewBox hit: a press inside an aux ViewBox's bounding rect
        # selects that channel directly (parity with the axis='y' branch).
        axis_handle = self._axis_handle_at_scene_pos(scene_pos)
        if axis_handle is not None:
            name = self._channel_name_for_handle(axis_handle)
            if name is not None:
                # Only accept an axis hit when it is NOT ambiguous with a
                # closer curve; the curve scan below refines it. We keep
                # the axis hit as a baseline candidate.
                axis_name = name
            else:
                axis_name = None
        else:
            axis_name = None

        best_name = None
        best_dist = float("inf")
        try:
            px = float(scene_pos.x())
            py = float(scene_pos.y())
        except Exception:
            return axis_name
        for name, (handle, line) in self._channel_lines.items():
            vb = handle.view_box
            if vb is None:
                continue
            pdi = line.plot_data_item
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
            # Drop NaN-gap samples so the pixel mapping below stays finite
            # (arraytoqpath-not-byte-identical lesson: NaN gaps + single
            # points need explicit handling).
            finite = np.isfinite(xdata) & np.isfinite(ydata)
            if not finite.any():
                continue
            xdata = xdata[finite]
            ydata = ydata[finite]
            if n > 3000:
                step = max(1, xdata.size // 3000)
                xdata = xdata[::step]
                ydata = ydata[::step]
            # Map each data point to scene pixels via this channel's VB.
            try:
                scene_pts = self._map_view_points_to_scene(vb, xdata, ydata)
            except Exception:
                continue
            if scene_pts is None or scene_pts.size == 0:
                continue
            dist = float(
                np.min(
                    np.hypot(scene_pts[:, 0] - px, scene_pts[:, 1] - py)
                )
            )
            if dist < best_dist:
                best_dist = dist
                best_name = name
        if best_name is not None and best_dist <= self._overlay_pick_radius_px:
            return best_name
        # No curve within the pick radius — fall back to the axis hit
        # (clicking the axis gutter still selects its channel).
        return axis_name

    def _map_view_points_to_scene(self, view_box, xdata, ydata):
        """Map arrays of (x, y) view coordinates to scene pixel coords.

        Returns an ``(n, 2)`` float array of scene (x, y) or ``None``. Uses
        the ViewBox's view→scene transform via ``mapViewToScene`` per
        point. A single point is handled correctly (n>=1).
        """
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

    def _channel_name_for_handle(self, handle):
        for name, (axis_handle, _line) in self._channel_lines.items():
            if axis_handle is handle:
                return name
        return None

    def _set_x_master_mouse_enabled(self, enabled):
        """Toggle the X-master ViewBox's mouse pan.

        Disabled for the duration of an overlay Y-drag so the curve drag
        does not also pan the shared X via the default ViewBox handler.
        """
        master = self._x_master_handle
        if master is None:
            return
        vb = master.view_box
        if vb is None:
            return
        try:
            vb.setMouseEnabled(x=bool(enabled), y=bool(enabled))
        except Exception:
            pass

    def _handle_overlay_mouse_press(self, event):
        """Overlay-mode left-press: select nearest channel + begin Y-drag,
        or deselect on a blank-area click. No-op outside overlay mode or
        in cursor mode (cursor takes precedence, matching canvases.py:853).
        Returns ``True`` when the gesture was consumed.
        """
        if not self._overlay_mode or self._cursor_visible:
            return False
        try:
            if event.button() != Qt.LeftButton:
                return False
            viewport_pos = event.pos()
        except Exception:
            return False
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        name = self._select_overlay_channel_from_scene_pos(scene_pos)
        if name is None:
            # Blank-area click → deselect (emits overlay_channel_selected(None)
            # only when something was selected, via select_overlay_channel).
            if self._selected_overlay_channel is not None:
                self.select_overlay_channel(None)
                return True
            return False
        self.select_overlay_channel(name)
        # Begin the Y-drag from this scene Y; disable the X-master pan so
        # the drag is Y-only.
        start_y = self._scene_y_from_viewport_pos(viewport_pos)
        if start_y is not None:
            self._begin_overlay_y_drag_at(start_y_px=start_y)
            self._overlay_dragging = True
            self._set_x_master_mouse_enabled(False)
        return True

    def _handle_overlay_mouse_move(self, event):
        """Apply a Y-drag while the left button is held during an overlay
        drag. Returns ``True`` when the drag consumed the move."""
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
        return True

    def get_statistics(self, time_range=None):
        """Read RAW arrays from ``channel_data`` (design §4.2 invariant).

        Identical to ``TimeDomainCanvas.get_statistics`` so the W0
        contract holds.
        """
        stats = {}
        for ch, (t, sig, _color, unit) in self.channel_data.items():
            if time_range is not None:
                lo, hi = time_range
                m = (t >= lo) & (t <= hi)
                s = sig[m]
            else:
                s = sig
            if len(s):
                stats[ch] = {
                    "min": float(np.min(s)),
                    "max": float(np.max(s)),
                    "mean": float(np.mean(s)),
                    "rms": float(np.sqrt(np.mean(s ** 2))),
                    "std": float(np.std(s)),
                    "p2p": float(np.ptp(s)),
                    "unit": unit,
                }
        return stats

    def enable_span_selector(self, cb):
        """Store the callback; do NOT auto-enable the drag-to-select.

        Design §4.2 invariant + main_window.py:993-996: the always-on
        SpanSelector was retired. We keep the method as a compatibility
        seam so callers don't AttributeError, but no drag handler is
        wired here — Task 6 will add an opt-in gesture if and only if
        the design requires one.
        """
        self._span_callback = cb
        # Intentionally no widget installed. self.span_selector stays None.

    def set_tick_density(self, x, y):
        """Apply inspector-controlled tick density to PG axes.

        Use pyqtgraph's adaptive density knob instead of explicit
        ``setTickSpacing``. Fixed major/minor spacing is range-stale after
        auto-range and makes the minor level labelable, which can produce dense
        tick-label piles and very slow repaint on channel rebuilds.
        """
        try:
            x_n = max(3, int(x))
            y_n = max(3, int(y))
        except Exception:
            x_n, y_n = self._tick_density
        self._tick_density = (x_n, y_n)
        self._apply_tick_density_to_all_axes()
        # Tick density changes tick-label text → left-axis auto-width, which
        # re-skews subplot left edges; re-unify after applying density.
        self._unify_subplot_left_axis_widths()
        self._refresh = True
        self.draw_idle()

    def _apply_tick_density_to_all_axes(self):
        x_n, y_n = self._tick_density
        x_density = max(0.35, min(3.0, float(x_n) / 10.0))
        y_density = max(0.35, min(3.0, float(y_n) / 6.0))
        for handle in self.axes_list:
            x_axis = handle.x_axis_item() if hasattr(handle, "x_axis_item") else None
            y_axis = handle.y_axis_item() if hasattr(handle, "y_axis_item") else None
            self._apply_axis_tick_density(x_axis, x_density)
            self._apply_axis_tick_density(y_axis, y_density)

    def _apply_axis_tick_density(self, axis, density):
        if axis is None:
            return
        set_style = getattr(axis, "setStyle", None)
        if callable(set_style):
            try:
                set_style(maxTickLevel=0)
            except Exception:
                pass
        reset_spacing = getattr(axis, "setTickSpacing", None)
        if callable(reset_spacing):
            try:
                reset_spacing()
            except Exception:
                pass
        set_density = getattr(axis, "setTickDensity", None)
        if callable(set_density):
            try:
                set_density(float(density))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Chart-options dialog (Fix 1: parity with the matplotlib path's
    # canvases.py:_open_chart_options_for_axes + dblclick handler).
    # ------------------------------------------------------------------

    def open_chart_options_dialog(self, parent=None):
        """Open the chart-options dialog for the active/primary axis.

        Wired to ``_ChartCard.open_chart_options()`` via the toolbar
        图表选项 button — the matplotlib canvas exposes the identically
        named method (canvases.py:593), and ``_ChartCard`` does
        ``getattr(self.canvas, 'open_chart_options_dialog', None)``; once
        this exists the button stops returning ``False`` on the PG canvas.

        Resolves the axis to drive (preferring the last double-clicked
        axis, then the primary), wraps it in its ``PgAxisHandle`` (already
        the live form in ``axes_list``), and hands it to
        ``_axis_interaction.edit_chart_options_dialog`` which T3 made
        handle-aware. Returns the dialog's truthy result.
        """
        handle = self._resolve_active_axis_handle()
        if handle is None:
            return False
        return self._open_chart_options_for_handle(handle, parent=parent)

    def _resolve_active_axis_handle(self):
        """Return the ``PgAxisHandle`` the toolbar button should target.

        Prefer the remembered (last double-clicked) handle when it is
        still live, else the primary axis, else the first in
        ``axes_list`` (mirrors canvases.py:_first_live_axes preference
        order).
        """
        remembered = self._chart_options_ax
        if remembered is not None and remembered in self.axes_list:
            return remembered
        if self._primary_xaxis_ax is not None and self._primary_xaxis_ax in self.axes_list:
            return self._primary_xaxis_ax
        return self.axes_list[0] if self.axes_list else None

    def _open_chart_options_for_handle(self, handle, parent=None):
        """Open the chart-options dialog for ``handle`` (a ``PgAxisHandle``).

        Guards against a double-open from a fast double-click via
        ``_chart_options_opening`` (pyqt-ui/2026-04-26-popover-accept-
        deactivate-race). Records the handle as the remembered axis so a
        following toolbar-button open targets the same subplot, then
        delegates to the handle-aware dialog entry point.
        """
        if self._chart_options_opening:
            return False
        if handle is None or handle not in self.axes_list:
            return False
        from . import _axis_interaction

        self._chart_options_ax = handle
        # Releasing any latched pan/zoom drag state so the modal does not
        # leave the ViewBox mid-drag (parity with matplotlib's
        # _clear_canvas_pointer_state). The PG canvas has no
        # _mouse_button_pressed flag, but it does carry overlay-drag
        # bookkeeping — drop it so the dialog cannot resume a stale drag.
        self._overlay_y_drag_start = None
        self._chart_options_opening = True
        try:
            target_parent = parent if parent is not None else self.window()
            return bool(_axis_interaction.edit_chart_options_dialog(target_parent, handle))
        finally:
            self._chart_options_opening = False

    def eventFilter(self, obj, event):
        """Intercept a left double-click on the GraphicsLayoutWidget's
        viewport and open the chart-options dialog for the subplot under
        the cursor.

        The matplotlib path keys on ``event.button == 1 and
        event.dblclick`` (canvases.py:1370); the QWidget analogue is a
        ``QEvent.MouseButtonDblClick`` with ``button() == LeftButton``. We
        map the viewport pixel position into the scene so the subplot
        hit-test (``_axis_handle_at_scene_pos``) stays accurate. A miss
        (double-click in the axis-label gutter) falls back to the
        active/primary axis so the gesture is never a dead click.
        """
        try:
            if event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.LeftButton:
                    self._handle_viewport_double_click(event.pos())
                    # Return False so the GraphicsView still processes the
                    # event for its own bookkeeping; we do not consume it.
            elif event.type() == QEvent.MouseButtonPress:
                # Overlay selection / Y-drag begin takes precedence over
                # cursor placement, but only outside cursor mode (cursor
                # mode wins, matching canvases.py:853). _handle_overlay_
                # mouse_press is a no-op outside overlay mode.
                if self._handle_overlay_mouse_press(event):
                    return True
                if self._handle_cursor_mouse_press(event):
                    return True
            elif event.type() == QEvent.MouseMove:
                if self._handle_overlay_mouse_move(event):
                    return True
                if self._handle_cursor_mouse_move(event):
                    return True
            elif event.type() == QEvent.MouseButtonRelease:
                if self._handle_overlay_mouse_release(event):
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _handle_viewport_double_click(self, viewport_pos):
        """Resolve the subplot under ``viewport_pos`` (a widget-pixel
        ``QPoint``) and open the chart-options dialog for it."""
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        handle = self._axis_handle_at_scene_pos(scene_pos)
        if handle is None:
            handle = self._resolve_active_axis_handle()
        if handle is None:
            return
        self._open_chart_options_for_handle(handle)

    def _viewport_pos_to_scene(self, viewport_pos):
        """Map a viewport-pixel ``QPoint`` to a scene ``QPointF`` via the
        GraphicsView's ``mapToScene``. Returns ``None`` on failure."""
        try:
            return self._glw.mapToScene(viewport_pos)
        except Exception:
            return None

    def _axis_handle_at_scene_pos(self, scene_pos):
        """Return the ``PgAxisHandle`` whose ViewBox contains ``scene_pos``.

        Iterates ``axes_list`` and tests each ViewBox's
        ``sceneBoundingRect`` (verified present on pyqtgraph 0.14.0
        ViewBox). Returns ``None`` when the click is outside every plot
        area (e.g. in the axis-label gutter) so the caller can fall back
        to the active axis.
        """
        if scene_pos is None:
            return None
        for handle in self.axes_list:
            vb = handle.view_box
            if vb is None:
                continue
            try:
                rect = vb.sceneBoundingRect()
            except Exception:
                continue
            try:
                if rect.contains(scene_pos):
                    return handle
            except Exception:
                continue
        return None

    def _axis_handle_for_view_box(self, view_box):
        if view_box is None:
            return None
        for handle in self.axes_list:
            if handle.view_box is view_box:
                return handle
        return None

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

    def invalidate_envelope_cache(self, reason: str, *, data_id=None, channel=None):
        """Drop curve-layer cache entries.

        Same filter contract as ``TimeDomainCanvas.invalidate_envelope_cache``
        so the call sites in MainWindow keep working unchanged. Filter
        scope: ``data_id`` is stored alongside the cache key (as part of
        the channel key prefix); without a channel filter we drop every
        entry whose channel name participates in this canvas's data_id
        mapping for that file.
        """
        if data_id is None and channel is None:
            self._curve_path_cache.clear()
            self._last_range_key.clear()
            return
        keys_to_drop = []
        for k in self._curve_path_cache:
            k_channel = k[0]
            if channel is not None and k_channel != channel:
                continue
            if data_id is not None:
                # Match data_id via the parallel dict.
                if self._channel_data_id.get(k_channel) != data_id:
                    continue
            keys_to_drop.append(k)
        for k in keys_to_drop:
            self._curve_path_cache.pop(k, None)
        # Also drop the per-channel last-range marker so the next flush
        # rebuilds the cache entry.
        if channel is not None:
            self._last_range_key.pop(channel, None)
        elif data_id is not None:
            for ch_name, ch_data_id in list(self._channel_data_id.items()):
                if ch_data_id == data_id:
                    self._last_range_key.pop(ch_name, None)

    def invalidate_monotonicity_cache(self, custom_xaxis_fid=None, custom_xaxis_ch=None):
        """Drop per-channel monotonicity flags. Mirrors the matplotlib
        canvas surface so MainWindow's invalidation call sites remain
        renderer-agnostic. Full-clear (no filters) matches the
        TimeDomainCanvas behavior — the next plot_channels rebuilds the
        dict."""
        self._channel_is_monotonic.clear()

    # ------------------------------------------------------------------
    # Viewport refresh wiring (design §5.2 hot path).
    # ------------------------------------------------------------------

    def _connect_xrange_listener(self, axis_handle):
        """Attach sigXRangeChanged on the axis's ViewBox.

        Connects ADDITIVELY: every subplot axis gets its own connection
        so an origin-aware propagation handler can identify which axis
        sourced the change. The prior implementation overwrote a single
        ``_xrange_conn`` slot per call, which left only the most-recent
        axis wired and silently dropped earlier subscriptions on every
        ``plot_channels`` rebuild.
        """
        vb = axis_handle.view_box if axis_handle is not None else None
        if vb is None or not hasattr(vb, "sigXRangeChanged"):
            return
        # Closure binds the SOURCE handle so origin-skip works correctly
        # without relying on pyqtgraph emitting the ViewBox as sender.
        source_handle = axis_handle

        def _handler(*_args, _src=source_handle):
            self._on_xrange_changed(_src)

        try:
            vb.sigXRangeChanged.connect(_handler)
            self._xrange_conns.append((vb, _handler))
        except Exception:
            pass

    def _disconnect_xrange_listener(self):
        """Drop every sigXRangeChanged hook before its axis is destroyed.

        Pyqtgraph analogue of
        ``pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle``:
        callbacks survive widget teardown unless explicitly disconnected.
        """
        for vb, handler in self._xrange_conns:
            try:
                vb.sigXRangeChanged.disconnect(handler)
            except Exception:
                pass
        self._xrange_conns = []

    def _on_xrange_changed(self, source_handle, *_args):
        """Coalesce rapid xlim updates into a single refresh AND
        propagate the exact range to sibling axes (subplot mode).

        We do NOT use pyqtgraph's ``setXLink`` because its
        ``linkedViewChanged`` uses screen-geometry interpolation that
        introduces a small per-axis shift when the subplots' screen
        widths differ. For this app the range must be byte-identical
        across subplots, so we push it ourselves.

        ``source_handle`` is the axis whose ViewBox emitted the range
        change. Propagation skips ``source_handle`` so it does not
        receive its own range back as a redundant write.
        """
        # Propagate first so the sibling axes are in sync BEFORE the
        # debounced refresh runs.
        self._propagate_xlim_to_siblings(source=source_handle)
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._refresh_timer.start()

    def _propagate_xlim_to_siblings(self, source=None):
        """Mirror ``source``'s xlim onto every other axis facade.

        Cheap and idempotent: pyqtgraph's setXRange short-circuits when
        the range is already equal modulo padding (event-conditional per
        ``pyqt-ui/2026-04-25-cache-invalidation-event-conditional`` — we
        skip siblings whose current range already matches the source).
        We guard against re-entrant sigXRangeChanged by blocking
        signals on siblings while we set the range.

        ``source=None`` falls back to the primary axis (legacy call site
        + the ``_restore_primary_xlim`` path).
        """
        if source is None:
            source = self._primary_xaxis_ax
        if source is None or len(self.axes_list) <= 1:
            return
        try:
            lo, hi = source.get_xlim()
        except Exception:
            return
        for handle in self.axes_list:
            if handle is source:
                continue
            vb = handle.view_box
            if vb is None:
                continue
            # Event-conditional skip: only push when the sibling's
            # current range actually differs. pyqtgraph's setXRange is
            # already a no-op for equal ranges, but checking here also
            # avoids the blockSignals dance for the no-op case.
            try:
                cur_lo, cur_hi = handle.get_xlim()
            except Exception:
                cur_lo, cur_hi = (None, None)
            if cur_lo == float(lo) and cur_hi == float(hi):
                continue
            try:
                # blockSignals avoids ping-pong with sibling listeners.
                vb.blockSignals(True)
                vb.setXRange(float(lo), float(hi), padding=0)
            except Exception:
                pass
            finally:
                try:
                    vb.blockSignals(False)
                except Exception:
                    pass

    def _flush_pending_refresh(self):
        """Drain any pending refresh immediately (end-of-pan/zoom).

        Per pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before:
        callers MUST invoke this AFTER mutating xlim, never before. The
        canvas has no awareness of who scheduled the pending refresh —
        all it does is run the visible-data update synchronously.
        """
        # Even with no scheduled timer we still want to allow a
        # synchronous repopulation when the caller has just mutated
        # xlim without a sigXRangeChanged round-trip (programmatic
        # plot_channels rebuilds). Hit the timer's flag too.
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        # If nothing is scheduled and there is no data, exit cheaply.
        if not self._channel_lines or self._primary_xaxis_ax is None:
            self._refresh_pending = False
            return
        # Run the update synchronously so the last frame of a pan ends
        # on the high-detail envelope.
        try:
            self._refresh_visible_data()
        finally:
            self._refresh_pending = False

    def _current_pixel_width(self) -> int:
        """Pixel width of the primary chart area (used as the envelope
        bucket count)."""
        primary = self._primary_xaxis_ax
        if primary is None:
            return self.MAX_PTS
        vb = primary.view_box
        if vb is None:
            return self.MAX_PTS
        try:
            rect = vb.sceneBoundingRect()
            w = int(max(1, rect.width()))
            return w
        except Exception:
            return self.MAX_PTS

    def _refresh_visible_data(self):
        """Recompute and display the viewport envelope for every channel."""
        self._refresh_pending = False
        if not self._channel_lines or self._primary_xaxis_ax is None:
            return
        try:
            xlim = self._primary_xaxis_ax.get_xlim()
        except Exception:
            return
        pixel_width = self._current_pixel_width()

        for name, (axis_facade, line_facade) in list(self._channel_lines.items()):
            entry = self.channel_data.get(name)
            if entry is None:
                continue
            t, sig, color, _unit = entry

            # Range-key gate: if the key didn't change since the last flush,
            # skip the envelope+setData work entirely. This keeps repeated
            # _flush_pending_refresh() calls with the same xlim a no-op.
            range_key = _quantize_range_key(name, xlim, pixel_width)
            if self._last_range_key.get(name) == range_key:
                continue

            is_monotonic = self._channel_is_monotonic.get(name)
            try:
                env_t, env_s = positions_envelope(
                    t, sig,
                    xlim=xlim,
                    pixel_width=pixel_width,
                    is_monotonic=is_monotonic,
                )
            except Exception as exc:
                _log.warning(
                    "positions_envelope failed for %r at xlim=%r: %s",
                    name, xlim, exc,
                )
                continue

            self._last_range_key[name] = range_key

            try:
                line_facade.plot_data_item.setData(env_t, env_s)
            except Exception as exc:
                _log.warning("PlotDataItem.setData failed for %r: %s", name, exc)

        self._refresh = True

    def _build_painter_path(self, t, s) -> QPainterPath:
        """Build a ``QPainterPath`` from envelope output. We work in data
        space here; the eventual blit translates to pixel space via the
        ViewBox's transform. Building the path once per cache key means
        repeated paint events (e.g. cursor overlay) do NOT re-walk the
        envelope arrays.

        Perf (T9): the all-finite case — which is the production hot path,
        since :func:`positions_envelope` bails to the numpy reference on any
        NaN in the visible window — is vectorized through
        ``pyqtgraph.functions.arrayToQPath(x, y, connect='all')``. That
        builds the ``QPainterPath`` from the numpy ``x``/``y`` arrays in C
        (the same QPolygonF→addPolygon fast path ``PlotCurveItem`` uses
        internally), replacing the pure-Python per-point
        ``moveTo``/``lineTo`` loop that dominated the ~10.7 ms pan frame
        (see signal-processing/2026-05-28-component-speedup-does-not-imply-
        end-to-end-target). For all-finite input the resulting path is
        byte-identical to the old loop (1 MoveTo + N-1 LineTo, same
        coordinates, same order).

        The NaN-gap path still goes through :meth:`_build_painter_path_loop`
        unchanged, because ``arrayToQPath``'s ``connect='all'`` would bridge
        the gap with a spurious line and its ``connect='finite'`` backfills
        non-finite samples with their neighbour (extra duplicate elements)
        and drops single-point chunks — neither reproduces the old loop's
        break-the-subpath discontinuity geometry.
        """
        n = min(len(t), len(s))
        if n == 0:
            return QPainterPath()
        t = np.asarray(t)
        s = np.asarray(s)
        # Fast path: >= 2 samples, all finite → vectorized C build.
        # asammdf's min/max envelope over a finite window is finite, so
        # this is the branch the production pan loop takes every frame.
        # We require n >= 2 because arrayToQPath drops a lone point
        # (elementCount 0), whereas the old loop emitted a bare moveTo
        # (elementCount 1) — routing n < 2 through the loop keeps that
        # degenerate single-point geometry byte-identical.
        if n >= 2 and np.isfinite(t[:n]).all() and np.isfinite(s[:n]).all():
            # arrayToQPath needs same-length contiguous float arrays; the
            # envelope output is float64 but slice to n and enforce
            # contiguity defensively (a view of a larger buffer would not
            # be C-contiguous). finiteCheck=False because we just proved
            # finiteness — this skips arrayToQPath's internal isfinite scan.
            x = np.ascontiguousarray(t[:n], dtype=np.float64)
            y = np.ascontiguousarray(s[:n], dtype=np.float64)
            return pg.functions.arrayToQPath(x, y, connect="all",
                                             finiteCheck=False)
        # Slow path: NaN segments present — break the sub-path on each
        # discontinuity, matches asammdf's handling. Byte-identical to the
        # historical loop (T9 preserved this verbatim for gap parity).
        return self._build_painter_path_loop(t, s, n)

    def _build_painter_path_loop(self, t, s, n) -> QPainterPath:
        """Pure-Python per-point builder used only when NaN gaps are
        present. Kept byte-identical to the pre-T9 ``_build_painter_path``
        loop so the discontinuity geometry (bare ``moveTo`` after a gap, no
        element for NaN samples) is preserved exactly.
        """
        path = QPainterPath()
        # Skip NaN segments by breaking the sub-path; matches asammdf's
        # discontinuity handling.
        started = False
        for i in range(n):
            ti = float(t[i])
            si = float(s[i])
            if not (np.isfinite(ti) and np.isfinite(si)):
                started = False
                continue
            if not started:
                path.moveTo(ti, si)
                started = True
            else:
                path.lineTo(ti, si)
        return path

    def _render_path_to_pixmap(self, path: QPainterPath, color: str, pixel_width: int) -> QPixmap:
        """Render the QPainterPath into a QPixmap once per cache entry.

        Antialiasing is OFF (matches asammdf strategy from design §5.2
        evidence). The pixmap is sized to ``pixel_width × 200`` as a
        proxy chart-area; T6 will plumb the actual ViewBox geometry once
        the overlay/cursor layer lands.
        """
        height = 200
        pix = QPixmap(max(1, pixel_width), height)
        pix.fill(Qt.transparent)
        # Painter on a 1×1 pixmap is a no-op; guard the degenerate case.
        if pix.isNull() or pix.width() < 2 or pix.height() < 2:
            return pix
        try:
            painter = QPainter(pix)
            painter.setRenderHint(QPainter.Antialiasing, False)
            pen = QPen()
            try:
                pen.setColor(pg.mkColor(color))
            except Exception:
                from PyQt5.QtGui import QColor
                pen.setColor(QColor(color))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawPath(path)
            painter.end()
        except Exception:
            # Degenerate-rect fallback (pyqt-ui/2026-04-25-tightbbox-
            # survives-offscreen-qt): a 1×1 transparent pixmap is still
            # a valid QPixmap; callers test pix.isNull(), not contents.
            pass
        return pix

    # ------------------------------------------------------------------
    # T6 — Overlay selection / emphasis (mirrors
    # canvases.py:_apply_overlay_selection_style).
    # ------------------------------------------------------------------

    def select_overlay_channel(self, name):
        """Select an overlay channel as the per-series Y-drag target.

        ``name=None`` clears the selection. Emits
        ``overlay_channel_selected(name)`` once and ONLY when the
        selection actually changes (matches matplotlib path's idempotent
        gate at canvases.py:813-814 so the test asserting exactly two
        emissions — select then deselect — holds).
        """
        if name is not None and name not in self._channel_lines:
            return
        if self._selected_overlay_channel == name:
            return
        self._selected_overlay_channel = name
        self._apply_overlay_emphasis()
        self.overlay_channel_selected.emit(name)
        self.draw_idle()

    def _overlay_emphasis_for_channel(self, name):
        """Return ``(line_width, alpha)`` currently displayed for ``name``.

        Used by tests to make a two-frame state-change assertion on the
        per-channel emphasis without coupling to pyqtgraph internals.
        """
        pair = self._channel_lines.get(name)
        if pair is None:
            return (None, None)
        _axis_facade, line_facade = pair
        pdi = line_facade.plot_data_item
        # Pull pen width + alpha from the PlotDataItem.
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
        """Walk every channel and set line width + alpha to match the
        current selection state. Matches
        canvases.py:_apply_overlay_selection_style.
        """
        selected = self._selected_overlay_channel
        for name, (_axis_facade, line_facade) in self._channel_lines.items():
            pdi = line_facade.plot_data_item
            if not self._overlay_mode or selected is None:
                self._apply_pdi_emphasis(
                    pdi, width=self._overlay_default_lw,
                    alpha=self._overlay_default_alpha,
                )
                continue
            is_selected = (name == selected)
            if is_selected:
                self._apply_pdi_emphasis(
                    pdi, width=self._overlay_selected_lw,
                    alpha=self._overlay_selected_alpha,
                )
            else:
                self._apply_pdi_emphasis(
                    pdi, width=self._overlay_de_emphasised_lw,
                    alpha=self._overlay_de_emphasised_alpha,
                )

    def _apply_pdi_emphasis(self, pdi, *, width, alpha):
        """Set line width (via pen) + alpha on a single PlotDataItem.

        Antialiasing stays OFF so the asammdf-style cached pixmap
        strategy (design §5.2) is preserved.
        """
        try:
            opts = getattr(pdi, "opts", {}) or {}
            pen = opts.get("pen")
            color = None
            try:
                from PyQt5.QtGui import QPen
                if isinstance(pen, QPen):
                    color = pen.color()
            except Exception:
                color = None
            if color is None:
                # Fall back to mkColor on the stored color name.
                try:
                    color = pg.mkColor(pen)
                except Exception:
                    color = None
            if color is None:
                pdi.setPen(pg.mkPen(width=float(width)))
            else:
                pdi.setPen(pg.mkPen(color=color, width=float(width)))
        except Exception:
            pass
        try:
            pdi.setOpacity(float(alpha))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # T6 — Selected-channel Y drag.
    # ------------------------------------------------------------------

    def _begin_overlay_y_drag_at(self, *, start_y_px):
        """Capture the (pixel, ylim) pair so the next drag-apply can
        compute the shift. Mirrors canvases.py:_begin_overlay_y_drag.
        """
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
        """Apply the pan implied by a Y drag from start to ``current_y_px``.

        Returns ``True`` when a ylim shift was applied, ``False``
        otherwise. Mirrors canvases.py:_update_overlay_y_drag, except we
        derive the pixel height from the ViewBox's sceneBoundingRect
        rather than ``ax.bbox.height``.
        """
        if self._overlay_y_drag_start is None:
            return False
        ax = self._selected_overlay_axes()
        if ax is None:
            self._overlay_y_drag_start = None
            return False
        start_y, (lo, hi) = self._overlay_y_drag_start
        # Pixel height of the selected ViewBox.
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
        # Symmetric overlay layout (Problem 3): the selected channel now
        # lives on its OWN aux ViewBox, NOT on the X-master ViewBox, so a
        # ``set_ylim`` here cannot perturb the shared X range — the prior
        # X-pin capture/restore around this mutation is dead and removed.
        # (Verified byte-exact by the X-stability assertions in
        # tests/ui/test_chart_stack.py and tests/ui/test_pg_timedomain_canvas.py.)
        try:
            ax.set_ylim(lo + shift, hi + shift)
        except Exception:
            return False
        self._refresh = True
        self.draw_idle()
        return True

    def _selected_overlay_axes(self):
        """Return the axis facade associated with the selected channel.

        Overlay mode now mirrors matplotlib twinx: every channel has its
        own Y-axis handle, so a selected-channel Y drag only moves that
        channel's ViewBox.
        """
        if self._selected_overlay_channel is None:
            return None
        pair = self._channel_lines.get(self._selected_overlay_channel)
        if pair is None:
            return None
        axis_handle, _line_handle = pair
        return axis_handle

    # ------------------------------------------------------------------
    # T6 — Modifier-aware wheel dispatch.
    # ------------------------------------------------------------------

    def _handle_wheel_dispatch(self, *, delta, modifiers, x_pos, y_pos, view_box=None):
        """Central wheel dispatch routed from ``_ModifierWheelViewBox``.

        Behavior matches canvases.py:_on_scroll (lines 1501-1515):

        - delta > 0 → factor 0.85 (zoom in / pan up)
        - delta < 0 → factor 1/0.85 (zoom out / pan down)
        - Ctrl + wheel  → zoom X about ``x_pos``
        - Shift + wheel → zoom Y about ``y_pos``
        - plain wheel   → pan Y by 10 % of span per step

        Returns ``True`` if consumed, ``False`` otherwise (caller falls
        back to default ViewBox behavior).
        """
        target = self._axis_handle_for_view_box(view_box) or self._primary_xaxis_ax
        if target is None:
            return False
        # Matplotlib uses step = +/-1; here Qt uses delta in units of 120.
        step = 1 if delta > 0 else -1 if delta < 0 else 0
        if step == 0:
            return False
        # Match matplotlib factor (canvases.py:1507).
        factor = 0.85 if step > 0 else 1.0 / 0.85

        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)

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
                lo, hi = target.get_ylim()
                d = (hi - lo) * 0.1 * step
                target.set_ylim(lo + d, hi + d)
        except Exception:
            return False

        self._refresh = True
        self.draw_idle()
        return True

    # ------------------------------------------------------------------
    # T6 — Cursor HTML emission (byte-for-byte parity with
    # canvases.py:_update_single / _update_dual).
    # ------------------------------------------------------------------

    def _emit_single_cursor_html(self, x):
        """Build and emit the single-cursor HTML payload exactly the
        same way canvases.py:_update_single does (lines 1434-1448).

        We do NOT call any pyqtgraph paint helpers here — this is the
        DATA-ONLY emit path the tests use to compare strings. The live
        UI's hover handler will call this plus an overlay-line update.
        """
        from html import escape
        sep = ('<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>')
        parts = [f'<span style="color:#111827;">t={x:.4f}s</span>']
        for ch, (tf, sf, color, u) in self.channel_data.items():
            if len(tf):
                idx = min(np.searchsorted(tf, x), len(sf) - 1)
                unit_s = f" {u}" if u else ""
                name = ch[:18]
                parts.append(
                    f'<span style="color:{color};">'
                    f'{escape(name)}=<b>{sf[idx]:.4g}{escape(unit_s)}</b>'
                    f'</span>'
                )
        self.cursor_info.emit(sep.join(parts))

    def _emit_dual_cursor_html(self):
        """Build and emit cursor_info + dual_cursor_info exactly the same
        way canvases.py:_update_dual does (lines 1450-1499).

        Reuses the module-level ``_format_dual_html`` helper imported
        from ``canvases.py`` so the bytes cannot drift —
        ``codex-plan-spec-literal-evidence`` is satisfied by import,
        not by reimplementation.
        """
        info, dual = [], []
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
            for ch, (tf, sf, color, u) in self.channel_data.items():
                if not len(tf):
                    continue
                m = (tf >= xlo) & (tf <= xhi)
                seg = sf[m]
                if not len(seg):
                    continue
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

    def _cursor_x_to_pixmap_x(self, data_x, pixmap_width):
        """Map a data-space cursor X to pixel-x in the grabbed pixmap.

        Used by the screenshot geometry test to assert the cursor pill
        position is contained in the pixmap bbox. The mapping uses the
        primary axis's current xlim → simple linear interpolation across
        the full pixmap width. (The actual chart area is narrower than
        the pixmap because of left/right axis gutters, but that is
        irrelevant to the bbox-contains gate.)
        """
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

    # ------------------------------------------------------------------
    # T6 — Subplot inside-label placement
    # (mirrors canvases.py:_subplot_ylabels_need_inside_labels).
    # ------------------------------------------------------------------

    def _subplot_ylabels_need_inside_labels(self):
        """Return True when the outer Y axis labels would overlap each
        other or the chart's left edge → callers should flip the labels
        inside the axes.

        Mirrors the rule in canvases.py:_subplot_ylabels_need_inside_labels
        (lines 937-965): the decision is bbox-overlap-driven, NOT a
        fixed pixel/percent offset. Design §0 explicitly corrects the
        earlier draft that proposed a 5-10% offset.

        Pyqtgraph implementation: normal-width stacks with long or
        file-prefixed channel names use inside labels because rotated
        AxisItem labels are taller than the subplot row. Narrow stacks also
        flip inside on the historical 320 px threshold.
        """
        if len(self.axes_list) <= 1:
            return False
        if len(self.axes_list) >= 4:
            return True
        for _handle, name, _color in self._subplot_label_specs:
            text = str(name)
            if len(text) > 32 or (text.startswith("[") and "]" in text):
                return True
        try:
            scene_widget = self._glw.viewport()
            widget_w = max(int(scene_widget.width()), 1)
        except Exception:
            widget_w = 0
        if widget_w == 0:
            return False
        return widget_w < 320

    def _teardown_inside_labels(self):
        """Remove every inside-label scene item and drop its listeners.

        Single owner of inside-label teardown. pyqtgraph's
        GraphicsLayout.clear() only removes items registered via
        addItem() (the PlotItems); our TextItem badges are attached with
        scene().addItem(), so they MUST be removed explicitly here or
        they leak into the scene on every rebuild (ghost badges).
        """
        self._disconnect_inside_label_listeners()
        for item in self._inside_label_items:
            try:
                scene = item.scene()
                if scene is not None:
                    scene.removeItem(item)
            except Exception:
                pass
        self._inside_label_items = []
        self._inside_label_handles = []

    def _disconnect_inside_label_listeners(self):
        for signal, handler in self._inside_label_conns:
            try:
                signal.disconnect(handler)
            except Exception:
                pass
        self._inside_label_conns = []

    def _position_inside_label_item(self, handle, item):
        vb = handle.view_box
        if vb is None:
            return
        try:
            rect = vb.sceneBoundingRect()
            item.setPos(rect.left() + 4.0, rect.top() + 4.0)
        except Exception:
            pass

    def _position_inside_label_items(self):
        for handle, item in zip(self._inside_label_handles, self._inside_label_items):
            self._position_inside_label_item(handle, item)

    def _attach_axis_handle_callbacks(self, handle):
        add_callback = getattr(handle, "add_title_changed_callback", None)
        if callable(add_callback):
            add_callback(self._on_axis_title_changed)

    def _on_axis_title_changed(self, handle, title):
        self._update_inside_label_visibility_for_handle(handle, title)

    def _update_inside_label_visibility_for_handle(self, handle, title=None):
        if title is None:
            try:
                title = handle.get_title()
            except Exception:
                title = ""
        title_visible = bool(str(title).strip())
        for label_handle, item in zip(self._inside_label_handles, self._inside_label_items):
            if label_handle is not handle:
                continue
            try:
                item.setVisible(not title_visible)
                if not title_visible:
                    self._position_inside_label_item(label_handle, item)
            except Exception:
                pass

    def _recheck_subplot_label_placement(self):
        """Place subplot Y labels either OUTSIDE (default AxisItem
        label) or INSIDE (a TextItem at the top-left of each ViewBox).

        Apply once per ``plot_channels`` build; resize-triggered
        re-checks are deferred to T7 because they're not on the parity
        gate for this task.
        """
        # Drop any previously-installed inside-label items.
        self._teardown_inside_labels()

        need_inside = self._subplot_ylabels_need_inside_labels()
        for handle, name, color in self._subplot_label_specs:
            ax_item = handle._ax("left") if hasattr(handle, "_ax") else None
            if need_inside:
                # Hide the outer label by clearing it; install a TextItem
                # at the top-left of the ViewBox.
                if ax_item is not None:
                    try:
                        ax_item.setLabel(text="")
                    except Exception:
                        pass
                prefix, rest = _split_prefixed_label(str(name))
                label_text = f"{prefix}\n{rest}" if prefix is not None else str(name)
                text_item = pg.TextItem(
                    text=f"● {label_text}",
                    color=pg.mkColor(color),
                    anchor=(0, 0),
                    fill=pg.mkBrush(255, 255, 255, 220),
                    border=pg.mkPen(color=color, width=0.8),
                )
                vb = handle.view_box
                if vb is not None:
                    try:
                        scene = vb.scene()
                        if scene is not None:
                            scene.addItem(text_item)
                        else:
                            vb.addItem(text_item, ignoreBounds=True)
                        text_item.setZValue(1000)
                        title_text = ""
                        try:
                            title_text = handle.get_title()
                        except Exception:
                            title_text = ""
                        text_item.setVisible(not bool(title_text))
                        self._position_inside_label_item(handle, text_item)
                        self._inside_label_items.append(text_item)
                        self._inside_label_handles.append(handle)
                        if hasattr(vb, "sigResized"):
                            def _resize_handler(*_args, _handle=handle, _item=text_item):
                                self._position_inside_label_item(_handle, _item)

                            vb.sigResized.connect(_resize_handler)
                            self._inside_label_conns.append((vb.sigResized, _resize_handler))
                    except Exception:
                        pass
            else:
                # Outside: ensure the standard axis label is set.
                if ax_item is not None:
                    try:
                        ax_item.setLabel(text=str(name))
                    except Exception:
                        pass

    def _unify_subplot_left_axis_widths(self):
        """Align every subplot's plot-area left edge to a common x.

        pyqtgraph sizes each PlotItem's left ``AxisItem`` to its own
        tick-label text width. In subplot mode that makes rows with wider
        numeric labels start further right, skewing the shared time grid.
        We measure each left axis's current width and pin all of them to
        the max so the left edges align. Cheap and idempotent: re-running
        with the same widths leaves the max unchanged.

        Only meaningful in subplot mode (``_subplot_label_specs`` is the
        subplot marker); short-circuits otherwise so overlay/single paths
        are untouched.
        """
        if not self._subplot_label_specs:
            return
        left_axes = []
        for handle in self.axes_list:
            ax_item = handle._ax("left") if hasattr(handle, "_ax") else None
            if ax_item is not None:
                left_axes.append(ax_item)
        if len(left_axes) < 2:
            return
        # Release any prior pin so width() reflects the CURRENT tick-label
        # text width before we re-measure. Without this, a previous pin
        # (e.g. from an earlier density level) would make every axis report
        # the same stale width and the unification would never re-tighten.
        for ax_item in left_axes:
            try:
                ax_item.setWidth(None)
            except Exception:
                pass
        max_w = 0.0
        for ax_item in left_axes:
            try:
                w = float(ax_item.width())
            except Exception:
                continue
            if w > max_w:
                max_w = w
        if max_w <= 0.0:
            return
        for ax_item in left_axes:
            try:
                ax_item.setWidth(max_w)
            except Exception:
                pass

    def resizeEvent(self, event):
        """Re-check subplot inside-label placement on resize.

        Mirrors canvases.py's resize-driven inside/outside flip without
        adding a new debounced QTimer (the existing `_refresh_timer` is
        for envelope refresh only). The recheck is cheap: we just call
        ``_recheck_subplot_label_placement`` which short-circuits when
        ``_subplot_label_specs`` is empty.
        """
        try:
            super().resizeEvent(event)
        finally:
            try:
                if self._subplot_label_specs:
                    self._recheck_subplot_label_placement()
                    # Resize changes label widths; re-pin so left edges
                    # stay aligned across rows.
                    self._unify_subplot_left_axis_widths()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Screenshot grab (compat with chart_stack._copy_card_image).
    # ------------------------------------------------------------------

    def grab_pixmap(self) -> QPixmap:
        """Return a ``QPixmap`` snapshot of the canvas.

        Order of attempts:
        1. ``QWidget.grab()`` on the outer widget (covers GraphicsLayoutWidget
           + any sibling overlays MainWindow may add later).
        2. Direct ``self._glw.grab()`` if the outer grab returned null.
        3. A 1×1 transparent fallback pixmap if both fail.

        Step 3 is the degenerate-rect fallback the
        ``2026-04-25-tightbbox-survives-offscreen-qt`` lesson prescribes:
        callers MUST check ``pix.isNull()`` rather than assuming a
        well-formed image.
        """
        try:
            pix = self.grab()
            if pix is not None and not pix.isNull() and pix.width() > 0 and pix.height() > 0:
                return pix
        except Exception:
            pass
        try:
            pix = self._glw.grab()
            if pix is not None and not pix.isNull() and pix.width() > 0 and pix.height() > 0:
                return pix
        except Exception:
            pass
        # Final fallback: a 1×1 transparent pixmap. Tests gate on
        # geometry, not pixels, so this is acceptable when offscreen Qt
        # cannot realize the widget at all.
        fallback = QPixmap(1, 1)
        fallback.fill(Qt.transparent)
        return fallback


__all__ = ["TimeDomainCanvasPG", "_quantize_range_key"]
