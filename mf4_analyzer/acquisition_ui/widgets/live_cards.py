"""Center-pane live signal cards.

Spec §Center Pane: each selected signal card shows sparkline, current
value, unit, raster pill, and compact stats (``μ / σ / max``). Per the
2026-07-10 cockpit-live-preview honesty fix (spec §A2/A4) BOTH idle and
recording compute μ/σ/max over the same trimmed ``_LIVE_WINDOW_S`` (30s)
window, so the stats label reads a single honest ``最近 30s`` in both
states — never the old idle ``since 60s`` (the window is 30s now) nor the
recording ``since rec start`` (which implied an unbounded history the
capped display buffer never held).

Each card also carries its own ``REC OFF`` / red-dot indicator. The
toolbar's global REC indicator is driven by the same ``RecHealth.state``
field via ``MainWindow``; the per-card indicator MUST not disagree.

Sparkline rendering (2026-07-10 cockpit-live-preview §A1/A2) positions x
by STREAM timestamp across a fixed ``[t_anchor - 30s, t_anchor]`` window
and draws a connected polyline at low density / a min-max envelope band
plus a last-value line at high density, breaking the trace at genuine
gaps rather than bridging them.
"""

from __future__ import annotations

import math
import re
import time
from collections import deque

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome
from mf4_analyzer.ui_kit.ticks_math import _fmt_tick, _frame_to_nice


# Stats-window tooltip label (spec §State Machine `stats window`, made
# honest by the 2026-07-10 cockpit-live-preview §A2/A4 fix). A-2 unified
# the trim window to ``_LIVE_WINDOW_S`` (30s) in BOTH idle and recording,
# so μ/σ/max now describe the same 30s span in both states. The label
# therefore reads a single honest ``最近 30s`` — matching the sparkline's
# painted window label — instead of the old idle ``since 60s`` (the
# window is 30s now, not 60s) or the recording ``since rec start`` (which
# implied an unbounded history the capped display buffer never held).
STATS_WINDOW_LABEL_IDLE = "最近 30s"
STATS_WINDOW_LABEL_RECORDING = "最近 30s"

# Unified live visible-window length (2026-07-10 cockpit-live-preview
# spec §A2/A4). Idle AND recording both trim the sparkline buffer to the
# newest sample's stream time minus this window, so the coordinate label
# and the μ/σ/max stats describe the SAME honest 30s span. Replaces the
# old idle-only ``_IDLE_WINDOW_S`` (60s) + recording's un-trimmed
# ``since rec start`` buffer.
#
# This is a stats/display-window definition, NOT a threshold band, so it
# is not exposed via ``acquisition_capture.thresholds`` (reserved for
# green/yellow/red band edges per Spec §Threshold Contract). Keeping it
# here as a named local constant keeps the spec citation next to the use
# site without leaking a UI-only constant into the capture-core module.
_LIVE_WINDOW_S = 30.0

# Raw display deque capacity. Sized so the buffer's held time span is
# ALWAYS ≥ the honest window it advertises (spec §A2 invariant): at the
# fastest 1ms raster, 30s = 30000 samples, so 32000 leaves ~2s of
# boundary headroom before the trim floor. This is the DISPLAY raw
# deque, NOT the recording ring buffer / writer. The painter respects
# the widget's actual width via ``self.width()``; this only bounds memory.
_SPARK_MAX_POINTS = 32000

_CARD_TRACE_COLORS = (
    "#2563eb",
    "#059669",
    "#ea580c",
    "#0891b2",
    "#64748b",
)

# Spec 2026-07-08 G1: below this card width the stats label yields to
# signal identity and current value. This is visual layout policy, not
# a health threshold, so it stays in this UI module.
_STATS_COLLAPSE_MIN_CARD_W = 430

# Spec §A: recording state collapses into the swatch — solid red fill.
_RECORDING_SWATCH_COLOR = "#dc2626"

# Spec §F: drop bus time-channels (``t [n:m]``) from the auto-cards seed.
# The capture core still accepts them; this is purely a UI-layer
# suppression that lives at the grid boundary.
_TIME_CHANNEL_RE = re.compile(r"^t\s*\[\d+:\d+\]$")


def _trace_color_for_index(index: int) -> QColor:
    return QColor(_CARD_TRACE_COLORS[index % len(_CARD_TRACE_COLORS)])


def _format_raster_display(raster: str | None) -> str:
    """Spec §C: strip ``event_`` prefix for display (``event_10ms`` → ``10 ms``).

    The full raster name remains available via the pill's tooltip so the
    abbreviated form never hides the truth.
    """
    if not raster:
        return "--"
    if raster.startswith("event_"):
        body = raster[len("event_") :]
        match = re.fullmatch(r"(\d+)([a-zA-Z]+)", body)
        if match:
            return f"{match.group(1)} {match.group(2)}"
        return body
    return raster


# Raster period parsing for the sparkline gap detector. ``event_10ms`` →
# 0.010 s; used only to size the break threshold (below), never to
# re-derive stream timestamps.
_RASTER_UNIT_TO_SECONDS = {"s": 1.0, "ms": 1e-3, "us": 1e-6}

# A genuine break in the trace needs a gap wider than ``3×`` the raster
# period, floored at 1 s so a slow (e.g. 200 ms) raster's normal cadence
# is never mistaken for a dropout. Without raster metadata the detector
# falls back to ``3×`` the median inter-sample interval.
_DISPLAY_MIN_GAP_S = 1.0

# Honest window label painted at the bottom of every sparkline (spec §A3).
# The stream-time trim window is ``_LIVE_WINDOW_S`` (30s) in BOTH idle and
# recording; the label states that span truthfully instead of implying an
# unbounded "since rec start" history.
_WINDOW_LABEL_IDLE = "最近 30s"
_WINDOW_LABEL_RECORDING = "最近 30s（录制中）"

