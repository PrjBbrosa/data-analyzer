"""Live-card visual contract tests for Cockpit center pane."""

from __future__ import annotations

import math

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QScrollArea, QWidget

from mf4_analyzer.acquisition_ui.widgets.live_cards import (
    LiveCardGrid,
    LiveSignalCard,
)


def _label(parent: QWidget, object_name: str) -> QLabel:
    label = parent.findChild(QLabel, object_name)
    assert label is not None, f"missing {object_name}"
    return label


def test_disconnected_canvas_replaces_plain_placeholder(qapp):
    grid = LiveCardGrid()

    canvas = grid.findChild(QWidget, "cockpitDisconnectedCanvas")
    assert canvas is not None
    assert grid.findChild(QLabel, "centerPanePlaceholder") is None

    texts = [label.text() for label in canvas.findChildren(QLabel)]
    assert any("未连接 ECU" in text for text in texts)
    assert any("数据流" in text and "连接" in text for text in texts)


def test_live_card_visual_parts_exist(qapp):
    grid = LiveCardGrid()
    grid.set_signals([("EngSpdAvg", "rpm", "event_10ms")])

    card = grid.cards["EngSpdAvg"]
    swatch = _label(card, "liveCardSwatch")
    assert swatch.property("traceColor") == "#2563eb"
    assert _label(card, "liveCardName").text() == "EngSpdAvg"
    assert _label(card, "liveCardUnit").text() == "rpm"
    # Spec §C: raster pill strips the ``event_`` prefix for display and
    # exposes the full raster name via the pill's tooltip.
    raster_pill = _label(card, "liveCardRaster")
    assert raster_pill.text() == "10 ms"
    assert raster_pill.toolTip() == "event_10ms"

    stats = _label(card, "liveCardStats")
    # Spec §C: the "since <window>" suffix moves from the visible text
    # to the stats label's tooltip. The visible text must NOT carry it.
    assert "since 60s" not in stats.text()
    assert "since 60s" in stats.toolTip()

    value = _label(card, "liveCardValue")
    assert value.alignment() & Qt.AlignRight

    card.set_recording(True, rec_start_ts=0.0)
    # After flipping into recording state, the same tooltip relocation
    # applies and the swatch tints solid red per Spec §A.
    assert "since rec start" not in stats.text()
    assert "since rec start" in stats.toolTip()
    assert "#dc2626" in swatch.styleSheet().lower()


def test_live_card_grid_scrolls_when_many_channels(qapp):
    """Spec §S1: cards overflow vertically → QScrollArea kicks in.

    20 cards at ~110 px each would naively produce a ~2000 px tall
    widget. With the scroll wrapper, the outer ``LiveCardGrid`` reports
    a size hint bounded by the viewport (not the inner content), and
    the vertical scrollbar must surface once the inner content exceeds
    the viewport.
    """
    grid = LiveCardGrid()
    signals = [(f"Sig{i}", "V", "event_10ms") for i in range(20)]
    grid.set_signals(signals)
    grid.resize(400, 400)
    grid.show()
    qapp.processEvents()

    scroll = grid.findChild(QScrollArea)
    assert scroll is not None, "LiveCardGrid must wrap its cards in a QScrollArea"
    assert scroll.verticalScrollBar().isVisible() is True
    assert grid.sizeHint().height() <= 500


def test_time_channels_are_filtered_from_auto_cards(qapp):
    """Spec §F: raw bus time-channels (``t [n:m]``) never seed a card.

    Normal channel names — including ``engine_speed`` here — must still
    produce cards. The filter lives at the grid boundary so the same
    call site is the only decision point. Capture-core is not involved.
    """
    grid = LiveCardGrid()
    grid.set_signals(
        [
            ("engine_speed", "rpm", "event_10ms"),
            ("t [0:100]", "s", None),
            ("t[1:50]", "s", None),
            ("t [3:0]", "s", None),
        ]
    )

    assert "engine_speed" in grid.cards
    assert "t [0:100]" not in grid.cards
    assert "t[1:50]" not in grid.cards
    assert "t [3:0]" not in grid.cards
    # No surprise side-effects: only the normal channel survived.
    assert list(grid.cards.keys()) == ["engine_speed"]


