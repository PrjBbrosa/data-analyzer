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
    assert d["meta"]["version"] == "v8.2.2"
    assert d["meta"]["updated"] == "2026-09-05"
    assert d["meta"]["docVersion"] == "3.0"
    assert [c["v"] for c in d["changelog"]][:6] == [
        "v8.2.2", "v8.2.1", "v8.2.0", "v8.1.0", "v8.0.1", "v8.0.0",
    ]
    current_manual, _changelog = MANUAL.read_text(encoding="utf-8").split(
        '  "changelog": [', 1,
    )
    assert "TraceLab v8.2.2" in current_manual
    assert "v8.0.0" not in current_manual.lower()


def test_v820_changelog_covers_stability_closure():
    entry = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v8.2.0"
    )
    description = " ".join(entry["items"])
    for keyword in (
        "WinWert", "公式", "窗口", "每条曲线", "横坐标", "纵坐标",
        "24 个", "原始记录", "当前聚焦的时域 View", "UltraView", "智能排版",
        "紧凑排列", "按原图比例", "适应内容", "保存重开",
    ):
        assert keyword in description


def test_v821_changelog_covers_each_visible_interaction_once():
    entry = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v8.2.1"
    )
    description = " ".join(entry["items"])
    for keyword in (
        "游标显示设置", "View 色标关闭", "标准快捷键", "Esc 分层", "⋯ 常驻",
        "未保存更改", "WWT 初始视图",
    ):
        assert description.count(keyword) == 1, keyword


def test_v800_changelog_covers_ultraview_workspace_and_restore():
    entry = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v8.0.0"
    )
    description = " ".join(entry["items"])
    for keyword in (
        "UltraView", "多个 Board", "12 列自由网格", "minimap", "PNG",
        "不会静默补算", "工程保存", "所有带来源的分析 View", "BLF / ASC",
    ):
        assert keyword in description


def test_v810_changelog_covers_ultraview_authoring_and_persistence():
    entry = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v8.1.0"
    )
    description = " ".join(entry["items"])
    for keyword in (
        "便笺", "文本", "图形", "画笔", "激光笔", "框选", "成组移动",
        "撤销", "重做", "视口", "minimap", "保存", "Windows",
    ):
        assert keyword in description


def test_manual_load_slide_mentions_recent_open_menu():
    data = _deck_data()
    load = next(slide for slide in data["slides"] if slide.get("id") == "load")
    text = json.dumps(load, ensure_ascii=False)
    assert "旁边箭头" in text
    assert "最近打开" in text
    assert "10" in text and "40" in text
    assert "搜索" in text
    preset = next(slide for slide in data["slides"] if slide.get("id") == "preset")
    preset_text = json.dumps(preset, ensure_ascii=False)
    assert "单位" in preset_text
    assert "荐" in preset_text
    assert "不做推荐" in preset_text


def test_manual_splits_detailed_wwt_guidance_from_the_load_slide():
    data = _deck_data()
    load = next(slide for slide in data["slides"] if slide.get("id") == "load")
    wwt = next(slide for slide in data["slides"] if slide.get("id") == "wwt-workflow")
    assert len(" ".join(load["blocks"][0]["right"][0]["paras"])) < 500
    wwt_copy = json.dumps(wwt, ensure_ascii=False)
    for keyword in ("普通时域 View", "查看全部 / Home", "原始记录", "未生成"):
        assert keyword in wwt_copy


def test_manual_uses_user_facing_language_for_current_workflows():
    current_manual, _changelog = MANUAL.read_text(encoding="utf-8").split(
        '  "changelog": [', 1,
    )
    for stale_copy in (
        "连成一条龙",
        "照着选就对，不用懂原理",
        "拖动不卡",
        "common 要求",
        "available_per_source",
    ):
        assert stale_copy not in current_manual
    assert "所有来源共有" in current_manual
    assert "按来源可用" in current_manual