# Value-aware minimum y span for the sparkline scale: a near-constant
# signal (e.g. EcuTemp hovering at 54.3) keeps a readable span rather than
# collapsing the axis onto a single value. ``max(1.0, |center| * 0.02)``.
_SCALE_MIN_SPAN_FRACTION = 0.02
_SCALE_MIN_SPAN_FLOOR = 1.0
# Head/foot headroom applied to the DATA span (before the value-aware
# minimum) so a peak never grazes the frame. Kept small and applied by
# widening the span, NOT by pushing the bounds symmetrically below a
# zero baseline: under a 2-division nice grid a negative-crossing pad
# blows a zero-anchored axis up to a half-empty ``[-3000, 0, 3000]``
# frame (the readability regression A-4 exists to fix). The nice-snap in
# :func:`_frame_to_nice` (floor bottom, extend top) supplies the rest of
# the headroom while keeping the baseline anchored to the data.
_SCALE_PADDING_FRACTION = 0.06

# Sparkline paint gutters (device px): a left slot for right-aligned y-tick
# text (spec §A3) and a bottom slot for the window label. The left gutter is
# only reserved on wide cards — narrow cards (< _STATS_COLLAPSE_MIN_CARD_W)
# suppress the y-tick text and give the full width back to the trace so the
# signal name + current value stay legible (spec §A3 narrow-yield).
_Y_TICK_GUTTER_PX = 34.0
_WINDOW_LABEL_GUTTER_PX = 13.0


def _raster_period_s(raster: str | None) -> float | None:
    """Parse an ``event_<n><unit>`` raster string into seconds.

    Returns ``None`` for unknown / missing rasters, in which case the gap
    detector falls back to the median-interval heuristic.
    """
    if not raster:
        return None
    body = raster[len("event_") :] if raster.startswith("event_") else raster
    match = re.fullmatch(r"(\d+)\s*([a-zA-Z]+)", body)
    if not match:
        return None
    value = int(match.group(1))
    scale = _RASTER_UNIT_TO_SECONDS.get(match.group(2).lower())
    if scale is None or value <= 0:
        return None
    return value * scale


def _spark_scale(
    ymin: float, ymax: float
) -> tuple[float, float, list[float]]:
    """Map a raw value range onto a nice-tick DISPLAY range.

    Two regimes (spec §A3):

    - **Data-dominated** (``data_span >= min_span``): pad the real data
      bounds by ``_SCALE_PADDING_FRACTION`` head/foot so a peak never
      grazes the frame, but clamp the low bound back to ``0`` when the
      data is non-negative — a zero-anchored signal (rpm from 0, percent)
      keeps its natural baseline instead of manufacturing a negative axis.
    - **Constant / near-constant** (``data_span < min_span``): center a
      value-aware minimum span ``max(1.0, |center| * 0.02)`` on the data so
      the axis does NOT collapse onto a single value (``EcuTemp`` at
      54.30–54.34 keeps a readable span).

    Both regimes then snap to a nice 2-division grid via
    :func:`_frame_to_nice`, whose floor/extend supplies the remaining
    headroom while keeping round tick values. A symmetric pad is NOT
    applied before the snap: under a 2-division grid a negative-crossing
    pad degenerates ``0..2360`` into a half-empty ``[-3000, 0, 3000]``
    frame — the readability regression A-4 exists to fix.

    Returns ``(lo, hi, ticks)`` where ``lo``/``hi`` are the snapped range
    bounds fed to the projection (``ticks[0] == lo``, ``ticks[-1] == hi``).
    """
    try:
        ymin = float(ymin)
        ymax = float(ymax)
    except (TypeError, ValueError):
        ymin, ymax = 0.0, 0.0
    if not (math.isfinite(ymin) and math.isfinite(ymax)):
        ymin, ymax = 0.0, 0.0
    if ymax < ymin:
        ymin, ymax = ymax, ymin

    center = (ymin + ymax) / 2.0
    raw_span = ymax - ymin
    min_span = max(_SCALE_MIN_SPAN_FLOOR, abs(center) * _SCALE_MIN_SPAN_FRACTION)
    if raw_span >= min_span:
        pad = raw_span * _SCALE_PADDING_FRACTION
        lo = ymin - pad
        hi = ymax + pad
        # Keep the zero baseline: a non-negative signal never gets a
        # manufactured negative axis (which the n=2 grid blows up).
        if ymin >= 0.0 and lo < 0.0:
            lo = 0.0
    else:
        lo = center - min_span / 2.0
        hi = center + min_span / 2.0
    bottom, top, ticks = _frame_to_nice(lo, hi, 2)
    return bottom, top, ticks


def _sample_state(
    last_arrival: float | None, now: float, raster_period: float | None
) -> str:
    """Classify arrival cadence off a monotonic ARRIVAL clock.

    - ``"no-data"``: no sample has ever been received (``last_arrival`` is
      ``None``).
    - ``"stale"``: the wall-clock gap since the last arrival exceeds
      ``max(1s, 3 × raster_period)`` — a slow raster gets a proportionally
      longer grace window, a fast raster the 1 s floor.
    - ``"live"``: a recent arrival (a fresh sample immediately clears
      ``stale``).

    This is decoupled from stream time on purpose: the x axis keeps using
    the STREAM timestamp so the trace stays honest, while staleness is a
    property of when data last *arrived*.
    """
    if last_arrival is None:
        return "no-data"
    threshold = _DISPLAY_MIN_GAP_S
    if raster_period and raster_period > 0:
        threshold = max(_DISPLAY_MIN_GAP_S, 3.0 * float(raster_period))
    if (now - last_arrival) > threshold:
        return "stale"
    return "live"


def _finite_value_bounds(
    samples: list[tuple[float, float]],
) -> tuple[float | None, float | None]:
    """Return ``(ymin, ymax)`` over finite sample values, or ``(None, None)``."""
    ymin = math.inf
    ymax = -math.inf
    for _ts, v in samples:
        if not math.isfinite(v):
            continue
        if v < ymin:
            ymin = v
        if v > ymax:
            ymax = v
    if not math.isfinite(ymin):
        return None, None
    return ymin, ymax


