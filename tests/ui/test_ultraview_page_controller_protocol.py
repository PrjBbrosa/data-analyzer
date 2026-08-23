"""Shrink-only AST guard: UltraViewPage uses explicit collaborator protocol.

Page may compose ViewportController, PointerRouter, BoardContextController,
AuthorUiController, and FloatingChromeController. It must not read or write
their private members, expand its instance surface by setattr of router
methods, or rely on a reflection-generated FORWARDED_METHODS list.

The allowed private-access set is empty and may only stay empty.
"""
from __future__ import annotations

import ast
from pathlib import Path


ULTRAVIEW_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
)
PAGE_PATH = ULTRAVIEW_ROOT / "page.py"
BOARD_POINTER_PATH = ULTRAVIEW_ROOT / "board_pointer.py"

COLLABORATOR_ATTRS = frozenset(
    {
        "_viewport_ctrl",
        "_pointer_router",
        "_board_context",
        "_author_ui",
        "_floating_chrome",
    }
)
COLLABORATOR_PUBLIC_GETTERS = frozenset({"pointer_router"})
REFLECT_NAMES = frozenset({"vars", "dir", "inspect", "getmembers"})


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _callee_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def _is_private_attr(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _is_collaborator_value(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute) and node.attr in COLLABORATOR_ATTRS:
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr in COLLABORATOR_ATTRS | COLLABORATOR_PUBLIC_GETTERS
    return False


def _collaborator_owner_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _callee_name(node)
    return ""


def _page_collaborator_private_accesses() -> list[tuple[int, str, str]]:
    tree = _parse(PAGE_PATH)
    hits: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_private_attr(node.attr):
            if _is_collaborator_value(node.value):
                hits.append((node.lineno, _collaborator_owner_name(node.value), node.attr))
            continue
        if not isinstance(node, ast.Call) or _callee_name(node) != "getattr":
            continue
        if len(node.args) < 2:
            continue
        attr = node.args[1]
        if not (isinstance(attr, ast.Constant) and isinstance(attr.value, str)):
            continue
        if not _is_private_attr(attr.value):
            continue
        if _is_collaborator_value(node.args[0]):
            hits.append(
                (node.lineno, _collaborator_owner_name(node.args[0]), attr.value)
            )
    return hits


def _page_setattr_router_expansions() -> list[int]:
    tree = _parse(PAGE_PATH)
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _callee_name(node) != "setattr":
            continue
        if len(node.args) < 3:
            continue
        target = node.args[0]
        value = node.args[2]
        if not (isinstance(target, ast.Name) and target.id == "self"):
            continue
        if not isinstance(value, ast.Call) or _callee_name(value) != "getattr":
            continue
        hits.append(node.lineno)
    return hits


def _is_forwarded_methods_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Name) and node.id == "FORWARDED_METHODS":
        return True
    return isinstance(node, ast.Attribute) and node.attr == "FORWARDED_METHODS"


def _assignment_targets(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign) and node.target is not None:
        return [node.target]
    return []


def _forwarded_methods_reflection_lines() -> list[int]:
    tree = _parse(BOARD_POINTER_PATH)
    hits: list[int] = []
    for node in ast.walk(tree):
        targets = _assignment_targets(node)
        if not targets or not any(_is_forwarded_methods_target(item) for item in targets):
            continue
        value = getattr(node, "value", None)
        if value is None:
            continue
        for child in ast.walk(value):
            if isinstance(child, ast.Name) and child.id in REFLECT_NAMES:
                hits.append(node.lineno)
                break
            if isinstance(child, ast.Attribute) and child.attr in REFLECT_NAMES:
                hits.append(node.lineno)
                break
            if isinstance(child, ast.Call) and _callee_name(child) in REFLECT_NAMES:
                hits.append(node.lineno)
                break
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _callee_name(node) != "setattr":
            continue
        if len(node.args) < 2:
            continue
        name = node.args[1]
        if (
            isinstance(name, ast.Constant)
            and name.value == "FORWARDED_METHODS"
        ):
            value = node.args[2] if len(node.args) > 2 else None
            if value is None:
                hits.append(node.lineno)
                continue
            for child in ast.walk(value):
                if isinstance(child, ast.Name) and child.id in REFLECT_NAMES:
                    hits.append(node.lineno)
                    break
                if isinstance(child, ast.Attribute) and child.attr in REFLECT_NAMES:
                    hits.append(node.lineno)
                    break
                if isinstance(child, ast.Call) and _callee_name(child) in REFLECT_NAMES:
                    hits.append(node.lineno)
                    break
    return hits


def test_page_does_not_access_collaborator_privates():
    hits = _page_collaborator_private_accesses()
    assert hits == [], (
        "UltraViewPage must use public collaborator facts/commands; "
        f"private accesses: {hits}"
    )


def test_page_does_not_setattr_router_methods():
    hits = _page_setattr_router_expansions()
    source = PAGE_PATH.read_text(encoding="utf-8")
    assert hits == [], f"setattr(self, ..., getattr(router...)) at lines {hits}"
    assert "setattr(self, name, getattr(router, name))" not in source


def test_pointer_router_does_not_reflect_forwarded_methods():
    hits = _forwarded_methods_reflection_lines()
    assert hits == [], (
        "PointerRouter.FORWARDED_METHODS must not be collected via "
        f"vars/dir/inspect; lines {hits}"
    )