def test_v801_changelog_covers_ultraview_and_time_domain_workflow():
    entry = next(
        entry for entry in _deck_data()["changelog"] if entry["v"] == "v8.0.1"
    )
    description = " ".join(entry["items"])
    for keyword in (
        "自由网格导出", "竖直居中", "抓图比例", "右键拖动", "左键拖动", "框选",
        "拖到绘图区", "X 带", "拖动文件或通道", "分屏", "叠加", "顺序排列",
    ):
        assert keyword in description


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


def test_published_guide_tracks_v821_and_real_ui_assets():
    html = PUBLISHED_GUIDE.read_text(encoding="utf-8")
    assert "TraceLab v8.2.2" in html
    for name in ("WWT", "ZFD", "MAT", "time-panel.png", "imports-panel.png"):
        assert name in html
    assert "matplotlib" not in html


def test_live_time_domain_view_cap_is_24_not_12():
    """Current-product time-domain copy is 24 Views; v7.6 changelog stays 12."""
    current_manual, changelog = MANUAL.read_text(encoding="utf-8").split(
        '  "changelog": [', 1,
    )
    assert "最多新建 24 个 View" in current_manual
    assert "最多新建 12 个 View" not in current_manual
    assert "独立 Board" not in current_manual
    assert "普通时域 View" in current_manual
    assert "原生范围" not in current_manual
    assert "查看全部 / Home 回到当前数据范围" in current_manual
    assert "时域工作区扩容至 <b>12 个 View</b>" in changelog

    time_guide = (HELP / "time-domain-guide.html").read_text(encoding="utf-8")
    assert "最多 24 个" in time_guide
    assert "最多可建 24 个 View" in time_guide
    assert "最多 12 个" not in time_guide
    assert "最多可建 12 个 View" not in time_guide

    published = PUBLISHED_GUIDE.read_text(encoding="utf-8")
    assert "最多 24 个时域 View" in published
    assert "最多 12 个时域 View" not in published
    assert "独立 Board" not in published
    assert "普通时域 View" in published
    assert "查看全部 / Home 回到当前数据范围" in published


def test_wwt_record_tree_copy_matches_left_tree_control_surface():
    """Live help/guide copy follows the left-tree record control surface."""
    current_manual, changelog = MANUAL.read_text(encoding="utf-8").split(
        '  "changelog": [', 1,
    )
    time_guide = (HELP / "time-domain-guide.html").read_text(encoding="utf-8")
    published = PUBLISHED_GUIDE.read_text(encoding="utf-8")
    for text in (current_manual, time_guide, published):
        assert "所属文件下的 WinWert 原始记录" in text
        assert "未生成" in text
        assert "时域 Inspector 列出 WinWert" not in text
        assert "右侧 Inspector 列出" not in text
        assert "RecordCurveList" not in text
        assert "set_record_curves" not in text
    assert "同步消失" in current_manual
    assert "同步消失" in time_guide
    assert "同步消失" in published
    assert "原始辅助线" in time_guide
    assert "不等于整个文件导入失败" in current_manual
    assert "所属文件下的 WinWert 原始记录" not in changelog


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
        "time-domain-guide.html": ["滤波", "框选", "Shift", "原始辅助线", "游标显示设置", "色标", "⋯"],
        "fft-guide.html": ["A 计权", "查看全部", "游标显示设置", "色标", "⋯"],
        "ffttime-guide.html": ["A 计权", "游标显示设置", "色标", "⋯"],
        "order-analysis-guide.html": ["加权", "采样率", "游标显示设置", "色标", "⋯"],
    }
    for fname, kws in checks.items():
        text = (HELP / fname).read_text(encoding="utf-8")
        assert "TraceLab v8.2.2" in text
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
    assert "TraceLab v8.2.2" in text
    for keyword in (
        "只读", "不计算", "View 库", "托盘", "加入总览",
        "打开原 View", "PNG", "缺", "孤儿", ".tlproj",
        "五个分析工作区", "不是第六种算法", "2×2", "3×2",
        "Esc", "演示", "UltraView（总览）", "View 栏最右侧 UltraView",
        "Board", "自由网格", "12 列", "24 张", "Option+Shift", "Ctrl+Shift+Z",
        "minimap", "直接拖卡片", "框选", "替换环",
        "Ctrl+滚轮", "适应", "25%", "300%", "减少留白", "双击",
        "标题卡", "类型标签", "完整 ghost",
        "点行切换", "拖拽排序", "行尾复制",
        "一键更新源",
        "基准网格", "导出标尺", "四向平移", "自动适应", "切换 Board", "适应内容",
        "临时聚焦", "不删除源 View", "200", "Ctrl/Cmd+Z",
        "常驻可关", "当前工程的所有 Board", "保存项目后保留",
        "schema 4", "schema 5", "24 列微格", "智能排版", "紧凑排列", "空白处右击", "右键按住", "左键按住空白框选",
        "锁定", "保存重开不重排", "预览分辨率较低",
        "Stack", "整框", "连接线",
        "V / N / T / S / P", "仍会渲染",
    ):
        assert keyword in text, f"UltraView guide missing: {keyword}"
    for banned in (
        "PDF", "SVG", "sidecar", "live card", "后台补图",
        "工具栏「总览」", "顶栏「总览」", "顶部「总览」",
        "Alt+拖", "Option 拖动位置",
        "隐藏来源条", "约 60%", "约 40% 只留标题", "碰撞会提示",
        "逻辑画布固定", "默认适应视口", "铺满视口", "12 列受控",
        "尚未提供", "Coming Soon",
        "自动排版",
    ):
        assert banned not in text, f"UltraView guide leaked P1 copy: {banned}"


