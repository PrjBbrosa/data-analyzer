"""Structural + consistency tests for the 操作速查 (Quick-Reference) catalog.

The catalog (``mf4_analyzer.ui.quickref``) is pure data — frozen dataclasses
the panel renders. These tests guard:

* all 11 expected groups are present and none is empty;
* every keyboard chip resolves through ``hints.shortcut_tooltip`` (the single
  source of truth for shortcut strings) — a missing key must surface, never
  silently blank;
* the 四个分析模式 group has exactly 4 rows, each carrying a one-line ``sub``;
* exactly the 共轴 row is flagged ``soon`` (matching ``coaxis.* ship="later"``);
* the 阶次 mode purpose names EPS 电机转速 (this user analyzes EPS — order base
  is motor speed, not engine).
"""
from mf4_analyzer.ui import quickref
from mf4_analyzer.ui import hints


EXPECTED_TITLES = [
    "开始 · 文件",
    "四个分析模式",
    "图表手势",
    "快捷键",
    "通道树（左侧）",
    "游标",
    "谱图（FFT-时间 / 阶次）",
    "标注",
    "预设",
    "导出 · 复制",
    "右键菜单",
]


def _all_rows():
    for group in quickref.QUICKREF:
        for row in group.rows:
            yield group, row


def test_eleven_groups_exact_titles():
    titles = [g.title for g in quickref.QUICKREF]
    assert len(titles) == 11, titles
    assert titles == EXPECTED_TITLES


def test_no_empty_groups():
    for group in quickref.QUICKREF:
        assert group.rows, f"group {group.title!r} has no rows"
        for row in group.rows:
            # Every row must carry a primary description.
            assert row.desc, f"row in {group.title!r} has empty desc"


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


def test_modes_group_has_four_rows_each_with_sub():
    modes = next(g for g in quickref.QUICKREF if g.title == "四个分析模式")
    assert len(modes.rows) == 4, [r.desc for r in modes.rows]
    for row in modes.rows:
        assert row.sub, f"mode row {row.desc!r} missing a one-line sub/purpose"
    # The group spans two columns in the rendered grid.
    assert modes.wide is True


def test_order_mode_names_eps_motor_speed():
    modes = next(g for g in quickref.QUICKREF if g.title == "四个分析模式")
    order_row = next(r for r in modes.rows if r.desc == "阶次")
    assert "EPS" in order_row.sub
    assert "电机转速" in order_row.sub


def test_exactly_coaxis_row_is_soon():
    soon_rows = [(g.title, r.desc) for g, r in _all_rows() if r.soon]
    assert len(soon_rows) == 1, soon_rows
    title, desc = soon_rows[0]
    assert "共轴" in desc, soon_rows


def test_coaxis_soon_matches_ship_later_hint():
    """The catalog's only 'soon' item must correspond to a ship='later' hint."""
    later_ids = {h.id for h in hints.all_hints() if h.ship == "later"}
    # The coaxis hints are the staged shared-axis feature.
    assert any(hid.startswith("coaxis.") for hid in later_ids)
    soon_rows = [r for _g, r in _all_rows() if r.soon]
    assert soon_rows and "共轴" in soon_rows[0].desc


def test_dataclasses_are_frozen():
    import dataclasses
    import pytest
    row = quickref.QUICKREF[0].rows[0]
    assert dataclasses.is_dataclass(row)
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.desc = "mutated"
