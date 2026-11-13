"""changeEvent must not watch window activation.

QEvent.WindowActivate and QEvent.WindowDeactivate are delivered to
``event()`` on the top-level window. They do not arrive via
``changeEvent``, so a comparison there is dead code.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.static_source

_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "mf4_analyzer"
_ACTIVATION_NAMES = frozenset({"WindowActivate", "WindowDeactivate"})


def _is_activation_token(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and node.attr in _ACTIVATION_NAMES:
        return True
    if isinstance(node, ast.Constant) and node.value in _ACTIVATION_NAMES:
        return True
    return False


def _compare_mentions_activation(node: ast.Compare) -> bool:
    return any(_is_activation_token(child) for child in ast.walk(node))


def _changeevent_activation_lines(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "changeEvent":
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Compare) and _compare_mentions_activation(child):
                lines.append(child.lineno)
    return sorted(set(lines))


def _package_hits() -> list[str]:
    hits: list[str] = []
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line in _changeevent_activation_lines(tree):
            relative = path.relative_to(_PACKAGE_ROOT.parent)
            hits.append(f"{relative}:{line}")
    return hits


def test_changeevent_does_not_compare_window_activation():
    assert _package_hits() == []


def test_scanner_flags_changeevent_activation_and_ignores_event():
    deactivated = ast.parse(
        "def changeEvent(self, event):\n"
        "    if event.type() == QEvent.WindowDeactivate:\n"
        "        pass\n"
    )
    assert _changeevent_activation_lines(deactivated) == [2]

    named = ast.parse(
        "def changeEvent(self, event):\n"
        "    if event.type() in (QEvent.WindowActivate, QEvent.FontChange):\n"
        "        pass\n"
    )
    assert _changeevent_activation_lines(named) == [2]

    as_text = ast.parse(
        "def changeEvent(self, event):\n"
        "    if name == 'WindowDeactivate':\n"
        "        pass\n"
    )
    assert _changeevent_activation_lines(as_text) == [2]

    allowed = ast.parse(
        "def event(self, event):\n"
        "    if event.type() == QEvent.WindowDeactivate:\n"
        "        pass\n"
        "def changeEvent(self, event):\n"
        "    if event.type() == QEvent.FontChange:\n"
        "        pass\n"
    )
    assert _changeevent_activation_lines(allowed) == []
