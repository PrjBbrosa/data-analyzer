"""Qt-free copy mapping and throttle for UltraView elastic-canvas feedback."""
from __future__ import annotations

import ast
from pathlib import Path

from mf4_analyzer.ui.chart_stack.ultraview.feedback import (
    ACCESSIBLE,
    CONTINUE_EXPAND,
    COPY,
    FEEDBACK_NO_LEGAL_LAYOUT,
    FEEDBACK_OUT_OF_GRID,
    FEEDBACK_REARRANGED,
    HARD_REJECT_THROTTLE_S,
    MEMBERSHIP_CAP,
    NO_LEGAL_LAYOUT,
    PLACED_CAP_TO_TRAY,
    PLACED_CAP_STILL_UNPLACED,
    REARRANGED,
    REMOVE_ACTION,
    REMOVED_FROM_BOARD,
    SAFETY_BOUNDS,
    SEARCH_CAP,
    FeedbackThrottle,
    accessible_for_key,
    format_displace_preview,
    format_export_too_large,
    format_rearranged,
    key_for_reason,
    text_for_key,
    text_for_reason,
)
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import LayoutRejectReason

FEEDBACK_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
    / "feedback.py"
)


def test_feedback_module_is_qt_free():
    tree = ast.parse(FEEDBACK_PATH.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(
        name == "PyQt5" or name.startswith("PyQt5.") for name in imported
    )


def test_stable_copy_strings():
    assert COPY[CONTINUE_EXPAND] == "继续拖动可扩展画布"
    assert COPY[SAFETY_BOUNDS] == "已到画布安全边界 · 整理卡片或新建 Board"
    assert COPY[REARRANGED] == "已重排 {n} 张 · Ctrl/Cmd+Z 撤销"
    assert COPY[NO_LEGAL_LAYOUT] == (
        "附近没有可用空间 · 继续向空白处拖动或整理 Board"
    )
    assert COPY[PLACED_CAP_TO_TRAY] == (
        "画布已放置 24 张，已移到未放置区 · 打开"
    )
    assert COPY[PLACED_CAP_STILL_UNPLACED] == (
        "画布已放置 24 张，仍在未放置区 · 打开"
    )
    assert COPY[MEMBERSHIP_CAP] == (
        "本 Board 已达 200 个 View · 新建 Board 或先移除"
    )
    assert COPY[REMOVED_FROM_BOARD] == (
        "已从当前 Board 移除 · 源 View 保留 · Ctrl/Cmd+Z 撤销"
    )
    assert COPY[REMOVE_ACTION] == "从当前 Board 移除（不删除源 View）"
    assert format_rearranged(3) == "已重排 3 张 · Ctrl/Cmd+Z 撤销"
    assert format_displace_preview(1) == "让位 1 张"
    assert format_displace_preview(3) == "让位 3 张"
    assert format_export_too_large(9000, 12000) == (
        "9000×12000 超出导出上限 · 改用 1× 或整理卡片"
    )


def test_out_of_bounds_is_safety_bounds_not_twelve_col_wall():
    assert key_for_reason(LayoutRejectReason.OUT_OF_BOUNDS) == SAFETY_BOUNDS
    assert text_for_reason(LayoutRejectReason.OUT_OF_BOUNDS) == COPY[SAFETY_BOUNDS]
    assert FEEDBACK_OUT_OF_GRID == COPY[SAFETY_BOUNDS]
    assert "不能移出网格" not in COPY.values()
    assert "12 列" not in COPY[SAFETY_BOUNDS]


def test_every_layout_reject_reason_maps_to_copy():
    expected = {
        LayoutRejectReason.OUT_OF_BOUNDS: SAFETY_BOUNDS,
        LayoutRejectReason.NO_LEGAL_LAYOUT: NO_LEGAL_LAYOUT,
        LayoutRejectReason.SPAN_INVARIANT: NO_LEGAL_LAYOUT,
        LayoutRejectReason.INVALID_INPUT: NO_LEGAL_LAYOUT,
        LayoutRejectReason.SEARCH_CAP: SEARCH_CAP,
    }
    assert set(LayoutRejectReason) == set(expected)
    for reason, key in expected.items():
        assert key_for_reason(reason) == key
        assert text_for_reason(reason) == COPY[key]
        assert accessible_for_key(key) == ACCESSIBLE[key]
    assert text_for_reason(None) == COPY[NO_LEGAL_LAYOUT]
    assert FEEDBACK_NO_LEGAL_LAYOUT == COPY[NO_LEGAL_LAYOUT]
    assert FEEDBACK_REARRANGED == COPY[REARRANGED]


def test_hard_rejects_explain_why_and_next_step():
    for key in (SAFETY_BOUNDS, NO_LEGAL_LAYOUT, MEMBERSHIP_CAP, SEARCH_CAP):
        text = text_for_key(key)
        assert "·" in text, key
        assert text == accessible_for_key(key)


def test_edge_hint_once_per_gesture():
    gate = FeedbackThrottle()
    assert gate.allow_continue_expand("g1") is True
    assert gate.allow_continue_expand("g1") is False
    assert gate.allow_continue_expand("g2") is True
    gate.end_gesture("g1")
    assert gate.allow_continue_expand("g1") is True
    assert gate.allow(
        CONTINUE_EXPAND, now=0.0, gesture_id="g2"
    ) is False


def test_hard_reject_same_key_suppressed_within_one_second():
    gate = FeedbackThrottle()
    assert HARD_REJECT_THROTTLE_S == 1.0
    assert gate.allow_hard_reject(SAFETY_BOUNDS, 10.0) is True
    assert gate.allow_hard_reject(SAFETY_BOUNDS, 10.9) is False
    assert gate.allow_hard_reject(NO_LEGAL_LAYOUT, 10.9) is True
    assert gate.allow_hard_reject(SAFETY_BOUNDS, 11.0) is True


def test_successful_commit_always_allowed_immediately():
    gate = FeedbackThrottle()
    assert gate.allow_hard_reject(NO_LEGAL_LAYOUT, 1.0) is True
    assert gate.allow_success(REARRANGED) is True
    assert gate.allow(REARRANGED, now=1.0) is True
    assert gate.allow(REMOVED_FROM_BOARD, now=1.1) is True
    assert gate.allow(PLACED_CAP_TO_TRAY, now=1.1) is True
    assert gate.allow(NO_LEGAL_LAYOUT, now=1.5) is False
