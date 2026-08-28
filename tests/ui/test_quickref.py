"""Structural + consistency tests for the 操作速查 (Quick-Reference) catalog.

The catalog (``mf4_analyzer.ui.quickref``) is pure data — frozen dataclasses
the panel renders. These tests guard:

* all expected groups are present in order and none is empty;
* every keyboard chip resolves through ``hints.shortcut_tooltip`` (the single
  source of truth for shortcut strings) — a missing key must surface, never
  silently blank;
* the 五个分析工作区 + 总览 group has 6 rows, each carrying a one-line ``sub``;
* the 共轴 row shipped 2026-06-27 — it carries no ``soon`` badge and no catalog
  row stays ``soon`` (matching ``coaxis.* ship="now"``);
* the 阶次 mode purpose names EPS 电机转速 (this user analyzes EPS — order base
  is motor speed, not engine).
"""
from mf4_analyzer.ui import quickref
from mf4_analyzer.ui import hints


def test_quickref_documents_channel_drop_and_navigator_order():
    gestures = next(g for g in quickref.QUICKREF if g.title == "图表手势")
    join = next(r for r in gestures.rows if r.desc == "拖通道加入当前 View")
    assert "绘图区" in (join.gesture or "")
    xaxis = next(r for r in gestures.rows if r.desc == "拖通道设为横坐标")
    assert "X 带" in (xaxis.gesture or "")
    assert "替换" in (xaxis.sub or "")
    assert "占位" in (xaxis.sub or "") or "跳过" in (xaxis.sub or "")
    tree = next(g for g in quickref.QUICKREF if g.title == "通道树（左侧）")
    order = next(r for r in tree.rows if "顺序" in r.desc)
    assert "通道树文件根节点" in (order.sub or "")
    assert "画布内不能拖行" in (order.sub or "")


EXPECTED_TITLES = [
    "开始 · 文件",
    "五个分析工作区 + 总览",
    "图表手势",
    "快捷键",
    "通道树（左侧）",
    "通道编辑（派生通道）",
    "游标",
    "谱图（FFT-时间 / 阶次）",
    "dB 参考（FFT / FFT-时间 / 阶次）",
    "标注",
    "预设",
    "导出 · 复制",
    "批处理",
    "右键菜单",
    "总览 · Board 与自由网格",
]


def _all_rows():
    for group in quickref.QUICKREF:
        for row in group.rows:
            yield group, row


def test_groups_exact_titles():
    titles = [g.title for g in quickref.QUICKREF]
    assert len(titles) == len(EXPECTED_TITLES), titles
    assert titles == EXPECTED_TITLES


def test_no_empty_groups():
    for group in quickref.QUICKREF:
        assert group.rows, f"group {group.title!r} has no rows"
        for row in group.rows:
            # Every row must carry a primary description.
            assert row.desc, f"row in {group.title!r} has empty desc"


def test_supported_formats_include_v77_imports():
    start = next(g for g in quickref.QUICKREF if g.title == "开始 · 文件")
    formats = next(r for r in start.rows if r.desc == "支持格式")
    for name in ("ASCII", "TDMS", "WWT", "ZFD", "MAT"):
        assert name in formats.sub


def test_every_keyboard_chip_resolves():
    """No keyboard chip may be None / empty.

    Keyboard chips are derived from the shortcut registry via the catalog's
    ``_sc`` helper; if a registry key is renamed/removed the chip must surface
    (blank/None), so this guards catalog<->hints consistency.
    """
    saw_any_keys = False
    for group, row in _all_rows():
        for chip in row.keys:
            saw_any_keys = True
            assert chip, (
                f"empty keyboard chip in {group.title!r} / {row.desc!r}: {row.keys!r}"
            )
    assert saw_any_keys, "no keyboard chips found in the whole catalog"


