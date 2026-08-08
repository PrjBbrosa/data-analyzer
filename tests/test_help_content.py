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
    assert d["meta"]["version"] == "v7.9.5"
    assert d["meta"]["updated"] == "2026-08-08"
    assert d["meta"]["docVersion"] == "3.0"
    assert [c["v"] for c in d["changelog"]][:3] == ["v7.9.5", "v7.9.4", "v7.9.3"]


def test_v795_changelog_covers_hdf_view_scope_and_ink_budget():
    current = _deck_data()["changelog"][0]
    assert current["v"] == "v7.9.5"
    description = " ".join(current["items"])
    for keyword in (
        "HDF", "完整通道名", "当前 View", "墨水量", "7px",
    ):
        assert keyword in description


def test_v794_changelog_covers_order_time_grid_and_slice_warnings():
    current = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9.4"
    )
    description = " ".join(current["items"])
    for keyword in (
        "时间轴", "10.000", "切片", "时间分辨率",
    ):
        assert keyword in description


def test_v793_changelog_covers_batch_rpm_pairing_and_slice_highlights():
    current = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9.3"
    )
    description = " ".join(current["items"])
    for keyword in ("批处理", "RPM", "切片"):
        assert keyword in description


def test_v791_changelog_covers_batch_custom_x():
    current = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9.1"
    )
    description = " ".join(current["items"])
    for keyword in ("批处理", "自定义横轴"):
        assert keyword in description


def test_v79_changelog_covers_interaction_budget_fixes():
    v79 = next(entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9")
    description = " ".join(v79["items"])
    for keyword in ("Ctrl / Shift", "100 ms"):
        assert keyword in description


def test_v78_changelog_covers_channel_configuration_system():
    v78 = next(entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.8")
    description = " ".join(v78["items"])
    for keyword in ("通道配置", "保存更改", "JSON 导入 / 导出", "保留、替换或跳过"):
        assert keyword in description


def test_changelog_omits_mechanical_version_and_package_sync_items():
    forbidden = (
        "软件版本更新至",
        "当前版本标识",
        "Windows 完整包与仅分析功能的轻量包默认名称同步",
    )
    for entry in _deck_data()["changelog"]:
        for item in entry["items"]:
            assert not any(text in item for text in forbidden), (
                f"{entry['v']} contains mechanical release metadata: {item}"
            )


def test_changelog_keeps_recent_front_and_packs_history_at_end():
    html = MANUAL.read_text(encoding="utf-8")
    assert "function arrangeChangelogSlides" in html
    assert "function packChangelogHistory" in html
    assert "changelog-page" in html
    assert "changelog-history-page" in html
    assert "mainSlides.concat(historySlides)" in html
    assert "data-release-indices" in html
    safe_area = re.search(
        r"\.slide\.changelog-page \.body\{bottom:(\d+)px;", html
    )
    assert safe_area, "changelog slide bottom safe area is missing"
    assert int(safe_area.group(1)) >= 200


def test_manual_has_filter_slide():
    d = _deck_data()
    assert any(s.get("id") == "filter" for s in d["slides"])


def test_manual_covers_new_features():
    html = MANUAL.read_text(encoding="utf-8")
    for kw in ["滤波", "低通", "高通", "带通", "带阻", ".blf", "DBC",
               "GPU", "框选", "A 计权", "采样率", ".wwt", ".zfd", ".mat"]:
        assert kw in html, f"manual missing: {kw}"


def test_manual_uses_current_real_ui_assets():
    html = MANUAL.read_text(encoding="utf-8")
    for name in ("time-panel.png", "imports-panel.png"):
        asset = HELP / "assets" / name
        assert asset.exists() and asset.stat().st_size > 100_000
        assert f"assets/{name}" in html


def test_published_guide_tracks_v795_and_real_ui_assets():
    html = PUBLISHED_GUIDE.read_text(encoding="utf-8")
    assert "TraceLab v7.9.5" in html
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
        assert "TraceLab v7.9.5" in text
        for kw in kws:
            assert kw in text, f"{fname} missing: {kw}"