def test_sparkline_height_grows_with_card(qapp):
    """Spec §B: a single card on a tall grid renders a sparkline ≥ 72 px.

    With Expanding/Expanding size policy on both the card and the
    sparkline AND the trailing ``addStretch(1)`` removed for the
    one-card path, the curve must claim at least its minimum height
    after one layout pass.
    """
    grid = LiveCardGrid()
    grid.set_signals([("EngSpdAvg", "rpm", "event_10ms")])
    # Give the grid enough vertical room that the sparkline floor is
    # not under-budget from a clipped viewport.
    grid.resize(400, 400)
    grid.show()
    qapp.processEvents()
    # A second pass after activation lets the layout settle to its
    # final geometry under offscreen Qt.
    grid.layout().activate()
    qapp.processEvents()

    card = grid.cards["EngSpdAvg"]
    sparkline = card.findChild(QWidget, "liveCardSparkline")
    assert sparkline is not None
    # Floor is 72 px per Spec §B; with Expanding on a 400 px grid the
    # actual height should be considerably larger, but we assert the
    # contract floor only so the test stays robust across layouts.
    assert sparkline.height() >= 72, (
        f"sparkline height={sparkline.height()} below 72px floor"
    )


def test_live_card_colors_are_deterministic(qapp):
    grid = LiveCardGrid()
    signals = [
        ("Sig0", "V", "event_10ms"),
        ("Sig1", "V", "event_20ms"),
        ("Sig2", "V", "event_50ms"),
        ("Sig3", "V", "event_100ms"),
        ("Sig4", "V", "event_200ms"),
        ("Sig5", "V", "event_10ms"),
    ]
    grid.set_signals(signals)

    expected = ["#2563eb", "#059669", "#ea580c", "#0891b2", "#64748b", "#2563eb"]
    for (name, _unit, _raster), color in zip(signals, expected, strict=True):
        card = grid.cards[name]
        swatch = _label(card, "liveCardSwatch")
        sparkline = card.findChild(QWidget, "liveCardSparkline")
        assert swatch.property("traceColor") == color
        assert color in swatch.styleSheet()
        assert card.property("traceColor") == color
        assert sparkline is not None
        assert sparkline.property("traceColor") == color


def test_idle_refresh_keeps_stream_time_samples(qtbot):
    """Stream-time samples must survive refresh (spec 2026-07-07 F1)."""
    card = LiveSignalCard("MotSpd", unit="rpm", raster="event_10ms")
    qtbot.addWidget(card)
    for i in range(100):
        card.push_sample(i * 0.01, float(i))
    card.refresh()
    assert card._spark.sample_count == 100
    assert "max 99.00" in card._stats_label.text()


def test_narrow_live_card_header_keeps_current_value_visible(qtbot):
    """At the 960 px tour width, cards prefer the current value over stats."""
    card = LiveSignalCard(
        "Rte_ActRet_mActiveReturnMotorTorq4Check_xds16",
        unit="Nm",
        raster="event_100ms",
    )
    qtbot.addWidget(card)
    for i in range(120):
        card.push_sample(i * 0.5, 1234.0 + i)
    card.refresh()

    card.resize(300, 140)
    card.show()
    card.layout().activate()
    qtbot.wait(0)

    stats = _label(card, "liveCardStats")
    value = _label(card, "liveCardValue")
    assert stats.isVisible() is False
    assert value.geometry().right() <= card.contentsRect().right()


