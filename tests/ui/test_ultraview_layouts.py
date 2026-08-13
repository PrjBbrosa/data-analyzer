"""UltraView layout geometry (UV-A06)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mf4_analyzer.ui.chart_stack.ultraview.layouts import (
    BASE_BOARD_SIZE,
    BOARD_PADDING,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    MIN_CARD_CHROME_HEIGHT,
    MIN_CARD_CONTENT_SIZE,
    SLOT_GUTTER,
    content_rect,
    logical_board_size,
    slot_rects,
)
from mf4_analyzer.ui.ultraview_state import (
    EQUAL_LAYOUTS,
    HERO_LAYOUTS,
    LAYOUT_SLOTS,
    clamp_ratio,
)

LAYOUTS_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
    / "layouts.py"
)


def _inside(rect, content) -> bool:
    x, y, w, h = rect
    cx, cy, cw, ch = content
    return x >= cx and y >= cy and x + w <= cx + cw and y + h <= cy + ch and w >= 0 and h >= 0


def _overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _axis_gap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x_overlap = ax < bx + bw and bx < ax + aw
    y_overlap = ay < by + bh and by < ay + ah
    if x_overlap and y_overlap:
        return 0
    if x_overlap:
        if ay + ah <= by:
            return by - (ay + ah)
        return ay - (by + bh)
    if y_overlap:
        if ax + aw <= bx:
            return bx - (ax + aw)
        return ax - (bx + bw)
    return None


def _assert_pack(layout_id: str, content, ratio: float) -> dict:
    rects = slot_rects(layout_id, content, ratio)
    expected = LAYOUT_SLOTS[layout_id]
    assert tuple(rects) == expected
    assert len(set(rects)) == len(expected)
    for rect in rects.values():
        assert _inside(rect, content)
        assert rect[2] > 0 and rect[3] > 0
    ids = list(rects)
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            assert not _overlap(rects[left], rects[right]), (left, right, rects)
            gap = _axis_gap(rects[left], rects[right])
            if gap is not None:
                assert gap >= SLOT_GUTTER, (left, right, gap, rects)
    return rects


def test_layouts_module_is_qt_free():
    tree = ast.parse(LAYOUTS_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module.split(".")[0])
    assert "PyQt5" not in imported
    assert "sip" not in imported
    source = LAYOUTS_PATH.read_text(encoding="utf-8")
    assert "QWidget" not in source
    assert "MainWindow" not in source


def test_all_templates_fit_without_overlap_at_supported_sizes():
    sizes = [
        content_rect(BASE_BOARD_SIZE),
        content_rect((1280, 800)),
        (12, 8, 640, 360),
    ]
    for layout_id in LAYOUT_SLOTS:
        for content in sizes:
            _assert_pack(layout_id, content, 0.67)


@pytest.mark.parametrize("ratio", [0.40, 0.67, 0.80])
def test_hero_ratio_changes_primary_share(ratio):
    content = content_rect(BASE_BOARD_SIZE)
    clamped = clamp_ratio(ratio)
    left = slot_rects("hero_left_4", content, ratio)
    top = slot_rects("hero_top_4", content, ratio)
    _assert_pack("hero_left_4", content, ratio)
    _assert_pack("hero_top_4", content, ratio)
    usable_w = content[2] - SLOT_GUTTER
    usable_h = content[3] - SLOT_GUTTER
    assert left["primary"][2] == pytest.approx(round(usable_w * clamped), abs=1)
    assert top["primary"][3] == pytest.approx(round(usable_h * clamped), abs=1)
    assert left["primary"][2] > left["aux_0"][2] or ratio <= 0.5
    if ratio >= 0.67:
        assert left["primary"][2] > left["aux_0"][2]
        assert top["primary"][3] > top["aux_0"][3]


def test_equal_templates_ignore_ratio():
    content = content_rect(BASE_BOARD_SIZE)
    for layout_id in EQUAL_LAYOUTS:
        a = slot_rects(layout_id, content, 0.40)
        b = slot_rects(layout_id, content, 0.80)
        assert a == b
        _assert_pack(layout_id, content, 0.40)


def test_hero_ratio_is_clamped():
    content = content_rect(BASE_BOARD_SIZE)
    assert slot_rects("hero_left_4", content, 0.10) == slot_rects(
        "hero_left_4", content, 0.40
    )
    assert slot_rects("hero_left_4", content, 1.50) == slot_rects(
        "hero_left_4", content, 0.80
    )


def test_gutter_is_ultraview_owned_constant():
    assert SLOT_GUTTER == 12
    assert BOARD_PADDING == 16
    assert BASE_BOARD_SIZE == (1600, 900)
    content = content_rect()
    assert content == (16, 16, 1568, 868)


def test_card_chrome_minimum_is_not_scaled_with_board_size():
    assert CARD_HEADER_HEIGHT + CARD_FOOTER_HEIGHT == MIN_CARD_CHROME_HEIGHT
    assert MIN_CARD_CHROME_HEIGHT >= 48
    assert HERO_LAYOUTS


@pytest.mark.parametrize(
    ("layout_id", "expected"),
    [
        ("grid_3x3", (3, 3)),
        ("grid_4x3", (3, 4)),
    ],
)
def test_p1_large_grid_templates_have_row_major_geometry(layout_id, expected):
    rows, cols = expected
    slots = LAYOUT_SLOTS[layout_id]
    assert len(slots) == rows * cols
    assert slots[0] == "r0c0"
    assert slots[-1] == f"r{rows - 1}c{cols - 1}"
    _assert_pack(layout_id, content_rect(BASE_BOARD_SIZE), 0.67)


def test_p1_large_grids_keep_readable_logical_canvas_at_small_viewport():
    viewport = (800, 560)
    nine = logical_board_size("grid_3x3", viewport)
    twelve = logical_board_size("grid_4x3", viewport)
    card_w, card_h = MIN_CARD_CONTENT_SIZE
    assert nine[0] == 2 * BOARD_PADDING + 3 * card_w + 2 * SLOT_GUTTER
    assert twelve[0] == 2 * BOARD_PADDING + 4 * card_w + 3 * SLOT_GUTTER
    assert nine[1] == twelve[1] == 2 * BOARD_PADDING + 3 * card_h + 2 * SLOT_GUTTER
    assert nine[0] > viewport[0]
    assert twelve[0] > viewport[0]
    assert logical_board_size("grid_3x2", viewport) == viewport
