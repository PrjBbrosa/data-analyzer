"""Live-card visual contract tests for Cockpit center pane."""

from __future__ import annotations

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


def test_idle_refresh_trims_to_last_60s_of_stream_time(qtbot):
    """The idle trim floor comes from the newest buffered stream timestamp."""
    card = LiveSignalCard("MotSpd")
    qtbot.addWidget(card)
    for t in (0.0, 30.0, 70.0, 100.0, 119.0):
        card.push_sample(t, 1.0)
    card.refresh()
    kept = [ts for ts, _ in card._spark._buffer]
    assert kept == [70.0, 100.0, 119.0]


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
