"""Duplicate QSS selector ratchet — shrink-only.

Spec: ``docs/analyzer/specs/2026-08-15-qss-consolidation-spec.md`` §3.4.
Parser lives in ``tests/ui_kit/_qss_parse.py`` (shared with liveness).

A normalized selector (comma-split, whitespace collapsed) that appears in
two or more rule blocks must be on the whitelist with a one-sentence reason.
The whitelist may only shrink: a new duplicate not listed here fails, and a
listed selector that is no longer duplicated (or is gone from ``style.qss``)
fails so the table is trimmed.

Task 5 inventory (after Tasks 2–4): 44 selectors, 46 extra occurrences.
By HEAD ``350969f2`` (merge side-effect: another QSS change landed in the
same merge and pushed one more selector past the duplicate threshold) the
whitelist holds 45 entries; the assertion below compares against the live
table length rather than a hardcoded count, so this drift did not need a
test change — only this docstring note.
None were safe to merge under the spec's conservative rule (identical
bodies or a strict declaration subset, and no intervening rule that can
hit the same widget). Token neutralization makes ``{{CONTROL_ACCENT}}``
and ``{{CONTROL_ACCENT_HI}}`` look identical, comma groups would leak
properties onto siblings, and several later copies are documented
cascade (Frame seams Rule B, UltraView legacy / migration overlays).
"""
from __future__ import annotations

from tests.ui_kit._qss_parse import (
    duplicate_selector_counts,
    iter_qss_rule_blocks,
    normalize_selector,
    split_selector_list,
)

# Selector → one-sentence reason. THIS MAP MAY ONLY SHRINK.
ALLOWED_DUPLICATE_SELECTORS: dict[str, str] = {
    # Batch inline file manager: shared transparent fill, then widget chrome.
    "QListWidget#BatchFileList": (
        "共享透明底后接列表边框/内边距，声明互补"
    ),
    "QWidget#BatchStructuredFileRow": (
        "共享透明底后接行底部分隔线，声明互补"
    ),
    "QLabel#BatchFileEmptyState": (
        "共享透明底后接空态字色与顶部分隔，声明互补"
    ),
    "QPushButton#BatchFileAddLoaded": (
        "与 AddDisk 共享尺寸后接 loaded-source 强调色"
    ),
    "QPushButton#BatchFileRowRemove": (
        "rest 灰底后被透明覆盖，值冲突不是子集"
    ),
    # Role chrome: fill family then icon-only size.
    'QPushButton[role="icon"]': (
        "quiet/icon 共享透明填充后接 icon 专属尺寸"
    ),
    'QToolButton[role="icon"]': (
        "quiet/icon 共享透明填充后接 icon 专属尺寸"
    ),
    "QPushButton#liveFocusCollapseButton": (
        "与 prev/next 共享 live-focus 铬后接更安静的 collapse 色"
    ),
    "QPushButton#inspectorHelpLink QLabel#inspectorHelpMark": (
        "与 help text 共享字色后接 '?' 光学 padding"
    ),
    # Documented later restatement (Frame seams Rule B).
    "QWidget#viewTabBar": (
        "Frame seams 须后于 hint/dock 局部规则"
    ),
    "QFrame#chartHintBar": (
        "Frame seams 须后于 status/dock 局部规则"
    ),
    "QDialog#channelConfigHtmlImportDialog QComboBox": (
        "共享对话框字段铬后接 combo 家族 7px 圆角"
    ),
    "QLabel#channelConfigHtmlMissingChip": (
        "与 match chip 共享形态后接 missing 琥珀态"
    ),
    "QCheckBox#channelConfigHtmlCheck": (
        "与 check host/cell 共享透明底后接 20px 勾选几何"
    ),
    # UltraView: early page rules vs later canvas/island restyle.
    "QWidget#ultraViewPage": (
        "页底 #f2f4f7 后被 canvas-host 共享洗色覆盖"
    ),
    "QWidget#ultraViewBoardGrid": (
        "早期白底后被 canvas host 透明覆盖"
    ),
    "QWidget#ultraViewFreeGrid": (
        "早期白底后被 canvas host 透明覆盖"
    ),
    "QLabel#ultraViewAxisWarning": (
        "共享 meta 灰色后接 warning 琥珀覆盖"
    ),
    "QToolButton#ultraViewLibrarySectionHead": (
        "共享 meta 字色后接 section-head 按钮铬"
    ),
    "QFrame#ultraViewToolRail": (
        "共享 island 11px 圆角后接 rail 12px 覆盖"
    ),
    "QLabel#ultraViewStatusMessage": (
        "共享 island 标题字重后接 status 弱化字色"
    ),
    "QLabel#ultraViewNavZoomLabel": (
        "共享 island 标题字重后接等宽 zoom 标签"
    ),
    # UltraView card / empty-slot: first page block vs migration overlay.
    "QWidget#ultraViewCard": (
        "UltraView legacy 迁移期保留"
    ),
    'QWidget#ultraViewCard[selected="true"]': (
        "UltraView legacy 迁移期保留"
    ),
    'QWidget#ultraViewCard[replacementArmed="true"]': (
        "UltraView legacy 迁移期保留"
    ),
    'QWidget#ultraViewCard[orphaned="true"]': (
        "UltraView legacy 迁移期保留"
    ),
    'QWidget#ultraViewCard[dropActive="true"]': (
        "UltraView legacy 迁移期保留"
    ),
    "QWidget#ultraViewEmptySlot": (
        "UltraView legacy 迁移期保留"
    ),
    "QWidget#ultraViewEmptySlot:hover": (
        "UltraView legacy 迁移期保留"
    ),
    'QWidget#ultraViewEmptySlot[dropActive="true"]': (
        "UltraView legacy 迁移期保留"
    ),
    # Toolbar / compare / tray + zoom: explicit legacy overlay at file end.
    "QFrame#ultraViewBoardToolbar": (
        "UltraView legacy 迁移期保留"
    ),
    "QFrame#ultraViewCompareRail": (
        "UltraView legacy 迁移期保留"
    ),
    "QFrame#ultraViewUnplacedTray": (
        "UltraView legacy 迁移期保留"
    ),
    "QFrame#ultraViewCompareRail QPushButton#ultraViewCompareButton:checked": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewZoomOutButton": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewZoomInButton": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewZoomFitButton": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewZoomResetButton": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewZoomOutButton:hover": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewZoomInButton:hover": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewZoomFitButton:hover": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewZoomResetButton:hover": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewCardFocusButton": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewCardFocusButton:hover": (
        "UltraView legacy 迁移期保留"
    ),
    "QToolButton#ultraViewCardFocusButton:pressed": (
        "UltraView legacy 迁移期保留"
    ),
}


