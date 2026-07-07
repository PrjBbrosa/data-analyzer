"""Center-pane live signal cards.

Spec §Center Pane: each selected signal card shows sparkline, current
value, unit, raster pill, and compact stats (``μ / σ / max``). Stats
window follows §State Machine ``stats window``:

- ``ConnectedIdle``: rolling 60 s window. Label reads ``since 60s``.
- ``Recording``: cumulative window from recording start. Label reads
  ``since rec start``.

Each card also carries its own ``REC OFF`` / red-dot indicator. The
toolbar's global REC indicator is driven by the same ``RecHealth.state``
field via ``MainWindow``; the per-card indicator MUST not disagree.

Sparkline rendering uses :func:`live_downsampler.downsample_minmax`
exclusively.
"""

from __future__ import annotations

import math
import re
from collections import deque

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.acquisition_ui.widgets.live_downsampler import (
    Bin,
    downsample_minmax,
)


# Spec §State Machine `stats window`.
STATS_WINDOW_LABEL_IDLE = "since 60s"
STATS_WINDOW_LABEL_RECORDING = "since rec start"

# Rolling-idle window length. Spec §State Machine ``stats window``:
#   "``ConnectedIdle``: rolling 60 s window of received samples."
#
# This is a stats-window definition, NOT a threshold band, so it is
# not exposed via ``acquisition_capture.thresholds`` (which is reserved
# for green/yellow/red band edges per Spec §Threshold Contract). The
# value is fixed by the state-machine contract, so keeping it here as
# a named local constant keeps the spec citation next to the use site
# without leaking a UI-only constant into the capture-core module.
_IDLE_WINDOW_S = 60.0

# Sparkline target width in logical pixels — fits the right pane card
# allotment when the window is 1280 px wide. The painter respects the
# widget's actual width via ``self.width()`` so this is just the deque
# capacity to bound memory.
_SPARK_MAX_POINTS = 4096

_CARD_TRACE_COLORS = (
    "#2563eb",
    "#059669",
    "#ea580c",
    "#0891b2",
    "#64748b",
)

# Below this card width the right-side current value is the more important
# live signal; stats are restored when the card has breathing room again.
_COMPACT_STATS_HIDE_WIDTH = 360

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
        # Spec §B: floor the sparkline at 72px and let it absorb free
        # vertical space so cards grow the curve when N decreases.
        self.setMinimumHeight(72)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_trace_color(self, color: QColor) -> None:
        self._color = QColor(color)
        self.setProperty("traceColor", self._color.name())
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

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        painter.setPen(QPen(QColor("#e5e7eb"), 0.8))
        for fraction in (0.25, 0.5, 0.75):
            y = rect.top() + rect.height() * fraction
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for fraction in (0.25, 0.5, 0.75):
            x = rect.left() + rect.width() * fraction
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
        # Card backdrop already paints; we draw only the line.
        target = max(8, rect.width())
        bins = downsample_minmax(list(self._buffer), target)
        if not bins or all(b is None for b in bins):
            painter.end()
            return

        # Y-scale across the visible bins.
        ymin = math.inf
        ymax = -math.inf
        for b in bins:
            if b is None:
                continue
            lo, hi = b
            if lo < ymin:
                ymin = lo
            if hi > ymax:
                ymax = hi
        if not math.isfinite(ymin) or not math.isfinite(ymax) or ymax == ymin:
            ymax = ymin + 1.0

        h = rect.height()
        w = rect.width()
        pen = QPen(self._color, 1.4)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        # Plot one vertical segment per bucket; gaps don't draw.
        for idx, b in enumerate(bins):
            if b is None:
                continue
            x = (idx / max(1, len(bins) - 1)) * w
            lo, hi = b
            y_lo = h - ((lo - ymin) / (ymax - ymin)) * h
            y_hi = h - ((hi - ymin) / (ymax - ymin)) * h
            if abs(y_lo - y_hi) < 0.6:
                # Single-sample bucket: draw a dot via short vertical.
                painter.drawPoint(QPointF(x, y_lo))
            else:
                painter.drawLine(QPointF(x, y_hi), QPointF(x, y_lo))
        painter.end()


