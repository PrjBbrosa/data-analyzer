"""Text contract for Acquisition Cockpit scoped QSS selectors."""

from __future__ import annotations

from pathlib import Path


STYLE_PATH = Path("mf4_analyzer/ui_kit/style.qss")


def _stylesheet() -> str:
    return STYLE_PATH.read_text(encoding="utf-8")


def test_cockpit_visual_selector_contract_is_present():
    qss = _stylesheet()

    required_tokens = [
        "cockpitToolbarBand",
        "cockpitSelector",
        "cockpitModeSegment",
        "cockpitRecIndicator",
        "healthChip",
        "filterChip",
        "cockpitDisconnectedCanvas",
        "liveSignalCard",
        "rightMetricSection",
        "rightVerdictBanner",
    ]

    missing = [token for token in required_tokens if token not in qss]
    assert missing == []


def test_analyzer_toolbar_time_segment_selector_is_preserved():
    qss = _stylesheet()

    assert 'Toolbar QPushButton[segment="time"]' in qss