def test_keyboard_chips_match_shortcut_registry():
    """Spot-check that registry-derived chips equal hints.shortcut_tooltip."""
    assert hints.shortcut_tooltip("home") == "Ctrl+R"
    assert hints.shortcut_tooltip("btn_subplot") == "Ctrl+1"
    assert hints.shortcut_tooltip("btn_overlay") == "Ctrl+2"
    assert hints.shortcut_tooltip("cursor_off") == "Ctrl+3"
    assert hints.shortcut_tooltip("cursor_single") == "Ctrl+4"
    assert hints.shortcut_tooltip("cursor_dual") == "Ctrl+5"
    assert hints.shortcut_tooltip("pan") == "Ctrl+G"
    assert hints.shortcut_tooltip("zoom") == "Ctrl+B"
    # The catalog's helper must reflect those exact strings.
    chips = {chip for _g, row in _all_rows() for chip in row.keys}
    assert "Ctrl+R" in chips
    assert "Ctrl+1" in chips
    assert "Ctrl+3" in chips
    assert "Ctrl+G" in chips
    assert "Ctrl+B" in chips


def test_sc_helper_surfaces_missing_key():
    """A missing registry key must raise, not silently blank a chip."""
    import pytest
    with pytest.raises(KeyError):
        quickref._sc("definitely-not-a-real-shortcut-key")


def test_modes_group_has_five_workspaces_plus_readonly_overview():
    modes = next(g for g in quickref.QUICKREF if g.title == "五个分析工作区 + 总览")
    assert [row.desc for row in modes.rows] == [
        "时域", "频谱", "时频", "阶次", "频响", "总览",
    ]
    for row in modes.rows:
        assert row.sub, f"mode row {row.desc!r} missing a one-line sub/purpose"
    frf = next(row for row in modes.rows if row.desc == "频响")
    assert "FRF" in frf.sub and "系统辨识" in frf.sub
    overview = next(row for row in modes.rows if row.desc == "总览")
    assert "只读" in overview.sub
    assert "不计算" in overview.sub
    assert "独立" in overview.sub
    assert "停手后" in overview.sub
    assert "游标" in overview.sub
    assert "标注" in overview.sub
    assert overview.gesture == "各工作区 View 栏最右侧 UltraView"
    catalog = " ".join(f"{r.desc} {r.sub} {r.gesture}" for _g, r in _all_rows())
    for banned in ("工具栏「总览」", "顶栏「总览」", "顶部「总览」"):
        assert banned not in catalog
    assert modes.note and "不是第六种算法" in modes.note
    assert "第六种算法" not in overview.sub
    assert modes.wide is True


def test_quickref_explains_the_pane_local_frequency_cursor_modes():
    group = next(g for g in quickref.QUICKREF if g.title == "游标")
    row = next(row for row in group.rows if row.desc == "频谱 / 频响游标")
    assert "关 / 单 / 双" in row.sub
    assert "Δf" in row.sub
    assert "ΔY" in row.sub
    assert "pane" in row.sub and "默认关闭" in row.sub


def test_order_mode_names_eps_motor_speed():
    modes = next(g for g in quickref.QUICKREF if g.title == "五个分析工作区 + 总览")
    order_row = next(r for r in modes.rows if r.desc == "阶次")
    assert "EPS" in order_row.sub
    assert "电机转速" in order_row.sub


def test_quickref_context_menu_covers_add_to_overview():
    group = next(g for g in quickref.QUICKREF if g.title == "右键菜单")
    range_row = next(r for r in group.rows if r.desc == "轴范围起止")
    assert "Tab" in (range_row.gesture or "")
    assert "起点" in (range_row.sub or "") and "终点" in (range_row.sub or "")
    tab_row = next(r for r in group.rows if r.desc == "View 标签右键")
    assert "加入总览" in tab_row.sub
    assert "不重新计算" in tab_row.sub
    card_row = next(r for r in group.rows if r.desc == "总览卡片右键")
    assert "替换为" in card_row.sub
    assert "右上角" in card_row.sub
    assert "同步" in card_row.sub


def test_coaxis_row_released_no_soon_badge():
    # 共轴组 shipped 2026-06-27: the 合并为共轴 row drops its 即将 badge, and it
    # was the catalog's only staged item, so no row stays flagged ``soon``.
    coaxis_rows = [(g.title, r) for g, r in _all_rows() if "共轴" in r.desc]
    assert any(r.desc == "合并为共轴比幅值" for _t, r in coaxis_rows), coaxis_rows
    assert all(not r.soon for _t, r in coaxis_rows)
    assert [r.desc for _g, r in _all_rows() if r.soon] == []