class LiveSignalCard(QFrame):
    """One card per selected signal.

    Public API:

    - :meth:`push_sample` — append ``(timestamp_s, value)``.
    - :meth:`set_recording` — switch stats label / scope.
    - :meth:`refresh` — recompute stats label + sparkline.
    """

    def __init__(
        self,
        name: str,
        unit: str = "",
        raster: str | None = None,
        card_index: int = 0,
        parent: QWidget | None = None,
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

        self._name_label = QLabel(self._name, self)
        self._name_label.setObjectName("liveCardName")
        self._name_label.setMinimumWidth(0)
        self._name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
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

    def reset_buffer(self) -> None:
        self._spark.reset()

    def _sync_header_compactness(self) -> None:
        compact = 0 < self.width() < _COMPACT_STATS_HIDE_WIDTH
        self._stats_label.setText(self._stats_full_text)
        self._stats_label.setVisible(not compact)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override.
        super().resizeEvent(event)
        self._sync_header_compactness()

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
        """Recompute stats label and trim the idle rolling window.

        Time-base invariant (2026-07-07 spec F1): the trim floor is
        derived from the buffer's own newest sample (stream time),
        never from a wall clock. Recording mode never trims: the
        cumulative-since-rec-start window is realised by clearing the
        buffer in :meth:`set_recording`.
        """
        if self._recording:
            label = STATS_WINDOW_LABEL_RECORDING
            t_min: float | None = None
        else:
            label = STATS_WINDOW_LABEL_IDLE
            buf = self._spark._buffer  # noqa: SLF001 - sibling widget.
            t_min = (buf[-1][0] - _IDLE_WINDOW_S) if buf else None
        self._spark.trim_to_window(t_min)
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(300)
        # Outer shell: thin zero-margin QVBoxLayout whose sole child is
        # the scroll area. The cards/placeholder layout lives on an
        # inner host widget inside the scroll viewport so vertical
        # overflow is solved at the container, not by shrinking cards
        # (Spec §S1.2, lessons: responsive-pane-containers +
        # inspector-content-max-width-and-tinted-card-bleed).
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

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

    def set_signals(self, signals: list[tuple[str, str, str | None]]) -> None:
        """Replace the cards with a new ``(name, unit, raster)`` list.

        Cards retain their buffer if the name still exists in the new
        list — this lets the live stream survive a transient filter
        edit without dropping the last 60 s.

        Spec §F: raw bus time-channels (``t [n:m]``) are silently
        dropped from the auto-cards seed. The filter lives here at the
        grid boundary; capture-core still accepts these names if a user
        re-adds them through the signal selector.
        """
        # Spec §F: filter at the grid boundary, not per-card.
        signals = [
            (name, unit, raster)
            for (name, unit, raster) in signals
            if not _TIME_CHANNEL_RE.match(name)
        ]

        existing = self._cards
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
            else:
                card.update_metadata(unit=unit, raster=raster)
                card.set_visual_index(idx)
            self._cards[name] = card
            self._layout.addWidget(card)
        # Spec §B: at least one card present — drop the trailing
        # stretch so vertical viewport space flows into the cards
        # themselves (Expanding/Expanding) rather than into dead slack
        # at the bottom of the scroll body.

    def push_sample(self, channel: str, timestamp_s: float, value: float) -> None:
        card = self._cards.get(channel)
        if card is None:
            return
        card.push_sample(timestamp_s, value)

    def set_recording(self, recording: bool, rec_start_ts: float | None = None) -> None:
        for card in self._cards.values():
            card.set_recording(recording, rec_start_ts)

    def refresh_all(self) -> None:
        for card in self._cards.values():
            card.refresh()

    def reset_buffers(self) -> None:
        """Clear every card's sparkline buffer."""
        for card in self._cards.values():
            card.reset_buffer()

    @property
    def cards(self) -> dict[str, LiveSignalCard]:
        return dict(self._cards)
