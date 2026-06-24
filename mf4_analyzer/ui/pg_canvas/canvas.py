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

from collections import OrderedDict
from typing import Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import (
    QEvent,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QPainterPath,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.signal._envelope_cutils import (  # noqa: F401
    positions_envelope,  # re-exported via the pg_canvases shim + renderer monkeypatch seam
)
from mf4_analyzer.ui._axis_handle import (
    PG_AXIS_NEUTRAL_COLOR,
    PG_AXIS_NEUTRAL_WIDTH,
    PgAxisHandle,
)
from mf4_analyzer.ui.plot_helpers import _split_prefixed_label  # noqa: F401
from mf4_analyzer.signal.envelope import build_envelope  # noqa: F401
from mf4_analyzer.ui.pg_canvas.context_menu import (
    _localize_pg_context_actions,
    _localize_pg_context_menu,
    redesign_pg_context_menu,
)
from mf4_analyzer.ui.pg_canvas.fonts import (
    _apply_pg_axis_font,
    _apply_pg_text_item_font,
)
from mf4_analyzer.ui.pg_canvas.annotations import AnnotationManager
from mf4_analyzer.ui.pg_canvas.cursor import CursorController
from mf4_analyzer.ui.pg_canvas.ticks_math import _quantize_range_key, _frame_to_nice
from mf4_analyzer.ui.pg_canvas.tick_density import TickDensityController
from mf4_analyzer.ui.pg_canvas.viewbox import _ModifierWheelViewBox  # noqa: F401
from mf4_analyzer.ui.pg_canvas import renderer as _renderer
from mf4_analyzer.ui.pg_canvas.overlay_axes import OverlayAxisManager
from mf4_analyzer.ui.pg_canvas.quality import QualityManager
from mf4_analyzer.ui.pg_canvas.renderer import (  # noqa: F401
    Renderer,
    _HIDPI_COPY_SCALE,
    _HIDPI_MAX_WIDTH,
    _capped_hidpi_scale,
)
from mf4_analyzer.ui.pg_canvas._shared import (  # noqa: F401
    _ChannelKeyDict,
    _hide_native_auto_button,
    _subplot_ylabel_text,
    _view_state_channel_key,
    show_major_grid_left_bottom_only,
)


# Idle-AA density budget (Fix C, 2026-05-31 overlay-aa-interaction-fixes;
# RECALIBRATED 2026-05-31 against the end-to-end grab()-repaint-frame
# harness — superseding the original 12000/16000, which never gated the
# measured-slow overlay).
#
# TWO BUDGETS, because subplot and overlay have fundamentally different
# per-frame economics (measured offscreen-raster grab() of the real
# GraphicsLayoutWidget; the AA-on minus AA-off DELTA isolates the actual
# antialiasing cost from the offscreen layout overhead, and is linear in
# the per-frame drawn-point SUM):
#
#   overlay sum  4000 → AA delta +10.2 ms   (≈ the ~10 ms target)
#   overlay sum  6000 → AA delta +16.6 ms   (2 curves, still affordable)
#   overlay sum  9000 → AA delta +31.3 ms   (3 curves, too slow → gate OFF)
#   overlay sum 12000 → AA delta +48.2 ms
#   overlay sum 15000 → AA delta +69.0 ms   (5 curves, the reported-slow case)
#
# OVERLAY metric = SUM of drawn points across ALL curves: overlay's aux
# ViewBoxes fully overlap at one full-plot rect, so a single draw_idle /
# _glw.update re-rasterizes every overlaid curve as ONE region. (Per-VB
# grouping under-counted overlay because each overlay curve lives on its
# OWN aux ViewBox — distinct objects, overlapping geometry — so the MAX
# saw only one curve. See the DeviceCoordinateCache lesson.) The overlay
# budget is tight so dense overlays (≥3 curves ≈ sum ≥ 9000, > ~30 ms)
# fall to AA-off; a light 2-curve overlay (sum ≤ 6000) still gets AA.
_AA_OVERLAY_SEGMENT_ON = 5000
_AA_OVERLAY_SEGMENT_OFF = 7000
_OVERLAY_GRID_ALPHA = 0.28        # 与 X 轴格线保持一致的透明度
#
# SUBPLOT/SINGLE metric = MAX over rows of that row's drawn points: the
# rows are disjoint device rectangles, AND subplot curves carry a
# DeviceCoordinateCache (Fix D, subplot-only) so an AA-on cached frame is
# ~0.3–0.9 ms at ANY width — measured 5×6000 subplot AA-on+cache = 0.86 ms
# vs 25.3 ms uncached. The subplot budget is therefore GENEROUS so a single
# maximized / 4K curve always qualifies: a 4K-wide single curve emits a
# ~7700-pt envelope (positions_envelope ≈ 2× plot-area pixel width), so OFF
# must sit well above that or issue 1 (AA off after maximize) regresses.
_AA_SUBPLOT_SEGMENT_ON = 10000
_AA_SUBPLOT_SEGMENT_OFF = 12000
#
# Back-compat aliases (legacy single-budget names; the instance still
# exposes _AA_SEGMENT_ON/_OFF, defaulted to the subplot pair, so existing
# tests/tools that poke the old attribute names keep working).
_AA_SEGMENT_ON = _AA_SUBPLOT_SEGMENT_ON
_AA_SEGMENT_OFF = _AA_SUBPLOT_SEGMENT_OFF


_OVERLAY_AXIS_LABEL_MIN_CHARS = 12
_OVERLAY_AXIS_LABEL_FALLBACK_CHARS = 22
_OVERLAY_AXIS_LABEL_VERTICAL_PADDING_PX = 32.0


class TimeDomainCanvasPG(QWidget):
    """Pyqtgraph-backed drop-in for ``canvases.TimeDomainCanvas``."""

    # Signal contract (design §3.1 — frozen by W0 contract test).
    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)
    dual_cursor_rows = pyqtSignal(object)  # emits raw dual list for mini pill
    span_selected = pyqtSignal(float, float)
    overlay_channel_selected = pyqtSignal(object)
    overlay_y_needs_selection = pyqtSignal()
    context_menu_requested = pyqtSignal()
    xrange_changed = pyqtSignal(float, float)
    visible_range_changed = pyqtSignal()
    quality_status_changed = pyqtSignal(object)

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
        # Enlarge the drawing area: pyqtgraph's central layout defaults to a
        # 9px outer gutter + 8px inter-row spacing, which is wasted chrome.
        # Axis tick text lives in each PlotItem's own reserved band (not this
        # outer margin), so tightening it grows the plot without clipping
        # labels. Set once here — it survives plot_channels rebuilds.
        self._glw.ci.setContentsMargins(2, 2, 2, 2)
        self._glw.ci.setSpacing(2)
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
        # IDENTITY is the composite (data_id, name) key (multi-file same-name
        # root fix): _ChannelKeyDict stores per (fid, name) so two files with an
        # identically-truncated [short_name] prefix never overwrite each other,
        # while bare-name reads (canvas._channel_lines["torque"]) and display-
        # name iteration still work for legacy / test call sites.
        self._channel_lines = _ChannelKeyDict()
        # View-state range restore needs a non-colliding key when two files
        # expose the same display channel name. Keep this separate so legacy
        # hover/selection/options paths can continue using _channel_lines.
        self._channel_view_state_lines = {}
        # channel_data is the raw post-range-filter dict — STAYS RAW.
        # get_statistics reads this; the envelope cache never feeds it. Same
        # composite (fid, name) identity as _channel_lines so the two iterate
        # in lock-step and never collide across same-named files.
        self.channel_data = _ChannelKeyDict()
        # Parallel data_id dict (kept separate per design §4.2).
        self._channel_data_id = _ChannelKeyDict()
        # Composite keys of display-companion curves (e.g. filter overlays)
        # bound onto a source channel's axis. Subset of _channel_lines keys;
        # lets the stats / emphasis paths exclude them from real-channel logic.
        # Keyed by the composite (fid, name) key so a companion never collides
        # with a same-named companion from another file.
        self._companion_names = set()
        # Per-channel monotonicity cache, populated once per
        # plot_channels build. Used in _refresh_visible_data so the hot
        # path skips np.diff(t).
        self._channel_is_monotonic = _ChannelKeyDict()
        # The "primary" axis facade — its sigXRangeChanged drives the
        # viewport-aware envelope refresh. Set after plot_channels.
        self._primary_xaxis_ax = None

        # --- viewport refresh state ------------------------------------
        self._refresh = True

        # --- viewport refresh wiring ------------------------------------
        # 40 ms ≈ 25 FPS coalesce window, matching TimeDomainCanvas.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)
        self._refresh_timer.timeout.connect(self._refresh_visible_data)
        self._refresh_pending = False
        # Density budget for idle AA (Fix C, 2026-05-31; RECALIBRATED against
        # the end-to-end grab() repaint-frame harness). Two budgets, branched
        # on _overlay_mode in _idle_aa_density_ok:
        #   * OVERLAY: metric = SUM of drawn points across ALL curves (they
        #     overlap at one full-plot rect → repaint as one region). Tight
        #     budget so a dense ≥3-curve overlay (sum ≥ 9000, measured > ~30 ms
        #     AA-on) gates OFF while a light 2-curve overlay (sum ≤ 6000) keeps
        #     AA. This is the UNCACHED path the gate must govern.
        #   * SUBPLOT/SINGLE: metric = MAX over rows of that row's drawn points
        #     (disjoint rects). Subplot curves carry a DeviceCoordinateCache
        #     (Fix D, subplot-only) so an AA-on cached frame is ~0.3–0.9 ms at
        #     ANY width; the budget is generous so a single maximized / 4K
        #     curve (~7700-pt envelope) always gets AA (fixes issue 1).
        # ON/OFF are real-hardware tunables; module defaults above carry the
        # measured frame-ms justification. Legacy _AA_SEGMENT_ON/_OFF are kept
        # as aliases of the subplot pair so existing tools/tests still work.
        self._AA_OVERLAY_SEGMENT_ON = _AA_OVERLAY_SEGMENT_ON
        self._AA_OVERLAY_SEGMENT_OFF = _AA_OVERLAY_SEGMENT_OFF
        self._AA_SUBPLOT_SEGMENT_ON = _AA_SUBPLOT_SEGMENT_ON
        self._AA_SUBPLOT_SEGMENT_OFF = _AA_SUBPLOT_SEGMENT_OFF
        self._AA_SEGMENT_ON = _AA_SEGMENT_ON
        self._AA_SEGMENT_OFF = _AA_SEGMENT_OFF
        # Cold-start dead-band fix: until the first decision (and after a
        # resize / rebuild reset) the density gate seeds via the OFF
        # threshold instead of inheriting the pessimistic initial False, so
        # a single wide curve no longer sticks AA-off forever.
        # --- resize re-arm debounce (Fix C) -----------------------------
        # A 40 ms single-shot (mirrors _refresh_timer's coalesce window)
        # so dragging the window border does not recompute the envelope on
        # every intermediate size; it fires once the resize settles.
        self._resize_settle_timer = QTimer(self)
        self._resize_settle_timer.setSingleShot(True)
        self._resize_settle_timer.setInterval(40)
        self._resize_settle_timer.timeout.connect(self._on_resize_settled)
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
        # Keyed by the COMPOSITE (fid, name) key (NOT the display name) so two
        # same-named channels from different files keep independent viewport
        # caches — a per-name key would let one channel's cache-hit suppress the
        # other's refresh (pyqt-ui/2026-06-11-cache-key-stability-id-reuse-and-
        # param-roundtrip). Bare-name reads still resolve for legacy/test code.
        self._last_range_key = _ChannelKeyDict()
        # Per-channel Y-overflow wall state (renderer._refresh_visible_data):
        # remembers whether THIS line was last flushed in the 满高竖线墙 regime so
        # a range-key cache-HIT (no-op refresh) can keep the frame wall flag set
        # — AA must stay off until the user widens Y, not until the next real
        # recompute. Cleared alongside _last_range_key on rebuild/invalidate.
        # Composite (fid, name) keyed for the same cross-file non-collision
        # reason as _last_range_key.
        self._line_wall_state = _ChannelKeyDict()
        self._last_refresh_signature = None
        self._monotonic_fingerprint_cache: dict = {}

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
        self._install_viewport_event_filter()

        # --- T6: overlay-mode selection + per-channel emphasis ----------
        # Mirrors canvases.py:_apply_overlay_selection_style (lw 1.0 / 1.8;
        # alpha 0.42 / 1.0). Stored per channel so test/UI can probe.
        self._overlay_mode = False
        # Number of axis-owning subplot channels that are HIGH-DENSITY (the
        # dense-stack bucket cap engages at >= 2). Recomputed each
        # plot_channels; 0 in overlay/single/low-density layouts.
        self._subplot_dense_count = 0
        # Y-overflow wall guard (renderer._refresh_visible_data). Set True for
        # the current frame when ANY line's window data amplitude span overflows
        # its Y view window by more than _WALL_OVERFLOW_RATIO_K (the dense
        # narrow-Y "满高竖线墙" regime). While active the idle-AA gate keeps
        # antialiasing OFF so the expensive AA compositing never re-arms over a
        # raster-fill wall. Reset to False on every refresh that finds no wall.
        self._y_overflow_wall_active = False
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

        # Bug 3: post-rebuild callbacks. plot_channels builds NEW ViewBoxes
        # (default PanMode), so any owner that pins a mouse mode (the
        # toolbar's pan/zoom state) must re-apply it to the fresh ViewBoxes.
        # Private (not a W0 signal) so the contract surface is unchanged;
        # _ChartCard registers toolbar.apply_current_mouse_mode here.
        self._replot_callbacks: list = []

        # Design D: shared mouse-mode controller (single source of truth). The
        # right-click 鼠标操作 submenu and the top toolbar BOTH drive the same
        # object so their pan/box-select state can never disagree. The toolbar
        # registers itself via register_mouse_mode_controller; until then this
        # stays None and the menu items are inert (no parallel mode path).
        self._mouse_mode_controller = None

        # Decomposition collaborators. Most keep only a canvas back-reference;
        # Phase 4.2 starts moving cohesive state into the owning collaborator.
        self._cursor = CursorController(self)
        self._annotations = AnnotationManager(self)
        self._tick_density_controller = TickDensityController(self)
        self._overlay_axes = OverlayAxisManager(self)
        self._quality = QualityManager(self)
        self._renderer = Renderer(self)

    # ------------------------------------------------------------------
    # Public surface (signal/method names frozen by W0 contract tests).
    # ------------------------------------------------------------------

    def plot_channels(
        self, ch_list, mode="overlay", xlabel="Time (s)", defer_first_frame=False
    ):
        """Build the chart for ``ch_list``.

        Row shape (legacy or preferred):

        - ``(name, visible, t, sig, color, unit)`` — legacy
        - ``(name, visible, t, sig, color, unit, data_id)`` — preferred

        ``data_id`` is required for the curve-layer cache to key entries
        per-source-file; rows without it route through the slow path.

        ``defer_first_frame`` skips the full-range bind envelope and binds
        empty stubs. Only use it when an xlim restore + flush follows the
        rebuild; plain plot_channels needs the bind envelope as its first
        frame because data-union x seeding blocks range signals.
        """
        self.disable_interactive_quality()
        self.clear()

        # Split primary channels from display companions. A companion row
        # carries an 8th ``meta`` dict with ``companion_of`` set to the
        # source channel's name (and ``dash=True``); the canvas overlays it
        # on the SOURCE channel's axis/row rather than allocating a fresh
        # subplot row. Legacy 6/7-tuple rows have no meta → always primary.
        #
        # AXIS-OWNERSHIP RULE (subplot/single/overlay alike): a subplot row /
        # axis belongs to the CHANNEL, not to the channel's original line. So
        # a channel gets an axis whenever EITHER the original is visible
        # ("显示原始") OR it has a visible companion ("显示滤波后" on the
        # dashed filtered trace). Without this, "显示原始 off + 显示滤波后 on"
        # skipped the (invisible) original → its axis was never built → the
        # companion had no source axis to bind onto → the whole chart went
        # blank. The original line is ALWAYS added when its channel keeps an
        # axis, but hidden via ``setVisible`` per its own visible flag so the
        # dashed companion can still anchor on the same ViewBox.
        primaries = []
        companions = []
        companion_visible_by_source = {}
        for row in ch_list:
            if len(row) >= 8 and isinstance(row[7], dict):
                name, visible, t, sig, color, unit, data_id, meta = row[:8]
            elif len(row) >= 7:
                name, visible, t, sig, color, unit, data_id = row[:7]
                meta = None
            else:
                name, visible, t, sig, color, unit = row[:6]
                data_id = None
                meta = None
            companion_of = meta.get("companion_of") if meta else None
            if companion_of is not None:
                cvis = bool(visible)
                companions.append(
                    (name, cvis, t, sig, color, unit, data_id,
                     companion_of, bool(meta.get("dash", True)))
                )
                if cvis:
                    companion_visible_by_source[companion_of] = True
                continue
            primaries.append(
                (name, bool(visible), t, sig, color, unit, data_id)
            )

        # ``vis`` = primaries that own an axis this rebuild = original visible
        # OR has a visible companion. Carry the original's own visibility as a
        # 7th element so we can ``setVisible(False)`` it after bind while still
        # building its axis/row for the companion to anchor onto.
        vis = [
            (name, t, sig, color, unit, data_id, p_visible)
            for (name, p_visible, t, sig, color, unit, data_id) in primaries
            if p_visible or companion_visible_by_source.get(name)
        ]

        if not vis:
            # No channel owns an axis (every original hidden AND no visible
            # companion) → nothing to draw and nothing to anchor companions to.
            return

        overlay_mode = (mode == "overlay" and len(vis) >= 2)
        subplot_mode = (mode == "subplot" and len(vis) > 1)
        self._overlay_mode = overlay_mode  # parity attr name with TimeDomainCanvas

        # Subplot dense-stack bucket cap (满高竖线墙): count how many of the
        # axis-owning channels are HIGH-DENSITY (source_len / plot_width above
        # the dense threshold). When >= 2 such rows stack, the initial-bind
        # envelope (and every later refresh) caps each dense row's bucket count
        # so re-showing the hidden originals doesn't repaint N full-height
        # vertical-stroke walls at once. Computed up-front so each bind shares
        # the same per-row budget. Single/low-density rows keep full resolution.
        self._subplot_dense_count = 0
        if subplot_mode:
            probe_w = self._overlay_axes._initial_bind_pixel_width()
            if probe_w and probe_w > 0:
                for _v in vis:
                    try:
                        if len(_v[2]) / probe_w >= _renderer._SUBPLOT_DENSE_DECIMATION:
                            self._subplot_dense_count += 1
                    except Exception:
                        pass

        if subplot_mode:
            for i, (name, t, sig, color, unit, data_id, p_visible) in enumerate(vis):
                pi = self._add_plot_item(row=i, col=0)
                handle = PgAxisHandle(plot_item=pi, owner_canvas=self)
                self.axes_list.append(handle)
                self._overlay_axes._bind_channel(
                    handle, name, t, sig, color, unit, data_id,
                    xlabel=xlabel if i == len(vis) - 1 else None,
                    skip_envelope=defer_first_frame,
                )
                self._set_primary_line_visible(name, p_visible)
                self._overlay_axes._configure_subplot_bottom_axis(
                    handle,
                    is_bottom=(i == len(vis) - 1),
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
            # vis[i] is (name, t, sig, color, unit, data_id); color idx3, unit idx4.
            self._subplot_label_specs = [
                (self.axes_list[i], vis[i][0], vis[i][3], vis[i][4])
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
            self._x_master_handle = PgAxisHandle(
                plot_item=pi,
                owner_canvas=self,
                allow_y_grid=False,
            )
            # Channel 1 → dedicated aux ViewBox bound to the LEFT axis.
            first_handle = self._overlay_axes._add_overlay_axis_handle(pi, 0)
            self.axes_list.append(first_handle)
            self._overlay_axes._bind_channel(
                first_handle,
                *vis[0][:6],
                xlabel=xlabel,
                skip_envelope=defer_first_frame,
            )
            self._set_primary_line_visible(vis[0][0], vis[0][6])
            # Channels 2..N → dedicated aux ViewBoxes bound to right axes.
            for idx, (name, t, sig, color, unit, data_id, p_visible) in enumerate(
                vis[1:], start=1
            ):
                handle = self._overlay_axes._add_overlay_axis_handle(pi, idx)
                self.axes_list.append(handle)
                self._overlay_axes._bind_channel(
                    handle,
                    name,
                    t,
                    sig,
                    color,
                    unit,
                    data_id,
                    xlabel=xlabel,
                    skip_envelope=defer_first_frame,
                )
                self._set_primary_line_visible(name, p_visible)
            # Apply default emphasis state (no selection).
            self._overlay_axes._apply_overlay_emphasis()
            # Grid: in overlay the built-in left + right axes are linked to
            # DIFFERENT per-channel ViewBoxes (independent Y ranges) and each
            # drew its own horizontal grid at its OWN ticks in its OWN channel
            # pen color (see _apply_pg_axis_style) → multiple non-coincident,
            # multi-colored Y grids. There is no canonical Y range to grid, so
            # show ONLY the single shared X grid (the bottom axis) and disable
            # the Y grid. subplot/single keep both grids (one Y range each).
            # Idempotent: re-running on rebuild just re-asserts x-only.
            try:
                pi.showGrid(x=True, y=False, alpha=0.28)
            except Exception:
                pass
            self._overlay_axes._build_overlay_y_grid()
        else:
            # Single channel.
            pi = self._add_plot_item(row=0, col=0)
            handle = PgAxisHandle(plot_item=pi, owner_canvas=self)
            self.axes_list.append(handle)
            name, t, sig, color, unit, data_id, p_visible = vis[0]
            self._overlay_axes._bind_channel(
                handle,
                name,
                t,
                sig,
                color,
                unit,
                data_id,
                xlabel=xlabel,
                skip_envelope=defer_first_frame,
            )
            self._set_primary_line_visible(name, p_visible)

        # Bind display companions (e.g. filter overlays) onto their source
        # channel's axis/row — NO new subplot row/axis is allocated, so the
        # subplot count stays equal to the primary-channel count. The dashed
        # pen distinguishes the overlay from its solid source. Companions are
        # registered in _channel_lines/channel_data under their own name so
        # the viewport envelope refresh (pan/zoom) and grab export pick them
        # up like any other curve.
        for (cname, cvisible, ct, csig, ccolor, cunit, cdata_id,
             companion_of, dash) in companions:
            # Resolve the source by its COMPOSITE (data_id, name) key so a
            # companion always anchors onto the SAME file's source channel, even
            # when another file exposes an identically-named source.
            source_key = _view_state_channel_key(cdata_id, companion_of)
            source_pair = self._overlay_axes._channel_lines.get(source_key)
            if source_pair is None:
                # Fall back to a bare-name lookup for legacy rows that carry no
                # data_id (companion_of resolves the unique entry when present).
                source_pair = self._overlay_axes._channel_lines.get(companion_of)
            if source_pair is None:
                # Source channel not visible/bound → skip (keeps invariant
                # that companions never spawn their own row).
                continue
            source_handle = source_pair[0]
            self._overlay_axes._bind_companion(
                source_handle,
                cname,
                ct,
                csig,
                ccolor,
                cunit,
                cdata_id,
                visible=cvisible,
                dash=dash,
                skip_envelope=defer_first_frame,
            )

        # 滤波子图 Y 自适应卡顿真因修复: a dashed filtered companion (e.g.
        # 低通 100 Hz, ±0.02) shares its source channel's ViewBox. With Y
        # auto-range left ON, pyqtgraph can recompute the shared axis from the
        # TINY companion mid-build (a setData on the small curve fires an
        # auto-range pass before the primary's contribution settles), framing
        # the axis to ±0.04 for one frame. The LARGE original (±2~6) then gets
        # rasterized inside that narrow Y window as a full-height vertical-
        # stroke wall (满屏竖线墙) — the most expensive raster regime — for
        # every dense channel, costing 十几秒 before Y re-settles to the
        # primary range. Fix: pin every companion-carrying axis's Y EXPLICITLY
        # to the PRIMARY's data extent (which disables Y auto-range on that
        # ViewBox), so the dense original is NEVER drawn under a companion-
        # narrow Y. Axes without a companion keep the default Y auto-range.
        # VISIBILITY-AWARE: when 显示原始 is off the original isn't drawn (no
        # wall risk) so the shared axis frames the visible companion instead.
        self._pin_companion_axes_y_to_visible()

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
            self._emit_xrange_changed()
            if self._overlay_mode:
                self._overlay_axes._connect_overlay_view_sync()

        self._refresh = True
        self._tick_density_controller._apply_tick_density_to_all_axes()
        if self._overlay_mode:
            self._repin_overlay_channel_ticks()
        self._unify_subplot_bottom_axis_heights()
        # Tick density and data-union X seeding can change AxisItem geometry
        # after the early subplot label pass. Re-pin once at the end of build
        # so the first rendered frame already has one shared X grid.
        self._unify_subplot_left_axis_widths()

        if self._overlay_mode:
            self._settle_layout()
            self._sync_overlay_aux_viewboxes()

        # Bug 3: notify owners that fresh ViewBoxes exist so they can
        # re-apply pinned interaction state (toolbar pan/zoom mode). Runs
        # last so callbacks see the fully-built axes_list / x_master.
        self._run_replot_callbacks()
        self.disable_interactive_quality()
        self.schedule_idle_quality()
        if defer_first_frame:
            self._refresh_pending = True
            self._refresh_timer.start()

        # Restore cursor visual items when A/B positions survived clear().
        if self._cursor.visible and self._cursor.dual:
            if self._cursor.ax is not None:
                a_items = self._ensure_cursor_items(
                    "_cursor_a_items", color="#2563eb", width=1.1
                )
                self._set_cursor_items_pos(a_items, self._cursor.ax)
            if self._cursor.bx is not None:
                b_items = self._ensure_cursor_items(
                    "_cursor_b_items", color="#dc2626", width=1.1
                )
                self._set_cursor_items_pos(b_items, self._cursor.bx)

    def _set_primary_line_visible(self, name, visible):
        """Hide/show a primary (original) curve in place without rebuilding.

        The channel's axis/row is kept regardless (a dashed companion may be
        anchored on the same ViewBox), so this only flips the PlotDataItem's
        visibility. ``name`` is the primary channel name (NOT a companion).
        """
        pair = self._channel_lines.get(name)
        if pair is None:
            return
        line = pair[1]
        pdi = getattr(line, "plot_data_item", None)
        if pdi is not None:
            try:
                pdi.setVisible(bool(visible))
            except Exception:
                pass

    def _clear_hidden_line_cache(self, pdi):
        """Drop a just-hidden curve's device-coordinate cache.

        The idle-AA pass sets ``DeviceCoordinateCache`` on every curve item
        (quality._set_curves_cache_mode). A cached offscreen raster pixmap can
        keep compositing AFTER ``setVisible(False)`` on some viewports (the
        lesson-95 GL fingerprint), so the hidden original/companion would still
        appear on screen even though its PlotDataItem reports not-visible. This
        is a generic ``QGraphicsItem`` cache reset (NOT a GL/viewport change):
        on a CPU raster backend it is a harmless no-op (Qt already skips hidden
        items); on a cached/GL backend it guarantees no stale pixmap lingers.
        """
        try:
            from PyQt5.QtWidgets import QGraphicsItem
            curve = getattr(pdi, "curve", None)
            if curve is not None and hasattr(curve, "setCacheMode"):
                curve.setCacheMode(QGraphicsItem.NoCache)
        except Exception:
            pass

    def set_original_lines_visible(self, visible):
        """Live toggle for "显示原始": flip every PRIMARY (non-companion)
        curve's visibility on the already-built chart WITHOUT a re-plot.

        The companion (filtered, dashed) curves and their axes are untouched,
        so unchecking "显示原始" while a filter overlay is on just hides the
        solid originals and leaves the dashed traces — no recompute, no axis
        teardown. Returns the number of primary curves toggled (0 when no
        chart is built yet, so the caller can fall back to a full plot).
        """
        flag = bool(visible)
        companions = getattr(self, "_companion_names", set())
        n = 0
        reshown = []
        for ck, _name, (_handle, line) in self._channel_lines.composite_items():
            if ck in companions:
                continue
            pdi = getattr(line, "plot_data_item", None)
            if pdi is not None:
                try:
                    pdi.setVisible(flag)
                    n += 1
                    if flag:
                        reshown.append(ck)
                    else:
                        # Drop any device-coordinate cache so the hidden solid
                        # original cannot keep compositing from a stale raster
                        # pixmap (lesson-95 GL fingerprint).
                        self._clear_hidden_line_cache(pdi)
                except Exception:
                    pass
        if n:
            # Re-shown lines were SKIPPED by _refresh_visible_data while hidden
            # (renderer hidden-curve guard), so their envelope can be stale for
            # the current x-window if the user panned/zoomed while they were
            # off. Drop their range-key so the next refresh recomputes them at
            # the current view, then run the refresh synchronously before draw.
            for ck in reshown:
                try:
                    self._last_range_key.pop(ck, None)
                except Exception:
                    pass
            # Visibility changed → re-frame companion axes to the now-visible
            # set BEFORE the draw (synchronous, no intermediate frame): hiding
            # 显示原始 must drop Y onto the visible ±0.0x companion, and
            # re-showing it must restore the ±primary framing so the dense
            # original is never painted inside a companion-narrow Y wall.
            self._pin_companion_axes_y_to_visible()
            if reshown:
                self._refresh_visible_data()
            self.draw()
        return n

    def set_companion_lines_visible(self, visible):
        """Live toggle for "显示滤波后": flip every COMPANION (filtered,
        dashed) curve's visibility on the already-built chart WITHOUT a
        re-plot. The companion's axis stays (it shares its source's row), so
        this just hides/shows the dashed trace. Returns the number toggled.
        """
        flag = bool(visible)
        companions = getattr(self, "_companion_names", set())
        n = 0
        reshown = []
        for ck in companions:
            pair = self._channel_lines.get(ck)
            if pair is None:
                continue
            pdi = getattr(pair[1], "plot_data_item", None)
            if pdi is not None:
                try:
                    pdi.setVisible(flag)
                    n += 1
                    if flag:
                        # Resolve to the stored composite key so the
                        # range-key drop below matches the renderer's key.
                        ckey = self._channel_lines.composite_key_for(ck) or ck
                        reshown.append(ckey)
                    else:
                        # Drop any device-coordinate cache so the hidden dashed
                        # companion cannot keep compositing from a stale raster
                        # pixmap (lesson-95 GL fingerprint).
                        self._clear_hidden_line_cache(pdi)
                except Exception:
                    pass
        if n:
            # Re-shown companions were skipped by _refresh_visible_data while
            # hidden; drop their range-key + refresh so the dashed trace shows
            # current-view data (see set_original_lines_visible for the rationale).
            for ck in reshown:
                try:
                    self._last_range_key.pop(ck, None)
                except Exception:
                    pass
            # Re-frame companion axes to the now-visible set before the draw:
            # toggling 显示滤波后 changes what the shared axis should fit (e.g.
            # showing the companion while 显示原始 is off must drop Y onto the
            # ±0.0x companion).
            self._pin_companion_axes_y_to_visible()
            if reshown:
                self._refresh_visible_data()
            self.draw()
        return n

    def _axis_groups(self, *, companion_only=False):
        """Map ``id(handle) -> (handle, [names on it])`` for axes in
        ``_channel_lines``. A companion shares its source channel's ViewBox, so
        a companion-carrying handle hosts the primary AND its companion(s).
        With ``companion_only=True`` only handles that carry at least one
        display companion are returned."""
        companions = getattr(self, "_companion_names", set())
        groups = {}
        # Iterate by COMPOSITE key so same-named channels on different files map
        # to distinct group members; the names list carries composite keys
        # (resolvable by channel_data.get / _channel_lines.get downstream).
        for ck, _name, (handle, _line) in self._channel_lines.composite_items():
            slot = groups.get(id(handle))
            if slot is None:
                groups[id(handle)] = [handle, [ck], ck in companions]
            else:
                slot[1].append(ck)
                if ck in companions:
                    slot[2] = True
        if companion_only:
            return {
                k: (h, names)
                for k, (h, names, has_comp) in groups.items()
                if has_comp
            }
        return {k: (h, names) for k, (h, names, _hc) in groups.items()}

    def _visible_raw_y_extent(self, names, *, xlim=None):
        """Union ``(lo, hi)`` over the RAW ``channel_data`` of the curves in
        ``names`` whose ``PlotDataItem`` is currently VISIBLE. Windowed to
        ``xlim`` when given (with a full-range fallback if the window is empty).
        Returns ``None`` when nothing visible/finite remains.

        This is what makes companion-axis Y framing VISIBILITY-AWARE: when
        显示原始 is off only the dashed companion is drawn, so the shared axis
        frames the companion (no dense original on screen → no 满屏竖线墙 risk),
        instead of staying pinned to the hidden primary and burying the filtered
        waveform in a flat line near 0 (本末倒置). When the original IS visible
        the union covers it (the larger extent), preserving the wall-avoidance
        framing the pin was built for."""
        lo = hi = None
        for name in names:
            pair = self._channel_lines.get(name)
            if pair is None:
                continue
            pdi = getattr(pair[1], "plot_data_item", None)
            if pdi is not None:
                try:
                    if not pdi.isVisible():
                        continue
                except Exception:
                    pass
            row = self.channel_data.get(name)
            if row is None:
                continue
            try:
                sig = np.asarray(row[1], dtype=float)
            except Exception:
                continue
            finite_mask = np.isfinite(sig)
            if xlim is not None:
                try:
                    t = np.asarray(row[0], dtype=float)
                except Exception:
                    t = None
                if t is not None and t.shape == sig.shape:
                    x0, x1 = xlim
                    if x1 < x0:
                        x0, x1 = x1, x0
                    wmask = finite_mask & np.isfinite(t) & (t >= x0) & (t <= x1)
                    window = sig[wmask]
                    if window.size == 0:
                        window = sig[finite_mask]
                else:
                    window = sig[finite_mask]
            else:
                window = sig[finite_mask]
            if window.size == 0:
                continue
            wlo = float(window.min())
            whi = float(window.max())
            if not (np.isfinite(wlo) and np.isfinite(whi)):
                continue
            lo = wlo if lo is None else min(lo, wlo)
            hi = whi if hi is None else max(hi, whi)
        if lo is None:
            return None
        return lo, hi

    def _frame_handle_y(self, handle, extent, n_y, *, frame_to_nice):
        """Pad ``extent`` (lo, hi), optionally snap to nice ticks, and apply it
        via ``set_ylim`` (which disables that ViewBox's Y auto-range). Returns
        True on success."""
        lo, hi = extent
        if hi <= lo:
            pad = abs(lo) * 0.05 or 1.0
        else:
            pad = (hi - lo) * 0.05
        lo, hi = lo - pad, hi + pad
        if frame_to_nice:
            try:
                lo, hi, _ticks = _frame_to_nice(lo, hi, n_y)
            except Exception:
                pass
        try:
            handle.set_ylim(lo, hi)
            return True
        except Exception:
            return False

    def _pin_companion_axes_y_to_visible(self):
        """Pin every companion-carrying axis's Y to the extent of the VISIBLE
        curves on it, disabling that ViewBox's Y auto-range.

        Rationale (滤波子图卡顿真因): a tiny-amplitude dashed companion (filter
        overlay) shares its source channel's ViewBox. While Y auto-range is ON,
        a companion ``setData`` can trigger an auto-range pass that frames the
        shared axis to the companion's tiny ±0.0x window for a transient frame;
        the dense LARGE original then rasterizes as a full-height vertical-
        stroke wall inside that narrow Y (the most expensive paint regime),
        which is the 十几秒 stall users see before Y re-settles. An explicit
        ``set_ylim`` turns Y auto-range OFF and removes that window.

        VISIBILITY-AWARE (本末倒置 fix): the framed extent is the union of the
        curves actually VISIBLE on the axis, not always the primary. With
        显示原始 on, the original dominates so Y covers it (wall avoided, the
        regime this pin was built for). With 显示原始 off + 显示滤波后 on, the
        dense original is NOT drawn — no wall can form — so Y fits the visible
        ±0.0x companion and the filtered waveform is actually usable.

        Only companion-carrying axes are touched — axes whose channel has no
        filtered overlay keep pyqtgraph's default Y auto-range. The extent is
        read from RAW ``channel_data`` (NOT the decimated envelope) and framed
        with the same nice-tick padding as ``reset_view_to_data_extents`` so the
        first painted frame already matches Home's Y framing."""
        groups = self._axis_groups(companion_only=True)
        if not groups:
            return
        n_y = max(3, min(20, self._tick_density_controller.density[1]))
        for handle, names in groups.values():
            extent = self._visible_raw_y_extent(names)
            if extent is None:
                continue
            self._frame_handle_y(handle, extent, n_y, frame_to_nice=True)

    # ------------------------------------------------------------------
    # Viewport event-filter helpers
    # ------------------------------------------------------------------

    def _install_viewport_event_filter(self):
        """Install the QWidget event filter on the current GLW viewport.

        Called once during __init__, so double-click / cursor / overlay
        events reach eventFilter() via the viewport.
        """
        try:
            viewport = self._glw.viewport()
            if viewport is not None:
                viewport.setMouseTracking(True)
                viewport.installEventFilter(self)
        except Exception:
            pass

    def register_replot_callback(self, callback):
        """Register a zero-arg ``callback`` invoked after every
        ``plot_channels`` rebuild. Idempotent; ignores duplicates.

        Used by ``_ChartCard`` to re-apply the toolbar's current mouse mode
        to the freshly-built ViewBoxes (Bug 3). Private hook — not part of
        the W0 signal contract.
        """
        if callable(callback) and callback not in self._replot_callbacks:
            self._replot_callbacks.append(callback)

    def _run_replot_callbacks(self):
        for callback in list(self._replot_callbacks):
            try:
                callback()
            except Exception:
                pass

    def register_mouse_mode_controller(self, controller):
        """Register the shared mouse-mode ``controller`` (design D).

        ``controller`` must expose ``current_mouse_mode()`` returning
        ``'pan'`` / ``'zoom'`` / ``''`` plus ``set_pan_mode()`` and
        ``set_zoom_mode()``. It may also expose
        ``set_mouse_mode_broadcast(mode)``; the right-click menu prefers that
        entry so split panes stay in sync. ``_ChartCard`` registers the
        ``PgNavigationToolbar`` here so the right-click 鼠标操作 submenu and the
        toolbar share ONE state machine — selecting a menu item updates the
        toolbar (and its ViewBoxes/icons), and opening the menu reflects the
        toolbar's current mode in the checkmark.
        """
        self._mouse_mode_controller = controller

    def _plot_item_for_view_box(self, view_box):
        """Return the PlotItem that owns ``view_box`` (or None).

        In single/subplot mode each ViewBox is the PlotItem's own view; in
        overlay mode the right-axis aux ViewBoxes share the X-master
        PlotItem, so we map any aux ViewBox back to that PlotItem.
        """
        for handle in list(self.axes_list):
            if getattr(handle, "view_box", None) is view_box:
                return getattr(handle, "plot_item", None)
        master = self._x_master_handle
        if master is not None and getattr(master, "view_box", None) is view_box:
            return getattr(master, "plot_item", None)
        # Overlay aux ViewBoxes all render onto the X-master PlotItem.
        if view_box in self._overlay_axes.aux_viewboxes and master is not None:
            return getattr(master, "plot_item", None)
        if master is not None:
            return getattr(master, "plot_item", None)
        if self.axes_list:
            return getattr(self.axes_list[0], "plot_item", None)
        return None

    def _redesign_context_menu_for_viewbox(self, view_box, menu):
        """Reshape the assembled right-click ``menu`` of ``view_box`` per the
        design (delegated from ``_ModifierWheelViewBox.raiseContextMenu`` so
        the canvas can supply the PlotItem + shared mouse-mode controller)."""
        plot_item = self._plot_item_for_view_box(view_box)
        redesign_pg_context_menu(
            menu,
            plot_item,
            self._mouse_mode_controller,
            view_all_handler=self.reset_view_to_data_extents,
            y_autofit_handler=self.fit_y_to_visible_x,
            allow_y_grid=not self._overlay_mode,
            view_box=view_box,
        )
        self._remove_annotation_context_menu_actions(menu)

    def _remove_annotation_context_menu_actions(self, menu):
        if menu is None:
            return
        for action in list(menu.actions()):
            try:
                object_name = action.objectName()
            except Exception:
                object_name = ""
            if object_name.startswith("tracelabAnnotationRemarkAction"):
                menu.removeAction(action)

    def _add_plot_item(self, *, row, col):
        """Add a PlotItem hosted by our ``_ModifierWheelViewBox``.

        Mirrors ``GraphicsLayoutWidget.addPlot`` but injects the custom
        ViewBox so wheel events route through ``_handle_wheel_dispatch``
        (T6 requirement 4). Also installs a ``sigMouseClicked`` hook on
        the scene for blank-click deselect in overlay mode.
        """
        vb = _ModifierWheelViewBox(owner_canvas=self)
        vb.setBorder(
            pg.mkPen(
                color=PG_AXIS_NEUTRAL_COLOR,
                width=PG_AXIS_NEUTRAL_WIDTH,
            )
        )
        pi = self._glw.addPlot(row=row, col=col, viewBox=vb)
        _hide_native_auto_button(pi)
        _localize_pg_context_menu(getattr(vb, "menu", None))
        _localize_pg_context_menu(getattr(pi, "ctrlMenu", None))
        _localize_pg_context_actions(getattr(pi.scene(), "contextMenu", []))
        try:
            show_major_grid_left_bottom_only(pi, alpha=0.28)
        except Exception:
            pass
        for axis_name in ("left", "right", "bottom", "top"):
            try:
                pi.getAxis(axis_name).setStyle(maxTickLevel=0)
            except Exception:
                pass
        for axis_name in ("left", "right", "bottom"):
            try:
                axis = pi.getAxis(axis_name)
                axis.enableAutoSIPrefix(False)
                _apply_pg_axis_font(axis)
                axis.setPen(
                    pg.mkPen(
                        color=PG_AXIS_NEUTRAL_COLOR,
                        width=PG_AXIS_NEUTRAL_WIDTH,
                    )
                )
            except Exception:
                pass
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
        self.plot_channels(
            ch_list,
            mode=mode,
            xlabel=xlabel,
            defer_first_frame=(cur_xlim is not None),
        )
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
        self._sync_x_axis_item_range(ax, new_lo, new_hi)
        self._propagate_xlim_to_siblings(source=ax)
        # Order per pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before:
        # mutate, then flush. set_xlim above fired sigXRangeChanged and
        # scheduled the 40 ms debounced QTimer; drain it synchronously
        # so the post-switch frame is the high-detail envelope.
        try:
            self._flush_pending_refresh()
        except Exception:
            pass

    def get_visible_xlim(self):
        """Return the current visible X range, or None before any plot."""
        return self._capture_primary_xlim()

    def restore_visible_xlim(self, xlim):
        """Restore visible X through the existing synchronized restore path."""
        if xlim is not None:
            self._restore_primary_xlim(xlim)

    def get_visible_ylims(self):
        """Return per-channel visible Y ranges keyed for ViewState storage."""
        out = {}
        for key, pair in (
            getattr(self, "_channel_view_state_lines", None) or {}
        ).items():
            try:
                out[key] = pair[0].get_ylim()
            except Exception:
                continue
        return out

    def restore_visible_ylims(self, ylims):
        """Restore per-channel Y ranges; fit newly-added channels once."""
        view_state_lines = getattr(self, "_channel_view_state_lines", None) or {}
        legacy_lines = getattr(self, "_channel_lines", None) or {}
        changed = False
        restored_keys = set()
        for name, ylim in (ylims or {}).items():
            pair = view_state_lines.get(name) or legacy_lines.get(name)
            if pair is None:
                continue
            try:
                pair[0].set_ylim(*ylim)
                if name in view_state_lines:
                    restored_keys.add(name)
                changed = True
            except Exception:
                continue
        if restored_keys and len(restored_keys) < len(view_state_lines):
            n_y = max(3, min(20, self._tick_density_controller.density[1]))
            for key, (handle, line) in view_state_lines.items():
                if key in restored_keys:
                    continue
                get_label = getattr(line, "get_label", None)
                channel_name = get_label() if callable(get_label) else key
                if self._fit_channel_y_to_visible_x(
                    channel_name,
                    handle,
                    n_y,
                    frame_to_nice=self._overlay_mode,
                ):
                    changed = True
        if changed:
            self.visible_range_changed.emit()

    def _fit_channel_y_to_visible_x(self, name, handle, n_y, *, frame_to_nice):
        row = self.channel_data.get(name)
        if row is None:
            return False
        try:
            x0, x1 = handle.get_xlim()
        except Exception:
            return False
        if x1 < x0:
            x0, x1 = x1, x0
        try:
            t = np.asarray(row[0], dtype=float)
            sig = np.asarray(row[1], dtype=float)
        except Exception:
            return False
        if t.size == 0 or sig.size == 0:
            return False
        mask = np.isfinite(t) & np.isfinite(sig) & (t >= x0) & (t <= x1)
        window = sig[mask] if mask.any() else sig[np.array([], dtype=int)]
        if window.size == 0:
            finite = sig[np.isfinite(sig)]
            if finite.size == 0:
                return False
            window = finite
        lo = float(window.min())
        hi = float(window.max())
        if not (np.isfinite(lo) and np.isfinite(hi)):
            return False
        if hi <= lo:
            pad = abs(lo) * 0.05 or 1.0
        else:
            pad = (hi - lo) * 0.05
        lo, hi = lo - pad, hi + pad
        if frame_to_nice:
            lo, hi, _ticks = _frame_to_nice(lo, hi, n_y)
        try:
            handle.set_ylim(lo, hi)
        except Exception:
            return False
        return True

    def _sync_x_axis_item_range(self, handle, lo, hi):
        try:
            axis = handle.x_axis_item()
        except Exception:
            axis = None
        if axis is None:
            return
        try:
            axis.setRange(float(lo), float(hi))
        except Exception:
            return
        try:
            axis.update()
        except Exception:
            pass

    def _refresh_overlay_axis_labels(self):
        return OverlayAxisManager._refresh_overlay_axis_labels(self._overlay_axes)

    def _channel_name_for_handle(self, handle):
        for name, (candidate, _line) in self._channel_lines.items():
            if candidate is handle:
                return name
        return None

    def _overlay_channel_is_visible(self, name):
        """Whether ``name``'s curve is currently drawn (its PlotDataItem is
        visible). Hidden curves (显示原始 / 显示滤波后 off) are not valid
        overlay drag/select targets."""
        pair = self._channel_lines.get(name)
        if pair is None:
            return False
        pdi = getattr(pair[1], "plot_data_item", None)
        if pdi is None:
            return True
        try:
            return bool(pdi.isVisible())
        except Exception:
            return True

    def _visible_channel_name_for_handle(self, handle):
        """Return a VISIBLE channel bound on ``handle`` (the dragged axis
        owner), or None when every curve on it is hidden. A companion shares
        its primary's handle, so with 显示原始 off this resolves to the visible
        companion rather than the hidden primary."""
        for name, (candidate, _line) in self._channel_lines.items():
            if candidate is handle and self._overlay_channel_is_visible(name):
                return name
        return None

    def _sync_pg_channel_color(self, channel_name, color):
        return OverlayAxisManager._sync_pg_channel_color(
            self._overlay_axes,
            channel_name,
            color,
        )

    def set_xlim(self, lo, hi):
        """Apply a new xlim to the primary axis. Compatibility-only:
        external callers should prefer ``self._primary_xaxis_ax.set_xlim``.
        """
        primary = self._primary_xaxis_ax
        if primary is None:
            return
        primary.set_xlim(float(lo), float(hi))

    def reset_view_to_data_extents(self):
        """Toolbar Home helper: restore global X (raw union) AND global Y
        (per-channel raw full min/max) in one click.

        Bug 4: the hot-path ``PlotDataItem`` holds ONLY the viewport-clipped
        envelope (``_refresh_visible_data`` ships the xlim-clipped envelope),
        so an ``autoRange()``-based Home computed Y from the clipped window
        and left Y stuck at the previous zoom. We instead read Y from the
        RAW ``channel_data`` arrays.

        Ordering honors pyqt-ui/2026-04-25-flush-after-axis-mutation-not-
        before: set the X union and Y ranges first (all synchronous, no
        intermediate frame can paint), then the single try/finally tail
        flush drains the debounce so the frame after Home holds the
        global-window envelope.
        """
        self.disable_interactive_quality()
        try:
            # (1) Set X to the raw union on every handle (seeds the X-master
            # too in overlay mode).
            self._set_xrange_to_data_union()
            # (2) Set Y per handle from the RAW channel data (full, finite),
            # not from the clipped PlotDataItem. Frame each handle to the
            # union of the curves VISIBLE on it: a companion shares its
            # source's ViewBox, so with 显示原始 on Y covers the dominant
            # original (wall avoided), and with 显示原始 off + 显示滤波后 on Y
            # fits the visible ±0.0x companion (no dense original drawn → no
            # 满屏竖线墙 — the filtered waveform is usable). Non-companion
            # handles host a single visible primary, so the union == that
            # primary's full extent (unchanged behavior).
            n_y = max(3, min(20, self._tick_density_controller.density[1]))
            for handle, names in self._axis_groups().values():
                extent = self._visible_raw_y_extent(names)
                if extent is None:
                    continue
                # frame_to_nice=True so Y-axis labels/grid start and end exactly
                # at the viewport edges.
                self._frame_handle_y(handle, extent, n_y, frame_to_nice=True)
            if self._overlay_mode:
                self._repin_overlay_channel_ticks()
            self._refresh = True
            self.draw_idle()
        finally:
            try:
                self._flush_pending_refresh()
            except Exception:
                pass
            self.schedule_idle_quality()

    def fit_y_to_visible_x(self):
        """Right-click 「Y 轴自适应」: keep the CURRENT X (time) window fixed and
        autoscale Y to just the waveform inside that window.

        Distinct from ``reset_view_to_data_extents`` (查看全部), which restores
        BOTH X and Y to the full data union. Here X is untouched; for every
        channel we read its handle's current X range, slice the RAW
        ``channel_data`` signal to that window, and ``set_ylim`` to the slice's
        finite min/max with a small symmetric pad.

        We compute Y manually rather than rely on
        ``setAutoVisible(y=True) + enableAutoRange(YAxis)`` because the hot-path
        ``PlotDataItem`` only holds the viewport-clipped *envelope*
        (decimated), so pyqtgraph's auto-visible Y would fit the envelope, not
        the true samples — and the manual path is a one-shot fit that does NOT
        leave Y in a persistent auto mode that would then fight the user's next
        pan. Works for subplot/single (one channel per handle) and overlay
        (one channel per aux ViewBox); the X-master handle carries no channel
        and is skipped naturally (it is absent from ``_channel_lines``).
        """
        self.disable_interactive_quality()
        try:
            n_y = max(3, min(20, self._tick_density_controller.density[1]))
            # Frame each handle to the union of the curves VISIBLE on it, sliced
            # to that handle's current X window. A companion shares its
            # source's ViewBox: with 显示原始 on Y fits the dominant original
            # (wall avoided); with 显示原始 off + 显示滤波后 on Y fits the
            # visible ±0.0x companion (no dense original drawn → usable filtered
            # waveform). Non-companion handles host a single visible primary, so
            # the union == that primary's windowed fit (unchanged behavior).
            for handle, names in self._axis_groups().values():
                try:
                    xlim = handle.get_xlim()
                except Exception:
                    xlim = None
                extent = self._visible_raw_y_extent(names, xlim=xlim)
                if extent is None:
                    continue
                self._frame_handle_y(
                    handle, extent, n_y, frame_to_nice=self._overlay_mode
                )
            if self._overlay_mode:
                self._repin_overlay_channel_ticks()
            self._refresh = True
            self.draw_idle()
        finally:
            try:
                self._flush_pending_refresh()
            except Exception:
                pass
            self.schedule_idle_quality()

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
            did_set = False
            try:
                if vb is not None:
                    vb.blockSignals(True)
                handle.set_xlim(lo, hi)
                did_set = True
            except Exception:
                pass
            finally:
                try:
                    if vb is not None:
                        vb.blockSignals(False)
                except Exception:
                    pass
            if did_set:
                self._sync_x_axis_item_range(handle, lo, hi)
        self._tick_density_controller._apply_target_x_ticks_to_all_axes()

    def _repin_overlay_channel_ticks(self):
        return OverlayAxisManager._repin_overlay_channel_ticks(self._overlay_axes)

    def _snap_overlay_channel_to_grid(self, ax):
        return OverlayAxisManager._snap_overlay_channel_to_grid(
            self._overlay_axes,
            ax,
        )

    def _apply_overlay_box_zoom_y(self):
        return OverlayAxisManager._apply_overlay_box_zoom_y(self._overlay_axes)

    def clear(self):
        """Tear down the chart. Mirrors TimeDomainCanvas.clear."""
        # Drop xrange listener before we wipe the axes it points at.
        self._disconnect_xrange_listener()
        self._disconnect_overlay_view_sync()
        # Remove overlay aux ViewBoxes + ch3+ appended axes from the scene
        # BEFORE _glw.clear() (which only drops layout PlotItems) and BEFORE
        # we zero _overlay_aux_viewboxes/_overlay_aux_axes below — otherwise
        # the ghost curves leak (Bug 2). Uses _primary_xaxis_ax for the
        # PlotItem layout, so it must run before that is nulled.
        self._overlay_axes._teardown_overlay_aux_viewboxes()
        self._teardown_inside_labels()
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        try:
            self._resize_settle_timer.stop()
        except Exception:
            pass
        self._refresh_pending = False
        self._quality.reset_for_rebuild()

        # Strip everything from the GraphicsLayoutWidget.
        try:
            self._glw.clear()
        except Exception:
            pass

        self.axes_list = []
        self._channel_lines = _ChannelKeyDict()
        self._channel_view_state_lines = {}
        self.channel_data = _ChannelKeyDict()
        self._channel_data_id = _ChannelKeyDict()
        self._companion_names = set()
        self._channel_is_monotonic = _ChannelKeyDict()
        self._primary_xaxis_ax = None
        self._curve_path_cache.clear()
        self._last_range_key.clear()
        self._line_wall_state.clear()
        self._y_overflow_wall_active = False
        self._last_refresh_signature = None
        self._overlay_mode = False
        self._refresh = True
        # T6 — drop overlay selection + subplot label scaffolding so the
        # next plot_channels build starts from a clean slate. Inside-label
        # scene items were already removed by _teardown_inside_labels()
        # above (pg.GLW.clear() does NOT remove scene().addItem() items).
        self._x_master_handle = None
        # InfiniteLines were added via vb.addItem() on the X-master ViewBox,
        # which is part of the PlotItem already destroyed by _glw.clear() above.
        # Overlay manager state is reset after the teardown path has walked
        # its aux ViewBox/axis bookkeeping.
        self._overlay_axes.reset_for_rebuild()
        self._subplot_label_specs = []
        self._cursor.clear_items()
        # Cursor placement is NOT cleared here — full_reset / reset_cursor_state
        # do that. Mirror TimeDomainCanvas.clear's behavior.

    def full_reset(self):
        """Clear chart AND cursor state. Use on file close."""
        self.clear()
        self._cursor.reset_all_state()
        self._curve_path_cache.clear()
        self._last_range_key.clear()
        self._line_wall_state.clear()
        self._y_overflow_wall_active = False
        self._last_refresh_signature = None
        self._monotonic_fingerprint_cache.clear()
        self.draw_idle()

    def set_cursor_visible(self, v):
        return CursorController.set_cursor_visible(self._cursor, v)

    def set_dual_cursor_mode(self, en):
        return CursorController.set_dual_cursor_mode(self._cursor, en)

    def reset_cursor_state(self):
        return CursorController.reset_cursor_state(self._cursor)

    def draw_idle(self):
        return CursorController.draw_idle(self._cursor)

    def draw(self):
        return CursorController.draw(self._cursor)

    def _hide_cursor_items(self, items):
        return CursorController._hide_cursor_items(self._cursor, items)

    def _ensure_cursor_items(self, attr_name, *, color, width=1.0, style=Qt.SolidLine):
        return CursorController._ensure_cursor_items(
            self._cursor,
            attr_name,
            color=color,
            width=width,
            style=style,
        )

    def _remove_cursor_items(self, items):
        return CursorController._remove_cursor_items(self._cursor, items)

    def _set_cursor_items_pos(self, items, x):
        return CursorController._set_cursor_items_pos(self._cursor, items, x)

    def _ensure_dual_cursor_extreme_markers(self):
        return CursorController._ensure_dual_cursor_extreme_markers(self._cursor)

    def _hide_dual_cursor_extreme_markers(self):
        return CursorController._hide_dual_cursor_extreme_markers(self._cursor)

    def _update_dual_cursor_extreme_markers(self, points_by_channel):
        return CursorController._update_dual_cursor_extreme_markers(
            self._cursor,
            points_by_channel,
        )

    def _cursor_data_x_from_viewport_pos(self, viewport_pos):
        return CursorController._cursor_data_x_from_viewport_pos(
            self._cursor,
            viewport_pos,
        )

    def _handle_cursor_mouse_move(self, event_or_pos):
        return CursorController._handle_cursor_mouse_move(self._cursor, event_or_pos)

    def _handle_cursor_mouse_press(self, event):
        return CursorController._handle_cursor_mouse_press(self._cursor, event)

    def _scene_y_from_viewport_pos(self, viewport_pos):
        return CursorController._scene_y_from_viewport_pos(self._cursor, viewport_pos)

    def _select_overlay_channel_from_scene_pos(self, scene_pos):
        return CursorController._select_overlay_channel_from_scene_pos(
            self._cursor,
            scene_pos,
        )

    def _map_view_points_to_scene(self, view_box, xdata, ydata):
        return CursorController._map_view_points_to_scene(
            self._cursor,
            view_box,
            xdata,
            ydata,
        )

    # ------------------------------------------------------------------
    # Annotation (remark) methods
    # ------------------------------------------------------------------

    def set_remark_enabled(self, enabled):
        return self._annotations.set_remark_enabled(enabled)

    def clear_remarks(self):
        return self._annotations.clear_remarks()

    def _handle_overlay_mouse_press(self, event):
        return OverlayAxisManager._handle_overlay_mouse_press(
            self._overlay_axes,
            event,
        )

    def _handle_overlay_mouse_release(self, event):
        return OverlayAxisManager._handle_overlay_mouse_release(
            self._overlay_axes,
            event,
        )

    def get_statistics(self, time_range=None):
        """Read RAW arrays from ``channel_data`` (design §4.2 invariant).

        Return contract (multi-file same-name decouple): the dict is keyed by
        the COMPOSITE ``(data_id, name)`` key so two files exposing the same
        channel name produce TWO distinct stats rows instead of one
        overwriting the other. Each value carries a ``display_label`` field
        (the human-readable channel name) so a header consumer can show the
        name without parsing the key. ``StatisticsPanel.update_stats`` reads
        ``display_label`` when present and falls back to the key otherwise.

        The live stats strip (window.py ``_plot_time_on_canvas``) builds its
        rows directly from the plot data, not from this method; ``get_statistics``
        is the compat/contract surface (W0) plus the test/automation seam.

        The result is a ``_ChannelKeyDict`` so bare-name reads
        (``stats["speed"]``) keep working for legacy/test consumers while the
        underlying identity stays the non-colliding composite key.
        """
        stats = _ChannelKeyDict()
        companion_names = getattr(self, "_companion_names", set())
        for ck, name, (t, sig, _color, unit) in self.channel_data.composite_items():
            # Display companions (filter overlays) are display-only; never
            # report stats for them — stats mirror acquired channels only.
            if ck in companion_names:
                continue
            if time_range is not None:
                lo, hi = time_range
                m = (t >= lo) & (t <= hi)
                s = sig[m]
            else:
                s = sig
            if len(s):
                stats.set_with_label(ck, name, {
                    "min": float(np.min(s)),
                    "max": float(np.max(s)),
                    "mean": float(np.mean(s)),
                    "rms": float(np.sqrt(np.mean(s ** 2))),
                    "std": float(np.std(s)),
                    "p2p": float(np.ptp(s)),
                    "unit": unit,
                    "display_label": name,
                })
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
        return self._tick_density_controller.set_tick_density(x, y)

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
        from mf4_analyzer.ui import _axis_interaction

        self._chart_options_ax = handle
        # Releasing any latched pan/zoom drag state so the modal does not
        # leave the ViewBox mid-drag (parity with matplotlib's
        # _clear_canvas_pointer_state). The PG canvas has no
        # _mouse_button_pressed flag, but it does carry overlay-drag
        # bookkeeping — drop it so the dialog cannot resume a stale drag.
        self._overlay_axes.drag_start = None
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
                annotation_result = self._annotations._handle_annotation_mouse_press(event)
                if annotation_result is not None:
                    return annotation_result
                # Overlay selection / Y-drag begin takes precedence over
                # cursor placement, but only outside cursor mode (cursor
                # mode wins, matching canvases.py:853). _handle_overlay_
                # mouse_press is a no-op outside overlay mode.
                if self._handle_overlay_mouse_press(event):
                    return True
                if self._handle_cursor_mouse_press(event):
                    return True
            elif event.type() == QEvent.MouseMove:
                annotation_result = self._annotations._handle_annotation_mouse_move(event)
                if annotation_result is not None:
                    return annotation_result
                if self._overlay_axes._handle_overlay_mouse_move(event):
                    return True
                if self._handle_cursor_mouse_move(event):
                    return True
            elif event.type() == QEvent.MouseButtonRelease:
                annotation_result = self._annotations._handle_annotation_mouse_release(event)
                if annotation_result is not None:
                    if annotation_result:
                        self.schedule_idle_quality()
                    return annotation_result
                if self._handle_overlay_mouse_release(event):
                    return True
                self.schedule_idle_quality()
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

    def _settle_layout(self):
        """Force the pyqtgraph GraphicsLayout to recompute geometry now."""
        try:
            layout = self._glw.ci.layout
            layout.invalidate()
            layout.activate()
        except Exception:
            pass

    def _sync_overlay_aux_viewboxes(self):
        return OverlayAxisManager._sync_overlay_aux_viewboxes(self._overlay_axes)

    def _disconnect_overlay_view_sync(self):
        return OverlayAxisManager._disconnect_overlay_view_sync(self._overlay_axes)

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
            self._last_refresh_signature = None
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
        # rebuilds the cache entry. The per-line caches are COMPOSITE-keyed, so
        # build the exact (data_id, name) key when both are known — this targets
        # the precise file's channel instead of an ambiguous bare-name pop that
        # could miss a same-named channel from another file.
        if channel is not None:
            if data_id is not None:
                ck = _view_state_channel_key(data_id, channel)
                self._last_range_key.pop(ck, None)
                self._line_wall_state.pop(ck, None)
            else:
                self._last_range_key.pop(channel, None)
                self._line_wall_state.pop(channel, None)
        elif data_id is not None:
            for ck, _name, ch_data_id in list(
                self._channel_data_id.composite_items()
            ):
                if ch_data_id == data_id:
                    self._last_range_key.pop(ck, None)
                    self._line_wall_state.pop(ck, None)

    def invalidate_monotonicity_cache(self, custom_xaxis_fid=None, custom_xaxis_ch=None):
        """Drop per-channel monotonicity flags. Mirrors the matplotlib
        canvas surface so MainWindow's invalidation call sites remain
        renderer-agnostic. Full-clear (no filters) matches the
        TimeDomainCanvas behavior — the next plot_channels rebuilds the
        dict."""
        self._channel_is_monotonic.clear()
        self._monotonic_fingerprint_cache.clear()

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
        self.disable_interactive_quality()
        # Drag ticks keep only the cheap visual work synchronous: quality drop
        # plus sibling-x propagation so subplot rows move together. Tick
        # recompute and range signals are flushed from _refresh_visible_data.
        self._propagate_xlim_to_siblings(source=source_handle)
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._refresh_timer.start()

    def _emit_xrange_changed(self, source_handle=None):
        if source_handle is None:
            source_handle = self._primary_xaxis_ax
        if source_handle is None:
            return
        try:
            lo, hi = source_handle.get_xlim()
        except Exception:
            return
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return
        self.xrange_changed.emit(float(lo), float(hi))
        self.visible_range_changed.emit()

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
        targets = list(self.axes_list)
        if self._overlay_mode and self._x_master_handle is not None:
            targets = [self._x_master_handle] + targets
        if source is None or len(targets) <= 1:
            return
        try:
            lo, hi = source.get_xlim()
        except Exception:
            return
        for handle in targets:
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
                # Already identical. AxisItem.setRange invalidates its cached
                # tick picture even for equal values, so avoid re-syncing it on
                # every sibling propagation tick.
                continue
            did_set = False
            try:
                # blockSignals avoids ping-pong with sibling listeners.
                vb.blockSignals(True)
                vb.setXRange(float(lo), float(hi), padding=0)
                did_set = True
            except Exception:
                pass
            finally:
                try:
                    vb.blockSignals(False)
                except Exception:
                    pass
            if did_set:
                self._sync_x_axis_item_range(handle, lo, hi)

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
        return self._renderer._current_pixel_width()

    def _effective_pixel_width(self, pixel_width: int,
                               *, source_len=None, dense_count=None) -> int:
        return self._renderer._effective_pixel_width(
            pixel_width, source_len=source_len, dense_count=dense_count,
        )

    def _refresh_visible_data(self):
        return self._renderer._refresh_visible_data()

    def _build_painter_path(self, t, s) -> QPainterPath:
        return self._renderer._build_painter_path(t, s)

    def _build_painter_path_loop(self, t, s, n) -> QPainterPath:
        return self._renderer._build_painter_path_loop(t, s, n)

    def _render_path_to_pixmap(self, path: QPainterPath, color: str, pixel_width: int) -> QPixmap:
        return self._renderer._render_path_to_pixmap(path, color, pixel_width)

    # ------------------------------------------------------------------
    # T6 — Overlay selection / emphasis (mirrors
    # canvases.py:_apply_overlay_selection_style).
    # ------------------------------------------------------------------

    def select_overlay_channel(self, name):
        return OverlayAxisManager.select_overlay_channel(self._overlay_axes, name)

    def _overlay_emphasis_for_channel(self, name):
        return OverlayAxisManager._overlay_emphasis_for_channel(
            self._overlay_axes,
            name,
        )

    # ------------------------------------------------------------------
    # T6 — Selected-channel Y drag.
    # ------------------------------------------------------------------

    def _begin_overlay_y_drag_at(self, *, start_y_px):
        return OverlayAxisManager._begin_overlay_y_drag_at(
            self._overlay_axes,
            start_y_px=start_y_px,
        )

    def _apply_overlay_y_drag_at(self, *, current_y_px):
        return OverlayAxisManager._apply_overlay_y_drag_at(
            self._overlay_axes,
            current_y_px=current_y_px,
        )

    def _selected_overlay_axes(self):
        return OverlayAxisManager._selected_overlay_axes(self._overlay_axes)

    # ------------------------------------------------------------------
    # T6 — Modifier-aware wheel dispatch.
    # ------------------------------------------------------------------

    def _handle_wheel_dispatch(self, *, delta, modifiers, x_pos, y_pos,
                               view_box=None, scene_pos=None, axis=None):
        return OverlayAxisManager._handle_wheel_dispatch(
            self._overlay_axes,
            delta=delta,
            modifiers=modifiers,
            x_pos=x_pos,
            y_pos=y_pos,
            view_box=view_box,
            scene_pos=scene_pos,
            axis=axis,
        )

    # ------------------------------------------------------------------
    # T6 — Cursor HTML emission (byte-for-byte parity with
    # canvases.py:_update_single / _update_dual).
    # ------------------------------------------------------------------

    def _emit_single_cursor_html(self, x):
        return CursorController._emit_single_cursor_html(self._cursor, x)

    def _emit_dual_cursor_html(self):
        return CursorController._emit_dual_cursor_html(self._cursor)

    def _cursor_x_to_pixmap_x(self, data_x, pixmap_width):
        return CursorController._cursor_x_to_pixmap_x(
            self._cursor,
            data_x,
            pixmap_width,
        )

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
        for _handle, name, _color, _unit in self._subplot_label_specs:
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
        for handle, name, color, unit in self._subplot_label_specs:
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
                unit_suffix = f" ({unit})" if unit else ""
                if prefix is not None:
                    label_text = f"{prefix}\n{rest}{unit_suffix}"
                else:
                    label_text = f"{str(name)}{unit_suffix}"
                text_item = pg.TextItem(
                    text=f"● {label_text}",
                    color=pg.mkColor(color),
                    anchor=(0, 0),
                    fill=pg.mkBrush(255, 255, 255, 220),
                    border=pg.mkPen(color=color, width=0.8),
                )
                _apply_pg_text_item_font(text_item)
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
                        ax_item.setLabel(text=_subplot_ylabel_text(name, unit))
                        _apply_pg_axis_font(ax_item)
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
        try:
            layout = self._glw.ci.layout
            layout.invalidate()
            layout.activate()
        except Exception:
            pass

    def _unify_subplot_bottom_axis_heights(self):
        """Collapse hidden upper subplot bottom-axis reserves and balance rows.

        Only the bottom subplot shows X tick values and the X label, yet every
        subplot's bottom AxisItem still consumes layout height. Letting the
        hidden upper rows reserve a full tick/label height opens a large blank
        band between rows — most visible in two-row mode. Reserve the X
        tick/label height only on the final row and collapse the hidden upper
        rows to ~1 px, so subplots sit flush regardless of row count.

        After collapsing, give every grid row equal preferred height + stretch
        so QGraphicsGridLayout keeps the ViewBoxes the same size instead of
        handing the collapsed rows extra cell height (which leaves the bottom
        plot cramped). The bottom ViewBox stays ~one-axis-height shorter than
        the rows above it — the intended stacked-shared-X look, favouring flush
        adjacency over pixel-equal heights. The preferred height is a constant:
        equal values distribute proportionally, so rows stay balanced at any
        canvas size without reading live geometry. See
        docs/superpowers/specs/2026-06-02-subplot-vertical-spacing-design.md.
        """
        if not self._subplot_label_specs:
            return
        bottom_axes = []
        for handle in self.axes_list:
            pi = getattr(handle, "plot_item", None)
            if pi is None:
                continue
            try:
                axis = pi.getAxis("bottom")
            except Exception:
                axis = None
            if axis is not None:
                bottom_axes.append(axis)
        if len(bottom_axes) < 2:
            return
        for axis in bottom_axes[:-1]:
            try:
                axis.setHeight(1.0)
            except Exception:
                pass
        try:
            bottom_axes[-1].setHeight(None)
        except Exception:
            pass
        try:
            layout = self._glw.ci.layout
            for row in range(layout.rowCount()):
                layout.setRowStretchFactor(row, 1)
                layout.setRowPreferredHeight(row, 100.0)
            layout.invalidate()
            layout.activate()
        except Exception:
            pass

    def resizeEvent(self, event):
        """Defer resize-driven recompute to the 40 ms settle pass."""
        try:
            super().resizeEvent(event)
        finally:
            # Fix C (2026-05-31): the plot-area width just changed, so the
            # idle-AA density budget and envelope point count are stale.
            try:
                self._quality.density_seeded = False
                self._resize_settle_timer.start()
            except Exception:
                pass

    def _on_resize_settled(self):
        """Resize-debounce slot (Fix C): recompute the viewport envelope at
        the new width and re-arm the idle-AA timer so AA recovers.

        Reuses the existing debounced envelope-refresh path (set
        ``_refresh_pending`` + start ``_refresh_timer``) rather than adding
        a new rendering primitive; the resize → data-settle → idle-AA
        sequencing is the two-stage settle the design accepts (R4).
        """
        try:
            self.disable_interactive_quality()
        except Exception:
            pass
        try:
            self._refresh_overlay_axis_labels()
        except Exception:
            pass
        try:
            if self._subplot_label_specs:
                self._recheck_subplot_label_placement()
        except Exception:
            pass
        try:
            self._tick_density_controller._apply_target_x_ticks_to_all_axes()
            self._unify_subplot_left_axis_widths()
            self._unify_subplot_bottom_axis_heights()
        except Exception:
            pass
        try:
            if self._overlay_mode:
                self._settle_layout()
                self._sync_overlay_aux_viewboxes()
        except Exception:
            pass
        # Recompute the envelope for the new plot-area width, matching the
        # _on_xrange_changed scheduling pattern (no new rendering path).
        try:
            if not self._refresh_pending:
                self._refresh_pending = True
                self._refresh_timer.start()
        except Exception:
            pass
        self.schedule_idle_quality()

    # ------------------------------------------------------------------
    # Screenshot grab (compat with chart_stack._copy_card_image).
    # ------------------------------------------------------------------

    def disable_interactive_quality(self):
        return self._quality.disable_interactive_quality()

    def schedule_idle_quality(self):
        return self._quality.schedule_idle_quality()

    def try_enable_idle_quality(self):
        return self._quality.try_enable_idle_quality()

    def quality_status(self):
        return self._quality.quality_status()

    def grab_pixmap(self, scale: float = 1.0) -> QPixmap:
        return self._renderer.grab_pixmap(scale=scale)

    @staticmethod
    def _grab_widget_scaled(widget, eff_scale: float) -> QPixmap:
        return Renderer._grab_widget_scaled(widget, eff_scale)


__all__ = [
    "TimeDomainCanvasPG",
    "_quantize_range_key",
    "_capped_hidpi_scale",
    "_HIDPI_MAX_WIDTH",
    "_HIDPI_COPY_SCALE",
]
