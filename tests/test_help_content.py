import json
import re
from pathlib import Path

HELP = Path(__file__).resolve().parents[1] / "mf4_analyzer" / "help"
MANUAL = HELP / "TraceLab-使用说明.html"


def _deck_data() -> dict:
    """Extract and parse the deckData JSON block from the main manual."""
    html = MANUAL.read_text(encoding="utf-8")
    m = re.search(
        r'<script type="application/json" id="deckData">(.*?)</script>',
        html, re.S,
    )
    assert m, "deckData block not found"
    return json.loads(m.group(1))


def test_deck_data_valid_and_version_bumped():
    d = _deck_data()
    assert d["meta"]["updated"] == "2026-06-25"
    assert d["meta"]["docVersion"] == "2.1"
    assert "v2.2" in [c["v"] for c in d["changelog"]]


def test_manual_has_filter_slide():
    d = _deck_data()
    assert any(s.get("id") == "filter" for s in d["slides"])


def test_manual_covers_new_features():
    html = MANUAL.read_text(encoding="utf-8")
    for kw in ["滤波", "低通", "高通", "带通", "带阻", ".blf", "DBC",
               "GPU", "框选", "A 计权", "采样率"]:
        assert kw in html, f"manual missing: {kw}"


def test_help_has_no_developer_jargon():
    banned = ["pyqtgraph", "matplotlib", "scipy", "QWidget", "PyQt5"]
    for f in HELP.glob("*.html"):
        text = f.read_text(encoding="utf-8")
        for b in banned:
            assert b not in text, f"{f.name} contains dev jargon: {b}"


def test_panel_guides_cover_new_topics():
    checks = {
        "time-domain-guide.html": ["滤波", "框选", "Shift"],
        "fft-guide.html": ["A 计权"],
        "ffttime-guide.html": ["A 计权"],
        "order-analysis-guide.html": ["加权", "采样率"],
    }
    for fname, kws in checks.items():
        text = (HELP / fname).read_text(encoding="utf-8")
        for kw in kws:
            assert kw in text, f"{fname} missing: {kw}"
