"""Interactive and idle quality helpers for the pyqtgraph canvas."""

from __future__ import annotations

from contextlib import contextmanager
import logging
from time import perf_counter

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QGraphicsItem

from . import _binding  # noqa: F401
from ._backref import _CanvasBackref

import pyqtgraph as pg

from .quality_backstop import AaFrameLatch
from .render_profile import envelope_ink_dev_px
from .renderer import (
    _INK_AA_OFF,
    _INK_AA_ON,
    _Y_SPAN_DEGENERATE_KEY,
    _quantize_y_span_key,
)
from .ticks_math import _quantize_range_key


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# MEASURED-FRAME BACKSTOP (spec
# docs/analyzer/specs/2026-08-08-timedomain-aa-ink-budget-spec.md §4.4 / §5).
#
# Everything above this line is a PREDICTION: the ink metric predicts paint
# cost, the AA band predicts affordability, the raster admission predicts a
# cheaper alternative. This layer is what catches a prediction that was WRONG,
# so that an unforeseen geometry costs at most ONE bad frame instead of
# repeating it every time the idle timer fires.
#
# The measurement itself comes from a resident paint timer on the time-domain
# GraphicsView (install_frame_paint_timer below). Its readings are compared
# against two ceilings:
#
#   * _BACKSTOP_FIRST_AA_MS gates the FIRST frame of an AA session, which
#     legitimately carries one-off costs (device-coordinate cache
#     construction). 2026-08-08 Cocoa measurement: the smooth control's first
#     AA frame is 474 ms and is today's ACCEPTED behavior, so the ceiling must
#     clear it with margin. Anything past a full second is not a slow frame,
#     it is an incident — the pathological cases measured 3.6 s (6ch
#     oscillating) and 63 s (1ch oscillating + Y fit).
#   * _BACKSTOP_STEADY_AA_MS gates the EMA of every subsequent AA frame in the
#     session. Same measurement: the smooth control's steady AA frame is
#     240 ms and must keep being allowed, so 250 ms is deliberately the
#     tightest ceiling that still passes it. Sustained frames above this mean
#     the prediction is not merely off, it is off every frame.
#
# _BACKSTOP_STEADY_EMA_ALPHA weights each new frame at half. Seeding the EMA
# with the first steady sample means a single catastrophic frame trips
# immediately (which is the whole point — spec §4.5 budgets exactly one bad
# frame per signature), while a single MILDLY slow frame is averaged down
# instead of latching on noise: 100 ms then 300 ms averages to 200 ms and
# passes. A slower alpha would spend several seconds-long frames converging;
# a faster one degenerates into a per-frame comparison.
#
# _BACKSTOP_BLACKLIST_MAX bounds the latch state. Unbounded per-view state on
# a long-lived UI object is a leak, and 32 distinct view signatures is far more
# than a user visits between rebuilds; the LRU drops the least recently
# latched one.
#
# All four are CALIBRATIONS, not knobs: change spec §5 first and re-measure
# with scripts/probe_aa_ink_budget.py on real hardware (an offscreen suite
# cannot measure paint cost). tests/ui/test_pg_timedomain_canvas.py::
# TestAaBackstopLatch fences the bands.
#
# The state machine those four parameterize lives in quality_backstop.py
# (AaFrameLatch, spec 2026-08-15 §3.3) so the analysis canvases can reuse ONE
# calibrated implementation. This manager keeps the Qt half — the armed flag
# the paint timer reads, and the deferred, epoch-checked AA disable — because
# mutating QGraphicsItems mid-paint is not safe and none of that is arithmetic.
# ---------------------------------------------------------------------------
_BACKSTOP_FIRST_AA_MS = 1000.0
_BACKSTOP_STEADY_AA_MS = 250.0
_BACKSTOP_STEADY_EMA_ALPHA = 0.5
_BACKSTOP_BLACKLIST_MAX = 32

# Qt dynamic property carrying the AA epoch a queued trip was raised for.
# Mirrors dense_raster's timer_generation_property discipline.
_BACKSTOP_EPOCH_PROPERTY = "tracelabAaBackstopEpoch"

# Instance marker + per-base class cache for the resident paint timer.
_FRAME_TIMER_INSTALLED_ATTR = "_tracelab_frame_timer_installed"
_FRAME_TIMER_OWNER_ATTR = "_tracelab_frame_timer_owner"
_frame_timed_view_classes: dict = {}


def _frame_timed_view_class(base):
    """Return (and memoize) a ``paintEvent``-timing subclass of ``base``.

    Memoized per base class so a workspace full of chart cards shares ONE
    generated class instead of minting one per canvas.
    """
    cached = _frame_timed_view_classes.get(base)
    if cached is not None:
        return cached

    class _FrameTimedGraphicsView(base):
        """``base`` plus a two-``perf_counter`` paint timer.

        Steady-state cost per frame: two ``perf_counter`` calls, one float
        store, and one boolean read that is False whenever AA is off (i.e.
        during every interaction frame, the ones that must stay cheap). No
        logging, no allocation, no container growth — this is the resident
        production twin of the diagnostic ``_perf_probe.install_paint_probe``,
        not the probe itself.

        Owner protocol (spec 2026-08-15 §3.3): the owning canvas must expose
        ``_aa_backstop_armed`` (the pairing token, read on EVERY frame, so it
        stays a bare attribute) and SHOULD expose ``_note_aa_frame(ms)``. The
        ``_quality._note_aa_frame`` fallback keeps a canvas that predates the
        protocol working; the direct hook is what lets the analysis canvases
        (line / frf), whose latch does not hang off a ``_quality`` manager,
        install this very same timer.
        """

        def paintEvent(self, ev):
            t0 = perf_counter()
            try:
                return base.paintEvent(self, ev)
            finally:
                try:
                    owner = getattr(self, _FRAME_TIMER_OWNER_ATTR, None)
                    if owner is not None:
                        frame_ms = (perf_counter() - t0) * 1000.0
                        owner._last_frame_paint_ms = frame_ms
                        if owner._aa_backstop_armed:
                            note = getattr(owner, "_note_aa_frame", None)
                            if callable(note):
                                note(frame_ms)
                            else:
                                owner._quality._note_aa_frame(frame_ms)
                except Exception:
                    # A measurement must never propagate an exception into
                    # Qt's paint dispatch. Zero cost on the happy path.
                    pass

    _FrameTimedGraphicsView.__name__ = f"_FrameTimed{base.__name__}"
    _FrameTimedGraphicsView.__qualname__ = _FrameTimedGraphicsView.__name__
    _frame_timed_view_classes[base] = _FrameTimedGraphicsView
    return _FrameTimedGraphicsView


