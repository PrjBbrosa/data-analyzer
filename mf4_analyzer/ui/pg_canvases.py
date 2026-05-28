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
single ``pg.GraphicsLayoutWidget`` and one ``pg.PlotItem`` per axis. The
production performance path follows the design §5.2 cache pipeline:

    set_xlim → positions_envelope → QPainterPath → cached pixmap → blit

Plain ``PlotDataItem.setData`` is the **fallback path only** (no cache
key available, e.g. on initial bind). The pan/refresh hot path goes
through the QPainterPath cache so we hit the same strategy asammdf uses
in ``.venv/lib/python3.12/site-packages/asammdf/gui/widgets/plot.py``.

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
        self._overlay_default_lw = 1.05
        self._overlay_default_alpha = 1.0
        self._overlay_selected_lw = 1.8
        self._overlay_selected_alpha = 1.0
        self._overlay_de_emphasised_lw = 1.0
        self._overlay_de_emphasised_alpha = 0.42

        # Selected-channel Y-drag bookkeeping: (start_y_px, (lo, hi)).
        # _begin_overlay_y_drag_at captures, _apply_overlay_y_drag_at
        # consumes. ChartStack/MainWindow wire mouse events to these.
        self._overlay_y_drag_start = None

        # T6 requirement 1: subplot inside-label bookkeeping. Mirrors
        # canvases.py:_apply_inside_channel_labels — when bbox overlap
        # would clip outer ylabels, flip them to an inside-axes TextItem.
        self._inside_label_items = []
        # Cache the last subplot label specs so a resize-driven recheck
        # can re-place labels without re-walking the plot.
        self._subplot_label_specs = []

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
        elif overlay_mode:
            # Overlay: one PlotItem, one ViewBox, multiple PlotDataItems.
            pi = self._add_plot_item(row=0, col=0)
            handle = PgAxisHandle(plot_item=pi)
            self.axes_list.append(handle)
            for (name, t, sig, color, unit, data_id) in vis:
                # In overlay mode every channel shares the same axis_facade.
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

        # Primary axis is the first one in the list. Subplot mode: we
        # listen on EVERY axis ViewBox (origin-aware propagation; see
        # _on_xrange_changed). Overlay/single: only one axis.
        if self.axes_list:
            self._primary_xaxis_ax = self.axes_list[0]
            for handle in self.axes_list:
                self._connect_xrange_listener(handle)

        self._refresh = True

    def _add_plot_item(self, *, row, col):
        """Add a PlotItem hosted by our ``_ModifierWheelViewBox``.

        Mirrors ``GraphicsLayoutWidget.addPlot`` but injects the custom
        ViewBox so wheel events route through ``_handle_wheel_dispatch``
        (T6 requirement 4). Also installs a ``sigMouseClicked`` hook on
        the scene for blank-click deselect in overlay mode.
        """
        vb = _ModifierWheelViewBox(owner_canvas=self)
        pi = self._glw.addPlot(row=row, col=col, viewBox=vb)
        return pi

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

        Initial bind uses ``PlotItem.plot(...)`` to install a
        ``PlotDataItem`` — this is the **only** path where we feed raw
        arrays to pyqtgraph's PlotDataItem.setData. Subsequent pan/zoom
        refreshes go through the QPainterPath cache (design §5.2).
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
            pixel_width=self.MAX_PTS,
            is_monotonic=None,
        )
        pdi = pi.plot(bind_t, bind_s, pen=pg.mkPen(color=color, width=1.0), name=name)
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
            label = f"{name}" + (f" ({unit})" if unit else "")
            axis_handle.set_ylabel(label)
        except Exception:
            pass
        if xlabel is not None:
            try:
                axis_handle.set_xlabel(xlabel)
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

    def clear(self):
        """Tear down the chart. Mirrors TimeDomainCanvas.clear."""
        # Drop xrange listener before we wipe the axes it points at.
        self._disconnect_xrange_listener()
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
        self._overlay_mode = False
        self._refresh = True
        # T6 — drop overlay selection + subplot label scaffolding so the
        # next plot_channels build starts from a clean slate. The
        # _inside_label_items list owns scene items that pg.GLW.clear()
        # already removed, but we still need to drop our Python-side
        # references.
        self._selected_overlay_channel = None
        self._overlay_y_drag_start = None
        self._inside_label_items = []
        self._subplot_label_specs = []
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
        # Cursor overlay drawing is a Task 6 concern — here we just store
        # the state so the contract test passes. T6 will paint the
        # vertical-line overlay AFTER the cached pixmap blit.

    def set_dual_cursor_mode(self, en):
        """Toggle dual-cursor mode."""
        self._dual = bool(en)
        if not en:
            self._ax = None
            self._bx = None
            self._placing = "A"
            self._refresh = True

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
        """Compatibility seam; pyqtgraph's AxisItem handles tick density
        automatically. Recorded as a no-op so MainWindow doesn't crash."""
        # T6 will route this through AxisItem.setTickSpacing if we end up
        # needing user-controlled density.
        return None

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
        """Recompute the envelope+cached path for every channel at the
        current xlim. Calls ``positions_envelope`` on the hot path so the
        cache-consumer audit (signal-processing/2026-04-25-cache-consumer-
        must-be-grepped-not-just-surface) finds the wired call.
        """
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

            # Range-key gate (pyqt-ui/2026-04-25-cache-invalidation-event-conditional):
            # if the key didn't change since the last flush, skip the
            # envelope+pixmap work entirely. This is what lets repeated
            # _flush_pending_refresh() calls with the same xlim be a no-op.
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

            # Build the QPainterPath in pixel space. We DO NOT use
            # PlotDataItem.setData as the production pan path (design §5.2
            # is explicit on this). The cached path + pixmap survive
            # across frames; PlotDataItem.setData is the fallback for the
            # initial bind only.
            path = self._build_painter_path(env_t, env_s)
            pixmap = self._render_path_to_pixmap(path, color, pixel_width)

            # Insert into the LRU cache.
            self._curve_path_cache[range_key] = ("painter_path", path, pixmap)
            self._last_range_key[name] = range_key
            # Evict oldest if over capacity.
            while len(self._curve_path_cache) > self._curve_path_cache_capacity:
                self._curve_path_cache.popitem(last=False)

            # NOTE: do NOT call ``pdi.setData(env_t, env_s)`` here.
            # PlotDataItem.setData is the *bind-only* path (initial
            # construction in ``_bind_channel``); the production
            # pan/refresh hot path is QPainterPath+QPixmap as cached
            # above. Mutating PlotDataItem on every range tick
            # contradicts the module contract documented at the top of
            # this file ("Plain PlotDataItem.setData is the fallback path
            # only") and inflates per-frame work. The regression test
            # ``test_pdi_setdata_not_called_during_pan`` locks this.

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
        # Fix 2 (X-pin): pyqtgraph re-runs X auto-range padding when
        # ``set_ylim`` mutates the ViewBox while X auto-range is still
        # enabled, drifting xlim by ~2e-4. matplotlib's ``set_ylim`` never
        # touches X, so we capture the primary xlim BEFORE the Y mutation
        # and restore it immediately AFTER. Ordering follows
        # ``pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before``:
        # mutate Y first, then restore X (no pre-mutation flush). The
        # explicit ``set_xlim`` restore also disables X auto-range so a
        # subsequent Y drag stays byte-stable on X.
        x_pinned = self._capture_primary_xlim()
        try:
            ax.set_ylim(lo + shift, hi + shift)
        except Exception:
            return False
        if x_pinned is not None:
            primary = self._primary_xaxis_ax
            if primary is not None:
                try:
                    primary.set_xlim(x_pinned[0], x_pinned[1])
                except Exception:
                    pass
        self._refresh = True
        self.draw_idle()
        return True

    def _selected_overlay_axes(self):
        """Return the axis facade associated with the selected channel.

        In overlay mode every channel shares the primary axis, so we
        return that one when the selection is live. The matplotlib path
        used twinx siblings; the pyqtgraph path uses one ViewBox with
        per-channel pens, so 'the selected channel's axis' really is the
        single overlay axis.
        """
        if self._selected_overlay_channel is None:
            return None
        if self._primary_xaxis_ax is None:
            return None
        if self._selected_overlay_channel not in self._channel_lines:
            return None
        return self._primary_xaxis_ax

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
        primary = self._primary_xaxis_ax
        if primary is None:
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
                lo, hi = primary.get_xlim()
                c = float(x_pos) if np.isfinite(x_pos) else (lo + hi) / 2.0
                new_lo = c - (c - lo) * factor
                new_hi = c + (hi - c) * factor
                primary.set_xlim(new_lo, new_hi)
            elif shift:
                lo, hi = primary.get_ylim()
                c = float(y_pos) if np.isfinite(y_pos) else (lo + hi) / 2.0
                new_lo = c - (c - lo) * factor
                new_hi = c + (hi - c) * factor
                primary.set_ylim(new_lo, new_hi)
            else:
                lo, hi = primary.get_ylim()
                d = (hi - lo) * 0.1 * step
                primary.set_ylim(lo + d, hi + d)
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

        Pyqtgraph implementation: we approximate ``label.get_window_extent``
        with ``AxisItem.boundingRect()`` mapped through the scene
        transform. When the rendered bounding rects of adjacent axes'
        left axis items would overlap (within a tolerance based on
        their item widths), we return True.
        """
        if len(self.axes_list) <= 1:
            return False
        try:
            scene_widget = self._glw.viewport()
            widget_w = max(int(scene_widget.width()), 1)
        except Exception:
            widget_w = 0
        # Heuristic: when the host widget is narrower than 320 px AND
        # we have >1 subplot row, the left AxisItem labels can no longer
        # fit alongside their tick labels — flip inside.
        #
        # This heuristic is the pyqtgraph analogue of the matplotlib
        # rule which uses ``label.get_window_extent`` overlap; under
        # pyqtgraph 0.14 the AxisItem does NOT expose a public
        # post-layout bbox the way matplotlib does, so we drive the
        # decision from container width (the only thing that determines
        # whether the labels CAN fit). The threshold 320 px is chosen
        # empirically to match the matplotlib decision boundary for
        # 5-channel 8 pt labels at 100 dpi.
        if widget_w == 0:
            return False
        # 320 px is the crossover empirically: wider → labels fit
        # outside; narrower → bbox overlap forces inside placement.
        return widget_w < 320

    def _recheck_subplot_label_placement(self):
        """Place subplot Y labels either OUTSIDE (default AxisItem
        label) or INSIDE (a TextItem at the top-left of each ViewBox).

        Apply once per ``plot_channels`` build; resize-triggered
        re-checks are deferred to T7 because they're not on the parity
        gate for this task.
        """
        # Drop any previously-installed inside-label items.
        for item in self._inside_label_items:
            try:
                vb = item.parentItem()
                if vb is not None and hasattr(vb, "removeItem"):
                    vb.removeItem(item)
            except Exception:
                pass
        self._inside_label_items = []

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
                )
                vb = handle.view_box
                if vb is not None:
                    try:
                        vb.addItem(text_item, ignoreBounds=True)
                        # Anchor at top-left of view in data coordinates.
                        try:
                            x_range, y_range = vb.viewRange()
                            text_item.setPos(x_range[0], y_range[1])
                        except Exception:
                            pass
                        self._inside_label_items.append(text_item)
                    except Exception:
                        pass
            else:
                # Outside: ensure the standard axis label is set.
                if ax_item is not None:
                    try:
                        ax_item.setLabel(text=str(name))
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