def test_narrow_card_keeps_identity_and_value(qtbot):
    """Spec 2026-07-08 G1: stats yield first; name elides but stays visible."""
    card = LiveSignalCard(
        "Rte_StrWhlTrqSnsrCalib_StrWhlTrqRawFiltered",
        unit="Nm",
        raster="event_1ms",
    )
    qtbot.addWidget(card)
    card.resize(360, 120)
    card.show()
    card.layout().activate()
    qtbot.waitExposed(card)

    assert card._stats_label.isHidden()
    shown = card._name_label.visible_text()
    assert "…" in shown
    assert shown.startswith("Rte_")
    assert not card._value_label.isHidden()
    card.resize(600, 120)
    card.layout().activate()
    qtbot.wait(0)
    assert not card._stats_label.isHidden()


def test_card_name_tooltip_is_full_name(qtbot):
    card = LiveSignalCard("MotSpd", unit="rpm")
    qtbot.addWidget(card)
    assert card._name_label.toolTip() == "MotSpd"
    assert card._name_label.full_text() == "MotSpd"


def test_idle_refresh_trims_to_last_30s_of_stream_time(qtbot):
    """The idle trim floor comes from the newest buffered stream timestamp.

    Unified 30s live window (2026-07-10 spec §A2): the floor is
    ``newest - _LIVE_WINDOW_S`` (30s), derived from the buffer's own
    stream time, never a wall clock.
    """
    card = LiveSignalCard("MotSpd")
    qtbot.addWidget(card)
    for t in (0.0, 70.0, 95.0, 100.0, 119.0):
        card.push_sample(t, 1.0)
    card.refresh()
    kept = [ts for ts, _ in card._spark._buffer]
    assert kept == [95.0, 100.0, 119.0]  # newest 119 − 30 = 89 floor


def test_recording_trims_to_live_window(qtbot):
    """Recording also trims to the honest 30s live window (A-2).

    Old behaviour let recording run with ``t_min=None`` (no trim) while a
    4096-cap deque only held ~4s at 1ms, so the buffer both under-trimmed
    the intent AND lied about the window. Now both idle and recording
    trim to ``newest - _LIVE_WINDOW_S`` and the raw deque is sized to
    hold a full honest 30s at 1ms.
    """
    card = LiveSignalCard("MotSpd", unit="rpm", raster="event_1ms")
    qtbot.addWidget(card)
    card.set_recording(True, rec_start_ts=0.0)
    for i in range(40000):  # 40s @ 1ms
        card.push_sample(i / 1000.0, float(i))
    card.refresh()
    buf = card._spark._buffer
    span = buf[-1][0] - buf[0][0]
    assert span <= 30.0 + 1e-6  # 录制态也裁到 30s（旧行为 t_min=None 不裁）
    assert span >= 29.0  # 且确实持有近 30s（buffer 容量足够）


def test_set_recording_true_resets_buffer(qtbot):
    """Recording starts a cumulative window by clearing the card buffer."""
    card = LiveSignalCard("MotSpd")
    qtbot.addWidget(card)
    card.push_sample(1.0, 5.0)
    card.set_recording(True, 0.0)
    assert card._spark.sample_count == 0
    card.push_sample(0.1, 7.0)
    card.set_recording(False)
    assert card._spark.sample_count == 1


def test_grid_reset_buffers(qtbot):
    grid = LiveCardGrid()
    qtbot.addWidget(grid)
    grid.set_signals([("A", "", None), ("B", "", None)])
    grid.push_sample("A", 0.0, 1.0)
    grid.push_sample("B", 0.0, 2.0)
    grid.reset_buffers()
    assert all(card._spark.sample_count == 0 for card in grid.cards.values())