def test_no_soon_row_and_no_ship_later_coaxis():
    """Release invariant: a ``soon`` row mirrors a ``ship="later"`` hint. After
    the coaxis release neither side carries coaxis — both are empty."""
    later_ids = {h.id for h in hints.all_hints() if h.ship == "later"}
    assert not any(hid.startswith("coaxis.") for hid in later_ids)
    assert [r.desc for _g, r in _all_rows() if r.soon] == []


def test_quickref_covers_db_reference_badge_and_manage_button():
    """Task 10A / spec A17: the three non-self-evident dB-reference
    interactions (A/M badge meaning, manual-commit-on-manual-edit, the tune/
    manage button) must each have a quickref row, and none is a staged
    ``soon`` item (the feature has landed)."""
    group = next(
        g for g in quickref.QUICKREF
        if "dB" in g.title and "参考" in g.title
    )
    haystack = " ".join(f"{r.desc} {r.sub}" for r in group.rows)
    # A/M 徽标含义 (blue A = auto-follow, amber M = manual lock).
    assert "A" in haystack and "M" in haystack
    assert "自动" in haystack and "手动" in haystack
    # 输入框手输提交即切 Manual.
    assert any("手输" in f"{r.desc}{r.sub}" for r in group.rows)
    # tune 按钮打开默认值管理弹窗.
    assert any(
        "管理" in f"{r.desc}{r.sub}" or "tune" in (r.gesture or "").lower()
        for r in group.rows
    )
    assert all(not r.soon for r in group.rows)


def test_quickref_explains_the_chart_quality_dot():
    """Every chart card (time / FFT / FRF since the view-switch settlement
    batch) shows a quality dot; the quickref must say what its three colors
    mean and that a settled render sharpens AFTER the first frame, so a
    yellow-then-green flash right after a View switch is not read as a bug."""
    group = next(g for g in quickref.QUICKREF if g.title == "图表手势")
    row = next(r for r in group.rows if "质量小圆点" in r.desc)
    sub = row.sub or ""
    for token in ("绿", "黄", "红", "悬停", "先出图再平滑"):
        assert token in sub, sub


def test_quickref_fft_preview_row_matches_overlay_contract():
    group = next(g for g in quickref.QUICKREF if g.title == "图表手势")
    row = next(r for r in group.rows if r.desc == "FFT 时域预览")
    assert "平滚轮" in (row.gesture or "")
    assert "平移" in (row.sub or "")
    assert "设左轴" in (row.sub or "")
    assert "单通道" in (row.sub or "")
    assert "勾选" in (row.sub or "")


def test_quickref_covers_batch_drawer():
    """The batch drawer had no quickref presence at all until the option-A
    picker rewrite (plan 2026-08-02). Guard the entry point plus the three
    interactions that are not self-evident from looking at the panel: the
    collapsed row is a read-only summary you must click to search, selection
    happens inside the popup, and RPM is single-select with a scale factor."""
    group = next(g for g in quickref.QUICKREF if g.title == "批处理")
    haystack = " ".join(f"{r.desc} {r.sub} {r.gesture}" for r in group.rows)
    # Entry point — without it the group is unreachable.
    assert "工具栏「批处理」" in haystack
    # Picker: type-to-filter inside the popup, tick rows to select.
    assert "筛选" in haystack and "勾选" in haystack
    # Bulk actions on the popup footer.
    assert "全选" in haystack and "清空" in haystack
    # Collapsed state is a summary + "+N" badge, not an input.
    assert "+N" in haystack
    # RPM row is single-select and carries the RPM scale factor.
    rpm = next(r for r in group.rows if "RPM" in r.desc)
    assert "单选" in rpm.sub
    # Every row here is mouse/gesture driven; a keyboard chip would have to go
    # through ``_sc`` and belongs in the 快捷键 group instead.
    assert all(not r.keys for r in group.rows), [
        r.desc for r in group.rows if r.keys
    ]
    # Remembered display preferences: say both what is kept and what is not,
    # so nobody expects the signal selection to come back with it.
    memory = next(r for r in group.rows if "记住" in r.desc)
    assert "刻度与字体" in memory.sub
    assert "不记" in memory.sub
    assert memory.gesture == "恢复默认"
    slice_export = next(r for r in group.rows if r.desc == "导出切片")
    assert "最多 4" in slice_export.sub
    assert "中英文" in slice_export.sub
    assert "FFT-时间" in slice_export.sub and "阶次" in slice_export.sub
    open_folder = next(r for r in group.rows if "完成后" in r.desc)
    assert "输出目录" in open_folder.desc
    assert "记" in open_folder.sub and "下次" in open_folder.sub
    run_warnings = next(r for r in group.rows if r.desc == "运行警告")
    assert "结果区" in run_warnings.sub
    assert "该行自己" in run_warnings.sub
    # The picker rewrite has landed — nothing here is a staged capability.
    assert all(not r.soon for r in group.rows)


