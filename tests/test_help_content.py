import json
import re
from pathlib import Path

HELP = Path(__file__).resolve().parents[1] / "mf4_analyzer" / "help"
MANUAL = HELP / "TraceLab-使用说明.html"
PUBLISHED_GUIDE = (
    Path(__file__).resolve().parents[1]
    / "docs" / "analyzer" / "user-guide" / "user-guide.html"
)


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
    assert d["meta"]["version"] == "v7.9.2"
    assert d["meta"]["updated"] == "2026-08-03"
    assert d["meta"]["docVersion"] == "2.8"
    assert [c["v"] for c in d["changelog"]][:3] == ["v7.9.2", "v7.9.1", "v7.9"]


def test_v792_changelog_covers_batch_panel_fit_and_action_ranking():
    current = _deck_data()["changelog"][0]
    assert current["v"] == "v7.9.2"
    description = " ".join(current["items"])
    for keyword in (
        "批处理", "自适应", "预览", "TraceLab7.9.2", "TraceLabAnalyzer7.9.2",
    ):
        assert keyword in description


def test_v791_changelog_covers_batch_custom_x_and_package_labels():
    current = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9.1"
    )
    description = " ".join(current["items"])
    for keyword in ("批处理", "自定义横轴", "TraceLab7.9.1", "TraceLabAnalyzer7.9.1"):
        assert keyword in description


def test_v79_changelog_covers_interaction_budget_fixes():
    v79 = next(entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9")
    description = " ".join(v79["items"])
    for keyword in ("Ctrl / Shift", "100 ms", "TraceLab7.9", "TraceLabAnalyzer7.9"):
        assert keyword in description


def test_v78_changelog_covers_channel_configuration_system():
    v78 = next(entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.8")
    description = " ".join(v78["items"])
    for keyword in ("通道配置", "保存更改", "JSON 导入 / 导出", "保留、替换或跳过"):
        assert keyword in description


def test_manual_has_filter_slide():
    d = _deck_data()
    assert any(s.get("id") == "filter" for s in d["slides"])


def test_manual_covers_new_features():
    html = MANUAL.read_text(encoding="utf-8")
    for kw in ["滤波", "低通", "高通", "带通", "带阻", ".blf", "DBC",
               "GPU", "框选", "A 计权", "采样率", ".wwt", ".zfd", ".mat",
               "TraceLabAnalyzer7.9.2"]:
        assert kw in html, f"manual missing: {kw}"


def test_manual_uses_current_real_ui_assets():
    html = MANUAL.read_text(encoding="utf-8")
    for name in ("time-panel.png", "imports-panel.png"):
        asset = HELP / "assets" / name
        assert asset.exists() and asset.stat().st_size > 100_000
        assert f"assets/{name}" in html


def test_published_guide_tracks_v792_and_real_ui_assets():
    html = PUBLISHED_GUIDE.read_text(encoding="utf-8")
    assert "TraceLab v7.9.2" in html
    for name in ("WWT", "ZFD", "MAT", "time-panel.png", "imports-panel.png"):
        assert name in html
    assert "matplotlib" not in html


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
        assert "TraceLab v7.9.2" in text
        for kw in kws:
            assert kw in text, f"{fname} missing: {kw}"
