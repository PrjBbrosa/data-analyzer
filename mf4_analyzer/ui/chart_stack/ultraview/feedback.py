"""Qt-free UltraView reason → copy mapping and toast throttle helpers.

Widgets, page, and the coordinator must import this module instead of
inventing Chinese strings. ``LayoutRejectReason.OUT_OF_BOUNDS`` is the
safety-bounds wall, not the old 12-column base frame.

This module does not import PyQt5. Dwell timing (400 ms edge hint) and
QTimer stay in page/widgets; callers pass monotonic seconds into the gate.
"""
from __future__ import annotations

from typing import Hashable

from .free_grid import LayoutRejectReason

CONTINUE_EXPAND = "continue_expand"
SAFETY_BOUNDS = "safety_bounds"
REARRANGED = "rearranged"
NO_LEGAL_LAYOUT = "no_legal_layout"
PLACED_CAP_TO_TRAY = "placed_cap_to_tray"
PLACED_CAP_STILL_UNPLACED = "placed_cap_still_unplaced"
MEMBERSHIP_CAP = "membership_cap"
REMOVED_FROM_BOARD = "removed_from_board"
EXPORT_TOO_LARGE = "export_too_large"
SEARCH_CAP = "search_cap"
DISPLACED_OFFSCREEN = "displaced_offscreen"
REMOVE_ACTION = "remove_action"
AUTHOR_LOCKED = "author_locked"

COPY: dict[str, str] = {
    CONTINUE_EXPAND: "继续拖动可扩展画布",
    SAFETY_BOUNDS: "已到画布安全边界 · 整理卡片或新建 Board",
    REARRANGED: "已重排 {n} 张 · Ctrl/Cmd+Z 撤销",
    NO_LEGAL_LAYOUT: "附近没有可用空间 · 继续向空白处拖动或整理 Board",
    PLACED_CAP_TO_TRAY: "画布已放置 24 张，已移到未放置区 · 打开",
    PLACED_CAP_STILL_UNPLACED: "画布已放置 24 张，仍在未放置区 · 打开",
    MEMBERSHIP_CAP: "本 Board 已达 200 个 View · 新建 Board 或先移除",
    REMOVED_FROM_BOARD: "已从当前 Board 移除 · 源 View 保留 · Ctrl/Cmd+Z 撤销",
    EXPORT_TOO_LARGE: "{width}×{height} 超出导出上限 · 改用 1× 或整理卡片",
    SEARCH_CAP: "布局搜索超出预算 · 可先整理 Board 再试",
    DISPLACED_OFFSCREEN: "被让位的卡片已移出可视区 · 四向平移查看",
    REMOVE_ACTION: "从当前 Board 移除（不删除源 View）",
    AUTHOR_LOCKED: "对象已锁定，不能移动、缩放或删除",
}

# Accessible names match the toast unless a control needs a longer label.
ACCESSIBLE: dict[str, str] = {
    CONTINUE_EXPAND: COPY[CONTINUE_EXPAND],
    SAFETY_BOUNDS: COPY[SAFETY_BOUNDS],
    REARRANGED: COPY[REARRANGED],
    NO_LEGAL_LAYOUT: COPY[NO_LEGAL_LAYOUT],
    PLACED_CAP_TO_TRAY: COPY[PLACED_CAP_TO_TRAY],
    PLACED_CAP_STILL_UNPLACED: COPY[PLACED_CAP_STILL_UNPLACED],
    MEMBERSHIP_CAP: COPY[MEMBERSHIP_CAP],
    REMOVED_FROM_BOARD: COPY[REMOVED_FROM_BOARD],
    EXPORT_TOO_LARGE: COPY[EXPORT_TOO_LARGE],
    SEARCH_CAP: COPY[SEARCH_CAP],
    DISPLACED_OFFSCREEN: COPY[DISPLACED_OFFSCREEN],
    REMOVE_ACTION: COPY[REMOVE_ACTION],
    AUTHOR_LOCKED: COPY[AUTHOR_LOCKED],
}

