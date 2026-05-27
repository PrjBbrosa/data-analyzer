from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (ROOT / "can_logger", ROOT / "mf4_analyzer")
FORBIDDEN = {"pya2l", "pyxcp"}
PYA2L_ALLOWED = {
    (Path("can_logger/p0/a2l_probe.py"), "_load_measurement_summary_inprocess"),
}


def _function_stack(tree: ast.AST) -> dict[ast.AST, tuple[str, ...]]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    stacks: dict[ast.AST, tuple[str, ...]] = {}
    for node in ast.walk(tree):
        names: list[str] = []
        cur = parents.get(node)
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.append(cur.name)
            cur = parents.get(cur)
        stacks[node] = tuple(reversed(names))
    return stacks


def _is_allowed_static_import(
    rel: Path,
    func: str | None,
    module: str,
) -> bool:
    return module == "pya2l" and (rel, func) in PYA2L_ALLOWED


def test_native_dependencies_have_no_unapproved_static_imports():
    violations: list[str] = []

    for root in SCAN_ROOTS:
        for path in root.rglob("*.py"):
            rel = path.relative_to(ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(rel))
            stacks = _function_stack(tree)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name.split(".")[0]
                        func = stacks[node][-1] if stacks[node] else None
                        if module in FORBIDDEN and not _is_allowed_static_import(
                            rel, func, module
                        ):
                            violations.append(f"{rel}:{node.lineno} import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    module = node.module.split(".")[0]
                    func = stacks[node][-1] if stacks[node] else None
                    if module in FORBIDDEN and not _is_allowed_static_import(
                        rel, func, module
                    ):
                        violations.append(f"{rel}:{node.lineno} from {node.module}")

    assert not violations, "\n".join(violations)
