"""Live-card visual contract tests for Cockpit center pane."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QWidget

from mf4_analyzer.acquisition_ui.widgets.live_cards import LiveCardGrid


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
    assert _label(card, "liveCardSwatch").property("traceColor") == "#2563eb"
    assert _label(card, "liveCardName").text() == "EngSpdAvg"
    assert _label(card, "liveCardUnit").text() == "rpm"
    assert _label(card, "liveCardRaster").text() == "event_10ms"
    assert "since 60s" in _label(card, "liveCardStats").text()

    value = _label(card, "liveCardValue")
    assert value.alignment() & Qt.AlignRight

    card.set_recording(True, rec_start_ts=0.0)
    assert "since rec start" in _label(card, "liveCardStats").text()


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
