"""Pyqtgraph canvas for one SISO frequency-response result.

The numerical owner supplies the immutable ``FrfResult``.  This widget only
derives presentation arrays (magnitude/phase), applies display-only masking,
and owns the three linked plotting surfaces.
"""
from __future__ import annotations

from html import escape
import logging

import numpy as np
import pyqtgraph as pg
from PyQt5 import sip
from PyQt5.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

from mf4_analyzer.render_profile import (
    envelope_ink_dev_px,
    log_frequency_minor_tick_levels,
    log_frequency_tick_levels,
)
from mf4_analyzer.signal.analysis_defaults import DEFAULT_COHERENCE_THRESHOLD
from mf4_analyzer.signal.frf import (
    magnitude_db,
    magnitude_linear,
    phase_unwrapped_deg,
    phase_wrapped_deg,
)

from .empty_hint import EmptyHintOverlay
from .analysis_axes import _apply_axis_tick_density, _tick_counts_to_density, _visual_padded_bounds
from .context_menu import redesign_pg_context_menu
from .frf_plot_host import FrfStackedPlotHost
from .quality import (
    _BACKSTOP_BLACKLIST_MAX,
    _BACKSTOP_EPOCH_PROPERTY,
    _BACKSTOP_FIRST_AA_MS,
    _BACKSTOP_STEADY_AA_MS,
    _BACKSTOP_STEADY_EMA_ALPHA,
    install_frame_paint_timer,
)
from .quality_backstop import AaFrameLatch
from .remarks import (
    RemarkArtist,
    RemarkInteraction,
    RemarkPoint,
    remark_at_viewport_pos,
    viewport_pos_to_scene,
)
from .overlay_intent import AnalysisRemarkStore, snapshot_frequency_cursor
from mf4_analyzer.ui.view_overlay_state import normalize_cursor_placement
from mf4_analyzer.ui.ultraview_capture_facts import (
    analysis_idle_timer_is_busy,
    build_capture_facts,
    dual_cursor_geometry,
    iter_axes_rubberband_items,
    quality_settled_from_status,
    widget_visible_and_sized,
)
from .renderer import _quantize_y_span_key


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FRF AA BUDGET (spec
# docs/analyzer/specs/2026-08-15-view-switch-quality-settlement-spec.md
# §3.4 / §5, calibrated 2026-08-15 on macOS Cocoa @ dpr 2.0, canvas 1400x900;
# magnitude/phase rows 296 px, coherence row 255 px).
#
# TWO legs, ANDed. Neither is sufficient on its own, and the spec's §5 warning
# is precisely about that:
#
#   * The INK leg is the cost metric (CLAUDE.md "时域渲染成本判据: ink"): a
#     9-point sweep (bins 1k/2k/4k x clean / noisy phase / noisy coherence),
#     summing the ink of all three rows, fits 3.21 ms per 1k dev-px and crosses
#     _BACKSTOP_STEADY_AA_MS (250 ms) at 117k, hence OFF = 115k and
#     ON = OFF x 2/3 = 75k (the same 2:3 hysteresis ratio as the time-domain
#     200k/300k band). The fit is the CONSERVATIVE one: noisy phase measured
#     1.44 ms/k while noisy coherence measured 3.55 ms/k, because the coherence
#     row's Y span is pinned to [0, 1] so a full-row stroke costs more than the
#     same ink spread over short strokes.
#
#   * The POINT leg exists because the ink leg is BLIND to bin count. A
#     "clean" FRF (smooth magnitude, flat phase, flat coherence) has ink ~2.5k
#     no matter how many bins it has, yet its AA frame still grows with the
#     grid: 8.2 ms at 1k bins to 20.7 ms at 4k. Points are summed over the
#     visible curves of all three rows, so ~2k bins is ~6-10k points (which
#     must pass; measured 21 ms) and ~8k bins is ~25-41k points (which must
#     not). ON/OFF = 12k / 18k sits between them, at the same order of
#     magnitude as line_canvas._SPECTRUM_AA_SEGMENT_ON/OFF (5000/8000) scaled
#     for three rows.
#
# All four are CALIBRATIONS, not knobs: change spec §5 first, then re-measure
# on real hardware with `scripts/probe_view_switch_quality.py analysis-frames`
# (an offscreen suite cannot measure paint cost — CLAUDE.md Gotchas). The point
# band in particular is DERIVED from the §5 frame table rather than swept
# directly, and is pending a Windows re-calibration alongside the ink band
# (plan Task 8 risk note).
# ---------------------------------------------------------------------------
_FRF_INK_AA_ON = 75_000
_FRF_INK_AA_OFF = 115_000
_FRF_POINT_AA_ON = 12_000
_FRF_POINT_AA_OFF = 18_000

_DEFAULT_DISPLAY = {
    "magnitude_scale": "db",
    "frequency_scale": "log",
    "phase_mode": "unwrapped",
    "coherence_threshold": DEFAULT_COHERENCE_THRESHOLD,
    "fade_low_coherence": True,
}
_STATE_TEXT = {
    "empty": "请选择输入和输出",
    "stale": "参数已变化，点击计算",
    "progress": "正在计算",
    "error": "计算失败",
}

_DUAL_CURSOR_DELTA_STYLE = (
    "color:#0b7af3; background-color:#e8f1ff; font-weight:700;"
)


def _finite_singleton_mask(x_values, y_values) -> np.ndarray:
    """Return finite samples whose contiguous finite run has length one."""

    finite = np.isfinite(x_values) & np.isfinite(y_values)
    if finite.size == 0:
        return finite
    left = np.r_[False, finite[:-1]]
    right = np.r_[finite[1:], False]
    return finite & ~left & ~right


class _AxisShim:
    __slots__ = ("view_box",)

    def __init__(self, view_box):
        self.view_box = view_box


class _HistoryHandle:
    __slots__ = ("_canvas", "_plot")

    def __init__(self, canvas, plot):
        self._canvas = canvas
        self._plot = plot

    def get_xlim(self):
        xlim = self._canvas.get_xlim()
        if xlim is None:
            raise RuntimeError("FRF canvas has no frequency range")
        return xlim

    def set_xlim(self, lo, hi):
        self._canvas.set_xlim(lo, hi)

    def get_ylim(self):
        return tuple(float(value) for value in self._plot.vb.viewRange()[1])

    def set_ylim(self, lo, hi):
        self._plot.setYRange(float(lo), float(hi), padding=0)


class PgFrfCanvas(QWidget):
    """Three-row magnitude/phase/coherence work surface with shared X."""

    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)
    context_menu_requested = pyqtSignal()
    layout_geometry_changed = pyqtSignal()
    manual_zoom_changed = pyqtSignal(bool)
    markup_revision_changed = pyqtSignal()
    # Emitting this (plus quality_status() below) is what makes
    # chart_stack.cards attach the reader-facing quality dot to an FRF card,
    # exactly as it already does for the time-domain and FFT canvases.
    quality_status_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pgFrfCanvas")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._plot_host = FrfStackedPlotHost(self)
        self._glw = self._plot_host.widget
        layout.addWidget(self._glw)

        self._plot_magnitude, self._plot_phase, self._plot_coherence = self._plot_host.plots
        self._plot = self._plot_magnitude  # AnalysisSectionPage primary surface
        self.plots = self._plot_host.plots
        self._plot_coherence.setLabel("bottom", "Frequency (Hz)")
        self._plot_magnitude.setLabel("left", "Magnitude (dB)")
        self._plot_phase.setLabel("left", "Phase (deg)")
        self._plot_coherence.setLabel("left", "Coherence")
        self._plot_coherence.setYRange(0.0, 1.0, padding=0)
        self._plot_coherence.vb.enableAutoRange(axis="y", enable=False)
        normal_pen = pg.mkPen("#1769e0", width=1.6)
        faded_pen = pg.mkPen((23, 105, 224, 70), width=1.4)
        coherence_pen = pg.mkPen("#0f9f83", width=1.5)
        # AA-OFF at construction (spec 2026-08-15 §3.4): a freshly built FRF
        # used to paint its first frame antialiased from inside the call that
        # created it, which is how a 2k-bin noisy result charged 527 ms to a
        # View switch. AA now lands on the discrete timer below, after the
        # gate has seen the real geometry.
        self._magnitude_curve = self._plot_magnitude.plot(
            [], [], pen=normal_pen, connect="finite", antialias=False
        )
        self._magnitude_low_curve = self._plot_magnitude.plot(
            [], [], pen=faded_pen, connect="finite", antialias=False,
        )
        self._phase_curve = self._plot_phase.plot(
            [], [], pen=normal_pen, connect="finite", antialias=False
        )
        self._phase_low_curve = self._plot_phase.plot(
            [], [], pen=faded_pen, connect="finite", antialias=False,
        )
        self._magnitude_low_points = self._plot_magnitude.plot(
            [], [], pen=None, symbol="o", symbolSize=4.5, symbolPen=None,
            symbolBrush=pg.mkBrush(23, 105, 224, 70),
        )
        self._phase_low_points = self._plot_phase.plot(
            [], [], pen=None, symbol="o", symbolSize=4.5, symbolPen=None,
            symbolBrush=pg.mkBrush(23, 105, 224, 70),
        )
        self._magnitude_singleton_points = self._plot_magnitude.plot(
            [], [], pen=None, symbol="o", symbolSize=4.5, symbolPen=None,
            symbolBrush=pg.mkBrush(23, 105, 224, 255),
        )
        self._phase_singleton_points = self._plot_phase.plot(
            [], [], pen=None, symbol="o", symbolSize=4.5, symbolPen=None,
            symbolBrush=pg.mkBrush(23, 105, 224, 255),
        )
        self._coherence_singleton_points = self._plot_coherence.plot(
            [], [], pen=None, symbol="o", symbolSize=4.5, symbolPen=None,
            symbolBrush=pg.mkBrush(15, 159, 131, 255),
        )
        self._coherence_curve = self._plot_coherence.plot(
            [], [], pen=coherence_pen, connect="finite", antialias=False
        )
        # Keep the settled FRF curves crisp, but do not rasterize five
        # full-length AA curves on every interactive zoom frame.  This mirrors
        # the FFT canvas policy: AA drops immediately, then comes back after a
        # short hands-off interval.
        self._aa_on = False
        self._aa_idle_timer = QTimer(self)
        self._aa_idle_timer.setSingleShot(True)
        self._aa_idle_timer.setInterval(150)
        self._aa_idle_timer.timeout.connect(self._enable_idle_quality)
        # A SEPARATE zero-delay timer, never `_aa_idle_timer.start(0)`:
        # QTimer.start(int) rewrites the interval PERMANENTLY, so reusing the
        # idle timer would silently collapse the 150 ms quiet window that the
        # continuous pan/zoom path depends on (spec §3.2, the Qt trap).
        # Rendering a new result is a DISCRETE event — nothing follows it —
        # so there is nothing to merge and nothing to wait for.
        self._discrete_aa_timer = QTimer(self)
        self._discrete_aa_timer.setSingleShot(True)
        self._discrete_aa_timer.setInterval(0)
        self._discrete_aa_timer.timeout.connect(self._enable_idle_quality)
        self.destroyed.connect(self._stop_aa_timers)
        # Hysteresis state for the two AA legs (ink + drawn points). Both are
        # re-seeded whenever a new result lands, because a replacement result
        # changes the very geometry the previous verdict was about.
        self._frf_ink_allowed = False
        self._frf_ink_seeded = False
        self._frf_point_allowed = False
        self._frf_point_seeded = False
        self._frf_last_point_total = 0
        self._aa_block_reason = None
        self._last_quality_status = None
        # --- measured-frame backstop (spec §3.3 / §3.4) -------------------
        # Everything above is a PREDICTION. The latch is what measures the
        # frame that actually happened, so a wrong prediction costs at most one
        # bad frame per view signature. Same calibrated ceilings as the
        # time-domain canvas: those are the user's patience, not a property of
        # a particular canvas family.
        self._aa_latch = AaFrameLatch(
            _BACKSTOP_FIRST_AA_MS,
            _BACKSTOP_STEADY_AA_MS,
            _BACKSTOP_STEADY_EMA_ALPHA,
            _BACKSTOP_BLACKLIST_MAX,
        )
        self._aa_backstop_armed = False
        self._last_frame_paint_ms = None
        self._backstop_timer = QTimer(self)
        self._backstop_timer.setSingleShot(True)
        self._backstop_timer.timeout.connect(self._on_aa_backstop_timeout)
        if not install_frame_paint_timer(self):
            logger.warning(
                "FRF canvas frame-paint timer not installed; the measured-AA-"
                "frame backstop is inactive for this canvas",
            )
        self._threshold_line = pg.InfiniteLine(
            pos=_DEFAULT_DISPLAY["coherence_threshold"],
            angle=0,
            movable=False,
            pen=pg.mkPen("#d97706", width=1.2, style=Qt.DashLine),
        )
        self._plot_coherence.addItem(self._threshold_line)

        self._cursor_lines = self._make_cursor_lines("#64748b")
        self._cursor_a_lines = self._make_cursor_lines("#1769e0")
        self._cursor_b_lines = self._make_cursor_lines("#d97706")
        self._cursor_mode = "off"
        self._cursor_a_frequency = None
        self._cursor_b_frequency = None
        self._next_dual_cursor = "a"

        # The three FRF panels share the standard pyqtgraph point-remark
        # artist/interaction contract used by FFT and heatmap canvases.  The
        # only FRF-specific part lives in _remark_point_at: it chooses one
        # panel's nearest physical-frequency sample and preserves Hz labels on
        # log axes whose ViewBox coordinates are log10(Hz).
        self._remarks = []
        self._remark_intent = AnalysisRemarkStore()
        self._remark_enabled = False
        self.markup_revision = 0
        self._remark_artist = RemarkArtist(on_moved=self._bump_markup_revision)
        self._remark_interaction = RemarkInteraction(
            add_at_viewport_pos=self._add_remark_at_viewport_pos,
            remove_at_viewport_pos=self._remove_remark_at_viewport_pos,
            remark_at_viewport_pos=self._remark_item_at_viewport_pos,
        )
        self._remark_viewport = self._glw.viewport()
        self._remark_viewport.setMouseTracking(True)
        self._remark_viewport.installEventFilter(self)

        self.axes_list = [_AxisShim(plot.vb) for plot in self.plots]
        self._channel_lines = {
            name: (_HistoryHandle(self, plot), None)
            for name, plot in zip(
                ("magnitude", "phase", "coherence"), self.plots
            )
        }
        self._result = None
        self._context = {}
        self._display_params = dict(_DEFAULT_DISPLAY)
        self._draw_frequencies = np.empty(0, dtype=float)
        self._draw_magnitude = np.empty(0, dtype=float)
        self._draw_phase = np.empty(0, dtype=float)
        self._draw_coherence = np.empty(0, dtype=float)
        self._state = "empty"
        self._empty_hint_item = None
        self._empty_hint_text = ""
        self._replot_callbacks = []
        self._mouse_mode_controller = None
        self._copy_image_handler = None
        self._empty_hint = EmptyHintOverlay(
            viewbox_getter=lambda: self._plot_magnitude.vb,
            reposition_slot=self._reposition_empty_hint,
            on_state=self._store_empty_hint_state,
        )
        self._scene_mouse_slot = self._on_scene_mouse_moved
        self._glw.scene().sigMouseMoved.connect(self._scene_mouse_slot)
        self._scene_click_slot = self._on_scene_mouse_clicked
        self._glw.scene().sigMouseClicked.connect(self._scene_click_slot)
        self._frequency_range_slot = self._sync_frequency_ticks
        self._plot_magnitude.vb.sigXRangeChanged.connect(
            self._frequency_range_slot
        )
        self._interactive_range_slot = self._on_interactive_range_changed
        for plot in self.plots:
            plot.vb.sigRangeChangedManually.connect(
                self._interactive_range_slot
            )
        self.set_state("empty")
        self._plot_host.schedule_alignment()

    def _store_empty_hint_state(self, item, text):
        self._empty_hint_item = item
        self._empty_hint_text = text

    def _make_cursor_lines(self, color):
        lines = []
        for plot in self.plots:
            line = pg.InfiniteLine(
                angle=90, movable=False, pen=pg.mkPen(color, width=1.2)
            )
            line.setZValue(50)
            line.hide()
            plot.addItem(line, ignoreBounds=True)
            lines.append(line)
        return lines

    def _interactive_curves(self):
        return (
            self._magnitude_curve,
            self._magnitude_low_curve,
            self._phase_curve,
            self._phase_low_curve,
            self._coherence_curve,
        )

    @staticmethod
    def _set_curve_aa(curve, on) -> None:
        on = bool(on)
        try:
            curve.opts["antialias"] = on
        except (AttributeError, TypeError):
            pass
        # pyqtgraph applies PlotDataItem AA to its child PlotCurveItem only
        # through setData().  Zooming intentionally does not call setData(),
        # so update the painted child directly.
        child = getattr(curve, "curve", None)
        if child is not None:
            try:
                child.opts["antialias"] = on
                child.update()
            except (AttributeError, RuntimeError, TypeError):
                pass

    def _ink_rows(self):
        """The three (ViewBox owner, curves that paint into it) pairs.

        The faded low-coherence curves carry the FULL magnitude/phase arrays
        (see ``_apply_curve_data``), so when fading is on they are a second
        full-length stroke per row and must be counted — their ink is real
        ink. The scatter overlays are not: they mark isolated bins only.
        """
        return (
            (self._plot_magnitude,
             (self._magnitude_curve, self._magnitude_low_curve)),
            (self._plot_phase,
             (self._phase_curve, self._phase_low_curve)),
            (self._plot_coherence, (self._coherence_curve,)),
        )

    def _frf_draw_totals(self):
        """Return ``(ink_dev_px, drawn_points)`` over the three rows, or None.

        One walk for both legs: each visible curve's Y array is read once and
        charged to its own row's Y span and row height, because the three rows
        have independent Y geometry (the coherence row's span is pinned to
        [0, 1], which is why a full-height coherence stroke is the most
        expensive ink this canvas can paint).

        ``None`` means "could not measure", which is NOT the same as zero —
        CLAUDE.md's ink rule is explicit that an unmeasured curve must never be
        treated as costing nothing.
        """
        try:
            dpr = float(self.devicePixelRatioF())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
        total_ink = 0.0
        total_points = 0
        for plot, curves in self._ink_rows():
            try:
                view_box = plot.vb
                # enableAutoRange is applied LAZILY, and the discrete 0 ms
                # timer can run before the first paint has flushed it. Without
                # this the Y span read below would be the PREVIOUS result's.
                view_box.updateAutoRange()
                lo, hi = view_box.viewRange()[1]
                y_span = float(hi) - float(lo)
                row_height = float(view_box.sceneBoundingRect().height())
            except (AttributeError, IndexError, RuntimeError, TypeError,
                    ValueError):
                return None
            for curve in curves:
                try:
                    if not curve.isVisible():
                        continue
                    values = curve.getData()[1]
                except (AttributeError, IndexError, RuntimeError, TypeError):
                    return None
                if values is None:
                    continue
                total_ink += envelope_ink_dev_px(
                    values,
                    y_span=y_span,
                    row_height_px=row_height,
                    dpr=dpr,
                )
                total_points += int(np.asarray(values).size)
        return total_ink, total_points

    def _frf_ink_total(self):
        """Summed three-row ink in device pixels, or ``None`` if unmeasurable."""
        totals = self._frf_draw_totals()
        return None if totals is None else totals[0]

    def _frf_point_total(self):
        """Summed drawn points across the three rows' visible curves."""
        totals = self._frf_draw_totals()
        return None if totals is None else totals[1]

    def _frf_aa_allowed(self) -> bool:
        """AND of the ink leg and the drawn-point leg, both with hysteresis.

        The two legs are orthogonal, and the spec §5 calibration is explicit
        that neither substitutes for the other: a clean FRF keeps ink flat
        while its frame cost grows with bin count, and a 2k-bin noisy FRF
        keeps its point count low while its ink explodes. Rejecting on either
        is correct; requiring both to fail would let each pathology through.
        """
        totals = self._frf_draw_totals()
        if totals is None:
            # Unknown is not cheap. Refuse this frame WITHOUT touching the
            # hysteresis state, so one unreadable curve cannot re-seed the
            # gate on a fiction.
            self._aa_block_reason = "unknown-ink"
            return False
        ink, points = totals
        self._frf_last_point_total = points
        if not self._frf_ink_seeded:
            # A replacement result is seeded against the OFF threshold, so it
            # starts allowed only if it is comfortably affordable.
            self._frf_ink_allowed = ink <= _FRF_INK_AA_OFF
            self._frf_ink_seeded = True
        elif ink <= _FRF_INK_AA_ON:
            self._frf_ink_allowed = True
        elif ink > _FRF_INK_AA_OFF:
            self._frf_ink_allowed = False
        if not self._frf_point_seeded:
            self._frf_point_allowed = points <= _FRF_POINT_AA_OFF
            self._frf_point_seeded = True
        elif points <= _FRF_POINT_AA_ON:
            self._frf_point_allowed = True
        elif points > _FRF_POINT_AA_OFF:
            self._frf_point_allowed = False
        if not self._frf_ink_allowed:
            self._aa_block_reason = "high-ink"
            return False
        if not self._frf_point_allowed:
            self._aa_block_reason = "high-density"
            return False
        self._aa_block_reason = None
        return True

    def _reset_aa_gates(self) -> None:
        """Re-seed both AA legs for a replacement result."""
        self._frf_ink_allowed = False
        self._frf_ink_seeded = False
        self._frf_point_allowed = False
        self._frf_point_seeded = False

    def _frf_view_signature(self):
        """Identity of the geometry an AA verdict was measured for.

        Everything that changes what gets painted, and nothing that does not:
        the bin count, each row's quantized Y span and integer row height, the
        pixel width, and the display parameters that reshape the curves
        (frequency/magnitude scale, phase wrapping, fading and its threshold).
        Used as the backstop blacklist key, so it must be hashable and stable
        across a rebuild of the same view. It flushes the lazy auto-range for
        the same reason ``_frf_draw_totals`` does, and so that the key a
        verdict is FILED under is read from the same geometry the verdict was
        MEASURED on — otherwise a blacklist entry could never be matched back.
        """
        try:
            spans = []
            heights = []
            for plot in self.plots:
                view_box = plot.vb
                view_box.updateAutoRange()
                lo, hi = view_box.viewRange()[1]
                spans.append(_quantize_y_span_key(float(hi) - float(lo)))
                heights.append(
                    int(round(view_box.sceneBoundingRect().height()))
                )
            width = int(
                round(self._plot_magnitude.vb.sceneBoundingRect().width())
            )
        except (AttributeError, IndexError, RuntimeError, TypeError,
                ValueError):
            return None
        params = self._display_params
        return (
            int(self._draw_frequencies.size),
            tuple(spans),
            tuple(heights),
            width,
            str(params.get("frequency_scale")),
            str(params.get("magnitude_scale")),
            str(params.get("phase_mode")),
            bool(params.get("fade_low_coherence")),
            float(params.get("coherence_threshold", 0.0)),
        )

    def _aa_timer_alive(self, timer):
        if timer is None:
            return None
        try:
            if sip.isdeleted(self) or sip.isdeleted(timer):
                return None
        except RuntimeError:
            # sip wrapper already gone; nothing left to start/stop.
            return None
        return timer

    def _stop_aa_timers(self, *_args) -> None:
        for name in ("_aa_idle_timer", "_discrete_aa_timer"):
            timer = self._aa_timer_alive(getattr(self, name, None))
            if timer is None:
                continue
            try:
                timer.stop()
            except RuntimeError:
                # QTimer C++ object already deleted with the canvas.
                continue

    def _aa_timers_active(self) -> bool:
        for name in ("_aa_idle_timer", "_discrete_aa_timer"):
            timer = self._aa_timer_alive(getattr(self, name, None))
            if timer is None:
                continue
            try:
                if timer.isActive():
                    return True
            except RuntimeError:
                continue
        return False

    def arm_discrete_aa(self) -> None:
        """Render a result AA-off now and settle AA on the next event turn.

        Spec §3.4 step 1. The caller (a recompute, a display-parameter change,
        a View switch) gets a cheap non-AA frame and returns; the antialiased
        frame — if the gate allows one at all — arrives one event-loop turn
        later instead of inside the call.
        """
        for curve in self._interactive_curves():
            self._set_curve_aa(curve, False)
        self._aa_on = False
        self._close_aa_backstop_session()
        self._reset_aa_gates()
        self._aa_block_reason = None
        self._stop_aa_timers()
        timer = self._aa_timer_alive(getattr(self, "_discrete_aa_timer", None))
        if timer is not None:
            timer.start()
        self._emit_quality_status()

    def disable_interactive_quality(self) -> None:
        """Use AA-off curves while an FRF pan or zoom is in progress."""
        timers_were_active = self._aa_timers_active()
        self._stop_aa_timers()
        self._close_aa_backstop_session()
        if not self._aa_on:
            # Hot path: after the first pan/zoom tick AA is already off. Only
            # rebuild the reader-facing status when cancelling a pending
            # upgrade actually changed it (yellow -> red).
            if timers_were_active:
                self._emit_quality_status()
            return
        for curve in self._interactive_curves():
            self._set_curve_aa(curve, False)
        self._aa_on = False
        self._glw.update()
        self._emit_quality_status()

    def schedule_idle_quality(self) -> None:
        """Restore anti-aliasing only after the interactive gesture settles."""
        timer = self._aa_timer_alive(getattr(self, "_aa_idle_timer", None))
        if timer is not None:
            timer.start()
        self._emit_quality_status()

    def _enable_idle_quality(self) -> None:
        if sip.isdeleted(self):
            return
        if self._aa_on:
            self._stop_aa_timers()
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            # Still hands-on: fall back to the continuous path's quiet window
            # rather than re-deciding on every event turn.
            self.schedule_idle_quality()
            return
        self._stop_aa_timers()
        signature = self._frf_view_signature()
        if self._aa_latch.blocked(signature):
            # This geometry already paid its one bad AA frame.
            self._aa_block_reason = "aa-backstop"
            self._emit_quality_status()
            return
        if not self._frf_aa_allowed():
            self._emit_quality_status()
            return
        for curve in self._interactive_curves():
            self._set_curve_aa(curve, True)
        self._aa_on = True
        self._open_aa_backstop_session(signature)
        self._glw.update()
        self._emit_quality_status()

    # ------------------------------------------------------------------
    # Measured-frame backstop (spec §3.3): the Qt half. The arithmetic and
    # the bookkeeping live in AaFrameLatch, which is safe to run inside a
    # paint; turning AA back off is a scene mutation and is not, so it is
    # deferred onto a zero-delay, epoch-tagged timer.
    # ------------------------------------------------------------------

    def _open_aa_backstop_session(self, signature) -> None:
        self._aa_latch.open(signature)
        self._aa_backstop_armed = True

    def _close_aa_backstop_session(self) -> None:
        if not self._aa_backstop_armed:
            return
        self._aa_backstop_armed = False
        self._aa_latch.close()

    def _note_aa_frame(self, frame_ms) -> None:
        """Feed one measured AA frame to the latch. Called FROM ``paintEvent``.

        The armed flag is the pairing token: it is raised only when AA is
        actually switched on and dropped on every path that switches it off,
        so a non-AA frame can never be miscounted as "the first AA frame".
        """
        if not self._aa_backstop_armed:
            return
        trip = self._aa_latch.note_frame(frame_ms)
        if trip is not None:
            self._trip_aa_backstop(trip[0], trip[1])

    def _trip_aa_backstop(self, reason: str, measured_ms: float) -> None:
        # Disarm FIRST: further frames of this session must not re-trip while
        # the deferred disable is still in flight.
        self._aa_backstop_armed = False
        self._aa_latch.reason = (str(reason), float(measured_ms))
        timer = self._aa_timer_alive(getattr(self, "_backstop_timer", None))
        if timer is None:
            logger.warning(
                "FRF AA backstop tripped (%s, %.1f ms) but its timer is gone; "
                "antialiasing stays on for this session",
                reason, float(measured_ms),
            )
            return
        try:
            timer.setProperty(
                _BACKSTOP_EPOCH_PROPERTY, int(self._aa_latch.epoch)
            )
            timer.start(0)
        except RuntimeError:
            logger.warning(
                "FRF AA backstop trip could not be queued", exc_info=True,
            )

    def _on_aa_backstop_timeout(self) -> None:
        """Deferred half of a trip: drop AA, but only for the epoch measured."""
        try:
            epoch = int(
                self._backstop_timer.property(_BACKSTOP_EPOCH_PROPERTY)
            )
        except (RuntimeError, TypeError, ValueError):
            return
        if epoch != int(self._aa_latch.epoch):
            # A rebuild or a newer session already superseded what was
            # measured; tearing AA off the CURRENT session would be wrong.
            return
        self.disable_interactive_quality()
        self._aa_block_reason = "aa-backstop"
        self._emit_quality_status()

    # ------------------------------------------------------------------
    # AA status (reader-facing traffic light). Shape mirrors
    # PgLineCanvas.quality_status so chart_stack.cards can consume both
    # without knowing which canvas it holds.
    # ------------------------------------------------------------------

    def quality_status(self):
        """Return the ``{state, tooltip}`` dict consumed by the quality dot."""
        if self._result is None or not self._draw_frequencies.size:
            return {
                "state": "red",
                "tooltip": "抗锯齿未激活：无曲线",
                "block_reason": "no-curves",
            }
        judged = []
        for curve in self._interactive_curves():
            try:
                if curve.isVisible():
                    judged.append(bool(curve.opts.get("antialias", False)))
            except (AttributeError, RuntimeError, TypeError):
                judged.append(False)
        if self._aa_on and judged and all(judged):
            return {"state": "green", "tooltip": "抗锯齿已完成"}
        if self._aa_timers_active():
            return {"state": "yellow", "tooltip": "抗锯齿等待空闲刷新"}
        reason = self._aa_block_reason
        if reason == "high-ink":
            return {
                "state": "red",
                "tooltip": (
                    "抗锯齿未激活：相位翻转/相干填满绘图区，绘制量超预算"
                ),
                "block_reason": "high-ink",
            }
        if reason == "high-density":
            return {
                "state": "red",
                "tooltip": (
                    f"抗锯齿未激活：曲线密度 {self._frf_last_point_total} "
                    f"> {_FRF_POINT_AA_OFF}"
                ),
                "block_reason": "high-density",
            }
        if reason == "aa-backstop":
            return {
                "state": "red",
                "tooltip": "抗锯齿未激活：实测帧超时",
                "block_reason": "aa-backstop",
            }
        if reason == "unknown-ink":
            return {
                "state": "red",
                "tooltip": "抗锯齿未激活：绘制量无法测量",
                "block_reason": "unknown-ink",
            }
        return {"state": "red", "tooltip": "抗锯齿未激活", "block_reason": None}

    def _emit_quality_status(self) -> None:
        """Emit ``quality_status_changed`` only when the status changes."""
        try:
            status = self.quality_status()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            logger.warning("FRF quality status unavailable", exc_info=True)
            return
        if status == self._last_quality_status:
            return
        self._last_quality_status = status
        self.quality_status_changed.emit(status)

    def _on_interactive_range_changed(self, *_args) -> None:
        """Treat native ViewBox wheel/pan updates like modifier-wheel zoom."""
        self.disable_interactive_quality()
        self.schedule_idle_quality()

    def _reposition_empty_hint(self, *_args):
        self._empty_hint.reposition()

    def show_empty_hint(self, text):
        self._empty_hint.show(text)

    def clear_empty_hint(self):
        self._empty_hint.clear()

    def state(self) -> str:
        return self._state

    def set_state(self, state: str, detail=None) -> None:
        token = str(state)
        if token not in _STATE_TEXT:
            raise ValueError(f"unknown FRF canvas state: {state!r}")
        self._state = token
        text = _STATE_TEXT[token]
        if detail:
            text = f"{text}：{detail}"
        self.show_empty_hint(text)

    def show_progress(self) -> None:
        self.set_state("progress")

    def show_error(self, detail=None) -> None:
        self.set_state("error", detail)

    def mark_stale(self) -> None:
        self.set_state("stale")

    def set_result(self, result, display_params=None, context=None) -> None:
        frequencies = np.asarray(result.frequencies, dtype=np.float64)
        transfer = np.asarray(result.transfer, dtype=np.complex128)
        coherence = np.asarray(result.coherence, dtype=np.float64)
        if frequencies.ndim != 1 or transfer.ndim != 1 or coherence.ndim != 1:
            raise ValueError("FRF result arrays must be one-dimensional")
        if not (frequencies.size == transfer.size == coherence.size):
            raise ValueError("FRF result arrays must have equal length")
        # Point labels include panel values, so a new calculation must
        # re-snap Y. Intent stays; Qt items are a projection.
        self._drop_remark_projection()
        self._result = result
        self._context = dict(context or {})
        if display_params:
            self._display_params.update(
                self._normalise_display_params(dict(display_params))
            )
        self._state = "ready"
        self._hide_frequency_cursor_items()
        self.clear_empty_hint()
        self._render_result()
        # Spec §3.4 step 1: the caller returns after a cheap non-AA frame; the
        # gate and (if it allows one) the AA frame land on the next event turn.
        self.arm_discrete_aa()
        self._plot_host.schedule_alignment()
        self._run_replot_callbacks()
        self._project_remarks()
        self._project_frequency_cursors()
        self.layout_geometry_changed.emit()

    def set_display_params(self, params) -> None:
        old_xlim = self.get_xlim()
        self._display_params.update(
            self._normalise_display_params(dict(params or {}))
        )
        if self._result is not None:
            # Magnitude scale, phase wrapping, and coherence presentation can
            # all change the value written into an existing remark label.
            self._drop_remark_projection()
            self._render_result()
            if old_xlim is not None:
                self.set_xlim(*old_xlim)
            # Magnitude scale / phase wrapping / fading all reshape the drawn
            # curves, so the previous AA verdict was about a different picture.
            self.arm_discrete_aa()
            self._project_remarks()
            self._project_frequency_cursors()
            self.layout_geometry_changed.emit()
            self._plot_host.schedule_alignment()

    @staticmethod
    def _normalise_display_params(params: dict) -> dict:
        """Strip/lower frequency_scale so ``"Log"`` matches batch FRF specs."""
        if "frequency_scale" in params:
            params["frequency_scale"] = str(
                params["frequency_scale"]
            ).strip().lower()
        return params

    def display_params(self) -> dict:
        return dict(self._display_params)

    def _render_result(self) -> None:
        result = self._result
        if result is None:
            return
        frequencies = np.asarray(result.frequencies, dtype=np.float64)
        transfer = np.asarray(result.transfer, dtype=np.complex128)
        coherence = np.asarray(result.coherence, dtype=np.float64)
        log_frequency = str(self._display_params["frequency_scale"]).lower() == "log"
        mask = frequencies > 0 if log_frequency else np.ones(frequencies.shape, dtype=bool)
        self._draw_frequencies = frequencies[mask].copy()
        draw_transfer = transfer[mask]
        self._draw_coherence = coherence[mask].copy()

        if str(self._display_params["magnitude_scale"]).lower() == "db":
            magnitude = magnitude_db(draw_transfer)
            self._plot_magnitude.setLabel("left", "Magnitude (dB)")
        else:
            magnitude = magnitude_linear(draw_transfer)
            self._plot_magnitude.setLabel(
                "left", f"Magnitude ({self._ratio_unit_label()})"
            )
        self._draw_magnitude = magnitude
        if str(self._display_params["phase_mode"]).lower() == "unwrapped":
            self._draw_phase = phase_unwrapped_deg(draw_transfer)
        else:
            self._draw_phase = phase_wrapped_deg(draw_transfer)

        for plot in self.plots:
            plot.setLogMode(x=log_frequency, y=False)
        self._sync_frequency_ticks()
        self._threshold_line.setValue(float(self._display_params["coherence_threshold"]))
        self._apply_curve_data()
        self._plot_coherence.setYRange(0.0, 1.0, padding=0)
        self._plot_coherence.vb.enableAutoRange(axis="y", enable=False)
        if self._draw_frequencies.size:
            self.reset_view_to_data_extents()

    def _ratio_unit_label(self) -> str:
        output_unit = str(self._context.get("output_unit") or "").strip()
        input_unit = str(self._context.get("input_unit") or "").strip()
        if output_unit and input_unit:
            return "1" if output_unit == input_unit else f"{output_unit}/{input_unit}"
        if output_unit:
            return output_unit
        if input_unit:
            return f"1/{input_unit}"
        return "ratio"

    def _magnitude_unit_suffix(self) -> str:
        """Return the unit written after the cursor's ``|H|`` value.

        The magnitude panel's own axis label already carries this unit; the
        readout used to print a bare number, so a dB figure and a linear ratio
        were indistinguishable. ``"ratio"``/``"1"`` are dropped because a
        trailing ``1`` reads as part of the number.
        """
        if str(self._display_params.get("magnitude_scale")).lower() == "db":
            return " dB"
        unit = self._ratio_unit_label()
        return "" if unit in ("ratio", "1") else f" {unit}"

    def _apply_curve_data(self) -> None:
        threshold = float(self._display_params["coherence_threshold"])
        fade = bool(self._display_params["fade_low_coherence"])
        low = ~np.isfinite(self._draw_coherence) | (
            self._draw_coherence < threshold
        )
        if fade:
            high_magnitude = self._draw_magnitude.copy()
            high_phase = self._draw_phase.copy()
            high_magnitude[low] = np.nan
            high_phase[low] = np.nan
            low_magnitude = self._draw_magnitude
            low_phase = self._draw_phase
            low_only_magnitude = np.where(low, self._draw_magnitude, np.nan)
            low_only_phase = np.where(low, self._draw_phase, np.nan)
        else:
            high_magnitude = self._draw_magnitude
            high_phase = self._draw_phase
            low_magnitude = np.empty(0, dtype=float)
            low_phase = np.empty(0, dtype=float)
            low_only_magnitude = np.empty(0, dtype=float)
            low_only_phase = np.empty(0, dtype=float)
        self._magnitude_curve.setData(
            self._draw_frequencies, high_magnitude, connect="finite"
        )
        self._phase_curve.setData(
            self._draw_frequencies, high_phase, connect="finite"
        )
        low_x = self._draw_frequencies if fade else np.empty(0, dtype=float)
        self._magnitude_low_curve.setData(low_x, low_magnitude, connect="finite")
        self._phase_low_curve.setData(low_x, low_phase, connect="finite")
        # ScatterPlotItem computes bounds with nanmin/nanmax.  Supplying a
        # full-length all-NaN array raises during Qt auto-range, so point
        # overlays receive only actual finite low-coherence bins.  This also
        # keeps an isolated low bin visible even when line gaps surround it.
        magnitude_singletons = _finite_singleton_mask(
            self._draw_frequencies, high_magnitude
        )
        phase_singletons = _finite_singleton_mask(
            self._draw_frequencies, high_phase
        )
        self._magnitude_singleton_points.setData(
            self._draw_frequencies[magnitude_singletons],
            high_magnitude[magnitude_singletons],
        )
        self._phase_singleton_points.setData(
            self._draw_frequencies[phase_singletons], high_phase[phase_singletons]
        )
        if fade:
            low_magnitude_singletons = _finite_singleton_mask(
                self._draw_frequencies, low_only_magnitude
            )
            low_phase_singletons = _finite_singleton_mask(
                self._draw_frequencies, low_only_phase
            )
            self._magnitude_low_points.setData(
                self._draw_frequencies[low_magnitude_singletons],
                low_only_magnitude[low_magnitude_singletons],
            )
            self._phase_low_points.setData(
                self._draw_frequencies[low_phase_singletons],
                low_only_phase[low_phase_singletons],
            )
        else:
            self._magnitude_low_points.setData([], [])
            self._phase_low_points.setData([], [])
        coherence_singletons = _finite_singleton_mask(
            self._draw_frequencies, self._draw_coherence
        )
        self._coherence_singleton_points.setData(
            self._draw_frequencies[coherence_singletons],
            self._draw_coherence[coherence_singletons],
        )
        self._magnitude_low_curve.setVisible(fade)
        self._phase_low_curve.setVisible(fade)
        self._magnitude_low_points.setVisible(fade)
        self._phase_low_points.setVisible(fade)
        self._coherence_curve.setData(
            self._draw_frequencies, self._draw_coherence, connect="finite"
        )

    def _sync_frequency_ticks(self, *_args) -> None:
        axes = [plot.getAxis("bottom") for plot in self.plots]
        if not self._is_log_frequency():
            # A restored linear scale may reuse this axis after a log view.
            # Do not let its former 2..9 decade positions shorten unrelated
            # adaptive linear ticks in the custom draw path.
            for axis in axes:
                setattr(axis, "_frf_minor_tick_values", ())
                axis.setTicks(None)
            return
        lo, hi = self._plot_magnitude.vb.viewRange()[0]
        # Shared with the batch report's log frequency axis so a zoom and its
        # exported PNG agree on which frequencies get labelled.
        ticks = log_frequency_tick_levels(float(lo), float(hi))
        if not ticks:
            # Degenerate view range mid-transition; keep the existing row
            # rather than blanking the axis.
            return
        minor_ticks = log_frequency_minor_tick_levels(lo, hi, ticks)
        for axis in axes:
            setter = getattr(axis, "set_frf_log_ticks", None)
            if callable(setter):
                setter(ticks, minor_ticks)
            else:
                axis.setTicks([
                    list(ticks), [(value, "") for value in minor_ticks],
                ])

    def set_xlim(self, xmin, xmax) -> None:
        lo, hi = float(xmin), float(xmax)
        if hi <= lo:
            raise ValueError("xmax must be greater than xmin")
        if self._is_log_frequency() and lo <= 0:
            positive = self._draw_frequencies[self._draw_frequencies > 0]
            if positive.size:
                lo = float(positive.min())
        self._plot_magnitude.setXRange(
            self._hz_to_view_x(lo), self._hz_to_view_x(hi), padding=0
        )

    def get_xlim(self):
        if self._result is None:
            return None
        view_range = self._plot_magnitude.vb.viewRange()[0]
        return tuple(self._view_x_to_hz(value) for value in view_range)

    def get_data_x_union(self):
        """Return ``(lo, hi)`` of the plotted analysis time window, or None.

        FRF's chart X is frequency, but「全部」/ draft-local checks need the
        *time* extent that produced this result. Prefer
        ``FrfEffectiveFacts.time_start/time_end`` (same contract shape as
        ``PgTimedomainCanvas.get_data_x_union``: raw data span or None).
        """
        result = self._result
        if result is None:
            return None
        effective = getattr(result, "effective", None)
        if effective is None:
            return None
        try:
            lo = float(effective.time_start)
            hi = float(effective.time_end)
        except (TypeError, ValueError, AttributeError):
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        return lo, hi

    def _is_log_frequency(self) -> bool:
        return str(self._display_params.get("frequency_scale")).lower() == "log"

    def _hz_to_view_x(self, frequency: float) -> float:
        value = float(frequency)
        if not self._is_log_frequency():
            return value
        if value <= 0:
            raise ValueError("log-frequency view requires positive Hz")
        return float(np.log10(value))

    def _view_x_to_hz(self, coordinate: float) -> float:
        value = float(coordinate)
        return float(10.0 ** value) if self._is_log_frequency() else value

    def set_ylim(self, panel, ymin, ymax) -> None:
        plot = self._plot_for_panel(panel)
        lo, hi = float(ymin), float(ymax)
        if hi <= lo:
            raise ValueError("ymax must be greater than ymin")
        if str(panel) == "coherence":
            lo, hi = 0.0, 1.0
        plot.vb.enableAutoRange(axis="y", enable=False)
        plot.setYRange(lo, hi, padding=0)

    def get_ylim(self, panel):
        plot = self._plot_for_panel(panel)
        return tuple(float(value) for value in plot.vb.viewRange()[1])

    def get_ylims(self):
        return {name: self.get_ylim(name) for name in ("magnitude", "phase", "coherence")}

    def _plot_for_panel(self, panel):
        try:
            return {
                "magnitude": self._plot_magnitude,
                "phase": self._plot_phase,
                "coherence": self._plot_coherence,
            }[str(panel)]
        except KeyError:
            raise ValueError(f"unknown FRF panel: {panel!r}") from None

    def set_remark_enabled(self, enabled: bool) -> None:
        """Enable the shared add/delete point-remark interaction for FRF."""
        self._remark_enabled = bool(enabled)
        self._remark_interaction.set_enabled(
            self._remark_enabled,
            viewport=self._remark_viewport,
            menu_viewboxes=tuple(plot.vb for plot in self.plots),
        )

    def clear_remarks(self) -> None:
        self._remark_intent.clear()
        if not self._remarks:
            return
        self._drop_remark_projection()
        self._bump_markup_revision()

    def _drop_remark_projection(self) -> None:
        if not self._remarks:
            return
        self._remark_artist.clear(self._remarks)

    def _project_remarks(self) -> None:
        self._drop_remark_projection()
        for item in list(self._remark_intent.items):
            self._restore_one_remark(item)

    def snapshot_remarks(self):
        return self._remark_intent.snapshot(self._remarks)

    def restore_remarks(self, payload) -> None:
        self._remark_intent.replace(payload)
        self._project_remarks()

    def _overlay_source(self):
        raw = self._context.get("output_source")
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            return (str(raw[0]), str(raw[1]))
        return None

    def _restore_one_remark(self, item) -> None:
        if not isinstance(item, dict):
            return
        panel = str(item.get("panel") or "magnitude")
        try:
            frequency = float(item["x"])
        except (KeyError, TypeError, ValueError):
            return
        source = item.get("source")
        overlay = self._overlay_source()
        if source is not None and overlay is not None:
            parsed = (str(source[0]), str(source[1])) if (
                isinstance(source, (list, tuple)) and len(source) == 2
            ) else None
            if parsed is not None and parsed != overlay:
                return
        point = self._remark_point_at(
            panel, frequency,
            label_dx=item.get("label_dx"),
            label_dy=item.get("label_dy"),
        )
        if point is None:
            return
        remark = self._remark_artist.add(point)
        remark["panel"] = panel
        if overlay is not None:
            remark["source"] = overlay
        elif source is not None:
            remark["source"] = source
        self._remarks.append(remark)

    def _bump_markup_revision(self) -> None:
        self.markup_revision = int(self.markup_revision) + 1
        self.markup_revision_changed.emit()

    def remark_count(self) -> int:
        return len(self._remarks)

    def _remark_panel_at_scene_pos(self, scene_pos):
        if scene_pos is None:
            return None
        for panel, plot in (
            ("magnitude", self._plot_magnitude),
            ("phase", self._plot_phase),
            ("coherence", self._plot_coherence),
        ):
            if plot.vb.sceneBoundingRect().contains(scene_pos):
                return panel, plot
        return None

    def _remark_point_at(self, panel: str, frequency: float, *, label_dx=None, label_dy=None):
        idx = self._nearest_frequency_index(frequency)
        if idx is None:
            return None
        try:
            plot, values, color, unit_y = {
                "magnitude": (
                    self._plot_magnitude,
                    self._draw_magnitude,
                    "#1769e0",
                    "dB" if str(self._display_params.get("magnitude_scale")).lower() == "db"
                    else self._ratio_unit_label(),
                ),
                "phase": (
                    self._plot_phase,
                    self._draw_phase,
                    "#1769e0",
                    "deg",
                ),
                "coherence": (
                    self._plot_coherence,
                    self._draw_coherence,
                    "#0f9f83",
                    "",
                ),
            }[str(panel)]
        except KeyError:
            raise ValueError(f"unknown FRF panel: {panel!r}") from None
        physical_frequency = float(self._draw_frequencies[idx])
        value = float(values[idx])
        if not (np.isfinite(physical_frequency) and np.isfinite(value)):
            return None
        return RemarkPoint(
            vb=plot.vb,
            x=self._hz_to_view_x(physical_frequency),
            y=value,
            color=color,
            unit_x="Hz",
            unit_y=unit_y,
            display_x=physical_frequency,
            label_dx=label_dx,
            label_dy=label_dy,
        )

    def add_remark_at(self, panel: str, frequency: float) -> None:
        if not self._remark_enabled:
            return
        point = self._remark_point_at(panel, frequency)
        if point is None:
            return
        remark = self._remark_artist.add(point)
        remark["panel"] = str(panel)
        source = self._overlay_source()
        if source is not None:
            remark["source"] = source
        self._remarks.append(remark)
        self._remark_intent.record(remark, panel=str(panel))
        self._bump_markup_revision()

    def _remove_remark(self, remark) -> None:
        self._remark_intent.discard(remark)
        self._remark_artist.remove(remark)
        try:
            self._remarks.remove(remark)
        except ValueError:
            return
        self._bump_markup_revision()

    def remove_remark_near(self, panel: str, frequency: float) -> None:
        plot = self._plot_for_panel(panel)
        candidates = [
            remark for remark in self._remarks if remark.get("vb") is plot.vb
        ]
        if not candidates:
            return
        target_x = self._hz_to_view_x(float(frequency))
        nearest = min(
            candidates,
            key=lambda remark: abs(float(remark["data_x"]) - target_x),
        )
        self._remove_remark(nearest)

    def _viewport_pos_to_scene(self, viewport_pos):
        return viewport_pos_to_scene(self._glw, viewport_pos)

    def _add_remark_at_viewport_pos(self, viewport_pos) -> None:
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        target = self._remark_panel_at_scene_pos(scene_pos)
        if target is None:
            return
        panel, plot = target
        position = plot.vb.mapSceneToView(scene_pos)
        self.add_remark_at(panel, self._view_x_to_hz(position.x()))

    def _remove_remark_at_viewport_pos(self, viewport_pos) -> None:
        scene_pos = self._viewport_pos_to_scene(viewport_pos)
        target = self._remark_panel_at_scene_pos(scene_pos)
        if target is None:
            return
        panel, plot = target
        position = plot.vb.mapSceneToView(scene_pos)
        self.remove_remark_near(panel, self._view_x_to_hz(position.x()))

    def _remark_item_at_viewport_pos(self, viewport_pos):
        return remark_at_viewport_pos(self._remarks, self._glw, viewport_pos)

    def eventFilter(self, obj, event):
        if obj is self._remark_viewport and self._remark_enabled:
            if event.type() == QEvent.MouseButtonPress:
                result = self._remark_interaction.handle_mouse_press(event)
                if result is not None:
                    return result
            elif event.type() == QEvent.MouseMove:
                result = self._remark_interaction.handle_mouse_move(event)
                if result is not None:
                    return result
            elif event.type() == QEvent.MouseButtonRelease:
                result = self._remark_interaction.handle_mouse_release(event)
                if result is not None:
                    return result
        return super().eventFilter(obj, event)

    def reset_view_to_data_extents(self) -> None:
        if self._draw_frequencies.size == 0:
            return
        finite_x = self._draw_frequencies[np.isfinite(self._draw_frequencies)]
        if finite_x.size:
            lo, hi = _visual_padded_bounds(
                self._hz_to_view_x(float(finite_x.min())),
                self._hz_to_view_x(float(finite_x.max())),
            )
            self._plot_magnitude.setXRange(
                lo, hi, padding=0,
            )
        self._plot_magnitude.vb.enableAutoRange(axis="y", enable=True)
        self._plot_phase.vb.enableAutoRange(axis="y", enable=True)
        self._plot_coherence.setYRange(0.0, 1.0, padding=0)
        self._plot_coherence.vb.enableAutoRange(axis="y", enable=False)
        self._plot_host.schedule_alignment()

    def _fit_y_to_visible_x(self, plot) -> None:
        if plot is self._plot_coherence:
            self._plot_coherence.setYRange(0.0, 1.0, padding=0)
            return
        values = (
            self._draw_magnitude if plot is self._plot_magnitude
            else self._draw_phase
        )
        lo, hi = plot.vb.viewRange()[0]
        frequencies = self._draw_frequencies
        mask = (
            np.isfinite(frequencies) & np.isfinite(values)
            & (frequencies >= self._view_x_to_hz(lo))
            & (frequencies <= self._view_x_to_hz(hi))
        )
        visible = values[mask]
        if visible.size == 0:
            return
        y_lo, y_hi = _visual_padded_bounds(float(visible.min()), float(visible.max()))
        if y_hi <= y_lo:
            y_lo -= 0.5
            y_hi += 0.5
        plot.vb.enableAutoRange(axis="y", enable=False)
        plot.setYRange(y_lo, y_hi, padding=0)
        self._plot_host.schedule_alignment()

    def _redesign_context_menu_for_viewbox(self, view_box, menu) -> None:
        plot = next((item for item in self.plots if item.vb is view_box), None)
        if plot is None:
            return
        redesign_pg_context_menu(
            menu, plot, self._mouse_mode_controller,
            view_all_handler=self.reset_view_to_data_extents,
            y_autofit_handler=lambda: self._fit_y_to_visible_x(plot),
            copy_image_handler=self._copy_image_handler,
            allow_y_grid=True, keep_plot_options=False, view_box=view_box,
        )

    def _handle_wheel_dispatch(self, *, delta, modifiers, x_pos, y_pos,
                               view_box=None, scene_pos=None, axis=None):
        step = 1 if delta > 0 else -1 if delta < 0 else 0
        if step == 0 or view_box is None:
            return False
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        if not (ctrl or shift):
            return False
        factor = 0.85 if step > 0 else 1.0 / 0.85
        try:
            x_range, y_range = view_box.viewRange()
            if ctrl:
                lo, hi = x_range
                center = float(x_pos) if np.isfinite(x_pos) else (lo + hi) / 2.0
                view_box.setXRange(
                    center - (center - lo) * factor,
                    center + (hi - center) * factor, padding=0,
                )
                self.manual_zoom_changed.emit(True)
            else:
                lo, hi = y_range
                center = float(y_pos) if np.isfinite(y_pos) else (lo + hi) / 2.0
                view_box.enableAutoRange(axis="y", enable=False)
                view_box.setYRange(
                    center - (center - lo) * factor,
                    center + (hi - center) * factor, padding=0,
                )
        except (RuntimeError, TypeError, ValueError, FloatingPointError):
            return False
        # Programmatic ranges do not emit sigRangeChangedManually, so this
        # modifier-wheel path must enter the same AA-off interaction state.
        self.disable_interactive_quality()
        self.schedule_idle_quality()
        self.layout_geometry_changed.emit()
        self._plot_host.schedule_alignment()
        return True

    def set_tick_density(self, x, y) -> None:
        try:
            x_count, y_count = max(3, int(x)), max(3, int(y))
        except (TypeError, ValueError):
            return
        x_density, y_density = _tick_counts_to_density(x_count, y_count)
        for plot in self.plots:
            _apply_axis_tick_density(plot.getAxis("left"), y_density)
        bottom = self._plot_coherence.getAxis("bottom")
        if self._is_log_frequency():
            self._sync_frequency_ticks()
        else:
            _apply_axis_tick_density(bottom, x_density)
        self.layout_geometry_changed.emit()
        self._plot_host.schedule_alignment()

    def frf_layout_metrics(self) -> dict:
        return self._plot_host.layout_metrics()

    def prepare_frf_layout_alignment(self) -> None:
        self._plot_host.prepare_alignment()

    def reset_frf_layout_alignment(self) -> None:
        self._plot_host.reset_alignment()

    def apply_frf_layout_alignment(self, *, left_axis_width: float) -> None:
        self._plot_host.apply_alignment(left_axis_width=left_axis_width)

    def _on_scene_mouse_moved(self, scene_pos) -> None:
        if self._cursor_mode != "single":
            return
        for plot in self.plots:
            if plot.vb.sceneBoundingRect().contains(scene_pos):
                frequency = self._view_x_to_hz(
                    plot.vb.mapSceneToView(scene_pos).x()
                )
                self.set_cursor_frequency(frequency)
                return

    def _on_scene_mouse_clicked(self, event) -> None:
        if self._remark_enabled:
            return
        if self._cursor_mode != "dual" or event.button() != Qt.LeftButton:
            return
        scene_pos = event.scenePos()
        for plot in self.plots:
            if plot.vb.sceneBoundingRect().contains(scene_pos):
                frequency = self._view_x_to_hz(
                    plot.vb.mapSceneToView(scene_pos).x()
                )
                if self._next_dual_cursor == "a":
                    self.set_dual_cursor_frequencies(frequency, None)
                    self._next_dual_cursor = "b"
                else:
                    self.set_dual_cursor_frequencies(
                        self._cursor_a_frequency, frequency
                    )
                    self._next_dual_cursor = "a"
                event.accept()
                return

    def _nearest_frequency_index(self, frequency):
        if self._draw_frequencies.size == 0:
            return None
        finite = np.isfinite(self._draw_frequencies)
        if not np.any(finite):
            return None
        finite_indices = np.flatnonzero(finite)
        return int(finite_indices[np.argmin(
            np.abs(self._draw_frequencies[finite] - float(frequency))
        )])

    def _show_frequency_lines(self, lines, frequency) -> None:
        for line in lines:
            line.setValue(self._hz_to_view_x(frequency))
            line.show()

    @staticmethod
    def _hide_frequency_lines(lines) -> None:
        for line in lines:
            line.hide()

    def _hide_frequency_cursor_items(self, *, emit_empty: bool = True) -> None:
        self._hide_frequency_lines(self._cursor_lines)
        self._hide_frequency_lines(self._cursor_a_lines)
        self._hide_frequency_lines(self._cursor_b_lines)
        if emit_empty:
            self.cursor_info.emit("")
            self.dual_cursor_info.emit("")

    def _clear_frequency_cursor_readout(self) -> None:
        """Wipe A/B placement and hide lines. File-close / empty-canvas path."""
        self._cursor_a_frequency = None
        self._cursor_b_frequency = None
        self._next_dual_cursor = "a"
        self._hide_frequency_cursor_items()

    def _project_frequency_cursors(self) -> None:
        if self._cursor_mode == "dual" and self._cursor_a_frequency is not None:
            self.set_dual_cursor_frequencies(
                self._cursor_a_frequency, self._cursor_b_frequency,
            )
            return
        self._hide_frequency_cursor_items()

    def snapshot_cursor_placement(self):
        return snapshot_frequency_cursor(
            self._cursor_a_frequency,
            self._cursor_b_frequency,
            cursor_mode=self._cursor_mode,
        )

    def restore_cursor_placement(self, payload) -> None:
        normalized = normalize_cursor_placement(
            payload, cursor_mode=self._cursor_mode,
        )
        if normalized is None:
            self._cursor_a_frequency = None
            self._cursor_b_frequency = None
            self._next_dual_cursor = "a"
        else:
            self._cursor_a_frequency = normalized["ax"]
            self._cursor_b_frequency = normalized.get("bx")
        self._project_frequency_cursors()

    def set_cursor_frequency(self, frequency) -> str:
        idx = self._nearest_frequency_index(frequency)
        if idx is None:
            self.cursor_info.emit("")
            return ""
        f_value = float(self._draw_frequencies[idx])
        self._show_frequency_lines(self._cursor_lines, f_value)
        text = (
            f"f={f_value:g} Hz | "
            f"|H|={self._draw_magnitude[idx]:.5g}"
            f"{self._magnitude_unit_suffix()} | "
            f"phase={self._draw_phase[idx]:.5g}° | "
            f"coherence={self._draw_coherence[idx]:.4g}"
        )
        self.cursor_info.emit(text)
        return text

    def _format_dual_sample(self, prefix, index) -> str:
        frequency = float(self._draw_frequencies[index])
        return (
            f"{prefix}: f={frequency:g} Hz | "
            f"|H|={self._draw_magnitude[index]:.5g}{self._magnitude_unit_suffix()} | "
            f"phase={self._draw_phase[index]:.5g}° | "
            f"coherence={self._draw_coherence[index]:.4g}"
        )

    def _format_dual_delta(self, a_index, b_index) -> str:
        """Return the highlighted B-minus-A readout for every FRF Y axis."""
        magnitude = self._draw_magnitude[b_index] - self._draw_magnitude[a_index]
        phase = self._draw_phase[b_index] - self._draw_phase[a_index]
        coherence = self._draw_coherence[b_index] - self._draw_coherence[a_index]
        return (
            f'<span style="{_DUAL_CURSOR_DELTA_STYLE}">'
            "ΔY："
            f"Δ|H|={magnitude:+.5g}{escape(self._magnitude_unit_suffix())} | "
            f"Δphase={phase:+.5g}° | "
            f"Δcoherence={coherence:+.4g}"
            "</span>"
        )

    def set_dual_cursor_frequencies(self, a_frequency, b_frequency) -> str:
        """Place the FRF A/B cursors and publish fA/fB/Δf plus both values."""
        a_index = self._nearest_frequency_index(a_frequency)
        if a_index is None:
            self.cursor_info.emit("")
            self.dual_cursor_info.emit("")
            return ""
        self._cursor_a_frequency = float(self._draw_frequencies[a_index])
        self._show_frequency_lines(self._cursor_a_lines, self._cursor_a_frequency)
        self._cursor_b_frequency = None
        self._hide_frequency_lines(self._cursor_b_lines)
        if b_frequency is None:
            primary = f"A: f={self._cursor_a_frequency:g} Hz | 点击 B 选择第二点"
            self.cursor_info.emit(primary)
            self.dual_cursor_info.emit("")
            return primary
        b_index = self._nearest_frequency_index(b_frequency)
        if b_index is None:
            return ""
        self._cursor_b_frequency = float(self._draw_frequencies[b_index])
        self._show_frequency_lines(self._cursor_b_lines, self._cursor_b_frequency)
        delta = self._cursor_b_frequency - self._cursor_a_frequency
        primary = (
            f"A={self._cursor_a_frequency:g} Hz | "
            f"B={self._cursor_b_frequency:g} Hz | "
            f'<span style="{_DUAL_CURSOR_DELTA_STYLE}">'
            f"Δf={delta:+g} Hz</span>"
        )
        self.cursor_info.emit(primary)
        self.dual_cursor_info.emit(
            f"{self._format_dual_sample('A', a_index)}<br>"
            f"{self._format_dual_sample('B', b_index)}<br>"
            f"{self._format_dual_delta(a_index, b_index)}"
        )
        return primary

    def cursor_mode(self) -> str:
        return self._cursor_mode

    def set_cursor_mode(self, mode: str) -> None:
        if mode not in {"off", "single", "dual"}:
            return
        self._cursor_mode = mode
        self._project_frequency_cursors()

    def cursor_enabled(self) -> bool:
        """Whether this FRF pane exposes its linked frequency readout."""
        return self._cursor_mode != "off"

    def set_cursor_enabled(self, enabled: bool) -> None:
        """Compatibility bridge for schema-4 callers (true → single)."""
        self.set_cursor_mode("single" if enabled else "off")

    def register_replot_callback(self, callback) -> None:
        if callable(callback):
            self._replot_callbacks.append(callback)

    def _run_replot_callbacks(self) -> None:
        for callback in tuple(self._replot_callbacks):
            try:
                callback()
            except (RuntimeError, TypeError):
                logger.debug("FRF replot callback failed", exc_info=True)

    def register_mouse_mode_controller(self, controller) -> None:
        self._mouse_mode_controller = controller

    def register_copy_image_handler(self, handler) -> None:
        self._copy_image_handler = handler

    def has_result(self) -> bool:
        return self._result is not None

    def has_plotted_result(self) -> bool:
        return self.has_result()

    def capture_quality_settled(self) -> bool:
        return quality_settled_from_status(self.quality_status() or {})

    def capture_interaction_idle(self) -> bool:
        timer = self._aa_timer_alive(getattr(self, "_aa_idle_timer", None))
        return not analysis_idle_timer_is_busy(timer)

    def capture_cursor_facts(self):
        dual = self.cursor_mode() == "dual"
        geometry = dual_cursor_geometry(
            dual=dual,
            ax=self._cursor_a_frequency,
            bx=self._cursor_b_frequency,
        )
        return dual, geometry

    def iter_transient_overlay_items(self, *, section: str = "unknown"):
        yield from self._cursor_lines or ()
        yield from iter_axes_rubberband_items(self)

    def presentation_capture_facts(self):
        dual, geometry = self.capture_cursor_facts()
        return build_capture_facts(
            host_kind="frf",
            visible_and_sized=widget_visible_and_sized(self),
            has_real_result=self.has_plotted_result(),
            quality_settled=self.capture_quality_settled(),
            interaction_idle=self.capture_interaction_idle(),
            cursor_dual=dual,
            cursor_geometry=geometry,
        )

    def clear(self) -> None:
        self.clear_remarks()
        self._result = None
        self._context = {}
        self._draw_frequencies = np.empty(0, dtype=float)
        self._draw_magnitude = np.empty(0, dtype=float)
        self._draw_phase = np.empty(0, dtype=float)
        self._draw_coherence = np.empty(0, dtype=float)
        for curve in (
            self._magnitude_curve,
            self._magnitude_low_curve,
            self._magnitude_low_points,
            self._magnitude_singleton_points,
            self._phase_curve,
            self._phase_low_curve,
            self._phase_low_points,
            self._phase_singleton_points,
            self._coherence_curve,
            self._coherence_singleton_points,
        ):
            curve.setData([], [])
        # No curves left to upgrade: cancel any pending AA settlement and end
        # the measurement session rather than letting it time out on nothing.
        self._stop_aa_timers()
        self._close_aa_backstop_session()
        self._reset_aa_gates()
        self._aa_block_reason = None
        self._clear_frequency_cursor_readout()
        self.set_state("empty")
        self._run_replot_callbacks()
        self.layout_geometry_changed.emit()
        self._emit_quality_status()

    def full_reset(self) -> None:
        self.clear()

    def grab_pixmap(self, scale: float = 2.0) -> QPixmap:
        base = self._glw.grab()
        if base.isNull() or base.width() <= 0 or base.height() <= 0:
            fallback = QPixmap(1, 1)
            fallback.fill(Qt.transparent)
            return fallback
        if scale <= 1.0:
            return base
        return base.scaled(
            int(round(base.width() * scale)),
            int(round(base.height() * scale)),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

    def closeEvent(self, event):
        self._stop_aa_timers()
        try:
            self._glw.scene().sigMouseMoved.disconnect(self._scene_mouse_slot)
        except (TypeError, RuntimeError):
            # The scene or signal wrapper may already be gone during QObject
            # child teardown; no live callback remains in either case.
            pass
        try:
            self._glw.scene().sigMouseClicked.disconnect(self._scene_click_slot)
        except (TypeError, RuntimeError):
            # The scene or signal wrapper may already be gone during QObject
            # child teardown; no live callback remains in either case.
            pass
        try:
            self._plot_magnitude.vb.sigXRangeChanged.disconnect(
                self._frequency_range_slot
            )
        except (TypeError, RuntimeError):
            # The ViewBox wrapper can already be invalid during child teardown.
            pass
        for plot in self.plots:
            try:
                plot.vb.sigRangeChangedManually.disconnect(
                    self._interactive_range_slot
                )
            except (TypeError, RuntimeError):
                # The ViewBox wrapper can already be invalid during teardown.
                pass
        self._empty_hint.clear()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._plot_host.schedule_alignment()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._plot_host.schedule_alignment()


__all__ = ["PgFrfCanvas"]