def test_quickref_covers_batch_frf_pairing_policy_and_outputs():
    group = next(g for g in quickref.QUICKREF if g.title == "批处理")
    haystack = " ".join(f"{r.desc} {r.sub} {r.gesture}" for r in group.rows)
    assert "输入" in haystack and "输出" in haystack and "同一来源" in haystack
    assert "common" in haystack and "available_per_source" in haystack
    for label in ("每对一张", "按来源", "按输入/输出对"):
        assert label in haystack


def test_dataclasses_are_frozen():
    import dataclasses
    import pytest
    row = quickref.QUICKREF[0].rows[0]
    assert dataclasses.is_dataclass(row)
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.desc = "mutated"


def _row_by_desc(desc):
    for _group, row in _all_rows():
        if row.desc == desc:
            return row
    raise AssertionError(f"quickref has no row named {desc!r}")


def test_catalog_covers_getting_a_file_into_a_view():
    """Opening a file is not the same as putting it in a View.

    Everything downstream — plotting, the channel tree, and the analysis signal
    pickers — is scoped to the active section/View's attached files, so the
    catalog has to name both the drag and the follow-link menu that governs
    file-scope intake.
    """
    attach = _row_by_desc("把文件加入当前 View")
    assert "拖" in attach.gesture
    assert "全局" in attach.sub and "当前 View" in attach.sub
    follow = _row_by_desc("文件范围跟随")
    assert "链接" in follow.gesture
    assert "继承" in follow.sub and "填充" in follow.sub


def test_catalog_states_the_analysis_picker_scope():
    """A short signal list is silent by design; the catalog must explain it."""
    row = _row_by_desc("分析信号的可选范围")
    assert "分析 View" in row.sub
    assert "时域 View" in row.sub
    assert "跟随" in row.sub
    for section in ("FFT", "阶次"):
        assert section in row.sub


def test_catalog_states_file_remove_action_is_available_in_every_mode():
    row = _row_by_desc("从当前 View 移除文件")
    assert "显示" in row.gesture and "×" in row.gesture
    for mode in ("时域", "频谱", "时频", "频响", "阶次"):
        assert mode in row.sub


def test_catalog_says_how_to_read_a_truncated_channel_name():
    row = _row_by_desc("看通道全名")
    assert "悬停" in row.gesture


def test_catalog_view_all_frames_plotted_channels_not_longest_file():
    """Inspector「全部」and Home frame plotted ink, not the longest loaded file."""
    row = _row_by_desc("时间范围「全部」")
    assert "已绘" in row.sub
    assert "最长文件" in row.sub or "全局" in row.sub
    assert "勾选" in row.sub or "过滤" in row.sub
    assert "全部" in row.gesture
    home = _row_by_desc("复位视图")
    assert "已绘" in home.sub
    menu = _row_by_desc("图表右键")
    assert "已绘" in menu.sub


def test_catalog_bottom_bar_is_question_mark_quickref():
    """27a479c2: the status hint bar keeps the ? glyph; rotating copy is opt-in."""
    row = _row_by_desc("操作速查")
    assert "?" in row.gesture
    assert "问号" in row.sub
    assert "底部提示" in row.sub
    manual = _row_by_desc("软件说明书")
    assert "状态栏" in manual.gesture
    assert "📖" not in manual.gesture


def test_catalog_channel_editor_create_and_param_help():
    """422cbc87: both forms say「创建通道」; sliding-average window is 样点数."""
    group = next(g for g in quickref.QUICKREF if g.title == "通道编辑（派生通道）")
    haystack = " ".join(f"{r.desc} {r.sub} {r.gesture}" for r in group.rows)
    assert haystack.count("创建通道") >= 2
    assert "窗长" in haystack and "样点" in haystack
    assert "?" in haystack
    time_views = _row_by_desc("时域 View")
    assert "悬停" in time_views.sub and "全名" in time_views.sub


