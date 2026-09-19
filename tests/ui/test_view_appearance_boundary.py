"""T5 ratchet: View appearance callers must not read canvas private structure."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_WINDOW_ROOT = REPO_ROOT / "mf4_analyzer" / "ui" / "main_window"
VIEW_MIXIN_PATH = MAIN_WINDOW_ROOT / "_view_mixin.py"

FORBIDDEN_CANVAS_FIELDS = frozenset({
    "_companion_source",
    "_channel_lines",
    "_channel_data_id",
    "_x_master_handle",
    "_overlay_mode",
    "_primary_xaxis_ax",
    "_inside_label_items",
    "_inside_label_handles",
    "_companion_names",
})

APPEARANCE_CHAIN_ROOTS = frozenset({
    "_connect_channel_color_sync",
    "_on_canvas_appearance_color_changed",
    "_on_canvas_channel_color_changed",
    "_resolve_companion_source_key",
    "_store_companion_color_override",
    "_on_canvas_chart_options_applied",
    "_capture_chart_appearance_from_handle",
    "_sync_custom_x_label_from_handle",
    "_handle_owns_time_xlabel",
    "_appearance_key_for_handle",
    "_apply_view_chart_appearance",
    "_repair_log_axis_ranges",
    "_autoscale_log_axis_if_invalid",
    "_hide_inside_labels_for_handle",
})

FACADE_METHODS = frozenset({
    "appearance_target_for_handle",
    "companion_source_key",
    "snapshot_chart_appearance",
    "apply_chart_appearance",
    "repair_chart_appearance_ranges",
    "appearance_color_changed",
})


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _class_def(tree: ast.AST, name: str) -> ast.ClassDef:
    for node in tree.body if isinstance(tree, ast.Module) else ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"class {name} not found")


def _function_map(class_node: ast.ClassDef) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef)
    }


def _self_method_calls(func: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if (
            isinstance(callee, ast.Attribute)
            and isinstance(callee.value, ast.Name)
            and callee.value.id == "self"
        ):
            names.add(callee.attr)
    return names


def _appearance_chain_functions() -> dict[str, ast.FunctionDef]:
    tree = _parse(VIEW_MIXIN_PATH)
    mixin = _class_def(tree, "ViewMixin")
    functions = _function_map(mixin)
    pending = set(APPEARANCE_CHAIN_ROOTS & functions.keys())
    chain: dict[str, ast.FunctionDef] = {}
    while pending:
        name = pending.pop()
        if name in chain:
            continue
        func = functions.get(name)
        if func is None:
            continue
        chain[name] = func
        for callee in _self_method_calls(func):
            if callee in functions and callee not in chain:
                pending.add(callee)
    return chain


def _forbidden_hits(func: ast.AST) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CANVAS_FIELDS:
            hits.append(node.attr)
        elif isinstance(node, ast.Constant) and node.value in FORBIDDEN_CANVAS_FIELDS:
            hits.append(str(node.value))
        elif isinstance(node, ast.Call):
            callee = node.func
            is_getattr = (
                (isinstance(callee, ast.Name) and callee.id == "getattr")
                or (isinstance(callee, ast.Attribute) and callee.attr == "getattr")
            )
            if not is_getattr or len(node.args) < 2:
                continue
            attr = node.args[1]
            if isinstance(attr, ast.Constant) and attr.value in FORBIDDEN_CANVAS_FIELDS:
                hits.append(str(attr.value))
    return hits


def test_appearance_chain_does_not_read_canvas_private_fields():
    chain = _appearance_chain_functions()
    assert chain, "appearance call chain was empty"
    leftover: dict[str, list[str]] = {}
    for name, func in chain.items():
        hits = _forbidden_hits(func)
        if hits:
            leftover[name] = sorted(set(hits))
    assert leftover == {}, leftover


def test_appearance_methods_were_not_moved_to_another_mixin():
    defined_elsewhere: dict[str, list[str]] = {}
    for path in sorted(MAIN_WINDOW_ROOT.glob("*.py")):
        if path.name == "_view_mixin.py":
            continue
        tree = _parse(path)
        names = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name in APPEARANCE_CHAIN_ROOTS
        }
        if names:
            defined_elsewhere[path.name] = sorted(names)
    assert defined_elsewhere == {}, defined_elsewhere


def test_appearance_chain_uses_canvas_facade_and_typed_color_signal():
    chain = _appearance_chain_functions()
    names_used: set[str] = set()
    connected_signals: set[str] = set()
    for func in chain.values():
        for node in ast.walk(func):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                names_used.add(node.value)
            if isinstance(node, ast.Attribute):
                names_used.add(node.attr)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
            ):
                value = node.args[1].value
                if value in {
                    "appearance_color_changed",
                    "channel_color_changed",
                }:
                    connected_signals.add(str(value))
    missing = sorted(FACADE_METHODS - names_used)
    assert missing == [], missing
    assert "appearance_color_changed" in connected_signals
    assert "channel_color_changed" not in connected_signals


def test_appearance_chain_does_not_guess_display_prefix():
    chain = _appearance_chain_functions()
    for name, func in chain.items():
        text = ast.dump(func)
        assert 'startswith' not in text, name
        source = ast.unparse(func)
        assert '{prefixed} (' not in source, name
        assert 'prefixed} (' not in source, name


def test_canvas_appearance_calls_do_not_pass_window_self():
    chain = _appearance_chain_functions()
    facade_names = {
        "appearance_target_for_handle",
        "companion_source_key",
        "snapshot_chart_appearance",
        "apply_chart_appearance",
        "repair_chart_appearance_ranges",
    }
    for name, func in chain.items():
        for node in ast.walk(func):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            called = None
            if isinstance(callee, ast.Attribute) and callee.attr in facade_names:
                called = callee.attr
            elif isinstance(callee, ast.Name) and callee.id.endswith("_fn"):
                called = callee.id
            if not node.args:
                continue
            first = node.args[0]
            if (
                isinstance(first, ast.Name)
                and first.id == "self"
                and called is not None
            ):
                raise AssertionError(
                    f"{name} passes self into canvas appearance call {called}"
                )
            if (
                isinstance(first, ast.Name)
                and first.id == "self"
                and isinstance(callee, ast.Name)
                and callee.id in {"apply_fn", "repair_fn", "snapshot_fn", "target_fn", "resolver"}
            ):
                raise AssertionError(
                    f"{name} passes self into {callee.id}"
                )
