"""Structural + consistency tests for the 操作速查 (Quick-Reference) catalog.

The catalog (``mf4_analyzer.ui.quickref``) is pure data — frozen dataclasses
the panel renders. These tests guard:

* all expected groups are present in order and none is empty;
* every keyboard chip resolves through ``hints.shortcut_tooltip`` (the single
  source of truth for shortcut strings) — a missing key must surface, never
  silently blank;
* the 五个分析模式 group has exactly 5 rows, each carrying a one-line ``sub``;
* the 共轴 row shipped 2026-06-27 — it carries no ``soon`` badge and no catalog
  row stays ``soon`` (matching ``coaxis.* ship="now"``);
* the 阶次 mode purpose names EPS 电机转速 (this user analyzes EPS — order base
  is motor speed, not engine).
"""
from mf4_analyzer.ui import quickref
from mf4_analyzer.ui import hints


EXPECTED_TITLES = [
    "开始 · 文件",
    "五个分析模式",
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


def test_modes_group_has_five_rows_each_with_sub_and_frf_explanation():
    modes = next(g for g in quickref.QUICKREF if g.title == "五个分析模式")
    assert [row.desc for row in modes.rows] == ["时域", "频谱", "时频", "阶次", "频响"]
    for row in modes.rows:
        assert row.sub, f"mode row {row.desc!r} missing a one-line sub/purpose"
    frf = next(row for row in modes.rows if row.desc == "频响")
    assert "FRF" in frf.sub and "系统辨识" in frf.sub
    assert "取时域范围" in frf.sub and "一次性" in frf.sub
    # The group spans two columns in the rendered grid.
    assert modes.wide is True


def test_quickref_explains_the_pane_local_frequency_cursor_modes():
    group = next(g for g in quickref.QUICKREF if g.title == "游标")
    row = next(row for row in group.rows if row.desc == "频谱 / 频响游标")
    assert "关 / 单 / 双" in row.sub
    assert "Δf" in row.sub
    assert "ΔY" in row.sub
    assert "pane" in row.sub and "默认关闭" in row.sub


def test_order_mode_names_eps_motor_speed():
    modes = next(g for g in quickref.QUICKREF if g.title == "五个分析模式")
    order_row = next(r for r in modes.rows if r.desc == "阶次")
    assert "EPS" in order_row.sub
    assert "电机转速" in order_row.sub


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
    assert "FFT-时间" in slice_export.sub and "阶次" in slice_export.sub
    open_folder = next(r for r in group.rows if "完成后" in r.desc)
    assert "输出目录" in open_folder.desc
    assert "记" in open_folder.sub and "下次" in open_folder.sub
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
    pickers — is scoped to the focused View's attached files, so the catalog
    has to name both the drag and the auto-attach toggle that governs it.
    """
    attach = _row_by_desc("把文件加入当前 View")
    assert "拖" in attach.gesture
    auto = _row_by_desc("自动加入开关")
    assert "开" in auto.sub and "关" in auto.sub


def test_catalog_states_the_analysis_picker_scope():
    """A short signal list is silent by design; the catalog must explain it."""
    row = _row_by_desc("分析信号的可选范围")
    assert "当前 View" in row.sub
    for section in ("FFT", "阶次"):
        assert section in row.sub


def test_catalog_says_how_to_read_a_truncated_channel_name():
    row = _row_by_desc("看通道全名")
    assert "悬停" in row.gesture