def _break_threshold(
    samples: list[tuple[float, float]], raster_period: float | None
) -> float:
    """Largest gap that still counts as continuous.

    ``max(3×raster_period, 1s)`` when the raster is known; otherwise ``3×``
    the median finite inter-sample interval (``inf`` if undeterminable, so
    nothing breaks).
    """
    if raster_period and raster_period > 0:
        return max(3.0 * raster_period, _DISPLAY_MIN_GAP_S)
    finite_ts = [ts for ts, v in samples if math.isfinite(ts) and math.isfinite(v)]
    if len(finite_ts) < 2:
        return math.inf
    intervals = sorted(
        finite_ts[i + 1] - finite_ts[i] for i in range(len(finite_ts) - 1)
    )
    median = intervals[len(intervals) // 2]
    return 3.0 * median if median > 0 else math.inf


def _split_runs(
    samples: list[tuple[float, float]], *, raster_period: float | None = None
) -> list[list[tuple[float, float]]]:
    """Split time-ordered samples into contiguous, all-finite runs.

    A run ends where the inter-sample gap exceeds :func:`_break_threshold`
    OR where a non-finite sample interrupts the stream. Non-finite samples
    are dropped AND force a break, so the painter never bridges a NaN gap
    with a spurious segment (cf. lessons-learned
    ``arraytoqpath-not-byte-identical-to-moveto-lineto-loop``). Returns a
    list of runs so breakpoints are representable — a single flat
    ``list[QPointF]`` cannot express a gap.
    """
    threshold = _break_threshold(samples, raster_period)
    runs: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    prev_ts: float | None = None
    for ts, v in samples:
        if not (math.isfinite(ts) and math.isfinite(v)):
            if cur:
                runs.append(cur)
                cur = []
            prev_ts = None
            continue
        if prev_ts is not None and (ts - prev_ts) > threshold:
            if cur:
                runs.append(cur)
            cur = [(ts, v)]
        else:
            cur.append((ts, v))
        prev_ts = ts
    if cur:
        runs.append(cur)
    return runs


def _build_polyline(
    samples: list[tuple[float, float]],
    w: float,
    h: float,
    window: float,
    t_anchor: float,
    ymin: float,
    ymax: float,
) -> list[QPointF]:
    """Project ``(ts, value)`` samples onto the sparkline rect.

    x is TIME-proportional across the visible window,
    ``x = w * (ts - (t_anchor - window)) / window`` — never a bin index —
    so a card that only received the last 5 s of a 30 s window draws its
    trace hugging the right edge instead of stretched across the full
    width. y = ``h - (v - ymin)/(ymax - ymin) * h``. Returns a flat list
    of ``QPointF`` (one per sample); callers that must honour gaps split
    the samples via :func:`_split_runs` first and project each run
    separately.
    """
    span = ymax - ymin
    x0 = t_anchor - window
    inv_window = (1.0 / window) if window else 0.0
    pts: list[QPointF] = []
    for ts, v in samples:
        x = w * (ts - x0) * inv_window
        if span > 0:
            y = h - (v - ymin) / span * h
        else:
            y = h * 0.5
        pts.append(QPointF(x, y))
    return pts


def _build_envelope(
    samples: list[tuple[float, float]],
    w: float,
    h: float,
    window: float,
    t_anchor: float,
    ymin: float,
    ymax: float,
    *,
    raster_period: float | None = None,
) -> tuple[QPainterPath, list[QPointF | None]]:
    """High-density render: a min/max band plus a last-value line.

    Columns tile the FULL ``[t_anchor - window, t_anchor]`` window (one
    per output pixel), so a 5 s slice of dense data only lights the right
    5/30 of the band rather than being stretched across ``[first, last]``.
    Each occupied column contributes its ``(min, max)`` to the band and
    its LAST value to the connecting line — connecting min/max instead
    would fabricate a full-height zig-zag that reads as noise. Returns
    ``(band_path, line_pts)`` where ``line_pts`` uses a ``None`` element
    to mark a genuine gap between column runs.
    """
    columns = max(1, int(round(w)))
    x0 = t_anchor - window
    inv_window = (1.0 / window) if window else 0.0
    # Per column accumulator: [mn, mx, last_value, last_ts].
    cols: list[list[float] | None] = [None] * columns
    for ts, v in samples:
        if not (math.isfinite(ts) and math.isfinite(v)):
            continue
        ci = int((ts - x0) * inv_window * columns)
        if ci < 0:
            ci = 0
        elif ci >= columns:
            ci = columns - 1
        c = cols[ci]
        if c is None:
            cols[ci] = [v, v, v, ts]
        else:
            if v < c[0]:
                c[0] = v
            if v > c[1]:
                c[1] = v
            c[2] = v
            c[3] = ts

    span = ymax - ymin

    def py(val: float) -> float:
        if span > 0:
            return h - (val - ymin) / span * h
        return h * 0.5

    col_px = w / columns

    def cx(ci: float) -> float:
        return (ci + 0.5) * col_px

    threshold = _break_threshold(samples, raster_period)

    # Group occupied columns into runs, breaking on a genuine time gap.
    runs: list[list[list[float]]] = []
    run: list[list[float]] = []
    prev_ts: float | None = None
    for ci in range(columns):
        c = cols[ci]
        if c is None:
            continue
        mn, mx, last, ts = c
        if prev_ts is not None and (ts - prev_ts) > threshold:
            if run:
                runs.append(run)
            run = []
        run.append([float(ci), mn, mx, last])
        prev_ts = ts
    if run:
        runs.append(run)

    band_path = QPainterPath()
    line_pts: list[QPointF | None] = []
    for run in runs:
        if line_pts:
            line_pts.append(None)  # gap separator between runs
        # Band polygon: upper edge (max) left→right, lower edge (min)
        # right→left, then close.
        band_path.moveTo(cx(run[0][0]), py(run[0][2]))
        for ci, _mn, mx, _last in run[1:]:
            band_path.lineTo(cx(ci), py(mx))
        for ci, mn, _mx, _last in reversed(run):
            band_path.lineTo(cx(ci), py(mn))
        band_path.closeSubpath()
        for ci, _mn, _mx, last in run:
            line_pts.append(QPointF(cx(ci), py(last)))

    return band_path, line_pts


class _ElidedLabel(QLabel):
    """QLabel that elides long signal names in the middle.

    EPS channel names often share long prefixes; the suffix is usually
    the distinguishing part, so middle elision preserves both ends.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text

    def full_text(self) -> str:
        return self._full_text

    def visible_text(self) -> str:
        return self.text()

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._update_elide()

    def _update_elide(self) -> None:
        width = max(16, self.width())
        text = self.fontMetrics().elidedText(
            self._full_text, Qt.ElideMiddle, width
        )
        if "…" in text and not text.startswith(self._full_text[:4]):
            text = self._prefix_preserving_elide(width)
        super().setText(text)

    def _prefix_preserving_elide(self, width: int) -> str:
        metrics = self.fontMetrics()
        prefix = self._full_text[: min(4, len(self._full_text))]
        ellipsis = "…"
        if metrics.horizontalAdvance(prefix + ellipsis) > width:
            return prefix + ellipsis
        tail = ""
        for i in range(1, len(self._full_text) - len(prefix) + 1):
            candidate_tail = self._full_text[-i:]
            candidate = prefix + ellipsis + candidate_tail
            if metrics.horizontalAdvance(candidate) > width:
                break
            tail = candidate_tail
        return prefix + ellipsis + tail

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override.
        super().resizeEvent(event)
        self._update_elide()


class Sparkline(QWidget):
    """A tiny min/max sparkline painter.

    Consumes a ``deque[(ts, value)]`` external buffer plus a
    ``target_pixels`` value sized to the current widget width. Repaints
    via :meth:`request_repaint` which schedules a Qt update().
    """

    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self.setObjectName("liveCardSparkline")
        self.setProperty("traceColor", self._color.name())
        self._buffer: deque[tuple[float, float]] = deque(maxlen=_SPARK_MAX_POINTS)
        # Raster period (seconds) for the gap detector; ``None`` ⇒ fall
        # back to the median-interval heuristic in :func:`_split_runs`.
        self._raster_period_s: float | None = None
        # A-4 paint state. ``_show_y_ticks`` reserves the left y-tick
        # gutter (suppressed on narrow cards); ``_recording_label`` picks
        # the honest window label; ``_sample_state`` / ``_stale_age`` drive
        # the ``无样本`` / ``停更 x.xs`` hints (arrival-clock derived, set by
        # the owning card — the trace x axis still uses STREAM time).
        self._show_y_ticks = True
        self._recording_label = False
        self._sample_state = "no-data"
        self._stale_age: float | None = None
        # Spec §B: floor the sparkline at 72px and let it absorb free
        # vertical space so cards grow the curve when N decreases.
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_trace_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.setProperty("traceColor", self._color.name())
        self.update()

    def set_raster_period(self, period_s: float | None) -> None:
        """Set the raster period (seconds) used to detect trace breaks."""
        self._raster_period_s = period_s

    def set_show_y_ticks(self, show: bool) -> None:
        """Reserve (or suppress) the left y-tick text gutter.

        Suppressed on narrow cards so the signal name + current value keep
        priority (spec §A3 narrow-yield). Idempotent + repaints on change.
        """
        show = bool(show)
        if show != self._show_y_ticks:
            self._show_y_ticks = show
            self.update()

    def y_ticks_visible(self) -> bool:
        return self._show_y_ticks

    def set_recording_label(self, recording: bool) -> None:
        """Pick the honest window label (``最近 30s`` vs ``…（录制中）``)."""
        recording = bool(recording)
        if recording != self._recording_label:
            self._recording_label = recording
            self.update()

    def window_label(self) -> str:
        return _WINDOW_LABEL_RECORDING if self._recording_label else _WINDOW_LABEL_IDLE

    def set_sample_state(self, state: str, stale_age: float | None = None) -> None:
        """Set the arrival-cadence hint (``no-data`` / ``live`` / ``stale``).

        ``stale_age`` (seconds since the last arrival) renders the low-key
        ``停更 x.xs`` note. Only the hint + repaint change here; the trace
        geometry and the global Health band are untouched (spec §A3).
        """
        self._sample_state = state
        self._stale_age = stale_age
        self.update()

    def push(self, timestamp_s: float, value: float) -> None:
        self._buffer.append((float(timestamp_s), float(value)))

    def trim_to_window(self, t_min: float | None) -> None:
        """Drop samples with ``ts < t_min``. ``None`` ⇒ no trim."""
        if t_min is None:
            return
        while self._buffer and self._buffer[0][0] < t_min:
            self._buffer.popleft()

    def reset(self) -> None:
        self._buffer.clear()
        self.update()

    def request_repaint(self) -> None:
        self.update()

    @property
    def sample_count(self) -> int:
        return len(self._buffer)

    def _small_font(self) -> QFont:
        """A slightly smaller font for axis text than the widget default."""
        font = QFont(self.font())
        size = self.font().pointSizeF()
        if size <= 0:
            size = 9.0
        font.setPointSizeF(max(7.0, size - 1.0))
        return font

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        full_w = float(rect.width())
        full_h = float(rect.height())

        # A-4: reserve a left slot for y-tick text (wide cards only) and a
        # bottom slot for the honest window label; the trace + grid live in
        # the remaining plot rect. Narrow cards drop the y-tick gutter so
        # the full width goes to the curve (name/value keep priority).
        left_gutter = _Y_TICK_GUTTER_PX if self._show_y_ticks else 0.0
        bottom_gutter = _WINDOW_LABEL_GUTTER_PX
        plot_w = max(1.0, full_w - left_gutter)
        plot_h = max(1.0, full_h - bottom_gutter)

        # Faint reference grid, now scoped to the plot rect so it aligns
        # with the trace instead of the full widget.
        painter.setPen(QPen(QColor("#e5e7eb"), 0.8))
        for fraction in (0.25, 0.5, 0.75):
            y = plot_h * fraction
            painter.drawLine(
                QPointF(left_gutter, y), QPointF(left_gutter + plot_w, y)
            )
        for fraction in (0.25, 0.5, 0.75):
            x = left_gutter + plot_w * fraction
            painter.drawLine(QPointF(x, 0.0), QPointF(x, plot_h))

        # The window label is honest even before any data arrives.
        self._paint_window_label(painter, left_gutter, plot_w, plot_h, full_h)

        samples = list(self._buffer)
        if not samples:
            self._paint_no_data(painter, left_gutter, plot_w, plot_h)
            painter.end()
            return

        ymin, ymax = _finite_value_bounds(samples)
        if ymin is None:
            self._paint_no_data(painter, left_gutter, plot_w, plot_h)
            painter.end()
            return

        # A-4: value-aware nice-tick scale — a constant signal keeps a
        # readable span instead of collapsing onto a single value.
        lo, hi, ticks = _spark_scale(ymin, ymax)

        # x anchor = newest STREAM timestamp, never a wall clock, so the
        # trace's right edge tracks the data itself (spec §A1). Staleness
        # is judged separately off the arrival clock (set_sample_state).
        t_anchor = samples[-1][0]
        w_target = max(8, plot_w)

        painter.save()
        painter.translate(left_gutter, 0.0)
        if len(samples) <= 2 * w_target:
            self._paint_polyline(painter, samples, plot_w, plot_h, t_anchor, lo, hi)
        else:
            self._paint_envelope(painter, samples, plot_w, plot_h, t_anchor, lo, hi)
        painter.restore()

        if self._show_y_ticks:
            self._paint_y_ticks(painter, ticks, lo, hi, left_gutter, plot_h)
        self._paint_stale_note(painter, left_gutter, plot_w)
        painter.end()

    def _paint_y_ticks(
        self,
        painter: QPainter,
        ticks: list[float],
        lo: float,
        hi: float,
        left_gutter: float,
        plot_h: float,
    ) -> None:
        """Right-align the round y-tick labels in the left gutter."""
        span = hi - lo
        if span <= 0 or left_gutter <= 0:
            return
        painter.setPen(QPen(QColor("#9aa4b2")))
        painter.setFont(self._small_font())
        fm = painter.fontMetrics()
        text_h = float(fm.height())
        gutter_w = left_gutter - 4.0
        for value in ticks:
            y = plot_h - (value - lo) / span * plot_h
            top = min(max(y - text_h / 2.0, 0.0), plot_h - text_h)
            painter.drawText(
                QRectF(0.0, top, gutter_w, text_h),
                int(Qt.AlignRight | Qt.AlignVCenter),
                _fmt_tick(value),
            )

    def _paint_window_label(
        self,
        painter: QPainter,
        left_gutter: float,
        plot_w: float,
        plot_h: float,
        full_h: float,
    ) -> None:
        """Honest ``最近 30s`` label along the bottom of the plot rect."""
        painter.setPen(QPen(QColor("#9aa4b2")))
        painter.setFont(self._small_font())
        painter.drawText(
            QRectF(left_gutter, plot_h, max(1.0, plot_w - 2.0), full_h - plot_h),
            int(Qt.AlignRight | Qt.AlignVCenter),
            self.window_label(),
        )

    def _paint_no_data(
        self, painter: QPainter, left_gutter: float, plot_w: float, plot_h: float
    ) -> None:
        """Centered ``无样本`` hint before the first sample ever arrives."""
        if self._sample_state != "no-data":
            return
        painter.setPen(QPen(QColor("#9aa4b2")))
        painter.setFont(self._small_font())
        painter.drawText(
            QRectF(left_gutter, 0.0, plot_w, plot_h),
            int(Qt.AlignCenter),
            "无样本",
        )

    def _paint_stale_note(
        self, painter: QPainter, left_gutter: float, plot_w: float
    ) -> None:
        """Low-interference ``停更 x.xs`` note in the top-right corner.

        Stale only annotates; it never extends or bridges the frozen trace
        (the x anchor is the newest STREAM timestamp, so a stalled signal
        simply stops advancing) and it does NOT touch the global Health
        band (spec §A3).
        """
        if self._sample_state != "stale" or self._stale_age is None:
            return
        painter.setPen(QPen(QColor("#b0713a")))
        painter.setFont(self._small_font())
        painter.drawText(
            QRectF(left_gutter, 1.0, max(1.0, plot_w - 4.0), 14.0),
            int(Qt.AlignRight | Qt.AlignTop),
            f"停更 {self._stale_age:.1f}s",
        )

    def _paint_polyline(
        self,
        painter: QPainter,
        samples: list[tuple[float, float]],
        w: float,
        h: float,
        t_anchor: float,
        ymin: float,
        ymax: float,
    ) -> None:
        """Low-density branch: one connected ``QPainterPath`` per run."""
        painter.setPen(QPen(self._color, 1.4))
        painter.setBrush(Qt.NoBrush)
        for run in _split_runs(samples, raster_period=self._raster_period_s):
            pts = _build_polyline(
                run, w, h, _LIVE_WINDOW_S, t_anchor, ymin, ymax
            )
            if not pts:
                continue
            if len(pts) == 1:
                # Single point: a bare dot (a moveTo-only path draws
                # nothing), mirroring the loop's degenerate case.
                painter.drawPoint(pts[0])
                continue
            # Each run is already contiguous + all-finite, so a plain
            # moveTo/lineTo path is safe (arraytoqpath lesson: only vector
            # over all-finite n>=2 — here we build the path by hand).
            path = QPainterPath()
            path.moveTo(pts[0])
            for p in pts[1:]:
                path.lineTo(p)
            painter.drawPath(path)

    def _paint_envelope(
        self,
        painter: QPainter,
        samples: list[tuple[float, float]],
        w: float,
        h: float,
        t_anchor: float,
        ymin: float,
        ymax: float,
    ) -> None:
        """High-density branch: min/max band + last-value connecting line."""
        band, line_pts = _build_envelope(
            samples,
            w,
            h,
            _LIVE_WINDOW_S,
            t_anchor,
            ymin,
            ymax,
            raster_period=self._raster_period_s,
        )
        if not band.isEmpty():
            fill = QColor(self._color)
            fill.setAlphaF(0.16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(fill))
            painter.drawPath(band)
        painter.setPen(QPen(self._color, 1.4))
        painter.setBrush(Qt.NoBrush)
        seg = QPainterPath()
        started = False
        for p in line_pts:
            if p is None:
                if started:
                    painter.drawPath(seg)
                seg = QPainterPath()
                started = False
                continue
            if not started:
                seg.moveTo(p)
                started = True
            else:
                seg.lineTo(p)
        if started:
            painter.drawPath(seg)


class LiveSignalCard(QFrame):
    """One card per selected signal.

    Public API:

    - :meth:`push_sample` — append ``(timestamp_s, value)``.
    - :meth:`set_recording` — switch stats label / scope.
    - :meth:`refresh` — recompute stats label + sparkline.
    """

    activated = pyqtSignal(str)

    def __init__(
        self,
        name: str,
        unit: str = "",
        raster: str | None = None,
        card_index: int = 0,
        parent: QWidget | None = None,
        *,
        clock=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("liveSignalCard")
        self._name = name
        self._unit = unit
        self._raster = raster
        self._trace_color = _trace_color_for_index(card_index)
        self.setProperty("traceColor", self._trace_color.name())
        self._recording = False
        self._rec_start_ts: float | None = None
        self._stats_full_text = "μ — · σ — · max —"
        # A-4: monotonic ARRIVAL clock (injectable so tests never sleep).
        # Records when the last sample *arrived* — orthogonal to the
        # sample's STREAM timestamp, which still drives the trace x axis.
        self._clock = clock if clock is not None else time.monotonic
        self._last_arrival: float | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        # Spec §B: cards absorb free vertical space so the sparkline can
        # grow with the viewport. Without Expanding policy the trailing
        # stretch eats the slack instead.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        outer = QVBoxLayout(self)
        # Spec §E: tighter card vertical margins (8 → 6). Horizontal
        # margins unchanged.
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(4)

        # Spec §C: a single tidy header row —
        #   [swatch] Name  ——  stats(μ σ max)  raster·unit  value
        header = QHBoxLayout()
        header.setSpacing(8)
        self._swatch_label = QLabel(self)
        self._swatch_label.setObjectName("liveCardSwatch")
        self._swatch_label.setFixedSize(10, 10)
        header.addWidget(self._swatch_label, 0, Qt.AlignVCenter)

        self._name_label = _ElidedLabel(self._name, self)
        self._name_label.setObjectName("liveCardName")
        self._name_label.setMinimumWidth(60)
        self._name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._name_label.setToolTip(self._name)
        # QSS owns the typography weight (Spec §D: weight 700); avoid
        # forcing bold from Python so QSS wins on polish.
        header.addWidget(self._name_label)

        self._stats_label = QLabel("μ — · σ — · max —", self)
        self._stats_label.setObjectName("liveCardStats")
        self._stats_label.setMinimumWidth(0)
        self._stats_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header.addWidget(self._stats_label)

        header.addStretch(1)

        # Spec §C: raster pill + unit sit immediately left of the value
        # on the right side of the header.
        self._raster_pill = QLabel(_format_raster_display(self._raster), self)
        self._raster_pill.setObjectName("liveCardRaster")
        self._raster_pill.setToolTip(self._raster if self._raster else "")
        header.addWidget(self._raster_pill)

        unit_text = self._unit if self._unit else ""
        self._unit_label = QLabel(unit_text, self)
        self._unit_label.setObjectName("liveCardUnit")
        header.addWidget(self._unit_label)

        self._value_label = QLabel("—", self)
        self._value_label.setObjectName("liveCardValue")
        self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value_label.setMinimumWidth(72)
        self._value_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        header.addWidget(self._value_label)
        outer.addLayout(header)

        # Spec §A: per-card REC row is removed entirely. State is
        # conveyed by the swatch fill + a 1px red left border driven by
        # the ``recording`` dynamic property on the card itself.

        self._spark = Sparkline(self._trace_color, self)
        self._spark.set_raster_period(_raster_period_s(self._raster))
        # Stretch=1 so the sparkline absorbs any vertical slack inside
        # the card's QVBoxLayout (header takes its sizeHint, the rest
        # belongs to the curve).
        outer.addWidget(self._spark, 1)
        self._apply_trace_color()
        # Seed the recording-state dynamic property so QSS selectors
        # keyed on ``[recording="true"]`` resolve at first polish.
        self.setProperty("recording", False)
        # Seed the stats tooltip so the visible label stays terse.
        self._stats_label.setToolTip(f"Stats window: {STATS_WINDOW_LABEL_IDLE}")
        self._sync_header_compactness()

    def set_visual_index(self, card_index: int) -> None:
        self._trace_color = _trace_color_for_index(card_index)
        self.setProperty("traceColor", self._trace_color.name())
        self._spark.set_trace_color(self._trace_color)
        self._apply_trace_color()

    def update_metadata(self, *, unit: str, raster: str | None) -> None:
        self._unit = unit
        self._raster = raster
        self._unit_label.setText(unit if unit else "")
        self._raster_pill.setText(_format_raster_display(raster))
        self._raster_pill.setToolTip(raster if raster else "")
        self._spark.set_raster_period(_raster_period_s(raster))

    def _apply_trace_color(self) -> None:
        """Paint the swatch.

        Spec §A: when recording, the swatch turns solid red regardless
        of the card's trace color. When not recording, the swatch shows
        the trace color.
        """
        if self._recording:
            fill = _RECORDING_SWATCH_COLOR
        else:
            fill = self._trace_color.name()
        # ``traceColor`` is read by tests + QSS attribute selectors; we
        # surface the *currently rendered* swatch color here so callers
        # do not need to peek into stylesheet text.
        self._swatch_label.setProperty("traceColor", fill)
        self._swatch_label.setStyleSheet(
            f"background-color: {fill}; border-radius: 5px;"
        )

    # ------------------------------------------------------------------
    # Data ingest
    # ------------------------------------------------------------------

    def push_sample(self, timestamp_s: float, value: float) -> None:
        self._spark.push(timestamp_s, value)
        self._value_label.setText(f"{value:.3f}")
        # Stamp the ARRIVAL time so staleness is judged on when data last
        # arrived, not on the sample's stream timestamp. A fresh arrival
        # immediately clears a prior ``stale`` state (see sample_state).
        self._last_arrival = self._clock()

    def reset_buffer(self) -> None:
        self._spark.reset()

    def sample_state(self) -> str:
        """Arrival-cadence state: ``no-data`` / ``live`` / ``stale``.

        Derived from the injectable monotonic arrival clock; the trace x
        axis keeps using stream time regardless (spec §A3).
        """
        return _sample_state(
            self._last_arrival, self._clock(), _raster_period_s(self._raster)
        )

    def _update_sample_state(self) -> None:
        now = self._clock()
        state = _sample_state(
            self._last_arrival, now, _raster_period_s(self._raster)
        )
        stale_age = (
            now - self._last_arrival
            if state == "stale" and self._last_arrival is not None
            else None
        )
        self._spark.set_sample_state(state, stale_age)

    def _sync_header_compactness(self) -> None:
        compact = 0 < self.width() < _STATS_COLLAPSE_MIN_CARD_W
        self._stats_label.setText(self._stats_full_text)
        self._stats_label.setVisible(not compact)
        # Same width threshold gates the sparkline's y-tick gutter so a
        # narrow card yields the axis text to the name + current value.
        self._spark.set_show_y_ticks(not compact)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override.
        super().resizeEvent(event)
        self._sync_header_compactness()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override.
        if event.button() == Qt.LeftButton:
            self.activated.emit(self._name)
        super().mousePressEvent(event)

    def set_recording(self, recording: bool, rec_start_ts: float | None = None) -> None:
        """Flip recording state.

        Spec §A: the per-card REC row is gone; state is encoded in the
        swatch fill plus a 1 px red left border driven by the dynamic
        property ``recording`` on the card itself. We re-polish the
        widget so QSS attribute selectors keyed on ``[recording="true"]``
        pick up the new value WITHOUT rebuilding the stylesheet.
        """
        self._recording = bool(recording)
        self._rec_start_ts = rec_start_ts if recording else None
        if self._recording:
            # Recording's cumulative window starts at the freshly
            # cleared buffer. This also prevents stream-time restarts
            # from interleaving old and new relative timestamps.
            self._spark.reset()
        # Keep the honest window label in sync (``最近 30s（录制中）``).
        self._spark.set_recording_label(self._recording)
        self.setProperty("recording", self._recording)
        # Force a stylesheet re-evaluation so the [recording="true"]
        # selector toggles the red left border immediately.
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self._apply_trace_color()
        self.refresh()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Recompute stats label and trim to the honest live window.

        Time-base invariant (2026-07-07 spec F1): the trim floor is
        derived from the buffer's own newest sample (stream time),
        never from a wall clock / ``time.monotonic()``. Both idle and
        recording now trim to ``newest - _LIVE_WINDOW_S`` (2026-07-10
        spec §A2/A4): the old recording ``t_min=None`` no-trim branch let
        a 4096-cap deque silently cover only ~4s while the label claimed
        the full recording, so μ/σ/max and the coordinate window lied.
        The stats below are computed over this SAME trimmed 30s buffer.
        """
        label = (
            STATS_WINDOW_LABEL_RECORDING
            if self._recording
            else STATS_WINDOW_LABEL_IDLE
        )
        buf = self._spark._buffer  # noqa: SLF001 - sibling widget.
        t_min: float | None = (buf[-1][0] - _LIVE_WINDOW_S) if buf else None
        self._spark.trim_to_window(t_min)
        # Refresh the arrival-cadence hint (no-data / live / stale) off the
        # monotonic arrival clock before the repaint.
        self._update_sample_state()
        self._spark.request_repaint()
        self._stats_label.setToolTip(f"Stats window: {label}")

        values = [v for _, v in list(self._spark._buffer)]  # noqa: SLF001 - sibling widget.
        if not values:
            self._stats_full_text = "μ — · σ — · max —"
            self._sync_header_compactness()
            return
        n = len(values)
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(var)
        peak = max(values)
        self._stats_full_text = f"μ {mean:.2f} · σ {std:.2f} · max {peak:.2f}"
        self._sync_header_compactness()

    @property
    def name(self) -> str:
        return self._name


class LiveCardGrid(QWidget):
    """Container for the per-signal cards plus a placeholder when empty.

    The Cockpit center pane is built around this widget so the
    "Connected idle already streams live charts" requirement holds:
    the moment :meth:`set_signals` runs with a non-empty list, the
    grid swaps the placeholder for the cards.
    """

    unpin_requested = pyqtSignal(str)
    pins_reset_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)
        self._pinning_enabled = False
        self._all_signals: list[tuple[str, str, str | None]] = []
        self._focused_channel: str | None = None
        # Outer shell: thin zero-margin QVBoxLayout whose sole child is
        # the scroll area. The cards/placeholder layout lives on an
        # inner host widget inside the scroll viewport so vertical
        # overflow is solved at the container, not by shrinking cards
        # (Spec §S1.2, lessons: responsive-pane-containers +
        # inspector-content-max-width-and-tinted-card-bleed).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Spec 2026-07-08 §G6: 选中数 > 实时显示数时的提示条。
        self._summary_bar = QLabel(self)
        self._summary_bar.setObjectName("liveMonitorSummary")
        self._summary_bar.setVisible(False)
        outer.addWidget(self._summary_bar)

        self._focus_shell = QFrame(self)
        self._focus_shell.setObjectName("liveFocusShell")
        focus_layout = QHBoxLayout(self._focus_shell)
        focus_layout.setContentsMargins(12, 6, 12, 6)
        focus_layout.setSpacing(8)
        self._focus_label = QLabel("", self._focus_shell)
        self._focus_label.setObjectName("liveFocusBar")
        focus_layout.addWidget(self._focus_label, stretch=1)
        self._focus_back_btn = QPushButton("返回全部", self._focus_shell)
        self._focus_back_btn.setObjectName("liveFocusBackButton")
        self._focus_back_btn.clicked.connect(self.clear_focus)
        focus_layout.addWidget(self._focus_back_btn)
        self._focus_shell.setVisible(False)
        outer.addWidget(self._focus_shell)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setObjectName("liveCardGridScroll")
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll_area.setFrameShape(QFrame.NoFrame)

        self._scroll_body = QWidget(self._scroll_area)
        self._scroll_body.setObjectName("liveCardGridBody")
        self._layout = QVBoxLayout(self._scroll_body)
        self._layout.setContentsMargins(12, 12, 12, 12)
        # Spec §E: tighter inter-card spacing so the sparkline gets more
        # room when N cards stack.
        self._layout.setSpacing(4)
        self._scroll_area.setWidget(self._scroll_body)
        outer.addWidget(self._scroll_area)

        self._disconnected_canvas = self._build_disconnected_canvas()
        self._layout.addWidget(self._disconnected_canvas)
        self._layout.addStretch(1)
        self._cards: dict[str, LiveSignalCard] = {}
        self._card_cache: dict[str, LiveSignalCard] = {}

    def _build_disconnected_canvas(self) -> QWidget:
        canvas = QWidget(self)
        canvas.setObjectName("cockpitDisconnectedCanvas")
        canvas.setMinimumHeight(180)
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(24, 24, 24, 24)
        canvas_layout.setSpacing(8)
        canvas_layout.addStretch(1)

        title = QLabel("未连接 ECU", canvas)
        title.setObjectName("cockpitDisconnectedTitle")
        title.setAlignment(Qt.AlignCenter)
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title.setFont(title_font)
        canvas_layout.addWidget(title)

        copy = QLabel("连接后这里会显示实时数据流、当前值和信号趋势。", canvas)
        copy.setObjectName("cockpitDisconnectedCopy")
        copy.setAlignment(Qt.AlignCenter)
        copy.setWordWrap(True)
        canvas_layout.addWidget(copy)

        action = QLabel("使用上方工具栏「连接 ECU」", canvas)
        action.setObjectName("cockpitDisconnectedAction")
        action.setAlignment(Qt.AlignCenter)
        canvas_layout.addWidget(action)

        canvas_layout.addStretch(1)
        return canvas

    def set_placeholder_copy(self, *, title: str, body: str, action: str) -> None:
        """Replace the zero-card placeholder copy."""
        canvas = self._disconnected_canvas
        canvas.findChild(QLabel, "cockpitDisconnectedTitle").setText(title)
        canvas.findChild(QLabel, "cockpitDisconnectedCopy").setText(body)
        canvas.findChild(QLabel, "cockpitDisconnectedAction").setText(action)

    def set_monitor_summary(self, text: str | None) -> None:
        """显示/隐藏「已选 N · 实时显示 P」计数条（spec §G6）。"""
        if text:
            self._summary_bar.setText(text)
            self._summary_bar.setVisible(True)
        else:
            self._summary_bar.setVisible(False)

    def set_pinning_enabled(self, enabled: bool) -> None:
        """启用卡片右键 pin 菜单（采集页开、回放页保持关闭）。"""
        self._pinning_enabled = bool(enabled)
        for card in self._card_cache.values():
            self._install_card_menu(card)

    def _install_card_menu(self, card: LiveSignalCard) -> None:
        if not self._pinning_enabled or bool(card.property("pinMenuInstalled")):
            return
        card.setProperty("pinMenuInstalled", True)
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda pos, c=card: self._build_card_menu(c).exec_(c.mapToGlobal(pos))
        )

    def _build_card_menu(self, card: LiveSignalCard) -> QMenu:
        menu = apply_rounded_menu_chrome(QMenu(card))
        unpin = menu.addAction("取消固定实时显示")
        unpin.triggered.connect(
            lambda _checked=False, name=card.name: self.unpin_requested.emit(name)
        )
        reset = menu.addAction("重置固定（默认前 5）")
        reset.triggered.connect(
            lambda _checked=False: self.pins_reset_requested.emit()
        )
        return menu

    def set_signals(self, signals: list[tuple[str, str, str | None]]) -> None:
        """Replace the cards with a new ``(name, unit, raster)`` list.

        Cards retain their buffer if the name still exists in the new
        list — this lets the live stream survive a transient filter
        edit without dropping the last 30 s.

        Spec §F: raw bus time-channels (``t [n:m]``) are silently
        dropped from the auto-cards seed. The filter lives here at the
        grid boundary; capture-core still accepts these names if a user
        re-adds them through the signal selector.
        """
        # Spec §F: filter at the grid boundary, not per-card.
        self._all_signals = [
            (name, unit, raster)
            for (name, unit, raster) in signals
            if not _TIME_CHANNEL_RE.match(name)
        ]
        if self._focused_channel not in {
            name for name, _unit, _raster in self._all_signals
        }:
            self._focused_channel = None
        self._render_signals()

    def focus_channel(self, name: str) -> None:
        """Show one enlarged live card in the center pane."""
        if name not in {n for n, _unit, _raster in self._all_signals}:
            return
        self._focused_channel = name
        self._render_signals()

    def clear_focus(self) -> None:
        """Return from focused-card view to the full live-card overview."""
        self._focused_channel = None
        self._render_signals()

    @property
    def focused_channel(self) -> str | None:
        return self._focused_channel

    def _visible_signals(self) -> list[tuple[str, str, str | None]]:
        if self._focused_channel is None:
            return list(self._all_signals)
        return [
            (name, unit, raster)
            for (name, unit, raster) in self._all_signals
            if name == self._focused_channel
        ]

    def _sync_focus_bar(self) -> None:
        if self._focused_channel is None:
            self._focus_label.setText("")
            self._focus_shell.setVisible(False)
            return
        self._focus_label.setText(f"聚焦查看 · {self._focused_channel}")
        self._focus_shell.setVisible(True)

    def _render_signals(self) -> None:
        signals = self._visible_signals()
        self._sync_focus_bar()
        existing = self._card_cache
        self._cards = {}
        # Clear layout (placeholder + previous cards + final stretch).
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        if not signals:
            # Zero-card path: KEEP the trailing stretch so the
            # disconnected-canvas placeholder does not stretch vertically
            # (Spec §B + responsive-pane-containers lesson).
            self._layout.addWidget(self._disconnected_canvas)
            self._layout.addStretch(1)
            return

        for idx, (name, unit, raster) in enumerate(signals):
            card = existing.get(name)
            if card is None:
                card = LiveSignalCard(name, unit=unit, raster=raster, card_index=idx)
                card.activated.connect(self.focus_channel)
                self._card_cache[name] = card
            else:
                card.update_metadata(unit=unit, raster=raster)
                card.set_visual_index(idx)
            self._cards[name] = card
            self._install_card_menu(card)
            self._layout.addWidget(card)
        # Spec §B: at least one card present — drop the trailing
        # stretch so vertical viewport space flows into the cards
        # themselves (Expanding/Expanding) rather than into dead slack
        # at the bottom of the scroll body.

    def push_sample(self, channel: str, timestamp_s: float, value: float) -> None:
        card = self._cards.get(channel) or self._card_cache.get(channel)
        if card is None:
            return
        card.push_sample(timestamp_s, value)

    def set_recording(self, recording: bool, rec_start_ts: float | None = None) -> None:
        for card in self._card_cache.values():
            card.set_recording(recording, rec_start_ts)

    def refresh_all(self) -> None:
        for card in self._card_cache.values():
            card.refresh()

    def reset_buffers(self) -> None:
        """Clear every card's sparkline buffer."""
        for card in self._card_cache.values():
            card.reset_buffer()

    @property
    def cards(self) -> dict[str, LiveSignalCard]:
        return dict(self._cards)
