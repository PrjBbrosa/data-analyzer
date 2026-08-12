"""State-rule ``border:`` shorthand must not silently zero ``border-radius``.

Qt stylesheet cascade is **not** CSS: when a more specific rule redeclares the
``border:`` shorthand and omits ``border-radius``, the radius resets to 0 for
that rule — measured in ``f4a6b923`` (combo drop-down) and catalogued as E2 in
the 2026-08-12 guideline-hardening review. Team convention is to change only
``border-color`` / ``border-width`` / ``border-style`` in state rules, or to
restate ``border-radius`` when a shorthand is unavoidable.

This lint freezes the empty-violation set. The whitelist may only **shrink**.
"""
from __future__ import annotations

import re
from pathlib import Path

_QSS_PATH = (
    Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui_kit" / "style.qss"
)

# Frozen at Task 14 (E2). THIS SET MAY ONLY SHRINK — a new entry means a state
# rule reintroduced ``border:`` shorthand over a radius-bearing baseline.
ALLOWED_BORDER_SHORTHAND_STATE_RULES: frozenset[str] = frozenset()

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_TOKEN_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_STATE_PSEUDO_RE = re.compile(
    r":(?:hover|pressed|checked|disabled|focus|selected|active|enabled|"
    r"indeterminate)\b"
)
_ATTR_RE = re.compile(r"\[[^\]]+\]")
_BORDER_SHORTHAND_RE = re.compile(r"(?<![\w-])border\s*:\s*([^;]+)")
_HAS_RADIUS_RE = re.compile(r"(?<![\w-])border-radius\s*:")


def _norm(sel: str) -> str:
    return " ".join(sel.split())


def _is_state_selector(sel: str) -> bool:
    """Pseudo-classes and ``[attr]`` count as state (spec E2)."""
    return bool(_STATE_PSEUDO_RE.search(sel) or _ATTR_RE.search(sel))


def _strip_states(sel: str) -> list[str]:
    """Peel trailing ``:pseudo`` / ``[attr]`` to produce baseline candidates."""
    out: list[str] = []
    cur = sel
    while True:
        out.append(cur)
        m = re.search(
            r"^(.*?)(?<![:]):(?:hover|pressed|checked|disabled|focus|selected|"
            r"active|enabled|indeterminate)$",
            cur,
        )
        if m:
            cur = m.group(1)
            continue
        m = re.search(r"^(.*)(\[[^\]]+\])$", cur)
        if m:
            cur = m.group(1)
            continue
        break
    # Unique, order-preserving.
    return list(dict.fromkeys(out))


def _parse_sheet() -> str:
    """Comments out; neutralize ``{{TOKEN}}`` so ``{``/``}`` block parsing works."""
    text = _COMMENT_RE.sub("", _QSS_PATH.read_text(encoding="utf-8"))
    return _TOKEN_RE.sub("__TOKEN__", text)


def _baseline_radius_selectors(text: str) -> set[str]:
    found: set[str] = set()
    for sels, body in _BLOCK_RE.findall(text):
        if not _HAS_RADIUS_RE.search(body):
            continue
        for raw in sels.split(","):
            sel = _norm(raw)
            if sel:
                found.add(sel)
    return found


def _match_baseline(sel: str, baselines: set[str]) -> str | None:
    cands = _strip_states(sel)
    for cand in cands[1:]:
        if cand in baselines:
            return cand
    bare = cands[-1]
    if bare in baselines:
        return bare
    last = bare.split()[-1]
    if last in baselines:
        return last
    return None


def find_border_shorthand_state_violations() -> list[tuple[str, str, str]]:
    """Return ``(selector, border_value, baseline_selector)`` violations."""
    text = _parse_sheet()
    baselines = _baseline_radius_selectors(text)
    violations: list[tuple[str, str, str]] = []
    for sels, body in _BLOCK_RE.findall(text):
        shorthand = _BORDER_SHORTHAND_RE.search(body)
        if not shorthand:
            continue
        # Restating radius alongside shorthand is the approved escape hatch
        # (see autoAttachFiles / combo item:selected).
        if _HAS_RADIUS_RE.search(body):
            continue
        for raw in sels.split(","):
            sel = _norm(raw)
            if not sel or not _is_state_selector(sel):
                continue
            baseline = _match_baseline(sel, baselines)
            if baseline is None:
                continue
            violations.append((sel, shorthand.group(1).strip(), baseline))
    return violations


def test_state_border_shorthand_whitelist_is_honored():
    violations = find_border_shorthand_state_violations()
    found = {sel for sel, _val, _base in violations}
    unexpected = sorted(found - ALLOWED_BORDER_SHORTHAND_STATE_RULES)
    stale = sorted(ALLOWED_BORDER_SHORTHAND_STATE_RULES - found)
    assert unexpected == [], (
        "state rule(s) use border: shorthand over a radius-bearing baseline "
        f"without restating border-radius (fix with border-color/width/style, "
        f"or restate radius): {unexpected}"
    )
    assert stale == [], (
        "ALLOWED_BORDER_SHORTHAND_STATE_RULES has stale entries — shrink the "
        f"whitelist, do not keep ghosts: {stale}"
    )


def test_channel_tree_selected_restates_border_radius():
    """E1: opaque selected fill must carry its own radius (parent 9 − border 1)."""
    text = _parse_sheet()
    item_radius = None
    branch_radius = None
    for sels, body in _BLOCK_RE.findall(text):
        for raw in sels.split(","):
            sel = _norm(raw)
            if sel == "QTreeWidget#channelTree::item:selected":
                m = re.search(r"(?<![\w-])border-radius\s*:\s*(\d+)px", body)
                item_radius = int(m.group(1)) if m else None
            if sel == "QTreeWidget#channelTree::branch:selected":
                m = re.search(r"(?<![\w-])border-radius\s*:\s*(\d+)px", body)
                branch_radius = int(m.group(1)) if m else None
    assert item_radius in {6, 8}, (
        f"channelTree::item:selected must declare border-radius 6 or 8 "
        f"(parent 9 − border 1), got {item_radius!r}"
    )
    assert branch_radius == item_radius, (
        f"branch:selected radius {branch_radius!r} must match item:selected "
        f"{item_radius!r}"
    )