def test_single_click_focuses_card_and_back_restores_all(qtbot):
    """Clicking a live card enlarges it by focusing the center pane."""
    grid = LiveCardGrid()
    qtbot.addWidget(grid)
    grid.set_signals(
        [
            ("MotSpd", "rpm", "event_1ms"),
            ("StrWhlTrq", "Nm", "event_1ms"),
            ("BattVolt", "V", "event_10ms"),
        ]
    )
    grid.resize(600, 420)
    grid.show()
    qtbot.waitExposed(grid)

    card = grid.cards["StrWhlTrq"]
    qtbot.mouseClick(card, Qt.LeftButton)

    assert grid.focused_channel == "StrWhlTrq"
    assert list(grid.cards) == ["StrWhlTrq"]
    focus_bar = grid.findChild(QLabel, "liveFocusBar")
    assert focus_bar is not None
    assert focus_bar.isVisible()
    assert "聚焦查看" in focus_bar.text()
    assert "StrWhlTrq" in focus_bar.text()

    back = grid.findChild(QWidget, "liveFocusBackButton")
    assert back is not None
    qtbot.mouseClick(back, Qt.LeftButton)

    assert grid.focused_channel is None
    assert sorted(grid.cards) == ["BattVolt", "MotSpd", "StrWhlTrq"]


# ----------------------------------------------------------------------
# Task A-3: continuous polyline + envelope render with time-based x.
# The sparkline painter positions x by STREAM timestamp mapped onto
# ``[t_anchor - 30s, t_anchor]`` (never a bin index), draws a connected
# ``QPainterPath`` at low density and a min/max envelope + last-value
# line at high density, and breaks the path at genuine gaps / non-finite
# samples (never bridging them — cf. arraytoqpath lesson).
# ----------------------------------------------------------------------


def test_low_density_builds_connected_polyline():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _build_polyline

    now = 10.0
    # 60 samples spanning the WHOLE 30s window (both edges included).
    samples = [(now - 30 + i * (30 / 59), float(i)) for i in range(60)]
    pts = _build_polyline(
        samples, w=600, h=64, window=30.0, t_anchor=now, ymin=0, ymax=59
    )
    assert len(pts) == 60  # a connected polyline, not isolated dots
    xs = [p.x() for p in pts]
    assert xs == sorted(xs)  # x is monotonic in time
    # Fills the full width: newest sample hugs the right edge, oldest is
    # inside the left boundary.
    assert xs[-1] > 590 and xs[0] < 10


def test_x_is_time_proportional_not_index():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _build_polyline

    now = 10.0
    # Only the most recent 5s of the 30s window carries data.
    samples = [(now - 5.0, 0.0), (now - 2.5, 1.0), (now, 2.0)]
    pts = _build_polyline(
        samples, w=600, h=64, window=30.0, t_anchor=now, ymin=0, ymax=2
    )
    # The earliest sample sits in the right 5/30 of the width (x > 500),
    # NOT at the left edge as it would with index-based positioning.
    assert pts[0].x() > 480
    assert pts[-1].x() > 590  # newest still hugs the right edge


def test_build_polyline_y_is_value_proportional():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _build_polyline

    now = 10.0
    samples = [(now, 0.0), (now, 10.0)]
    pts = _build_polyline(
        samples, w=600, h=100, window=30.0, t_anchor=now, ymin=0.0, ymax=10.0
    )
    # y = h - (v-ymin)/(ymax-ymin)*h : v=0 -> bottom, v=10 -> top.
    assert abs(pts[0].y() - 100.0) < 1e-6
    assert abs(pts[1].y() - 0.0) < 1e-6


def test_envelope_covers_only_recent_window_fraction():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _build_envelope

    now = 10.0
    n = 2000  # dense (> 2*w) but only 5s of coverage
    samples = [
        (now - 5.0 + i * (5.0 / (n - 1)), math.sin(i * 0.01)) for i in range(n)
    ]
    band, line = _build_envelope(
        samples, w=600, h=64, window=30.0, t_anchor=now, ymin=-1.0, ymax=1.0
    )
    xs = [p.x() for p in line if p is not None]
    assert xs, "envelope must emit a last-value line"
    # 5/30 of the window is the right ~100 px; nothing on the left 70%.
    assert min(xs) > 600 * 0.7
    assert max(xs) <= 600 + 1e-6
    # The band is likewise anchored to the right, not stretched [first,last].
    assert band.boundingRect().left() > 600 * 0.7