def test_manual_cover_lists_all_analysis_modes_and_quiet_credit():
    html = MANUAL.read_text(encoding="utf-8")
    from mf4_analyzer.app_meta import APP_CREDIT

    assert _deck_data()["meta"]["credit"] == APP_CREDIT
    assert "m.credit ? ` · ${m.credit}` : ''" in html
    for row in (
        ("看波形", "时域"),
        ("看频率成分", "FFT"),
        ("看频率随时间", "时频"),
        ("看输入到输出", "频响"),
        ("看转速相关振动", "阶次"),
        ("实时录数据", "采集"),
    ):
        label, mode = row
        assert f"<span>{label}</span><b>{mode}</b>" in html, f"cover missing {mode}"


def test_main_manual_and_published_guide_name_the_five_modes_and_frf():
    for guide in (MANUAL, PUBLISHED_GUIDE):
        text = guide.read_text(encoding="utf-8")
        for label in ("时域", "频谱", "时频", "频响", "阶次", "FRF"):
            assert label in text, f"{guide.name} missing: {label}"


def test_published_guide_covers_ultraview_four_actions():
    text = PUBLISHED_GUIDE.read_text(encoding="utf-8")
    for keyword in (
        "UltraView", "智能排版", "紧凑排列", "按原图比例", "适应内容",
        "锁定", "解锁", "撤销", "重开不会再自动重排",
    ):
        assert keyword in text, f"published guide missing: {keyword}"
    assert "自动排版" not in text


def test_published_guide_removes_hidden_controls_and_explains_frf_range():
    text = PUBLISHED_GUIDE.read_text(encoding="utf-8")
    assert "去均值" not in text
    assert "取时域范围" not in text
    assert "使用选定时间范围" in text


def test_cheat_sheet_matches_runtime_desktop_shortcuts():
    cheat = next(slide for slide in _deck_data()["slides"] if slide.get("id") == "cheat")
    blob = json.dumps(cheat, ensure_ascii=False)
    for phrase in (
        "Alt+Left",
        "Alt+Right",
        "视角后退",
        "Ctrl/Cmd+Z 保留给编辑撤销",
        "视角后退已改为 Alt+Left",
        "Esc 先清空搜索",
        "有未保存更改时可保存、不保存或取消",
        "Enter / Space",
        "F2",
        "Alt+Up/Down",
    ):
        assert phrase in blob, f"cheat sheet missing {phrase!r}"
    project = next(slide for slide in _deck_data()["slides"] if slide.get("id") == "project")
    project_blob = json.dumps(project, ensure_ascii=False)
    assert "有未保存更改时可保存、不保存或取消" in project_blob
    assert "全局撤销栈" not in project_blob


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