REASON_TO_KEY: dict[LayoutRejectReason, str] = {
    LayoutRejectReason.OUT_OF_BOUNDS: SAFETY_BOUNDS,
    LayoutRejectReason.NO_LEGAL_LAYOUT: NO_LEGAL_LAYOUT,
    LayoutRejectReason.SPAN_INVARIANT: NO_LEGAL_LAYOUT,
    LayoutRejectReason.INVALID_INPUT: NO_LEGAL_LAYOUT,
    LayoutRejectReason.SEARCH_CAP: SEARCH_CAP,
}

HARD_REJECT_KEYS = frozenset(
    {
        SAFETY_BOUNDS,
        NO_LEGAL_LAYOUT,
        SEARCH_CAP,
        MEMBERSHIP_CAP,
        EXPORT_TOO_LARGE,
        DISPLACED_OFFSCREEN,
    }
)
SUCCESS_KEYS = frozenset(
    {REARRANGED, REMOVED_FROM_BOARD, PLACED_CAP_TO_TRAY, PLACED_CAP_STILL_UNPLACED}
)

HARD_REJECT_THROTTLE_S = 1.0

# widgets.py re-exports these aliases and maps reject reasons through
# text_for_reason. page.py / chrome / coordinator still have a few leftover
# membership-cap strings to rewire.
FEEDBACK_OUT_OF_GRID = COPY[SAFETY_BOUNDS]
FEEDBACK_NO_LEGAL_LAYOUT = COPY[NO_LEGAL_LAYOUT]
FEEDBACK_SEARCH_BUDGET = COPY[SEARCH_CAP]
FEEDBACK_REARRANGED = COPY[REARRANGED]
FEEDBACK_DISPLACED_OFFSCREEN = COPY[DISPLACED_OFFSCREEN]


def text_for_key(key: str, **kwargs: object) -> str:
    """Return the stable user-facing string for ``key``."""
    template = COPY[key]
    if kwargs:
        return template.format(**kwargs)
    return template


def accessible_for_key(key: str, **kwargs: object) -> str:
    """Return the accessible description for ``key`` (usually the toast text)."""
    template = ACCESSIBLE[key]
    if kwargs:
        return template.format(**kwargs)
    return template


def key_for_reason(reason: LayoutRejectReason | None) -> str:
    if reason is None:
        return NO_LEGAL_LAYOUT
    return REASON_TO_KEY.get(reason, NO_LEGAL_LAYOUT)


def text_for_reason(reason: LayoutRejectReason | None) -> str:
    """Map a planner reject reason onto the single copy table."""
    return text_for_key(key_for_reason(reason))


def format_rearranged(n: int) -> str:
    return text_for_key(REARRANGED, n=int(n))


def format_export_too_large(width: int, height: int) -> str:
    """Page/compositor call this when an export exceeds the safety ceiling."""
    return text_for_key(EXPORT_TOO_LARGE, width=int(width), height=int(height))


class FeedbackThrottle:
    """Pure gate for edge hints and hard-reject toasts.

    Callers own clocks: pass ``time.monotonic()`` (or a test double). Do not
    put a QTimer in this module.
    """

    def __init__(self) -> None:
        self._expand_gestures: set[Hashable] = set()
        self._last_hard_reject_at: dict[str, float] = {}

    def allow_continue_expand(self, gesture_id: Hashable) -> bool:
        """Edge continuation hint: once per gesture id."""
        if gesture_id in self._expand_gestures:
            return False
        self._expand_gestures.add(gesture_id)
        return True

    def end_gesture(self, gesture_id: Hashable) -> None:
        self._expand_gestures.discard(gesture_id)

    def allow_hard_reject(self, key: str, now: float) -> bool:
        """Same hard-reject key is suppressed within 1.0 s."""
        last = self._last_hard_reject_at.get(key)
        if last is not None and (now - last) < HARD_REJECT_THROTTLE_S:
            return False
        self._last_hard_reject_at[key] = float(now)
        return True

    def allow_success(self, key: str | None = None) -> bool:
        """A successful commit is always allowed immediately."""
        return True

    def allow(
        self,
        key: str,
        *,
        now: float,
        gesture_id: Hashable | None = None,
        success: bool = False,
    ) -> bool:
        if success or key in SUCCESS_KEYS:
            return self.allow_success(key)
        if key == CONTINUE_EXPAND:
            if gesture_id is None:
                return False
            return self.allow_continue_expand(gesture_id)
        return self.allow_hard_reject(key, now)