def test_envelope_line_connects_last_value_not_minmax():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _build_envelope

    now = 10.0
    # All samples land in the single right-most column; min 0, max 10,
    # last 5. The connecting line must follow the LAST value (5), never
    # the min/max — connecting min/max fabricates a full-height zigzag.
    vals = [0.0, 10.0, 3.0, 10.0, 5.0]
    samples = [(now - 0.04 + i * 0.01, v) for i, v in enumerate(vals)]
    band, line = _build_envelope(
        samples, w=600, h=100, window=30.0, t_anchor=now, ymin=0.0, ymax=10.0
    )
    line_pts = [p for p in line if p is not None]
    assert len(line_pts) == 1
    # py(5) with ymin=0 ymax=10 h=100 -> 100 - 5/10*100 = 50.
    assert abs(line_pts[0].y() - 50.0) < 1e-6
    # The band still spans the FULL min..max (0..10 -> y 100..0).
    br = band.boundingRect()
    assert br.top() < 1.0 and br.bottom() > 99.0


def test_split_runs_breaks_on_time_gap():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _split_runs

    a = [(i * 0.1, float(i)) for i in range(10)]  # 0.0 .. 0.9
    b = [(6.0 + i * 0.1, float(i)) for i in range(10)]  # gap 6.0-0.9 = 5.1 s
    runs = _split_runs(a + b, raster_period=0.1)
    assert len(runs) == 2
    assert len(runs[0]) == 10 and len(runs[1]) == 10


def test_split_runs_breaks_on_nonfinite_value():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _split_runs

    # A NaN in the middle must BREAK the path (arraytoqpath lesson:
    # connect-finite bridging fabricates a spurious segment).
    samples = [
        (0.0, 1.0),
        (0.1, 2.0),
        (0.2, math.nan),
        (0.3, 3.0),
        (0.4, 4.0),
    ]
    runs = _split_runs(samples, raster_period=0.1)
    assert len(runs) == 2
    assert [v for _, v in runs[0]] == [1.0, 2.0]
    assert [v for _, v in runs[1]] == [3.0, 4.0]


def test_split_runs_fallback_median_without_raster():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _split_runs

    # No raster metadata: fall back to > 3x median interval. Median of
    # {0.1, 0.1, 0.7} is 0.1 -> threshold 0.3; the 0.7 gap breaks.
    samples = [(0.0, 0.0), (0.1, 1.0), (0.2, 2.0), (0.9, 3.0)]
    runs = _split_runs(samples, raster_period=None)
    assert len(runs) == 2


def test_paint_polyline_survives_low_density(qtbot):
    """End-to-end: a live card with few samples paints without error and
    goes through the low-density polyline branch (n <= 2*w)."""
    card = LiveSignalCard("MotSpd", unit="rpm", raster="event_1ms")
    qtbot.addWidget(card)
    card.resize(400, 120)
    card.show()
    qtbot.waitExposed(card)
    for i in range(30):
        card.push_sample(i * 0.5, float(i))
    card.refresh()
    card._spark.repaint()  # exercise the real paintEvent
    assert card._spark.sample_count == 30


# ----------------------------------------------------------------------
# Task A-4: compact y-ticks + honest 30s window label + no-data/stale.
# ``_spark_scale`` maps a raw value range onto a nice-tick DISPLAY range
# that keeps a readable, value-aware minimum span so a constant signal
# does NOT collapse the axis; ``_sample_state`` classifies arrival cadence
# off an injectable monotonic clock (x still uses STREAM time).
# ----------------------------------------------------------------------