def test_ultraview_quickref_describes_direct_manipulation_not_alt_drag():
    group = next(g for g in quickref.QUICKREF if g.title == "总览 · Board 与自由网格")
    haystack = " ".join(f"{row.desc} {row.sub}" for row in group.rows)
    assert "直接拖动" in haystack
    assert "框选" in haystack
    assert "替换环" in haystack
    assert "画布缩放" in haystack
    assert "适应" in haystack
    assert "25%–300%" in haystack
    assert "当前预览尺度" in haystack
    assert "居中" in haystack
    assert "按原图比例" in haystack
    assert "Option+Shift" in haystack
    assert "ghost" in haystack
    assert "标题卡" in haystack
    assert "minimap" in haystack
    assert "Ctrl+Shift+Z" in haystack
    assert "Ctrl/Cmd+Z" in haystack
    assert "点行切换" in haystack
    assert "拖拽排序" in haystack
    assert "行尾复制" in haystack
    assert "一键更新源" in haystack
    assert "空白右击" in haystack or "画布右键" in haystack or "空白处" in haystack
    assert "自动排版" in haystack
    overview = _row_by_desc("总览")
    assert "当前工程所有 Board" in overview.sub
    assert "保存项目后保留" in overview.sub
    assert "实心按钮" in haystack
    assert "从左侧 View 库添加对比" in haystack
    assert "基准网格" in haystack
    assert "导出标尺" in haystack
    assert "四向" in haystack
    assert "自动适应" in haystack
    assert "切换 Board" in haystack
    assert "适应内容" in haystack
    assert "100%" in haystack
    assert "临时聚焦" in haystack
    assert "不删除源 View" in haystack
    assert "200" in haystack
    assert "⋯" not in haystack
    assert "Alt+拖" not in haystack
    assert "Option 拖动" not in haystack
    assert "碰撞时提示" not in haystack
    assert "逻辑画布固定" not in haystack
    assert "默认适应视口" not in haystack
    assert "铺满视口" not in haystack
    assert "12 列受控" not in haystack


def test_ultraview_quickref_describes_released_authoring_tools():
    group = next(g for g in quickref.QUICKREF if g.title == "总览 · Board 与自由网格")
    haystack = " ".join(f"{row.desc} {row.sub}" for row in group.rows)
    assert "左侧 Select / Sticky" not in haystack
    assert "尚未提供" not in haystack
    assert "Coming Soon" not in haystack
    rows = {row.desc: row for row in group.rows}
    pointer = rows["指针"]
    sticky = rows["便签 Sticky"]
    text = rows["文字 Text"]
    shape = rows["形状 Shape"]
    existing = rows["已有连线与笔画"]
    assert pointer.keys == ("V", "Esc")
    assert "激光笔" in pointer.sub
    assert "整块单击" in pointer.sub
    assert "发光圆点" in pointer.sub
    assert "不选择" not in pointer.sub
    assert sticky.keys == ("N",)
    assert text.keys == ("T",)
    assert shape.keys == ("S",)
    assert "连接线 Connector" not in rows
    assert "画笔 Draw" not in rows
    assert "N / T / S / P" in sticky.sub
    assert "V 或 Esc" in sticky.sub
    assert "Stack" in sticky.sub
    assert "固定连续创建" not in sticky.sub
    assert "图标栏" in text.sub
    assert "固定连续创建" not in text.sub
    assert "矩形" in shape.sub
    assert "连接线" in shape.sub
    assert "P 打开" in shape.sub
    assert "固定连续创建" not in shape.sub
    assert "仍会显示" in existing.sub
    assert "删除" in existing.sub
    assert "尚未提供" not in existing.sub


def test_wwt_winwert_layout_row_covers_views_and_ultraview():
    start = next(g for g in quickref.QUICKREF if g.title == "开始 · 文件")
    row = next(r for r in start.rows if "WinWert" in r.desc)
    joined = f"{row.desc} {row.sub}"
    for token in ("WWT", "WinWert", "View", "UltraView"):
        assert token in joined
    assert "像素级一致" not in joined
    assert "全部公式" not in joined