def install_frame_paint_timer(canvas) -> bool:
    """Install the resident paint timer on ``canvas._glw``. Idempotent.

    Implementation constraint (the Qt trap documented at length in
    ``_perf_probe.install_paint_probe``): pyqtgraph's ``_glw`` IS the
    ``QGraphicsView`` that paints, and Qt dispatches ``paintEvent`` from C++
    through the virtual table. That reaches Python ONLY when the method is
    overridden AT CLASS LEVEL — assigning a function to the instance, or
    substituting a viewport subclass, is never called (measured: 0 hits). So
    the only working shape is a runtime ``__class__`` swap onto a subclass of
    the widget's own current class.

    Returns True when this call performed the swap, False when it was already
    installed (or there is nothing to install on), so the idempotence is
    observable instead of silent.
    """
    glw = getattr(canvas, "_glw", None)
    if glw is None:
        return False
    if getattr(glw, _FRAME_TIMER_INSTALLED_ATTR, False):
        return False
    try:
        glw.__class__ = _frame_timed_view_class(type(glw))
        setattr(glw, _FRAME_TIMER_OWNER_ATTR, canvas)
        setattr(glw, _FRAME_TIMER_INSTALLED_ATTR, True)
    except Exception:
        return False
    return True


class QualityManager(_CanvasBackref):
    """Curve antialiasing and idle-quality policy.

    Owns the idle-AA timer and hysteresis state. Threshold constants remain on
    the canvas so existing tuning/tests can keep reading and overriding them.
    """

    # The six aa_backstop_* / aa_*_frame* names below are PROPERTIES onto
    # ``latch`` (see the block after __init__), not instance attributes. They
    # have to stay declared here anyway: _CanvasBackref.__setattr__ only lets
    # object.__setattr__ — the call that runs a data descriptor — happen for
    # declared names, so dropping them would silently route every write past
    # the property and onto the canvas.
    _owned_names = frozenset({
        "aa_backstop_blacklist",
        "aa_backstop_epoch",
        "aa_backstop_reason",
        "aa_backstop_signature",
        "aa_epoch_frames",
        "aa_frame_ema",
        "aa_on",
        "backstop_timer",
        "latch",
        "density_allowed",
        "density_seeded",
        "ink_allowed",
        "ink_seeded",
        "last_emitted_status",
        "timer",
        # Injectable defensive provider for the idle-quality mouse-buttons
        # probe (P1-6). Owned by the manager, never write-through: local
        # canvas interaction state (_interaction_depth / _overlay_axes.
        # dragging) is the primary busy judge, this is only consulted so a
        # raising provider stays observable. See
        # docs/lessons-learned/idle-quality-follows-local-canvas-activity.md.
        "_mouse_buttons_provider",
    })

    _delegate_names = frozenset({
        "_collect_curve_items",
        "_set_curves_antialias",
        "_set_curves_cache_mode",
        "disable_interactive_quality",
        "schedule_idle_quality",
        "try_enable_idle_quality",
        "_idle_quality_allowed",
        "_idle_aa_density_ok",
        "_export_aa_affordable",
        "_curves_antialiased",
    })

    def __init__(self, canvas):
        super().__init__(canvas)
        self.aa_on = False
        self.timer = QTimer(canvas)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.try_enable_idle_quality)
        self.density_allowed = False
        self.density_seeded = False
        # Ink-sum hysteresis state (spec §4.2), mirrors density_allowed /
        # density_seeded above but tracks the SUMMED per-line ink of the
        # native-AA-path lines rather than displayed point count.
        self.ink_allowed = False
        self.ink_seeded = False
        self.last_emitted_status = None
        # --- measured-frame backstop (spec §4.4) -------------------------
        # The epoch / first-frame / steady-EMA / bounded-memory state machine
        # lives in AaFrameLatch (spec 2026-08-15 §3.3). Its epoch identifies
        # ONE AA session and is bumped when a session opens and when it closes,
        # which is what lets a queued trip tell "the session I measured" from
        # "some later session". Its blacklist holds the view signatures whose
        # AA frames measured unaffordable (LRU, newest at the right); its memo
        # holds what a cheap view's first AA frame actually cost.
        self.latch = AaFrameLatch(
            _BACKSTOP_FIRST_AA_MS,
            _BACKSTOP_STEADY_AA_MS,
            _BACKSTOP_STEADY_EMA_ALPHA,
            _BACKSTOP_BLACKLIST_MAX,
        )
        self.backstop_timer = QTimer(canvas)
        self.backstop_timer.setSingleShot(True)
        self.backstop_timer.timeout.connect(self._on_aa_backstop_timeout)
        # Defensive injectable provider (P1-6): defaults to the real Qt
        # query but is swappable so tests can inject failures/foreign-press
        # readings without depending on the live mouse. Its result is only
        # ever probed for observability, never used to gate — see
        # _idle_quality_allowed.
        self._mouse_buttons_provider = QApplication.mouseButtons

    # ------------------------------------------------------------------
    # Latch state, kept readable (and writable) under its historical names.
    #
    # The state moved into AaFrameLatch, the NAMES did not: diagnostics and
    # the backstop tests reach for canvas._quality.aa_backstop_* directly, and
    # renaming a reader-facing surface is not what an extraction is for. These
    # are plain forwards — no coercion, no lazy init — so the latch stays the
    # single source of truth and there is nothing to keep in sync.
    # ------------------------------------------------------------------

    @property
    def aa_backstop_epoch(self):
        return self.latch.epoch

    @aa_backstop_epoch.setter
    def aa_backstop_epoch(self, value):
        self.latch.epoch = value

    @property
    def aa_epoch_frames(self):
        return self.latch.frames

    @aa_epoch_frames.setter
    def aa_epoch_frames(self, value):
        self.latch.frames = value

    @property
    def aa_frame_ema(self):
        return self.latch.ema

    @aa_frame_ema.setter
    def aa_frame_ema(self, value):
        self.latch.ema = value

    @property
    def aa_backstop_signature(self):
        return self.latch.signature

    @aa_backstop_signature.setter
    def aa_backstop_signature(self, value):
        self.latch.signature = value

    @property
    def aa_backstop_reason(self):
        return self.latch.reason

    @aa_backstop_reason.setter
    def aa_backstop_reason(self, value):
        self.latch.reason = value

    @property
    def aa_backstop_blacklist(self):
        return self.latch.blacklist

    @aa_backstop_blacklist.setter
    def aa_backstop_blacklist(self, value):
        self.latch.blacklist = value

    def reset_for_rebuild(self):
        """Reset idle-AA runtime state after the curve set is rebuilt."""
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self.backstop_timer.stop()
        except Exception:
            pass
        self.aa_on = False
        self.density_allowed = False
        # Rebuild changes the curve set / point counts, so the next decision
        # must re-seed via the OFF threshold rather than inherit stale state.
        self.density_seeded = False
        self.ink_allowed = False
        self.ink_seeded = False
        self.last_emitted_status = None
        # The per-session backstop counters belong to the AA session that the
        # rebuild just ended, so they go. The BLACKLIST does NOT: a rebuild
        # re-creates curves, it does not change the fact that this view
        # geometry cannot afford vector AA, and the signature already carries
        # everything that would make that fact stale (xlim, y spans, the
        # visible channel set, pixel width). Clearing it here would hand back
        # exactly one seconds-long frame per rebuild — and a rebuild is what a
        # re-plot, a filter toggle and a view switch all funnel through.
        # Bounded by the LRU, so entries that no longer match simply age out.
        self._close_aa_backstop_epoch()
        self._emit_quality_status_changed()

    def _collect_curve_items(self):
        """Every ``PlotCurveItem`` on the scene; ``[]`` if unreachable."""
        try:
            scene = self._glw.scene()
        except Exception:
            scene = None
        if scene is None:
            return []
        return [it for it in scene.items() if isinstance(it, pg.PlotCurveItem)]

    def _raster_covered_curve_items(self):
        """Visible raster-backed curves fully replaced by a ready raster."""
        try:
            if self._dense_raster.quality_status().get("state") != "green":
                return set()
        except Exception:
            return set()
        covered = set()
        try:
            entries = self._channel_lines.composite_items()
        except Exception:
            return covered
        for ck, _name, (_axis, line) in entries:
            # Shared admission predicate (spec §4.3): dense-discrete by
            # strategy, or a line the ink budget admitted to the raster path.
            if not self._raster_backend_eligible(ck):
                continue
            pdi = getattr(line, "plot_data_item", None)
            try:
                if (
                    pdi is not None
                    and pdi.isVisible()
                    and self._dense_raster.entry_for(ck) is not None
                ):
                    covered.add(pdi.curve)
            except Exception:
                continue
        return covered

    def _native_aa_curve_items(self):
        covered = self._raster_covered_curve_items()
        return [it for it in self._collect_curve_items() if it not in covered]

    def _line_ink_now(self, axis, pdi) -> float | None:
        """Ink for the data CURRENTLY bound to ``pdi``, computed on the spot.

        The fallback for a line the renderer has not recorded yet. It reads
        the same three inputs ``_refresh_visible_data`` would
        (the bound samples, the line's Y view span, its row height in device
        pixels), so the number is directly comparable to a recorded one.

        A degenerate handle with fewer than two samples yields 0.0 through
        ``envelope_ink_dev_px``'s own sentinels — that is a real empty-ink
        measurement, not a failure. Measurement FAILURE (missing view box,
        ``get_ylim`` / DPR / envelope exceptions) returns ``None``: unknown
        is not zero (B3). Callers must refuse AA for the frame and must NOT
        write ``None`` into ``_line_ink_state``.
        """
        try:
            _x, y = pdi.getData()
            if y is None:
                return 0.0
            lo, hi = axis.get_ylim()
            y_span = abs(float(hi) - float(lo))
            view_box = getattr(axis, "view_box", None)
            if view_box is None:
                return None
            row_height = float(view_box.sceneBoundingRect().height())
            dpr = float(self._glw.devicePixelRatioF())
        except Exception:
            return None
        try:
            return float(envelope_ink_dev_px(
                y, y_span=y_span, row_height_px=row_height, dpr=dpr,
            ))
        except Exception:
            return None

    def _frame_native_ink_total(self) -> float:
        """Sum this frame's per-line ink for lines still on the native-AA
        paint path (spec §4.2 / renderer ``_line_ink_state``).

        Walks the LINES that will actually paint natively rather than the
        recorded ink entries, because the two sets are not the same and the
        difference is load-bearing. A line counts when it is visible and NOT
        already covered by a settled dense-raster entry
        (``_raster_covered_curve_items`` — the raster upgrade replaced its
        paint cost, so its recorded ink must not keep blocking AA for the rest
        of the frame).

        A line with no record yet is MEASURED ON THE SPOT (``_line_ink_now``),
        never treated as zero. ``plot_channels`` ends with
        ``schedule_idle_quality()`` while ``_line_ink_state`` is still empty —
        the first frame is bound by the bind envelope, not by
        ``_refresh_visible_data`` — so summing an empty map to 0.0 let the idle
        timer switch vector AA on for a curve nobody had measured: 65.9 s,
        measured on Cocoa right after a plain plot_channels of the spec §3.2
        fixture, with no user interaction at all. The backstop caught it, after
        the frame was paid. Computing instead of refusing keeps the fix inside
        the actual hole: charts whose ink is genuinely low still get AA on the
        first idle window, exactly as before.

        Measurement FAILURE (``_line_ink_now`` → ``None``) is a different case
        from "not yet recorded": unknown refuses AA for THIS frame
        (return over ``_INK_AA_OFF``) without writing ``_line_ink_state``, so
        the next frame can remeasure. Do not fold the first-frame normal path
        into that failure path (``0c07517a`` regressed 34 tests that way).

        Recorded values win when present, so the AA gate and the raster
        admission keep deciding on the one shared pre-cap number
        (spec §4.2 / §4.3); the on-the-spot value is only ever a stand-in for a
        line that has none.

        Matched by COMPOSITE ``(data_id, name)`` identity, never the display
        name, for the same multi-file-same-name reason the renderer's own
        per-line cache uses composite keys.
        """
        covered = self._raster_covered_curve_items()
        ink_state = getattr(self, "_line_ink_state", None)
        try:
            entries = list(self._channel_lines.composite_items())
        except Exception:
            return 0.0
        total = 0.0
        for ck, _name, (axis, line) in entries:
            pdi = getattr(line, "plot_data_item", None)
            try:
                if pdi is not None and not pdi.isVisible():
                    continue
            except Exception:
                pass
            try:
                if pdi is not None and pdi.curve in covered:
                    continue
            except Exception:
                pass
            state = None
            if ink_state is not None:
                try:
                    state = ink_state.get(ck)
                except Exception:
                    state = None
            ink = None
            if state is not None:
                try:
                    ink = float(state[0])
                except (TypeError, IndexError, ValueError):
                    ink = None
            if ink is None and pdi is not None:
                ink = self._line_ink_now(axis, pdi)
            if ink is None:
                # Unknown ≠ 0: refuse AA this frame; do not persist.
                return float(_INK_AA_OFF) + 1.0
            total += float(ink)
        return total

    def _set_curves_antialias(self, on: bool) -> int:
        """Persistently set curve AA without repainting or changing data."""
        n = 0
        covered = self._raster_covered_curve_items() if on else set()
        for it in self._collect_curve_items():
            try:
                enabled = bool(on and it not in covered)
                it.opts["antialias"] = enabled
                if not on or enabled:
                    n += 1
            except Exception:
                pass
        return n

    def _set_curves_cache_mode(self, mode) -> None:
        """Set the QGraphicsItem cache mode on every curve item.

        Fix D (2026-05-31): ``DeviceCoordinateCache`` lets hover /
        ``draw_idle`` blit the cached device-coordinate bitmap of the
        overlaid AA curves instead of re-rasterizing them every frame.
        The cache MUST be cleared (``NoCache``) on any range / geometry /
        resize / replot change, all of which converge on
        ``disable_interactive_quality`` (verified callers: _on_xrange_changed,
        reset_view_to_data_extents, the overlay Y-drag, the box-zoom hook,
        wheel zoom, and rebuild's AA reset).
        """
        items = (
            self._collect_curve_items()
            if mode == QGraphicsItem.NoCache
            else self._native_aa_curve_items()
        )
        for it in items:
            try:
                it.setCacheMode(mode)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Measured-frame backstop (spec §4.4)
    # ------------------------------------------------------------------

    def _view_signature(self):
        """Identity of the CONFIGURATION whose AA cost was measured.

        Not a cache key for pixels — a key for the QUESTION "can this view
        afford vector AA". It has to change whenever the answer could change
        and stay put otherwise, which is exactly the four inputs spec §4.4
        lists:

        * the quantized xlim, via the SAME ``_quantize_range_key`` bucketing
          the per-line refresh cache uses (a constant channel slot, since this
          is a whole-canvas question), so float jitter on a static window does
          not look like a new view;
        * per-row ``_quantize_y_span_key`` — Y span is a direct factor of ink,
          so a Y zoom is genuinely a different question;
        * the VISIBLE composite-key set, which doubles as the channel
          fingerprint (hiding 显示原始 changes what gets painted);
        * pixel width and overlay-vs-subplot, which change the geometry the
          cost was measured on.

        Returns ``None`` when the canvas cannot answer (no primary axis, no
        visible curve, a degenerate handle). ``None`` is treated as "no
        opinion" everywhere: it never latches and never blocks.
        """
        try:
            primary = self._primary_xaxis_ax
            if primary is None:
                return None
            xlo, xhi = primary.get_xlim()
            pixel_width = int(self._current_pixel_width())
            rows = []
            entries = self._channel_lines.composite_items()
            for ck, _name, (axis, line) in entries:
                pdi = getattr(line, "plot_data_item", None)
                try:
                    if pdi is not None and not pdi.isVisible():
                        continue
                except Exception:
                    continue
                try:
                    ylo, yhi = axis.get_ylim()
                    y_key = _quantize_y_span_key(abs(float(yhi) - float(ylo)))
                except Exception:
                    y_key = _Y_SPAN_DEGENERATE_KEY
                rows.append((str(ck), int(y_key)))
            if not rows:
                return None
            return (
                _quantize_range_key("", (float(xlo), float(xhi)), pixel_width),
                tuple(sorted(rows)),
                int(pixel_width),
                bool(getattr(self, "_overlay_mode", False)),
            )
        except Exception:
            return None

    def _aa_backstop_blocked(self) -> bool:
        """Whether the CURRENT view already paid its one bad AA frame."""
        latch = self.latch
        if not latch.blacklist:
            # Overwhelmingly the common case: nothing has ever tripped, so the
            # gate costs one empty-dict test and the signature is never built.
            return False
        return latch.blocked(self._view_signature())

    def _open_aa_backstop_epoch(self):
        """Arm measurement for the AA session that just started."""
        self.latch.open(self._view_signature())
        self._aa_backstop_armed = True

    def _close_aa_backstop_epoch(self):
        """End the AA session and void any trip still queued against it."""
        self._aa_backstop_armed = False
        self.latch.close()

    def _note_aa_frame(self, frame_ms) -> None:
        """Feed one measured AA frame to the latch. Called FROM ``paintEvent``.

        Frame pairing: the armed flag is the token. It is raised only when AA
        is actually switched on and dropped on every path that switches it off
        (including the trip itself), so a frame painted while AA is off is
        never offered here at all — an interleaved non-AA frame cannot be
        miscounted as "the first AA frame". Within a session the frames are
        counted, so the FIRST one is judged against the one-off ceiling and
        every later one feeds the steady EMA; the epoch counter keeps a late
        trip from a previous session from being attributed to this one. All of
        that arithmetic is AaFrameLatch's — safe to run inside a paint.

        This wrapper stays on the hot path, so it does exactly two things
        beyond the delegation: read the armed token, and hand a trip to the
        Qt-side half. The only scene mutation (turning AA back off) is deferred
        to a zero-delay timer, because mutating QGraphicsItems mid-paint is not
        safe.
        """
        if not self._aa_backstop_armed:
            return
        trip = self.latch.note_frame(frame_ms)
        if trip is not None:
            self._trip_aa_backstop(trip[0], trip[1])

    def _trip_aa_backstop(self, reason: str, measured_ms: float) -> None:
        """Qt half of a trip: disarm and queue the epoch-tagged AA disable.

        The bookkeeping half (blacklist entry, memo eviction) already happened
        inside ``AaFrameLatch.note_frame`` — it is pure Python and therefore
        safe in a paint. Only what touches Qt lives here. The verdict is still
        re-recorded from the arguments so this method reads (and behaves) as
        the whole trip when called directly.
        """
        # Disarm FIRST: further frames of this session must not re-trip while
        # the deferred disable is still in flight.
        self._aa_backstop_armed = False
        self.latch.reason = (str(reason), float(measured_ms))
        try:
            self.backstop_timer.setProperty(
                _BACKSTOP_EPOCH_PROPERTY, int(self.aa_backstop_epoch),
            )
            self.backstop_timer.start(0)
        except Exception:
            pass

    def _on_aa_backstop_timeout(self):
        """Deferred half of a trip: drop AA, but only for the epoch measured.

        Generation discipline, same shape as ``dense_raster``'s rebuild timer:
        the epoch travels on the timer as a Qt dynamic property and is checked
        against the live one before anything is mutated, so a trip raised for
        an AA session that a rebuild / a new session has already superseded is
        a no-op instead of tearing AA off the CURRENT session. A
        sender-identity check adds nothing here because this timer object is
        never replaced (unlike the canvas' refresh/coarse timers, which
        ``clear()`` recreates per interaction generation).
        """
        try:
            epoch = int(
                self.backstop_timer.property(_BACKSTOP_EPOCH_PROPERTY)
            )
        except (TypeError, ValueError):
            return
        if epoch != int(self.aa_backstop_epoch):
            return
        self.disable_interactive_quality()

    def disable_interactive_quality(self):
        """Force the interactive path back to AA-off and cancel idle upgrade."""
        if self._aa_backstop_armed:
            # Guarded so the pan/zoom hot path (where AA is already off and
            # nothing is armed) keeps costing exactly the early return below.
            self._close_aa_backstop_epoch()
        timer_was_active = False
        try:
            timer_was_active = self.timer.isActive()
            self.timer.stop()
        except Exception:
            pass
        if not self.aa_on:
            # Hot path: after the first pan/zoom tick AA is already off and
            # the idle timer is stopped. quality_status() walks the scene, so
            # rebuild it only when cancelling a pending idle upgrade changed
            # the reader-facing state from yellow to red.
            if timer_was_active:
                self._emit_quality_status_changed()
            return
        self._set_curves_antialias(False)
        # Fix D: a stale device-coordinate cache would smear during the
        # pan/zoom that this call precedes. Clear unconditionally so no stale
        # cache survives mode switches.
        self._set_curves_cache_mode(QGraphicsItem.NoCache)
        self.aa_on = False
        try:
            self._glw.update()
        except Exception:
            pass
        self._emit_quality_status_changed()

    def schedule_idle_quality(self):
        """Re-arm the single-shot idle-AA timer after a settled interaction."""
        try:
            self.timer.start()
        except Exception:
            pass
        self._emit_quality_status_changed()

    def reconcile_backend_quality(self):
        """Drop latched native AA when a raster backend becomes unavailable."""
        if self._high_raster_cost_status()["blocked"] and self.aa_on:
            self.disable_interactive_quality()
            return
        self._emit_quality_status_changed()

    def try_enable_idle_quality(self):
        """Idle timer slot: enable curve AA once every hands-off gate passes."""
        if not self._idle_quality_allowed():
            # The affordability backend can change while idle (for example a
            # ready dense raster can fall back after a memory-cap change).
            # Do not leave native AA from the former green state latched on.
            if self.aa_on:
                self.disable_interactive_quality()
            else:
                self._emit_quality_status_changed()
            if self._idle_quality_locally_busy():
                # P1-6: a live local drag / overlay Y-drag is a transient
                # block that can clear without any OTHER canvas event
                # necessarily following it. The old code just `return`ed
                # with the timer left stopped, so recovery silently waited
                # for the user to touch this canvas again. Keep polling
                # instead of giving up.
                self.schedule_idle_quality()
            return
        if self.aa_on:
            self._emit_quality_status_changed()
            return
        if self._set_curves_antialias(True) > 0:
            # Fix D (RECALIBRATED, subplot-only): DeviceCoordinateCache blits
            # the cached device-coordinate bitmap on subsequent hover /
            # draw_idle repaints instead of re-rasterizing. Measured 15-30x
            # win for SUBPLOT, but no win for OVERLAY where aux ViewBoxes
            # overlap at one full-plot rect.
            if not getattr(self, "_overlay_mode", False):
                self._set_curves_cache_mode(QGraphicsItem.DeviceCoordinateCache)
            self.aa_on = True
            # Open the measurement window BEFORE requesting the repaint, so
            # the very frame this update() schedules is the one judged as the
            # session's first AA frame.
            self._open_aa_backstop_epoch()
            try:
                self._glw.update()
            except Exception:
                pass
        self._emit_quality_status_changed()

    def _idle_quality_allowed(self) -> bool:
        """Return True only while the user is hands-off and density is safe."""
        # Consult the provider so an injected failure stays observable, but
        # its raw result never solely gates idle recovery: mouseButtons()
        # is GLOBAL (any window, any widget), so using it as the primary
        # busy judge let a press held elsewhere in the app pin THIS canvas
        # pending forever (P1-6). Local canvas interaction state is the
        # primary judge instead — see _idle_quality_locally_busy and
        # docs/lessons-learned/idle-quality-follows-local-canvas-activity.md.
        self._probe_idle_mouse_buttons_provider()
        if self._idle_quality_locally_busy():
            return False
        # Measured-frame latch (spec §4.4): the last word belongs to what was
        # actually observed, so a view whose AA frame was measured
        # unaffordable is refused regardless of what the predictive gates
        # below think of it. Any change to the view produces a different
        # signature and re-arms automatically.
        if self._aa_backstop_blocked():
            return False
        return self._idle_aa_density_ok()

    def _idle_quality_locally_busy(self) -> bool:
        """Whether THIS canvas' own interaction lifecycle blocks idle-AA.

        Mirrors line_canvas.py's ``_IdleQualityActivity.is_busy()``: a live
        ViewBox drag (``_interaction_depth``, incremented by
        ``_begin_view_interaction`` / decremented by ``_end_view_interaction``)
        or an overlay Y-drag (``_overlay_axes.dragging``) are the only
        sticky "busy" conditions this canvas can answer for on its own.
        Neither is perturbed by input delivered to a DIFFERENT window,
        unlike the global ``QApplication.mouseButtons()`` query this
        replaces as the primary judge.
        """
        if self._interaction_depth:
            return True
        return bool(self._overlay_axes.dragging)

    def _probe_idle_mouse_buttons_provider(self) -> None:
        """Defensive injectable query; failures are logged and never gate.

        Kept only so a broken/raising provider stays observable (mirrors
        line_canvas.py's ``_query_idle_mouse_buttons``) — the boolean
        result is discarded, never used to block idle-AA recovery.
        """
        provider = self._mouse_buttons_provider
        if provider is None:
            provider = QApplication.mouseButtons
        try:
            provider()
        except Exception:
            logger.warning(
                "idle-quality mouse-buttons provider failed", exc_info=True,
            )

    def _idle_aa_density_ok(self) -> bool:
        """Hysteresis density gate, branched on overlay vs subplot economics."""
        # RenderProfile is derived from the RAW channel, before any envelope
        # cap.  A dense-discrete/CRC trace can be capped to only ~700 displayed
        # points and still cost hundreds of milliseconds to re-rasterize with
        # AA under a ViewBox transform.  The displayed-point density metric is
        # therefore not a safe affordability proxy for this strategy.
        if self._high_raster_cost_status()["blocked"]:
            self.density_allowed = False
            return False
        # Universal ink budget (spec §4.2): sum the per-line vertical ink of
        # every line still on the native-AA path (raster-covered lines are
        # excluded by _frame_native_ink_total — their paint cost was already
        # replaced by the raster upgrade, so one high-ink raster-covered line
        # must not keep blocking AA for the rest of the frame). Double-
        # threshold hysteresis, same shape as the point-count density gate
        # below: a sum parked in the (_INK_AA_ON, _INK_AA_OFF] dead band holds
        # whatever the previous decision was instead of flapping every frame.
        # AND'd with the point-count gate below, not a replacement for it —
        # "too many points" is still a real, orthogonal constraint.
        total_ink = self._frame_native_ink_total()
        if not self.ink_seeded:
            self.ink_allowed = total_ink <= _INK_AA_OFF
            self.ink_seeded = True
        elif total_ink <= _INK_AA_ON:
            self.ink_allowed = True
        elif total_ink > _INK_AA_OFF:
            self.ink_allowed = False
        if not self.ink_allowed:
            self.density_allowed = False
            return False
        status = self._density_status()
        if status["error"]:
            self.density_allowed = False
            return False
        metric = status["metric"]
        on_budget = status["on_budget"]
        off_budget = status["off_budget"]

        if not self.density_seeded:
            self.density_allowed = metric <= off_budget
            self.density_seeded = True
        elif metric <= on_budget:
            self.density_allowed = True
        elif metric > off_budget:
            self.density_allowed = False
        return bool(self.density_allowed)

    def _export_aa_affordable(self) -> bool:
        """Return whether copy/export can afford forced curve antialiasing."""
        # Export owns its own non-mutating affordability decision.  Do not let
        # the idle hysteresis state opt a dense-discrete curve back into the
        # temporary forced-AA context used by grab_pixmap().
        if self._high_raster_cost_status()["blocked"]:
            return False
        # Same ink ceiling as the idle-AA gate (spec §4.2), one-shot: export
        # has no hysteresis state to seed or hold, it decides fresh on every
        # call, so this is a plain comparison against _INK_AA_OFF (no ON/OFF
        # dead band, no self.ink_allowed/ink_seeded mutation). Lines with no
        # recorded ink are measured on the spot by _frame_native_ink_total,
        # so export cannot be talked into forcing AA over an unmeasured curve.
        if self._frame_native_ink_total() > _INK_AA_OFF:
            return False
        dense_status = self._dense_raster.quality_status()
        if dense_status.get("has_dense") and not self._native_aa_curve_items():
            # Pure dense-raster export stays WYSIWYG and avoids magnifying the
            # screen cache solely because its native-AA metric is empty.
            return False
        status = self._density_status()
        if status["error"]:
            return False
        return status["metric"] <= status["off_budget"]

    def _high_raster_cost_status(self):
        """Describe visible curves that need the raster backend but lack it.

        Membership is the canvas' shared admission predicate (spec §4.3), keyed
        by the same composite ``(data_id, name)`` identity as
        ``_channel_lines``: a dense-discrete profile, or a line whose measured
        ink puts vector AA out of reach.  Either way, until a ready raster
        covers it the curve is on native non-AA and must block the AA gate.
        Visibility matters: a dormant curve retained by the selection-delta
        path must not block AA for the curves that are actually painted.
        """
        empty = {
            "blocked": False, "count": 0, "labels": (),
            "dense_labels": (), "ink_labels": (),
        }
        covered_curves = self._raster_covered_curve_items()
        lines = getattr(self, "_channel_lines", None)
        labels = []
        dense_labels = []
        ink_labels = []
        if lines is None or not hasattr(lines, "composite_items"):
            return empty
        try:
            entries = list(lines.composite_items())
        except Exception:
            return empty
        profiles = self._channel_render_profiles
        for composite_key, display_name, pair in entries:
            try:
                pdi = pair[1].plot_data_item
                if pdi is not None and not pdi.isVisible():
                    continue
            except Exception:
                continue
            if self._raster_backend_eligible(composite_key):
                if getattr(pdi, "curve", None) in covered_curves:
                    continue
                name = str(display_name)
                labels.append(name)
                # Split by WHICH leg admitted the line, because the two carry
                # different user-facing explanations. "密集离散跳变" is only
                # true of the dense-discrete profile (integer-like, <=512
                # unique values — a CRC/counter trace). An analog line
                # admitted on ink alone is a smooth-valued waveform that
                # merely fills its row, and telling the user it is a discrete
                # jump signal is simply wrong.
                if getattr(
                    profiles.get(composite_key), "strategy", None,
                ) == "dense_discrete":
                    dense_labels.append(name)
                else:
                    ink_labels.append(name)
        return {
            "blocked": bool(labels),
            "count": len(labels),
            "labels": tuple(labels),
            "dense_labels": tuple(dense_labels),
            "ink_labels": tuple(ink_labels),
        }

    def _density_status(self):
        overlay = bool(getattr(self, "_overlay_mode", False))
        if overlay:
            on_budget = int(self._AA_OVERLAY_SEGMENT_ON)
            off_budget = int(self._AA_OVERLAY_SEGMENT_OFF)
        else:
            on_budget = int(self._AA_SUBPLOT_SEGMENT_ON)
            off_budget = int(self._AA_SUBPLOT_SEGMENT_OFF)
        sums: dict = {}
        total = 0
        items = self._native_aa_curve_items()
        for it in items:
            try:
                xd, _ = it.getData()
                n = 0 if xd is None else len(xd)
            except Exception:
                return {
                    "overlay": overlay,
                    "metric": 0,
                    "on_budget": on_budget,
                    "off_budget": off_budget,
                    "curve_count": len(items),
                    "error": True,
                }
            total += n
            try:
                vb = it.getViewBox()
            except Exception:
                vb = None
            key = id(vb) if vb is not None else None
            sums[key] = sums.get(key, 0) + n
        metric = total if overlay else (max(sums.values()) if sums else 0)
        return {
            "overlay": overlay,
            "metric": int(metric),
            "on_budget": on_budget,
            "off_budget": off_budget,
            "curve_count": len(items),
            "error": False,
        }

    def quality_status(self):
        """Return the reader-facing AA status for the chart quality dot."""
        items = self._collect_curve_items()
        native_items = self._native_aa_curve_items()
        density = self._density_status()
        raster_cost = self._high_raster_cost_status()
        dense_raster = self._dense_raster.quality_status()
        base = {
            "metric": density["metric"],
            "budget": density["off_budget"],
            "curve_count": density["curve_count"],
            "overlay": density["overlay"],
        }
        if not items:
            return {
                **base,
                "state": "red",
                "tooltip": "抗锯齿未激活：无曲线",
            }
        if raster_cost["blocked"]:
            if dense_raster["state"] == "green":
                return {
                    **base,
                    "state": "green",
                    "render_path": "dense-raster",
                    "high_raster_curve_count": raster_cost["count"],
                    "tooltip": "平滑曲线已完成（高分辨率缓存）",
                }
            if dense_raster["state"] == "yellow":
                return {
                    **base,
                    "state": "yellow",
                    "render_path": "dense-raster",
                    "high_raster_curve_count": raster_cost["count"],
                    "tooltip": "平滑曲线正在生成（高分辨率缓存）",
                }
            def _preview(names):
                text = "、".join(names[:2])
                if len(names) > 2:
                    text += f" 等 {len(names)} 条"
                return text

            # One block, two possible causes — name the one that actually
            # applies to each curve instead of labelling every admitted line
            # a discrete-jump signal (see _high_raster_cost_status).
            parts = []
            if raster_cost["dense_labels"]:
                parts.append(
                    f"高光栅成本曲线 {_preview(list(raster_cost['dense_labels']))}"
                    "（密集离散跳变）"
                )
            if raster_cost["ink_labels"]:
                parts.append(
                    f"满幅振荡曲线 {_preview(list(raster_cost['ink_labels']))}"
                    "（绘制量超预算）"
                )
            return {
                **base,
                "state": "red",
                "render_path": "native-non-aa",
                "block_reason": "high-raster-cost",
                "high_raster_curve_count": raster_cost["count"],
                "high_raster_dense_count": len(raster_cost["dense_labels"]),
                "high_raster_ink_count": len(raster_cost["ink_labels"]),
                "tooltip": "抗锯齿未激活：" + "；".join(parts),
            }
        # Ink gate (spec §4.2), reported in the SAME order the decision is
        # made in _idle_aa_density_ok: after the raster-cost block, before
        # overlay pressure and the point-count budget. Without this branch a
        # frame refused purely on ink — every overlay high-ink frame, now that
        # the ink admission leg short-circuits in overlay — falls through to
        # the bare "抗锯齿未激活" with no reason at all, which is exactly the
        # question the quality dot exists to answer. Reads the LATCHED gate
        # state (seeded + refused) rather than recomputing, so the dead band
        # is honored and this reporting path stays non-mutating.
        if self.ink_seeded and not self.ink_allowed:
            return {
                **base,
                "state": "red",
                "render_path": "native-non-aa",
                "block_reason": "high-ink",
                "frame_ink": int(self._frame_native_ink_total()),
                "ink_budget": int(_INK_AA_OFF),
                "tooltip": "抗锯齿未激活：波形填满绘图区，绘制量超预算",
            }
        # density["error"] AFTER raster-cost and ink — matches
        # _idle_aa_density_ok decision order (B7).
        if density["error"]:
            return {
                **base,
                "state": "red",
                "tooltip": "抗锯齿未激活：曲线密度不可读取",
            }
        label = "叠加密度" if density["overlay"] else "曲线密度"
        if density["metric"] > density["off_budget"]:
            return {
                **base,
                "state": "red",
                "tooltip": (
                    f"抗锯齿未激活：{label} "
                    f"{density['metric']} > {density['off_budget']}"
                ),
            }
        actual_on = bool(native_items)
        for it in native_items:
            try:
                actual_on = actual_on and bool(it.opts.get("antialias", False))
            except Exception:
                actual_on = False
        if self.aa_on and actual_on:
            if dense_raster["state"] == "green":
                return {
                    **base,
                    "state": "green",
                    "render_path": "dense-raster+native-aa",
                    "tooltip": "高分辨率平滑缓存；其他曲线抗锯齿已完成",
                }
            return {
                **base,
                "state": "green",
                "tooltip": "抗锯齿已完成",
            }
        if dense_raster["state"] == "green" and not native_items:
            return {
                **base,
                "state": "green",
                "render_path": "dense-raster",
                "tooltip": "平滑曲线已完成（高分辨率缓存）",
            }
        if dense_raster["state"] == "yellow":
            return {
                **base,
                "state": "yellow",
                "render_path": "dense-raster",
                "tooltip": "平滑曲线正在生成（高分辨率缓存）",
            }
        try:
            timer_active = self.timer.isActive()
        except Exception:
            timer_active = False
        if timer_active or bool(getattr(self, "_refresh_pending", False)):
            return {
                **base,
                "state": "yellow",
                "tooltip": "抗锯齿等待空闲刷新",
            }
        return {
            **base,
            "state": "red",
            "tooltip": "抗锯齿未激活",
        }

    def _emit_quality_status_changed(self):
        try:
            status = self.quality_status()
            if status == self.last_emitted_status:
                return
            self.last_emitted_status = status
            self.quality_status_changed.emit(status)
        except Exception:
            pass

    @contextmanager
    def _curves_antialiased(self):
        """Temporarily enable antialiasing for a grab, then restore it."""
        saved = []
        for it in self._native_aa_curve_items():
            try:
                saved.append((it, it.opts.get("antialias", False)))
                it.opts["antialias"] = True
            except Exception:
                pass
        try:
            yield
        finally:
            for it, prev in saved:
                try:
                    it.opts["antialias"] = bool(prev)
                except Exception:
                    pass