def test_constant_signal_keeps_min_span():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _spark_scale

    lo, hi, ticks = _spark_scale(54.30, 54.34)
    # Near-constant signal keeps a readable span (value-aware min span =
    # max(1.0, |center| * 0.02)) instead of collapsing toward ~0.
    assert (hi - lo) >= 1.0
    assert len(ticks) >= 3


def test_scale_uses_nice_ticks():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _spark_scale

    lo, hi, ticks = _spark_scale(0.0, 2360.0)
    assert hi >= 2360.0 and lo <= 0.0  # data covered + padding
    assert all(t == round(t, 6) for t in ticks)  # round grid


def test_scale_recovers_from_nonfinite_bounds():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _spark_scale

    lo, hi, ticks = _spark_scale(math.nan, math.inf)
    assert math.isfinite(lo) and math.isfinite(hi) and hi > lo
    assert len(ticks) >= 3


def test_sample_state_recovers_after_new_arrival():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _sample_state

    assert _sample_state(None, now=10.0, raster_period=0.001) == "no-data"
    assert _sample_state(8.0, now=10.0, raster_period=0.001) == "stale"
    assert _sample_state(10.0, now=10.0, raster_period=0.001) == "live"


def test_sample_state_threshold_floors_at_one_second():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _sample_state

    # 3×raster (3×0.2 = 0.6s) is below the 1s floor, so 0.8s is still live.
    assert _sample_state(9.2, now=10.0, raster_period=0.2) == "live"
    # A slow 1s raster: 3× = 3s threshold, so 2s idle is still live but 4s stale.
    assert _sample_state(8.0, now=10.0, raster_period=1.0) == "live"
    assert _sample_state(6.0, now=10.0, raster_period=1.0) == "stale"


def test_card_sample_state_uses_injected_clock(qtbot):
    clock = [0.0]
    card = LiveSignalCard("MotSpd", raster="event_1ms", clock=lambda: clock[0])
    qtbot.addWidget(card)
    assert card.sample_state() == "no-data"  # never received a sample
    clock[0] = 5.0
    card.push_sample(0.0, 1.0)  # arrival recorded at monotonic 5.0
    assert card.sample_state() == "live"
    clock[0] = 7.0  # 2s since arrival > max(1s, 3×1ms)
    assert card.sample_state() == "stale"
    clock[0] = 7.5
    card.push_sample(0.001, 2.0)  # a fresh arrival
    assert card.sample_state() == "live"  # recovers immediately


def test_window_label_reflects_recording(qtbot):
    card = LiveSignalCard("MotSpd", raster="event_1ms")
    qtbot.addWidget(card)
    assert card._spark.window_label() == "最近 30s"
    card.set_recording(True, rec_start_ts=0.0)
    assert card._spark.window_label() == "最近 30s（录制中）"


def test_narrow_card_hides_y_tick_text(qtbot):
    card = LiveSignalCard("MotSpd", unit="rpm", raster="event_1ms")
    qtbot.addWidget(card)
    card.resize(360, 120)
    card.show()
    card.layout().activate()
    qtbot.waitExposed(card)
    # Below _STATS_COLLAPSE_MIN_CARD_W the y-tick gutter yields to the
    # signal name + current value (same width threshold as the stats row).
    assert card._spark.y_ticks_visible() is False
    card.resize(600, 140)
    card.layout().activate()
    qtbot.wait(0)
    assert card._spark.y_ticks_visible() is True


def test_paint_with_y_ticks_survives(qtbot):
    """A wide card paints y-tick labels + window label without error."""
    card = LiveSignalCard("MotSpd", unit="rpm", raster="event_1ms")
    qtbot.addWidget(card)
    card.resize(600, 160)
    card.show()
    qtbot.waitExposed(card)
    for i in range(50):
        card.push_sample(i * 0.5, 54.3)  # constant signal must not collapse
    card.refresh()
    card._spark.repaint()  # exercise the real paintEvent + y-tick text
    assert card._spark.y_ticks_visible() is True
    assert card._spark.sample_count == 50