def test_duplicate_selectors_match_shrink_only_whitelist():
    found = duplicate_selector_counts()
    unexpected = sorted(set(found) - set(ALLOWED_DUPLICATE_SELECTORS))
    stale = sorted(set(ALLOWED_DUPLICATE_SELECTORS) - set(found))
    assert unexpected == [], (
        "new duplicate QSS selector(s) are not on the whitelist — classify "
        "as intentional cascade (add a one-sentence reason) or merge only "
        "when bodies are identical / a strict subset with no intervening "
        f"same-widget rule: {unexpected}"
    )
    assert stale == [], (
        "ALLOWED_DUPLICATE_SELECTORS has stale entries — the selector is "
        "no longer duplicated or is gone from style.qss; shrink the "
        f"whitelist, do not keep ghosts: {stale}"
    )


def test_whitelist_reasons_are_nonempty():
    empty = sorted(
        sel
        for sel, reason in ALLOWED_DUPLICATE_SELECTORS.items()
        if not str(reason).strip()
    )
    assert empty == [], (
        "whitelist reason must be a non-empty sentence, got blank for: "
        f"{empty}"
    )


def test_iter_blocks_neutralizes_tokens_before_brace_pairing():
    """``{{CONTROL_*}}`` double braces must not drop the next rule."""
    text = (
        "QLabel#frfSegmentChoice { color: {{CONTROL_ACCENT}}; }\n"
        "QLabel#chartHint { color: red; }\n"
    )
    blocks = list(iter_qss_rule_blocks(text))
    selectors = [split_selector_list(sel)[0] for sel, _body in blocks]
    assert selectors == ["QLabel#frfSegmentChoice", "QLabel#chartHint"]
    assert "__TOKEN__" in blocks[0][1]
    assert "{{" not in blocks[0][1]


def test_comma_lists_are_split_and_whitespace_normalized():
    text = (
        "QLabel#chartHint,   QLabel#chartHintBar { color: red; }\n"
        "QLabel#chartHint { color: blue; }\n"
    )
    found = duplicate_selector_counts(text)
    assert found == {"QLabel#chartHint": 2}
    assert normalize_selector("  QLabel#chartHint   QPushButton  ") == (
        "QLabel#chartHint QPushButton"
    )


def test_injected_duplicate_is_detected():
    """A second definition of a unique production selector must fail the lint."""
    from tests.ui_kit._qss_parse import load_style_qss

    probe = "QLabel#qssDupProbeTask5 { color: red; }\n"
    base = load_style_qss()
    once = duplicate_selector_counts(base + "\n" + probe)
    twice = duplicate_selector_counts(base + "\n" + probe + probe)
    assert "QLabel#qssDupProbeTask5" not in once
    assert twice.get("QLabel#qssDupProbeTask5") == 2
    assert "QLabel#qssDupProbeTask5" not in ALLOWED_DUPLICATE_SELECTORS


def test_gradient_stop_is_not_a_selector():
    text = """
    QPushButton {
        background-color: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 #ffffff, stop: 1 #eef2f7
        );
    }
    QPushButton { padding: 0; }
    """
    found = duplicate_selector_counts(text)
    assert found == {"QPushButton": 2}
    assert all("stop:" not in sel for sel in found)
