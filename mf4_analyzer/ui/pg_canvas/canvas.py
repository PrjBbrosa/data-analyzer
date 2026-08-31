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
import logging
from math import ceil, isfinite
from time import monotonic
from typing import Tuple

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import (
    QEvent,
    QTimer,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from PyQt5.QtGui import (
    QPainterPath,
    QPen,
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
from mf4_analyzer.diagnostics import throttled
from mf4_analyzer.ui.ultraview_capture_facts import (
    build_capture_facts,
    iter_axes_rubberband_items,
    mapping_has_items,
    quality_settled_from_status,
    widget_visible_and_sized,
)
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
from mf4_analyzer.ui.pg_canvas.ticks_math import (
    _quantize_range_key,
    _frame_to_nice,
    pad_y_extent,
)
from mf4_analyzer.ui.pg_canvas.tick_density import TickDensityController
from mf4_analyzer.ui.pg_canvas.viewbox import (
    _ModifierWheelViewBox,  # noqa: F401
    _WheelDeltaGraphicsLayoutWidget,
)
from mf4_analyzer.ui.pg_canvas import renderer as _renderer
from mf4_analyzer.ui.pg_canvas.overlay_axes import OverlayAxisManager
from mf4_analyzer.ui_kit.axis_metrics import pin_left_axes_to_common_width
from mf4_analyzer.ui.axis_group_palette import axis_group_color
from mf4_analyzer.ui.pg_canvas.native_axes import tag_axis_group
from mf4_analyzer.ui.pg_canvas.quality import (
    QualityManager,
    _FRAME_TIMER_INSTALLED_ATTR,
    install_frame_paint_timer,
)
from mf4_analyzer.ui.pg_canvas.dense_raster import DenseDiscreteRasterLayer
from mf4_analyzer.ui.pg_canvas.render_profile import DENSE_DISCRETE_POLICY_ENABLED
from mf4_analyzer.ui.pg_canvas.renderer import (  # noqa: F401
    Renderer,
    _HIDPI_COPY_SCALE,
    _HIDPI_MAX_WIDTH,
    _INK_AA_OFF,
    _INK_AA_ON,
    _capped_hidpi_scale,
)
from mf4_analyzer.ui.pg_canvas._shared import (  # noqa: F401
    BorderAlignedAxisItem,
    GridLabelSlackAxisItem,
    _ChannelKeyDict,
    _hide_native_auto_button,
    _subplot_ylabel_text,
    _view_state_channel_key,
    show_major_grid_left_bottom_only,
)


_LOG = logging.getLogger(__name__)


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


# ---- Situational-nudge signal detection (feeds hints.HintState). These are
# pure helpers so the logic is unit-tested independently of rendering; the
# thresholds themselves are perceptual and need on-device tuning. ----
_NUDGE_PTP_MAX_SAMPLES = 2000   # subsample cap for the per-channel range probe
_AMP_DISPARITY_RATIO = 10.0     # max/min range ratio that reads as "dwarfed"
_CLIP_FRACTION = 0.03           # share of samples pinned to an extreme = clipped


def _finite_y_range(spec, *, require_span=False):
    """Return ``(lo, hi)`` when both ends are finite; else ``None``.

    Native WWT facts require ``hi > lo``. Persisted ylims may be collapsed
    (``hi == lo``); callers pass ``require_span=True`` only for native facts.
    """
    if spec is None:
        return None
    if isinstance(spec, dict):
        lo, hi = spec.get("lo"), spec.get("hi")
    else:
        try:
            lo, hi = spec[0], spec[1]
        except (TypeError, IndexError, ValueError, KeyError):
            return None
    try:
        lo_f = float(lo)
        hi_f = float(hi)
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(lo_f) and np.isfinite(hi_f)):
        return None
    if hi_f < lo_f:
        lo_f, hi_f = hi_f, lo_f
    if require_span and not (hi_f > lo_f):
        return None
    return lo_f, hi_f


def _union_y_ranges(ranges):
    lo = hi = None
    for rng in ranges:
        if rng is None:
            continue
        a, b = rng
        lo = a if lo is None else min(lo, a)
        hi = b if hi is None else max(hi, b)
    if lo is None:
        return None
    return lo, hi


def _subsampled(sig):
    arr = np.asarray(sig, dtype=float)
    if arr.size == 0:
        return arr
    stride = max(1, arr.size // _NUDGE_PTP_MAX_SAMPLES)
    s = arr[::stride]
    return s[np.isfinite(s)]


def _subsampled_ptp(sig):
    """Peak-to-peak of a (subsampled, finite) signal, or None if empty."""
    s = _subsampled(sig)
    if s.size == 0:
        return None
    return float(np.max(s) - np.min(s))


def _looks_clipped(sig):
    """True if a meaningful share of samples sit exactly at an extreme.

    A clean signal touches its max/min essentially once (fraction ≈ 1/N); a
    saturated/clipped one has a flat top/bottom repeating the extreme value.
    """
    s = _subsampled(sig)
    if s.size < 50:
        return False
    hi = float(np.max(s))
    lo = float(np.min(s))
    if hi == lo:
        return False  # constant trace ≠ clipped
    eps = (hi - lo) * 1e-6
    at_top = int(np.count_nonzero(s >= hi - eps))
    at_bot = int(np.count_nonzero(s <= lo + eps))
    return (max(at_top, at_bot) / s.size) >= _CLIP_FRACTION


def _compute_time_nudge_signals(vis):
    """Derive nudge signals from the visible primary rows plot_channels built.

    ``vis`` rows: (name, t, sig, color, unit, data_id, p_visible, axis_group).
    """
    count = len(vis)
    units = [str(r[4]).strip() for r in vis if r[4] and str(r[4]).strip()]
    same_unit = count >= 2 and len(units) == count and len(set(units)) == 1
    has_axis_group = any(r[7] for r in vis)
    ptps = [p for p in (_subsampled_ptp(r[2]) for r in vis) if p and p > 0]
    amp_disparate = (
        count >= 2 and len(ptps) >= 2
        and (max(ptps) / min(ptps)) >= _AMP_DISPARITY_RATIO
    )
    clipped = any(_looks_clipped(r[2]) for r in vis)
    return {
        "channel_count": count,
        "same_unit": same_unit,
        "has_axis_group": has_axis_group,
        "amp_disparate": amp_disparate,
        "clipped": clipped,
    }


class TimeDomainCanvasPG(QWidget):
    """Pyqtgraph-backed drop-in for ``canvases.TimeDomainCanvas``."""

    # Signal contract (design §3.1 — frozen by W0 contract test).
    cursor_info = pyqtSignal(str)
    single_cursor_rows = pyqtSignal(object)
    dual_cursor_info = pyqtSignal(str)
    dual_cursor_rows = pyqtSignal(object)  # emits raw dual list for mini pill
    span_selected = pyqtSignal(float, float)
    overlay_channel_selected = pyqtSignal(object)
    overlay_y_needs_selection = pyqtSignal()
    context_menu_requested = pyqtSignal()
    xrange_changed = pyqtSignal(float, float)
    visible_range_changed = pyqtSignal()
    quality_status_changed = pyqtSignal(object)
    # Fires after plot_channels rebuilds the chart, so the footer can refresh
    # situational nudges (channel count / units / amplitude / clip).
    chart_rebuilt = pyqtSignal()
    # Fires when a curve is recolored on the canvas (via the 图表选项 dialog),
    # carrying (data_id, display_name, color). MainWindow maps the display name
    # back to the raw (fid, ch) and writes navigator._colors so the left
    # channel-list swatch AND time/FFT replot follow one color truth.
    channel_color_changed = pyqtSignal(object, object, str)
    markup_revision_changed = pyqtSignal()

    # Mirror TimeDomainCanvas constants so callers see the same surface.
    MAX_PTS = 8000
    # Range events restart this timer. 100 ms is the spec's quiet-window
    # default: mouse/wheel/box interaction transforms the already-bound PDI
    # geometry, then only the latest viewport rebuilds its envelope.
    _INTERACTION_SETTLE_MS = 100
    _COARSE_REFRESH_MS = 100  # hard ceiling: at most 10 coarse setData/s
    _X_BUFFER_MARGIN_RATIO = 0.25
    _RESIZE_SETTLE_MS = 150
    _TIMER_GENERATION_PROPERTY = "tracelabInteractionGeneration"

    def __init__(self, parent=None):
        super().__init__(parent)

        # --- inner widget tree ------------------------------------------
        # GraphicsLayoutWidget is the host for one or more PlotItem rows.
        # We keep it as a child rather than subclassing so this widget
        # itself can carry pyqtSignals without metaclass conflicts.
        self._glw = _WheelDeltaGraphicsLayoutWidget(
            self, owner_canvas=self,
        )
        self._empty_hint_item = None
        self._empty_hint_text = ""
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
        # Raw X extents are immutable for one render generation.  The HDF
        # loader deliberately shares one time ndarray across every channel in
        # a raster, so key the finite-bounds scan by the array fingerprint and
        # cache the union consumed by Home/buffered pan/resize.  Range events
        # must never turn this O(samples * channels) again.
        self._raw_x_bounds_by_fingerprint = {}
        self._raw_x_union_cache = None
        self._raw_x_union_cache_valid = False
        self._x_viewport_intent = None
        # Parallel data_id dict (kept separate per design §4.2).
        self._channel_data_id = _ChannelKeyDict()
        # Composite keys of display-companion curves (e.g. filter overlays)
        # bound onto a source channel's axis. Subset of _channel_lines keys;
        # lets the stats / emphasis paths exclude them from real-channel logic.
        # Keyed by the composite (fid, name) key so a companion never collides
        # with a same-named companion from another file.
        self._companion_names = set()
        # Map each companion's composite key -> its SOURCE channel's composite
        # key. Used by _sync_companion_dash_styles to draw a companion DASHED
        # only while its solid source original is visible (otherwise SOLID): a
        # Qt.DashLine pen rasterizes a dense min/max-envelope zigzag several×
        # slower than a solid pen on the CPU raster backend, so a comp-only view
        # (显示原始 off + 显示滤波后 on) must not pay the dash cost when there is
        # no original to distinguish the filtered trace from.
        self._companion_source = {}
        # Per-channel monotonicity cache, populated once per
        # plot_channels build. Used in _refresh_visible_data so the hot
        # path skips np.diff(t).
        self._channel_is_monotonic = _ChannelKeyDict()
        # Render strategy classification belongs to this canvas generation.
        # Collaborators share and mutate this mapping in place; clear() drops
        # stale source revisions before the next file/selection generation.
        self._channel_render_profiles = {}
        # The "primary" axis facade — its sigXRangeChanged drives the
        # viewport-aware envelope refresh. Set after plot_channels.
        self._primary_xaxis_ax = None
        # Selection-delta model. Bound curves may become dormant (unchecked /
        # eye-hidden) without destroying their PDI/ViewBox, then reappear in
        # place when the same source/context is selected again.
        self._selection_bound_keys = set()
        self._selection_active_keys = set()
        self._selection_row_signatures = {}
        self._selection_mode = None
        self._selection_context_key = None
        self._selection_xlabel = "Time (s)"
        self._last_selection_delta = None
        self._last_full_rebuild_reason = None
        # Subplot rows may be collapsed and restored without destroying their
        # PlotItem/ViewBox.  The retained order is append-only within one
        # compatible selection generation; requests that need a middle insert
        # fall back to the existing structural rebuild.
        self._subplot_retained_order = []
        self._subplot_retained_handles = {}
        self._subplot_row_constraints = {}

        # --- viewport refresh wiring ------------------------------------
        # Interaction settle timer. Unlike the former 40 ms periodic refresh,
        # every new range event RESTARTS this timer, so a continuous gesture
        # cannot invalidate PlotDataItem geometry event-by-event.
        self._refresh_pending = False
        self._interaction_generation = 0
        self._interaction_depth = 0
        self._interaction_state = "idle"
        self._latest_target_xlim = None
        self._display_x_coverage = None
        self._display_x_coverage_by_channel = {}
        self._pending_coarse_xlim = None
        self._last_coarse_refresh_at = 0.0
        self._refresh_timer = self._new_refresh_timer(
            self._interaction_generation
        )
        self._coarse_timer = self._new_coarse_timer(
            self._interaction_generation
        )
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
        # A true resize quiet window.  It is intentionally longer than the
        # interaction-settle timer: on Cocoa a six-row paint can itself exceed
        # 100 ms, so the old 40 ms timer could expire while border dragging was
        # still active and re-enter the data/tick/layout refresh path.
        self._resize_settle_timer = QTimer(self)
        self._resize_settle_timer.setSingleShot(True)
        self._resize_settle_timer.setInterval(self._RESIZE_SETTLE_MS)
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
        # Per-channel ink state (renderer._refresh_visible_data): the
        # ``(ink_dev_px, high)`` pair recorded for THIS line at its last
        # un-skipped flush, so a range-key cache-HIT (no-op refresh) can keep
        # the frame ink flag set — AA must stay off until the geometry actually
        # changes, not until the next real recompute. Cleared alongside
        # _last_range_key on rebuild/invalidate. Composite (fid, name) keyed for
        # the same cross-file non-collision reason as _last_range_key.
        self._line_ink_state = _ChannelKeyDict()
        # Composite keys currently admitted to the dense-raster backend BY INK
        # (see _raster_backend_eligible). dense_discrete lines are admitted by
        # strategy and never enter this set. Hysteresis state, so it has to
        # survive between frames and be dropped with the rest of the per-line
        # caches on rebuild/full reset.
        self._ink_raster_admitted = set()
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
        # Ink budget (renderer._refresh_visible_data). Set True for the current
        # frame when ANY line's envelope is over _INK_OFF_BUDGET device pixels
        # of vertical ink. While active the idle-AA gate keeps antialiasing OFF
        # so the expensive AA compositing never re-arms over an ink band. Reset
        # to False on every refresh that finds every line under budget.
        self._frame_ink_high = False
        # --- measured-frame backstop (spec §4.4) ------------------------
        # Written by the resident paint timer installed on _glw below
        # (quality.install_frame_paint_timer). Deliberately PLAIN attributes,
        # not properties or a collaborator hop: they are touched from inside
        # Qt's paintEvent on every frame, so the write has to be a bare
        # __dict__ store. _last_frame_paint_ms is the most recent measured
        # frame in milliseconds (diagnostics + tests read it);
        # _aa_backstop_armed is the pairing token the paint timer tests before
        # doing anything beyond that store — it is True ONLY between the
        # moment idle AA is switched on and the moment it goes back off, so
        # non-AA frames cost one boolean read and are never offered to the
        # latch. QualityManager owns the flag's lifecycle.
        self._last_frame_paint_ms = 0.0
        self._aa_backstop_armed = False
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
        self._copy_image_handler = None

        # Decomposition collaborators. Most keep only a canvas back-reference;
        # Phase 4.2 starts moving cohesive state into the owning collaborator.
        self._cursor = CursorController(self)
        self._annotations = AnnotationManager(self)
        self._tick_density_controller = TickDensityController(self)
        self._overlay_axes = OverlayAxisManager(self)
        self._dense_raster = DenseDiscreteRasterLayer(self)
        self._quality = QualityManager(self)
        self._renderer = Renderer(self)
        # Resident paint timer (spec §4.4). Installed after _quality exists
        # because a timed frame calls straight into it. _glw is built once in
        # this constructor and is never replaced (clear() only empties it), so
        # one install covers the canvas' whole life; the call is idempotent
        # regardless. Consume the return value (B1): a failed first install
        # leaves the measured-frame backstop silently absent — log it.
        if not install_frame_paint_timer(self):
            glw = getattr(self, "_glw", None)
            if glw is None or not getattr(
                glw, _FRAME_TIMER_INSTALLED_ATTR, False,
            ):
                _LOG.warning(
                    "AA frame-paint backstop failed to install; "
                    "measured-frame safety net is inactive on this canvas"
                )

    # ------------------------------------------------------------------
    # Public surface (signal/method names frozen by W0 contract tests).
    # ------------------------------------------------------------------

    def _group_visible_into_slots(self, vis):
        """按 axis_group 把可见通道归并成「轴槽」。

        未分组通道（gid is None）各占一槽；同 gid 通道合并到该组首次
        出现位置的槽。槽序 = 通道首次出现顺序。叠加与分屏共用，保证两
        模式归并结果一致。返回 ``[{"gid": int|None, "members": [vis...]}]``。
        """
        slots = []
        slot_of_gid = {}
        for v in vis:
            gid = v[7]
            if gid is None:
                slots.append({"gid": None, "members": [v]})
            elif gid in slot_of_gid:
                slots[slot_of_gid[gid]]["members"].append(v)
            else:
                slot_of_gid[gid] = len(slots)
                slots.append({"gid": gid, "members": [v]})
        return slots

    def _subplot_layout_slots(self, layout_entries, vis):
        """Ordered subplot slots mixing success members and placeholders."""
        # Display names collide across files; identity is (name, data_id).
        vis_map = {(v[0], v[5]): v for v in vis}
        slots = []
        slot_of_gid = {}
        for kind, payload in layout_entries:
            if kind == "placeholder":
                slots.append({
                    "placeholder": payload,
                    "gid": None,
                    "members": [],
                })
                continue
            name = payload[0]
            data_id = payload[6] if len(payload) > 6 else None
            vis_row = vis_map.get((name, data_id))
            if vis_row is None:
                continue
            gid = vis_row[7]
            if gid is None:
                slots.append({
                    "placeholder": None,
                    "gid": None,
                    "members": [vis_row],
                })
            elif gid in slot_of_gid:
                slots[slot_of_gid[gid]]["members"].append(vis_row)
            else:
                slot_of_gid[gid] = len(slots)
                slots.append({
                    "placeholder": None,
                    "gid": gid,
                    "members": [vis_row],
                })
        return slots

    def _add_placeholder_subplot(self, payload, *, xlabel, is_bottom, row):
        """Neutral empty subplot row that does not join cursor/Y-fit/ink."""
        pi = self._add_plot_item(row=row, col=0)
        handle = PgAxisHandle(plot_item=pi, owner_canvas=self)
        handle.placeholder = True
        self.axes_list.append(handle)
        reason = str(payload.get("reason") or "无法绘制")
        name = str(payload.get("name") or "")
        vb = handle.view_box
        if vb is not None:
            vb.setMouseEnabled(x=False, y=False)
            try:
                vb.setMenuEnabled(False)
            except Exception:
                pass
            try:
                vb.enableAutoRange(enable=False)
                vb.setRange(xRange=(0.0, 1.0), yRange=(0.0, 1.0), padding=0.0)
            except Exception:
                pass
            escaped = (
                reason.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            label = pg.TextItem(
                html=(
                    f'<span style="color:#64748b;font-size:11pt">{escaped}</span>'
                ),
                anchor=(0.5, 0.5),
            )
            try:
                vb.addItem(label, ignoreBounds=True)
                label.setPos(0.5, 0.5)
            except Exception:
                pass
        if name:
            try:
                pi.getAxis("left").setLabel(name)
            except Exception:
                pass
        if xlabel and is_bottom:
            try:
                pi.setLabel("bottom", xlabel)
            except Exception:
                pass
        self._overlay_axes._configure_subplot_bottom_axis(
            handle, is_bottom=is_bottom,
        )
        self._subplot_label_specs.append(
            (handle, name or reason, "#9aa0a6", "")
        )

    def plot_channels(
        self,
        ch_list,
        mode="overlay",
        xlabel="Time (s)",
        defer_first_frame=False,
        progress_callback=None,
        render_context_key=None,
        full_rebuild_reason=None,
        x_axis_context=None,
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
        def report_progress(current, total=1000):
            if not callable(progress_callback):
                return
            try:
                progress_callback(int(current), max(1, int(total)))
            except Exception:
                pass

        def trace_work(values):
            try:
                return max(1, len(values))
            except TypeError:
                return 1

        report_progress(0)
        self.disable_interactive_quality()
        self.clear()
        self.set_cursor_x_axis_context(x_axis_context)
        self._native_line_width_px = {}

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
        layout_entries = []
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
            if meta and meta.get("placeholder"):
                layout_entries.append((
                    "placeholder",
                    {
                        "name": name,
                        "reason": str(meta.get("placeholder_reason") or "无法绘制"),
                        "data_id": data_id,
                    },
                ))
                continue
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
            axis_group = meta.get("axis_group") if meta else None
            if meta and meta.get("line_width_mm"):
                from .native_axes import line_width_px
                dpi = 96.0
                logical = getattr(self, "logicalDpiX", None)
                if callable(logical):
                    try:
                        dpi = float(logical()) or 96.0
                    except (TypeError, ValueError, RuntimeError):
                        # Widget may be mid-teardown; 96 dpi is a safe mm→px default.
                        dpi = 96.0
                ck = _view_state_channel_key(data_id, name)
                self._native_line_width_px[ck] = line_width_px(
                    float(meta["line_width_mm"]), dpi
                )
            primary = (
                name, bool(visible), t, sig, color, unit, data_id, axis_group
            )
            primaries.append(primary)
            layout_entries.append(("primary", primary))
        report_progress(100)

        # ``vis`` = primaries that own an axis this rebuild = original visible
        # OR has a visible companion. Carry the original's own visibility as a
        # 7th element so we can ``setVisible(False)`` it after bind while still
        # building its axis/row for the companion to anchor onto.
        vis = [
            (name, t, sig, color, unit, data_id, p_visible, axis_group)
            for (name, p_visible, t, sig, color, unit, data_id, axis_group) in primaries
            if p_visible or companion_visible_by_source.get(name)
        ]
        subplot_layout_slots = self._subplot_layout_slots(layout_entries, vis)

        # Situational nudge signals (channel count / units / amplitude / clip)
        # for the footer — see hints.HintState. Derived from the visible rows
        # here so the empty-chart path below resets them to calm too.
        self._nudge_signals = _compute_time_nudge_signals(vis)

        if not vis and not (mode == "subplot" and subplot_layout_slots):
            # No channel owns an axis (every original hidden AND no visible
            # companion) → nothing to draw and nothing to anchor companions to.
            self._project_remarks()
            self.chart_rebuilt.emit()
            report_progress(1000)
            return

        binding_total = max(
            1,
            sum(trace_work(row[1]) for row in vis)
            + sum(trace_work(row[2]) for row in companions),
        )
        binding_done = 0

        def record_bound_trace(values):
            nonlocal binding_done
            binding_done += trace_work(values)
            report_progress(150 + 750 * binding_done // binding_total)

        report_progress(150)

        overlay_mode = (mode == "overlay" and len(vis) >= 2)
        subplot_mode = (
            mode == "subplot"
            and (
                len(subplot_layout_slots) > 1
                or (
                    len(subplot_layout_slots) == 1
                    and subplot_layout_slots[0].get("placeholder")
                )
            )
        )
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
            # Build ONE subplot row per axis SLOT, not per channel. Channels
            # that share an axis_group collapse into a single row (one PlotItem,
            # one main ViewBox, one shared Y axis whose union range comes from
            # the ViewBox auto-range, axis pen = group color); ungrouped
            # channels each own their own row exactly as before. The slot order
            # (and merge rule) is the SAME helper the overlay branch uses, so
            # subplot/overlay group identically.
            slots = subplot_layout_slots
            n_slots = len(slots)
            # Subplot labels need bbox-overlap-driven inside/outside flip; build
            # one spec PER SLOT (group rows carry the group color + member-name
            # label, ungrouped rows carry the channel's own color).
            self._subplot_label_specs = []
            for slot_idx, slot in enumerate(slots):
                is_bottom = (slot_idx == n_slots - 1)
                if slot.get("placeholder"):
                    self._add_placeholder_subplot(
                        slot["placeholder"],
                        xlabel=xlabel,
                        is_bottom=is_bottom,
                        row=slot_idx,
                    )
                    continue
                pi = self._add_plot_item(row=slot_idx, col=0)
                handle = PgAxisHandle(plot_item=pi, owner_canvas=self)
                tag_axis_group(handle, slot["gid"])
                self.axes_list.append(handle)
                members = slot["members"]
                if slot["gid"] is None:
                    name, t, sig, color, unit, data_id, p_visible, _ag = members[0]
                    self._overlay_axes._bind_channel(
                        handle, name, t, sig, color, unit, data_id,
                        xlabel=xlabel if is_bottom else None,
                        skip_envelope=defer_first_frame,
                    )
                    record_bound_trace(sig)
                    self._set_primary_line_visible(name, p_visible)
                    self._subplot_label_specs.append((handle, name, color, unit))
                else:
                    # Multi-member slot: bind EVERY member curve onto the SAME
                    # handle (same PlotItem main ViewBox) — _bind_channel already
                    # supports multiple curves per handle (overlay does the same).
                    # Only j==0 sets the group axis label / group color / axis
                    # style refresh; each curve keeps its OWN channel color.
                    gid = slot["gid"]
                    group_color = axis_group_color(gid)
                    units = {m[4] for m in members}
                    group_unit = next(iter(units)) if len(units) == 1 else "(混合单位)"
                    group_label = " · ".join(str(m[0]) for m in members)
                    for j, m in enumerate(members):
                        name, t, sig, color, unit, data_id, p_visible, _ag = m
                        self._overlay_axes._bind_channel(
                            handle, name, t, sig, color, unit, data_id,
                            xlabel=xlabel if (is_bottom and j == 0) else None,
                            skip_envelope=defer_first_frame,
                            axis_label=group_label if j == 0 else None,
                            axis_color=group_color if j == 0 else None,
                            update_axis_style=(j == 0),
                        )
                        record_bound_trace(sig)
                        self._set_primary_line_visible(name, p_visible)
                    self._subplot_label_specs.append(
                        (handle, group_label, group_color, group_unit)
                    )
                self._overlay_axes._configure_subplot_bottom_axis(
                    handle, is_bottom=is_bottom,
                )
            # NOTE: we intentionally do NOT call ``setXLink`` here.
            # Pyqtgraph's linked-view propagation uses screen-geometry
            # interpolation (ViewBox.linkedViewChanged) which produces a
            # small per-subplot shift when the subplots' screen widths
            # differ (the bottommost subplot owns the x-axis label
            # gutter). For an analytical app the linked range MUST be
            # exact, so we propagate explicitly via _propagate_xlim_to_siblings
            # on every sigXRangeChanged tick from the primary.
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
            # plus one dedicated aux ViewBox + Y axis PER AXIS SLOT. Channels
            # that share the same axis_group collapse into a single slot (one
            # aux ViewBox, one Y axis, union Y range); ungrouped channels each
            # own their own independent slot. Slot 0 binds the LEFT axis;
            # slots 1..N bind successive right axes.
            pi = self._add_plot_item(row=0, col=0)
            # X-master handle wraps the main ViewBox; never enters
            # axes_list and never carries a curve.
            self._x_master_handle = PgAxisHandle(
                plot_item=pi,
                owner_canvas=self,
                allow_y_grid=False,
            )
            # 按 axis_group 归并成「轴槽」：未分组通道各占一槽；同 group 的通道
            # 共享一槽（一个 aux ViewBox + 一根 Y 轴，量程取并集自动）。槽序保持
            # 通道首次出现顺序；槽 0 绑左轴，其余绑右轴。分屏与叠加共用同一归槽
            # helper，保证两模式归并结果绝对一致。
            slots = self._group_visible_into_slots(vis)

            for slot_idx, slot in enumerate(slots):
                handle = self._overlay_axes._add_overlay_axis_handle(pi, slot_idx)
                tag_axis_group(handle, slot["gid"])
                self.axes_list.append(handle)
                members = slot["members"]
                gid = slot["gid"]
                if gid is None:
                    name, t, sig, color, unit, data_id, p_visible, _ag = members[0]
                    self._overlay_axes._bind_channel(
                        handle, name, t, sig, color, unit, data_id,
                        xlabel=xlabel, skip_envelope=defer_first_frame,
                    )
                    record_bound_trace(sig)
                    self._set_primary_line_visible(name, p_visible)
                else:
                    units = {m[4] for m in members}
                    group_label = next(iter(units)) if len(units) == 1 else "(混合单位)"
                    group_color = axis_group_color(gid)
                    for j, m in enumerate(members):
                        name, t, sig, color, unit, data_id, p_visible, _ag = m
                        self._overlay_axes._bind_channel(
                            handle, name, t, sig, color, unit, data_id,
                            xlabel=xlabel, skip_envelope=defer_first_frame,
                            axis_label=group_label if j == 0 else None,
                            axis_color=group_color if j == 0 else None,
                            update_axis_style=(j == 0),
                        )
                        record_bound_trace(sig)
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
            tag_axis_group(handle, vis[0][7])
            self.axes_list.append(handle)
            name, t, sig, color, unit, data_id, p_visible, _axis_group = vis[0]
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
            record_bound_trace(sig)
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
            record_bound_trace(csig)
            # Record companion -> source identity so _sync_companion_dash_styles
            # can decide solid (no visible original to distinguish from) vs
            # dashed (original visible) on every live visibility toggle. Only
            # genuine dashed companions need the swap; a row that asked for a
            # solid pen (dash=False) is left out so it always stays solid.
            if dash:
                companion_ck = _view_state_channel_key(cdata_id, cname)
                resolved_companion = (
                    self._channel_lines.composite_key_for(companion_ck)
                    or companion_ck
                )
                resolved_source = (
                    self._channel_lines.composite_key_for(source_key)
                    or source_key
                )
                self._companion_source[resolved_companion] = resolved_source

        # The dashed pen is purely a visual affordance to tell the filtered
        # companion apart from its solid source. When the original is hidden
        # (显示原始 off) there is nothing to distinguish it from, AND a Qt.DashLine
        # pen rasterizes a dense min/max-envelope zigzag far slower than a solid
        # pen on the CPU raster backend (实测 comp-only pan 单帧 47ms→7ms). So
        # sync each companion's dash style to its source's CURRENT visibility:
        # solid when the original is hidden, dashed when it is shown.
        self._sync_companion_dash_styles()

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

        if self._subplot_label_specs:
            self._settle_subplot_layout()
        else:
            self._tick_density_controller._apply_tick_density_to_all_axes()
            if self._overlay_mode:
                self._repin_overlay_channel_ticks()

        if self._overlay_mode:
            # PlotItem columns, not just glw.ci — collapsed right axes still
            # paint, so this has to pin measured widths after ticks exist.
            self._realize_overlay_axis_columns()

        # Bug 3: notify owners that fresh ViewBoxes exist so they can
        # re-apply pinned interaction state (toolbar pan/zoom mode). Runs
        # last so callbacks see the fully-built axes_list / x_master.
        self._run_replot_callbacks()
        self.disable_interactive_quality()
        self.schedule_idle_quality()
        if defer_first_frame:
            self._refresh_pending = True
            self._arm_interaction_settle()

        self._restore_dual_cursor_items()
        self._project_remarks()

        self.chart_rebuilt.emit()
        self._display_x_coverage = (
            None if defer_first_frame else self._current_display_x_coverage()
        )
        self._record_selection_model(
            ch_list,
            mode=mode,
            render_context_key=render_context_key,
        )
        self._selection_xlabel = str(xlabel)
        self._dense_raster.schedule_rebuild("plot-built", delay_ms=0)
        self._last_full_rebuild_reason = full_rebuild_reason
        report_progress(1000)

    def nudge_signals(self) -> dict:
        """Situational signals for the footer nudge surface (see hints.py)."""
        return dict(getattr(self, "_nudge_signals", {}) or {})

    @staticmethod
    def _selection_array_fingerprint(values):
        try:
            arr = np.asarray(values)
            ptr = int(arr.__array_interface__["data"][0]) if arr.size else 0
            return (ptr, arr.shape, arr.strides, str(arr.dtype))
        except Exception:
            return (id(values),)

    def _selection_rows(self, rows):
        parsed = {}
        for row in rows or []:
            if len(row) >= 8 and isinstance(row[7], dict):
                name, visible, t, sig, _color, _unit, data_id, meta = row[:8]
            elif len(row) >= 7:
                name, visible, t, sig, _color, _unit, data_id = row[:7]
                meta = None
            else:
                name, visible, t, sig, _color, _unit = row[:6]
                data_id = None
                meta = None
            meta = dict(meta or {})
            key = _view_state_channel_key(data_id, name)
            topology = (
                meta.get("axis_group"),
                meta.get("companion_of"),
                bool(meta.get("dash", False)),
            )
            parsed[key] = {
                "name": str(name),
                "visible": bool(visible),
                "row": row,
                "topology": topology,
                "signature": (
                    data_id,
                    str(name),
                    self._selection_array_fingerprint(t),
                    self._selection_array_fingerprint(sig),
                    topology,
                ),
            }
        return parsed

    def _record_selection_model(self, rows, *, mode, render_context_key):
        parsed = self._selection_rows(rows)
        bound_keys = {
            ck for ck, _name, _pair in self._channel_lines.composite_items()
        }
        self._selection_bound_keys = bound_keys
        self._selection_active_keys = bound_keys & set(parsed)
        self._selection_row_signatures = {
            key: parsed[key]["signature"]
            for key in bound_keys if key in parsed
        }
        self._selection_mode = str(mode)
        self._selection_context_key = render_context_key
        self._last_selection_delta = None
        if str(mode) == "subplot" and all(
            parsed.get(key, {}).get("topology") == (None, None, False)
            for key in bound_keys
        ):
            order = [key for key in parsed if key in bound_keys]
            self._subplot_retained_order = order
            self._subplot_retained_handles = {
                key: self._channel_lines[key][0] for key in order
            }
            self._subplot_row_constraints = {}
            for key, handle in self._subplot_retained_handles.items():
                pi = getattr(handle, "plot_item", None)
                if pi is None:
                    continue
                self._subplot_row_constraints[key] = (
                    float(pi.minimumHeight()),
                    float(pi.maximumHeight()),
                )
        else:
            self._subplot_retained_order = []
            self._subplot_retained_handles = {}
            self._subplot_row_constraints = {}

    def try_apply_selection_delta(
        self, rows, *, mode, render_context_key=None,
    ):
        """Hide/re-show already-bound curves without rebuilding chart objects.

        Ordinary retained subplots may hide, restore, or append a row without
        rebuilding their existing axes. New rows that require insertion, and
        every unsupported topology, return an explicit fallback reason so the
        owner can use the audited full rebuild safely.
        """
        if not self._selection_bound_keys:
            return {"applied": False, "reason": "no-render-model"}
        if str(mode) != self._selection_mode:
            return {"applied": False, "reason": "plot-mode-changed"}
        if (
            render_context_key is not None
            and self._selection_context_key is not None
            and render_context_key != self._selection_context_key
        ):
            return {"applied": False, "reason": "render-context-changed"}

        parsed = self._selection_rows(rows)
        requested = set(parsed)
        if str(mode) == "subplot":
            subplot_result = self._try_apply_subplot_selection_delta(
                parsed,
            )
            if subplot_result is not None:
                return subplot_result
        if not requested.issubset(self._selection_bound_keys):
            return {"applied": False, "reason": "new-channel"}
        if (
            len(self._selection_bound_keys) > 1
            and requested != self._selection_active_keys
            and self._selection_mode in {"overlay", "subplot"}
        ):
            return {
                "applied": False,
                "reason": f"{self._selection_mode}-topology-change",
            }
        for key in requested:
            if parsed[key]["signature"] != self._selection_row_signatures.get(key):
                return {"applied": False, "reason": "source-revision-changed"}

        reshown = []
        for ck, _name, (_handle, line) in self._channel_lines.composite_items():
            pdi = getattr(line, "plot_data_item", None)
            if pdi is None:
                continue
            should_show = bool(
                ck in requested and parsed.get(ck, {}).get("visible", False)
            )
            try:
                was_visible = bool(pdi.isVisible())
                pdi.setVisible(should_show)
            except Exception:
                continue
            if was_visible and not should_show:
                self._clear_hidden_line_cache(pdi)
            elif should_show and not was_visible:
                reshown.append(ck)

        self._selection_active_keys = requested
        self._last_selection_delta = {
            "applied": True,
            "reason": "visibility-only",
        }
        self._sync_companion_dash_styles()
        self._reframe_companion_axes_after_visibility_change()
        if reshown:
            for key in reshown:
                self._last_range_key.pop(key, None)
            self._settle_visible_data(self._interaction_generation)
        self._dense_raster.sync_visibility()
        self.draw_idle()
        return dict(self._last_selection_delta)

    def _try_apply_subplot_selection_delta(self, parsed):
        """Retain ordinary subplot rows; return None for the legacy path."""
        requested_order = list(parsed)
        requested = set(requested_order)
        previous_active = set(self._selection_active_keys)
        if not self._subplot_retained_order and self._selection_bound_keys:
            return None
        if not requested:
            self._last_selection_delta = {
                "applied": False,
                "reason": "subplot-empty-selection-reset",
            }
            return dict(self._last_selection_delta)
        if any(
            info.get("topology") != (None, None, False)
            or not info.get("visible", False)
            for info in parsed.values()
        ):
            return {
                "applied": False,
                "reason": "subplot-complex-topology-change",
            }

        bound = set(self._selection_bound_keys)
        for key in requested & bound:
            if parsed[key]["signature"] != self._selection_row_signatures.get(key):
                return {"applied": False, "reason": "source-revision-changed"}

        # Existing retained rows keep their relative order.  New rows may be
        # appended only; inserting one between already-bound rows would require
        # manipulating QGraphicsLayout's private row/item maps, so use the
        # audited full rebuild for that structural case.
        requested_existing = [key for key in requested_order if key in bound]
        retained_existing = [
            key for key in self._subplot_retained_order if key in requested
        ]
        seen_new = False
        for key in requested_order:
            if key not in bound:
                seen_new = True
            elif seen_new:
                return {
                    "applied": False,
                    "reason": "subplot-insertion-order-change",
                }
        if requested_existing != retained_existing:
            return {
                "applied": False,
                "reason": "subplot-order-change",
            }

        xlim = self._capture_primary_xlim()
        added = []
        for key in requested_order:
            if key in bound:
                continue
            row = parsed[key]["row"]
            if len(row) >= 7:
                name, visible, t, sig, color, unit, data_id = row[:7]
            else:
                name, visible, t, sig, color, unit = row[:6]
                data_id = None
            handle = PgAxisHandle(
                plot_item=self._add_plot_item(
                    row=len(self._subplot_retained_order), col=0,
                ),
                owner_canvas=self,
            )
            self._overlay_axes._bind_channel(
                handle,
                name,
                t,
                sig,
                color,
                unit,
                data_id,
                xlabel=None,
                skip_envelope=False,
            )
            self._attach_axis_handle_callbacks(handle)
            self._subplot_retained_order.append(key)
            self._subplot_retained_handles[key] = handle
            pi = handle.plot_item
            self._subplot_row_constraints[key] = (
                float(pi.minimumHeight()), float(pi.maximumHeight()),
            )
            self._selection_bound_keys.add(key)
            self._selection_row_signatures[key] = parsed[key]["signature"]
            added.append(key)
            bound.add(key)

        active_handles = []
        active_specs = []
        for key in self._subplot_retained_order:
            handle = self._subplot_retained_handles.get(key)
            pi = getattr(handle, "plot_item", None)
            if handle is None or pi is None:
                continue
            active = key in requested
            pair = self._channel_lines.get(key)
            pdi = (
                getattr(pair[1], "plot_data_item", None)
                if pair is not None else None
            )
            if active:
                minimum, maximum = self._subplot_row_constraints.get(
                    key, (0.0, 16777215.0),
                )
                pi.setMaximumHeight(maximum)
                pi.setMinimumHeight(minimum)
                pi.show()
                if pdi is not None:
                    pdi.setVisible(True)
                active_handles.append(handle)
                row = self.channel_data.get(key)
                if row is not None:
                    _t, _sig, color, unit = row
                    active_specs.append(
                        (handle, parsed.get(key, {}).get("name") or
                         self.channel_data.display_label(key, key), color, unit)
                    )
            else:
                if pdi is not None:
                    pdi.setVisible(False)
                    self._clear_hidden_line_cache(pdi)
                pi.hide()
                pi.setMinimumHeight(0.0)
                pi.setMaximumHeight(0.0)

        self._disconnect_xrange_listener()
        self.axes_list = active_handles
        self._primary_xaxis_ax = active_handles[0] if active_handles else None
        for handle in active_handles:
            if xlim is not None:
                vb = handle.view_box
                try:
                    vb.blockSignals(True)
                    handle.set_xlim(*xlim)
                finally:
                    try:
                        vb.blockSignals(False)
                    except Exception:
                        pass
            self._connect_xrange_listener(handle)

        for idx, handle in enumerate(active_handles):
            is_bottom = idx == len(active_handles) - 1
            self._overlay_axes._configure_subplot_bottom_axis(
                handle, is_bottom=is_bottom,
            )
            if is_bottom:
                try:
                    handle.set_xlabel(self._selection_xlabel)
                except Exception:
                    pass

        self._teardown_inside_labels()
        self._subplot_label_specs = active_specs
        self._settle_subplot_layout()
        invalid_realized_geometry = False
        try:
            if self._subplot_geometry_is_observable():
                invalid_realized_geometry = (
                    not self._subplot_realized_geometry_is_usable()
                )
        except RuntimeError:
            # A stale/deleted Qt graphics object is indistinguishable from
            # unusable realized geometry; retain no partially-mutated rows.
            invalid_realized_geometry = True
        if invalid_realized_geometry:
            failure = {
                "applied": False,
                "reason": "subplot-realized-geometry-invalid",
            }
            self.clear()
            self._last_selection_delta = dict(failure)
            return failure

        self._restore_dual_cursor_items()
        self._project_remarks()

        probe_w = self._overlay_axes._initial_bind_pixel_width()
        self._subplot_dense_count = 0
        if probe_w and probe_w > 0:
            for key in requested_order:
                row = self.channel_data.get(key)
                if row is not None and len(row[1]) / probe_w >= _renderer._SUBPLOT_DENSE_DECIMATION:
                    self._subplot_dense_count += 1

        self._selection_active_keys = requested
        self._raw_x_union_cache = None
        self._raw_x_union_cache_valid = False
        self._last_selection_delta = {
            "applied": True,
            "reason": "subplot-object-reuse",
            "added": len(added),
            "removed": len(previous_active - requested),
        }
        # The public result stays compact/stable; detailed counts remain on the
        # canvas for diagnostics.
        self._dense_raster.sync_visibility()
        if added:
            self._dense_raster.schedule_rebuild("selection-row-added", delay_ms=0)
            self._run_replot_callbacks()
        self.disable_interactive_quality()
        self.schedule_idle_quality()
        self.chart_rebuilt.emit()
        self.draw_idle()
        return {"applied": True, "reason": "subplot-object-reuse"}

    def _restore_dual_cursor_items(self):
        """Reconcile dual cursor lines with the current active axis topology."""
        if not (self._cursor.visible and self._cursor.dual):
            return
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
        self._emit_dual_cursor_html()

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
            # Original visibility flipped → re-sync companion dash styles BEFORE
            # the draw: hiding 显示原始 makes each companion the only trace on its
            # axis, so it should drop its slow dashed pen for a solid one
            # (comp-only 单帧 47ms→7ms); re-showing the original restores the
            # dash so the two traces stay distinguishable. Idempotent + cheap.
            self._sync_companion_dash_styles()
            # Visibility changed → re-frame companion axes to the now-visible
            # set BEFORE the draw (synchronous, no intermediate frame): hiding
            # 显示原始 must drop Y onto the visible ±0.0x companion, and
            # re-showing it must restore the ±primary framing so the dense
            # original is never painted inside a companion-narrow Y wall.
            self._reframe_companion_axes_after_visibility_change()
            if reshown:
                self._refresh_visible_data()
            self._dense_raster.sync_visibility()
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
            # A just-re-shown companion must adopt the correct pen style for the
            # current original visibility (solid while 显示原始 off so the dashed
            # raster cost stays off, dashed when the original is also shown).
            self._sync_companion_dash_styles()
            # Re-frame companion axes to the now-visible set before the draw:
            # toggling 显示滤波后 changes what the shared axis should fit (e.g.
            # showing the companion while 显示原始 is off must drop Y onto the
            # ±0.0x companion).
            self._reframe_companion_axes_after_visibility_change()
            if reshown:
                self._refresh_visible_data()
            self._dense_raster.sync_visibility()
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

    def _reframe_companion_axes_after_visibility_change(self):
        self._pin_companion_axes_y_to_visible()
        if self._overlay_mode:
            self._repin_overlay_channel_ticks()

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
        True on success.

        The padding lives in ``ticks_math.pad_y_extent`` because the constant
        case is subtler than the ``hi <= lo`` test that used to be inlined
        here: a channel computed from two others is constant in intent but not
        bit-exact, and auto-framing onto that ~1e-16 relative residue is what
        produced 18-character Y tick labels and a left axis pinned six times
        too wide. See that function for the mechanism.
        """
        lo, hi = pad_y_extent(*extent)
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

    def _source_original_visible(self, companion_ck):
        """Return True when the original (solid) source of ``companion_ck`` is
        currently a visible PlotDataItem. Unknown / unmapped companions and a
        missing source default to True (keep the dashed look — never silently
        drop the affordance when we can't prove the original is hidden)."""
        source_ck = self._companion_source.get(companion_ck)
        if source_ck is None:
            return True
        pair = self._channel_lines.get(source_ck)
        if pair is None:
            return True
        pdi = getattr(pair[1], "plot_data_item", None)
        if pdi is None:
            return True
        try:
            return bool(pdi.isVisible())
        except Exception:
            return True

    def _sync_companion_dash_styles(self):
        """Set each dashed companion's pen style from its source's visibility.

        ROOT-CAUSE PERF FIX (filter-overlay comp-only lag): the filtered
        companion is drawn with a ``Qt.DashLine`` pen purely to tell it apart
        from its solid source original. Qt's CPU raster dash-stroker walks the
        dash phase along EVERY segment of the stroked path, and a min/max
        envelope of a dense wideband filtered signal is a high-frequency zigzag
        with thousands of tiny segments — so a dashed pen rasterizes that path
        several× slower than a solid one (实测 4 通道×150万点, AA-off 交互式
        拖动单帧: 显示滤波后 47 ms vs 显示原始 16 ms; the dash IS the 31 ms
        delta). When the original is hidden (显示原始 off + 显示滤波后 on) there
        is no solid trace to distinguish the companion from, so the dash is pure
        cost with zero benefit → draw the companion SOLID (单帧降到 ~7 ms, even
        faster than 显示原始). When the original is visible again, restore the
        dash so the two traces stay distinguishable.

        Idempotent and cheap: only flips a pen whose style actually needs to
        change (no setPen / no repaint when already correct). Preserves the
        companion pen's color and width — only the style toggles."""
        companions = getattr(self, "_companion_names", set())
        if not companions:
            return
        for ck in companions:
            pair = self._channel_lines.get(ck)
            if pair is None:
                continue
            pdi = getattr(pair[1], "plot_data_item", None)
            if pdi is None:
                continue
            try:
                pen = pdi.opts.get("pen")
            except Exception:
                pen = None
            manager = getattr(self, "_dense_raster", None)
            if pen is None and manager is not None:
                pen = manager.native_pen_for(ck, pdi)
            if not isinstance(pen, QPen):
                continue
            want_dash = self._source_original_visible(ck)
            want_style = Qt.DashLine if want_dash else Qt.SolidLine
            try:
                if pen.style() == want_style:
                    continue
                if manager is not None and manager.set_native_pen_style(
                    ck, pdi, want_style,
                ):
                    continue
                new_pen = QPen(pen)
                new_pen.setStyle(want_style)
                pdi.setPen(new_pen)
            except Exception:
                pass

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

    def register_copy_image_handler(self, handler):
        """Register a 0-arg callable that copies the focused chart image.

        ``_ChartCard`` injects ``card.copy_image_requested.emit`` here so the
        right-click custom-action slot triggers the same copy path as the
        toolbar button.
        """
        self._copy_image_handler = handler

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
            copy_image_handler=self._copy_image_handler,
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
        # The left axis is the one that carries the Y grid here
        # (show_major_grid_left_bottom_only below). pyqtgraph's grid branch in
        # AxisItem.boundingRect drops the vertical tick-label slack, which
        # silently DELETES the topmost/bottommost Y tick values; the subclass
        # restores it and keeps the restored end labels inside their own row.
        #
        # Both visible axes also have to sit on the ``vb.setBorder`` frame
        # above instead of one pixel outside it (pyqtgraph 0.14 offsets the
        # axis line outwards, which showed up as a doubled left edge on
        # Retina). Top/right keep the stock AxisItem — they are hidden here,
        # so they stroke nothing to double up with.
        pi = self._glw.addPlot(
            row=row,
            col=col,
            viewBox=vb,
            axisItems={
                "left": GridLabelSlackAxisItem(orientation="left"),
                "bottom": BorderAlignedAxisItem(orientation="bottom"),
            },
        )
        # Keep the bottom-axis text reserve stable while interaction-time
        # adaptive ticks replace the settled explicit target ticks. The
        # default auto-reduction collapses this reserve to zero when a frame
        # has no drawable labels, moving the ViewBox border until reticking.
        # autoExpandTextSpace remains enabled so genuinely taller text can
        # still grow the axis; hidden upper subplot axes are separately pinned
        # to 1 px by _unify_subplot_bottom_axis_heights().
        pi.getAxis("bottom").setStyle(autoReduceTextSpace=False)
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
        x_axis_context = getattr(self._cursor, "x_axis_context", None)
        self.plot_channels(
            ch_list,
            mode=mode,
            xlabel=xlabel,
            defer_first_frame=(cur_xlim is not None),
            x_axis_context=x_axis_context,
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

    def _restore_primary_xlim(self, xlim, *, flush=True):
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
        if not flush:
            # View-restore transaction (2026-08-15 view-switch settlement spec
            # §3.1): X is only half of the final geometry — Y lands next — and
            # every consumer of a refresh (ink, envelope bucket cap, AA gate,
            # raster admission) reads the Y span. Bank the debt here and let
            # settle_view_restore() pay it once, on the final geometry.
            self._refresh_pending = True
            return
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

    def get_data_x_union(self):
        """Return ``(lo, hi)`` spanning all plotted data, or None when empty.

        This is what Home frames to and what a fresh ``plot_channels`` seeds
        the axes with — i.e. the full extent of what is currently drawn, with
        no view padding. Owners compare a preserved window against it to tell
        "user zoomed into the data" from "window left over from other data".
        """
        return self._data_x_union()

    def frame_x_to_data(self):
        """Re-frame X onto the plotted extent (what Home does for X).

        A replot that reuses existing axes leaves the X range alone, so a
        window sized for a previous, longer recording survives onto shorter
        data. Owners call this when they decide the carried-over window no
        longer belongs to what is drawn.
        """
        self._set_xrange_to_data_union()

    def restore_visible_xlim(self, xlim, *, flush=True):
        """Restore visible X through the existing synchronized restore path.

        ``flush=False`` opens a View-restore transaction: X is applied and
        synchronized as usual, but the refresh is only marked pending. The
        caller then owes a :meth:`settle_view_restore` once the rest of the
        geometry (Y, tick density) has landed. The default keeps the
        synchronous behaviour every other caller relies on.
        """
        if xlim is not None:
            self._restore_primary_xlim(xlim, flush=flush)

    def settle_view_restore(self):
        """Close a View-restore transaction on the FINAL geometry.

        One restore, one settlement: refresh once, schedule the raster once,
        decide quality once. See the 2026-08-15 view-switch quality settlement
        spec §3.1 — restoring X and Y as two independently self-finishing steps
        used to measure ink against the ``[0, 1]`` placeholder Y that
        ``plot_channels(defer_first_frame=True)`` leaves behind, inflating it
        ~70x and then never re-deciding.

        Order is load-bearing: ``_refresh_visible_data`` re-arms the 150 ms
        idle-quality timer on its way out, so the quality decision has to come
        after the flush or it would be overwritten. Overlay right-axis columns
        are realized before that flush so the first restored paint already
        has separated gutters — View switch does not resize the widget, so
        ``_on_resize_settled`` will not do this later.
        """
        if self._overlay_mode:
            self._realize_overlay_axis_columns()
        if self._refresh_pending:
            # No pending work means this was a first visit (no stored xlim,
            # non-deferred build): the bind envelope already IS the first
            # frame, so recomputing it here would be pure duplicate work.
            self._flush_pending_refresh()
        if self._dense_raster.has_dense_candidates():
            self._dense_raster.schedule_rebuild("view-restored", delay_ms=0)
        self._quality.settle_after_discrete_render()

    def get_visible_ylims(self):
        """Return per-channel visible Y ranges keyed for ViewState storage."""
        out = {}
        for key, pair in (
            getattr(self, "_channel_view_state_lines", None) or {}
        ).items():
            try:
                out[key] = pair[0].get_ylim()
            except Exception as exc:
                throttled(
                    _LOG,
                    f"canvas:get_visible_ylims:get_ylim:{type(exc).__name__}",
                    logging.WARNING,
                    "Failed to capture Y range for channel_key=%r",
                    key,
                    exc_info=True,
                )
                continue
        return out

    def restore_visible_ylims(self, ylims, *, native_axis_ranges=None):
        """Restore Y ranges once per shared axis handle.

        Priority for each unique handle: any persisted member ylim (finite
        union when they disagree), then WWT ``native_ticks['y'][axis_id]``
        ``lo``/``hi``, then the union of visible raw samples inside the
        current X window (full finite samples if that window is empty).

        Independent handles still fit a newly plotted channel that has no
        saved ylim. A sibling on a *shared* handle must not overwrite a
        persisted or native range already applied to that handle.
        """
        view_state_lines = getattr(self, "_channel_view_state_lines", None) or {}
        legacy_lines = getattr(self, "_channel_lines", None) or {}
        ylims = ylims or {}
        native_table = native_axis_ranges or {}

        def _pair_for_key(key):
            pair = view_state_lines.get(key)
            if pair is None:
                getter = getattr(legacy_lines, "get", None)
                if callable(getter):
                    pair = getter(key)
            return pair

        handle_members = {}
        seen_keys = set()

        def _register(key, pair):
            if pair is None or key in seen_keys:
                return
            handle = pair[0]
            if handle is None or getattr(handle, "placeholder", False):
                return
            seen_keys.add(key)
            slot = handle_members.get(id(handle))
            if slot is None:
                handle_members[id(handle)] = (handle, [key])
            else:
                slot[1].append(key)

        for key, pair in view_state_lines.items():
            _register(key, pair)
        composite = getattr(legacy_lines, "composite_items", None)
        if callable(composite):
            for ck, _name, pair in composite():
                _register(ck, pair)
        elif isinstance(legacy_lines, dict):
            for key, pair in legacy_lines.items():
                _register(key, pair)

        persisted_by_handle = {}
        for name, ylim in ylims.items():
            pair = _pair_for_key(name)
            if pair is None:
                continue
            _register(name, pair)
            rng = _finite_y_range(ylim)
            if rng is None:
                continue
            hid = id(pair[0])
            persisted_by_handle.setdefault(hid, []).append((name, rng))

        def _apply_ylim(handle, lo, hi, keys):
            try:
                handle.set_ylim(lo, hi)
                return True
            except Exception as exc:
                throttled(
                    _LOG,
                    f"canvas:restore_visible_ylims:set_ylim:{type(exc).__name__}",
                    logging.WARNING,
                    "Failed to restore Y range for channel_key=%r",
                    keys[0] if keys else None,
                    exc_info=True,
                )
                return False

        def _fit_handle_from_data(handle, keys, n_y):
            visible_extent = getattr(self, "_visible_raw_y_extent", None)
            frame_y = getattr(self, "_frame_handle_y", None)
            overlay = bool(getattr(self, "_overlay_mode", False))
            if callable(visible_extent) and callable(frame_y):
                try:
                    xlim = handle.get_xlim()
                except Exception:
                    xlim = None
                extent = visible_extent(keys, xlim=xlim)
                if extent is None:
                    return False
                return bool(frame_y(handle, extent, n_y, frame_to_nice=overlay))
            fitter = getattr(self, "_fit_channel_y_to_visible_x", None)
            if not callable(fitter):
                return False
            fitted = False
            for key in keys:
                if fitter(key, handle, n_y, frame_to_nice=overlay):
                    fitted = True
            return fitted

        ctrl = getattr(self, "_tick_density_controller", None)
        density = getattr(ctrl, "density", (10, 10)) if ctrl is not None else (10, 10)
        try:
            n_y = max(3, min(20, density[1]))
        except (TypeError, IndexError):
            n_y = 10

        changed = False
        any_persisted_applied = False
        pending_fit = []
        for hid, (handle, keys) in handle_members.items():
            persisted = persisted_by_handle.get(hid) or ()
            union = _union_y_ranges(rng for _key, rng in persisted)
            if union is not None and _apply_ylim(handle, union[0], union[1], keys):
                any_persisted_applied = True
                changed = True
                continue
            native = _finite_y_range(
                native_table.get(getattr(handle, "axis_group", None)),
                require_span=True,
            )
            if native is not None and _apply_ylim(handle, native[0], native[1], keys):
                changed = True
                continue
            pending_fit.append((handle, keys))

        if (not ylims) or any_persisted_applied:
            for handle, keys in pending_fit:
                if _fit_handle_from_data(handle, keys, n_y):
                    changed = True

        if changed:
            self._dense_raster.schedule_rebuild(
                "y-range-restored", delay_ms=self._INTERACTION_SETTLE_MS,
            )
            self.visible_range_changed.emit()

    def _fit_channel_y_to_visible_x(
        self,
        channel_key,
        handle,
        n_y,
        *,
        frame_to_nice,
    ):
        """Fit ``handle`` from the composite channel key's visible samples."""
        resolved_key = self.channel_data.resolve_unique(channel_key)
        if resolved_key is None:
            # ``get`` intentionally remains last-bound-wins for compatibility,
            # but an identity-sensitive Y fit must fail closed when a legacy
            # display-label fallback is ambiguous.
            return False
        # A legacy display-label key may fall back only after unique resolution;
        # fetch once by the resulting exact composite identity.
        row = self.channel_data.get(resolved_key)
        if row is None:
            return False
        try:
            x0, x1 = handle.get_xlim()
        except Exception as exc:
            throttled(
                _LOG,
                f"canvas:fit_visible_y:get_xlim:{type(exc).__name__}",
                logging.WARNING,
                "Failed to read visible X range for channel_key=%r",
                channel_key,
                exc_info=True,
            )
            return False
        if x1 < x0:
            x0, x1 = x1, x0
        try:
            t = np.asarray(row[0], dtype=float)
            sig = np.asarray(row[1], dtype=float)
        except Exception as exc:
            throttled(
                _LOG,
                f"canvas:fit_visible_y:array_coercion:{type(exc).__name__}",
                logging.WARNING,
                "Failed to coerce visible-fit arrays for channel_key=%r",
                channel_key,
                exc_info=True,
            )
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
        # Same padding contract as ``_frame_handle_y`` — including the
        # residue-only-span collapse, without which a computed channel that is
        # flat across the visible window frames Y onto its own float64 noise.
        lo, hi = pad_y_extent(lo, hi)
        if frame_to_nice:
            lo, hi, _ticks = _frame_to_nice(lo, hi, n_y)
        try:
            handle.set_ylim(lo, hi)
        except Exception as exc:
            throttled(
                _LOG,
                f"canvas:fit_visible_y:set_ylim:{type(exc).__name__}",
                logging.WARNING,
                "Failed to apply fitted Y range for channel_key=%r",
                channel_key,
                exc_info=True,
            )
            return False
        return True

    def _sync_x_axis_item_range(self, handle, lo, hi):
        try:
            axis = handle.x_axis_item()
        except Exception as exc:
            throttled(
                _LOG,
                f"canvas:sync_x_axis:x_axis_item:{type(exc).__name__}",
                logging.WARNING,
                "Failed to resolve X AxisItem for axis_handle=%s@0x%x",
                type(handle).__name__,
                id(handle),
                exc_info=True,
            )
            axis = None
        if axis is None:
            return
        try:
            axis.setRange(float(lo), float(hi))
        except Exception as exc:
            throttled(
                _LOG,
                f"canvas:sync_x_axis:set_range:{type(exc).__name__}",
                logging.WARNING,
                "Failed to sync X range for axis=%s@0x%x lo=%r hi=%r",
                type(axis).__name__,
                id(axis),
                lo,
                hi,
                exc_info=True,
            )
            return
        try:
            axis.update()
        except Exception as exc:
            throttled(
                _LOG,
                f"canvas:sync_x_axis:update:{type(exc).__name__}",
                logging.WARNING,
                "Failed to repaint synced X axis=%s@0x%x",
                type(axis).__name__,
                id(axis),
                exc_info=True,
            )
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
        result = OverlayAxisManager._sync_pg_channel_color(
            self._overlay_axes,
            channel_name,
            color,
        )
        self._dense_raster.capture_pen_update(channel_name)
        self._dense_raster.sync_visibility(schedule_missing=False)
        # Propagate the recolor to the navigator (swatch + color source-of-
        # truth for replot/FFT). ``channel_name`` is the composite key, so
        # recover the ORIGINAL fid + display name from the identity dicts —
        # the composite key stringifies the fid, but ``_channel_data_id`` keeps
        # it untouched, which is what the navigator (fid, ch) lookup needs.
        try:
            data_id = self._channel_data_id.get(channel_name)
            display_name = self.channel_data.display_label(channel_name, channel_name)
            self.channel_color_changed.emit(data_id, display_name, str(color))
        except Exception:
            pass
        self._dense_raster.invalidate_all("color-changed", schedule=True)
        return result

    def _raster_backend_eligible(self, ck) -> bool:
        """Whether ``ck`` should render through the dense-raster backend.

        ONE predicate, five consumers (spec §4.3): ``_dense_visible_keys`` /
        ``refresh_all`` in dense_raster, the renderer's interactive skip path
        and its ``update_channel`` / ``deactivate_channel`` branch, and
        ``_raster_covered_curve_items`` / ``_high_raster_cost_status`` in
        quality. Keeping it in one place is what lets the green/yellow/red
        state machine, the pen suppression and the rebuild-timer semantics stay
        untouched while the admission itself widens.

        Two legs:

        * ``strategy == "dense_discrete"`` — the original CRC/counter
          admission, independent of ink, gated by
          ``DENSE_DISCRETE_POLICY_ENABLED`` (default on per spec §4.3's
          dense_discrete-OR-high-ink predicate; re-armed 2026-08-15 after
          a 2026-08-14 attempt to park it broke batch_render_qt's settled
          bucket-cap contract — see ``render_profile.py``'s comment on the
          flag).
        * INK — a ``general`` line whose measured vertical ink puts it out of
          reach of vector AA. The raster path is the only remaining way to
          give it a smooth presentation at a bounded cost (spec §4.3: same
          geometry, 43 ms raster build vs 124 s vector AA).

        The ink leg carries HYSTERESIS over the shared AA band: a line is
        admitted above ``_INK_AA_OFF`` and released only below ``_INK_AA_ON``.
        Inside the band the previous decision stands, so a line sitting on the
        boundary cannot flap between backends frame to frame. The ink read is
        the PRE-cap demand recorded by ``_refresh_visible_data`` — the same
        number the AA gate refuses on, which is what keeps the two decisions on
        one boundary. A line with no recorded ink yet (never flushed, or its
        cache was dropped) keeps whatever it had; ``clear()`` / ``full_reset()``
        are what actually reset the set.
        """
        if (
            DENSE_DISCRETE_POLICY_ENABLED
            and getattr(self._channel_render_profiles.get(ck), "strategy", None)
            == "dense_discrete"
        ):
            return True
        # OVERLAY short-circuit — INK LEG ONLY. The raster backend refuses to
        # run in overlay at all (`_dense_visible_keys` returns nothing and
        # `refresh_all` drops every entry there), so admitting a line on ink
        # would assert "needs the raster backend" about a mode that has no
        # raster backend — and _high_raster_cost_status would then report a
        # high-raster-cost block for a path that does not exist. Overlay's
        # high-ink frames are refused by the ink AA gate on their own merits
        # and report through the ink branch of quality_status() instead.
        # The dense-discrete leg above is deliberately NOT short-circuited:
        # its overlay behavior predates the ink work and stays byte-identical.
        # The admitted set is left untouched (not discarded) so a
        # subplot→overlay→subplot round trip keeps its hysteresis memory.
        if bool(getattr(self, "_overlay_mode", False)):
            return False
        admitted = ck in self._ink_raster_admitted
        state = self._line_ink_state.get(ck)
        try:
            ink = float(state[0]) if state is not None else None
        except (TypeError, ValueError, IndexError):
            ink = None
        if ink is not None and isfinite(ink):
            if ink > _INK_AA_OFF:
                admitted = True
            elif ink < _INK_AA_ON:
                admitted = False
        if admitted:
            self._ink_raster_admitted.add(ck)
        else:
            self._ink_raster_admitted.discard(ck)
        return admitted

    def _on_pg_axis_scale_changed(self):
        """Synchronously replace an incompatible linear dense raster path."""
        if not self._dense_raster.has_dense_candidates():
            return
        self._dense_raster.invalidate_all("axis-scale-changed")
        self._dense_raster.flush_pending(self._interaction_generation)
        self.draw_idle()

    def _on_pg_axis_ylim_changed(self):
        """Debounce direct AxisHandle.set_ylim mutations into a fresh raster."""
        if not self._dense_raster.has_dense_candidates():
            return
        self._dense_raster.schedule_resuppress()
        self._dense_raster.schedule_rebuild(
            "programmatic-y-range", delay_ms=self._INTERACTION_SETTLE_MS,
        )

    def set_xlim(self, lo, hi):
        """Apply a new xlim to the primary axis. Compatibility-only:
        external callers should prefer ``self._primary_xaxis_ax.set_xlim``.
        """
        primary = self._primary_xaxis_ax
        if primary is None:
            return
        primary.set_xlim(float(lo), float(hi))
        # Public programmatic range changes (project restore, automation and
        # callers outside ViewBox gestures) are deterministic: mutation first,
        # then one synchronous settled refresh.
        self._flush_pending_refresh()

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
            # (1) Set X to the native Home target when this canvas is a WWT
            # view; otherwise the raw data union (seeds the X-master too in
            # overlay mode).
            home = self._home_x_range()
            if home is not None:
                self._set_xrange_to_data_union(home)
            else:
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
            self.draw_idle()
        finally:
            try:
                self._flush_pending_refresh()
            except Exception:
                pass
            self.schedule_idle_quality()

    def _data_x_union(self):
        if self._raw_x_union_cache_valid:
            return self._raw_x_union_cache
        bounds = []
        retained = set(self._subplot_retained_order)
        active = set(self._selection_active_keys)
        for key, _name, row in self.channel_data.composite_items():
            if retained and key not in active:
                continue
            t, _sig, _color, _unit = row
            fingerprint = self._selection_array_fingerprint(t)
            if fingerprint not in self._raw_x_bounds_by_fingerprint:
                self._raw_x_bounds_by_fingerprint[fingerprint] = (
                    self._scan_finite_x_bounds(t)
                )
            bound = self._raw_x_bounds_by_fingerprint[fingerprint]
            if bound is not None:
                bounds.append(bound)
        union = None
        if bounds:
            union = (
                min(lo for lo, _hi in bounds),
                max(hi for _lo, hi in bounds),
            )
        self._raw_x_union_cache = union
        self._raw_x_union_cache_valid = True
        return union

    @staticmethod
    def _scan_finite_x_bounds(values):
        """Return finite min/max for one raw X array (the counted scan seam)."""
        try:
            arr = np.asarray(values, dtype=float)
            finite_mask = np.isfinite(arr)
        except Exception:
            return None
        if arr.size == 0 or not finite_mask.any():
            return None
        if finite_mask.all():
            finite = arr
        else:
            finite = arr[finite_mask]
        return (float(finite.min()), float(finite.max()))

    def _invalidate_raw_x_bounds(self, values=None):
        """Invalidate only when raw channel membership/data actually changes."""
        self._raw_x_union_cache = None
        self._raw_x_union_cache_valid = False
        if values is None:
            self._raw_x_bounds_by_fingerprint.clear()
            return
        self._raw_x_bounds_by_fingerprint.pop(
            self._selection_array_fingerprint(values), None,
        )

    def _set_xrange_to_data_union(self, xlim=None):
        if xlim is None:
            x_union = self._data_x_union()
            if x_union is None:
                return
            lo, hi = x_union
        else:
            lo, hi = float(xlim[0]), float(xlim[1])
            if not (isfinite(lo) and isfinite(hi) and hi > lo):
                return
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

    def _repin_overlay_channel_ticks(self, *, reframe=True):
        return OverlayAxisManager._repin_overlay_channel_ticks(
            self._overlay_axes, reframe=reframe,
        )

    def _snap_overlay_channel_to_grid(self, ax):
        return OverlayAxisManager._snap_overlay_channel_to_grid(
            self._overlay_axes,
            ax,
        )

    def _apply_overlay_box_zoom_y(self):
        return OverlayAxisManager._apply_overlay_box_zoom_y(self._overlay_axes)

    def clear(self):
        """Tear down the chart. Mirrors TimeDomainCanvas.clear."""
        # Invalidate callbacks captured by the previous curve generation
        # before stopping timers or destroying PlotDataItems.
        self._interaction_generation += 1
        # Raster items live in channel ViewBoxes, so remove them before those
        # ViewBoxes are torn down by the overlay/layout cleanup below.
        self._dense_raster.clear()
        # Remarks are Qt items parented to the same ViewBoxes. Drop the
        # projection before overlay teardown / _glw.clear() so the live list
        # cannot retain sip-deleted wrappers. Intent stays so plot_channels
        # can reproject after the rebuild.
        self._drop_remark_projection()
        self._interaction_depth = 0
        self._interaction_state = "idle"
        self._latest_target_xlim = None
        self._display_x_coverage = None
        self._display_x_coverage_by_channel = {}
        self._pending_coarse_xlim = None
        self._last_coarse_refresh_at = 0.0
        # Replace the QObject, not just its interval/property. A timeout already
        # queued by Qt keeps the OLD lambda's captured generation and therefore
        # cannot mutate the new PlotDataItems after clear()/rebuild.
        old_refresh_timer = self._refresh_timer
        try:
            old_refresh_timer.stop()
            old_refresh_timer.deleteLater()
        except Exception:
            pass
        self._refresh_timer = self._new_refresh_timer(
            self._interaction_generation
        )
        old_coarse_timer = self._coarse_timer
        try:
            old_coarse_timer.stop()
            old_coarse_timer.deleteLater()
        except Exception:
            pass
        self._coarse_timer = self._new_coarse_timer(
            self._interaction_generation
        )
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
        self._tick_density_controller.set_native_tick_policy(None)

        # Strip everything from the GraphicsLayoutWidget.
        try:
            self._glw.clear()
        except Exception:
            pass
        self._empty_hint_item = None
        self._empty_hint_text = ""

        self.axes_list = []
        self._channel_lines = _ChannelKeyDict()
        self._channel_view_state_lines = {}
        self.channel_data = _ChannelKeyDict()
        self._invalidate_raw_x_bounds()
        self._channel_data_id = _ChannelKeyDict()
        self._companion_names = set()
        self._companion_source = {}
        self._channel_is_monotonic = _ChannelKeyDict()
        self._channel_render_profiles.clear()
        self._primary_xaxis_ax = None
        self._selection_bound_keys = set()
        self._selection_active_keys = set()
        self._selection_row_signatures = {}
        self._selection_mode = None
        self._selection_context_key = None
        self._selection_xlabel = "Time (s)"
        self._last_selection_delta = None
        self._subplot_retained_order = []
        self._subplot_retained_handles = {}
        self._subplot_row_constraints = {}
        self._curve_path_cache.clear()
        self._last_range_key.clear()
        self._line_ink_state.clear()
        self._ink_raster_admitted.clear()
        self._frame_ink_high = False
        self._last_refresh_signature = None
        self._overlay_mode = False
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
        self.set_cursor_x_axis_context(None)
        self.set_x_viewport_intent(None)
        # Cursor placement is NOT cleared here — full_reset / reset_cursor_state
        # do that. Mirror TimeDomainCanvas.clear's behavior.

    def show_empty_hint(self, text):
        """Replace the chart with a centered, non-interactive empty-state hint."""
        self.clear()
        self._empty_hint_text = str(text or "")
        if not self._empty_hint_text:
            return
        hint = pg.LabelItem(justify="center")
        hint.setText(
            self._empty_hint_text,
            color="#64748b",
            size="12pt",
        )
        self._glw.addItem(hint, row=0, col=0)
        self._empty_hint_item = hint

    def clear_empty_hint(self):
        if self._empty_hint_item is None:
            self._empty_hint_text = ""
            return
        try:
            self._glw.removeItem(self._empty_hint_item)
        except Exception:
            pass
        self._empty_hint_item = None
        self._empty_hint_text = ""

    def full_reset(self):
        """Clear chart AND cursor state. Use on file close."""
        self.clear()
        self._cursor.reset_all_state()
        self._curve_path_cache.clear()
        self._last_range_key.clear()
        self._line_ink_state.clear()
        self._ink_raster_admitted.clear()
        self._frame_ink_high = False
        self._last_refresh_signature = None
        self._monotonic_fingerprint_cache.clear()
        self.draw_idle()

    def set_cursor_visible(self, v):
        return CursorController.set_cursor_visible(self._cursor, v)

    def set_dual_cursor_mode(self, en):
        return CursorController.set_dual_cursor_mode(self._cursor, en)

    def set_cursor_x_axis_context(self, context):
        return CursorController.set_x_axis_context(self._cursor, context)

    def set_cursor_display_options(self, options):
        return CursorController.set_cursor_display_options(self._cursor, options)

    def cursor_display_options(self):
        return CursorController.cursor_display_options(self._cursor)

    def set_x_viewport_intent(self, intent):
        self._x_viewport_intent = intent

    @property
    def x_viewport_intent(self):
        return self._x_viewport_intent

    def _home_x_range(self):
        from mf4_analyzer.ui.view_state import trusted_wwt_native_intent

        intent = self._x_viewport_intent
        if not trusted_wwt_native_intent(intent):
            return None
        home = getattr(intent, "home_range", None)
        if home is None:
            return None
        lo, hi = float(home[0]), float(home[1])
        if not (isfinite(lo) and isfinite(hi) and hi > lo):
            return None
        union = self._data_x_union()
        if union is not None:
            overlap_lo = max(lo, float(union[0]))
            overlap_hi = min(hi, float(union[1]))
            if not (overlap_hi > overlap_lo):
                return None
        return (lo, hi)

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

    def _drop_remark_projection(self):
        return self._annotations._drop_remark_projection()

    def _project_remarks(self):
        return self._annotations._project_remarks()

    def snapshot_remarks(self):
        return self._annotations.snapshot_remarks()

    def restore_remarks(self, payload):
        return self._annotations.restore_remarks(payload)

    def snapshot_cursor_placement(self):
        fn = getattr(self._cursor, "snapshot_placement", None)
        return fn() if callable(fn) else None

    def restore_cursor_placement(self, placement):
        fn = getattr(self._cursor, "restore_placement", None)
        if callable(fn):
            return fn(placement)

    def remark_count(self):
        return len(self._annotations.remarks)

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

    def set_tick_density(self, x, y, *, reframe_overlay_y=True):
        return self._tick_density_controller.set_tick_density(
            x, y, reframe_overlay_y=reframe_overlay_y,
        )

    def set_native_tick_policy(self, native_ticks):
        return self._tick_density_controller.set_native_tick_policy(native_ticks)

    def project_native_ticks(self):
        return self._tick_density_controller.project_native_ticks()

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
        """Open the chart-options dialog for the curve under ``viewport_pos``.

        Overlay mode targets the EXACT curve double-clicked (its own axis
        handle) so its color/coordinates are editable — not just the left
        axis: a double-click on a channel's Y-axis gutter resolves that
        channel unambiguously (gutters are laid out in separate columns),
        and a double-click on a curve body picks the nearest visible curve.
        The resolved curve is emphasised while its dialog is open. A miss
        (blank plot area / subplot) falls back to the plot-area / active
        axis so the gesture is never a dead click."""
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        handle, curve_name = self._resolve_double_click_target(scene_pos)
        if handle is None:
            handle = self._resolve_active_axis_handle()
        if handle is None:
            return
        highlighted = False
        if curve_name is not None:
            try:
                self.select_overlay_channel(curve_name, notify=False)
                highlighted = True
            except Exception:
                highlighted = False
        try:
            self._open_chart_options_for_handle(handle)
        finally:
            if highlighted:
                try:
                    self.select_overlay_channel(None, notify=False)
                except Exception:
                    pass

    def _resolve_double_click_target(self, scene_pos):
        """Return ``(axis_handle, curve_name)`` for a double-click.

        Overlay: prefer the Y-axis gutter under the cursor (that one
        channel), else the nearest visible curve within the pick radius.
        ``curve_name`` is None when no specific curve is resolved (blank
        overlay area, or non-overlay/subplot) — the caller then targets the
        plot-area ViewBox under the cursor."""
        if scene_pos is None:
            return (None, None)
        if self._overlay_mode:
            axis_handle = self._overlay_axes._overlay_axis_handle_at_scene_pos(
                scene_pos
            )
            if axis_handle is not None:
                return (axis_handle, self._visible_channel_name_for_handle(axis_handle))
            name = self._select_overlay_channel_from_scene_pos(scene_pos)
            if name is not None:
                pair = self._channel_lines.get(name)
                if pair is not None:
                    return (pair[0], name)
        return (self._axis_handle_at_scene_pos(scene_pos), None)

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

    def _realize_overlay_axis_columns(self):
        return OverlayAxisManager._realize_overlay_axis_columns(self._overlay_axes)

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
                self._line_ink_state.pop(ck, None)
                self._ink_raster_admitted.discard(ck)
            else:
                self._last_range_key.pop(channel, None)
                self._line_ink_state.pop(channel, None)
                self._ink_raster_admitted.discard(channel)
        elif data_id is not None:
            for ck, _name, ch_data_id in list(
                self._channel_data_id.composite_items()
            ):
                if ch_data_id == data_id:
                    self._last_range_key.pop(ck, None)
                    self._line_ink_state.pop(ck, None)
                    self._ink_raster_admitted.discard(ck)

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
        self._tick_density_controller._use_adaptive_x_ticks_during_range_change()
        # Drag ticks keep only the cheap visual work synchronous: quality drop
        # plus sibling-x propagation so subplot rows move together. Tick
        # recompute and range signals are flushed from _refresh_visible_data.
        self._propagate_xlim_to_siblings(source=source_handle)
        try:
            self._latest_target_xlim = tuple(
                float(v) for v in source_handle.get_xlim()
            )
        except Exception:
            self._latest_target_xlim = None
        self._dense_raster.drop_lossy_for_xlim(self._latest_target_xlim)
        self._refresh_pending = True
        self._interaction_state = (
            "interactive" if self._interaction_depth else "settling"
        )
        self._schedule_coarse_refresh_if_needed(self._latest_target_xlim)
        # PlotDataItem.viewRangeChanged may re-apply its stored pen while it
        # recomputes clipping/downsampling. Keep bounds/business visibility,
        # but immediately re-suppress the native stroke behind a ready raster.
        self._dense_raster.schedule_resuppress()
        # Critical difference from the old contract: restart on EVERY event.
        # This makes the interval a quiet window rather than a periodic 25 FPS
        # setData clock during a long drag.
        self._arm_interaction_settle()

    def _begin_view_interaction(self):
        """Enter the transform-only path for a mouse drag gesture."""
        self._interaction_depth += 1
        self._interaction_state = "interactive"
        try:
            self._refresh_timer.stop()
        except Exception:
            pass
        # A user gesture supersedes an unfinished resize quiet window.  Leaving
        # it armed would let resize-driven setData race the coarse 10 Hz path
        # (notably just after an initial show/resize), defeating the
        # transform-only interaction contract.
        try:
            self._resize_settle_timer.stop()
        except Exception:
            pass
        self.disable_interactive_quality()

    def _end_view_interaction(self):
        """End a drag and start the quiet window for its latest range."""
        self._interaction_depth = max(0, self._interaction_depth - 1)
        if self._interaction_depth:
            return
        # Release commits through the settled frame. Cancel any coarse frame
        # queued for the held gesture so it cannot race immediately before the
        # one required final setData.
        try:
            self._coarse_timer.stop()
        except Exception:
            pass
        self._pending_coarse_xlim = None
        if self._refresh_pending:
            self._interaction_state = "settling"
            self._arm_interaction_settle()
        else:
            self._interaction_state = "idle"
        self._dense_raster.schedule_resuppress()
        # A vertical-only pan may not emit sigXRangeChanged. Rebuild the cached
        # bitmap after the same 100 ms quiet window so Y transforms settle too.
        self._dense_raster.schedule_rebuild(
            "view-interaction", delay_ms=self._INTERACTION_SETTLE_MS,
        )

    def _arm_interaction_settle(self):
        try:
            self._refresh_timer.start(self._INTERACTION_SETTLE_MS)
        except TypeError:
            self._refresh_timer.start()

    def _new_refresh_timer(self, generation):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(self._INTERACTION_SETTLE_MS)
        timer.setProperty(self._TIMER_GENERATION_PROPERTY, int(generation))
        timer.timeout.connect(self._on_refresh_timer_timeout)
        return timer

    def _new_coarse_timer(self, generation):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setProperty(self._TIMER_GENERATION_PROPERTY, int(generation))
        timer.timeout.connect(self._on_coarse_timer_timeout)
        return timer

    def _sender_timer_generation(self):
        timer = self.sender()
        if not isinstance(timer, QTimer):
            return None, None
        try:
            generation = int(timer.property(self._TIMER_GENERATION_PROPERTY))
        except (TypeError, ValueError):
            return timer, None
        return timer, generation

    @pyqtSlot()
    def _on_refresh_timer_timeout(self):
        """Bound timeout slot; generation lives on the QObject, not a closure."""
        timer, generation = self._sender_timer_generation()
        if (
            timer is not self._refresh_timer
            or generation is None
            or not self._refresh_pending
        ):
            return
        self._settle_visible_data(generation)

    @pyqtSlot()
    def _on_coarse_timer_timeout(self):
        """Bound coarse slot with QObject-owned generation metadata."""
        timer, generation = self._sender_timer_generation()
        if timer is not self._coarse_timer or generation is None:
            return
        self._run_coarse_refresh(generation)

    @staticmethod
    def _coverage_contains(coverage, viewport):
        if coverage is None or viewport is None:
            return False
        try:
            clo, chi = (float(v) for v in coverage)
            vlo, vhi = (float(v) for v in viewport)
        except Exception:
            return False
        eps = max(abs(vhi - vlo), 1.0) * 1e-9
        return clo <= vlo + eps and chi >= vhi - eps

    def _current_display_x_coverage(self):
        """Return the finite-X intersection actually present on visible PDIs."""
        per_channel = {}
        for ck, _name, (_axis, line) in self._channel_lines.composite_items():
            pdi = getattr(line, "plot_data_item", None)
            if pdi is None or not pdi.isVisible():
                continue
            try:
                x_data, _y_data = pdi.getData()
                finite = np.asarray(x_data, dtype=float)
                finite = finite[np.isfinite(finite)]
            except Exception:
                continue
            if finite.size:
                per_channel[ck] = (float(finite.min()), float(finite.max()))
        self._display_x_coverage_by_channel = per_channel
        if not per_channel:
            return None
        return (
            max(lo for lo, _hi in per_channel.values()),
            min(hi for _lo, hi in per_channel.values()),
        )

    def _buffered_xlim(self, viewport):
        if viewport is None:
            return None
        try:
            lo, hi = (float(v) for v in viewport)
        except Exception:
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        margin = (hi - lo) * self._X_BUFFER_MARGIN_RATIO
        buffered = [lo - margin, hi + margin]
        data_union = self._data_x_union()
        if data_union is not None:
            buffered[0] = max(buffered[0], float(data_union[0]))
            buffered[1] = min(buffered[1], float(data_union[1]))
        if buffered[1] <= buffered[0]:
            return (lo, hi)
        return tuple(buffered)

    def _remaining_coarse_refresh_ms(self, now=None):
        if self._last_coarse_refresh_at <= 0.0:
            return int(self._COARSE_REFRESH_MS)
        current = monotonic() if now is None else float(now)
        elapsed_ms = (current - self._last_coarse_refresh_at) * 1000.0
        remaining_ms = float(self._COARSE_REFRESH_MS) - elapsed_ms
        return 0 if remaining_ms <= 0.0 else max(1, int(ceil(remaining_ms)))

    def _schedule_coarse_refresh_if_needed(self, viewport):
        if viewport is None or self._coverage_contains(
            self._display_x_coverage, viewport
        ):
            return
        self._pending_coarse_xlim = tuple(viewport)
        if self._coarse_timer.isActive():
            return
        if self._last_coarse_refresh_at <= 0.0:
            # The first coarse frame also observes the 100 ms gate. This makes
            # the contract unambiguous: a one-second gesture can schedule at
            # most ten coarse frames, not t=0 plus ten interval boundaries.
            delay_ms = self._COARSE_REFRESH_MS
        else:
            delay_ms = self._remaining_coarse_refresh_ms()
        self._coarse_timer.start(delay_ms)

    def _run_coarse_refresh(self, generation):
        if int(generation) != self._interaction_generation:
            return False
        if self._last_coarse_refresh_at > 0.0:
            remaining_ms = self._remaining_coarse_refresh_ms()
            if remaining_ms > 0:
                self._coarse_timer.start(remaining_ms)
                return False
        # A one-shot wheel/box event has its final settled timer due at the
        # same boundary; let that higher-quality frame win instead of doing a
        # coarse setData immediately followed by a settled setData. During a
        # continuing gesture the settle timer has been pushed farther out.
        try:
            settle_due_ms = self._refresh_timer.remainingTime()
        except Exception:
            settle_due_ms = -1
        if (
            self._interaction_depth == 0
            and self._refresh_timer.isActive()
            and 0 <= settle_due_ms <= 5
        ):
            self._pending_coarse_xlim = None
            return False
        viewport = self._pending_coarse_xlim
        self._pending_coarse_xlim = None
        if viewport is None or self._coverage_contains(
            self._display_x_coverage, viewport
        ):
            return False
        coverage = self._buffered_xlim(viewport)
        if coverage is None:
            return False
        actual_coverage = self._refresh_visible_data(
            xlim_override=coverage,
            interactive=True,
        )
        if actual_coverage is not None:
            self._display_x_coverage = actual_coverage
        self._last_coarse_refresh_at = monotonic()
        # Renderer clears _refresh_pending at entry; a coarse frame is not the
        # final frame, so preserve the pending settled refresh for release/
        # quiet-window completion.
        self._refresh_pending = True
        latest = self._latest_target_xlim
        if not self._coverage_contains(self._display_x_coverage, latest):
            self._schedule_coarse_refresh_if_needed(latest)
        return True

    def _settle_visible_data(self, generation):
        """Refresh once for the newest range if it still owns this canvas."""
        if int(generation) != self._interaction_generation:
            return False
        # A held mouse drag remains transform-only even if the pointer pauses
        # longer than the wheel/box quiet window. mouse release re-arms us.
        if self._interaction_depth:
            self._interaction_state = "interactive"
            return False
        if not self._channel_lines or self._primary_xaxis_ax is None:
            self._refresh_pending = False
            self._interaction_state = "idle"
            return False
        try:
            viewport = tuple(
                float(v) for v in self._primary_xaxis_ax.get_xlim()
            )
        except Exception:
            viewport = self._latest_target_xlim
        coverage = self._buffered_xlim(viewport)
        try:
            actual_coverage = self._refresh_visible_data(
                xlim_override=coverage,
                interactive=False,
            )
            if actual_coverage is not None:
                self._display_x_coverage = actual_coverage
        finally:
            self._refresh_pending = False
            self._interaction_state = "idle"
            self._quality._emit_quality_status_changed()
        return True

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
        # Run the generation-gated settled path synchronously. This remains a
        # public/programmatic seam; ViewBox gestures never call it per tick.
        self._settle_visible_data(self._interaction_generation)

    def _flush_pending_export_refresh(self):
        """Commit the latest quiet-window frame before copy/save grabs it.

        Unlike ``_flush_pending_refresh`` this is event-conditional: an idle
        export must not regenerate PlotDataItem geometry.  The current canvas
        generation is passed through the same settled path used by the timer,
        so a stale timer from a cleared plot cannot mutate the export frame.
        """
        if not self._refresh_pending:
            return False
        try:
            self._refresh_timer.stop()
        except Exception:
            pass
        try:
            self._coarse_timer.stop()
        except Exception:
            pass
        self._pending_coarse_xlim = None
        return bool(self._settle_visible_data(self._interaction_generation))

    def _current_pixel_width(self) -> int:
        return self._renderer._current_pixel_width()

    def _effective_pixel_width(self, pixel_width: int,
                               *, source_len=None, dense_count=None) -> int:
        return self._renderer._effective_pixel_width(
            pixel_width, source_len=source_len, dense_count=dense_count,
        )

    def _refresh_visible_data(self, *, xlim_override=None, interactive=False):
        return self._renderer._refresh_visible_data(
            xlim_override=xlim_override,
            interactive=interactive,
        )

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

    def select_overlay_channel(self, name, *, notify=True):
        return OverlayAxisManager.select_overlay_channel(
            self._overlay_axes, name, notify=notify
        )

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
        # Plain/Shift wheel is Y-only. Preserve its immediate Y/tick/visible
        # feedback; no X envelope geometry is invalidated on that path.
        if not bool(modifiers & Qt.ControlModifier):
            consumed = OverlayAxisManager._handle_wheel_dispatch(
                self._overlay_axes,
                delta=delta,
                modifiers=modifiers,
                x_pos=x_pos,
                y_pos=y_pos,
                view_box=view_box,
                scene_pos=scene_pos,
                axis=axis,
            )
            if consumed:
                self._dense_raster.schedule_resuppress()
                self._dense_raster.schedule_rebuild(
                    "y-wheel", delay_ms=self._INTERACTION_SETTLE_MS,
                )
            return consumed
        # OverlayAxisManager historically emitted visible_range_changed on
        # every Ctrl+wheel notch. Suppress that duplicate immediate broadcast
        # and route X-wheel mutations through the same settled tail as drag/
        # box zoom; ViewBox sigXRangeChanged remains live because it is a
        # signal on the ViewBox, not on this canvas.
        was_blocked = self.signalsBlocked()
        self.blockSignals(True)
        try:
            consumed = OverlayAxisManager._handle_wheel_dispatch(
                self._overlay_axes,
                delta=delta,
                modifiers=modifiers,
                x_pos=x_pos,
                y_pos=y_pos,
                view_box=view_box,
                scene_pos=scene_pos,
                axis=axis,
            )
        finally:
            self.blockSignals(was_blocked)
        if consumed:
            self._refresh_pending = True
            self._interaction_state = "settling"
            self._arm_interaction_settle()
        return consumed

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

    def _settle_subplot_layout(self):
        """Finalize active subplot axes before geometry is observed or painted.

        Single end-of-projection seam for subplot full builds AND in-place
        selection deltas. Ordered so each step measures the previous step's
        geometry: the left unifier reads tick-label text width, whose tick set
        depends on the row heights the bottom unifier just assigned, so left
        runs last. Always ends in a layout activation so the realized-geometry
        postcondition never depends on an inner unifier's early return
        (``_unify_subplot_left_axis_widths`` returns early below two axes).
        """
        if not self.axes_list:
            return
        if self._subplot_label_specs:
            self._recheck_subplot_label_placement()
        self._tick_density_controller._apply_tick_density_to_all_axes()
        self._unify_subplot_bottom_axis_heights()
        self._unify_subplot_left_axis_widths()
        self._settle_layout()

    def _subplot_geometry_is_observable(self):
        """Return whether realized subplot geometry can be measured at all.

        A hidden canvas or zero-size viewport has no Qt-realized layout, so it
        can neither prove nor disprove the postcondition. Callers SKIP the
        check in that case rather than failing closed: the fallback would be a
        full rebuild that is equally unrealized, permanently downgrading every
        later delta on an off-screen pane. A hide->show transition delivers a
        resize event, and the existing resize settle path re-measures then.
        """
        if not self.axes_list or not self.isVisible() or not self._glw.isVisible():
            return False
        viewport = self._glw.viewport().rect()
        return viewport.width() > 0 and viewport.height() > 0

    def _subplot_realized_geometry_is_usable(self):
        """Return whether active subplot ViewBoxes materially occupy the viewport.

        Only meaningful when ``_subplot_geometry_is_observable()`` is True.
        """
        if not self.axes_list:
            return False
        viewport = self._glw.viewport().rect()
        viewport_width = float(viewport.width())
        viewport_height = float(viewport.height())
        if viewport_width <= 0.0 or viewport_height <= 0.0:
            return False

        active_count = len(self.axes_list)
        min_width = max(1.0, viewport_width * 0.25)
        min_row_height = max(
            1.0, viewport_height * 0.10 / max(1, active_count)
        )
        tops = []
        bottoms = []
        for handle in self.axes_list:
            plot_item = getattr(handle, "plot_item", None)
            view_box = getattr(handle, "view_box", None)
            if plot_item is None or view_box is None or not plot_item.isVisible():
                return False
            rect = view_box.sceneBoundingRect()
            width = float(rect.width())
            height = float(rect.height())
            top = float(rect.top())
            bottom = float(rect.bottom())
            if not all(
                isfinite(value) for value in (width, height, top, bottom)
            ):
                return False
            if width < min_width or height < min_row_height:
                return False
            tops.append(top)
            bottoms.append(bottom)

        combined_height = max(bottoms) - min(tops)
        return combined_height >= max(1.0, viewport_height * 0.25)

    def _unify_subplot_left_axis_widths(self):
        """Align every subplot's plot-area left edge to a common x.

        pyqtgraph sizes each PlotItem's left ``AxisItem`` to its own
        tick-label text width. In subplot mode that makes rows with wider
        numeric labels start further right, skewing the shared time grid.
        Every left axis is pinned to the widest requirement so the left edges
        land on the same screen x.

        The requirement is measured from the tick STRINGS each axis is
        carrying right now (``pin_left_axes_to_common_width``), never by
        releasing the pin and reading ``AxisItem.width()`` back. That older
        release-and-remeasure was wrong twice over: ``setWidth(None)`` moves
        only size hints while ``width()`` reports realized geometry, so with
        no layout activation in between the read returned the width that was
        already pinned — the pin was a fixed point of itself and could never
        grow — and the value it froze at came from a pre-first-paint
        ``AxisItem.textWidth`` of 30. A row whose labels did not fit (e.g.
        rack force at +/-5000 N) then had every over-wide label silently
        dropped by ``AxisItem.generateDrawSpecs``. Font metrics answer the
        question directly, so the whole dance is gone.

        Pinning is monotonically non-decreasing (the shared helper folds each
        axis's realized ``width()`` into the max), matching the batch
        renderer's semantics: an axis does not shrink back when its labels
        get shorter. See ``ui_kit.axis_metrics`` for the tradeoff note.

        Only meaningful in subplot mode (``_subplot_label_specs`` is the
        subplot marker); short-circuits otherwise so overlay/single paths
        are untouched.
        """
        if not self._subplot_label_specs:
            return
        left_axes = []
        layout_owners = [self._glw.ci]
        seen_owners = {id(self._glw.ci)}
        for handle in self.axes_list:
            ax_item = handle._ax("left") if hasattr(handle, "_ax") else None
            if ax_item is not None:
                left_axes.append(ax_item)
            plot_item = getattr(handle, "plot_item", None)
            if plot_item is not None and id(plot_item) not in seen_owners:
                seen_owners.add(id(plot_item))
                layout_owners.append(plot_item)
        if len(left_axes) < 2:
            return
        # The AxisItem cell is sized by its own PlotItem's layout, not by the
        # outer GraphicsLayout grid, so both have to be activated or the pin
        # never reaches realized geometry.
        pin_left_axes_to_common_width(left_axes, layout_owners=layout_owners)

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
        """Keep border dragging transform/paint-only until one quiet settle."""
        try:
            self.disable_interactive_quality()
        except Exception:
            pass
        try:
            self._refresh_timer.stop()
            self._coarse_timer.stop()
            self._pending_coarse_xlim = None
            if self._channel_lines:
                self._refresh_pending = True
                self._interaction_state = "interactive"
        except Exception:
            pass
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
        """Run label/tick/layout/data work once after the final resize event."""
        try:
            self._resize_settle_timer.stop()
        except Exception:
            pass
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
                self._realize_overlay_axis_columns()
        except Exception:
            pass
        try:
            if self._channel_lines:
                self._refresh_pending = True
                self._interaction_state = "settling"
                self._settle_visible_data(self._interaction_generation)
            else:
                self._refresh_pending = False
                self._interaction_state = "idle"
        except Exception:
            self._refresh_pending = False
            self._interaction_state = "idle"
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

    def _note_aa_frame(self, frame_ms):
        """Owner hook for the resident paint timer (spec 2026-08-15 §3.3).

        The timer measures the frame and hands it to ``owner._note_aa_frame``,
        so every canvas that installs it can route the reading to whatever
        holds its ``AaFrameLatch``. Here that is the quality manager. A bound
        method, not a lambda: the lambda ratchet in
        tests/ui/test_no_lambda_signal_connections.py exists because closures
        over ``self`` on long-lived Qt objects are how this codebase used to
        leak wrappers.
        """
        return self._quality._note_aa_frame(frame_ms)

    def quality_status(self):
        return self._quality.quality_status()

    def has_plotted_result(self) -> bool:
        """Time emptiness: plotted channel tables or a ready dense-raster path.

        Native ``curve_count`` is not the gate — a ready raster covers
        PlotCurveItems and reports 0 while ink is still on screen.
        """
        if mapping_has_items(self._channel_lines) or mapping_has_items(
            self.channel_data
        ):
            return True
        status = self.quality_status() or {}
        return status.get("render_path") == "dense-raster"

    def capture_quality_settled(self) -> bool:
        if not quality_settled_from_status(self.quality_status() or {}):
            return False
        dense = self._dense_raster.quality_status() or {}
        if dense.get("has_dense") and dense.get("state") == "yellow":
            return False
        return True

    def capture_interaction_idle(self) -> bool:
        if self._interaction_state != "idle":
            return False
        if bool(self._refresh_pending):
            return False
        return True

    def capture_cursor_facts(self):
        cursor = self._cursor
        dual = bool(cursor.dual)
        return dual, cursor.capture_dual_geometry()

    def capture_markup_revision(self) -> int:
        return int(self._annotations.markup_revision or 0)

    def iter_transient_overlay_items(self, *, section: str = "unknown"):
        yield from self._cursor.line_items or ()
        yield from iter_axes_rubberband_items(self)

    def presentation_capture_facts(self):
        dual, geometry = self.capture_cursor_facts()
        leaves = ()
        composite = getattr(self._channel_lines, "composite_items", None)
        if callable(composite):
            leaves = tuple(sorted(str(ck) for ck, _name, _pair in composite()))
        elif mapping_has_items(self._channel_lines):
            leaves = tuple(sorted(str(key) for key in self._channel_lines))
        return build_capture_facts(
            host_kind="time",
            visible_and_sized=widget_visible_and_sized(self),
            has_real_result=self.has_plotted_result(),
            quality_settled=self.capture_quality_settled(),
            interaction_idle=self.capture_interaction_idle(),
            cursor_dual=dual,
            cursor_geometry=geometry,
            digest_leaves=leaves,
            markup_revision=self.capture_markup_revision(),
        )

    def grab_pixmap(self, scale: float = 1.0) -> QPixmap:
        self._flush_pending_export_refresh()
        self._dense_raster.flush_pending(self._interaction_generation)
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
