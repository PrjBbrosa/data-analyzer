"""Shared QSS text helpers for ui_kit selector lints.

Qt-free. Task 1 (objectName liveness) and Task 5 (duplicate-selector lint)
share this module so the two tests never drift onto separate parsers.

Pitfalls copied from spec §5.1 (2026-08-15-qss-consolidation-spec):

1. Prefix swallowing: a substring scan lets ``#chartHint`` match inside
   ``#chartHintBar``, and ``#channelConfigManager`` inside
   ``#channelConfigManagerHtml``. Extract full ``#objectName`` tokens with
   a word-boundary regex (the character after the name must not be
   ``[A-Za-z0-9_]``) and compare them as an exact set against Python
   string literals — never ``in``/substring.

2. Do **not** parse rule blocks by brace pairing. ``{{CONTROL_*}}`` /
   ``{{ICON_*}}`` double braces interrupt pairing and have already dropped
   a whole family (``frfSegmentChoice``) from an earlier inventory.
   Liveness scans selector text; Task 5 must neutralize tokens before any
   later ``selector { body }`` walk.

3. Hex colors such as ``#1769e0`` are not objectNames. Drop tokens that
   are pure hex and length 3, 6, or 8.

4. Before treating commas or ``stop:`` as selector syntax, strip comments
   and mask ``url(...)`` / Qt gradient parentheses. Otherwise
   ``qlineargradient``'s ``stop:`` is mistaken for a selector.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STYLE_QSS_PATH = REPO_ROOT / "mf4_analyzer" / "ui_kit" / "style.qss"
PACKAGE_ROOT = REPO_ROOT / "mf4_analyzer"

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_TOKEN_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
# Trailing ``[A-Za-z0-9_]*`` is greedy, so ``#chartHintBar`` yields
# ``chartHintBar`` rather than the prefix ``chartHint``.
_OBJECT_NAME_RE = re.compile(r"#([A-Za-z_][A-Za-z0-9_]*)")
_HEX_COLOR_RE = re.compile(r"^(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_MASK_CALL_RE = re.compile(
    r"(?:url|qlineargradient|qradialgradient|qconicalgradient)\s*\(",
    re.I,
)


def style_qss_path() -> Path:
    """Return the production ``style.qss`` path."""
    return STYLE_QSS_PATH


def load_style_qss() -> str:
    """Read ``mf4_analyzer/ui_kit/style.qss`` as UTF-8."""
    return STYLE_QSS_PATH.read_text(encoding="utf-8")


def strip_qss_comments(text: str) -> str:
    """Remove ``/* ... */`` comments (including the retired-name notes)."""
    return _COMMENT_RE.sub("", text)


def neutralize_qss_tokens(text: str) -> str:
    """Replace ``{{TOKEN}}`` so a later brace-pair walk is not interrupted.

    Liveness does not brace-pair; Task 5 should call this before splitting
    ``selector { body }``.
    """
    return _TOKEN_RE.sub("__TOKEN__", text)


def mask_qss_url_and_gradient_parens(text: str) -> str:
    """Replace ``url(...)`` and Qt gradient calls with a placeholder.

    Inner commas and ``stop:`` must not participate in selector splitting.
    Nested parentheses and quoted strings inside the call are respected.
    """
    out: list[str] = []
    i = 0
    while True:
        match = _MASK_CALL_RE.search(text, i)
        if match is None:
            out.append(text[i:])
            break
        out.append(text[i:match.start()])
        close_at = _closing_paren_index(text, match.end() - 1)
        out.append("__MASKED_CALL__")
        i = len(text) if close_at is None else close_at + 1
    return "".join(out)


def prepare_qss_selector_text(text: str | None = None) -> str:
    """Strip comments, neutralize ``{{TOKEN}}``, mask url/gradient calls.

    This is the shared preprocessing step for selector-list work (Task 5)
    and a safe input for objectName extraction.
    """
    if text is None:
        text = load_style_qss()
    text = strip_qss_comments(text)
    text = neutralize_qss_tokens(text)
    return mask_qss_url_and_gradient_parens(text)


def normalize_selector(selector: str) -> str:
    """Collapse runs of whitespace. Empty input stays empty."""
    return " ".join(selector.split())


def split_selector_list(selector_text: str) -> list[str]:
    """Comma-split a selector list and normalize each item.

    Caller must already have masked ``url(...)`` / gradient parentheses;
    otherwise commas inside those calls split the list.
    """
    return [
        sel
        for raw in selector_text.split(",")
        if (sel := normalize_selector(raw))
    ]


# Safe only after :func:`prepare_qss_selector_text`: ``{{TOKEN}}`` double
# braces would otherwise interrupt pairing (spec §5.1). Nested QSS blocks
# do not occur in this sheet.
_BLOCK_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)


def iter_qss_rule_blocks(text: str | None = None) -> Iterator[tuple[str, str]]:
    """Yield ``(selector_text, body)`` after shared preprocessing.

    Always runs :func:`prepare_qss_selector_text` first so ``{{CONTROL_*}}``
    / ``{{ICON_*}}`` cannot break the ``selector { body }`` walk.
    """
    prepared = prepare_qss_selector_text(text)
    for match in _BLOCK_RE.finditer(prepared):
        selector = match.group(1).strip()
        if selector:
            yield selector, match.group(2)


def duplicate_selector_counts(text: str | None = None) -> dict[str, int]:
    """Normalized selectors that appear in two or more rule blocks.

    A comma list contributes one count per item. Whitespace is collapsed
    via :func:`normalize_selector` so ``QLabel#a,  QLabel#b`` matches
    a later ``QLabel#a``.
    """
    counts: dict[str, int] = {}
    for selector_text, _body in iter_qss_rule_blocks(text):
        for sel in split_selector_list(selector_text):
            counts[sel] = counts.get(sel, 0) + 1
    return {sel: n for sel, n in counts.items() if n >= 2}


def is_hex_color_token(name: str) -> bool:
    """True when ``name`` is a CSS hex color without the leading ``#``."""
    return _HEX_COLOR_RE.fullmatch(name) is not None


