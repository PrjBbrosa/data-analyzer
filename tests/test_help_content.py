import json
import re
from pathlib import Path

HELP = Path(__file__).resolve().parents[1] / "mf4_analyzer" / "help"
MANUAL = HELP / "TraceLab-使用说明.html"
FRF_GUIDE = HELP / "frf-guide.html"
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
    assert d["meta"]["version"] == "v7.9.9"
    assert d["meta"]["updated"] == "2026-08-12"
    assert d["meta"]["docVersion"] == "3.0"
    assert [c["v"] for c in d["changelog"]][:5] == [
        "v7.9.9", "v7.9.8", "v7.9.7", "v7.9.6", "v7.9.5",
    ]


def test_v799_changelog_covers_view_all_tick_density_and_wwt():
    entry = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9.9"
    )
    description = " ".join(entry["items"])
    for keyword in ("查看全部", "密", "WinWert", "进度", "操作速查"):
        assert keyword in description


def test_v798_changelog_covers_source_isolation_and_follow_menu():
    entry = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9.8"
    )
    description = " ".join(entry["items"])
    for keyword in (
        "文件范围", "文件范围跟随", "新建 View", "填充空 View", "分析 View", "拖拽导入",
    ):
        assert keyword in description


def test_v797_changelog_covers_control_surface_and_frf_markup():
    current = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9.7"
    )
    description = " ".join(current["items"])
    for keyword in (
        "当前 View", "Δf / ΔY", "真实 Hz", "标注", "使用选定时间范围",
    ):
        assert keyword in description


def test_v796_changelog_covers_frf_system_identification_and_batch_output():
    current = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9.6"
    )
    description = " ".join(current["items"])
    for keyword in (
        "频响（FRF）系统辨识", "H1 / H2", "相干度", "批处理", "CSV、PNG 和 manifest",
    ):
        assert keyword in description


def test_v795_changelog_covers_hdf_view_scope_and_ink_budget():
    current = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v7.9.5"
    )
    description = " ".join(current["items"])
    for keyword in ("HDF", "完整通道名", "当前 View", "墨水量", "7px"):
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


def test_changelog_renders_v798_and_v797_as_separate_recent_pages():
    html = MANUAL.read_text(encoding="utf-8")
    assert "const RECENT_CHANGELOG_COUNT=2;" in html
    assert "recent.forEach((index,pageIndex)=>{" in html
    assert "indices.filter(index=>index>=RECENT_CHANGELOG_COUNT)" in html


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


def test_published_guide_tracks_v799_and_real_ui_assets():
    html = PUBLISHED_GUIDE.read_text(encoding="utf-8")
    assert "TraceLab v7.9.9" in html
    for name in ("WWT", "ZFD", "MAT", "time-panel.png", "imports-panel.png"):
        assert name in html
    assert "matplotlib" not in html


def test_help_has_no_developer_jargon():
    banned = ["pyqtgraph", "matplotlib", "scipy", "QWidget", "PyQt5"]
    for f in HELP.glob("*.html"):
        text = f.read_text(encoding="utf-8").lower()
        for b in banned:
            # FRF names the user-visible NumPy-only/SciPy parity boundary; every
            # other help page keeps the existing no-developer-jargon ratchet.
            if f == FRF_GUIDE and b.lower() == "scipy":
                continue
            assert b.lower() not in text, f"{f.name} contains dev jargon: {b}"


def test_panel_guides_cover_new_topics():
    checks = {
        "time-domain-guide.html": ["滤波", "框选", "Shift"],
        "fft-guide.html": ["A 计权"],
        "ffttime-guide.html": ["A 计权"],
        "order-analysis-guide.html": ["加权", "采样率"],
    }
    for fname, kws in checks.items():
        text = (HELP / fname).read_text(encoding="utf-8")
        assert "TraceLab v7.9.9" in text
        for kw in kws:
            assert kw in text, f"{fname} missing: {kw}"


def test_frf_guide_is_mapped_and_covers_frozen_frf_contract():
    from mf4_analyzer.help import guide_path

    assert guide_path("frf") == FRF_GUIDE
    assert FRF_GUIDE.is_file()
    text = FRF_GUIDE.read_text(encoding="utf-8")
    for keyword in (
        "H1", "H2", "coherence", "窗长", "重叠", "df", "段数",
        "20log10", "1 ratio-unit", "output/input", "严格同时间轴",
        "NumPy-only", "SciPy", "custom-X", "common",
        "available_per_source", "frequency_hz", "pxy_imag",
        "默认关闭", "2–9", "双游标", "Δf", "保留，不做自动补偿",
    ):
        assert keyword in text, f"FRF guide missing: {keyword}"
    assert "先复用同一签名" in text
    assert "没有时才新建" in text
    assert "使用选定时间范围" in text
    assert "取时域范围" not in text
    # D8: jitter path is auto-rebuild, not a hard block label.
    assert '>自动重建</div>' in text
    assert "数据被阻断" not in text


def test_ultraview_guide_is_mapped_and_covers_readonly_board_contract():
    from mf4_analyzer.help import guide_path

    path = HELP / "ultraview-guide.html"
    assert guide_path("ultraview") == path
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "TraceLab v7.9.9" in text
    for keyword in (
        "只读", "不计算", "View 库", "托盘", "加入总览",
        "打开原 View", "PNG", "缺", "孤儿", ".tlproj",
        "五个分析工作区", "不是第六种算法", "2×2", "3×2",
        "Esc", "演示", "UltraView（总览）", "View 栏最右侧 UltraView",
        "Board", "自由网格", "12 列", "24 张", "Option+Shift", "整理布局",
        "minimap", "直接拖卡片", "框选", "替换环",
        "Ctrl+滚轮", "适应", "25%", "双击",
    ):
        assert keyword in text, f"UltraView guide missing: {keyword}"
    for banned in (
        "PDF", "SVG", "sidecar", "live card", "后台补图",
        "工具栏「总览」", "顶栏「总览」", "顶部「总览」",
        "Alt+拖", "Option 拖动位置",
    ):
        assert banned not in text, f"UltraView guide leaked P1 copy: {banned}"


def test_main_manual_and_published_guide_name_the_five_modes_and_frf():
    for guide in (MANUAL, PUBLISHED_GUIDE):
        text = guide.read_text(encoding="utf-8")
        for label in ("时域", "频谱", "时频", "频响", "阶次", "FRF"):
            assert label in text, f"{guide.name} missing: {label}"


def test_published_guide_removes_hidden_controls_and_explains_frf_range():
    text = PUBLISHED_GUIDE.read_text(encoding="utf-8")
    assert "去均值" not in text
    assert "取时域范围" not in text
    assert "使用选定时间范围" in text


def test_ultraview_p3_surfaces_drop_alt_drag_copy():
    """UV-P3-A15: product hints / quickref / help must not keep Alt+拖."""
    root = Path(__file__).resolve().parents[1]
    surfaces = [
        root / "mf4_analyzer" / "ui" / "hints.py",
        root / "mf4_analyzer" / "ui" / "quickref.py",
        HELP / "ultraview-guide.html",
    ]
    banned = ("Alt+拖", "Option 拖动位置", "Option 拖动、")
    for path in surfaces:
        text = path.read_text(encoding="utf-8")
        for phrase in banned:
            assert phrase not in text, f"{path.name} still has {phrase!r}"