def extract_qss_object_names(text: str | None = None) -> frozenset[str]:
    """Return distinct ``#objectName`` ids from QSS selector text.

    Scans the text; does not parse by brace pairing. Comments are stripped
    first so a name that lives only in a comment is not a selector.
    Pure-hex tokens of length 3/6/8 are dropped.
    """
    if text is None:
        text = load_style_qss()
    text = strip_qss_comments(text)
    names: set[str] = set()
    for match in _OBJECT_NAME_RE.finditer(text):
        name = match.group(1)
        if is_hex_color_token(name):
            continue
        names.add(name)
    return frozenset(names)


def iter_python_string_literals(source: str, filename: str = "<qss>") -> Iterator[str]:
    """Yield string literals from ``source`` via AST.

    Covers ``setObjectName("foo")`` constants and the constant fragments
    of f-strings. Dynamic f-string parts are **not** reconstructed —
    those names belong on the DYNAMIC whitelist.
    """
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def collect_production_string_literals(
    package_root: Path | None = None,
) -> frozenset[str]:
    """Exact string literals in ``mf4_analyzer/**/*.py``.

    ``tests/`` is outside this tree and must not count as a production
    hit — including absence assertions that mention a retired name.
    """
    root = package_root or PACKAGE_ROOT
    literals: set[str] = set()
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            literals.update(iter_python_string_literals(source, filename=str(path)))
        except SyntaxError:
            continue
    return frozenset(literals)


def dead_qss_object_names(
    qss_text: str | None = None,
    *,
    production_literals: frozenset[str] | None = None,
) -> frozenset[str]:
    """QSS objectNames with no exact production string-literal hit."""
    names = extract_qss_object_names(qss_text)
    literals = (
        collect_production_string_literals()
        if production_literals is None
        else production_literals
    )
    return frozenset(name for name in names if name not in literals)


def _closing_paren_index(text: str, open_at: int) -> int | None:
    """Index of the ``)`` matching ``text[open_at] == '('``, or None."""
    depth = 0
    in_str: str | None = None
    i = open_at
    while i < len(text):
        ch = text[i]
        if in_str is not None:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in {'"', "'"}:
            in_str = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None
